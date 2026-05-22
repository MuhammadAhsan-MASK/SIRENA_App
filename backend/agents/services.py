"""Shared in-memory session service for CIRO API and ADK endpoints."""

from __future__ import annotations

from google.adk.cli.service_registry import get_service_registry
from google.adk.sessions.in_memory_session_service import InMemorySessionService

ciro_session_service = InMemorySessionService()


def ciro_memory_session_factory(uri: str, **kwargs) -> InMemorySessionService:
    return ciro_session_service


get_service_registry().register_session_service("memory", ciro_memory_session_factory)
