"""
Notification & communication agent — LlmAgent + inner VerificationLoop (LoopAgent).

Generates audience-specific alerts (6 groups), DS-007 reach, false-alarm retraction,
writes ``final:notifications`` and ``final:incident_record``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools import exit_loop
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import (
    AllocationPlan,
    CityConfig,
    ClassifiedIncident,
    FinalIncidentRecord,
    NotificationBatch,
    NotificationRecord,
    SeverityAssessment,
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
    "Input may be Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

AUDIENCES = (
    "GENERAL_PUBLIC",
    "EMERGENCY_SERVICES",
    "HOSPITALS",
    "UTILITY_COMPANIES",
    "TRANSPORT_AUTHORITY",
    "MEDIA_COMMAND_CENTER",
)

AUDIENCE_CHANNELS: dict[str, list[str]] = {
    "GENERAL_PUBLIC": ["push_notification", "sms", "app_alert"],
    "EMERGENCY_SERVICES": ["internal_dispatch", "websocket"],
    "HOSPITALS": ["email", "push"],
    "UTILITY_COMPANIES": ["api_webhook"],
    "TRANSPORT_AUTHORITY": ["dashboard", "api"],
    "MEDIA_COMMAND_CENTER": ["dashboard", "pdf_brief"],
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


def _sync_pipeline_aliases(state: dict[str, Any]) -> None:
    """Map canonical temp keys to notification-agent input names."""
    if "temp:classified_incidents" not in state and state.get("temp:classified_clusters"):
        state["temp:classified_incidents"] = state["temp:classified_clusters"]
    if "temp:severity_assessments" not in state and state.get("temp:severity_records"):
        state["temp:severity_assessments"] = state["temp:severity_records"]


def _parse_incidents(raw: Any) -> list[ClassifiedIncident]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [
        i if isinstance(i, ClassifiedIncident) else ClassifiedIncident.model_validate(i)
        for i in raw
    ]


def _parse_severity(raw: Any) -> list[SeverityAssessment]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [
        s if isinstance(s, SeverityAssessment) else SeverityAssessment.model_validate(s)
        for s in raw
    ]


def _parse_allocation(raw: Any) -> AllocationPlan:
    if not raw:
        return AllocationPlan()
    if isinstance(raw, str):
        raw = json.loads(raw)
    return AllocationPlan.model_validate(raw)


def _parse_clusters(raw: Any) -> dict[str, SignalCluster]:
    if not raw:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    clusters = [
        c if isinstance(c, SignalCluster) else SignalCluster.model_validate(c)
        for c in raw
    ]
    return {c.cluster_id: c for c in clusters}


def _zone_id_for_name(zone_name: Optional[str], city: str) -> str:
    if not zone_name:
        return "ZN-ISB-001"
    key = zone_name.strip().lower()
    for zone in _load_db().get("DS-005", {}).get("zones", []):
        if zone.get("city", "").lower() != city.lower():
            continue
        names = {zone.get("zone_name", "").lower(), *[
            a.lower() for a in (zone.get("zone_alias") or [])
        ]}
        if key in names or any(key in n or n in key for n in names if n):
            return zone["zone_id"]
    return "ZN-ISB-001"


def _incident_id(cluster_id: str) -> str:
    return f"INCIDENT-{cluster_id.replace('CLU-', '')[:6].upper()}"


async def calculate_alert_reach(zone_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """tool_use: DS-007 notification registry reach for a zone."""
    _sync_pipeline_aliases(tool_context.state)
    registry = _load_db().get("DS-007", {}).get("registry", [])
    entry = next((r for r in registry if r.get("zone_id") == zone_id), None)

    if not entry:
        _emit_trace(
            f"No DS-007 registry row for {zone_id}; use conservative defaults.",
            f"tool_use: calculate_alert_reach — zone_id={zone_id} not found.",
            "Return zero reach and flag for manual review.",
        )
        return {
            "sms_reach": 0,
            "whatsapp_reach": 0,
            "app_push_reach": 0,
            "email_reach": 0,
            "total_reach": 0,
            "preferred_language": "urdu",
            "fm_channel": None,
            "delivery_rate": 0.0,
        }

    sms = int(entry.get("sms_enabled_count", 0))
    whatsapp = int(entry.get("whatsapp_enabled_count", 0))
    app_push = int(entry.get("app_push_enabled_count", 0))
    email = int(entry.get("email_enabled_count", 0))
    total = int(entry.get("estimated_reach_per_alert", sms + app_push))
    delivery = float(entry.get("avg_alert_open_rate_percent", 78.0)) / 100.0

    _emit_trace(
        f"Public alerts for {entry.get('zone_name')} must use DS-007 reach only.",
        f"tool_use: calculate_alert_reach — reach={total}, delivery={delivery:.1%}, "
        f"preferred_language={entry.get('preferred_language')}.",
        f"Load FM channel {entry.get('radio_fm_channel')} for GENERAL_PUBLIC.",
    )

    return {
        "sms_reach": sms,
        "whatsapp_reach": whatsapp,
        "app_push_reach": app_push,
        "email_reach": email,
        "total_reach": total,
        "preferred_language": entry.get("preferred_language", "urdu"),
        "fm_channel": entry.get("radio_fm_channel"),
        "delivery_rate": round(delivery, 3),
    }


def _run_verification(state: dict[str, Any]) -> dict[str, Any]:
    _sync_pipeline_aliases(state)
    incidents = _parse_incidents(state.get("temp:classified_incidents", []))
    clusters = _parse_clusters(state.get("temp:fused_clusters", []))
    low_confidence: list[str] = []
    verified_all = True
    reason_parts: list[str] = []

    for inc in incidents:
        cluster = clusters.get(inc.cluster_id)
        credibility = cluster.aggregate_credibility if cluster else 0.0
        signal_count = len(cluster.signals) if cluster else 0
        flags = cluster.metadata.get("suspicious_flags", []) if cluster else []
        single_source = "UNVERIFIED_SINGLE_SOURCE" in flags or signal_count <= 1

        fails = (
            inc.requires_verification
            or credibility < 0.45
            or single_source
        )
        if fails:
            verified_all = False
            low_confidence.append(inc.cluster_id)
            reason_parts.append(
                f"{inc.cluster_id}: credibility={credibility:.2f}, "
                f"signals={signal_count}, requires_verification={inc.requires_verification}"
            )

    reason = (
        "All incidents verified."
        if verified_all
        else "; ".join(reason_parts) or "Verification criteria not met."
    )
    return {
        "verified": verified_all,
        "reason": reason,
        "incidents_checked": len(incidents),
        "low_confidence_incidents": low_confidence,
    }


async def verify_incident_status(tool_context: ToolContext) -> dict[str, Any]:
    """tool_use: false-alarm verification check before sending alerts."""
    result = _run_verification(tool_context.state)
    iteration = int(tool_context.state.get("temp:verification_iterations", 0)) + 1
    tool_context.state["temp:verification_iterations"] = iteration
    tool_context.state["temp:verification_result"] = result

    if result["verified"]:
        tool_context.state["temp:retraction_required"] = False
    elif iteration >= 3:
        tool_context.state["temp:retraction_required"] = True

    _emit_trace(
        "False alarms erode public trust — verify before notifying.",
        f"tool_use: verify_incident_status — verified={result['verified']}, "
        f"iteration={iteration}, reason={result['reason'][:120]}",
        "Call exit_loop if verified; else continue VerificationLoop.",
    )
    return {**result, "iteration": iteration}


async def send_notification(
    audience: str,
    channel: str,
    message: str,
    zone_id: str,
    incident_id: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """tool_use: mock notification send (no external API)."""
    reach_data = await calculate_alert_reach(zone_id, tool_context)
    now = datetime.now(timezone.utc)
    delivery = reach_data.get("delivery_rate", 0.94)

    _emit_trace(
        f"{audience} needs tailored messaging on {channel}.",
        f"tool_use: send_notification — reach={reach_data['total_reach']}, "
        f"delivery={delivery:.1%}",
        f"Mock SENT {audience}/{channel} for {incident_id} in {zone_id}.",
    )

    record = {
        "status": "SENT",
        "audience": audience,
        "channel": channel,
        "message_preview": message[:100],
        "reach": reach_data["total_reach"],
        "timestamp": now.isoformat(),
        "delivery_rate": delivery,
        "simulation_note": "Mock send — real Twilio/FCM endpoint here in production",
    }
    log = tool_context.state.setdefault("temp:notification_log", [])
    if isinstance(log, str):
        log = json.loads(log)
    log.append(record)
    tool_context.state["temp:notification_log"] = log
    return record


VERIFICATION_INSTRUCTION = f"""
You are the CIRO Verification Loop step (max 3 iterations).

{URDU_RULE}

Each iteration:
1. Call verify_incident_status (tool_use).
2. If verified=True: immediately call exit_loop and stop.
3. If verified=False and iteration < 3: end turn (loop continues).
4. If verified=False and iteration >= 3: set retraction path and call exit_loop.

Print [THOUGHT], [OBSERVATION] (prefix tool_use:), [ACTION] every iteration.
"""


NOTIFICATION_INSTRUCTION = f"""
You are the CIRO Notification & Communication Agent.

{URDU_RULE}

Your job is to generate precise, audience-specific emergency alerts.

Strict workflow (verification already completed by VerificationLoop — do not re-verify):
1. Read temp:verification_result and temp:retraction_required from session state.
   If retraction required: jump to step 5.
2. Call calculate_alert_reach for each affected zone (tool_use).
3. call_llm: Generate message for GENERAL_PUBLIC — English + Roman Urdu.
4. call_llm: Generate messages for remaining 5 audiences — English only.
5. Call send_notification for each audience+channel combination (tool_use).
6. If retraction: call_llm to generate retraction messages, then send.
7. Compile NotificationBatch and write to final:notifications.

Print [THOUGHT], [OBSERVATION], [ACTION] for every step.
On step 3-4 observations use prefix: call_llm:
On step 2,5 observations use prefix: tool_use:

Never invent reach numbers — always use calculate_alert_reach tool result.
Never skip an audience — all 6 must receive a message or explicit STAND_DOWN.

Read inputs from session state:
- temp:allocation_plan
- temp:severity_assessments (or temp:severity_records)
- temp:classified_incidents (or temp:classified_clusters)
- temp:verification_result / temp:retraction_required after VerificationLoop
- city_config

Return NotificationBatch JSON as output_schema.
"""


def _crisis_label(slug: str) -> str:
    return slug.upper().replace("_", " ")


def build_notifications_heuristic(
    incidents: list[ClassifiedIncident],
    severity_list: list[SeverityAssessment],
    allocation: AllocationPlan,
    clusters: dict[str, SignalCluster],
    city: str,
    retraction: bool = False,
) -> NotificationBatch:
    """Deterministic notification batch when LLM output is unavailable."""
    severity_by_id = {s.cluster_id: s for s in severity_list}
    notifications: list[NotificationRecord] = []
    total_reach = 0
    incident_ids: list[str] = []

    for inc in incidents:
        inc_id = _incident_id(inc.cluster_id)
        incident_ids.append(inc_id)
        sev = severity_by_id.get(inc.cluster_id)
        cluster = clusters.get(inc.cluster_id)
        zone_name = inc.location.zone or "G-10"
        zone_id = _zone_id_for_name(zone_name, city)
        reach_row = _load_db().get("DS-007", {}).get("registry", [])
        entry = next((r for r in reach_row if r.get("zone_id") == zone_id), {})
        reach = int(entry.get("estimated_reach_per_alert", 12000))
        delivery = float(entry.get("avg_alert_open_rate_percent", 78.0)) / 100.0
        fm = entry.get("radio_fm_channel")
        now = datetime.now(timezone.utc)
        ctype = _crisis_label(inc.primary_classification)
        lat = inc.location.lat or 33.72
        lon = inc.location.lon or 73.04

        if retraction:
            pub_en = (
                f"Earlier alert for {zone_name} has been cancelled. "
                "No emergency confirmed. Apologies for the inconvenience."
            )
            pub_ur = (
                "Pehle wali alert cancel kar di gayi hai. Koi emergency confirm nahi hui."
            )
            em_en = (
                f"STAND DOWN — {inc_id} retracted. False alarm confirmed. "
                "All units return to base."
            )
            messages = [
                ("GENERAL_PUBLIC", "sms", pub_en, pub_ur),
                ("EMERGENCY_SERVICES", "internal_dispatch", em_en, None),
            ]
        else:
            shelter = "F-7 shelter"
            pub_en = (
                f"{ctype} reported in {zone_name}. Avoid main roads. "
                f"Move to {shelter} now."
            )
            pub_ur = (
                f"{zone_name} mein {ctype.lower()} ki soorat-e-haal hai. "
                f"Markaz Road se door rahein. Abhi {shelter} jayein."
            )
            pop = sev.population_at_risk if sev else 500
            cas_low = max(5, pop // 200)
            cas_high = max(cas_low + 5, pop // 100)
            alloc = next(
                (a for a in allocation.allocations if a.cluster_id == inc.cluster_id),
                None,
            )
            units = []
            if alloc:
                for asn in alloc.assignments:
                    if asn.assigned_count > 0 and asn.assigned_unit_ids:
                        units.append(asn.assigned_unit_ids[0])
            unit_str = " | ".join(units[:2]) or "RSC-001 dispatched"
            em_en = (
                f"{inc_id} | {ctype} | {zone_name} | {lat:.4f},{lon:.4f} | "
                f"{unit_str} ETA 8min | Priority: "
                f"{sev.severity_label.upper() if sev else 'HIGH'}"
            )
            hosp_en = (
                f"Estimated {cas_low}-{cas_high} trauma cases inbound. "
                f"{ctype}-related injuries. Prepare emergency ward. "
                "First arrivals in ~20 minutes."
            )
            util_en = (
                f"Grid zone {zone_id} degraded. Outage scope ~18%. "
                "Escalation requested. Estimated restore 4h."
            )
            transport_en = (
                f"Affected roads in {zone_name} per DS-003. "
                "Reroute via adjacent zones. Expect diversion congestion +0.15."
            )
            media_en = (
                f"CIRO briefing: {ctype} in {zone_name}. Status ACTIVE. "
                f"Resources deployed. Severity "
                f"{sev.severity_level if sev else 3}/5. Zones: {zone_name}."
            )
            messages = [
                ("GENERAL_PUBLIC", "sms", pub_en, pub_ur),
                ("GENERAL_PUBLIC", "push_notification", pub_en, pub_ur),
                ("EMERGENCY_SERVICES", "internal_dispatch", em_en, None),
                ("HOSPITALS", "email", hosp_en, None),
                ("UTILITY_COMPANIES", "api_webhook", util_en, None),
                ("TRANSPORT_AUTHORITY", "dashboard", transport_en, None),
                ("MEDIA_COMMAND_CENTER", "pdf_brief", media_en, None),
            ]

        for audience, channel, msg_en, msg_ur in messages:
            notifications.append(
                NotificationRecord(
                    notification_id=f"NTF-{uuid.uuid4().hex[:8]}",
                    incident_id=inc_id,
                    audience=audience,
                    channel=channel,
                    message_en=msg_en,
                    message_ur=msg_ur,
                    zone_id=zone_id,
                    reach=reach,
                    delivery_rate=delivery,
                    fm_channel=fm if audience == "GENERAL_PUBLIC" else None,
                    status="RETRACTED" if retraction else "SENT",
                    timestamp=now,
                    retraction=retraction,
                )
            )
            total_reach += reach

    return NotificationBatch(
        notifications=notifications,
        total_reach=total_reach,
        retraction_issued=retraction,
        verified=not retraction,
        incident_ids=incident_ids,
    )


async def _persist_final_outputs(callback_context) -> None:
    state = callback_context.state
    raw = state.get("notification_batch")

    if not raw:
        content = getattr(callback_context, "agent_response", None)
        if content:
            for part in getattr(content, "parts", []):
                text = getattr(part, "text", None)
                if text and "notifications" in text:
                    raw = text.strip().lstrip("```json").rstrip("```").strip()
                    break

    batch = None  # initialize before both branches

    if raw:
        if isinstance(raw, str):
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            try:
                raw = json.loads(raw)
            except Exception:
                pass
        try:
            batch = NotificationBatch.model_validate(raw)
        except Exception as e:
            print(f"[NOTIFY] Parse error: {e}")

    if batch is None:  # fallback covers both "no raw" and "parse failed"
        verification = state.get("temp:verification_result", {})
        if isinstance(verification, str):
            verification = json.loads(verification)
        retraction = bool(
            state.get("temp:retraction_required")
            or not verification.get("verified", True)
        )
        batch = build_notifications_heuristic(
            _parse_incidents(state.get("temp:classified_incidents", [])),
            _parse_severity(state.get("temp:severity_assessments", [])),
            _parse_allocation(state.get("temp:allocation_plan", {})),
            _parse_clusters(state.get("temp:fused_clusters", {})),
            city=(
                state.get("city_config", {}).get("city", "Islamabad")
                if isinstance(state.get("city_config"), dict)
                else "Islamabad"
            ),
            retraction=retraction,
        )

    # now batch is always defined
    state["final:notifications"] = [n.model_dump(mode="json") for n in batch.notifications]


    allocation = _parse_allocation(state.get("temp:allocation_plan", {}))
    severity = _parse_severity(state.get("temp:severity_assessments", []))
    incidents = _parse_incidents(state.get("temp:classified_incidents", []))

    final_record = FinalIncidentRecord(
        incident_ids=batch.incident_ids,
        verified=batch.verified,
        retraction_issued=batch.retraction_issued,
        notifications=batch.notifications,
        allocation_summary={
            "crises_count": allocation.crises_count,
            "unmet_demand": allocation.unmet_demand,
            "trade_off_summary": allocation.trade_off_summary,
        },
        severity_summary=[s.model_dump(mode="json") for s in severity],
        classification_summary=[i.model_dump(mode="json") for i in incidents],
    )
    state["final:incident_record"] = final_record.model_dump(mode="json")

    _emit_trace(
        "Notification pipeline complete.",
        f"final:notifications count={len(batch.notifications)}, "
        f"total_reach={batch.total_reach}, retraction={batch.retraction_issued}.",
        "Persisted final:incident_record for API layer.",
    )


verification_step_agent = LlmAgent(
    name="VerificationStep",
    model=GEMINI_MODEL,
    description="Verification loop step — checks incident credibility before alerts.",
    instruction=VERIFICATION_INSTRUCTION,
    tools=[FunctionTool(verify_incident_status), exit_loop],
)

verification_loop = LoopAgent(
    name="VerificationLoop",
    description="False-alarm verification retraction loop (max 3 iterations).",
    max_iterations=3,
    sub_agents=[verification_step_agent],
)

notification_llm_agent = LlmAgent(
    name="NotificationCommunicator",
    model=GEMINI_MODEL,
    description=(
        "Generates bilingual, audience-specific emergency notifications "
        "with DS-007 reach and mock dispatch."
    ),
    instruction=NOTIFICATION_INSTRUCTION,
    tools=[
        FunctionTool(calculate_alert_reach),
        FunctionTool(send_notification),
    ],
    # output_schema=NotificationBatch,
    # output_key="notification_batch",
)

# LlmAgent (outer) orchestration wrapping inner VerificationLoop, then communicator
notification_agent = SequentialAgent(
    name="NotificationAgent",
    description=(
        "Notification agent: VerificationLoop (LoopAgent, max 3) then "
        "LlmAgent message generation for 6 stakeholder audiences."
    ),
    sub_agents=[verification_loop, notification_llm_agent],
    after_agent_callback=_persist_final_outputs,
)

root_agent = notification_agent
