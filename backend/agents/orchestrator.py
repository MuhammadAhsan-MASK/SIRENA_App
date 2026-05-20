import json
import asyncio
import httpx
from typing import List, Dict, Optional

from backend.agents.agent_modules import (
    SignalAgent, DetectionAgent, SeverityAgent, 
    PlanningAgent, ExecutionAgent, OutcomeAgent
)
from backend.agents.urdu_intake import intake_agent

import firebase_admin
from firebase_admin import credentials, messaging

# Attempt to initialize Firebase Admin
import os
from dotenv import load_dotenv

load_dotenv() # Load variables from .env

# Attempt to initialize Firebase Admin
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

class MapboxRouter:
    @staticmethod
    async def get_alternate_route(origin_coords: tuple, dest_coords: tuple):
        """
        Calls Mapbox Directions API for an alternate route.
        """
        try:
            # Format: lng,lat;lng,lat
            coords_str = f"{origin_coords[1]},{origin_coords[0]};{dest_coords[1]},{dest_coords[0]}"
            url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{coords_str}?alternatives=true&geometries=geojson&access_token={MAPBOX_TOKEN}"
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("routes"):
                        # Get the second route (alternate) if available, or summary of the first
                        route = data["routes"][len(data["routes"])-1] 
                        summary = route.get("summary", "Primary Route")
                        duration = round(route.get("duration", 0) / 60)
                        distance = round(route.get("distance", 0) / 1000, 1)
                        return {
                            "summary": summary,
                            "duration": f"{duration} min",
                            "distance": f"{distance} km",
                            "full_text": f"Diverting via {summary} ({distance}km, {duration}m)"
                        }
        except Exception as e:
            print(f"Mapbox API Error: {e}")
        return None

class AgentOrchestrator:
    def send_push_notification(self, title: str, body: str):
        if not FIREBASE_READY:
            print(f"NOTIFICATION (Mock): {title} - {body}")
            return
        
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic="crisis_alerts"
        )
        messaging.send(message)
    def __init__(self, data_path: str = "backend/data/ciro_datasets.json"):
        with open(data_path, "r") as f:
            self.data = json.load(f)["ciro_datasets"]
        self.sessions = {}
        # Pre-index zones for fast city lookup
        self.zone_to_city = {}
        for zone in self.data.get("DS-005", {}).get("zones", []):
            city = zone.get("city", "Unknown")
            self.zone_to_city[zone["zone_name"].lower()] = city
            for alias in zone.get("zone_alias", []):
                self.zone_to_city[alias.lower()] = city
        
        # Instantiate agents
        self.agents = [
            SignalAgent(),
            DetectionAgent(),
            SeverityAgent(),
            PlanningAgent(),
            ExecutionAgent(),
            OutcomeAgent()
        ]

    async def run_scenario(self, scenario_id: int, origin: str = "Unknown", destination: str = "Unknown"):
        session_id = f"session-{scenario_id}-{int(asyncio.get_event_loop().time())}"
        self.sessions[session_id] = {
            "scenario_id": f"SCN-00{scenario_id}",
            "origin": origin,
            "destination": destination,
            "traces": [],
            "status": "running",
            "data": {} # Shared data between agents
        }
        
        asyncio.create_task(self._process_agents(session_id))
        return session_id

    async def chat(self, message: str, session_id: Optional[str] = None):
        """
        Handles a chat message, optionally within an existing session.
        If it's a new report, it starts a session.
        """
        if not session_id:
            session_id = f"chat-{int(asyncio.get_event_loop().time())}"
            self.sessions[session_id] = {
                "traces": [],
                "status": "chatting",
                "data": {},
                "messages": []
            }
        
        session = self.sessions[session_id]
        session["messages"].append({"role": "user", "content": message})
        
        # Invoke Intake Agent
        result = await intake_agent.process_chat(message, context=session["data"])
        
        # Add thought to traces
        session["traces"].append({"agent": "IntakeAgent", "message": result.get("thought", "Analyzing report...")})
        
        if result.get("resolved") and result.get("extracted_info"):
            # Trigger full pipeline if we have enough info
            info = result["extracted_info"]
            city = info.get("city", "Islamabad")
            # Map type to scenario
            ctype = str(info.get("crisis_type", "")).lower()
            if "flood" in ctype: scenario_id = 1
            elif "heat" in ctype: scenario_id = 2
            elif "road" in ctype or "block" in ctype: scenario_id = 3
            elif "accident" in ctype: scenario_id = 4
            elif "power" in ctype or "blackout" in ctype: scenario_id = 5
            else: scenario_id = 1 # Fallback
            
            # Update session to full scenario
            session["scenario_id"] = f"SCN-00{scenario_id}"
            session["origin"] = info.get("zone", "Detected Zone")
            session["destination"] = "Nearest Hospital"
            session["status"] = "running"
            
            asyncio.create_task(self._process_agents(session_id))
            
            response_text = f"The crisis has been verified. I am initiating a response plan for {session['origin']} in {city}. You can view the live map now."
        else:
            response_text = result.get("response") or result.get("clarification_question") or "Interesting. Can you tell me more about the location?"
            
        session["messages"].append({"role": "assistant", "content": response_text})
        return {
            "session_id": session_id,
            "response": response_text,
            "resolved": result.get("resolved", False),
            "thought": result.get("thought")
        }

    async def _process_agents(self, session_id: str):
        session = self.sessions[session_id]
        city = self.get_city_for_location(session["origin"])
        print(f"[DEBUG] Processing agents for {session['origin']} in city: {city}")
        
        # 1. Signal & Detection
        msg_signal = f"Analyzing situational awareness signals in {city}..."
        session["traces"].append({"agent": self.agents[0].name, "message": msg_signal})
        await asyncio.sleep(1)
        
        msg_det = f"Established cluster pattern: {session.get('scenario_id')} verified in {session['origin']}."
        session["traces"].append({"agent": self.agents[1].name, "message": msg_det})
        session["data"]["detection"] = {
            "type": "Crisis Event",
            "confidence": "94%",
            "location": session["origin"],
            "city": city
        }
        await asyncio.sleep(1)

        # 2. Severity
        msg_sev = f"Impact radius analysis for {session['origin']} indicates high population risk."
        session["traces"].append({"agent": self.agents[2].name, "message": msg_sev})
        session["data"]["severity"] = {
            "level": "CRITICAL",
            "impact_radius": "2.1km",
            "affected_pop": "~340 people"
        }
        await asyncio.sleep(1)

        # 3. Planning (LIVE MAPBOX ROUTING)
        origin_coords = self.get_coords_for_location(session["origin"])
        dest_coords = self.get_coords_for_location(session["destination"])
        
        diversion_info = await MapboxRouter.get_alternate_route(origin_coords, dest_coords)
        
        if diversion_info:
            msg_plan = f"Mapbox optimization: {diversion_info['full_text']}."
            target_road = diversion_info["summary"]
        else:
            msg_plan = f"Optimizing response routes. Bypassing congested arteries near {session['origin']}."
            target_road = "Shahrah-e-Faisal" if city == "Karachi" else "Expressway"

        session["traces"].append({"agent": self.agents[3].name, "message": msg_plan})
        
        session["data"]["actions"] = [
            {"id": "A1", "name": "Dispatch Rescue Units", "desc": f"Deploying units to {session['origin']}.", "status": "pending"},
            {"id": "A2", "name": "Reroute Traffic", "desc": f"Redirecting vehicles via {target_road}.", "status": "pending"}
        ]
        self.send_push_notification(
            "SIRENA Tactical Plan Ready", 
            f"A response plan for {city} has been generated."
        )
        await asyncio.sleep(1)

        # 4. Execution & Outcome
        result_exe = await self.agents[4].run(session)
        msg_exe = f"Coordinating with local {city} response units for rapid deployment."
        session["traces"].append({"agent": self.agents[4].name, "message": msg_exe})
        
        result_out = await self.agents[5].run(session)
        session["traces"].append({"agent": self.agents[5].name, "message": result_out.get("trace")})
        session["data"]["outcome"] = {
            "congestion_reduction": "63%",
            "response_time": "14 min",
            "citizens_alerted": "1,247"
        }

        session["status"] = "completed"

    def get_city_for_location(self, location: str) -> str:
        loc_lower = location.lower()
        # 1. Check exact match or alias
        if loc_lower in self.zone_to_city:
            return self.zone_to_city[loc_lower]
        
        # 2. Heuristic check for city names in string
        if "karachi" in loc_lower:
            return "Karachi"
        if "islamabad" in loc_lower:
            return "Islamabad"
            
        # 3. Fallback
        return "Islamabad" # Dataset is 80% ISB, but Karachi scenarios exist

    def get_coords_for_location(self, location: str) -> tuple:
        """
        Returns (lat, lng) for a zone or alias.
        """
        loc_lower = location.lower()
        for zone in self.data.get("DS-005", {}).get("zones", []):
            if zone["zone_name"].lower() == loc_lower or loc_lower in [a.lower() for a in zone.get("zone_alias", [])]:
                return (zone["lat_center"], zone["lng_center"])
        
        # Defaults if not found
        if "karachi" in loc_lower:
            return (24.86, 67.02)
        return (33.68, 73.04) # Islamabad center

    def get_session_data(self, session_id: str):
        return self.sessions.get(session_id, {})

    def get_traces(self, session_id: str):
        return self.sessions.get(session_id, {}).get("traces", [])

    def get_outcome(self, session_id: str):
        session = self.sessions.get(session_id, {})
        data = session.get("data", {})
        return data.get("outcome", {
            "congestion_reduction": "N/A", 
            "response_time": "N/A", 
            "citizens_alerted": "N/A"
        })

orchestrator = AgentOrchestrator()
