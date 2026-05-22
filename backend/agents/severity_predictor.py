"""
Severity & evolution predictor — LlmAgent estimating impact of classified crises.

Reads ``temp:classified_clusters`` (+ ``temp:fused_clusters`` for context), integrates
DS-002 weather via tool_use, call_llm for severity reasoning, writes
``temp:severity_records``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import (
    CityConfig,
    ClusterClassification,
    SeverityPredictionResult,
    SeverityRecord,
    SignalCluster,
)

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATHS = (
    PROJECT_ROOT / "mock_data" / "ciro_all_datasets.json",
    PROJECT_ROOT / "mock_data" / "ciro_datasets.json",
)

URDU_RULE = (
    "Input may be Urdu, Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

_ENVIRONMENTAL_CRISIS_TYPES = frozenset(
    {
        "urban_flood",
        "heatwave",
        "power_outage",
        "fire",
        "water_main_burst",
    }
)

_SEVERITY_TABLE: dict[int, tuple[str, str]] = {
    1: ("Minimal", "Monitor only"),
    2: ("Low", "Dispatch team"),
    3: ("Moderate", "Coordinate"),
    4: ("High", "Full mobilization"),
    5: ("Critical", "Emergency declaration"),
}

_DB: Optional[dict[str, Any]] = None


def _emit_trace(thought: str, observation: str, action: str) -> None:
    print(f"[THOUGHT] {thought}")
    print(f"[OBSERVATION] {observation}")
    print(f"[ACTION] {action}")


def _load_db() -> dict[str, Any]:
    global _DB
    if _DB is not None:
        return _DB
    for path in DATASET_PATHS:
        if path.is_file():
            with path.open(encoding="utf-8") as f:
                _DB = json.load(f)["ciro_datasets"]
            return _DB
    raise FileNotFoundError("Dataset file not found under mock_data/")


def _parse_classifications(raw: Any) -> list[ClusterClassification]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [
        c if isinstance(c, ClusterClassification) else ClusterClassification.model_validate(c)
        for c in raw
    ]


def _parse_fused_clusters(raw: Any) -> dict[str, SignalCluster]:
    if not raw:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    clusters = [
        c if isinstance(c, SignalCluster) else SignalCluster.model_validate(c)
        for c in raw
    ]
    return {c.cluster_id: c for c in clusters}


def _get_phase(tool_context: ToolContext) -> str:
    raw = tool_context.state.get("city_config")
    if isinstance(raw, dict):
        return raw.get("phase", "T1_during")
    if isinstance(raw, CityConfig):
        return raw.phase
    return "T1_during"


def _lookup_zone(city: str, zone: Optional[str]) -> dict[str, Any]:
    zones = _load_db().get("DS-005", {}).get("zones", [])
    if zone:
        zone_l = zone.strip().lower()
        for z in zones:
            if z.get("city", "").lower() != city.lower():
                continue
            names = {z.get("zone_name", "").lower(), *[
                a.lower() for a in (z.get("zone_alias") or [])
            ]}
            if zone_l in names or any(zone_l in n or n in zone_l for n in names if n):
                return z
    for z in zones:
        if z.get("city", "").lower() == city.lower():
            return z
    return {"population_estimate": 10000, "area_sq_km": 5.0}


def _fetch_weather_snapshot(city: str, phase: str) -> Optional[dict[str, Any]]:
    snapshots_root = _load_db().get("DS-002", {}).get("snapshots", {})
    for _scenario_id, phases in snapshots_root.items():
        snap = phases.get(phase) or phases.get("T1_during")
        if snap and snap.get("city", "").lower() == city.lower():
            return snap
    return None


def _exposure_fraction(crisis_type: str, weather: Optional[dict[str, Any]]) -> float:
    base = {
        "urban_flood": 0.25,
        "heatwave": 0.20,
        "traffic_accident": 0.03,
        "public_disorder": 0.08,
        "power_outage": 0.18,
        "infrastructure_failure": 0.12,
        "disease_cluster": 0.10,
        "fire": 0.15,
        "water_main_burst": 0.14,
    }.get(crisis_type, 0.08)

    if not weather:
        return base

    if crisis_type == "urban_flood":
        flood_risk = weather.get("flood_risk_score", 0.5)
        return min(0.55, base + flood_risk * 0.3)
    if crisis_type == "heatwave":
        temp = weather.get("temperature_c", 35)
        return min(0.45, base + max(0, temp - 38) * 0.02)
    if crisis_type == "power_outage" and weather.get("power_grid_stress"):
        return min(0.40, base + 0.15)
    return base


def _severity_level(
    population_at_risk: int,
    crisis_type: str,
    cluster: Optional[SignalCluster],
    weather: Optional[dict[str, Any]],
) -> int:
    critical_infra = crisis_type in (
        "power_outage",
        "infrastructure_failure",
        "water_main_burst",
    )
    cascading = False
    if cluster:
        flags = cluster.metadata.get("suspicious_flags", [])
        cascading = cluster.hypothesis_diversity_flag or "SOURCE_CONFLICT" in flags
    if weather and weather.get("threshold_breached") and crisis_type == "urban_flood":
        cascading = True

    if population_at_risk >= 10_000:
        level = 5
    elif population_at_risk >= 2_000 or (critical_infra and population_at_risk >= 800):
        level = 4
    elif population_at_risk >= 500:
        level = 3
    elif population_at_risk >= 100:
        level = 2
    else:
        level = 1

    if cascading:
        if population_at_risk >= 500:
            level = max(level, 5)
        else:
            level = max(level, 3)
    return level


def _radius_km(level: int, area_sq_km: float, signal_count: int) -> float:
    base = {1: 0.3, 2: 0.8, 3: 1.5, 4: 3.0, 5: 5.0}.get(level, 1.0)
    return round(min(base, max(0.5, area_sq_km**0.5 * 0.4 + signal_count * 0.1)), 2)


def _duration_hours(crisis_type: str, weather: Optional[dict[str, Any]], level: int) -> float:
    defaults = {
        "urban_flood": 6.0,
        "heatwave": 8.0,
        "traffic_accident": 3.0,
        "public_disorder": 5.0,
        "power_outage": 4.0,
        "fire": 4.0,
        "water_main_burst": 6.0,
    }
    hours = defaults.get(crisis_type, 4.0)
    if weather and crisis_type == "urban_flood":
        hours = 8.0 if weather.get("rainfall_mm_per_hour", 0) > 30 else 5.0
    return hours + (level - 3) * 0.5 if level > 3 else hours


def _spread_risk(
    crisis_type: str,
    cluster: Optional[SignalCluster],
    weather: Optional[dict[str, Any]],
    level: int,
) -> float:
    score = 0.15 + level * 0.08
    if cluster:
        score += cluster.mention_velocity * 0.25
        if cluster.hypothesis_diversity_flag:
            score += 0.15
    if weather:
        if crisis_type == "urban_flood":
            score += float(weather.get("flood_risk_score", 0)) * 0.35
        if crisis_type == "heatwave":
            score += min(0.25, max(0, float(weather.get("heat_index_c", 40)) - 40) * 0.02)
        if weather.get("power_grid_stress"):
            score += 0.12
    return round(min(1.0, score), 3)


def predict_severity_heuristic(
    classification: ClusterClassification,
    cluster: Optional[SignalCluster],
    weather: Optional[dict[str, Any]],
) -> SeverityRecord:
    """Deterministic severity estimate when LLM output is unavailable."""
    city = cluster.city if cluster else "Unknown"
    zone = classification.location.zone or (cluster.zone if cluster else None)
    zone_data = _lookup_zone(city, zone)
    zone_pop = int(zone_data.get("population_estimate", 10_000))
    area_sq_km = float(zone_data.get("area_sq_km", 5.0))

    crisis_type = classification.primary_classification
    exposure = _exposure_fraction(crisis_type, weather)
    signal_boost = min(0.15, (len(cluster.signals) if cluster else 1) * 0.02)
    population_at_risk = max(
        50,
        int(zone_pop * (exposure + signal_boost) * classification.confidence),
    )

    level = _severity_level(population_at_risk, crisis_type, cluster, weather)
    label, priority = _SEVERITY_TABLE[level]
    p10 = max(0, int(population_at_risk * 0.7))
    p90 = int(population_at_risk * 1.35)

    now = datetime.now(timezone.utc)
    if weather and weather.get("timestamp"):
        try:
            base_ts = datetime.fromisoformat(weather["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            base_ts = now
    else:
        base_ts = now
    peak_eta = base_ts + timedelta(hours=1 if level <= 2 else 2 if level <= 4 else 3)

    env_factors: dict[str, Any] = {}
    if weather:
        env_factors = {
            "alert_level": weather.get("alert_level"),
            "agent_trigger": weather.get("agent_trigger"),
            "rainfall_mm_per_hour": weather.get("rainfall_mm_per_hour"),
            "temperature_c": weather.get("temperature_c"),
            "flood_risk_score": weather.get("flood_risk_score"),
            "forecast_next_2hr": weather.get("forecast_next_2hr"),
            "forecast_next_4hr": weather.get("forecast_next_4hr"),
            "power_grid_stress": weather.get("power_grid_stress"),
        }

    return SeverityRecord(
        cluster_id=classification.cluster_id,
        crisis_type=crisis_type,
        severity_level=level,
        severity_label=label,
        response_priority=priority,
        affected_radius_km=_radius_km(
            level, area_sq_km, len(cluster.signals) if cluster else 1
        ),
        population_at_risk=population_at_risk,
        population_p10=p10,
        population_p90=p90,
        expected_duration_hours=round(
            _duration_hours(crisis_type, weather, level), 1
        ),
        peak_impact_eta=peak_eta,
        spread_risk_score=_spread_risk(crisis_type, cluster, weather, level),
        environmental_factors=env_factors,
        requires_verification=classification.requires_verification,
    )


async def fetch_weather_forecast(
    cluster_id: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    tool_use: Mock weather API (DS-002) for environmental severity factors.
    """
    try:
        classifications = _parse_classifications(
            tool_context.state.get("temp:classified_clusters", [])
        )
        classification = next(
            (c for c in classifications if c.cluster_id == cluster_id), None
        )
        if classification is None:
            return {"error": f"cluster_id {cluster_id} not found in classified_clusters"}

        fused = _parse_fused_clusters(tool_context.state.get("temp:fused_clusters", {}))
        cluster = fused.get(cluster_id)
        city_name = cluster.city if cluster else "Islamabad"

        phase = _get_phase(tool_context)
        crisis_type = classification.primary_classification

        _emit_trace(
            f"Environmental factors needed for {crisis_type}.",
            f"tool_use: fetch_weather_forecast cluster={cluster_id}, city={city_name}.",
            "Load DS-002 snapshot and forecast fields for severity adjustment.",
        )

        if crisis_type not in _ENVIRONMENTAL_CRISIS_TYPES:
            return {
                "cluster_id": cluster_id,
                "environmental_applicable": False,
                "message": f"{crisis_type} is not weather-driven; skip forecast integration.",
            }

        weather = _fetch_weather_snapshot(city_name, phase)
        tool_context.state.setdefault("temp:weather_context", {})[cluster_id] = weather

        _emit_trace(
            "Weather context retrieved for severity model.",
            f"DS-002 alert={weather.get('alert_level') if weather else 'n/a'}, "
            f"forecast={weather.get('forecast_next_2hr') if weather else 'n/a'}.",
            "Return forecast payload for call_llm severity reasoning.",
        )

        return {
            "cluster_id": cluster_id,
            "environmental_applicable": True,
            "city": city_name,
            "phase": phase,
            "weather_snapshot": weather,
        }
    except Exception as exc:  # noqa: BLE001
        _emit_trace(
            "Weather fetch failed.",
            f"tool_use error: {exc}",
            "Proceed with population-only severity heuristics.",
        )
        return {"cluster_id": cluster_id, "error": str(exc), "weather_snapshot": None}


SEVERITY_INSTRUCTION = f"""
You are the CIRO Severity & Evolution Predictor Agent.

{URDU_RULE}

Input: `temp:classified_clusters` (ClusterClassification list).
Optional context: `temp:fused_clusters` for signal counts, velocity, flags.

Severity scale (use exactly):
1 Minimal — <100 people, monitor only
2 Low — 100–500, dispatch team
3 Moderate — 500–2,000, coordinate
4 High — 2,000–10,000 or critical infrastructure, full mobilization
5 Critical — >10,000 or cascading failure, emergency declaration

For EACH classification in temp:classified_clusters:
1. tool_use: Call `fetch_weather_forecast(cluster_id)` when crisis is environmental
   (urban_flood, heatwave, power_outage, fire, water_main_burst).
2. call_llm: Reason about severity using classification confidence, zone population
   (from tool weather context or fused cluster), suspicious flags, and forecasts.
   On [OBSERVATION], prefix: "call_llm: severity reasoning for <cluster_id> ..."
3. Emit one SeverityRecord per cluster with:
   - severity_level (1–5), severity_label, response_priority
   - affected_radius_km, population_at_risk, population_p10, population_p90
   - expected_duration_hours, peak_impact_eta (ISO datetime)
   - spread_risk_score (0–1)
   - environmental_factors dict from weather tool when applicable

Print [THOUGHT], [OBSERVATION], [ACTION] for each cluster.
Return SeverityPredictionResult JSON.
"""


async def _persist_severity_records(callback_context) -> None:
    state = callback_context.state
    raw = state.get("severity_prediction") or state.get("temp:severity_prediction")
    records: list[SeverityRecord] = []

    if raw:
        if isinstance(raw, str):
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            raw = json.loads(raw)
        result = SeverityPredictionResult.model_validate(raw)
        records = result.records
    else:
        classifications = _parse_classifications(state.get("temp:classified_clusters", []))
        fused = _parse_fused_clusters(state.get("temp:fused_clusters", {}))
        weather_ctx = state.get("temp:weather_context", {})
        for clf in classifications:
            cluster = fused.get(clf.cluster_id)
            weather = weather_ctx.get(clf.cluster_id)
            records.append(
                predict_severity_heuristic(clf, cluster, weather)
            )

    state["temp:severity_records"] = [r.model_dump(mode="json") for r in records]
    _emit_trace(
        "Severity records ready for response planning.",
        f"Persisted {len(records)} SeverityRecords to temp:severity_records.",
        "Downstream dispatch agents use severity_level and response_priority.",
    )


severity_predictor_agent = LlmAgent(
    name="SeverityPredictorAgent",
    model=GEMINI_MODEL,
    description=(
        "Estimates crisis severity level, population at risk, spread risk, and peak "
        "impact timing using classified clusters and weather integration."
    ),
    instruction=SEVERITY_INSTRUCTION,
    tools=[FunctionTool(fetch_weather_forecast)],
    output_schema=SeverityPredictionResult,
    output_key="severity_prediction",
    after_agent_callback=_persist_severity_records,
)

root_agent = severity_predictor_agent
