"""
Urdu / Roman Urdu intake — first pipeline step converting freeform user text
into structured SignalEvent objects in ``temp:raw_signals``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from schemas.models import CityConfig, IntakeResult, SignalEvent, SignalSource

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"

_RU_KEYWORDS: dict[str, str] = {
    "paani": "water",
    "pani": "water",
    "paanee": "water",
    "aag": "fire",
    "ag": "fire",
    "baadh": "flood",
    "selaab": "flood",
    "hadsa": "accident",
    "bijli gayi": "power outage",
    "light nahi": "power outage",
    "light gayi": "power outage",
    "bijli nahi": "power outage",
    "rasta band": "road blocked",
    "rasta bnd": "road blocked",
    "garmi": "heatwave",
    "lu": "heatwave",
    "madad chahiye": "help needed",
    "paani ki pipe toot gayi": "water main burst",
    "pipe toot": "water main burst",
    "1122": "rescue needed",
}

_SORTED_RU_PHRASES = sorted(_RU_KEYWORDS.keys(), key=len, reverse=True)
_RU_WORDS = {w for phrase in _RU_KEYWORDS for w in phrase.lower().split()}
_URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_WORD_RE = re.compile(r"[a-zA-Z0-9\u0600-\u06FF]+")

AGENT_INSTRUCTION = """You are the CIRO Intake Agent. You handle the first contact with users.

Input may be Roman Urdu, English, or mixed. Parse directly.
paani=water, aag=fire, hadsa=accident, bijli gayi=power outage,
baadh=flood, rasta band=road blocked, garmi=heatwave,
selaab=flood, garmi/lu=heatwave, madad=help

Strict workflow:
1. Call normalize_roman_urdu(text) — tool_use. Always first.
2. Call check_city_config — tool_use. Check if city is already known.
3. call_llm: Analyze normalized text. Decide: clear / vague-location /
   vague-type / contradictory / understated.
4. If vague-location AND city unknown: set intake:clarification_question,
   set intake:resolved=False, return. Do NOT call text_to_signal_event yet.
5. For all other cases: call text_to_signal_event (tool_use) once per
   distinct crisis hypothesis. Set intake:resolved=True.
6. Return IntakeResult JSON.

Rules:
- Maximum ONE clarifying question ever. If city known, never ask again.
- Ambiguous crisis type → create multiple SignalEvents, never ask user.
- Contradictory input → create both severities, flag CONTRADICTORY_REPORT.
- Never deprioritize based on tone alone (thodi si problem = still process).
- Always print [THOUGHT], [OBSERVATION], [ACTION] for every step."""

# Note: the intake agent's single clarification question is produced by the LLM.
# To encourage Roman Urdu replies when the user writes Roman Urdu, we include an
# explicit style rule in the instruction (no ADK imports in API layer needed).
AGENT_INSTRUCTION = (
    AGENT_INSTRUCTION
    + "\n\nLanguage style:\n"
    + "- If user input is Roman Urdu / mixed, ask the ONE clarification question in Roman Urdu.\n"
    + "- Otherwise ask in English.\n"
)


def _emit_trace(thought: str, observation: str, action: str) -> None:
    print(f"[THOUGHT] {thought}")
    print(f"[OBSERVATION] {observation}")
    print(f"[ACTION] {action}")


def _parse_city_config(tool_context: ToolContext) -> Optional[CityConfig]:
    raw = tool_context.state.get("city_config")
    if isinstance(raw, CityConfig):
        return raw
    if isinstance(raw, dict):
        try:
            return CityConfig.model_validate(raw)
        except Exception:
            return None
    if isinstance(raw, str):
        try:
            return CityConfig.model_validate(json.loads(raw))
        except Exception:
            return None
    return None


def _user_text(tool_context: ToolContext, fallback: str = "") -> str:
    return str(
        tool_context.state.get("user_message")
        or tool_context.state.get("user_input")
        or fallback
    )


def normalize_roman_urdu(text: str, tool_context: ToolContext) -> dict[str, Any]:
    """Apply Roman Urdu keyword normalization and language detection."""
    original = text or ""
    working = original
    crisis_keywords_found: list[str] = []

    for phrase in _SORTED_RU_PHRASES:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(working):
            crisis_keywords_found.append(phrase)
            working = pattern.sub(_RU_KEYWORDS[phrase], working)

    words = _WORD_RE.findall(original.lower())
    ru_hits = sum(1 for w in words if w in _RU_WORDS)
    word_ratio = (ru_hits / len(words)) if words else 0.0

    has_urdu_script = bool(_URDU_SCRIPT_RE.search(original))
    if has_urdu_script:
        detected_language = "urdu_script"
        roman_urdu_confidence = 0.0
    elif word_ratio > 0.3:
        detected_language = "roman_urdu"
        roman_urdu_confidence = min(1.0, word_ratio)
    elif word_ratio > 0.0 and word_ratio <= 0.3:
        detected_language = "mixed"
        roman_urdu_confidence = word_ratio
    else:
        detected_language = "english"
        roman_urdu_confidence = 0.0

    result = {
        "normalized_text": working.strip(),
        "original_text": original,
        "detected_language": detected_language,
        "crisis_keywords_found": crisis_keywords_found,
        "roman_urdu_confidence": round(roman_urdu_confidence, 3),
    }
    tool_context.state["intake:last_normalize"] = result

    _emit_trace(
        f"Normalizing user text; {len(crisis_keywords_found)} crisis keyword(s) matched.",
        f"tool_use: normalize_roman_urdu -> language={detected_language}, "
        f"keywords={crisis_keywords_found}",
        f"Normalized preview: {working[:120]!r}",
    )
    return result


def check_city_config(tool_context: ToolContext) -> dict[str, Any]:
    """Read geographic scope already configured in session state."""
    cfg = _parse_city_config(tool_context)
    extracted = tool_context.state.get("intake:extracted_info") or {}
    if not isinstance(extracted, dict):
        extracted = {}

    city: Optional[str] = None
    zone: Optional[str] = None
    has_city = False

    if cfg and cfg.city.strip():
        city = cfg.city.strip()
        has_city = True
    elif extracted.get("city"):
        city = str(extracted["city"])
        has_city = bool(city)

    zone_val = extracted.get("zone")
    if zone_val:
        zone = str(zone_val)

    result = {"city": city, "zone": zone, "has_city": has_city}

    _emit_trace(
        "Checking whether city/zone are already known for location resolution.",
        f"tool_use: check_city_config -> {result}",
        "City context ready for vague-location handling.",
    )
    return result


def text_to_signal_event(
    text: str,
    city: str,
    zone: Optional[str],
    crisis_type: Optional[str],
    tool_context: ToolContext,
    confidence: float = 0.65,
    severity: Optional[str] = None,
    urgency_understated: bool = False,
    contradictory_report: bool = False,
    time_uncertain: bool = False,
) -> dict[str, Any]:
    """Create one SignalEvent and append it to temp:raw_signals."""
    state = tool_context.state
    cfg = _parse_city_config(tool_context)
    resolved_city = (city or "").strip() or (cfg.city if cfg else "") or "Unknown"

    norm = state.get("intake:last_normalize") or {}
    detected_language = norm.get("detected_language", "english")
    crisis_keywords = norm.get("crisis_keywords_found") or []

    if severity is None:
        severity = "high" if crisis_keywords else "medium"

    signal_id = f"USR-{uuid.uuid4().hex[:8]}"
    event = SignalEvent(
        signal_id=signal_id,
        source=SignalSource.SOCIAL,
        timestamp=datetime.now(timezone.utc),
        city=resolved_city,
        zone=zone.strip() if zone and zone.strip() else None,
        crisis_type=crisis_type,
        severity=severity,
        summary=(text or _user_text(tool_context))[:280],
        confidence=confidence,
        raw={
            "text": text or _user_text(tool_context),
            "source": "user_input",
            "intake_processed": True,
        },
        metadata={
            "agent_filter_decision": "INCLUDE",
            "language": detected_language,
            "intake_source": "chatbot",
            "URGENCY_UNDERSTATED": urgency_understated,
            "CONTRADICTORY_REPORT": contradictory_report,
            "TIME_UNCERTAIN": time_uncertain,
        },
    )

    raw_signals = state.setdefault("temp:raw_signals", [])
    if not isinstance(raw_signals, list):
        raw_signals = []
        state["temp:raw_signals"] = raw_signals
    raw_signals.append(event.model_dump(mode="json"))

    state["intake:resolved"] = True
    state["intake:clarification_question"] = None
    extracted = state.setdefault("intake:extracted_info", {})
    if not isinstance(extracted, dict):
        extracted = {}
    extracted.update(
        {
            "city": resolved_city,
            "zone": zone,
            "crisis_type": crisis_type,
            "severity_hint": severity,
        }
    )
    state["intake:extracted_info"] = extracted

    count = len(raw_signals)
    _emit_trace(
        f"Injecting SignalEvent {signal_id} "
        f"(crisis_type={crisis_type}, severity={severity}, confidence={confidence}).",
        f"tool_use: text_to_signal_event -> signal_id={signal_id}, "
        f"temp_raw_signals_count={count}",
        f"Appended signal to temp:raw_signals (total={count}).",
    )
    return {
        "signal_id": signal_id,
        "injected": True,
        "temp_raw_signals_count": count,
    }


async def _persist_intake_state(callback_context) -> None:
    """Sync IntakeResult LLM output and tool side-effects into session state."""
    state = callback_context.state
    raw = state.get("intake_result")

    if not raw:
        content = getattr(callback_context, "agent_response", None)
        if content:
            for part in getattr(content, "parts", []):
                text = getattr(part, "text", None)
                if text and "resolved" in text:
                    raw = text.strip().lstrip("```json").rstrip("```").strip()
                    break

    result: Optional[IntakeResult] = None
    if raw:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = None
        if isinstance(raw, dict):
            try:
                result = IntakeResult.model_validate(raw)
            except Exception:
                result = None

    signals_count = len(state.get("temp:raw_signals") or [])
    norm = state.get("intake:last_normalize") or {}

    if result:
        state["intake:resolved"] = result.resolved
        state["intake:clarification_question"] = result.clarification_question
        extracted = {
            "city": result.extracted_city,
            "zone": result.extracted_zone,
            "crisis_type": result.extracted_crisis_type,
            "severity_hint": (state.get("intake:extracted_info") or {}).get(
                "severity_hint"
            ),
        }
        state["intake:extracted_info"] = extracted
        if result.resolved:
            state["intake:clarification_question"] = None
    else:
        resolved = bool(state.get("intake:resolved", signals_count > 0))
        state["intake:resolved"] = resolved
        if not resolved and not state.get("intake:clarification_question"):
            state["intake:clarification_question"] = None

    _emit_trace(
        "Intake step complete; persisting pipeline gate flags.",
        f"intake:resolved={state.get('intake:resolved')}, "
        f"signals={signals_count}, language={norm.get('detected_language', 'english')}",
        "State keys intake:resolved / intake:clarification_question updated.",
    )


urdu_intake_agent = LlmAgent(
    name="UrduIntakeAgent",
    model=GEMINI_MODEL,
    description=(
        "First pipeline step: converts freeform user text (English, Roman Urdu, "
        "or mixed) into SignalEvents and manages a single clarifying question."
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[
        FunctionTool(normalize_roman_urdu),
        FunctionTool(check_city_config),
        FunctionTool(text_to_signal_event),
    ],
    output_schema=IntakeResult,
    output_key="intake_result",
    after_agent_callback=_persist_intake_state,
)
