"""
CIRO root agent — central triage, operator commands, and pipeline delegation.

Live integrations on this agent:
- OpenWeatherMap One Call 3.0 via ``fetch_live_weather`` (ToolContext-aware LlmAgent tool).

Production integration point (not wired here):
- Google Maps Directions API for dispatch ETAs belongs on a dedicated routing
  service or pre-pipeline batch job. ``resource_allocator`` uses haversine @ 40 km/h
  because the greedy solver is a BaseAgent without ToolContext.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from pipeline.runner import incident_processing_pipeline
from schemas.models import ActiveCrisisEntry, CityConfig, WeatherSignalPayload

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATHS = (
    PROJECT_ROOT / "mock_data" / "ciro_all_datasets.json",
    PROJECT_ROOT / "mock_data" / "ciro_datasets.json",
)

TriageDecision = Literal["PIPELINE", "COMMAND", "QUERY", "DEGRADED"]

URDU_RULE = (
    "Input may be Urdu, Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

_URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_ROMAN_URDU_HINTS = (
    "paani",
    "pani",
    "aag",
    "hadsa",
    "bijli",
    "garmi",
    "lu",
    "selaab",
    "baadh",
    "rasta band",
    "madad",
    "karachi",
    "islamabad",
)


def _prefers_roman_urdu(message: str) -> bool:
    """Heuristic: if user writes Roman Urdu (or Urdu script), reply in Roman Urdu."""
    if not message:
        return False
    if _URDU_SCRIPT_RE.search(message):
        return True
    msg = message.lower()
    return any(h in msg for h in _ROMAN_URDU_HINTS)


def _reply(message: str, *, en: str, ru: str) -> str:
    """Choose Roman Urdu reply when user input suggests it."""
    return ru if _prefers_roman_urdu(message) else en


_PIPELINE_KEYWORDS = (
    "new alert",
    "signals received",
    "run scenario",
    "process",
    "t1_during",
    "flood",
    "selaab",
    "baadh",
    "heat",
    "garmi",
    "accident",
    "hadsa",
    "outage",
    "bijli gayi",
    "blockage",
    "rasta band",
)

_COMMAND_KEYWORDS = (
    "approve",
    "override",
    "escalate",
    "stand down",
    "cancel alert",
    "retract",
    "manual dispatch",
)

_QUERY_KEYWORDS = (
    "status",
    "what is happening",
    "what's happening",
    "active alert",
    "active crisis",
    "resource status",
    "zone risk",
    "how many incident",
    "current situation",
)

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


def _parse_city_config(raw: Any) -> CityConfig:
    if isinstance(raw, CityConfig):
        return raw
    if isinstance(raw, dict):
        return CityConfig.model_validate(raw)
    if isinstance(raw, str):
        return CityConfig.model_validate(json.loads(raw))
    return CityConfig(
        city="Islamabad",
        bbox_north=33.75,
        bbox_south=33.65,
        bbox_east=73.10,
        bbox_west=73.00,
        phase="T1_during",
    )


def _bbox_center(cfg: CityConfig) -> tuple[float, float]:
    lat = (cfg.bbox_north + cfg.bbox_south) / 2.0
    lng = (cfg.bbox_east + cfg.bbox_west) / 2.0
    return lat, lng


def _get_registry(state: dict[str, Any]) -> dict[str, Any]:
    reg = state.get("app:active_crisis_registry")
    if reg is None:
        reg = {}
        state["app:active_crisis_registry"] = reg
    if isinstance(reg, str):
        reg = json.loads(reg)
        state["app:active_crisis_registry"] = reg
    return reg


def _extract_user_text(callback_context: Any) -> str:
    content = getattr(callback_context, "user_content", None)
    if content is None:
        return str(callback_context.state.get("user_message", ""))
    if isinstance(content, str):
        return content
    parts = getattr(content, "parts", None) or []
    texts: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            texts.append(text)
    if texts:
        return " ".join(texts)
    if isinstance(content, dict):
        return json.dumps(content)
    return str(content)


def _raw_signals_present(state: dict[str, Any]) -> bool:
    raw = state.get("temp:raw_signals")
    if not raw:
        return False
    if isinstance(raw, str):
        raw = json.loads(raw)
    return bool(raw)


def _message_lower(message: str) -> str:
    return message.lower().strip()


def _has_scenario_token(message: str) -> bool:
    return bool(re.search(r"scn-00[1-5]", message, re.IGNORECASE))


def _detect_pipeline_trigger(message: str, state: dict[str, Any]) -> bool:
    if _raw_signals_present(state):
        return True
    msg = _message_lower(message)
    if _has_scenario_token(msg):
        return True
    return any(kw in msg for kw in _PIPELINE_KEYWORDS)


def _detect_command_trigger(message: str) -> bool:
    msg = _message_lower(message)
    return any(kw in msg for kw in _COMMAND_KEYWORDS)


def _detect_query_trigger(message: str) -> bool:
    msg = _message_lower(message)
    if any(kw in msg for kw in _QUERY_KEYWORDS):
        return True
    return bool(re.search(r"what is happening in\s+\S+", msg))


def determine_triage_path(
    message: str, state: dict[str, Any]
) -> tuple[TriageDecision, str]:
    """Deterministic triage (strict priority order from spec)."""
    if _detect_pipeline_trigger(message, state):
        reason = (
            "temp:raw_signals present"
            if _raw_signals_present(state)
            else f"pipeline keywords or scenario token in: {message[:80]}"
        )
        return "PIPELINE", reason
    if _detect_command_trigger(message):
        return "COMMAND", f"operator command keywords in: {message[:80]}"
    if _detect_query_trigger(message):
        return "QUERY", f"status query detected in: {message[:80]}"
    if _raw_signals_present(state):
        return "PIPELINE", "signals present — default to pipeline (never suppress)"
    return "PIPELINE", "uncertain input — default to PATH A per policy"


def _new_incident_id() -> str:
    return f"INCIDENT-{uuid.uuid4().hex[:6].upper()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_entry_from_state(
    incident_id: str,
    state: dict[str, Any],
    *,
    status: str = "PROCESSING",
) -> dict[str, Any]:
    cfg = _parse_city_config(state.get("city_config"))
    scenario = cfg.scenario_id
    return ActiveCrisisEntry(
        incident_id=incident_id,
        scenario_id=scenario,
        city=cfg.city,
        phase=cfg.phase,
        zone="TBD",
        crisis_type="pending",
        severity_level=1,
        status=status,
        created_at=_now_iso(),
        updated_at=_now_iso(),
        cluster_ids=[],
        resources_dispatched=[],
        notifications_sent=0,
    ).model_dump(mode="json")


def _start_pipeline_incident(state: dict[str, Any]) -> str:
    registry = _get_registry(state)
    incident_id = _new_incident_id()
    registry[incident_id] = _registry_entry_from_state(incident_id, state, status="PROCESSING")
    return incident_id


def _sync_registry_from_pipeline(state: dict[str, Any]) -> None:
    """Promote PROCESSING incidents using downstream pipeline outputs."""
    registry = _get_registry(state)
    cluster_ids: list[str] = []
    fused = state.get("temp:fused_clusters", [])
    if isinstance(fused, str):
        fused = json.loads(fused)
    for item in fused or []:
        cid = item.get("cluster_id") if isinstance(item, dict) else None
        if cid:
            cluster_ids.append(cid)

    classifications = state.get("temp:classified_clusters", [])
    if isinstance(classifications, str):
        classifications = json.loads(classifications)

    severity_records = state.get("temp:severity_records", [])
    if isinstance(severity_records, str):
        severity_records = json.loads(severity_records)

    for clf in classifications or []:
        if isinstance(clf, str):
            continue
        cluster_id = clf.get("cluster_id", "")
        inc_id = f"INCIDENT-{cluster_id.replace('CLU-', '')[:6].upper()}"
        existing = registry.get(inc_id)
        sev = next(
            (s for s in (severity_records or []) if s.get("cluster_id") == cluster_id),
            {},
        )
        zone = (clf.get("location") or {}).get("zone") or "TBD"
        entry = existing or _registry_entry_from_state(inc_id, state, status="ACTIVE")
        entry.update(
            {
                "incident_id": inc_id,
                "zone": zone,
                "crisis_type": clf.get("primary_classification", entry.get("crisis_type")),
                "severity_level": sev.get("severity_level", entry.get("severity_level", 1)),
                "status": "ACTIVE",
                "updated_at": _now_iso(),
                "cluster_ids": list({*entry.get("cluster_ids", []), cluster_id}),
            }
        )
        notif_count = len(state.get("final:notifications", []) or [])
        entry["notifications_sent"] = notif_count
        registry[inc_id] = entry

    for inc_id, entry in list(registry.items()):
        if entry.get("status") == "PROCESSING" and cluster_ids:
            entry["cluster_ids"] = cluster_ids
            entry["status"] = "ACTIVE"
            entry["updated_at"] = _now_iso()


def _handle_operator_command(message: str, state: dict[str, Any]) -> str:
    registry = _get_registry(state)
    msg = message.strip()
    lower = _message_lower(msg)
    now = _now_iso()

    approve = re.search(r"approve\s+([\w-]+)", lower)
    if approve:
        inc_id = approve.group(1).upper()
        if not inc_id.startswith("INCIDENT-"):
            inc_id = f"INCIDENT-{inc_id}"
        entry = registry.setdefault(inc_id, _registry_entry_from_state(inc_id, state))
        entry["status"] = "APPROVED"
        entry["updated_at"] = now
        entry["operator_override"] = msg
        return _reply(
            msg,
            en=f"Approved incident {inc_id}; status=APPROVED.",
            ru=f"Incident {inc_id} approve ho gaya. Status=APPROVED.",
        )

    override = re.search(
        r"override\s+severity\s+([\w-]+)\s+to\s+(\d)",
        lower,
    )
    if override:
        inc_id = override.group(1).upper()
        if not inc_id.startswith("INCIDENT-"):
            inc_id = f"INCIDENT-{inc_id}"
        level = int(override.group(2))
        entry = registry.setdefault(inc_id, _registry_entry_from_state(inc_id, state))
        entry["severity_level"] = max(1, min(5, level))
        entry["updated_at"] = now
        entry["operator_override"] = msg
        return _reply(
            msg,
            en=f"Override applied: {inc_id} severity_level={level}.",
            ru=f"Override apply ho gaya: {inc_id} severity_level={level}.",
        )

    stand_down = re.search(r"stand\s+down\s+([\w-]+)", lower)
    if stand_down:
        inc_id = stand_down.group(1).upper()
        if not inc_id.startswith("INCIDENT-"):
            inc_id = f"INCIDENT-{inc_id}"
        entry = registry.setdefault(inc_id, _registry_entry_from_state(inc_id, state))
        entry["status"] = "RETRACTED"
        entry["updated_at"] = now
        entry["operator_override"] = msg
        state["temp:retraction_required"] = True
        return _reply(
            msg,
            en=f"Stand down executed for {inc_id}; retraction path flagged.",
            ru=f"{inc_id} stand down kar diya. Retraction flag ho gaya.",
        )

    dispatch = re.search(
        r"manual\s+dispatch\s+([\w-]+)\s+to\s+([\w-]+)",
        lower,
    )
    if dispatch:
        resource_id = dispatch.group(1).upper()
        zone = dispatch.group(2).upper()
        inc_id = _new_incident_id()
        entry = _registry_entry_from_state(inc_id, state, status="ACTIVE")
        entry["zone"] = zone
        entry["resources_dispatched"] = [f"{resource_id}@{zone}"]
        entry["operator_override"] = msg
        registry[inc_id] = entry
        return _reply(
            msg,
            en=f"Manual dispatch logged: {resource_id} -> {zone} under {inc_id}.",
            ru=f"Manual dispatch note ho gaya: {resource_id} -> {zone} ({inc_id}).",
        )

    if "escalate" in lower:
        active = [e for e in registry.values() if e.get("status") in ("ACTIVE", "APPROVED")]
        if not active:
            return _reply(
                msg,
                en="No active incidents to escalate.",
                ru="Escalate ke liye koi active incident nahi.",
            )
        target = max(active, key=lambda e: e.get("severity_level", 1))
        target["severity_level"] = min(5, int(target.get("severity_level", 1)) + 1)
        target["updated_at"] = now
        target["operator_override"] = msg
        return _reply(
            msg,
            en=f"Escalated {target['incident_id']} to severity {target['severity_level']}.",
            ru=f"{target['incident_id']} ko severity {target['severity_level']} tak escalate kar diya.",
        )

    if "cancel alert" in lower or "retract" in lower:
        for entry in registry.values():
            if entry.get("status") in ("ACTIVE", "APPROVED"):
                entry["status"] = "RETRACTED"
                entry["updated_at"] = now
        state["temp:retraction_required"] = True
        return _reply(
            msg,
            en="Retraction applied to all active incidents.",
            ru="Sab active incidents par retraction apply kar di gayi.",
        )

    return _reply(
        msg,
        en=(
            "Command recognized but not parsed. Use: approve <id>, override severity "
            "<id> to <level>, stand down <id>, or manual dispatch <resource> to <zone>."
        ),
        ru=(
            "Command samajh aayi lekin parse nahi hui. Examples: approve <id>, "
            "override severity <id> to <level>, stand down <id>, manual dispatch <resource> to <zone>."
        ),
    )


def _format_status_query(state: dict[str, Any]) -> str:
    registry = _get_registry(state)
    active = [
        e
        for e in registry.values()
        if e.get("status") in ("PROCESSING", "ACTIVE", "APPROVED")
    ]
    if not active:
        return "Active crises: 0 | Highest severity: none | Zones affected: []"

    highest = max(int(e.get("severity_level", 1)) for e in active)
    zones = sorted({e.get("zone", "TBD") for e in active if e.get("zone")})
    return (
        f"Active crises: {len(active)} | Highest severity: {highest} | "
        f"Zones affected: {zones}"
    )


def _enter_degraded_mode(state: dict[str, Any], reason: str) -> str:
    raw = state.get("temp:raw_signals", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    signals = raw or []
    pending = state.setdefault("app:pending_human_review", [])
    if isinstance(pending, str):
        pending = json.loads(pending)
        state["app:pending_human_review"] = pending
    for sig in signals:
        if isinstance(sig, dict):
            pending.append(sig)
    n = len(signals)
    state["triage_decision"] = "DEGRADED"
    state["app:degraded_mode"] = True
    state["triage_reasoning"] = reason
    response = (
        f"CIRO operating in degraded mode. Human operator required. "
        f"{n} signals queued for review."
    )
    state["operator_response"] = response
    _emit_trace(
        "LLM triage failed or signals could not be routed automatically.",
        f"call_llm: triage reasoning — path=DEGRADED ({reason})",
        f"DEGRADED MODE: Escalating {n} signals to human operator. "
        "All automatic dispatch suspended. Awaiting manual approval.",
    )
    return response


def _apply_triage(
    decision: TriageDecision,
    reasoning: str,
    message: str,
    state: dict[str, Any],
) -> None:
    state["triage_decision"] = decision
    state["triage_reasoning"] = reasoning

    if decision == "PIPELINE":
        incident_id = _start_pipeline_incident(state)
        _emit_trace(
            f"Incoming request requires full pipeline ({reasoning}).",
            "call_llm: triage reasoning — path=PIPELINE (pipeline is next sequential step)",
            f"Registered {incident_id} in app:active_crisis_registry with status=PROCESSING.",
        )
        state["operator_response"] = _reply(
            message,
            en=f"Pipeline triggered for incident {incident_id}. Processing signals.",
            ru=f"Pipeline start ho gaya (incident {incident_id}). Signals process ho rahe hain.",
        )
        return

    if decision == "COMMAND":
        response = _handle_operator_command(message, state)
        state["operator_response"] = response
        _emit_trace(
            f"Operator command path ({reasoning}).",
            "call_llm: triage reasoning — path=COMMAND",
            f"Updated app:active_crisis_registry per operator command.",
        )
        return

    if decision == "QUERY":
        summary = _format_status_query(state)
        response = _reply(
            message,
            en=summary,
            ru=summary,  # Roman Urdu UI: keep numeric/status string identical
        )
        state["operator_response"] = response
        _emit_trace(
            f"Status query path ({reasoning}).",
            "call_llm: triage reasoning — path=QUERY",
            "Read app:active_crisis_registry; no mutation required.",
        )
        return


def _fetch_ds002_fallback(city: str, phase: str) -> WeatherSignalPayload:
    snapshots_root = _load_db().get("DS-002", {}).get("snapshots", {})
    snap: Optional[dict[str, Any]] = None
    for _scenario_id, phases in snapshots_root.items():
        candidate = phases.get(phase) or phases.get("T1_during")
        if candidate and candidate.get("city", "").lower() == city.lower():
            snap = candidate
            break
    if not snap:
        snap = {
            "city": city,
            "temperature_c": 30.0,
            "rainfall_mm_per_hour": 0.0,
            "alert_level": "LOW",
            "flood_risk_score": 0.2,
            "agent_trigger": "NO_ACTION",
            "timestamp": _now_iso(),
        }
    lat, lng = 33.70, 73.05
    return WeatherSignalPayload(
        city=snap.get("city", city),
        latitude=lat,
        longitude=lng,
        timestamp=datetime.fromisoformat(
            str(snap.get("timestamp", _now_iso())).replace("Z", "+00:00")
        ),
        temperature_c=float(snap.get("temperature_c", 30.0)),
        feels_like_c=snap.get("feels_like_c"),
        humidity_percent=snap.get("humidity_percent"),
        rainfall_mm_per_hour=float(snap.get("rainfall_mm_per_hour", 0.0)),
        wind_speed_kmh=snap.get("wind_speed_kmh"),
        alert_type=snap.get("alert_type"),
        alert_level=str(snap.get("alert_level", "LOW")),
        flood_risk_score=float(snap.get("flood_risk_score", 0.0)),
        forecast_next_2hr=snap.get("forecast_next_2hr"),
        agent_trigger=str(snap.get("agent_trigger", "NO_ACTION")),
        threshold_breached=bool(snap.get("threshold_breached")),
        source_status="STALE",
        raw=snap,
    )


def _map_openweather(data: dict[str, Any], city: str, lat: float, lng: float) -> WeatherSignalPayload:
    current = data.get("current", {})
    temp = float(current.get("temp", 30.0))
    rain_block = current.get("rain") or {}
    rainfall_1h = float(rain_block.get("1h", 0.0) or 0.0)
    humidity = current.get("humidity")
    wind = current.get("wind_speed")
    if wind is not None:
        wind = float(wind) * 3.6

    agent_trigger = "NO_ACTION"
    alert_level = "LOW"
    threshold_breached = False
    if rainfall_1h > 25:
        agent_trigger = "ESCALATE_FLOOD_ALERT"
        alert_level = "HIGH"
        threshold_breached = True
    elif temp > 42:
        agent_trigger = "EXTREME_HEAT_EMERGENCY"
        alert_level = "HIGH"
        threshold_breached = True

    flood_risk = min(1.0, rainfall_1h / 50.0) if rainfall_1h else 0.1
    ts = datetime.fromtimestamp(current.get("dt", datetime.now(timezone.utc).timestamp()), tz=timezone.utc)

    return WeatherSignalPayload(
        city=city,
        latitude=lat,
        longitude=lng,
        timestamp=ts,
        temperature_c=temp,
        feels_like_c=current.get("feels_like"),
        humidity_percent=int(humidity) if humidity is not None else None,
        rainfall_mm_per_hour=rainfall_1h,
        wind_speed_kmh=wind,
        alert_type="WEATHER_ALERT" if threshold_breached else None,
        alert_level=alert_level,
        flood_risk_score=round(flood_risk, 3),
        forecast_next_2hr=data.get("hourly", [{}])[0].get("summary") if data.get("hourly") else None,
        agent_trigger=agent_trigger,
        threshold_breached=threshold_breached,
        source_status="LIVE",
        raw=current,
    )


async def fetch_live_weather(city: str, tool_context: ToolContext) -> dict[str, Any]:
    """Fetch live weather from OpenWeatherMap One Call 3.0; fall back to DS-002.

    Sole live API tool on CIRORoot. Dispatch routing ETAs stay in the allocator
    (haversine mock); see resource_allocator._travel_time_mins for Maps notes.
    """
    cfg = _parse_city_config(tool_context.state.get("city_config"))
    phase = cfg.phase
    lat, lng = _bbox_center(cfg)
    api_key = os.getenv("OPENWEATHER_API_KEY", "")

    _emit_trace(
        f"Live environmental context needed for {city}.",
        f"tool_use: fetch_live_weather — lat={lat:.4f}, lng={lng:.4f}",
        "Call OpenWeatherMap One Call 3.0; map to WeatherSignalPayload.",
    )

    if not api_key or api_key.startswith("your_"):
        payload = _fetch_ds002_fallback(city or cfg.city, phase)
        tool_context.state["temp:live_weather"] = payload.model_dump(mode="json")
        _emit_trace(
            "API key missing — using mock DS-002 weather.",
            f"STALE fallback for {payload.city}; agent_trigger={payload.agent_trigger}",
            "Stored temp:live_weather with source_status=STALE.",
        )
        return payload.model_dump(mode="json")

    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {"lat": lat, "lon": lng, "appid": api_key, "units": "metric"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        payload = _map_openweather(data, city or cfg.city, lat, lng)
        tool_context.state["temp:live_weather"] = payload.model_dump(mode="json")
        _emit_trace(
            "OpenWeatherMap response received.",
            f"LIVE weather: {payload.rainfall_mm_per_hour}mm/hr, {payload.temperature_c}°C",
            f"agent_trigger={payload.agent_trigger}",
        )
        return payload.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        payload = _fetch_ds002_fallback(city or cfg.city, phase)
        tool_context.state["temp:live_weather"] = payload.model_dump(mode="json")
        _emit_trace(
            "OpenWeatherMap call failed.",
            f"tool_use error: {exc}",
            "Fell back to DS-002 mock; source_status=STALE.",
        )
        return payload.model_dump(mode="json")


TRIAGE_INSTRUCTION = f"""
You are CIRORoot Triage, the first step of CIRO central command for urban crisis
management in Pakistan (Islamabad and Karachi).

{URDU_RULE}

You classify each request. IncidentProcessingPipeline runs automatically immediately
after you finish — do NOT attempt agent transfer or call any tool except the one listed.

TOOLS (strict):
- You have exactly ONE tool: fetch_live_weather(city).
- NEVER call set_session_state, set_state, update_state, or any other function name.
  Those tools do not exist. Session keys (triage_decision, operator_response) are
  written by the system callback after your turn — you cannot set them via tools.

Decision rules (strict priority order):
1. If temp:raw_signals exists in state with signals present → PATH A (PIPELINE)
2. If message contains operator command keywords → PATH B (COMMAND)
3. If message is a status question → PATH C (QUERY)
4. If uncertain → default to PATH A (never suppress signals)

Critical constraints:
- Never issue public alerts directly (NotificationAgent runs in the pipeline step).
- When in doubt between PIPELINE and COMMAND, choose PIPELINE.
- Reply to the user in Roman Urdu if they wrote Roman Urdu/mixed; otherwise English.

On every decision, print:
[THOUGHT] what you understood from the input and why you chose this path
[OBSERVATION] call_llm: triage reasoning — path=PIPELINE|COMMAND|QUERY
[ACTION] brief note (registry updates are applied by the system, not by tools)

PATH A (PIPELINE): explain that the pipeline will run. Call fetch_live_weather only
  when live weather helps (optional).
PATH B (COMMAND): acknowledge the operator command in your reply text.
PATH C (QUERY): summarize active crises in your reply (counts, severity, zones).

Do not invent tools. Do not output function calls except fetch_live_weather.
"""


async def _finalize_triage_step(callback_context: Any) -> None:
    """Apply deterministic triage state after the LlmAgent (before pipeline runs).

    The LLM must not call set_session_state — only fetch_live_weather exists.
    This callback always sets triage_decision, triage_reasoning, operator_response.
    """
    state = callback_context.state
    message = _extract_user_text(callback_context)

    try:
        decision, reasoning = determine_triage_path(message, state)
        _apply_triage(decision, reasoning, message, state)
    except Exception as exc:  # noqa: BLE001
        _enter_degraded_mode(state, f"exception during triage: {exc}")


async def _finalize_ciro_root(callback_context: Any) -> None:
    """After triage + pipeline sequential run: sync registry from pipeline outputs."""
    state = callback_context.state
    if state.get("triage_decision") == "PIPELINE":
        _sync_registry_from_pipeline(state)
        _emit_trace(
            "IncidentProcessingPipeline sequential step completed.",
            "agent_transfer: IncidentProcessingPipeline finished (SequentialAgent step 2)",
            "Synced app:active_crisis_registry from pipeline outputs.",
        )


triage_agent = LlmAgent(
    name="CIRORootTriage",
    model=GEMINI_MODEL,
    description=(
        "Classifies operator requests; triage_decision is set in after_agent_callback "
        "(tools: fetch_live_weather only)."
    ),
    instruction=TRIAGE_INSTRUCTION,
    tools=[FunctionTool(fetch_live_weather)],
    after_agent_callback=_finalize_triage_step,
)

# SequentialAgent guarantees pipeline runs after triage (no LLM agent_transfer).
root_agent = SequentialAgent(
    name="CIRORoot",
    description=(
        "Central CIRO entry: triage LlmAgent then IncidentProcessingPipeline "
        "(fuse → classify → severity → allocate → notify)."
    ),
    sub_agents=[triage_agent, incident_processing_pipeline],
    after_agent_callback=_finalize_ciro_root,
)
