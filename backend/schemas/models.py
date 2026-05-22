"""CIRO Pydantic v2 schemas — shared across all agents."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SignalSource(str, Enum):
    SOCIAL = "social"
    WEATHER = "weather"
    TRAFFIC = "traffic"
    SENSOR = "sensor"
    FIELD_REPORT = "field_report"


class CityConfig(BaseModel):
    """Geographic scope for signal ingestion."""

    city: str
    bbox_north: float
    bbox_south: float
    bbox_east: float
    bbox_west: float
    phase: str = "T1_during"
    scenario_id: Optional[str] = None


class WeatherSignalPayload(BaseModel):
    """Normalized live or mock weather snapshot for root-agent tools."""

    city: str
    latitude: float
    longitude: float
    timestamp: datetime
    temperature_c: float
    feels_like_c: Optional[float] = None
    humidity_percent: Optional[int] = None
    rainfall_mm_per_hour: float = 0.0
    wind_speed_kmh: Optional[float] = None
    alert_type: Optional[str] = None
    alert_level: str = "LOW"
    flood_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    forecast_next_2hr: Optional[str] = None
    agent_trigger: str = "NO_ACTION"
    threshold_breached: bool = False
    source_status: str = "LIVE"
    raw: dict[str, Any] = Field(default_factory=dict)


class ActiveCrisisEntry(BaseModel):
    """One row in app:active_crisis_registry."""

    incident_id: str
    scenario_id: Optional[str] = None
    city: str
    phase: str = "T1_during"
    zone: str = "TBD"
    crisis_type: str = "pending"
    severity_level: int = Field(default=1, ge=1, le=5)
    status: str = "PROCESSING"
    created_at: str
    updated_at: str
    cluster_ids: list[str] = Field(default_factory=list)
    resources_dispatched: list[str] = Field(default_factory=list)
    notifications_sent: int = 0
    operator_override: Optional[str] = None


class SignalEvent(BaseModel):
    """Normalized crisis signal from any ingestion source."""

    signal_id: str
    source: SignalSource
    timestamp: datetime
    city: str
    zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crisis_type: Optional[str] = None
    severity: Optional[str] = None
    summary: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    raw: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalBatch(BaseModel):
    """Structured output from each ingestion sub-agent."""

    signals: list[SignalEvent] = Field(default_factory=list)
    source_status: str = "LIVE"
    error: Optional[str] = None


class IntakeResult(BaseModel):
    """Structured output from the Urdu intake LlmAgent."""

    resolved: bool
    clarification_question: Optional[str] = None
    extracted_city: Optional[str] = None
    extracted_zone: Optional[str] = None
    extracted_crisis_type: Optional[str] = None
    signals_injected: int = 0
    detected_language: str = "english"


class ScoredSignal(BaseModel):
    """SignalEvent with decomposed credibility factors."""

    signal_id: str
    credibility_score: float = Field(ge=0.0, le=1.0)
    source_reputation: float = Field(ge=0.0, le=1.0)
    geolocation_confidence: float = Field(ge=0.0, le=1.0)
    mention_velocity: float = Field(ge=0.0, le=1.0)
    contradiction_factor: float = Field(ge=0.0, le=1.0)
    signal: SignalEvent


class SignalCluster(BaseModel):
    """Correlated signals grouped into a candidate incident."""

    cluster_id: str
    city: str
    zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crisis_type: Optional[str] = None
    signal_ids: list[str] = Field(default_factory=list)
    signals: list[SignalEvent] = Field(default_factory=list)
    aggregate_credibility: float = Field(ge=0.0, le=1.0)
    mention_velocity: float = Field(ge=0.0, le=1.0, default=0.0)
    hypothesis_diversity_flag: bool = False
    semantic_theme: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusionClusterLlm(BaseModel):
    """Flat cluster shape for LlmAgent output_schema (ADK rejects nested $ref/$defs)."""

    cluster_id: str
    city: str
    zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    crisis_type: Optional[str] = None
    signal_ids: list[str] = Field(default_factory=list)
    aggregate_credibility: float = Field(ge=0.0, le=1.0, default=0.0)
    mention_velocity: float = Field(default=0.0, ge=0.0, le=1.0)
    hypothesis_diversity_flag: bool = False
    semantic_theme: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusionResultLlm(BaseModel):
    """LLM structured output for signal fusion; hydrate to FusionResult in callback."""

    clusters: list[FusionClusterLlm] = Field(default_factory=list)


class FusionResult(BaseModel):
    """Output of the signal fusion agent."""

    clusters: list[SignalCluster] = Field(default_factory=list)


class CrisisType(str, Enum):
    """Supported crisis classifications (slug values)."""

    URBAN_FLOOD = "urban_flood"
    HEATWAVE = "heatwave"
    TRAFFIC_ACCIDENT = "traffic_accident"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    POWER_OUTAGE = "power_outage"
    PUBLIC_DISORDER = "public_disorder"
    DISEASE_CLUSTER = "disease_cluster"
    FIRE = "fire"
    WATER_MAIN_BURST = "water_main_burst"


class ClassificationHypothesis(BaseModel):
    type: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClusterLocation(BaseModel):
    zone: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class ClusterClassification(BaseModel):
    """Classification output for one fused signal cluster."""

    cluster_id: str
    primary_classification: str
    confidence: float = Field(ge=0.0, le=1.0)
    secondary_hypothesis: Optional[ClassificationHypothesis] = None
    conflicting_signals: list[str] = Field(default_factory=list)
    location: ClusterLocation
    requires_verification: bool = False


class ClassificationResult(BaseModel):
    """Output of the crisis classifier agent."""

    classifications: list[ClusterClassification] = Field(default_factory=list)


class SeverityRecord(BaseModel):
    """Severity and evolution estimate for one classified crisis cluster."""

    cluster_id: str
    crisis_type: str
    severity_level: int = Field(ge=1, le=5)
    severity_label: str
    response_priority: str
    affected_radius_km: float = Field(ge=0.0)
    population_at_risk: int = Field(ge=0)
    population_p10: int = Field(ge=0)
    population_p90: int = Field(ge=0)
    expected_duration_hours: float = Field(ge=0.0)
    peak_impact_eta: datetime
    spread_risk_score: float = Field(ge=0.0, le=1.0)
    environmental_factors: dict[str, Any] = Field(default_factory=dict)
    requires_verification: bool = False


class SeverityPredictionResult(BaseModel):
    """Output of the severity & evolution predictor agent."""

    records: list[SeverityRecord] = Field(default_factory=list)


class ResourceUnitAssignment(BaseModel):
    resource_type: str
    required_count: int = 0
    assigned_count: int = 0
    assigned_unit_ids: list[str] = Field(default_factory=list)
    avg_travel_time_mins: Optional[float] = None


class CrisisAllocation(BaseModel):
    cluster_id: str
    crisis_type: str
    severity_level: int = Field(ge=1, le=5)
    priority_score: float = 0.0
    location: ClusterLocation
    assignments: list[ResourceUnitAssignment] = Field(default_factory=list)
    resource_deficit: bool = False
    deficit_types: list[str] = Field(default_factory=list)
    trade_off_note: Optional[str] = None


class AllocationPlan(BaseModel):
    """Resource allocation plan across simultaneous crises."""

    crises_count: int = 0
    unmet_demand: int = 0
    trade_off_summary: str = ""
    allocations: list[CrisisAllocation] = Field(default_factory=list)


class RecommendedAction(BaseModel):
    """Action candidate derived from allocation plan and DS-006."""

    action_id: str
    action_key: str
    simulation_type: str
    action_type: str
    description: str
    target_zone: Optional[str] = None
    target_city: Optional[str] = None
    cluster_id: Optional[str] = None
    crisis_type: Optional[str] = None
    resource_cost: dict[str, Any] = Field(default_factory=dict)


class ActionSimulation(BaseModel):
    """Before/after simulation for one response action."""

    action: str
    simulation_type: str
    before_state: dict[str, Any] = Field(default_factory=dict)
    response_action: str
    expected_after_state: dict[str, Any] = Field(default_factory=dict)
    response_time_improvement_pct: float = 0.0
    resource_cost: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    agent_trace_note: Optional[str] = None


class ActionSimulationResult(BaseModel):
    """Output of the action simulation agent pipeline."""

    simulations: list[ActionSimulation] = Field(default_factory=list)
    simulation_summary: str = ""


# Aliases for notification agent pipeline inputs
ClassifiedIncident = ClusterClassification
SeverityAssessment = SeverityRecord


class NotificationRecord(BaseModel):
    notification_id: str
    incident_id: str
    audience: str
    channel: str
    message_en: str
    message_ur: Optional[str] = None
    zone_id: str
    reach: int = 0
    delivery_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    fm_channel: Optional[str] = None
    status: str = "SENT"
    timestamp: datetime
    retraction: bool = False


class NotificationBatch(BaseModel):
    notifications: list[NotificationRecord] = Field(default_factory=list)
    total_reach: int = 0
    retraction_issued: bool = False
    verified: bool = True
    incident_ids: list[str] = Field(default_factory=list)


class FinalIncidentRecord(BaseModel):
    """Merged API-facing incident output."""

    incident_ids: list[str] = Field(default_factory=list)
    verified: bool = True
    retraction_issued: bool = False
    notifications: list[NotificationRecord] = Field(default_factory=list)
    allocation_summary: dict[str, Any] = Field(default_factory=dict)
    severity_summary: list[dict[str, Any]] = Field(default_factory=list)
    classification_summary: list[dict[str, Any]] = Field(default_factory=list)
