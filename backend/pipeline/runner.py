"""
CIRO incident processing pipeline — wires ADK agents in execution order.
"""

from __future__ import annotations

from google.adk.agents.sequential_agent import SequentialAgent

from agents.action import action_simulation_agent
from agents.crisis_classifier import crisis_classifier_agent
from agents.notification_agent import notification_agent
from agents.resource_allocator import resource_allocation_workflow
from agents.severity_predictor import severity_predictor_agent
from agents.signal_fusion import signal_fusion_agent
from agents.signal_ingestion import signal_ingestion_agent
from intake.urdu_intake import urdu_intake_agent

incident_processing_pipeline = SequentialAgent(
    name="IncidentProcessingPipeline",
    description=(
        "Full crisis pipeline: intake → ingest → fuse → classify → severity → "
        "allocate → simulate → notify"
    ),
    sub_agents=[
        urdu_intake_agent,
        signal_ingestion_agent,
        signal_fusion_agent,
        crisis_classifier_agent,
        severity_predictor_agent,
        resource_allocation_workflow,
        action_simulation_agent,
        notification_agent,
    ],
)
