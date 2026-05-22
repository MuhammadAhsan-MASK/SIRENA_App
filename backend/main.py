"""
CIRO FastAPI gateway — REST, SSE, and WebSocket over the ADK agent pipeline.
"""

from __future__ import annotations

import asyncio
import builtins
import contextvars
import importlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.genai import types
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agents.agent import root_agent
from agents.services import ciro_session_service
from schemas.models import (
    CityConfig,
    FinalIncidentRecord,
    SignalEvent,
    SignalSource,
)

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_PATH = PROJECT_ROOT / "mock_data" / "ciro_datasets.json"

APP_NAME = "ciro"
FLUTTER_USER_ID = "flutter"

# Module-level registries (persist across requests)
session_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
GLOBAL_CRISIS_REGISTRY: dict[str, dict[str, Any]] = {}
INCIDENT_SESSION_INDEX: dict[str, str] = {}
active_websockets: dict[str, set[WebSocket]] = {}

current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "ciro_session_id", default=None
)

_CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "Islamabad": (33.75, 33.65, 73.10, 73.00),
    "Karachi": (25.05, 24.75, 67.20, 66.95),
}

_TRACE_MODULES = (
    "agents.root_agent",
    "intake.urdu_intake",
    "agents.signal_ingestion",
    "agents.signal_fusion",
    "agents.crisis_classifier",
    "agents.severity_predictor",
    "agents.resource_allocator",
    "agents.notification_agent",
    "agents.action",
)

_MODULE_AGENT_NAMES: dict[str, str] = {
    "agents.root_agent": "CIRORoot",
    "intake.urdu_intake": "UrduIntakeAgent",
    "agents.signal_ingestion": "SignalIngestionAgent",
    "agents.signal_fusion": "SignalFusionAgent",
    "agents.crisis_classifier": "CrisisClassifierAgent",
    "agents.severity_predictor": "SeverityPredictorAgent",
    "agents.resource_allocator": "ResourceAllocatorAgent",
    "agents.notification_agent": "NotificationAgent",
    "agents.action": "ActionSimulationAgent",
}

_OFFICIAL_ROLES = frozenset({"health_worker", "official", "itp_warden", "cda_warden"})

_runner: Optional[Runner] = None
_db_cache: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str
    city: Optional[str] = None
    scenario_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    triage_decision: str
    incident_id: Optional[str] = None
    done: bool = True


class FieldReportRequest(BaseModel):
    text: str
    zone: str
    city: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    reporter_role: Optional[str] = None
    session_id: str


class FieldReportResponse(BaseModel):
    signal_id: str
    status: str
    session_id: str


# ---------------------------------------------------------------------------
# Trace + streaming
# ---------------------------------------------------------------------------


def _emit_api_trace(thought: str, observation: str, action: str) -> None:
    print(f"[THOUGHT] {thought}")
    print(f"[OBSERVATION] {observation}")
    print(f"[ACTION] {action}")


def _get_queue(session_id: str) -> asyncio.Queue[dict[str, Any]]:
    if session_id not in session_queues:
        session_queues[session_id] = asyncio.Queue(maxsize=500)
    return session_queues[session_id]


def _enqueue_event(session_id: Optional[str], event: dict[str, Any]) -> None:
    if not session_id:
        return
    queue = session_queues.get(session_id)
    if queue is None:
        return
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


class StreamingTraceInterceptor:
    """Redirect agent _emit_trace and [THOUGHT] prints to per-session SSE queues."""

    def __init__(self) -> None:
        self._original_print = builtins.print
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        for module_name in _TRACE_MODULES:
            try:
                mod = importlib.import_module(module_name)
            except ImportError:
                continue
            if not hasattr(mod, "_emit_trace"):
                continue
            original = mod._emit_trace

            def make_wrapper(
                orig: Any, mod_name: str = module_name
            ) -> Any:
                def wrapped(thought: str, observation: str, action: str) -> None:
                    self._publish_trace(mod_name, thought, observation, action)
                    return orig(thought, observation, action)

                return wrapped

            mod._emit_trace = make_wrapper(original)
        builtins.print = self._intercept_print
        self._installed = True

    def _agent_name(self, module_name: str) -> str:
        return _MODULE_AGENT_NAMES.get(module_name, module_name.split(".")[-1])

    def _publish_trace(
        self, module_name: str, thought: str, observation: str, action: str
    ) -> None:
        sid = current_session_id.get()
        if not sid:
            return
        _enqueue_event(
            sid,
            {
                "type": "AGENT_TRACE",
                "agent": self._agent_name(module_name),
                "thought": thought,
                "observation": observation,
                "action": action,
            },
        )

    def _intercept_print(self, *args: Any, **kwargs: Any) -> Any:
        text = " ".join(str(a) for a in args)
        sid = current_session_id.get()
        if sid and text.startswith(("[THOUGHT]", "[OBSERVATION]", "[ACTION]")):
            if text.startswith("[THOUGHT]"):
                _enqueue_event(
                    sid,
                    {
                        "type": "AGENT_TRACE",
                        "agent": "CIRO",
                        "thought": text[len("[THOUGHT] ") :].strip(),
                        "observation": "",
                        "action": "",
                    },
                )
            elif text.startswith("[OBSERVATION]"):
                _enqueue_event(
                    sid,
                    {
                        "type": "AGENT_TRACE",
                        "agent": "CIRO",
                        "thought": "",
                        "observation": text[len("[OBSERVATION] ") :].strip(),
                        "action": "",
                    },
                )
            elif text.startswith("[ACTION]"):
                _enqueue_event(
                    sid,
                    {
                        "type": "AGENT_TRACE",
                        "agent": "CIRO",
                        "thought": "",
                        "observation": "",
                        "action": text[len("[ACTION] ") :].strip(),
                    },
                )
        return self._original_print(*args, **kwargs)


trace_interceptor = StreamingTraceInterceptor()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_db() -> dict[str, Any]:
    global _db_cache
    if _db_cache is not None:
        return _db_cache
    with DATASET_PATH.open(encoding="utf-8") as f:
        _db_cache = json.load(f)["ciro_datasets"]
    return _db_cache


def _city_config_dict(city: Optional[str], scenario_id: Optional[str]) -> dict[str, Any]:
    name = (city or "Islamabad").strip()
    north, south, east, west = _CITY_BBOX.get(
        name.title(), _CITY_BBOX["Islamabad"]
    )
    return CityConfig(
        city=name,
        bbox_north=north,
        bbox_south=south,
        bbox_east=east,
        bbox_west=west,
        phase="T1_during",
        scenario_id=scenario_id,
    ).model_dump(mode="json")


def _scenario_signals(scenario_id: str, city: str) -> list[dict[str, Any]]:
    """Load DS-001 T1_during social posts for demo scenario into SignalEvents."""
    db = _load_db()
    posts = db.get("DS-001", {}).get("posts", {}).get("T1_during", [])
    events: list[dict[str, Any]] = []
    for post in posts:
        if post.get("scenario_id") != scenario_id:
            continue
        if post.get("city", "").lower() != city.lower():
            continue
        filter_decision = post.get("agent_filter_decision", "INCLUDE")
        confidence = 0.85 if filter_decision == "INCLUDE" else 0.4
        event = SignalEvent(
            signal_id=f"SOC-{uuid.uuid4().hex[:10]}",
            source=SignalSource.SOCIAL,
            timestamp=datetime.fromisoformat(
                post["timestamp"].replace("Z", "+00:00")
            ),
            city=post["city"],
            zone=post.get("location_mentioned"),
            crisis_type=post.get("crisis_type_hint"),
            severity="high" if post.get("crisis_signal") else "medium",
            summary=str(post.get("text", ""))[:280],
            confidence=confidence,
            raw=post,
            metadata={
                "platform": post.get("platform"),
                "agent_filter_decision": filter_decision,
                "language": post.get("language"),
                "phase": "T1_during",
                "scenario_id": scenario_id,
            },
        )
        events.append(event.model_dump(mode="json"))
    return events


def _merge_registry(session_id: str, state: dict[str, Any]) -> None:
    reg = state.get("app:active_crisis_registry") or {}
    if isinstance(reg, str):
        reg = json.loads(reg)
    for inc_id, entry in reg.items():
        merged = dict(entry)
        merged["session_id"] = session_id
        GLOBAL_CRISIS_REGISTRY[inc_id] = merged
        INCIDENT_SESSION_INDEX[inc_id] = session_id


def _primary_incident_id(state: dict[str, Any]) -> Optional[str]:
    reg = state.get("app:active_crisis_registry") or {}
    if isinstance(reg, str):
        reg = json.loads(reg)
    if not reg:
        return None
    for status in ("PROCESSING", "ACTIVE", "APPROVED"):
        for inc_id, entry in reg.items():
            if entry.get("status") == status:
                return inc_id
    return next(iter(reg), None)


def _push_incident_updates(session_id: str, state: dict[str, Any]) -> None:
    classifications = state.get("temp:classified_clusters", []) or []
    severity_records = state.get("temp:severity_records", []) or []
    reg = state.get("app:active_crisis_registry") or {}

    for clf in classifications:
        if isinstance(clf, str):
            continue
        cluster_id = clf.get("cluster_id", "")
        inc_id = f"INCIDENT-{cluster_id.replace('CLU-', '')[:6].upper()}"
        sev = next(
            (s for s in severity_records if s.get("cluster_id") == cluster_id),
            {},
        )
        entry = reg.get(inc_id, {}) if isinstance(reg, dict) else {}
        _enqueue_event(
            session_id,
            {
                "type": "INCIDENT_UPDATE",
                "incident_id": inc_id,
                "status": entry.get("status", "ACTIVE"),
                "classification": clf.get("primary_classification"),
                "severity": sev.get("severity_level", entry.get("severity_level", 1)),
            },
        )

    for notif in state.get("final:notifications", []) or []:
        if isinstance(notif, str):
            continue
        _enqueue_event(
            session_id,
            {
                "type": "NOTIFICATION_SENT",
                "audience": notif.get("audience", "GENERAL_PUBLIC"),
                "reach": notif.get("reach", 0),
                "message_preview": (notif.get("message_en") or "")[:120],
            },
        )


async def _ensure_session(session_id: str) -> Any:
    session = await ciro_session_service.get_session(
        app_name=APP_NAME, user_id=FLUTTER_USER_ID, session_id=session_id
    )
    if session is None:
        session = await ciro_session_service.create_session(
            app_name=APP_NAME,
            user_id=FLUTTER_USER_ID,
            session_id=session_id,
        )
    return session


async def _run_agent_pipeline(
    session_id: str,
    message: str,
    *,
    city: Optional[str] = None,
    scenario_id: Optional[str] = None,
    preload_signals: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Run root_agent and return final session state."""
    global _runner
    if _runner is None:
        _runner = Runner(
            agent=root_agent,
            app_name=APP_NAME,
            session_service=ciro_session_service,
        )

    session = await _ensure_session(session_id)
    state = session.state
    state["user_message"] = message
    state["city_config"] = _city_config_dict(city, scenario_id)

    existing_raw = state.get("temp:raw_signals") or []
    if not isinstance(existing_raw, list):
        existing_raw = []
    if scenario_id:
        scenario_events = _scenario_signals(
            scenario_id, state["city_config"]["city"]
        )
        existing_raw = list(existing_raw) + scenario_events
    if preload_signals:
        existing_raw = list(existing_raw) + preload_signals
    state["temp:raw_signals"] = existing_raw

    _emit_api_trace(
        f"API chat run for session {session_id}: {message[:80]!r}",
        f"city={state['city_config'].get('city')}, scenario={scenario_id}, "
        f"signals={len(existing_raw)}",
        "Invoking CIRORoot via InMemory Runner.",
    )

    token = current_session_id.set(session_id)
    try:
        user_content = types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )
        async for _event in _runner.run_async(
            user_id=FLUTTER_USER_ID,
            session_id=session_id,
            new_message=user_content,
        ):
            pass
    finally:
        current_session_id.reset(token)

    session = await ciro_session_service.get_session(
        app_name=APP_NAME, user_id=FLUTTER_USER_ID, session_id=session_id
    )
    final_state = session.state if session else state
    _merge_registry(session_id, final_state)
    _push_incident_updates(session_id, final_state)

    final_record = final_state.get("final:incident_record")
    if isinstance(final_record, str):
        try:
            final_record = json.loads(final_record)
        except json.JSONDecodeError:
            final_record = None

    _enqueue_event(
        session_id,
        {
            "type": "DONE",
            "incident_record": final_record,
        },
    )

    return final_state


def _print_flutter_urls() -> None:
    lines = [
        "CIRO API started. Agents loaded.",
        "  Chat endpoint:     POST http://localhost:8000/api/chat",
        "  SSE stream:        GET  http://localhost:8000/api/stream/{session_id}",
        "  WebSocket:         WS   ws://localhost:8000/ws/{session_id}",
        "  Incident list:     GET  http://localhost:8000/api/incidents",
        "  Field report:      POST http://localhost:8000/api/field-report",
        "  ADK session run:   POST http://localhost:8000/apps/ciro/users/{uid}/sessions/{sid}/runs",
    ]
    for line in lines:
        print(line)


# ---------------------------------------------------------------------------
# FastAPI app (ADK base + CIRO routes)
# ---------------------------------------------------------------------------

trace_interceptor.install()

app: FastAPI = get_fast_api_app(
    agents_dir=str(PROJECT_ROOT / "agents"),
    session_service_uri="memory://",
    allow_origins=["*"],
    web=False,
    use_local_storage=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    global _runner
    _runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=ciro_session_service,
    )
    _get_queue("_bootstrap")
    _print_flutter_urls()
    _emit_api_trace(
        "CIRO API gateway starting.",
        "InMemorySessionService and trace interceptor ready.",
        "Listening for Flutter REST/SSE/WebSocket clients.",
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    for session_id, sockets in list(active_websockets.items()):
        for ws in list(sockets):
            try:
                await ws.close()
            except Exception:
                pass
        active_websockets[session_id] = set()
    _emit_api_trace(
        "CIRO API shutting down.",
        f"Closed {sum(len(s) for s in active_websockets.values())} WebSocket(s).",
        "Shutdown complete.",
    )


@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(body: ChatRequest) -> ChatResponse:
    try:
        final_state = await _run_agent_pipeline(
            body.session_id,
            body.message,
            city=body.city,
            scenario_id=body.scenario_id,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_api_trace(
            "Pipeline run failed.",
            f"error={exc}",
            "Returning DEGRADED response to client.",
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    triage = str(final_state.get("triage_decision", "PIPELINE"))
    response_text = (
        final_state.get("operator_response")
        or final_state.get("intake:clarification_question")
        or "CIRO processing complete."
    )
    return ChatResponse(
        response=str(response_text),
        session_id=body.session_id,
        triage_decision=triage,
        incident_id=_primary_incident_id(final_state),
        done=True,
    )


async def _sse_generator(session_id: str):
    queue = _get_queue(session_id)
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
        except asyncio.TimeoutError:
            yield {"event": "ping", "data": json.dumps({"type": "PING"})}
            continue
        yield {"event": event.get("type", "message"), "data": json.dumps(event)}
        if event.get("type") == "DONE":
            break


@app.get("/api/stream/{session_id}")
async def api_stream(session_id: str) -> EventSourceResponse:
    return EventSourceResponse(_sse_generator(session_id))


@app.websocket("/ws/{session_id}")
async def websocket_feed(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    active_websockets.setdefault(session_id, set()).add(websocket)

    registry_snapshot = dict(GLOBAL_CRISIS_REGISTRY)
    await websocket.send_json(
        {"type": "REGISTRY_SNAPSHOT", "incidents": list(registry_snapshot.values())}
    )

    queue = _get_queue(session_id)

    async def forward_queue() -> None:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") == "DONE":
                break

    forward_task = asyncio.create_task(forward_queue())

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await websocket.send_json({"type": "PING"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "PING"})
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        active_websockets.get(session_id, set()).discard(websocket)
        try:
            await forward_task
        except asyncio.CancelledError:
            pass


@app.get("/api/incidents")
async def list_incidents() -> dict[str, Any]:
    incidents = []
    for entry in GLOBAL_CRISIS_REGISTRY.values():
        incidents.append(
            {
                "incident_id": entry.get("incident_id"),
                "city": entry.get("city"),
                "zone": entry.get("zone"),
                "crisis_type": entry.get("crisis_type"),
                "severity_level": entry.get("severity_level", 1),
                "status": entry.get("status"),
                "notifications_sent": entry.get("notifications_sent", 0),
                "created_at": entry.get("created_at"),
            }
        )
    active_count = sum(
        1
        for e in incidents
        if e.get("status") in ("PROCESSING", "ACTIVE", "APPROVED")
    )
    return {
        "incidents": incidents,
        "total": len(incidents),
        "active_count": active_count,
    }


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict[str, Any]:
    session_id = INCIDENT_SESSION_INDEX.get(incident_id)
    if not session_id:
        entry = GLOBAL_CRISIS_REGISTRY.get(incident_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Incident not found")
        session_id = entry.get("session_id")

    session = await ciro_session_service.get_session(
        app_name=APP_NAME,
        user_id=FLUTTER_USER_ID,
        session_id=session_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found for incident")

    record = session.state.get("final:incident_record")
    if not record:
        raise HTTPException(
            status_code=404, detail="final:incident_record not yet available"
        )
    if isinstance(record, str):
        record = json.loads(record)
    try:
        return FinalIncidentRecord.model_validate(record).model_dump(mode="json")
    except Exception:
        return record


@app.post("/api/field-report", response_model=FieldReportResponse)
async def field_report(body: FieldReportRequest) -> FieldReportResponse:
    role = (body.reporter_role or "citizen").lower()
    confidence = 0.95 if role in _OFFICIAL_ROLES else 0.65
    signal_id = f"FLD-{uuid.uuid4().hex[:8]}"

    event = SignalEvent(
        signal_id=signal_id,
        source=SignalSource.FIELD_REPORT,
        timestamp=datetime.now(timezone.utc),
        city=body.city,
        zone=body.zone,
        latitude=body.lat,
        longitude=body.lng,
        crisis_type=None,
        severity="high",
        summary=body.text[:280],
        confidence=confidence,
        raw={
            "text": body.text,
            "reporter_role": role,
            "source": "field_report_api",
        },
        metadata={
            "agent_filter_decision": "INCLUDE",
            "intake_source": "field_report",
            "reporter_role": role,
        },
    )

    _emit_api_trace(
        f"Field report from {role} in {body.zone}, {body.city}.",
        f"signal_id={signal_id}, confidence={confidence}",
        "Queuing pipeline run via /api/chat equivalent.",
    )

    await _run_agent_pipeline(
        body.session_id,
        "process field report",
        city=body.city,
        preload_signals=[event.model_dump(mode="json")],
    )

    return FieldReportResponse(
        signal_id=signal_id,
        status="queued",
        session_id=body.session_id,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
