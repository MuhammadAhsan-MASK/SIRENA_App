"""
Resource allocation — Sequential workflow: greedy solver + LLM trade-off explainer.

Reads ``temp:severity_records`` and DS-004 resource pool, allocates by priority
(severity * population / distance), flags RESOURCE_DEFICIT, writes
``temp:allocation_plan``.
"""

from __future__ import annotations

import json
import math
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
from typing_extensions import override

from schemas.models import (
    AllocationPlan,
    ClusterClassification,
    ClusterLocation,
    CrisisAllocation,
    ResourceUnitAssignment,
    SeverityRecord,
)

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATHS = (
    PROJECT_ROOT / "mock_data" / "ciro_all_datasets.json",
    PROJECT_ROOT / "mock_data" / "ciro_datasets.json",
)
RESOURCES_JSON = PROJECT_ROOT / "mock_data" / "resources.json"
ACCEPTABLE_TRAVEL_MINS = 45.0
ROAD_SPEED_KMH = 40.0

URDU_RULE = (
    "Input may be Urdu, Roman Urdu, or mixed. Parse directly. "
    "paani=water, aag=fire, hadsa=accident, bijli gayi=power outage, "
    "baadh=flood, rasta band=road blocked, garmi=heatwave"
)

# Canonical resource types (architecture spec)
RESOURCE_TYPES = (
    "ambulances",
    "police_units",
    "rescue_teams",
    "fire_trucks",
    "shelters",
    "water_tankers",
    "drones",
    "field_teams",
    "generators",
)

_DS_TYPE_MAP: dict[str, str] = {
    "ambulance": "ambulances",
    "police_unit": "police_units",
    "rescue_team": "rescue_teams",
    "fire_brigade": "fire_trucks",
    "cooling_center": "shelters",
    "water_tanker": "water_tankers",
    "traffic_warden": "field_teams",
    "utility_repair_team": "generators",
}

_BASE_REQUIREMENTS: dict[str, dict[str, int]] = {
    "urban_flood": {
        "ambulances": 3,
        "rescue_teams": 3,
        "fire_trucks": 1,
        "water_tankers": 2,
        "police_units": 2,
        "field_teams": 2,
        "drones": 1,
        "shelters": 1,
        "generators": 1,
    },
    "heatwave": {
        "ambulances": 4,
        "shelters": 2,
        "water_tankers": 2,
        "field_teams": 1,
        "police_units": 1,
        "generators": 2,
    },
    "traffic_accident": {
        "ambulances": 2,
        "police_units": 1,
        "rescue_teams": 1,
        "fire_trucks": 1,
    },
    "public_disorder": {
        "police_units": 4,
        "field_teams": 2,
        "ambulances": 2,
        "drones": 1,
    },
    "power_outage": {
        "generators": 3,
        "field_teams": 2,
        "ambulances": 2,
        "shelters": 1,
    },
    "fire": {
        "fire_trucks": 3,
        "ambulances": 2,
        "rescue_teams": 2,
        "police_units": 1,
        "drones": 1,
    },
    "water_main_burst": {
        "water_tankers": 3,
        "rescue_teams": 2,
        "field_teams": 2,
        "generators": 1,
    },
    "infrastructure_failure": {
        "field_teams": 2,
        "generators": 2,
        "rescue_teams": 1,
        "police_units": 1,
    },
    "disease_cluster": {
        "ambulances": 3,
        "field_teams": 2,
        "shelters": 1,
        "police_units": 1,
    },
}

_SEVERITY_SCALE = {1: 0.25, 2: 0.5, 3: 1.0, 4: 1.5, 5: 2.0}

_DB: Optional[dict[str, Any]] = None


def _emit_trace(thought: str, observation: str, action: str) -> None:
    print(f"[THOUGHT] {thought}")
    print(f"[OBSERVATION] {observation}")
    print(f"[ACTION] {action}")


def _emit_allocation_span(
    crises_count: int,
    unmet_demand: int,
    trade_off_summary: str,
) -> None:
    print(
        "[OBSERVATION] resource_allocation span: "
        f"crises_count={crises_count}, unmet_demand={unmet_demand}, "
        f"trade_off_summary={trade_off_summary}"
    )


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


def _travel_time_mins(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Mock urban travel time from straight-line distance at ROAD_SPEED_KMH.

    Production: replace with Google Maps Directions API (traffic_model=best_guess)
    via a routing service that pre-computes an eta_cache keyed by resource/zone
    pairs — the greedy solver is a BaseAgent and cannot call LlmAgent FunctionTools.
    """
    km = _haversine_km(lat1, lng1, lat2, lng2)
    return (km / ROAD_SPEED_KMH) * 60.0


def _parse_severity_records(raw: Any) -> list[SeverityRecord]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [
        r if isinstance(r, SeverityRecord) else SeverityRecord.model_validate(r)
        for r in raw
    ]


def _parse_classifications(raw: Any) -> dict[str, ClusterClassification]:
    if not raw:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    items = [
        c if isinstance(c, ClusterClassification) else ClusterClassification.model_validate(c)
        for c in raw
    ]
    return {c.cluster_id: c for c in items}


def _lookup_zone_coords(city: str, zone: Optional[str]) -> tuple[float, float]:
    for z in _load_db().get("DS-005", {}).get("zones", []):
        if z.get("city", "").lower() != city.lower():
            continue
        if zone:
            names = {z.get("zone_name", "").lower(), *[
                a.lower() for a in (z.get("zone_alias") or [])
            ]}
            if zone.lower() in names or any(zone.lower() in n for n in names if n):
                return float(z["lat_center"]), float(z["lng_center"])
        else:
            return float(z["lat_center"]), float(z["lng_center"])
    return 33.69, 73.01


def _crisis_location(record: SeverityRecord, clf: Optional[ClusterClassification]) -> ClusterLocation:
    if clf:
        return clf.location
    lat, lon = _lookup_zone_coords("Islamabad", None)
    return ClusterLocation(zone=None, lat=lat, lon=lon)


def _scale_requirements(crisis_type: str, severity_level: int) -> dict[str, int]:
    base = _BASE_REQUIREMENTS.get(crisis_type, _BASE_REQUIREMENTS["infrastructure_failure"])
    factor = _SEVERITY_SCALE.get(severity_level, 1.0)
    return {rtype: max(0, int(count * factor)) for rtype, count in base.items()}


def _build_resource_pool(city: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """Build per-type unit pool from DS-004 (+ mock resources.json for drones)."""
    pool: dict[str, list[dict[str, Any]]] = {t: [] for t in RESOURCE_TYPES}
    for res in _load_db().get("DS-004", {}).get("resources", []):
        if res.get("status") != "available":
            continue
        if city and res.get("city", "").lower() != city.lower():
            continue
        canonical = _DS_TYPE_MAP.get(res.get("resource_type", ""))
        if not canonical:
            continue
        pool[canonical].append(
            {
                "unit_id": res["resource_id"],
                "lat": res["lat"],
                "lng": res["lng"],
                "name": res.get("name"),
                "zone": res.get("zone"),
            }
        )

    if RESOURCES_JSON.is_file():
        extra = json.loads(RESOURCES_JSON.read_text(encoding="utf-8"))
        for key, units in extra.items():
            canonical = key if key in RESOURCE_TYPES else _DS_TYPE_MAP.get(key, key)
            if canonical not in pool:
                continue
            for u in units:
                if not u.get("available", True):
                    continue
                pool[canonical].append(
                    {
                        "unit_id": u["unit_id"],
                        "lat": 33.694,
                        "lng": 73.012,
                        "name": u.get("location"),
                        "zone": "G-10",
                    }
                )

    pool.setdefault("drones", [])
    if not pool["drones"]:
        pool["drones"] = [
            {"unit_id": "DRN-01", "lat": 33.700, "lng": 73.020, "name": "CDA Drone 1", "zone": "G-10"},
            {"unit_id": "DRN-02", "lat": 33.710, "lng": 73.030, "name": "CDA Drone 2", "zone": "F-8"},
        ]
    return pool


def _priority_score(
    record: SeverityRecord,
    location: ClusterLocation,
    pool: dict[str, list[dict[str, Any]]],
) -> float:
    lat = location.lat or 33.69
    lon = location.lon or 73.01
    nearest = 1.0
    for units in pool.values():
        for u in units:
            nearest = min(nearest, _haversine_km(lat, lon, u["lat"], u["lng"]))
    distance = max(nearest, 0.5)
    return (record.severity_level * record.population_at_risk) / distance


def run_greedy_allocation(
    severity_records: list[SeverityRecord],
    classifications: dict[str, ClusterClassification],
    city: Optional[str] = None,
) -> AllocationPlan:
    """Deterministic priority-weighted greedy allocation with travel-time cost."""
    pool = _build_resource_pool(city)
    crises: list[tuple[float, SeverityRecord, ClusterLocation, dict[str, int]]] = []

    for record in severity_records:
        clf = classifications.get(record.cluster_id)
        loc = _crisis_location(record, clf)
        reqs = _scale_requirements(record.crisis_type, record.severity_level)
        score = _priority_score(record, loc, pool)
        crises.append((score, record, loc, reqs))

    crises.sort(key=lambda x: -x[0])
    allocations: list[CrisisAllocation] = []
    total_unmet = 0

    for priority, record, loc, requirements in crises:
        lat = loc.lat or 33.69
        lon = loc.lon or 73.01
        assignment_rows: list[ResourceUnitAssignment] = []
        deficit_types: list[str] = []

        for rtype in RESOURCE_TYPES:
            required = requirements.get(rtype, 0)
            if required <= 0:
                continue

            units = pool.get(rtype, [])
            ranked = sorted(
                units,
                key=lambda u: _travel_time_mins(lat, lon, u["lat"], u["lng"]),
            )
            assigned_ids: list[str] = []
            travel_times: list[float] = []
            for unit in ranked:
                if len(assigned_ids) >= required:
                    break
                ttime = _travel_time_mins(lat, lon, unit["lat"], unit["lng"])
                if ttime <= ACCEPTABLE_TRAVEL_MINS:
                    assigned_ids.append(unit["unit_id"])
                    travel_times.append(ttime)
                    pool[rtype] = [u for u in pool[rtype] if u["unit_id"] != unit["unit_id"]]

            assigned_count = len(assigned_ids)
            if assigned_count < required:
                deficit_types.append(rtype)
                total_unmet += required - assigned_count

            assignment_rows.append(
                ResourceUnitAssignment(
                    resource_type=rtype,
                    required_count=required,
                    assigned_count=assigned_count,
                    assigned_unit_ids=assigned_ids,
                    avg_travel_time_mins=(
                        round(sum(travel_times) / len(travel_times), 1)
                        if travel_times
                        else None
                    ),
                )
            )

        allocations.append(
            CrisisAllocation(
                cluster_id=record.cluster_id,
                crisis_type=record.crisis_type,
                severity_level=record.severity_level,
                priority_score=round(priority, 2),
                location=loc,
                assignments=assignment_rows,
                resource_deficit=bool(deficit_types),
                deficit_types=deficit_types,
            )
        )

    deficit_crises = [a for a in allocations if a.resource_deficit]
    summary = (
        f"{len(deficit_crises)} crisis(es) with RESOURCE_DEFICIT; "
        f"{total_unmet} total units unmet."
        if deficit_crises
        else "All crisis resource requirements met within travel-time limits."
    )

    plan = AllocationPlan(
        crises_count=len(allocations),
        unmet_demand=total_unmet,
        trade_off_summary=summary,
        allocations=allocations,
    )
    _emit_allocation_span(plan.crises_count, plan.unmet_demand, plan.trade_off_summary)
    return plan


class GreedyAllocationSolverAgent(BaseAgent):
    """Deterministic greedy allocator (no LLM)."""

    @override
    async def _run_async_impl(self, ctx: InvocationContext):  # noqa: ANN201
        records = _parse_severity_records(ctx.session.state.get("temp:severity_records", []))
        classifications = _parse_classifications(
            ctx.session.state.get("temp:classified_clusters", [])
        )
        city = None
        raw_cfg = ctx.session.state.get("city_config")
        if isinstance(raw_cfg, dict):
            city = raw_cfg.get("city")

        _emit_trace(
            "Multiple crises may compete for the same resource pool.",
            f"Running greedy allocation for {len(records)} severity records.",
            "Sort by severity*population/distance; assign nearest units within travel limit.",
        )

        plan = run_greedy_allocation(records, classifications, city=city)
        ctx.session.state["temp:allocation_solver_output"] = plan.model_dump(mode="json")

        _emit_trace(
            "Greedy solver finished.",
            f"Allocated across {plan.crises_count} crises; unmet_demand={plan.unmet_demand}.",
            "Hand off to LlmAgent for trade-off explanations if deficits exist.",
        )
        if False:
            yield Event()


async def get_allocation_context(tool_context: ToolContext) -> dict[str, Any]:
    """Return solver output for the trade-off explainer LlmAgent."""
    raw = tool_context.state.get("temp:allocation_solver_output", {})
    if isinstance(raw, str):
        raw = json.loads(raw)
    plan = AllocationPlan.model_validate(raw) if raw else AllocationPlan()
    deficits = [
        {
            "cluster_id": a.cluster_id,
            "crisis_type": a.crisis_type,
            "deficit_types": a.deficit_types,
            "assignments": [x.model_dump() for x in a.assignments if x.assigned_count < x.required_count],
        }
        for a in plan.allocations
        if a.resource_deficit
    ]
    return {
        "crises_count": plan.crises_count,
        "unmet_demand": plan.unmet_demand,
        "trade_off_summary": plan.trade_off_summary,
        "deficit_crises": deficits,
        "full_plan": raw,
    }


TRADEOFF_INSTRUCTION = f"""
You are the CIRO Resource Allocation Explainer.

{URDU_RULE}

The greedy solver has already run. Call `get_allocation_context` once to load results.

For every crisis with RESOURCE_DEFICIT (see deficit_crises):
- call_llm: Write a clear trade_off_note (2–4 sentences) explaining which resources
  are short, which higher-priority crisis received them, and recommended next steps.
  Prefix an [OBSERVATION] line with: call_llm: trade-off justification for <cluster_id>

Crises without deficits: leave trade_off_note null.

Return the complete AllocationPlan JSON (same structure as temp:allocation_solver_output)
with trade_off_note filled in and trade_off_summary updated to synthesize all deficits.

Print [THOUGHT], [OBSERVATION], [ACTION] per deficit crisis.
"""


async def _persist_allocation_plan(callback_context) -> None:
    state = callback_context.state
    raw = state.get("allocation_plan") or state.get("temp:allocation_plan_draft")
    if raw:
        if isinstance(raw, str):
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            raw = json.loads(raw)
        plan = AllocationPlan.model_validate(raw)
    else:
        raw_solver = state.get("temp:allocation_solver_output", {})
        plan = AllocationPlan.model_validate(raw_solver)

    state["temp:allocation_plan"] = plan.model_dump(mode="json")
    _emit_allocation_span(plan.crises_count, plan.unmet_demand, plan.trade_off_summary)
    _emit_trace(
        "Allocation plan persisted for execution agents.",
        f"resource_allocation span complete: {plan.crises_count} crises, "
        f"unmet_demand={plan.unmet_demand}.",
        "Write temp:allocation_plan for DS-006 response action agent.",
    )


greedy_allocation_solver = GreedyAllocationSolverAgent(
    name="GreedyAllocationSolver",
    description="Deterministic priority-weighted resource allocation solver.",
)

tradeoff_explainer_agent = LlmAgent(
    name="AllocationTradeoffExplainer",
    model=GEMINI_MODEL,
    description="Generates human-readable trade-off notes when resources are insufficient.",
    instruction=TRADEOFF_INSTRUCTION,
    tools=[FunctionTool(get_allocation_context)],
    # output_schema=AllocationPlan,
    # output_key="allocation_plan",
)

# WorkflowAgent pattern: deterministic solver → LLM explanation (SequentialAgent)
resource_allocation_workflow = SequentialAgent(
    name="ResourceAllocationWorkflow",
    description=(
        "Allocates emergency resources across crises using a greedy solver, "
        "then explains trade-offs when demand exceeds supply."
    ),
    sub_agents=[greedy_allocation_solver, tradeoff_explainer_agent],
    after_agent_callback=_persist_allocation_plan,
)

resource_allocator_agent = resource_allocation_workflow
root_agent = resource_allocation_workflow
