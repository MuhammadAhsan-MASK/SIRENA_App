"""
Action simulation — SequentialAgent chaining per-type simulations + LLM side effects.

Reads ``temp:allocation_plan`` and DS-006/DS-003, simulates before/after states per action,
writes ``temp:action_simulations``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.events.event import Event
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from pydantic import Field
from typing_extensions import override

from schemas.models import (
    ActionSimulation,
    ActionSimulationResult,
    AllocationPlan,
    RecommendedAction,
    SeverityRecord,
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

_SIMULATION_TYPES = (
    "traffic_rerouting",
    "emergency_dispatch",
    "hospital_preparation",
    "utility_escalation",
    "public_evacuation_alert",
    "shelter_activation",
)

_ACTION_TYPE_TO_SIM: dict[str, str] = {
    "reroute": "traffic_rerouting",
    "dispatch": "emergency_dispatch",
    "alert": "public_evacuation_alert",
    "notify": "utility_escalation",
    "activate": "shelter_activation",
    "restrict": "traffic_rerouting",
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


def _slug_action(name: str, zone: Optional[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if zone:
        z = re.sub(r"[^a-z0-9]+", "_", zone.lower()).strip("_")
        return f"{base}_{z}"[:64]
    return base[:64]


def _parse_allocation_plan(raw: Any) -> AllocationPlan:
    if not raw:
        return AllocationPlan()
    if isinstance(raw, str):
        raw = json.loads(raw)
    return AllocationPlan.model_validate(raw)


def _parse_severity_records(raw: Any) -> dict[str, SeverityRecord]:
    if not raw:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    records = [
        r if isinstance(r, SeverityRecord) else SeverityRecord.model_validate(r)
        for r in raw
    ]
    return {r.cluster_id: r for r in records}


def _zone_match(action_zone: str, target_zone: Optional[str]) -> bool:
    if not target_zone:
        return True
    a = action_zone.lower()
    t = target_zone.lower()
    return a in t or t in a or a.split("/")[0].strip() in t


def derive_recommended_actions(
    plan: AllocationPlan,
    severity_by_cluster: dict[str, SeverityRecord],
    scenario_id: Optional[str] = None,
) -> list[RecommendedAction]:
    """Build action list from DS-006 matched to allocation crises."""
    db = _load_db()
    ds6_actions = db.get("DS-006", {}).get("actions", [])
    recommended: list[RecommendedAction] = []
    seen: set[str] = set()

    for alloc in plan.allocations:
        zone = alloc.location.zone
        sev = severity_by_cluster.get(alloc.cluster_id)
        for act in ds6_actions:
            if scenario_id and act.get("scenario_id") != scenario_id:
                continue
            if zone and act.get("target_zone") and not _zone_match(
                act["target_zone"], zone
            ):
                continue
            if act["action_id"] in seen:
                continue
            sim_type = _ACTION_TYPE_TO_SIM.get(
                act.get("action_type", ""), "emergency_dispatch"
            )
            action_key = _slug_action(act.get("action_name", act["action_id"]), zone)
            cost: dict[str, Any] = {"duration_hours": 2}
            if sim_type == "traffic_rerouting":
                cost["police_units"] = 3
            elif sim_type == "emergency_dispatch":
                cost["ambulances"] = 1
            elif sim_type == "shelter_activation":
                cost["shelters"] = 1

            recommended.append(
                RecommendedAction(
                    action_id=act["action_id"],
                    action_key=action_key,
                    simulation_type=sim_type,
                    action_type=act.get("action_type", ""),
                    description=act.get("description", ""),
                    target_zone=act.get("target_zone") or zone,
                    target_city=act.get("target_city"),
                    cluster_id=alloc.cluster_id,
                    crisis_type=alloc.crisis_type,
                    resource_cost=cost,
                )
            )
            seen.add(act["action_id"])

        if not any(r.cluster_id == alloc.cluster_id for r in recommended):
            for assign in alloc.assignments:
                if assign.assigned_count <= 0:
                    continue
                sim_type = {
                    "ambulances": "emergency_dispatch",
                    "police_units": "traffic_rerouting",
                    "rescue_teams": "emergency_dispatch",
                    "shelters": "shelter_activation",
                    "generators": "utility_escalation",
                    "water_tankers": "utility_escalation",
                }.get(assign.resource_type, "emergency_dispatch")
                key = f"{sim_type}_{alloc.cluster_id}_{assign.resource_type}"
                recommended.append(
                    RecommendedAction(
                        action_id=f"SYN-{alloc.cluster_id}-{assign.resource_type}",
                        action_key=key,
                        simulation_type=sim_type,
                        action_type="synthetic",
                        description=f"Deploy {assign.assigned_count} {assign.resource_type}",
                        target_zone=zone,
                        target_city=None,
                        cluster_id=alloc.cluster_id,
                        crisis_type=alloc.crisis_type,
                        resource_cost={
                            assign.resource_type: assign.assigned_count,
                            "duration_hours": 2,
                        },
                    )
                )

    return recommended


def _roads_for_zone(zone: Optional[str], city: Optional[str]) -> list[dict[str, Any]]:
    roads = _load_db().get("DS-003", {}).get("roads", [])
    matched = []
    for road in roads:
        if city and road.get("city", "").lower() != city.lower():
            continue
        if zone and road.get("zone") and not _zone_match(road["zone"], zone):
            continue
        matched.append(road)
    return matched or roads[:1]


def _hospital_for_zone(zone: Optional[str], city: Optional[str]) -> dict[str, Any]:
    for res in _load_db().get("DS-004", {}).get("resources", []):
        if res.get("resource_type") != "hospital":
            continue
        if city and res.get("city", "").lower() != city.lower():
            continue
        return res
    hospitals = [
        r for r in _load_db().get("DS-004", {}).get("resources", [])
        if r.get("resource_type") == "hospital"
    ]
    return hospitals[0] if hospitals else {"capacity": 200, "name": "Default Hospital"}


def simulate_traffic_rerouting(action: RecommendedAction) -> ActionSimulation:
    roads = _roads_for_zone(action.target_zone, action.target_city)
    road = roads[0]
    t1 = road.get("T1", {})
    t2 = road.get("T2", {})
    before_cong = (t1.get("congestion_percent", 85) or 85) / 100.0
    before_speed = float(t1.get("current_speed_kmh", 12) or 12)
    reduction = float(t2.get("congestion_reduction_percent", 55) or 55) / 100.0
    after_cong = round(max(0.15, before_cong * (1 - reduction)), 2)
    after_speed = round(
        max(before_speed, float(t2.get("current_speed_kmh", 31) or 31)), 1
    )
    alt = t2.get("diversion_via", "Sector G-9 Service Road")
    improvement = round((before_cong - after_cong) / max(before_cong, 0.01) * 100, 1)

    return ActionSimulation(
        action=action.action_key,
        simulation_type="traffic_rerouting",
        before_state={
            "congestion_index": round(before_cong, 2),
            "avg_speed_kmh": before_speed,
            "road": road.get("road_name"),
            "status": t1.get("status", "BLOCKED"),
        },
        response_action=f"redirect via {alt} + 3 alternate routes",
        expected_after_state={
            "congestion_index": after_cong,
            "avg_speed_kmh": after_speed,
            "diversion_active": True,
        },
        response_time_improvement_pct=improvement,
        resource_cost=action.resource_cost or {"police_units": 3, "duration_hours": 2},
        side_effects=[],
        agent_trace_note="Traffic graph updated from DS-003 T1→T2 diversion curve.",
    )


def simulate_emergency_dispatch(action: RecommendedAction) -> ActionSimulation:
    travel_mins = 12
    on_scene_mins = 25
    return_mins = 18
    total_before = 55
    total_after = travel_mins + on_scene_mins
    improvement = round((total_before - total_after) / total_before * 100, 1)

    return ActionSimulation(
        action=action.action_key,
        simulation_type="emergency_dispatch",
        before_state={
            "dispatch_eta_mins": total_before,
            "units_available": 0,
            "on_scene": False,
        },
        response_action=f"Dispatch allocated units; ETA {travel_mins} min",
        expected_after_state={
            "dispatch_eta_mins": travel_mins,
            "on_scene_time_mins": on_scene_mins,
            "return_time_mins": return_mins,
            "on_scene": True,
        },
        response_time_improvement_pct=improvement,
        resource_cost=action.resource_cost,
        side_effects=[],
        agent_trace_note="Mock Rescue API: travel + on-scene per DS-006 ACT-001 pattern.",
    )


def simulate_hospital_preparation(action: RecommendedAction) -> ActionSimulation:
    hospital = _hospital_for_zone(action.target_zone, action.target_city)
    capacity = int(hospital.get("capacity", 200))
    beds_allocated = min(capacity, max(20, capacity // 5))
    staff_recall_mins = 20

    return ActionSimulation(
        action=action.action_key,
        simulation_type="hospital_preparation",
        before_state={
            "beds_available": capacity,
            "beds_allocated_emergency": 0,
            "staff_recall_mins": None,
        },
        response_action=f"Reserve {beds_allocated} beds + recall staff at {hospital.get('name')}",
        expected_after_state={
            "beds_available": capacity - beds_allocated,
            "beds_allocated_emergency": beds_allocated,
            "staff_recall_mins": staff_recall_mins,
        },
        response_time_improvement_pct=round(
            beds_allocated / max(capacity, 1) * 40, 1
        ),
        resource_cost={"field_teams": 1, "duration_hours": 3},
        side_effects=[],
        agent_trace_note="Bed surge modeled from DS-004 hospital capacity.",
    )


def simulate_utility_escalation(action: RecommendedAction) -> ActionSimulation:
    restore_hours = 4.0
    if action.crisis_type in ("power_outage", "water_main_burst"):
        restore_hours = 2.5

    return ActionSimulation(
        action=action.action_key,
        simulation_type="utility_escalation",
        before_state={
            "grid_status": "degraded",
            "estimated_restore_hours": 8.0,
            "water_pressure_pct": 40,
        },
        response_action="Escalate to utility repair teams + portable generators",
        expected_after_state={
            "grid_status": "recovering",
            "estimated_restore_hours": restore_hours,
            "water_pressure_pct": 75,
        },
        response_time_improvement_pct=round((8.0 - restore_hours) / 8.0 * 100, 1),
        resource_cost=action.resource_cost or {"generators": 2, "duration_hours": restore_hours},
        side_effects=[],
        agent_trace_note="Restore timeline from DS-006 notify/utility patterns.",
    )


def simulate_public_evacuation_alert(action: RecommendedAction) -> ActionSimulation:
    recipients = 12400
    return ActionSimulation(
        action=action.action_key,
        simulation_type="public_evacuation_alert",
        before_state={
            "congestion_index": 0.55,
            "evacuation_started_pct": 0,
            "alert_reach": 0,
        },
        response_action=f"SMS/push evacuation advisory to {recipients} residents",
        expected_after_state={
            "congestion_index": 0.72,
            "evacuation_started_pct": 35,
            "alert_reach": recipients,
        },
        response_time_improvement_pct=15.0,
        resource_cost={"duration_hours": 1},
        side_effects=[],
        agent_trace_note="Evacuation alert may spike outbound road congestion (known side effect).",
    )


def simulate_shelter_activation(
    action: RecommendedAction,
    displaced_estimate: int = 500,
) -> ActionSimulation:
    shelter_cap = 300
    occupancy = min(shelter_cap, displaced_estimate)
    over_capacity = displaced_estimate > shelter_cap

    return ActionSimulation(
        action=action.action_key,
        simulation_type="shelter_activation",
        before_state={
            "shelter_capacity": shelter_cap,
            "occupancy": 0,
            "displaced_estimate": displaced_estimate,
        },
        response_action=f"Activate cooling/shelter facility for up to {shelter_cap} people",
        expected_after_state={
            "shelter_capacity": shelter_cap,
            "occupancy": occupancy,
            "utilization_pct": round(occupancy / shelter_cap * 100, 1),
        },
        response_time_improvement_pct=round(occupancy / max(displaced_estimate, 1) * 100, 1),
        resource_cost=action.resource_cost or {"shelters": 1, "duration_hours": 6},
        side_effects=(
            ["Overflow: need secondary shelter activation"]
            if over_capacity
            else []
        ),
        agent_trace_note="Capacity vs displaced from severity population estimate.",
    )


_SIMULATORS = {
    "traffic_rerouting": simulate_traffic_rerouting,
    "emergency_dispatch": simulate_emergency_dispatch,
    "hospital_preparation": simulate_hospital_preparation,
    "utility_escalation": simulate_utility_escalation,
    "public_evacuation_alert": simulate_public_evacuation_alert,
    "shelter_activation": simulate_shelter_activation,
}


def _append_simulations(ctx: InvocationContext, new_sims: list[ActionSimulation]) -> None:
    existing = ctx.session.state.get("temp:action_simulations_partial", [])
    if isinstance(existing, str):
        existing = json.loads(existing)
    merged = existing + [s.model_dump(mode="json") for s in new_sims]
    ctx.session.state["temp:action_simulations_partial"] = merged


def _actions_for_type(ctx: InvocationContext, sim_type: str) -> list[RecommendedAction]:
    raw = ctx.session.state.get("temp:recommended_actions", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    actions = [RecommendedAction.model_validate(a) for a in raw]
    return [a for a in actions if a.simulation_type == sim_type]


def _severity_map(ctx: InvocationContext) -> dict[str, SeverityRecord]:
    return _parse_severity_records(ctx.session.state.get("temp:severity_records", []))


class SimulationStepAgent(BaseAgent):
    """One simulation-type step in the SequentialAgent chain."""

    step_type: str = Field(default="traffic_rerouting")

    @override
    async def _run_async_impl(self, ctx: InvocationContext):
        actions = _actions_for_type(ctx, self.step_type)
        severity = _severity_map(ctx)
        results: list[ActionSimulation] = []

        _emit_trace(
            f"Simulate {self.step_type} impacts.",
            f"tool_use: {self.step_type} — {len(actions)} action(s) queued.",
            "Compute before/after state from mock traffic, hospital, utility datasets.",
        )

        simulator = _SIMULATORS[self.step_type]
        for act in actions:
            if self.step_type == "shelter_activation":
                sev = severity.get(act.cluster_id or "")
                displaced = int((sev.population_at_risk if sev else 500) * 0.1)
                sim = simulate_shelter_activation(act, displaced_estimate=displaced)
            else:
                sim = simulator(act)
            results.append(sim)
            _emit_trace(
                f"Completed {self.step_type} for {act.action_key}.",
                f"tool_use result: improvement={sim.response_time_improvement_pct}%, "
                f"before={sim.before_state}, after={sim.expected_after_state}",
                f"Store simulation for {act.action}.",
            )

        _append_simulations(ctx, results)
        if False:
            yield Event()


class ActionPlanLoaderAgent(BaseAgent):
    """Loads recommended actions from allocation plan + DS-006."""

    @override
    async def _run_async_impl(self, ctx: InvocationContext):
        plan = _parse_allocation_plan(ctx.session.state.get("temp:allocation_plan", {}))
        severity = _parse_severity_records(ctx.session.state.get("temp:severity_records", []))
        scenario_id = None
        raw_cfg = ctx.session.state.get("city_config")
        if isinstance(raw_cfg, dict):
            scenario_id = raw_cfg.get("scenario_id")

        actions = derive_recommended_actions(plan, severity, scenario_id=scenario_id)
        ctx.session.state["temp:recommended_actions"] = [
            a.model_dump(mode="json") for a in actions
        ]
        ctx.session.state["temp:action_simulations_partial"] = []

        _emit_trace(
            "Translate allocation plan into executable simulations.",
            f"Derived {len(actions)} recommended actions from DS-006 + allocation.",
            "Chain sub-simulation agents per action type.",
        )
        if False:
            yield Event()


async def get_simulation_batch(tool_context: ToolContext) -> dict[str, Any]:
    """Return partial simulations for side-effect LLM reasoning."""
    raw = tool_context.state.get("temp:action_simulations_partial", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    return {
        "simulation_count": len(raw),
        "simulations": raw,
    }


SIDE_EFFECT_INSTRUCTION = f"""
You are the CIRO Action Simulation side-effect reasoner.

{URDU_RULE}

Call `get_simulation_batch` once to load deterministic simulation results.

For each simulation:
1. call_llm: Add realistic side_effects (1–3 short strings) especially for:
   - traffic_rerouting (alternate route congestion)
   - public_evacuation_alert (evacuation congestion spike)
   - shelter_activation (overflow)
   - utility_escalation (rolling blackout risk)
2. Preserve all numeric fields from the tool output (before_state, after_state,
   response_time_improvement_pct, resource_cost).
3. Copy agent_trace_note from DS-006 patterns where relevant.

Return ActionSimulationResult with every simulation enriched with side_effects.
Print [THOUGHT], [OBSERVATION] (prefix call_llm: side-effect reasoning for <action>),
and [ACTION] per modified simulation.
"""


async def _persist_action_simulations(callback_context) -> None:
    state = callback_context.state
    raw = state.get("action_simulation_result") or state.get("temp:action_simulation_result")
    if raw:
        if isinstance(raw, str):
            raw = json.loads(raw)
        result = ActionSimulationResult.model_validate(raw)
    else:
        partial = state.get("temp:action_simulations_partial", [])
        sims = [ActionSimulation.model_validate(s) for s in partial]
        result = ActionSimulationResult(
            simulations=sims,
            simulation_summary=f"{len(sims)} action simulations completed.",
        )

    state["temp:action_simulations"] = result.model_dump(mode="json")
    _emit_trace(
        "Action simulations ready for response execution agent.",
        f"Persisted {len(result.simulations)} simulations to temp:action_simulations.",
        "DS-006 agent_trace_note fields available for judge review.",
    )


action_plan_loader = ActionPlanLoaderAgent(
    name="ActionPlanLoader",
    description="Derives recommended actions from allocation plan and DS-006.",
)

side_effect_reasoner = LlmAgent(
    name="ActionSideEffectReasoner",
    model=GEMINI_MODEL,
    description="Adds side-effect reasoning to deterministic action simulations.",
    instruction=SIDE_EFFECT_INSTRUCTION,
    tools=[FunctionTool(get_simulation_batch)],
    output_schema=ActionSimulationResult,
    output_key="action_simulation_result",
)

action_simulation_agent = SequentialAgent(
    name="ActionSimulationAgent",
    description=(
        "Chains traffic, dispatch, hospital, utility, evacuation, and shelter "
        "simulations then LLM side-effect reasoning."
    ),
    sub_agents=[
        action_plan_loader,
        SimulationStepAgent(
            name="TrafficSimulation",
            description="Simulates traffic rerouting before/after congestion.",
            step_type="traffic_rerouting",
        ),
        SimulationStepAgent(
            name="DispatchSimulation",
            description="Simulates emergency dispatch travel and on-scene times.",
            step_type="emergency_dispatch",
        ),
        SimulationStepAgent(
            name="HospitalSimulation",
            description="Simulates hospital bed and staff recall preparation.",
            step_type="hospital_preparation",
        ),
        SimulationStepAgent(
            name="UtilitySimulation",
            description="Simulates utility restoration escalation timelines.",
            step_type="utility_escalation",
        ),
        SimulationStepAgent(
            name="EvacuationSimulation",
            description="Simulates public evacuation alert congestion effects.",
            step_type="public_evacuation_alert",
        ),
        SimulationStepAgent(
            name="ShelterSimulation",
            description="Simulates shelter capacity vs displaced population.",
            step_type="shelter_activation",
        ),
        side_effect_reasoner,
    ],
    after_agent_callback=_persist_action_simulations,
)

root_agent = action_simulation_agent
