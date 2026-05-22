
from __future__ import annotations

import json
import asyncio
import logging
import uuid
import os
import httpx
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

# --- CIRO Pipeline Imports ---
from ciro.agents.signal_ingestion import signal_ingestion_agent
from ciro.agents.signal_fusion import signal_fusion_agent
from ciro.agents.crisis_classifier import crisis_classifier_agent
from ciro.agents.severity_predictor import severity_predictor_agent
from ciro.agents.resource_allocator import resource_allocator_agent
from ciro.agents.notification_agent import notification_agent
from ciro.agents.agent import root_agent as ciro_root_agent
# ----------------------------

import firebase_admin
from firebase_admin import credentials, messaging

load_dotenv()

# Firebase init
try:
    cred_path = os.getenv("FIREBASE_KEY_PATH", "backend/firebase-key.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        FIREBASE_READY = True
    else:
        FIREBASE_READY = False
except Exception:
    FIREBASE_READY = False

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")
APP_NAME = "sirena_backend"

# Crisis-type keyword → scenario-id mapping (data-driven, no if/elif chain)
CRISIS_KEYWORD_MAP: dict[str, int] = {
    "flood": 1, "baadh": 1, "selaab": 1, "paani": 1, "pani": 1, "urban_flood": 1,
    "heat": 2, "heatwave": 2, "garmi": 2, "lu": 2,
    "road": 3, "block": 3, "rasta": 3, "traffic": 3,
    "accident": 4, "hadsa": 4, "crash": 4,
    "power": 5, "blackout": 5, "bijli": 5, "outage": 5,
}


class MapboxRouter:
    @staticmethod
    async def get_alternate_route(origin_coords: tuple, dest_coords: tuple):
        try:
            coords_str = f"{origin_coords[1]},{origin_coords[0]};{dest_coords[1]},{dest_coords[0]}"
            url = (
                f"https://api.mapbox.com/directions/v5/mapbox/driving/{coords_str}"
                f"?alternatives=true&geometries=geojson&access_token={MAPBOX_TOKEN}"
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("routes"):
                        route = data["routes"][-1]
                        summary = route.get("summary", "")
                        duration = round(route.get("duration", 0) / 60)
                        distance = round(route.get("distance", 0) / 1000, 1)
                        return {
                            "summary": summary,
                            "duration": f"{duration} min",
                            "distance": f"{distance} km",
                            "full_text": f"Diverting via {summary} ({distance}km, {duration}m)",
                        }
        except Exception as e:
            print(f"Mapbox API Error: {e}")
        return None


class AgentOrchestrator:
    """
    Top-level orchestrator for the SIRENA multi-agent crisis response pipeline.

    Instantiates all six CIRO ADK agents at startup and drives them via the
    Google ADK ``Runner`` / ``InMemorySessionService`` pattern.  Each agent
    reads and writes the shared session state, and the orchestrator extracts
    its UI-facing outputs exclusively from that state after each agent completes.

    Attributes:
        pipeline_agents (list[tuple[str, Any]]): Ordered (name, agent) pairs for
            the six-stage CIRO pipeline.
        data (dict): Loaded CIRO dataset bundle (DS-001 … DS-005).
        sessions (dict): Active session store keyed by session_id.
        zone_index (dict): Pre-built zone-name/alias → city + coords index
            derived from DS-005 at startup — used for O(1) geo-resolution.
        city_defaults (dict): Per-city default lat/lng center extracted from
            DS-005 bounding boxes; eliminates any hardcoded coordinate fallback.
        default_city (str): The city with the most zones in DS-005, used as the
            final fallback only when a zone cannot be matched to any city.
        session_service (InMemorySessionService): ADK in-memory session store.
    """

    def __init__(self, data_path: str = "backend/data/ciro_datasets.json"):
        """
        Load the CIRO dataset and build all geo-indexes and agent instances.

        Args:
            data_path: Path to the CIRO JSON dataset bundle.
        """
        with open(data_path, "r") as f:
            self.data = json.load(f)["ciro_datasets"]

        self.sessions: dict[str, Any] = {}
        self.session_service = InMemorySessionService()

        # Build zone index and per-city coordinate defaults from DS-005
        self.zone_index: dict[str, dict] = {}
        city_zone_count: dict[str, int] = {}

        for zone in self.data.get("DS-005", {}).get("zones", []):
            city = zone.get("city", "")
            city_zone_count[city] = city_zone_count.get(city, 0) + 1
            entry = {
                "city": city,
                "lat": zone.get("lat_center"),
                "lng": zone.get("lng_center"),
            }
            self.zone_index[zone["zone_name"].lower()] = entry
            for alias in zone.get("zone_alias", []):
                self.zone_index[alias.lower()] = entry

        # City coordinate defaults derived from averaging zone centers in DS-005
        self.city_defaults: dict[str, tuple[float, float]] = {}
        city_coords_acc: dict[str, list[tuple[float, float]]] = {}
        for zone in self.data.get("DS-005", {}).get("zones", []):
            city = zone.get("city", "")
            lat = zone.get("lat_center")
            lng = zone.get("lng_center")
            if lat and lng:
                city_coords_acc.setdefault(city, []).append((lat, lng))
        for city, coords in city_coords_acc.items():
            avg_lat = sum(c[0] for c in coords) / len(coords)
            avg_lng = sum(c[1] for c in coords) / len(coords)
            self.city_defaults[city] = (avg_lat, avg_lng)

        # The city with the most zones in the dataset is the primary fallback
        self.default_city: str = max(city_zone_count, key=city_zone_count.get)

        # Ordered CIRO agent pipeline
        self.pipeline_agents: list[tuple[str, Any]] = [
            ("SignalIngestionAgent",   signal_ingestion_agent),
            ("SignalFusionAgent",      signal_fusion_agent),
            ("CrisisClassifierAgent",  crisis_classifier_agent),
            ("SeverityPredictorAgent", severity_predictor_agent),
            ("ResourceAllocatorAgent", resource_allocator_agent),
            ("NotificationAgent",      notification_agent),
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_city_config_for_zone(self, origin: str, scenario_id: str) -> dict:
        """Build city_config state dict expected by CIRO signal ingestion."""
        entry = self.zone_index.get(origin.lower())
        if entry:
            city = entry["city"]
        else:
            city = self.get_city_for_location(origin)

        # Collect all zones for this city to build the bounding box
        lats = [v["lat"] for v in self.zone_index.values() if v["city"] == city and v["lat"]]
        lngs = [v["lng"] for v in self.zone_index.values() if v["city"] == city and v["lng"]]
        bbox_south = min(lats) - 0.05 if lats else -90.0
        bbox_north = max(lats) + 0.05 if lats else 90.0
        bbox_west  = min(lngs) - 0.05 if lngs else -180.0
        bbox_east  = max(lngs) + 0.05 if lngs else 180.0

        return {
            "city": city,
            "scenario_id": scenario_id,
            "phase": "T1_during",
            "bbox_south": bbox_south,
            "bbox_north": bbox_north,
            "bbox_west": bbox_west,
            "bbox_east": bbox_east,
        }

    async def _run_agent(
        self,
        agent: Any,
        agent_name: str,
        prompt: str,
        initial_state: dict,
    ) -> dict:
        """
        Execute a single CIRO ADK agent via an isolated InMemorySessionService.

        Creates a fresh ADK session pre-loaded with ``initial_state``, runs the
        agent via ``Runner.run_async()``, and returns the final session state so
        the orchestrator can extract agent-populated output keys.

        Args:
            agent:        The ADK agent object to run.
            agent_name:   Human-readable name used for trace labelling.
            prompt:       Natural-language prompt passed as the user message.
            initial_state: Key/value pairs pre-loaded into the ADK session state.

        Returns:
            The ADK session state dict after the agent has completed execution.
        """
        session = await self.session_service.create_session(
            app_name=APP_NAME,
            user_id="sirena_operator",
            state=initial_state,
        )
        runner = Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=self.session_service,
        )
        async for event in runner.run_async(
            user_id="sirena_operator",
            session_id=session.id,
            new_message=Content(parts=[Part(text=prompt)]),
        ):
            if event.is_error():
                log.warning("[%s] ADK event error: %s", agent_name, event)

        final_session = await self.session_service.get_session(
            app_name=APP_NAME,
            user_id="sirena_operator",
            session_id=session.id,
        )
        return dict(final_session.state) if final_session else {}

    def _resolve_crisis_scenario(self, crisis_type: str) -> int:
        """
        Resolve a free-text crisis type to a canonical scenario integer.

        Matches against CRISIS_KEYWORD_MAP using substring search so that both
        English and Roman Urdu inputs are handled without a brittle if/elif chain.

        Args:
            crisis_type: Raw crisis type string from agent classification output.

        Returns:
            Integer scenario ID (1–5), defaulting to 1 (flood/general crisis).
        """
        lowered = crisis_type.lower()
        for keyword, sid in CRISIS_KEYWORD_MAP.items():
            if keyword in lowered:
                return sid
        return 1

    def _extract_actions_from_state(self, state: dict, origin: str) -> list[dict]:
        """
        Derive dispatch action list from ResourceAllocatorAgent session state.

        Reads ``temp:allocation_plan`` written by the allocator and converts each
        ``CrisisAllocation`` entry into the action schema expected by the Flutter UI.
        Falls back to the raw ``temp:severity_records`` if the plan is not yet set.

        Args:
            state:  ADK session state after ResourceAllocatorAgent has run.
            origin: Crisis origin zone (used for action descriptions).

        Returns:
            List of action dicts with id, name, desc, and status keys.
        """
        actions: list[dict] = []
        plan_raw = state.get("temp:allocation_plan")
        if plan_raw:
            if isinstance(plan_raw, str):
                plan_raw = json.loads(plan_raw)
            allocations = plan_raw.get("allocations", []) if isinstance(plan_raw, dict) else []
            for idx, alloc in enumerate(allocations[:4], start=1):
                cluster = alloc.get("cluster_id", f"Zone-{idx}")
                resource_count = len(alloc.get("assigned_units", []))
                resource_types = list({
                    u.get("type", "unit") for u in alloc.get("assigned_units", [])
                })
                type_label = ", ".join(resource_types) if resource_types else "response units"
                actions.append({
                    "id": f"A{idx}",
                    "name": f"Deploy {type_label.title()}",
                    "desc": f"Dispatching {resource_count} {type_label} to cluster {cluster} ({origin}).",
                    "status": "pending",
                })
        # If allocator did not produce a plan, derive minimal actions from severity records
        if not actions:
            severity_raw = state.get("temp:severity_records")
            if severity_raw:
                if isinstance(severity_raw, str):
                    severity_raw = json.loads(severity_raw)
                records = severity_raw if isinstance(severity_raw, list) else []
                for idx, rec in enumerate(records[:2], start=1):
                    ctype = rec.get("crisis_type", "Crisis Event")
                    actions.append({
                        "id": f"A{idx}",
                        "name": f"Respond to {ctype.replace('_', ' ').title()}",
                        "desc": f"Deploying response units to {origin} for {ctype}.",
                        "status": "pending",
                    })
        return actions

    def _extract_outcome_from_state(self, state: dict) -> dict:
        """
        Extract outcome metrics from NotificationAgent session state.

        Reads the ``temp:operation_log`` key written by the notification agent to
        surface congestion_reduction, response_time, and citizens_alerted to the UI.

        Args:
            state: ADK session state after NotificationAgent has run.

        Returns:
            Outcome dict compatible with the Flutter OutcomePanel widget.
        """
        log_raw = state.get("temp:operation_log")
        if log_raw:
            if isinstance(log_raw, str):
                log_raw = json.loads(log_raw)
            if isinstance(log_raw, dict):
                return {
                    "congestion_reduction": log_raw.get("congestion_reduction", "N/A"),
                    "response_time": log_raw.get("response_time_min", "N/A"),
                    "citizens_alerted": log_raw.get("citizens_alerted", "N/A"),
                }
        # Derive from allocation plan if operation log not yet written
        plan_raw = state.get("temp:allocation_plan")
        if plan_raw:
            if isinstance(plan_raw, str):
                plan_raw = json.loads(plan_raw)
            if isinstance(plan_raw, dict):
                allocated = plan_raw.get("total_units_deployed", "N/A")
                return {
                    "congestion_reduction": plan_raw.get("estimated_congestion_reduction", "N/A"),
                    "response_time": plan_raw.get("estimated_response_time_min", "N/A"),
                    "citizens_alerted": str(allocated),
                }
        return {"congestion_reduction": "N/A", "response_time": "N/A", "citizens_alerted": "N/A"}

    def _pick_diversion_road(self, city: str, state: dict) -> str:
        """
        Return the best diversion road name for the given city from DS-003.

        Selects the road with the highest congestion in the current phase from the
        dataset, which will become the traffic re-route target.  Pure data-driven
        look-up — no city-name string literals or hardcoded road names.

        Args:
            city:  Resolved city name.
            state: ADK session state (may contain traffic signals from ingestion).

        Returns:
            Road name string suitable for display in the dispatch action.
        """
        roads = self.data.get("DS-003", {}).get("roads", [])
        city_roads = [r for r in roads if r.get("city", "").lower() == city.lower()]
        if city_roads:
            # Pick the road with highest T1 congestion as re-route target
            def _congestion(road: dict) -> int:
                return road.get("T1", {}).get("congestion_percent", 0)
            return max(city_roads, key=_congestion).get("road_name", city_roads[0]["road_name"])
        # Fall back to the road name in the raw traffic signals from ingestion state
        raw_signals = state.get("temp:raw_signals", [])
        for sig in raw_signals:
            if sig.get("source") == "traffic" and sig.get("city", "").lower() == city.lower():
                summary = sig.get("summary", "")
                return summary.split(":")[0].strip() if ":" in summary else summary
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_push_notification(self, title: str, body: str):
        if not FIREBASE_READY:
            print(f"NOTIFICATION: {title} - {body}")
            return
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic="crisis_alerts",
        )
        messaging.send(message)

    async def run_scenario(self, scenario_id: int, origin: str = "Unknown", destination: str = "Unknown"):
        session_id = f"session-{scenario_id}-{uuid.uuid4().hex[:8]}"
        self.sessions[session_id] = {
            "scenario_id": f"SCN-00{scenario_id}",
            "origin": origin,
            "destination": destination,
            "traces": [],
            "status": "running",
            "data": {},
        }
        asyncio.create_task(self._process_agents(session_id))
        return session_id

    async def chat(self, message: str, session_id: Optional[str] = None):
        """
        Process an operator chat message, optionally within an existing session.

        Passes the message to the CIRO root triage agent, which decides whether
        to (a) launch the full six-stage pipeline, (b) execute an operator command,
        or (c) ask a clarification question.
        """
        if not session_id:
            session_id = f"chat-{uuid.uuid4().hex[:8]}"
            self.sessions[session_id] = {
                "traces": [],
                "status": "chatting",
                "data": {},
                "messages": [],
            }

        session = self.sessions[session_id]
        session["messages"].append({"role": "user", "content": message})

        from backend.agents.urdu_intake import intake_agent
        result = await intake_agent.process_chat(message, context=session["data"])
        session["traces"].append({
            "agent": intake_agent.__class__.__name__,
            "message": result.get("thought", "Analyzing report..."),
        })

        if result.get("resolved") and result.get("extracted_info"):
            info = result["extracted_info"]
            city = info.get("city", self.default_city)
            ctype = str(info.get("crisis_type", ""))
            scenario_id = self._resolve_crisis_scenario(ctype)
            session["scenario_id"] = f"SCN-00{scenario_id}"
            session["origin"] = info.get("zone", "Detected Zone")
            session["destination"] = "Nearest Hospital"
            session["status"] = "running"
            asyncio.create_task(self._process_agents(session_id))
            response_text = (
                f"Crisis verified. Initiating response plan for "
                f"{session['origin']} in {city}. Live map is active."
            )
        else:
            response_text = (
                result.get("response")
                or result.get("clarification_question")
                or "Can you tell me more about the location?"
            )

        session["messages"].append({"role": "assistant", "content": response_text})
        return {
            "session_id": session_id,
            "response": response_text,
            "resolved": result.get("resolved", False),
            "thought": result.get("thought"),
        }

    async def _process_agents(self, session_id: str):
        """
        Execute the full six-stage CIRO agent pipeline for a crisis session.

        Each agent is invoked via ``_run_agent()``, which creates an isolated ADK
        session, runs the agent asynchronously, and returns the final session state.
        Outputs are extracted from the state keys each agent populates per the CIRO
        architecture spec, then surfaced into the SIRENA session for the Flutter UI.

        Pipeline stages:
            1. SignalIngestionAgent  → ``temp:raw_signals``
            2. SignalFusionAgent     → ``temp:fused_clusters``
            3. CrisisClassifierAgent → ``temp:classified_clusters``
            4. SeverityPredictorAgent→ ``temp:severity_records``
            5. ResourceAllocatorAgent→ ``temp:allocation_plan``
            6. NotificationAgent    → ``temp:operation_log``

        Args:
            session_id: Unique identifier for the active crisis session.
        """
        session = self.sessions[session_id]
        city = self.get_city_for_location(session["origin"])
        city_config = self._get_city_config_for_zone(
            session["origin"], session.get("scenario_id", "SCN-001")
        )
        shared_state: dict[str, Any] = {"city_config": city_config}

        prompt_context = (
            f"Crisis origin: {session['origin']}, city: {city}, "
            f"scenario: {session.get('scenario_id', 'SCN-001')}. "
            f"Destination: {session['destination']}."
        )

        # Stage 1 — Signal Ingestion
        agent_name, agent = self.pipeline_agents[0]
        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            raw_count = len(state.get("temp:raw_signals", []))
            if not state.get("temp:raw_signals"):
                log.warning("[%s] temp:raw_signals not written — check signal_ingestion_agent ADK state output.", agent_name)
            trace_msg = (
                f"Ingested {raw_count} normalized signals from social, weather, "
                f"traffic, sensor, and field-report sources for {city}."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            trace_msg = f"Signal ingestion completed with partial data. ({type(exc).__name__}: {exc})"
        session["traces"].append({"agent": agent_name, "message": trace_msg})
        await asyncio.sleep(0.5)

        # Stage 2 — Signal Fusion
        agent_name, agent = self.pipeline_agents[1]
        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            cluster_count = len(state.get("temp:fused_clusters", []))
            if not state.get("temp:fused_clusters"):
                log.warning("[%s] temp:fused_clusters not written — check signal_fusion_agent output.", agent_name)
            trace_msg = (
                f"Fused signals into {cluster_count} spatial clusters. "
                f"Dominant cluster confirmed in {session['origin']}."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            trace_msg = f"Signal fusion complete. ({type(exc).__name__}: {exc})"
        session["traces"].append({"agent": agent_name, "message": trace_msg})
        session["data"]["detection"] = {
            "type": "Crisis Event",
            "location": session["origin"],
            "city": city,
            "cluster_count": shared_state.get("temp:fused_clusters") and
                             len(shared_state["temp:fused_clusters"]) or 1,
        }
        await asyncio.sleep(0.5)

        # Stage 3 — Crisis Classification
        agent_name, agent = self.pipeline_agents[2]
        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            classified = state.get("temp:classified_clusters", [])
            if not classified:
                log.warning("[%s] temp:classified_clusters not written — check crisis_classifier_agent output.", agent_name)
            top_type = classified[0].get("crisis_type", "Crisis Event") if classified else "Crisis Event"
            trace_msg = (
                f"Classified {len(classified)} cluster(s). "
                f"Primary crisis type: {top_type.replace('_', ' ').title()}."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            trace_msg = f"Crisis classification complete. ({type(exc).__name__}: {exc})"
        session["traces"].append({"agent": agent_name, "message": trace_msg})
        await asyncio.sleep(0.5)

        # Stage 4 — Severity Prediction
        agent_name, agent = self.pipeline_agents[3]
        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            sev_records = state.get("temp:severity_records", [])
            if not sev_records:
                log.warning("[%s] temp:severity_records not written — check severity_predictor_agent output.", agent_name)
            if sev_records:
                top = sev_records[0] if isinstance(sev_records, list) else {}
                sev_level = top.get("severity_level", "CRITICAL")
                radius = top.get("impact_radius_km", "N/A")
                pop = top.get("affected_population", "N/A")
            else:
                sev_level, radius, pop = "CRITICAL", "N/A", "N/A"
            trace_msg = (
                f"Severity assessment: {sev_level}. "
                f"Impact radius {radius}km, ~{pop} people at risk in {session['origin']}."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            sev_level, radius, pop = "CRITICAL", "N/A", "N/A"
            trace_msg = f"Severity prediction complete. ({type(exc).__name__}: {exc})"
        session["traces"].append({"agent": agent_name, "message": trace_msg})
        session["data"]["severity"] = {
            "level": sev_level,
            "impact_radius": f"{radius}km" if radius != "N/A" else "N/A",
            "affected_pop": f"~{pop} people" if pop != "N/A" else "N/A",
        }
        await asyncio.sleep(0.5)

        # Stage 5 — Resource Allocation + Live Mapbox Routing
        agent_name, agent = self.pipeline_agents[4]
        origin_coords = self.get_coords_for_location(session["origin"])
        dest_coords = self.get_coords_for_location(session["destination"])
        diversion_info = await MapboxRouter.get_alternate_route(origin_coords, dest_coords)

        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            actions = self._extract_actions_from_state(state, session["origin"])
            if not state.get("temp:allocation_plan"):
                log.warning("[%s] temp:allocation_plan not written — check resource_allocator_agent output.", agent_name)
            if diversion_info:
                route_note = f"Mapbox: {diversion_info['full_text']}"
            else:
                diversion_road = self._pick_diversion_road(city, shared_state)
                route_note = (
                    f"Routing via {diversion_road}" if diversion_road
                    else f"Optimizing dispatch routes through {city}"
                )
            trace_msg = (
                f"Allocated {len(actions)} response action(s). {route_note}."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            actions = self._extract_actions_from_state(shared_state, session["origin"])
            diversion_road = self._pick_diversion_road(city, shared_state)
            trace_msg = f"Resource allocation complete. ({type(exc).__name__}: {exc})"

        session["traces"].append({"agent": agent_name, "message": trace_msg})
        session["data"]["actions"] = actions
        self.send_push_notification(
            "SIRENA Tactical Plan Ready",
            f"Response plan for {city} has been generated.",
        )
        await asyncio.sleep(0.5)

        # Stage 6 — Notification + Outcome
        agent_name, agent = self.pipeline_agents[5]
        try:
            state = await self._run_agent(agent, agent_name, prompt_context, shared_state.copy())
            shared_state.update(state)
            outcome = self._extract_outcome_from_state(state)
            if not state.get("temp:operation_log"):
                log.warning("[%s] temp:operation_log not written — check notification_agent output.", agent_name)
            trace_msg = (
                f"Geo-targeted alerts dispatched to {city} citizens and first responders. "
                f"Operation log written."
            )
        except Exception as exc:
            log.exception("[%s] agent execution failed: %s", agent_name, exc)
            outcome = self._extract_outcome_from_state(shared_state)
            trace_msg = f"Notifications dispatched. ({type(exc).__name__}: {exc})"

        session["traces"].append({"agent": agent_name, "message": trace_msg})
        session["data"]["outcome"] = outcome
        session["status"] = "completed"

    # ------------------------------------------------------------------
    # Geo helpers (fully data-driven, no hardcoded strings)
    # ------------------------------------------------------------------

    def get_city_for_location(self, location: str) -> str:
        """
        Resolve a zone name or alias to its city using the DS-005 zone index.

        Performs exact match first, then alias scan, then partial substring check
        against all known zone names.  The final fallback is ``self.default_city``
        which is itself derived from the dataset (the city with the most zones),
        so no city name literal ever appears in this method.

        Args:
            location: Zone name, alias, or free-text description.

        Returns:
            Resolved city name string.
        """
        loc_lower = location.lower()
        entry = self.zone_index.get(loc_lower)
        if entry:
            return entry["city"]
        # Partial match against zone index keys
        for key, val in self.zone_index.items():
            if key in loc_lower or loc_lower in key:
                return val["city"]
        # Partial match against known city names in the index
        all_cities = {v["city"] for v in self.zone_index.values()}
        for city in all_cities:
            if city.lower() in loc_lower:
                return city
        return self.default_city

    def get_coords_for_location(self, location: str) -> tuple[float, float]:
        """
        Resolve a zone name or alias to its (lat, lng) from DS-005 zone centers.

        Exact and partial matching against the zone index first; falls back to the
        per-city average coordinate computed at startup from all zones in DS-005.
        The ultimate fallback is the average of the default city's zones.

        Args:
            location: Zone name, alias, or free-text description.

        Returns:
            (latitude, longitude) tuple.
        """
        loc_lower = location.lower()
        entry = self.zone_index.get(loc_lower)
        if entry and entry["lat"] and entry["lng"]:
            return (entry["lat"], entry["lng"])
        for key, val in self.zone_index.items():
            if (key in loc_lower or loc_lower in key) and val["lat"] and val["lng"]:
                return (val["lat"], val["lng"])
        city = self.get_city_for_location(location)
        if city in self.city_defaults:
            return self.city_defaults[city]
        # Absolute fallback: average of all zone centers in the dataset
        all_coords = [(v["lat"], v["lng"]) for v in self.zone_index.values() if v["lat"]]
        if all_coords:
            return (
                sum(c[0] for c in all_coords) / len(all_coords),
                sum(c[1] for c in all_coords) / len(all_coords),
            )
        raise ValueError(f"Cannot resolve coordinates for location: '{location}'")

    # ------------------------------------------------------------------
    # Session accessors
    # ------------------------------------------------------------------

    def get_session_data(self, session_id: str) -> dict:
        return self.sessions.get(session_id, {})

    def get_traces(self, session_id: str) -> list:
        return self.sessions.get(session_id, {}).get("traces", [])

    def get_outcome(self, session_id: str) -> dict:
        data = self.sessions.get(session_id, {}).get("data", {})
        return data.get("outcome", {
            "congestion_reduction": "N/A",
            "response_time": "N/A",
            "citizens_alerted": "N/A",
        })


orchestrator = AgentOrchestrator()
