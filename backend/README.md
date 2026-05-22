# CIRO — Crisis Intelligence & Response Orchestrator

> **Google Antigravity Hackathon 2026 | Challenge 3**  
> Multi-agent agentic system for real-time urban crisis detection, severity prediction, resource allocation, and coordinated stakeholder response across Islamabad and Karachi.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Google ADK (Antigravity) Integration](#3-google-adk-antigravity-integration)
4. [Agents Developed](#4-agents-developed)
5. [Data Stream Schemas](#5-data-stream-schemas)
6. [APIs Used](#6-apis-used)
7. [Datasets (CIRO Mock Data)](#7-datasets-ciro-mock-data)
8. [Flutter Mobile App](#8-flutter-mobile-app)
9. [Web Dashboard (Admin Panel — HITL)](#9-web-dashboard-admin-panel--hitl)
10. [Agentic Reasoning Trace — Live Example](#10-agentic-reasoning-trace--live-example)
11. [Baseline Comparison](#11-baseline-comparison)
12. [Robustness & Degraded Mode](#12-robustness--degraded-mode)
13. [Cost & Latency Analysis](#13-cost--latency-analysis)
14. [Scalability Discussion](#14-scalability-discussion)
15. [Privacy & Safety Note](#15-privacy--safety-note)
16. [Assumptions & Limitations](#16-assumptions--limitations)
17. [Future Work](#17-future-work)
18. [Setup & Running Locally](#18-setup--running-locally)
19. [Team](#19-team)

---

## 1. Project Overview

Cities face localized crises — urban flooding, heatwaves, road blockages, power outages, accidents — where signals exist scattered across social media, weather feeds, traffic sensors, and field reports, but response systems are fragmented and purely reactive.

**CIRO** is a fully agentic crisis management system that:

- Ingests **five concurrent signal sources** (social posts, weather mock data, traffic feeds, IoT sensors, field reports)
- Fuses and scores signals using a **credibility algorithm** with source reputation, geolocation confidence, mention velocity, and contradiction detection
- Classifies crises with **ranked hypotheses** and historical pattern grounding
- Predicts **severity level (1–5)**, affected population, spread risk, and peak impact ETA
- Allocates **constrained emergency resources** across simultaneous crises using a priority-weighted greedy solver
- Simulates **before/after action states** for traffic rerouting, dispatch, hospital prep, utility escalation, and shelter activation
- Generates **tailored stakeholder notifications** for 6 audience groups in English and Roman Urdu
- Provides a **Human-in-the-Loop (HITL) web dashboard** where dispatchers approve or reject AI-generated alerts before they reach citizens
- Handles **false alarms, conflicting signals, and API failures** with graceful fallback and retraction logic
- Delivers **live safe-path navigation** on the Flutter mobile app using Google Maps, showing blocked roads and clear alternate routes

All agent orchestration runs on **Google ADK (Antigravity)** using a hierarchy of `SequentialAgent`, `ParallelAgent`, `LlmAgent`, `LoopAgent`, and custom `BaseAgent` implementations powered by **Gemini 2.5 Flash**.

---

## 2. Architecture Overview

> **⚠️ Insert here:** Sections 2 and 3 (System Overview, Top-Level Architecture diagram, ADK Agent Hierarchy, Observability, and Session State Namespaces) from `CIROComplete_architecture.pdf` verbatim.

### High-Level System Layers

```
┌─────────────────────────────────────────────────────────────┐
│              Flutter Mobile App (Citizen-facing)             │
│   Scenario Map · Safe Path Navigation · Chat · Alerts UI    │
└──────────────────────────┬──────────────────────────────────┘
                           │ Google Maps SDK (live)
┌──────────────────────────▼──────────────────────────────────┐
│          React Web Dashboard (Admin / HITL Panel)            │
│   Hosted on Netlify · Firebase Realtime DB listener          │
└──────────────────────────┬──────────────────────────────────┘
                           │ Firebase Realtime Database
┌──────────────────────────▼──────────────────────────────────┐
│         FastAPI Gateway  (Docker · Hugging Face Spaces)      │
│  /api/chat · /api/stream/{sid} · /ws/{sid} · /api/incidents  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              Google ADK Agent Pipeline                       │
│                                                              │
│  CIRORoot (SequentialAgent)                                  │
│  ├── CIRORootTriage (LlmAgent)          ← PATH SELECTION    │
│  └── IncidentProcessingPipeline         ← FULL PIPELINE     │
│       ├── UrduIntakeAgent (LlmAgent)                         │
│       ├── SignalIngestionAgent (ParallelAgent)               │
│       │    ├── SocialSignalFetcher                           │
│       │    ├── WeatherSignalFetcher                          │
│       │    ├── TrafficSignalFetcher                          │
│       │    ├── SensorSignalFetcher                           │
│       │    └── FieldReportFetcher                            │
│       ├── SignalFusionAgent (LlmAgent)                       │
│       ├── CrisisClassifierAgent (LlmAgent)                   │
│       ├── SeverityPredictorAgent (LlmAgent)                  │
│       ├── ResourceAllocationWorkflow (SequentialAgent)       │
│       │    ├── GreedyAllocationSolver (BaseAgent)            │
│       │    └── AllocationTradeoffExplainer (LlmAgent)        │
│       └── NotificationAgent (SequentialAgent)                │
│            ├── VerificationLoop (LoopAgent, max 3)           │
│            └── NotificationCommunicator (LlmAgent)           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              Mock Data Layer + Live APIs                     │
│  DS-001 to DS-008 (ciro_datasets.json)                       │
│  Gemini 2.5 Flash (via Google AI Studio)                     │
│  Google Maps SDK (Flutter — live navigation)                 │
└─────────────────────────────────────────────────────────────┘
```

### Session State Namespaces

| Prefix | Purpose |
|--------|---------|
| `app:` | Persistent cross-session registry (active crises, degraded mode flag) |
| `temp:` | Pipeline-internal intermediate data (raw signals, clusters, severity records) |
| `intake:` | Urdu intake agent outputs (normalized text, resolved flag) |
| `final:` | Committed pipeline outputs (notifications, incident record) |

---

## 3. Google ADK (Antigravity) Integration

ADK is the **sole orchestration layer** for the agentic pipeline. No agent logic runs outside ADK agent boundaries.

### Triage Decision Logic

Every user message or signal payload enters `CIRORootTriage` (LlmAgent), which applies a strict priority-ordered decision:

```
1. temp:raw_signals present in session state?   → PATH A: PIPELINE
2. Operator command keywords detected?          → PATH B: COMMAND
3. Status query detected?                       → PATH C: QUERY
4. Uncertain / default                          → PATH A: PIPELINE (never suppress signals)
```

PATH B handles: `approve <id>`, `override severity <id> to <N>`, `stand down <id>`, `manual dispatch <resource> to <zone>`, `escalate`, `cancel alert`.

PATH C returns: `Active crises: N | Highest severity: X | Zones affected: [list]`.

### ADK Agent Types Used

| ADK Type | Used In | Reason |
|----------|---------|--------|
| `SequentialAgent` | CIRORoot, Pipeline, ResourceAllocation, Notification | Enforces strict execution order between dependent stages |
| `ParallelAgent` | SignalIngestionAgent | Five source fetchers run concurrently for low latency |
| `LlmAgent` | Triage, Intake, Fusion, Classifier, Severity, TradeoffExplainer, Notification | Reasoning, language understanding, hypothesis generation |
| `LoopAgent` | VerificationLoop | False-alarm verification with max 3 iteration guard |
| `BaseAgent` | GreedySolver, ActionPlanLoader | Deterministic logic with no LLM overhead |

### Traces & Observability

Every agent emits structured `[THOUGHT] → [OBSERVATION] → [ACTION]` traces conforming to the ADK reasoning trace format. Tool calls are prefixed with `tool_use:`, LLM reasoning steps with `call_llm:`, and all state mutations are logged explicitly. These traces are streamed live to the Flutter app and to the ADK web interface.

---

## 4. Agents Developed

> **⚠️ Insert here:** Section 4 (Individual Agent Specifications) from `CIROComplete_architecture.pdf` for the full per-agent specs including credibility algorithm detail, severity scale table, allocation algorithm pseudocode, notification audience matrix, and verification loop logic.

### Implemented Agents (8 of 8 built for this submission)

| # | Agent | ADK Type | Key Session State Output |
|---|-------|----------|--------------------------|
| 1 | CIRORootTriage | LlmAgent | `triage_decision`, `operator_response` |
| 2 | UrduIntakeAgent | LlmAgent | `intake:extracted_info`, `intake:resolved` |
| 3 | SignalIngestionAgent | ParallelAgent | `temp:raw_signals` (merged from 5 sources) |
| 4 | SignalFusionAgent | LlmAgent | `temp:fused_clusters` with credibility scores |
| 5 | CrisisClassifierAgent | LlmAgent | `temp:classified_clusters` with ranked hypotheses |
| 6 | SeverityPredictorAgent | LlmAgent | `temp:severity_records` (level 1–5, population p10–p90) |
| 7 | GreedyAllocationSolver + AllocationTradeoffExplainer | BaseAgent + LlmAgent | `temp:allocation_plan` with trade-off notes |
| 8 | NotificationAgent (VerificationLoop + Communicator) | SequentialAgent + LoopAgent + LlmAgent | `final:notifications` (6 audiences, bilingual) |

**Additionally**, the Admin Panel (Web Dashboard) uses two independent agents deployed as a FastAPI Docker container:
- **Intel & Sentiment Analyst Agent** — credibility scoring, SITREP generation
- **Tactical Commander Agent** — Crisis Action Plan with 3–5 tactical steps and priority tier

### Web Dashboard Agents (separate deployment)

These agents run independently of the ADK pipeline and power the HITL web dashboard:

| Agent | Task | Output |
|-------|------|--------|
| Intel & Sentiment Analyst | Parses crisis descriptions, calculates confidence score (0–100%), generates 2-sentence SITREP | Confidence metric, SITREP text |
| Tactical Commander | Formulates itemized action plan (3–5 steps), assigns priority tier (IMMEDIATE / FLASH) | Crisis Action Plan, response tier |

### Credibility Algorithm (Signal Fusion)

```
Final Credibility = 0.4 × source_reputation
                  + 0.3 × geolocation_confidence
                  + 0.2 × mention_velocity_score
                  + 0.1 × (1 - contradiction_factor)
```

| Signal Source | Reputation Score |
|---------------|-----------------|
| Official government / verified news account | 1.0 |
| Traffic sensor / weather station | 0.90–0.92 |
| Verified field report | 0.95 |
| Unverified field report | 0.65 |
| Verified social account | 0.75 |
| Anonymous social post | 0.30 |

### Severity Scale

| Level | Label | Trigger Criteria | Response Priority |
|-------|-------|-----------------|-------------------|
| 1 | Minimal | < 100 people | Monitor only |
| 2 | Low | 100–500 people | Dispatch team |
| 3 | Moderate | 500–2,000 people | Coordinate |
| 4 | High | 2,000–10,000 or critical infrastructure | Full mobilization |
| 5 | Critical | > 10,000 or cascading failure | Emergency declaration |

---

## 5. Data Stream Schemas

These schemas reflect the actual Pydantic models defined in `schemas/models.py`.

### SignalEvent (raw ingested signal)

```json
{
  "signal_id": "SOC-a3f2c1b8d9",
  "source": "social",
  "timestamp": "2025-05-15T14:15:00+00:00",
  "city": "Islamabad",
  "zone": "G-10",
  "latitude": 33.6938,
  "longitude": 73.0117,
  "crisis_type": "FLOODING",
  "severity": "high",
  "summary": "G-10 mein paani bhar gaya, gaariyan phans gayi hain!",
  "confidence": 0.85,
  "metadata": {
    "platform": "Twitter/X",
    "agent_filter_decision": "INCLUDE",
    "language": "roman_urdu"
  }
}
```

### SignalCluster (fused output from SignalFusionAgent)

```json
{
  "cluster_id": "CLU-4f8a2e1b",
  "city": "Islamabad",
  "zone": "G-10",
  "crisis_type": "FLOODING",
  "aggregate_credibility": 0.7812,
  "mention_velocity": 0.8400,
  "hypothesis_diversity_flag": false,
  "semantic_theme": "Urban flooding G-10 Markaz",
  "metadata": {
    "spatial_group_size": 5,
    "sources": ["social", "weather", "traffic"],
    "suspicious_flags": []
  }
}
```

### ClusterClassification (CrisisClassifierAgent output)

```json
{
  "cluster_id": "CLU-4f8a2e1b",
  "primary_classification": "urban_flood",
  "confidence": 0.73,
  "secondary_hypothesis": {
    "type": "water_main_burst",
    "confidence": 0.21
  },
  "conflicting_signals": [],
  "location": { "zone": "G-10", "lat": 33.6938, "lon": 73.0117 },
  "requires_verification": false
}
```

### AllocationPlan (ResourceAllocationWorkflow output)

```json
{
  "crises_count": 1,
  "unmet_demand": 1,
  "trade_off_summary": "1 crisis with RESOURCE_DEFICIT; 1 ambulance unmet.",
  "allocations": [{
    "cluster_id": "CLU-4f8a2e1b",
    "crisis_type": "urban_flood",
    "severity_level": 4,
    "priority_score": 8420.5,
    "assignments": [{
      "resource_type": "ambulances",
      "required_count": 3,
      "assigned_count": 2,
      "assigned_unit_ids": ["RSC-009", "RSC-010"],
      "avg_travel_time_mins": 7.3
    }],
    "resource_deficit": true,
    "deficit_types": ["ambulances"]
  }]
}
```

---

## 6. APIs Used

### Live APIs (Real, Used in Submission)

| API | Where Used | Purpose |
|-----|-----------|---------|
| **Google Gemini 2.5 Flash** | All LlmAgent calls (ADK pipeline + web dashboard agents) | LLM reasoning, Roman Urdu normalization, classification, severity prediction, notification generation |
| **Google Maps SDK (Flutter)** | Flutter mobile app | Live map rendering, blocked road overlay (red), safe alternate route display (green), hospital and resource markers, turn-by-turn safe path navigation during crises |

### Mock / Simulated Data Sources

All other data sources are simulated using the `ciro_datasets.json` mock bundle. No real weather API, traffic API, SMS gateway, or sensor network is called in this submission.

| Mock Source | Simulates | Dataset |
|-------------|-----------|---------|
| Social media posts | Twitter/X, Facebook, WhatsApp crisis signals in English and Roman Urdu | DS-001 (44 posts, 5 scenarios, 4 deliberate noise posts) |
| Weather snapshots | Pakistan Meteorological Department API telemetry | DS-002 (15 snapshots, T0/T1/T2 phases per scenario) |
| Traffic & road data | TomTom / NTRC congestion feed | DS-003 (25 roads with before/after congestion states) |
| Emergency resources | Rescue 1122, Edhi, KMC, IESCO, K-Electric, CDA resource pool | DS-004 (45 resources; 3 busy, 1 offline to test allocation constraints) |
| IoT sensors | MQTT hydro/heat/grid sensor grid | `mock_data/sensors.json` |
| Field reports | On-ground warden and citizen reports | `mock_data/field_reports.json` |
| Notification dispatch | Twilio SMS / Firebase FCM push | DS-007 reach counts used; no actual messages sent |

### Firebase Realtime Database

Used by the **web dashboard** to bridge the FastAPI backend and the React admin panel. The pipeline pushes approved alerts to the `/admin_alerts` node; the dashboard listens reactively and displays pending incidents for dispatcher review.

---

## 7. Datasets (CIRO Mock Data)

Eight cross-linked datasets covering five crisis scenarios across Islamabad and Karachi, each across three temporal phases (T0 before, T1 active peak, T2 after response). Every ID reference is verified to resolve cross-dataset — if a resource ID in DS-006 does not exist in DS-004, execution fails by design.

| ID | Dataset | Volume | Role |
|----|---------|--------|------|
| DS-001 | Social Media Posts | 44 posts | Citizen & official signals; 4 noise posts for filter testing (romantic poem, cricket result, sarcastic joke, vague city complaint) |
| DS-002 | Weather Snapshots | 15 snapshots | Climate-based detection; each snapshot has `agent_trigger` field (e.g., `ESCALATE_FLOOD_ALERT`) |
| DS-003 | Traffic & Roads | 25 roads | Routing and congestion logic with T0/T1/T2 phase snapshots and diversion routes |
| DS-004 | Emergency Resources | 45 resources | Dispatch and allocation pool; 3 busy ambulances + 1 offline cooling center to force constraint handling |
| DS-005 | City Zones | 25 zones | Geographic context, flood/heat/accident risk ratings, nearest hospital IDs |
| DS-006 | Response Actions | 25 actions | Mock API endpoints with request/response bodies; 2 actions deliberately `SIMULATED_PARTIAL` |
| DS-007 | Notification Registry | 13 entries | Per-zone SMS/WhatsApp/push/email reach counts and FM radio channels |
| DS-008 | Historical Events | 15 events (2021–2024) | `key_lesson_learned` fields written in agent-readable format for classification grounding |

**Five crisis scenarios:**

| Scenario | Type | City | Zone | Peak Condition |
|----------|------|------|------|---------------|
| SCN-001 | Urban Flooding | Islamabad | G-10 | 42.7 mm/hr rainfall, 100% road blockage |
| SCN-002 | Heatwave | Karachi | Saddar | 46°C, heat index 52°C, power grid stress |
| SCN-003 | Road Blockage (Dharna) | Islamabad | Faizabad | 100% congestion on 9th Avenue |
| SCN-004 | Road Accident | Islamabad | F-6 / Blue Area | Wet road, dusk, Margalla Road blocked |
| SCN-005 | Power Outage | Karachi | Korangi Industrial | 44°C + 2-hr power cut, 18,000+ affected |

---

## 8. Flutter Mobile App

The Flutter app is the **citizen-facing and operator-facing mobile interface** for CIRO.

### Features

**Scenario Dashboard**
Lists all five crisis scenarios. Selecting a scenario loads the Google Maps live view with:
- Blocked roads in **red**
- Safe alternate routes in **green** with turn-by-turn navigation
- Hospital, shelter, and resource markers
- Particularly useful for Karachi scenarios (SCN-002, SCN-005) where citizens need safe paths away from heatwave and power-outage zones

**Live Safe-Path Navigation**
During an active crisis, the app uses **Google Maps SDK** to compute and display safe routes from the user's location, avoiding blocked and high-risk roads. This is the primary live API integration in the mobile app.

**Chat Interface**
Accepts English, Roman Urdu, or mixed input (e.g., `"G-10 mai flooding"`, `"rasta band hai Faizabad pe"`). The `UrduIntakeAgent` normalizes input before the pipeline runs. Results stream back via Server-Sent Events (SSE).

**Agent Trace Viewer**
Real-time `[THOUGHT] → [OBSERVATION] → [ACTION]` trace display, fed from `/api/stream/{session_id}`. Judges can observe every agent decision live during the demo.

**Notification Dashboard**
Shows alerts generated for each of the 6 stakeholder audiences: General Public, Emergency Services, Hospitals, Utility Companies, Transport Authority, Media Command Center. Includes bilingual message previews (English + Roman Urdu for public) and delivery reach numbers from DS-007.

**Field Report Submission**
Warden or citizen field report form that posts to `/api/field-report`, injecting a `SignalEvent` directly into the pipeline.

### FastAPI ↔ Flutter Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Send message, trigger ADK pipeline |
| `/api/stream/{session_id}` | GET (SSE) | Stream agent traces and events live |
| `/ws/{session_id}` | WebSocket | Real-time incident registry push updates |
| `/api/incidents` | GET | List all active incidents |
| `/api/incidents/{id}` | GET | Full `FinalIncidentRecord` |
| `/api/field-report` | POST | Submit field report signal into pipeline |

---

## 9. Web Dashboard (Admin Panel — HITL)

The **CIRO Command Center Admin Panel** is a React web application that implements the Human-in-the-Loop control layer between the AI pipeline and the citizen alert network.

**Hosted on:** Netlify  
**Backend:** FastAPI (Docker container on Hugging Face Spaces)  
**Realtime bridge:** Firebase Realtime Database (`/admin_alerts` node)

### Role

Fully automated AI dispatches can cause coordination errors or false alarms at scale. The Admin Panel sits between the AI pipeline and the public notification network, ensuring experienced safety dispatchers review AI threat assessments before any public emergency alarm is triggered.

### Operational Workflow

```
1. AI Pipeline runs → crisis alert generated with confidence score and action plan
2. Alert pushed to Firebase Realtime Database (/admin_alerts)
3. Admin Dashboard (reactive DB listener) displays alert in Pending Actions queue
4. Dispatcher decision:
   ├── APPROVE → alert status set to "approved"
   │             Flutter mobile apps alert citizens immediately
   └── REJECT  → status set to "rejected"
                 Archived in Audit Trail table as confirmed false alarm
```

### Dashboard Panels

**Pending Actions Queue** — incoming alerts with confidence score (0–100%), AI-generated SITREP, and tactical action plan. Dispatcher reviews and approves or rejects.

**Command Tactical Radar** — live city map showing incident GPS coordinates, active threat zones, and fleet readiness overlay.

**Active Incident Table** — approved incidents with status, severity tier, and resource deployment log.

**Audit Trail** — historical log of all approved and rejected alerts for post-incident review.

### Web Dashboard Agents

Two agents run as a FastAPI Docker container powering the dashboard's AI layer:

**Agent 1 — Intel & Sentiment Analyst**
- Parses raw crisis descriptions from citizen reports or sensor suites
- Calculates a Confidence Score (0–100%) based on source consistency and data features
- Generates a 2-sentence SITREP optimized for high-pressure dispatcher reading

**Agent 2 — Tactical Commander**
- Analyzes the Intel Agent's structured output
- Determines assets required (rescue boats, police vehicles, firefighting teams, etc.)
- Compiles an itemized Crisis Action Plan (3–5 tactical steps)
- Assigns a response priority tier: `IMMEDIATE` or `FLASH`

---

## 10. Agentic Reasoning Trace — Live Example

The following is a real session from the ADK web interface.

**Input:** `"Flooding alert in G-10, rasta band hai"`

### Step 1 — Triage (CIRORootTriage)

```
[THOUGHT] The user is reporting a flooding alert and a blocked road, which are
signals for the incident processing pipeline. I will confirm the pipeline will
run and fetch live weather for Islamabad as it is relevant to the flood.

[OBSERVATION] call_llm: triage reasoning — path=PIPELINE

[ACTION] Registry updates applied by system.
```

**State committed:**
```json
{
  "triage_decision": "PIPELINE",
  "triage_reasoning": "pipeline keywords or scenario token in: Flooding alert in G-10, rasta band hai",
  "operator_response": "Pipeline start ho gaya (incident INCIDENT-EF1169). Signals process ho rahe hain."
}
```

### Step 2 — Multilingual Intake (UrduIntakeAgent)

```
[THOUGHT] Normalize the Roman Urdu text and detect language.

[OBSERVATION] tool_use: normalize_roman_urdu →
  normalized_text: "Flooding alert in G-10, road blocked hai"
  detected_language: "mixed"
  crisis_keywords_found: ["rasta band"]
  roman_urdu_confidence: 0.25

[THOUGHT] City not in session state. CIRORootTriage fetched weather for
"Islamabad", implying city context. G-10 is a zone within Islamabad.
Policy: "If city known, never ask again." Inferring Islamabad.
Two crisis types detected: flood + road blocked. Creating two SignalEvents.

[OBSERVATION] tool_use: check_city_config → city not in session; inferring
from triage context (Islamabad).

[ACTION] set_model_response called.
```

**Final intake output:**
```json
{
  "resolved": true,
  "extracted_city": "Islamabad",
  "extracted_zone": "G-10",
  "extracted_crisis_type": "flood, road blocked",
  "signals_injected": 2,
  "detected_language": "mixed"
}
```

**Full session state after intake:**
```
triage_decision: "PIPELINE"
intake:resolved: true
intake:extracted_info:
  city: "Islamabad"
  zone: "G-10"
  crisis_type: "flood, road blocked"
  severity_hint: "high"
app:active_crisis_registry:
  INCIDENT-784735:
    status: "PROCESSING"
    city: "Islamabad"
    phase: "T1_during"
    severity_level: 1
    notifications_sent: 0
```

### Step 3 onward — Pipeline

After intake: `SignalIngestionAgent` (5 parallel fetchers, ~730ms) → `SignalFusionAgent` (credibility scoring + clustering) → `CrisisClassifierAgent` (historical lookup + ranked hypotheses) → `SeverityPredictorAgent` (population risk + spread score) → `ResourceAllocationWorkflow` (greedy solver + trade-off explainer) → `NotificationAgent` (VerificationLoop + 6-audience bilingual messages).

### Execution Latency Breakdown

```
[PLATFORM] CIRORoot ................................................ [36.51s]
   ├── [ORCHESTRATOR] CIRORootTriage .............................. [15.55s]
   │      ├── [LLM_CALL] gemini-2.5-flash (Path Selection) ........ [ 8.93s]
   │      └── [TOOL_EXEC] fetch_live_weather ...................... [84.23ms]
   └── [PIPELINE] IncidentProcessingPipeline ...................... [20.93s]
          └── [AGENT] UrduIntakeAgent ............................. [20.18s]
                 ├── [LLM_CALL] gemini-2.5-flash (Normalize) ...... [ 6.84s]
                 ├── [TOOL_EXEC] normalize_roman_urdu ............. [62.18ms]
                 ├── [TOOL_EXEC] check_city_config ................ [ 6.97ms]
                 ├── [AGENT_CALL] SignalIngestionAgent ............. [729.48ms]
                 │      ├── SocialSignalFetcher ................... [447.44ms]
                 │      ├── WeatherSignalFetcher .................. [61.94ms]
                 │      ├── TrafficSignalFetcher .................. [63.14ms]
                 │      ├── SensorSignalFetcher ................... [29.92ms]
                 │      └── FieldReportFetcher .................... [33.91ms]
                 └── [TOOL_EXEC] set_model_response ............... [ 2.73ms]
```

---

## 11. Baseline Comparison

| Capability | Rule-Based Baseline | CIRO (Agentic) |
|-----------|--------------------|--------------------|
| Language handling | English keywords only | Roman Urdu, English, mixed code-switched input via LLM normalization |
| Noise filtering | None | 4 noise posts in DS-001 (romantic rain poem, cricket result, sarcastic flood joke, vague city complaint) correctly discarded |
| Conflicting signals | Accept first | Detects contradiction, scores both hypotheses, flags `requires_verification`, triggers VerificationLoop |
| Multi-crisis | Single queue | Simultaneous crises with shared resource pool; explicit deficit notes when ambulances are short |
| Resource allocation | First-come-first-served | Priority-weighted greedy (severity × population / distance), travel-time constrained |
| Notifications | One generic alert | 6 tailored audience messages; English + Roman Urdu for public; technical for dispatch; medical briefing for hospitals |
| False alarm handling | No correction | LoopAgent (max 3 iterations) with retraction message generation |
| Human oversight | None | Full HITL Admin Panel — dispatchers approve/reject before citizen alerts fire |
| API failure | System crash | Per-source STALE fallback, cached last-good batch, degraded mode with human escalation queue |

---

## 12. Robustness & Degraded Mode

**Stale data fallback:** Each of the five signal fetchers wraps its tool call in try/except. On failure, `_apply_fallback()` returns the last cached batch tagged `source_status: "STALE"`. Fusion agent down-weights stale signals automatically.

**False alarm / low-confidence:** `VerificationLoop` (LoopAgent, max 3 iterations) checks `requires_verification` and `aggregate_credibility < 0.45`. On failure after 3 iterations, `temp:retraction_required` is set and retraction messages are generated for all alerted audiences.

**Degraded mode:** If triage fails or signals cannot be routed after 2 retries, `_enter_degraded_mode()` suspends all automatic dispatch, queues signals in `app:pending_human_review`, and notifies the operator.

**Resource constraints:** DS-004 includes 3 busy ambulances, 1 deployed rescue team, and 1 offline cooling center. The greedy allocator skips unavailable units and sets `RESOURCE_DEFICIT` with `deficit_types` list.

**Partial action failures:** Two actions in DS-006 (`ACT-008`, `ACT-024`) are deliberately `SIMULATED_PARTIAL`, demonstrating graceful execution despite tool-level failures.

**HITL safety net:** Even if the full ADK pipeline runs successfully, no citizen alert fires unless a dispatcher approves it in the Admin Panel.

---

## 13. Cost & Latency Analysis

### Per Pipeline Run Estimates

| Component | Latency | Notes |
|-----------|---------|-------|
| Triage LLM call | ~8–15s | Path selection |
| Signal ingestion (parallel, 5 fetchers) | ~730ms | Concurrent execution |
| Signal fusion LLM | ~6–10s | Credibility scoring + semantic grouping |
| Crisis classification LLM | ~5–8s | Per cluster |
| Severity prediction LLM | ~4–7s | Per cluster |
| Resource allocation (greedy solver) | < 100ms | Deterministic BaseAgent, no LLM |
| Trade-off explainer LLM | ~4–6s | Only fires on deficit crises |
| Notification (verification + generation) | ~8–12s | LoopAgent + 6-audience LLM |
| **End-to-end (observed)** | **~36s** | Single scenario, Gemini 2.5 Flash |

### Cost Estimate

**Gemini 2.5 Flash**
- ~$0.075 / 1M input tokens, ~$0.30 / 1M output tokens
- Estimated per pipeline run: 8,000–15,000 input tokens, 2,000–4,000 output tokens
- **Cost per run: < $0.005 USD**

**Google Maps SDK (Flutter)**
- Map loads: ~$0.007 per 1,000 map tile loads (Dynamic Maps)
- Directions API (safe path): ~$0.005 per route request
- At 100 active users during a crisis event: **~$1–2 per incident for Maps**

**Total estimated operational cost at 1,000 incident detections/day:** < $10/day (LLM + Maps combined).

---

## 14. Scalability Discussion

**Current state:** `InMemorySessionService` — suitable for demo. Resets on server restart.

**Production path:**
- Replace `InMemorySessionService` with **Firestore** (single swap in `services.py`)
- `ParallelAgent` fetchers scale horizontally — each fetcher is stateless
- FastAPI runs behind **Cloud Run** with autoscaling
- Greedy allocator is O(crises × resource_types × units) — acceptable for real-time urban scale
- Gemini 2.5 Flash supports high QPS with no cold-start penalty

**Multi-city extension:** `city_config` (bounding box + city) is already parameterized per session. New cities require only adding DS-005 zone and DS-004 resource entries.

---

## 15. Privacy & Safety Note

- All social media data is **mock/synthetic** — no real citizen identifiers
- No actual SMS, push notifications, or WhatsApp messages are sent
- Field reports are processed in-memory and discarded on session end
- `GOOGLE_API_KEY` (Gemini) and Google Maps SDK key are the only real credentials
- Production deployment would require PDPA compliance, end-to-end encryption on field reports, and data minimization at the ingestion layer

---

## 16. Assumptions & Limitations

- Travel time uses haversine distance at 40 km/h — not live Maps Directions API ETAs. The code comment in `resource_allocator.py` documents exactly where to plug in the Maps API
- Session state is in-memory; pipeline state is lost on server restart
- Roman Urdu normalization relies on Gemini 2.5 Flash; no dedicated NLP model used
- The five scenarios cover Islamabad and Karachi only
- Concurrent multi-session load has not been stress-tested beyond demo scenarios
- Action simulation (ActionSimulationAgent) was designed but not wired into the final submission pipeline — it is present in the codebase for completeness

---

## 17. Future Work

The following agents and capabilities are designed in the architecture but not implemented in this submission:

| Component | Description |
|-----------|-------------|
| ActionSimulationAgent (full wiring) | Before/after state simulation for all 6 action types (traffic, dispatch, hospital, utility, evacuation, shelter) — code exists, not in pipeline |
| Live OpenWeatherMap integration | `fetch_live_weather()` in `agent.py` is fully implemented with DS-002 fallback; requires a live API key to activate |
| Live traffic feed | Replace DS-003 mock with TomTom or Google Maps Traffic Layer API |
| Google Maps Directions ETA | Replace haversine travel time in `resource_allocator.py` with live Directions API for accurate dispatch ETAs |
| Real SMS / FCM dispatch | Replace mock `send_notification()` with Twilio (SMS) and Firebase Cloud Messaging (push) |
| MQTT sensor integration | Replace `sensors.json` with a live MQTT broker for real IoT sensor feeds |
| Multi-city expansion | Lahore, Rawalpindi zone and resource datasets |
| Dedicated Roman Urdu NLP model | Replace LLM-based normalization with a fine-tuned multilingual model for lower latency |

---

## 18. Setup & Running Locally

### Prerequisites

- Python 3.11+
- Flutter 3.x
- `GOOGLE_API_KEY` (Gemini via Google AI Studio or Vertex AI)
- Google Maps SDK key (for Flutter app)

### Backend (FastAPI + ADK Pipeline)

```bash
git clone <repo-url>
cd ciro

pip install -r requirements.txt

cp .env.example .env
# Set GOOGLE_API_KEY in .env

uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### ADK Web Interface (for trace visualization)

```bash
adk web agents/agent.py
```

### Flutter App

```bash
cd flutter_app
flutter pub get
# Set baseUrl to http://localhost:8000 in app config
# Set Google Maps API key in AndroidManifest.xml / AppDelegate.swift
flutter run
```

### Trigger a Scenario via API

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "run scenario SCN-001",
    "session_id": "demo-001",
    "city": "Islamabad",
    "scenario_id": "SCN-001"
  }'
```

Or type in the Flutter chat: `"G-10 mein flooding hai, rasta band hai"`

### Web Dashboard

The React admin panel is hosted on Netlify and connects to the FastAPI Docker container on Hugging Face Spaces. No local setup required to view the hosted version — see the link in submission.

---

## 19. Team

**Project:** Crisis Intelligence & Response Orchestrator (CIRO)  
**Hackathon:** Google Antigravity 2026 | Challenge 3

| Member | Role | Primary Deliverables |
|--------|------|---------------------|
| Lead AI Architect & Systems Engineer | Core ADK pipeline, agent orchestration, signal fusion, credibility algorithm, resource allocator, severity predictor, FastAPI gateway, SSE/WebSocket streaming | `agent.py`, `runner.py`, `signal_fusion.py`, `crisis_classifier.py`, `severity_predictor.py`, `resource_allocator.py`, `notification_agent.py`, `main.py` |
| Flutter Developer | Mobile app, Google Maps integration, scenario dashboard, safe-path navigation, chat UI, trace viewer, notifications panel | Flutter app codebase |
| Data Engineer & Agent Support | Mock dataset design (DS-001 to DS-008), `ciro_datasets.json`, sensor and field report mock data, signal ingestion agent | `signal_ingestion.py`, `ciro_datasets.json`, `sensors.json`, `field_reports.json` |
| Integration Engineer | React web admin panel, Firebase integration, web dashboard agents (Intel Analyst + Tactical Commander), Hugging Face Spaces deployment | React dashboard, web agent code, Firebase config |

---

*Built with Google ADK (Antigravity) · Gemini 2.5 Flash · Google Maps SDK · FastAPI · Flutter · Firebase · React · Python 3.11*
