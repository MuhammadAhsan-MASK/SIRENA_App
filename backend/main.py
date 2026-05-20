from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(title="SIRENA Backend", version="1.0.0")

from fastapi import Request
import traceback

# Enable CORS for Flutter web/mobile development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"REQUEST: {request.method} {request.url}")
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print(f"SERVER ERROR: {e}")
        traceback.print_exc()
        raise

class SignalIngestRequest(BaseModel):
    user_origin: str
    user_destination: str
    scenario: Optional[str] = None

class RouteUpdateRequest(BaseModel):
    alternate_route: str
    crisis_location: str

class AlertRequest(BaseModel):
    alert_text: str
    crisis_type: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    resolved: bool
    thought: str

class ScenarioResponse(BaseModel):
    session_id: str
    status: str

@app.get("/")
async def root():
    return {"message": "SIRENA API is running"}

from backend.agents.orchestrator import orchestrator

@app.post("/api/scenario/{scenario_id}")
async def run_scenario(scenario_id: int):
    session_id = await orchestrator.run_scenario(scenario_id)
    return {"session_id": session_id, "status": "started"}

@app.post("/api/ingest/signal")
async def ingest_signal(req: SignalIngestRequest):
    city = orchestrator.get_city_for_location(req.user_origin)
    # Default to scenario 1 (Flooding) for Islamabad, scenario 2 (Heatwave) for Karachi
    # as these are the "primary" scenarios for those cities in our dataset.
    scenario_id = 1 if city == "Islamabad" else 2
    
    if req.scenario:
        scenario_lower = req.scenario.lower()
        if "flood" in scenario_lower: scenario_id = 1
        elif "heat" in scenario_lower: scenario_id = 2
        elif "road" in scenario_lower and "block" in scenario_lower: scenario_id = 3
        elif "accident" in scenario_lower: scenario_id = 4
        elif "infrastructure" in scenario_lower or "power" in scenario_lower: scenario_id = 5
        elif "scn-00" in scenario_lower:
            try:
                scenario_id = int(scenario_lower[-1])
            except: pass

    session_id = await orchestrator.run_scenario(scenario_id, origin=req.user_origin, destination=req.user_destination)
    return {"session_id": session_id, "status": "ingested", "city": city}

@app.post("/api/update-route")
async def update_route(req: RouteUpdateRequest):
    # Simulated webhook response
    return {"status": "route_updated", "location": req.crisis_location}

@app.post("/api/send-alert")
async def send_alert(req: AlertRequest):
    orchestrator.send_push_notification("SIRENA ALERT", f"{req.crisis_type}: {req.alert_text}")
    return {"status": "alert_dispatched"}

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    data = orchestrator.get_session_data(session_id)
    return data

@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    result = await orchestrator.chat(req.message, req.session_id)
    return ChatResponse(
        response=result["response"],
        session_id=result["session_id"],
        resolved=result["resolved"],
        thought=result["thought"]
    )

@app.get("/api/traces/{session_id}")
async def get_traces(session_id: str):
    traces = orchestrator.get_traces(session_id)
    return {"traces": traces}

@app.get("/api/stream/{session_id}")
async def stream_traces(session_id: str):
    async def event_generator():
        last_index = 0
        while True:
            session = orchestrator.get_session_data(session_id)
            if not session:
                break
            
            traces = session.get("traces", [])
            if len(traces) > last_index:
                for i in range(last_index, len(traces)):
                    trace = traces[i]
                    data = {
                        "type": "AGENT_TRACE",
                        "agent": trace["agent"],
                        "thought": trace["message"]
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                last_index = len(traces)
            
            if session.get("status") == "completed" and last_index == len(traces):
                yield f"data: {json.dumps({'type': 'DONE'})}\n\n"
                break
            
            await asyncio.sleep(0.5)
            
    import json
    import asyncio
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/execute/all")
async def execute_actions(session_id: str):
    return {"status": "execution_started"}

@app.get("/api/outcome/{session_id}")
async def get_outcome(session_id: str):
    outcome = orchestrator.get_outcome(session_id)
    return {"outcome": outcome}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
