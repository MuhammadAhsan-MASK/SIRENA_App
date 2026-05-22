"""
Signal fusion & credibility — LlmAgent that scores and clusters raw signals.

Reads ``temp:raw_signals``, applies credibility scoring (source, geo, velocity,
contradiction), groups by spatial proximity and semantic similarity, writes
``temp:fused_clusters``.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from datetime import timezone
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import (
    FusionClusterLlm,
    FusionResult,
    FusionResultLlm,
    ScoredSignal,
    SignalCluster,
    SignalEvent,
    SignalSource,
)

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
WINDOW_SECONDS = 300
EMA_ALPHA = 0.4
SPATIAL_RADIUS_KM = 2.0

# Source reputation (architecture spec)
REP_WEATHER = 0.92
REP_SENSOR = 0.90
REP_FIELD_REPORT_VERIFIED = 0.95
REP_FIELD_REPORT_UNVERIFIED = 0.65
REP_TRAFFIC = 1.0
REP_SOCIAL_OFFICIAL = 1.0
REP_SOCIAL_VERIFIED = 0.75
REP_SOCIAL_ANONYMOUS = 0.3

# Mention-velocity normalization thresholds (mentions per 5-min window)
VELOCITY_THRESHOLD_FLOOD = 3.0
VELOCITY_THRESHOLD_HEAT = 2.0
VELOCITY_THRESHOLD_DEFAULT = 5.0

URDU_RULE = (
    "Input may be Urdu, Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

_OFFICIAL_ROLES = frozenset(
    {
        "itp_warden",
        "cda_warden",
        "health_worker",
        "official",
        "news_org",
    }
)

_CRISIS_ALIASES: dict[str, str] = {
    "FLOOD": "FLOODING",
    "FLOODING": "FLOODING",
    "FLASH_FLOOD_WARNING": "FLOODING",
    "HEAT": "HEATWAVE",
    "HEATWAVE": "HEATWAVE",
    "EXTREME_HEAT_EMERGENCY": "HEATWAVE",
    "ROAD_BLOCKAGE": "ROAD_BLOCKAGE",
    "ROAD_ACCIDENT": "ROAD_ACCIDENT",
    "POWER_OUTAGE": "POWER_OUTAGE",
    "TRAFFIC": "TRAFFIC",
}


def _emit_trace(thought: str, observation: str, action: str) -> None:
    print(f"[THOUGHT] {thought}")
    print(f"[OBSERVATION] {observation}")
    print(f"[ACTION] {action}")


def _normalize_crisis_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.upper().replace(" ", "_")
    return _CRISIS_ALIASES.get(key, key)


def _parse_raw_signals(raw: Any) -> list[SignalEvent]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    events: list[SignalEvent] = []
    for item in raw:
        if isinstance(item, SignalEvent):
            events.append(item)
        else:
            events.append(SignalEvent.model_validate(item))
    return events


def _source_reputation(signal: SignalEvent) -> float:
    if signal.source == SignalSource.WEATHER:
        return REP_WEATHER
    if signal.source == SignalSource.SENSOR:
        return REP_SENSOR
    if signal.source == SignalSource.TRAFFIC:
        return REP_TRAFFIC

    if signal.source == SignalSource.FIELD_REPORT:
        verified = signal.raw.get("verified") or signal.metadata.get("verified")
        role = str(signal.metadata.get("reporter_role", "")).lower()
        if verified or role in _OFFICIAL_ROLES:
            return REP_FIELD_REPORT_VERIFIED
        return REP_FIELD_REPORT_UNVERIFIED

    if signal.source == SignalSource.SOCIAL:
        raw = signal.raw
        user_type = str(raw.get("user_type", "")).lower()
        if user_type in ("official", "news_org"):
            return REP_SOCIAL_OFFICIAL
        if raw.get("verified_source"):
            return REP_SOCIAL_VERIFIED
        return REP_SOCIAL_ANONYMOUS

    return 0.5


def _geolocation_confidence(signal: SignalEvent) -> float:
    if signal.latitude is not None and signal.longitude is not None:
        return 1.0
    if signal.zone:
        return 0.4
    return 0.2


def _zone_key(signal: SignalEvent) -> str:
    return (signal.zone or signal.city or "unknown").strip().lower()


def _velocity_threshold(signal: SignalEvent) -> float:
    ctype = _normalize_crisis_type(signal.crisis_type)
    if ctype in ("FLOODING", "FLOOD"):
        return VELOCITY_THRESHOLD_FLOOD
    if ctype == "HEATWAVE":
        return VELOCITY_THRESHOLD_HEAT
    return VELOCITY_THRESHOLD_DEFAULT


def _compute_zone_ema(signals: list[SignalEvent]) -> dict[str, float]:
    """Exponential smoothing of mention counts over 5-minute windows (raw EMA)."""
    buckets: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for signal in signals:
        zone = _zone_key(signal)
        ts = signal.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bucket_id = int(ts.timestamp()) // WINDOW_SECONDS
        buckets[zone][bucket_id] += 1

    ema_by_zone: dict[str, float] = {}
    for zone, window_counts in buckets.items():
        ema = 0.0
        for bucket_id in sorted(window_counts):
            count = window_counts[bucket_id]
            ema = EMA_ALPHA * count + (1 - EMA_ALPHA) * ema
        ema_by_zone[zone] = ema
    return ema_by_zone


def _mention_velocity_score(signal: SignalEvent, zone_ema: dict[str, float]) -> float:
    """Normalize zone EMA by crisis-specific threshold (flood=3, heat=2)."""
    ema = zone_ema.get(_zone_key(signal), 0.0)
    threshold = _velocity_threshold(signal)
    return min(ema / threshold, 1.0)


def _contradiction_by_zone(signals: list[SignalEvent]) -> dict[str, float]:
    """Zones with conflicting crisis types assign 0.25 contradiction factor."""
    types_by_zone: dict[str, set[str]] = defaultdict(set)
    for signal in signals:
        ctype = _normalize_crisis_type(signal.crisis_type)
        if ctype:
            types_by_zone[_zone_key(signal)].add(ctype)

    conflicting = {zone for zone, types in types_by_zone.items() if len(types) > 1}
    return {zone: (0.25 if zone in conflicting else 0.0) for zone in types_by_zone}


def _final_credibility(
    source_rep: float,
    geo_conf: float,
    velocity: float,
    contradiction: float,
) -> float:
    score = (
        0.4 * source_rep
        + 0.3 * geo_conf
        + 0.2 * velocity
        + 0.1 * (1.0 - contradiction)
    )
    return max(0.0, min(1.0, score))


def _cluster_suspicious_flags(
    signals: list[SignalEvent],
    crisis_types: list[str],
    lats: list[float],
    zones: list[str],
) -> list[str]:
    flags: list[str] = []
    if len(signals) == 1:
        flags.append("UNVERIFIED_SINGLE_SOURCE")
    if len(set(crisis_types)) > 1:
        flags.append("SOURCE_CONFLICT")
    if not lats and not zones:
        flags.append("GEO_OUTLIER")
    return flags


def score_signals(signals: list[SignalEvent]) -> list[ScoredSignal]:
    """Apply credibility algorithm to each signal."""
    zone_ema = _compute_zone_ema(signals)
    contradictions = _contradiction_by_zone(signals)
    scored: list[ScoredSignal] = []

    for signal in signals:
        zone = _zone_key(signal)
        source_rep = _source_reputation(signal)
        geo_conf = _geolocation_confidence(signal)
        velocity = _mention_velocity_score(signal, zone_ema)
        contradiction = contradictions.get(zone, 0.0)
        credibility = _final_credibility(source_rep, geo_conf, velocity, contradiction)
        scored.append(
            ScoredSignal(
                signal_id=signal.signal_id,
                credibility_score=credibility,
                source_reputation=source_rep,
                geolocation_confidence=geo_conf,
                mention_velocity=velocity,
                contradiction_factor=contradiction,
                signal=signal,
            )
        )
    return scored


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


def _cluster_index(scored: list[ScoredSignal]) -> list[list[int]]:
    """Union-find spatial grouping by proximity and shared zone."""
    n = len(scored)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            si, sj = scored[i].signal, scored[j].signal
            same_zone = (
                si.zone
                and sj.zone
                and si.zone.strip().lower() == sj.zone.strip().lower()
            )
            if same_zone:
                union(i, j)
                continue
            if (
                si.latitude is not None
                and si.longitude is not None
                and sj.latitude is not None
                and sj.longitude is not None
            ):
                dist = _haversine_km(
                    si.latitude, si.longitude, sj.latitude, sj.longitude
                )
                if dist <= SPATIAL_RADIUS_KM:
                    union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return list(groups.values())


def build_spatial_clusters(scored: list[ScoredSignal]) -> list[SignalCluster]:
    """Group scored signals into candidate clusters by spatial proximity."""
    if not scored:
        return []

    index_groups = _cluster_index(scored)
    clusters: list[SignalCluster] = []

    for members in index_groups:
        group_scored = [scored[i] for i in members]
        signals = [s.signal for s in group_scored]
        lats = [s.latitude for s in signals if s.latitude is not None]
        lngs = [s.longitude for s in signals if s.longitude is not None]
        zones = [s.zone for s in signals if s.zone]

        crisis_types = [
            _normalize_crisis_type(s.crisis_type)
            for s in signals
            if s.crisis_type
        ]
        consensus = max(set(crisis_types), key=crisis_types.count) if crisis_types else None
        hypothesis_diversity_flag = len(set(crisis_types)) > 1
        suspicious_flags = _cluster_suspicious_flags(signals, crisis_types, lats, zones)

        weights = [s.geolocation_confidence for s in group_scored]
        creds = [s.credibility_score for s in group_scored]
        aggregate = sum(w * c for w, c in zip(weights, creds)) / max(sum(weights), 1e-6)
        velocity = max(s.mention_velocity for s in group_scored)

        if suspicious_flags:
            _emit_trace(
                f"Cluster in {zones[0] if zones else signals[0].city} needs review.",
                f"Suspicious flags: {', '.join(suspicious_flags)}",
                "Attach flags to cluster metadata for judge trace.",
            )

        clusters.append(
            SignalCluster(
                cluster_id=f"CLU-{uuid.uuid4().hex[:8]}",
                city=signals[0].city,
                zone=zones[0] if zones else None,
                latitude=sum(lats) / len(lats) if lats else None,
                longitude=sum(lngs) / len(lngs) if lngs else None,
                crisis_type=consensus,
                signal_ids=[s.signal_id for s in signals],
                signals=signals,
                aggregate_credibility=round(aggregate, 4),
                mention_velocity=round(velocity, 4),
                hypothesis_diversity_flag=hypothesis_diversity_flag,
                metadata={
                    "spatial_group_size": len(signals),
                    "sources": sorted({s.source.value for s in signals}),
                    "suspicious_flags": suspicious_flags,
                },
            )
        )
    return clusters


def _signals_by_id_from_state(state: dict[str, Any]) -> dict[str, SignalEvent]:
    """Index SignalEvents from scored/raw state for LLM output hydration."""
    by_id: dict[str, SignalEvent] = {}
    scored = state.get("temp:scored_signals", [])
    if isinstance(scored, str):
        scored = json.loads(scored)
    for item in scored or []:
        if isinstance(item, ScoredSignal):
            by_id[item.signal_id] = item.signal
        elif isinstance(item, dict):
            sig = item.get("signal")
            if isinstance(sig, dict):
                by_id[item["signal_id"]] = SignalEvent.model_validate(sig)
            elif "signal_id" in item:
                by_id[item["signal_id"]] = SignalEvent.model_validate(item)
    if by_id:
        return by_id
    for sig in _parse_raw_signals(state.get("temp:raw_signals", [])):
        by_id[sig.signal_id] = sig
    return by_id


def _hydrate_cluster(lite: FusionClusterLlm, state: dict[str, Any]) -> SignalCluster:
    """Merge flat LLM cluster output with full SignalEvents from session state."""
    by_id = _signals_by_id_from_state(state)
    signals = [by_id[sid] for sid in lite.signal_ids if sid in by_id]
    cluster = SignalCluster(
        cluster_id=lite.cluster_id,
        city=lite.city,
        zone=lite.zone,
        latitude=lite.latitude,
        longitude=lite.longitude,
        crisis_type=lite.crisis_type,
        signal_ids=lite.signal_ids,
        signals=signals,
        aggregate_credibility=lite.aggregate_credibility,
        mention_velocity=lite.mention_velocity,
        hypothesis_diversity_flag=lite.hypothesis_diversity_flag,
        semantic_theme=lite.semantic_theme,
        metadata=lite.metadata,
    )
    return _enrich_cluster_from_signals(cluster)


def _enrich_cluster_from_signals(cluster: SignalCluster) -> SignalCluster:
    """Recompute diversity flag and suspicious flags from member signals."""
    signals = cluster.signals
    lats = [s.latitude for s in signals if s.latitude is not None]
    zones = [s.zone for s in signals if s.zone]
    crisis_types = [
        ct
        for ct in (_normalize_crisis_type(s.crisis_type) for s in signals)
        if ct
    ]
    flags = _cluster_suspicious_flags(signals, crisis_types, lats, zones)
    updates: dict[str, Any] = {
        "hypothesis_diversity_flag": len(set(crisis_types)) > 1,
        "metadata": {
            **cluster.metadata,
            "suspicious_flags": flags,
        },
    }
    return cluster.model_copy(update=updates)


async def score_signals_credibility(tool_context: ToolContext) -> dict[str, Any]:
    """
    tool_use: Score every signal in temp:raw_signals with the credibility algorithm.
    """
    try:
        raw = tool_context.state.get("temp:raw_signals", [])
        signals = _parse_raw_signals(raw)
        _emit_trace(
            "Raw signals need credibility weighting before fusion.",
            f"tool_use: score_signals_credibility on {len(signals)} SignalEvents.",
            "Compute source_rep, geo_conf, velocity, contradiction per signal.",
        )

        scored = score_signals(signals)
        tool_context.state["temp:scored_signals"] = [
            s.model_dump(mode="json") for s in scored
        ]

        contradictions = [s for s in scored if s.contradiction_factor > 0]
        _emit_trace(
            "Credibility scoring complete.",
            f"Scored {len(scored)} signals; {len(contradictions)} in contradictory zones.",
            "Store temp:scored_signals and return compact summary for LLM grouping.",
        )

        summary = [
            {
                "signal_id": s.signal_id,
                "credibility_score": s.credibility_score,
                "source_reputation": s.source_reputation,
                "geolocation_confidence": s.geolocation_confidence,
                "mention_velocity": s.mention_velocity,
                "contradiction_factor": s.contradiction_factor,
                "zone": s.signal.zone,
                "city": s.signal.city,
                "crisis_type": _normalize_crisis_type(s.signal.crisis_type),
                "summary": s.signal.summary[:120],
                "source": s.signal.source.value,
            }
            for s in scored
        ]
        spatial = build_spatial_clusters(scored)
        tool_context.state["temp:spatial_cluster_candidates"] = [
            c.model_dump(mode="json") for c in spatial
        ]

        return {
            "scored_count": len(scored),
            "contradiction_zones": len(contradictions),
            "spatial_candidate_count": len(spatial),
            "scored_signals": summary,
            "spatial_candidates": [
                {
                    "cluster_id": c.cluster_id,
                    "zone": c.zone,
                    "crisis_type": c.crisis_type,
                    "signal_ids": c.signal_ids,
                    "aggregate_credibility": c.aggregate_credibility,
                    "hypothesis_diversity_flag": c.hypothesis_diversity_flag,
                    "suspicious_flags": c.metadata.get("suspicious_flags", []),
                    "summaries": [s.summary[:80] for s in c.signals],
                }
                for c in spatial
            ],
        }
    except Exception as exc:  # noqa: BLE001
        _emit_trace(
            "Credibility scoring failed.",
            f"tool_use error: {exc}",
            "Propagate error to agent for recovery.",
        )
        return {"error": str(exc), "scored_count": 0}


FUSION_INSTRUCTION = f"""
You are the CIRO Signal Fusion & Credibility Agent.

{URDU_RULE}

Workflow (strict order):
1. Call `score_signals_credibility` once (tool_use). Do not skip this step.
2. call_llm: Review scored_signals and spatial_candidates from the tool.
   Merge or split clusters when summaries describe the same incident
   (semantic similarity) even if spatially separate, OR split when one
   spatial group mixes unrelated crisis types.
3. Return ONLY a raw JSON object (no markdown, no backticks) in this exact format:
    {{"clusters": [...]}}
   where each cluster has: cluster_id, city, zone, latitude, longitude, 
   crisis_type, signal_ids, aggregate_credibility, mention_velocity,
   hypothesis_diversity_flag, semantic_theme, metadata

Rules for semantic grouping:
- Combine clusters that clearly refer to the same event (e.g. flood + blocked road in G-10).
- Keep separate clusters for unrelated crises in the same city.
- Set aggregate_credibility to the weighted mean of member credibility scores
  (weight by geolocation_confidence).
- Preserve all signal_ids; copy full SignalEvent objects into each cluster.signals.
- Set semantic_theme to a short English label (e.g. "Urban flooding G-10").

Print [THOUGHT], [OBSERVATION], [ACTION] lines for each major step.
On [OBSERVATION] for step 2, include the prefix: call_llm: semantic grouping

Input signals are in session state as temp:raw_signals (already loaded by the tool).
"""


async def _persist_fused_clusters(callback_context) -> None:
    """Write agent FusionResult output to temp:fused_clusters."""
    state = callback_context.state
    raw_output = state.get("fusion_result") or state.get("temp:fusion_result")

    # reading from the agent response content directly f raw is not present
    if not raw_output:
        content = getattr(callback_context, "agent_response", None)
        if content:
            for part in getattr(content, "parts", []):
                text = getattr(part, "text", None)
                if text and "clusters" in text:
                    raw_output = text
                    break

    clusters: list[SignalCluster] = []
    if raw_output:
        if isinstance(raw_output, str):
            # Strip markdown fences if present
            raw_output = raw_output.strip().lstrip("```json").rstrip("```").strip()
            raw_output = json.loads(raw_output)
        try:
            llm_result = FusionResultLlm.model_validate(raw_output)
            clusters = [_hydrate_cluster(c, state) for c in llm_result.clusters]
        except Exception:
            try:
                result = FusionResult.model_validate(raw_output)
                clusters = [_enrich_cluster_from_signals(c) for c in result.clusters]
            except Exception:
                pass

    # Fallback to spatial candidates if LLM parsing fails
    if not clusters and state.get("temp:spatial_cluster_candidates"):
        clusters = [
            SignalCluster.model_validate(c)
            for c in state["temp:spatial_cluster_candidates"]
        ]

    state["temp:fused_clusters"] = [c.model_dump(mode="json") for c in clusters]
    _emit_trace(
        "Fusion output ready for downstream severity / situation agents.",
        f"Persisted {len(clusters)} clusters to temp:fused_clusters.",
        "Downstream agents may read aggregate_credibility per cluster.",
    )


signal_fusion_agent = LlmAgent(
    name="SignalFusionAgent",
    model=GEMINI_MODEL,
    description=(
        "Scores signal credibility, detects contradictions, and fuses correlated "
        "signals into incident clusters."
    ),
    instruction=FUSION_INSTRUCTION,
    tools=[FunctionTool(score_signals_credibility)],
    output_schema=FusionResultLlm,
    output_key="fusion_result",
    after_agent_callback=_persist_fused_clusters,
)

root_agent = signal_fusion_agent
