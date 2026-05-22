"""
Signal ingestion — ParallelAgent that fetches and normalizes crisis signals.

Concurrently runs five LlmAgent fetchers (social, weather, traffic, sensors,
field reports), merges into ``temp:raw_signals``, with per-source STALE fallback.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import CityConfig, SignalBatch, SignalEvent, SignalSource

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATHS = (
    PROJECT_ROOT / "mock_data" / "ciro_all_datasets.json",
    PROJECT_ROOT / "mock_data" / "ciro_datasets.json",
)
SENSORS_PATH = PROJECT_ROOT / "mock_data" / "sensors.json"
FIELD_REPORTS_PATH = PROJECT_ROOT / "mock_data" / "field_reports.json"

URDU_RULE = (
    "Input may be Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

TRACE_PREFIXES = ("[THOUGHT]", "[OBSERVATION]", "[ACTION]")

# Per-source last-good batch cache (serialized SignalEvent dicts).
_SOURCE_CACHE: dict[str, list[dict[str, Any]]] = {}
_DB: Optional[dict[str, Any]] = None

_SUB_AGENT_OUTPUT_KEYS = (
    "social_signals",
    "weather_signals",
    "traffic_signals",
    "sensor_signals",
    "field_report_signals",
)


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
    raise FileNotFoundError(
        f"No dataset found under {PROJECT_ROOT / 'mock_data'}"
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _city_config_from_state(state: Any) -> CityConfig:
    """Parse CityConfig from session state (dict or ADK ``State``; merge has no ToolContext)."""
    raw = state.get("city_config")
    if isinstance(raw, CityConfig):
        return raw
    if isinstance(raw, dict):
        return CityConfig.model_validate(raw)
    if isinstance(raw, str):
        return CityConfig.model_validate(json.loads(raw))
    raise ValueError(
        "city_config missing from session state. "
        "Set state['city_config'] before running signal ingestion."
    )


def _parse_city_config(tool_context: ToolContext) -> CityConfig:
    return _city_config_from_state(tool_context.state)


def _collect_normalized_signals(cfg: CityConfig) -> list[SignalEvent]:
    """Deterministic ingestion (same normalization as fetch_* tools) — no LLM required."""
    return (
        _normalize_social(cfg)
        + _normalize_weather(cfg)
        + _normalize_traffic(cfg)
        + _normalize_sensors(cfg)
        + _normalize_field_reports(cfg)
    )


def _in_bbox(
    lat: Optional[float],
    lng: Optional[float],
    cfg: CityConfig,
) -> bool:
    if lat is None or lng is None:
        return True
    return (
        cfg.bbox_south <= lat <= cfg.bbox_north
        and cfg.bbox_west <= lng <= cfg.bbox_east
    )


def _city_match(record_city: str, cfg: CityConfig) -> bool:
    return record_city.lower() == cfg.city.lower()


def _scenario_match(record_scenario: Optional[str], cfg: CityConfig) -> bool:
    if not cfg.scenario_id or not record_scenario:
        return True
    return record_scenario == cfg.scenario_id


def _new_signal_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _severity_from_level(level: Optional[str]) -> Optional[str]:
    if not level:
        return None
    mapping = {
        "NONE": "low",
        "LOW": "low",
        "MODERATE": "medium",
        "HIGH": "high",
        "CRITICAL": "critical",
        "ALERT": "high",
    }
    return mapping.get(level.upper(), level.lower())


def _apply_fallback(
    source_key: str,
    signals: list[SignalEvent],
    error: Optional[str] = None,
) -> SignalBatch:
    serialized = [s.model_dump(mode="json") for s in signals]
    if serialized:
        _SOURCE_CACHE[source_key] = serialized

    if error:
        cached = _SOURCE_CACHE.get(source_key, [])
        stale_events = [
            SignalEvent.model_validate(
                {
                    **item,
                    "metadata": {
                        **(item.get("metadata") or {}),
                        "stale": True,
                        "source_status": "STALE",
                        "fallback_reason": error,
                    },
                }
            )
            for item in cached
        ]
        _emit_trace(
            f"{source_key} fetch failed; falling back to cache.",
            f"Recovered {len(stale_events)} cached signals. Error: {error}",
            f"Return STALE batch for {source_key}.",
        )
        return SignalBatch(
            signals=stale_events,
            source_status="STALE",
            error=error,
        )

    return SignalBatch(signals=signals, source_status="LIVE")


def _zone_centers_in_bbox(cfg: CityConfig) -> set[str]:
    zones = _load_db().get("DS-005", {}).get("zones", [])
    names: set[str] = set()
    for zone in zones:
        if not _city_match(zone.get("city", ""), cfg):
            continue
        lat = zone.get("lat_center")
        lng = zone.get("lng_center")
        if _in_bbox(lat, lng, cfg):
            names.add(zone.get("zone_name", ""))
            names.update(zone.get("zone_alias") or [])
    return {n for n in names if n}


def _normalize_social(cfg: CityConfig) -> list[SignalEvent]:
    db = _load_db()
    phase_key = cfg.phase if cfg.phase in ("T0_before", "T1_during", "T2_after_response") else "T1_during"
    posts = db["DS-001"]["posts"].get(phase_key, [])
    zone_names = _zone_centers_in_bbox(cfg)
    events: list[SignalEvent] = []

    for post in posts:
        if not _city_match(post.get("city", ""), cfg):
            continue
        if not _scenario_match(post.get("scenario_id"), cfg):
            continue
        loc = post.get("location_mentioned") or post.get("location_tag") or ""
        if zone_names and loc and loc not in zone_names and post.get("city") != cfg.city:
            continue

        filter_decision = post.get("agent_filter_decision", "INCLUDE")
        confidence = 0.85 if filter_decision == "INCLUDE" else 0.4
        events.append(
            SignalEvent(
                signal_id=_new_signal_id("SOC"),
                source=SignalSource.SOCIAL,
                timestamp=_parse_ts(post["timestamp"]),
                city=post["city"],
                zone=post.get("location_mentioned"),
                crisis_type=post.get("crisis_type_hint"),
                severity="high" if post.get("crisis_signal") else "medium",
                summary=post.get("text", "")[:280],
                confidence=confidence,
                raw=post,
                metadata={
                    "platform": post.get("platform"),
                    "agent_filter_decision": filter_decision,
                    "language": post.get("language"),
                    "phase": phase_key,
                },
            )
        )
    return events


def _normalize_weather(cfg: CityConfig) -> list[SignalEvent]:
    db = _load_db()
    snapshots_root = db["DS-002"]["snapshots"]
    phase_key = cfg.phase
    events: list[SignalEvent] = []

    for _scenario_id, phases in snapshots_root.items():
        if not _scenario_match(_scenario_id, cfg):
            continue
        snap = phases.get(phase_key) or phases.get("T1_during")
        if not snap:
            continue
        if not _city_match(snap.get("city", ""), cfg):
            continue

        severity = _severity_from_level(snap.get("alert_level"))
        rainfall = snap.get("rainfall_mm_per_hour", 0) or 0
        temp = snap.get("temperature_c", 0) or 0
        summary = (
            f"{snap.get('alert_type', 'WEATHER')}: "
            f"{rainfall}mm/hr rain, {temp}°C at {snap.get('station', 'station')}"
        )
        events.append(
            SignalEvent(
                signal_id=_new_signal_id("WX"),
                source=SignalSource.WEATHER,
                timestamp=_parse_ts(snap["timestamp"]),
                city=snap["city"],
                crisis_type=snap.get("alert_type"),
                severity=severity,
                summary=summary,
                confidence=0.92 if snap.get("threshold_breached") else 0.75,
                raw=snap,
                metadata={
                    "agent_trigger": snap.get("agent_trigger"),
                    "flood_risk_score": snap.get("flood_risk_score"),
                    "phase": phase_key,
                },
            )
        )
    return events


def _normalize_traffic(cfg: CityConfig) -> list[SignalEvent]:
    db = _load_db()
    roads = db["DS-003"]["roads"]
    traffic_phase = "T1" if "T1" in cfg.phase else cfg.phase.replace("_during", "").replace("_before", "T0").replace("_after_response", "T2")
    if traffic_phase not in ("T0", "T1", "T2"):
        traffic_phase = "T1"
    events: list[SignalEvent] = []

    for road in roads:
        if not _city_match(road.get("city", ""), cfg):
            continue
        if not _scenario_match(road.get("scenario_id"), cfg):
            continue
        lat = (road.get("lat_start", 0) + road.get("lat_end", 0)) / 2
        lng = (road.get("lng_start", 0) + road.get("lng_end", 0)) / 2
        if not _in_bbox(lat, lng, cfg):
            continue

        snap = road.get(traffic_phase) or road.get("T1", {})
        status = snap.get("status", "UNKNOWN")
        congestion = snap.get("congestion_percent", 0)
        events.append(
            SignalEvent(
                signal_id=_new_signal_id("TRF"),
                source=SignalSource.TRAFFIC,
                timestamp=_parse_ts(
                    snap.get("timestamp", datetime.now(timezone.utc).isoformat())
                ),
                city=road["city"],
                zone=road.get("zone"),
                latitude=lat,
                longitude=lng,
                crisis_type=snap.get("incident_type") or "TRAFFIC",
                severity=_severity_from_level(status) or "medium",
                summary=(
                    f"{road['road_name']}: {status}, "
                    f"{congestion}% congestion"
                ),
                confidence=0.88,
                raw={"road": road, "snapshot": snap},
                metadata={
                    "road_id": road.get("road_id"),
                    "vehicles_stranded": snap.get("vehicles_stranded"),
                    "traffic_phase": traffic_phase,
                },
            )
        )
    return events


def _normalize_sensors(cfg: CityConfig) -> list[SignalEvent]:
    payload = _load_json(SENSORS_PATH)
    events: list[SignalEvent] = []
    for reading in payload.get("sensors", []):
        if not _city_match(reading.get("city", ""), cfg):
            continue
        if not _scenario_match(reading.get("scenario_id"), cfg):
            continue
        if not _in_bbox(reading.get("lat"), reading.get("lng"), cfg):
            continue

        status = reading.get("status", "OK")
        events.append(
            SignalEvent(
                signal_id=_new_signal_id("SNS"),
                source=SignalSource.SENSOR,
                timestamp=_parse_ts(reading["timestamp"]),
                city=reading["city"],
                zone=reading.get("zone"),
                latitude=reading.get("lat"),
                longitude=reading.get("lng"),
                crisis_type=reading.get("crisis_type_hint"),
                severity=_severity_from_level(status),
                summary=(
                    f"{reading['sensor_type']}={reading['value']}{reading.get('unit', '')} "
                    f"({status}) in {reading.get('zone', 'zone')}"
                ),
                confidence=0.9 if status in ("ALERT", "CRITICAL") else 0.7,
                raw=reading,
                metadata={
                    "sensor_id": reading.get("sensor_id"),
                    "sensor_type": reading.get("sensor_type"),
                },
            )
        )
    return events


def _normalize_field_reports(cfg: CityConfig) -> list[SignalEvent]:
    payload = _load_json(FIELD_REPORTS_PATH)
    events: list[SignalEvent] = []
    for report in payload.get("field_reports", []):
        if not _city_match(report.get("city", ""), cfg):
            continue
        if not _scenario_match(report.get("scenario_id"), cfg):
            continue
        if not _in_bbox(report.get("lat"), report.get("lng"), cfg):
            continue

        severity = _severity_from_level(report.get("severity"))
        events.append(
            SignalEvent(
                signal_id=_new_signal_id("FR"),
                source=SignalSource.FIELD_REPORT,
                timestamp=_parse_ts(report["timestamp"]),
                city=report["city"],
                zone=report.get("zone"),
                latitude=report.get("lat"),
                longitude=report.get("lng"),
                crisis_type=report.get("crisis_type"),
                severity=severity,
                summary=report.get("text", "")[:280],
                confidence=0.95 if report.get("verified") else 0.65,
                raw=report,
                metadata={
                    "report_id": report.get("report_id"),
                    "reporter_role": report.get("reporter_role"),
                    "language": report.get("language"),
                },
            )
        )
    return events


async def fetch_social_signals(tool_context: ToolContext) -> dict[str, Any]:
    """Load DS-001 social posts, filter by city bbox, return SignalBatch JSON."""
    source_key = "social"
    try:
        cfg = _parse_city_config(tool_context)
        _emit_trace(
            "Need citizen/social signals for the configured bounding box.",
            f"City={cfg.city}, phase={cfg.phase}, bbox="
            f"[{cfg.bbox_south},{cfg.bbox_west}]–[{cfg.bbox_north},{cfg.bbox_east}]",
            "Load DS-001 and normalize to SignalEvent list.",
        )
        signals = _normalize_social(cfg)
        batch = _apply_fallback(source_key, signals)
        _emit_trace(
            "Social fetch succeeded.",
            f"Normalized {len(batch.signals)} social SignalEvents.",
            "Return LIVE SignalBatch to the agent.",
        )
        return batch.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 — per-source isolation
        batch = _apply_fallback(source_key, [], str(exc))
        return batch.model_dump(mode="json")


async def fetch_weather_signals(tool_context: ToolContext) -> dict[str, Any]:
    """Load DS-002 weather snapshots for the city bbox."""
    source_key = "weather"
    try:
        cfg = _parse_city_config(tool_context)
        _emit_trace(
            "Weather thresholds may trigger flood/heat escalation.",
            f"Reading DS-002 for {cfg.city}, phase {cfg.phase}.",
            "Normalize snapshots including agent_trigger metadata.",
        )
        signals = _normalize_weather(cfg)
        batch = _apply_fallback(source_key, signals)
        _emit_trace(
            "Weather fetch succeeded.",
            f"Collected {len(batch.signals)} weather SignalEvents.",
            "Return batch with agent_trigger preserved in metadata.",
        )
        return batch.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        batch = _apply_fallback(source_key, [], str(exc))
        return batch.model_dump(mode="json")


async def fetch_traffic_signals(tool_context: ToolContext) -> dict[str, Any]:
    """Load DS-003 road/traffic data within the bounding box."""
    source_key = "traffic"
    try:
        cfg = _parse_city_config(tool_context)
        _emit_trace(
            "Traffic congestion and blockages affect routing.",
            f"Filtering DS-003 roads inside {cfg.city} bbox.",
            "Map road T1/T0/T2 snapshots to SignalEvents.",
        )
        signals = _normalize_traffic(cfg)
        batch = _apply_fallback(source_key, signals)
        _emit_trace(
            "Traffic fetch succeeded.",
            f"Normalized {len(batch.signals)} traffic SignalEvents.",
            "Return LIVE SignalBatch.",
        )
        return batch.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        batch = _apply_fallback(source_key, [], str(exc))
        return batch.model_dump(mode="json")


async def fetch_sensor_signals(tool_context: ToolContext) -> dict[str, Any]:
    """Load IoT sensor readings from mock_data/sensors.json."""
    source_key = "sensor"
    try:
        cfg = _parse_city_config(tool_context)
        _emit_trace(
            "IoT sensors provide ground-truth readings (water, heat, grid).",
            f"Reading sensors.json for {cfg.city}.",
            "Normalize sensor alerts to SignalEvent schema.",
        )
        signals = _normalize_sensors(cfg)
        batch = _apply_fallback(source_key, signals)
        _emit_trace(
            "Sensor fetch succeeded.",
            f"Collected {len(batch.signals)} sensor SignalEvents.",
            "Return LIVE SignalBatch.",
        )
        return batch.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        batch = _apply_fallback(source_key, [], str(exc))
        return batch.model_dump(mode="json")


async def fetch_field_report_signals(tool_context: ToolContext) -> dict[str, Any]:
    """Load verified field reports from mock_data/field_reports.json."""
    source_key = "field_report"
    try:
        cfg = _parse_city_config(tool_context)
        _emit_trace(
            "Field reports are trusted on-ground observations.",
            f"Loading field_reports.json for {cfg.city}.",
            "Parse Urdu/Roman Urdu text directly into summaries.",
        )
        signals = _normalize_field_reports(cfg)
        batch = _apply_fallback(source_key, signals)
        _emit_trace(
            "Field report fetch succeeded.",
            f"Normalized {len(batch.signals)} field-report SignalEvents.",
            "Return LIVE SignalBatch.",
        )
        return batch.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        batch = _apply_fallback(source_key, [], str(exc))
        return batch.model_dump(mode="json")


def _fetcher_instruction(source_label: str, tool_name: str) -> str:
    return f"""
You are the {source_label} for CIRO signal ingestion.

{URDU_RULE}

Your job:
1. Call the `{tool_name}` tool exactly once.
2. Print lines starting with [THOUGHT], [OBSERVATION], and [ACTION] describing your reasoning.
3. Return the tool result as a SignalBatch (signals list unchanged).

City configuration is in session state as `city_config` (bounding box + city + phase).
Do not invent signals — only normalize what the tool returns.
If the tool reports source_status STALE, preserve metadata.stale flags on every signal.
"""


async def _merge_raw_signals(callback_context) -> None:
    """After parallel fetchers complete, merge batches into temp:raw_signals.

    - **Append**, never wipe: preserves Urdu intake / field-report SignalEvents already
      in ``temp:raw_signals`` (per pipeline spec).
    - If parallel LlmAgents did not persist ``output_schema`` batches to session state,
      fall back to the same deterministic normalization used by fetch_* tools so
      ``SignalFusionAgent`` always receives valid ``SignalEvent`` dicts.
    """
    state = callback_context.state
    existing: list[dict[str, Any]] = []
    prior = state.get("temp:raw_signals")
    if prior:
        if isinstance(prior, str):
            prior = json.loads(prior)
        if isinstance(prior, list):
            for item in prior:
                if isinstance(item, dict):
                    existing.append(dict(item))

    merged: list[dict[str, Any]] = []
    stale_sources: list[str] = []

    for key in _SUB_AGENT_OUTPUT_KEYS:
        batch_raw = state.get(key)
        if not batch_raw:
            continue
        try:
            if isinstance(batch_raw, str):
                batch_raw = json.loads(batch_raw)
            if isinstance(batch_raw, SignalBatch):
                batch = batch_raw
            else:
                batch = SignalBatch.model_validate(batch_raw)
        except Exception as exc:  # noqa: BLE001 — do not stall pipeline on one branch
            _emit_trace(
                f"Ingest merge: could not parse batch for {key}.",
                f"Validate error: {exc}",
                "Skipping this source; other batches / fallback still apply.",
            )
            continue

        if batch.source_status == "STALE":
            stale_sources.append(key)
        for signal in batch.signals:
            merged.append(signal.model_dump(mode="json"))

    if not merged:
        try:
            cfg = _city_config_from_state(state)
            fallback_events = _collect_normalized_signals(cfg)
            merged = [e.model_dump(mode="json") for e in fallback_events]
            _emit_trace(
                "Parallel LlmAgents left no ingest batches on session state; "
                "using deterministic normalization (same as tool path).",
                f"fallback_signal_count={len(merged)}, city={cfg.city}",
                "Populate temp:raw_signals so fusion can proceed.",
            )
        except Exception as exc:  # noqa: BLE001
            _emit_trace(
                "Deterministic ingest fallback failed.",
                f"error={exc}",
                "temp:raw_signals will only retain pre-ingestion signals.",
            )

    merged_ids = {item.get("signal_id") for item in merged if item.get("signal_id")}
    retained = [
        item
        for item in existing
        if isinstance(item, dict)
        and item.get("signal_id") not in merged_ids
    ]
    combined = retained + merged
    state["temp:raw_signals"] = combined
    _emit_trace(
        "All parallel fetchers finished; consolidate normalized events.",
        (
            f"Retained prior signals: {len(retained)}, ingest merge added: "
            f"{len(merged)}, total temp:raw_signals={len(combined)}. "
            f"Stale sources: {stale_sources or 'none'}."
        ),
        "Write combined list to temp:raw_signals for SignalFusionAgent.",
    )


# --- Sub-agents (LlmAgent per source) ---

social_signal_fetcher = LlmAgent(
    name="SocialSignalFetcher",
    model=GEMINI_MODEL,
    description="Fetches and normalizes DS-001 social media posts into SignalEvents.",
    instruction=_fetcher_instruction("Social Signal Fetcher", "fetch_social_signals"),
    tools=[FunctionTool(fetch_social_signals)],
    # output_schema=SignalBatch,
    # output_key="social_signals",
)

weather_signal_fetcher = LlmAgent(
    name="WeatherSignalFetcher",
    model=GEMINI_MODEL,
    description="Fetches and normalizes DS-002 weather snapshots into SignalEvents.",
    instruction=_fetcher_instruction("Weather Signal Fetcher", "fetch_weather_signals"),
    tools=[FunctionTool(fetch_weather_signals)],
    # output_schema=SignalBatch,
    # output_key="weather_signals",
)

traffic_signal_fetcher = LlmAgent(
    name="TrafficSignalFetcher",
    model=GEMINI_MODEL,
    description="Fetches and normalizes DS-003 traffic/road data into SignalEvents.",
    instruction=_fetcher_instruction("Traffic Signal Fetcher", "fetch_traffic_signals"),
    tools=[FunctionTool(fetch_traffic_signals)],
    # output_schema=SignalBatch,
    # output_key="traffic_signals",
)

sensor_signal_fetcher = LlmAgent(
    name="SensorSignalFetcher",
    model=GEMINI_MODEL,
    description="Fetches and normalizes IoT sensor readings into SignalEvents.",
    instruction=_fetcher_instruction("Sensor Signal Fetcher", "fetch_sensor_signals"),
    tools=[FunctionTool(fetch_sensor_signals)],
    # output_schema=SignalBatch,
    # output_key="sensor_signals",
)

field_report_fetcher = LlmAgent(
    name="FieldReportFetcher",
    model=GEMINI_MODEL,
    description="Fetches and normalizes on-ground field reports into SignalEvents.",
    instruction=_fetcher_instruction("Field Report Fetcher", "fetch_field_report_signals"),
    tools=[FunctionTool(fetch_field_report_signals)],
    # output_schema=SignalBatch,
    # output_key="field_report_signals",
)

signal_ingestion_agent = SequentialAgent(
    name="SignalIngestionAgent",
    description=(
        "Concurrently fetches signals from social, weather, traffic, sensor, "
        "and field-report sources; normalizes to SignalEvent; stores temp:raw_signals."
    ),
    sub_agents=[
        social_signal_fetcher,
        weather_signal_fetcher,
        traffic_signal_fetcher,
        sensor_signal_fetcher,
        field_report_fetcher,
    ],
    after_agent_callback=_merge_raw_signals,
)

root_agent = signal_ingestion_agent
