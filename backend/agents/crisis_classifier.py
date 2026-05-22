"""
Crisis classifier — LlmAgent that labels fused clusters with crisis types.

Reads ``temp:fused_clusters``, uses DS-008 historical pattern lookup (tool_use),
then call_llm for primary/secondary hypotheses. Writes ``temp:classified_clusters``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import (
    ClassificationHypothesis,
    ClassificationResult,
    ClusterClassification,
    ClusterLocation,
    CrisisType,
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

_SUPPORTED_CLASSIFICATIONS = {c.value for c in CrisisType}

_RAW_TO_SLUG: dict[str, str] = {
    "FLOODING": CrisisType.URBAN_FLOOD.value,
    "URBAN_FLOODING": CrisisType.URBAN_FLOOD.value,
    "FLASH_FLOOD_WARNING": CrisisType.URBAN_FLOOD.value,
    "FLOOD": CrisisType.URBAN_FLOOD.value,
    "HEATWAVE": CrisisType.HEATWAVE.value,
    "EXTREME_HEAT_EMERGENCY": CrisisType.HEATWAVE.value,
    "HEAT": CrisisType.HEATWAVE.value,
    "ROAD_ACCIDENT": CrisisType.TRAFFIC_ACCIDENT.value,
    "TRAFFIC_ACCIDENT": CrisisType.TRAFFIC_ACCIDENT.value,
    "ACCIDENT": CrisisType.TRAFFIC_ACCIDENT.value,
    "ROAD_BLOCKAGE": CrisisType.PUBLIC_DISORDER.value,
    "PUBLIC_DISORDER": CrisisType.PUBLIC_DISORDER.value,
    "DHARNA": CrisisType.PUBLIC_DISORDER.value,
    "POWER_OUTAGE": CrisisType.POWER_OUTAGE.value,
    "INFRASTRUCTURE": CrisisType.INFRASTRUCTURE_FAILURE.value,
    "INFRASTRUCTURE_FAILURE": CrisisType.INFRASTRUCTURE_FAILURE.value,
    "DISEASE": CrisisType.DISEASE_CLUSTER.value,
    "DISEASE_CLUSTER": CrisisType.DISEASE_CLUSTER.value,
    "FIRE": CrisisType.FIRE.value,
    "WATER_MAIN": CrisisType.WATER_MAIN_BURST.value,
    "WATER_MAIN_BURST": CrisisType.WATER_MAIN_BURST.value,
    "NOISE": CrisisType.INFRASTRUCTURE_FAILURE.value,
    "TRAFFIC": CrisisType.TRAFFIC_ACCIDENT.value,
}

_HISTORICAL_TO_SLUG: dict[str, str] = {
    "URBAN_FLOODING": CrisisType.URBAN_FLOOD.value,
    "HEATWAVE": CrisisType.HEATWAVE.value,
    "ROAD_ACCIDENT": CrisisType.TRAFFIC_ACCIDENT.value,
    "POWER_OUTAGE": CrisisType.POWER_OUTAGE.value,
    "PUBLIC_DISORDER": CrisisType.PUBLIC_DISORDER.value,
    "FIRE": CrisisType.FIRE.value,
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


def _parse_fused_clusters(raw: Any) -> list[SignalCluster]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [
        c if isinstance(c, SignalCluster) else SignalCluster.model_validate(c)
        for c in raw
    ]


def _to_slug(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.upper().replace(" ", "_").replace("-", "_")
    return _RAW_TO_SLUG.get(key, _HISTORICAL_TO_SLUG.get(key))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _cluster_summary(cluster: SignalCluster) -> str:
    lines = [
        f"Cluster {cluster.cluster_id} | zone={cluster.zone} | city={cluster.city}",
        f"aggregate_credibility={cluster.aggregate_credibility:.2f} | "
        f"mention_velocity={cluster.mention_velocity:.2f}",
        f"semantic_theme={cluster.semantic_theme or 'n/a'} | "
        f"hint_crisis_type={cluster.crisis_type or 'n/a'}",
        "Signals:",
    ]
    for sig in cluster.signals[:12]:
        lines.append(
            f"  - [{sig.source.value}] {sig.signal_id}: {sig.summary[:100]}"
        )
    if len(cluster.signals) > 12:
        lines.append(f"  ... +{len(cluster.signals) - 12} more")
    return "\n".join(lines)


def _detect_conflicts(cluster: SignalCluster) -> list[str]:
    conflicts: list[str] = []
    by_source: dict[str, list[str]] = {}
    type_votes: dict[str, int] = {}

    for sig in cluster.signals:
        slug = _to_slug(sig.crisis_type)
        if slug:
            type_votes[slug] = type_votes.get(slug, 0) + 1
        by_source.setdefault(sig.source.value, []).append(sig.signal_id)

    if len(type_votes) > 1:
        ranked = sorted(type_votes.items(), key=lambda x: -x[1])
        conflicts.append(
            f"Mixed crisis hints: {ranked[0][0]} ({ranked[0][1]} signals) vs "
            f"{ranked[1][0]} ({ranked[1][1]} signals)"
        )

    if "field_report" in by_source and "social" in by_source:
        fr_types = {_to_slug(s.crisis_type) for s in cluster.signals if s.source.value == "field_report"}
        soc_types = {_to_slug(s.crisis_type) for s in cluster.signals if s.source.value == "social"}
        fr_types.discard(None)
        soc_types.discard(None)
        if fr_types and soc_types and fr_types != soc_types:
            fr_id = by_source["field_report"][0]
            conflicts.append(
                f"{fr_id} contradicts social cluster "
                f"({fr_types} vs {soc_types})"
            )

    return conflicts


def lookup_historical_for_cluster(
    cluster: SignalCluster,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Query DS-008 for events similar in location and crisis pattern."""
    db = _load_db()
    events = db.get("DS-008", {}).get("events", [])
    zone_key = (cluster.zone or "").strip().lower()
    candidates: list[tuple[float, dict[str, Any]]] = []

    cluster_slug = _to_slug(cluster.crisis_type)
    for event in events:
        score = 0.0
        if cluster.city.lower() == event.get("location_city", "").lower():
            score += 0.3
        area = str(event.get("location_area", "")).lower()
        if zone_key and (zone_key in area or area in zone_key):
            score += 0.4
        hist_slug = _HISTORICAL_TO_SLUG.get(
            event.get("crisis_type", "").upper(), ""
        )
        if cluster_slug and hist_slug == cluster_slug:
            score += 0.3
        if (
            cluster.latitude is not None
            and cluster.longitude is not None
            and event.get("location_lat") is not None
        ):
            dist = _haversine_km(
                cluster.latitude,
                cluster.longitude,
                event["location_lat"],
                event["location_lng"],
            )
            if dist <= 5.0:
                score += max(0.0, 0.2 - dist * 0.02)

        if score >= 0.3:
            candidates.append(
                (
                    score,
                    {
                        "event_id": event.get("event_id"),
                        "crisis_type": event.get("crisis_type"),
                        "subtype": event.get("subtype"),
                        "location_area": event.get("location_area"),
                        "location_city": event.get("location_city"),
                        "severity": event.get("severity"),
                        "key_lesson_learned": event.get("key_lesson_learned"),
                        "similar_to_scenario_id": event.get("similar_to_scenario_id"),
                        "relevance_score": round(score, 3),
                    },
                )
            )

    candidates.sort(key=lambda x: -x[0])
    return [item for _, item in candidates[:limit]]


def classify_cluster_heuristic(
    cluster: SignalCluster,
    historical: list[dict[str, Any]],
) -> ClusterClassification:
    """Deterministic baseline classification when LLM output is unavailable."""
    votes: dict[str, float] = {}
    for sig in cluster.signals:
        slug = _to_slug(sig.crisis_type)
        if slug:
            votes[slug] = votes.get(slug, 0.0) + sig.confidence

    if historical:
        hist_slug = _HISTORICAL_TO_SLUG.get(
            historical[0].get("crisis_type", "").upper(), ""
        )
        if hist_slug:
            votes[hist_slug] = votes.get(hist_slug, 0.0) + 0.5

    if not votes:
        votes[CrisisType.INFRASTRUCTURE_FAILURE.value] = 0.1

    ranked = sorted(votes.items(), key=lambda x: -x[1])
    primary, top_score = ranked[0]
    total = sum(votes.values()) or 1.0
    confidence = min(0.95, round(top_score / total * cluster.aggregate_credibility, 2))

    secondary: Optional[ClassificationHypothesis] = None
    if len(ranked) > 1:
        sec_type, sec_score = ranked[1]
        secondary = ClassificationHypothesis(
            type=sec_type,
            confidence=round(sec_score / total * 0.5, 2),
        )

    conflicts = _detect_conflicts(cluster)
    requires = confidence < 0.6 or bool(conflicts) or cluster.aggregate_credibility < 0.5

    return ClusterClassification(
        cluster_id=cluster.cluster_id,
        primary_classification=primary,
        confidence=confidence,
        secondary_hypothesis=secondary,
        conflicting_signals=conflicts,
        location=ClusterLocation(
            zone=cluster.zone,
            lat=cluster.latitude,
            lon=cluster.longitude,
        ),
        requires_verification=requires,
    )


async def lookup_historical_patterns(
    cluster_id: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    tool_use: DS-008 historical pattern lookup for one fused cluster.
    """
    try:
        clusters = _parse_fused_clusters(tool_context.state.get("temp:fused_clusters", []))
        cluster = next((c for c in clusters if c.cluster_id == cluster_id), None)
        if cluster is None:
            return {"error": f"cluster_id {cluster_id} not found", "matches": []}

        _emit_trace(
            f"Classify cluster {cluster_id} using prior incidents.",
            f"tool_use: lookup_historical_patterns for zone={cluster.zone}, "
            f"city={cluster.city}.",
            "Query DS-008 historical_crisis_events for location/crisis similarity.",
        )

        matches = lookup_historical_for_cluster(cluster)
        summary = _cluster_summary(cluster)
        tool_context.state.setdefault("temp:historical_context", {})[cluster_id] = {
            "matches": matches,
            "summary": summary,
        }

        _emit_trace(
            "Historical context ready for LLM classification.",
            f"Found {len(matches)} DS-008 matches; signal summary has "
            f"{len(cluster.signals)} events.",
            f"Return context for call_llm on cluster {cluster_id}.",
        )

        return {
            "cluster_id": cluster_id,
            "signal_summary": summary,
            "historical_matches": matches,
            "conflict_hints": _detect_conflicts(cluster),
        }
    except Exception as exc:  # noqa: BLE001
        _emit_trace(
            "Historical lookup failed.",
            f"tool_use error: {exc}",
            "Continue classification using signal summary only.",
        )
        return {"cluster_id": cluster_id, "error": str(exc), "historical_matches": []}


CLASSIFIER_INSTRUCTION = f"""
You are the CIRO Crisis Classifier Agent.

{URDU_RULE}

Input: session state `temp:fused_clusters` (list of SignalCluster).

Supported primary_classification slugs (use exactly these):
{", ".join(sorted(_SUPPORTED_CLASSIFICATIONS))}

Workflow for EACH cluster in temp:fused_clusters:
1. tool_use: Call `lookup_historical_patterns` with that cluster's cluster_id.
2. call_llm: Classify using the tool's signal_summary, historical_matches, and
   conflict_hints. On [OBSERVATION] for this step, start with:
   "call_llm: classifying cluster <id> with signal summary ..."
3. Produce one ClusterClassification per cluster with:
   - primary_classification (best slug)
   - confidence (0-1)
   - secondary_hypothesis when ambiguous (second-ranked type + confidence)
   - conflicting_signals (human-readable strings)
   - location {{zone, lat, lon}} from the cluster
   - requires_verification=true if confidence < 0.6, conflicts exist, or signals disagree

Use historical key_lesson_learned to boost confidence when patterns align.
When ambiguous, always include secondary_hypothesis with confidence < primary.

Return ClassificationResult JSON with all classifications.
Print [THOUGHT], [OBSERVATION], [ACTION] for every cluster processed.
"""


async def _persist_classifications(callback_context) -> None:
    state = callback_context.state
    raw = state.get("classification_result") or state.get("temp:classification_result")
    classifications: list[ClusterClassification] = []

    if raw:
        if isinstance(raw, str):
            raw = json.loads(raw)
        result = ClassificationResult.model_validate(raw)
        classifications = result.classifications
    else:
        clusters = _parse_fused_clusters(state.get("temp:fused_clusters", []))
        hist_ctx = state.get("temp:historical_context", {})
        for cluster in clusters:
            historical = (hist_ctx.get(cluster.cluster_id) or {}).get("matches", [])
            classifications.append(classify_cluster_heuristic(cluster, historical))

    state["temp:classified_clusters"] = [
        c.model_dump(mode="json") for c in classifications
    ]
    _emit_trace(
        "Classifications ready for severity prediction and response planning.",
        f"Persisted {len(classifications)} entries to temp:classified_clusters.",
        "Downstream agents read primary_classification and requires_verification.",
    )


crisis_classifier_agent = LlmAgent(
    name="CrisisClassifierAgent",
    model=GEMINI_MODEL,
    description=(
        "Classifies fused signal clusters into crisis types with ranked hypotheses "
        "and historical pattern grounding."
    ),
    instruction=CLASSIFIER_INSTRUCTION,
    tools=[FunctionTool(lookup_historical_patterns)],
    # output_schema=ClassificationResult,
    # output_key="classification_result",
    after_agent_callback=_persist_classifications,
)

root_agent = crisis_classifier_agent
