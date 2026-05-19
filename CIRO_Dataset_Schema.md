# CIRO — Crisis Intelligence & Response Orchestrator
## Complete Dataset Schema Reference (All 8 Datasets)
> AI Seekho Hackathon | Senior Data Engineering Spec | 5 Scenarios × 3 Time Phases

---

## Schema Conventions

| Symbol | Meaning |
|--------|---------|
| `[T0]` | Present in T0_before phase |
| `[T1]` | Present in T1_during phase |
| `[T2]` | Present in T2_after_response phase |
| `*` | Required in all applicable phases |
| `~` | Optional / conditionally present |

**Scenario IDs:** SCN-001 (Flooding) · SCN-002 (Heatwave) · SCN-003 (Road Blockage) · SCN-004 (Accident) · SCN-005 (Infrastructure)

**Cities covered:** Islamabad · Karachi

---

---

## DATASET 1 — Social Media Posts

**Purpose:** Raw noisy signals fed to Signal Ingestion Agent. Tests NLP filtering, Roman Urdu parsing, crisis signal extraction.

**Time Phases:** T0_before · T1_during · T2_after_response

**Target Volume:** 44 posts total — ~8–9 per scenario across phases + 4 noise-only posts distributed

**Top-level structure:**
```json
{
  "dataset_id": "DS-001",
  "dataset_name": "social_media_posts",
  "version": "1.0.0",
  "total_posts": 44,
  "scenarios_covered": ["SCN-001","SCN-002","SCN-003","SCN-004","SCN-005"],
  "posts": { "T0_before": [...], "T1_during": [...], "T2_after_response": [...] }
}
```

### Column Definitions

| Column | Type | Required | Phases | Description | Example |
|--------|------|----------|--------|-------------|---------|
| `post_id` | string | * | T0,T1,T2 | Unique post identifier | `"SM-001"` |
| `scenario_id` | string | * | T0,T1,T2 | Links post to a scenario | `"SCN-001"` |
| `timestamp` | ISO 8601 string | * | T0,T1,T2 | Post creation time | `"2025-05-15T14:05:00"` |
| `platform` | string | * | T0,T1,T2 | Source platform | `"Twitter/X"`, `"Facebook"`, `"WhatsApp"` |
| `language` | string | * | T0,T1,T2 | Detected language tag | `"roman_urdu"`, `"english"`, `"mixed"` |
| `user` | string | * | T0,T1,T2 | Handle or page name | `"@ali_g10"`, `"PIMS Hospital"` |
| `user_type` | string | * | T0,T1,T2 | Source credibility tier | `"citizen"`, `"official"`, `"news_org"`, `"ngo"` |
| `text` | string | * | T0,T1,T2 | Raw post content | `"G-10 mein paani bhar gaya!"` |
| `location_mentioned` | string | * | T0,T1,T2 | Location extracted from text | `"G-10"`, `"Korangi"` |
| `location_tag` | string | ~ | T0,T1,T2 | GPS-tagged location on platform | `"G-10 Markaz, Islamabad"` |
| `city` | string | * | T0,T1,T2 | Resolved city | `"Islamabad"`, `"Karachi"` |
| `crisis_type_hint` | string | * | T0,T1,T2 | Agent-labeled crisis category | `"FLOODING"`, `"HEATWAVE"`, `"ACCIDENT"`, `"NOISE"` |
| `sentiment` | string | * | T0,T1,T2 | Emotional tone | `"urgent"`, `"panic"`, `"informational"`, `"neutral"`, `"positive"` |
| `crisis_signal` | boolean | * | T0,T1,T2 | Is this a genuine crisis signal? | `true`, `false` |
| `noise_level` | string | * | T0,T1,T2 | Signal quality rating | `"low"`, `"medium"`, `"high"` |
| `likes` | integer or null | * | T0,T1,T2 | Engagement count (null for WhatsApp) | `189`, `null` |
| `shares` | integer or null | ~ | T1,T2 | Retweet/share count | `45`, `null` |
| `verified_source` | boolean | * | T0,T1,T2 | Is the account verified/official? | `true`, `false` |
| `media_attached` | boolean | ~ | T1 | Photo/video attached? | `true`, `false` |
| `keywords_extracted` | array of strings | * | T0,T1,T2 | NLP-extracted crisis keywords | `["paani", "flood", "stranded"]` |
| `agent_filter_decision` | string | * | T0,T1,T2 | What ingestion agent does with post | `"INCLUDE"`, `"DISCARD_NOISE"`, `"FLAG_UNVERIFIED"` |
| `phase` | string | * | T0,T1,T2 | Time phase tag | `"T0_before"`, `"T1_during"`, `"T2_after_response"` |

### Phase-Specific Notes

**T0_before** — Early warning only. Low engagement. `crisis_signal: false` mostly. Keywords vague ("might rain", "getting hot"). Used as baseline.

**T1_during** — Peak signal burst. High engagement. Multiple confirming posts within short time window (15–30 min). Mix of citizen + official. Contains 4 noise posts across all scenarios.

**T2_after_response** — Resolution signals. "Rescue team arrived", "alternate route", "cooling center open". `crisis_signal: false`. Used for outcome visualization.

### Noise Post Rules (4 required)
Posts that `crisis_signal: false` AND `crisis_type_hint: "NOISE"` AND `agent_filter_decision: "DISCARD_NOISE"`:
- One romantic/irrelevant comment about rain
- One unrelated event (concert, match result)
- One vague complaint with no location
- One sarcastic/joke post

---

---

## DATASET 2 — Weather Data

**Purpose:** Corroborate social signals. The escalating numbers give the Detection Agent quantitative justification for confidence scores.

**Time Phases:** T0_before · T1_during · T2_after_response

**Target Volume:** 15 snapshots — 3 per scenario (one per phase)

**Top-level structure:**
```json
{
  "dataset_id": "DS-002",
  "dataset_name": "weather_snapshots",
  "version": "1.0.0",
  "source": "Mock Pakistan Meteorological Department API",
  "total_snapshots": 15,
  "snapshots": { "SCN-001": { "T0_before": {...}, "T1_during": {...}, "T2_after_response": {...} }, ... }
}
```

### Column Definitions

| Column | Type | Required | Phases | Description | Example |
|--------|------|----------|--------|-------------|---------|
| `snapshot_id` | string | * | T0,T1,T2 | Unique snapshot ID | `"WX-001-T0"` |
| `scenario_id` | string | * | T0,T1,T2 | Linked scenario | `"SCN-001"` |
| `phase` | string | * | T0,T1,T2 | Time phase | `"T0_before"` |
| `timestamp` | ISO 8601 | * | T0,T1,T2 | Reading time | `"2025-05-15T13:00:00"` |
| `city` | string | * | T0,T1,T2 | City of measurement | `"Islamabad"` |
| `station` | string | * | T0,T1,T2 | Weather station name | `"ISB-North Station"` |
| `temperature_c` | float | * | T0,T1,T2 | Air temperature in Celsius | `29.0`, `44.2` |
| `feels_like_c` | float | * | T0,T1,T2 | Apparent / heat index temp | `31.5`, `51.0` |
| `humidity_percent` | integer | * | T0,T1,T2 | Relative humidity | `72`, `95` |
| `rainfall_mm_per_hour` | float | * | T0,T1,T2 | Precipitation rate | `0.0`, `42.7` |
| `rainfall_mm_last_3hr` | float | ~ | T1,T2 | Cumulative recent rainfall | `0.0`, `98.4` |
| `wind_speed_kmh` | float | * | T0,T1,T2 | Wind speed | `18.0`, `34.0` |
| `wind_direction` | string | ~ | T1 | Cardinal direction | `"NE"`, `"SW"` |
| `cloud_cover_percent` | integer | * | T0,T1,T2 | Cloud coverage | `85`, `100` |
| `visibility_km` | float | * | T0,T1,T2 | Horizontal visibility | `10.0`, `4.2` |
| `uv_index` | integer | ~ | T1 (heatwave) | UV intensity (0–11+) | `3`, `11` |
| `heat_index_c` | float | ~ | T1,T2 (heatwave/infra) | Feels-like in heat context | `38.5`, `51.0` |
| `road_condition` | string | ~ | T1 (accident/flood) | Surface state | `"DRY"`, `"WET"`, `"FLOODED"` |
| `alert_type` | string | * | T0,T1,T2 | Meteorological alert code | `"FLASH_FLOOD_WARNING"`, `"EXTREME_HEAT_EMERGENCY"`, `"CLEAR"` |
| `alert_level` | string | * | T0,T1,T2 | Severity tier | `"NONE"`, `"LOW"`, `"MODERATE"`, `"HIGH"`, `"CRITICAL"` |
| `flood_risk_score` | float 0–1 | ~ | T0,T1,T2 (flooding) | Model-computed flood probability | `0.12`, `0.91` |
| `power_grid_stress` | boolean | ~ | T1 (heatwave/infra) | Grid under stress from heat | `true`, `false` |
| `forecast_next_2hr` | string | * | T0,T1 | Short forecast description | `"Heavy rain expected"` |
| `forecast_next_4hr` | string | ~ | T1 | Longer forecast | `"Temperatures staying above 43°C"` |
| `agent_trigger` | string | * | T0,T1,T2 | What this reading triggers in agent | `"ESCALATE_FLOOD_ALERT"`, `"NO_ACTION"`, `"STAND_DOWN"` |
| `threshold_breached` | boolean | * | T0,T1,T2 | Has a danger threshold been crossed? | `true`, `false` |
| `threshold_detail` | string | ~ | T1 | Which threshold and by how much | `"Rainfall 42.7mm/hr exceeds 25mm/hr danger limit"` |

### Escalation Pattern (enforced per scenario)

| Scenario | T0 Alert Level | T1 Alert Level | T2 Alert Level | Key Threshold |
|----------|---------------|---------------|---------------|---------------|
| SCN-001 Flooding | LOW | HIGH/CRITICAL | MODERATE | rainfall > 25 mm/hr |
| SCN-002 Heatwave | LOW | CRITICAL | HIGH | temp > 42°C |
| SCN-003 Road Blockage | NONE | NONE | NONE | weather not a factor |
| SCN-004 Accident | NONE | NONE | NONE | road_condition WET |
| SCN-005 Infrastructure | MODERATE | HIGH | MODERATE | heat amplifies outage |

---

---

## DATASET 3 — Traffic & Roads

**Purpose:** Confirm crisis impact on infrastructure; enable rerouting simulation; provide before/after delta for outcome screen.

**Time Phases:** T0_before (baseline) · T1_during (crisis active) · T2_after_response (post-action)

**Target Volume:** 25 road records. Each record carries T0/T1/T2 state embedded. 10 Karachi roads · 8 Islamabad roads · 7 dedicated alternate routes.

**Top-level structure:**
```json
{
  "dataset_id": "DS-003",
  "dataset_name": "traffic_roads",
  "version": "1.0.0",
  "total_roads": 25,
  "roads": [ {...}, {...} ]
}
```

### Column Definitions — Core Road Identity

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `road_id` | string | * | Unique road ID | `"RD-001"` |
| `road_name` | string | * | Official road name | `"Kashmir Highway"`, `"Korangi Road"` |
| `city` | string | * | City | `"Islamabad"`, `"Karachi"` |
| `zone` | string | * | Area/sector zone | `"G-10"`, `"Korangi Industrial"` |
| `road_type` | string | * | Classification | `"highway"`, `"arterial"`, `"secondary"`, `"service_road"` |
| `lat_start` | float | * | Start coord latitude | `33.6938` |
| `lng_start` | float | * | Start coord longitude | `73.0117` |
| `lat_end` | float | * | End coord latitude | `33.7100` |
| `lng_end` | float | * | End coord longitude | `73.0250` |
| `length_km` | float | * | Road segment length | `3.2` |
| `lanes` | integer | * | Number of lanes | `4` |
| `scenario_id` | string | * | Linked scenario | `"SCN-001"` |
| `is_alternate_route` | boolean | * | Is this a diversion route? | `true`, `false` |
| `alternate_for_road_id` | string | ~ | Road it substitutes when blocked | `"RD-001"` |
| `alternate_route_via` | string | ~ | Descriptive path for alternate | `"Margalla Road via Golra Mor"` |

### Column Definitions — T0_before State

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `T0.timestamp` | ISO 8601 | * | Baseline reading time | `"2025-05-15T13:00:00"` |
| `T0.normal_speed_kmh` | integer | * | Free-flow speed | `50` |
| `T0.current_speed_kmh` | integer | * | Actual speed at T0 | `45` |
| `T0.congestion_percent` | integer | * | 0–100% congestion level | `15` |
| `T0.status` | string | * | Traffic state | `"FREE"`, `"MODERATE"`, `"SLOW"` |
| `T0.vehicles_stranded` | integer | * | Stranded vehicle count | `0` |
| `T0.incident_type` | string | ~ | Any incident at T0 | `null`, `"MINOR_ACCIDENT"` |

### Column Definitions — T1_during State

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `T1.timestamp` | ISO 8601 | * | Crisis-active reading time | `"2025-05-15T14:15:00"` |
| `T1.current_speed_kmh` | integer | * | Speed during crisis | `0`, `4` |
| `T1.congestion_percent` | integer | * | Congestion at peak crisis | `100`, `85` |
| `T1.status` | string | * | Traffic state | `"BLOCKED"`, `"SEVERE"` |
| `T1.vehicles_stranded` | integer | * | Vehicles stuck | `43`, `85` |
| `T1.blockage_duration_mins` | integer | ~ | How long blocked | `30`, `65` |
| `T1.incident_type` | string | ~ | Cause of blockage | `"FLOODING"`, `"PROTEST"`, `"ACCIDENT"` |
| `T1.emergency_lane_open` | boolean | * | Emergency vehicle path? | `true`, `false` |
| `T1.signal_status` | string | ~ | Traffic signal state | `"OPERATIONAL"`, `"OFFLINE"`, `"MANUAL"` |

### Column Definitions — T2_after_response State

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `T2.timestamp` | ISO 8601 | * | Post-response reading time | `"2025-05-15T15:25:00"` |
| `T2.current_speed_kmh` | integer | * | Speed after intervention | `20`, `48` |
| `T2.congestion_percent` | integer | * | Congestion after intervention | `45`, `10` |
| `T2.status` | string | * | Traffic state | `"MODERATE"`, `"FREE"` |
| `T2.vehicles_stranded` | integer | * | Remaining stranded vehicles | `8`, `0` |
| `T2.diversion_active` | boolean | * | Is alternate route being used? | `true`, `false` |
| `T2.diversion_via` | string | ~ | Active diversion name | `"Margalla Road"` |
| `T2.congestion_reduction_percent` | float | * | Delta improvement | `74.0`, `55.0` |
| `T2.wardens_deployed` | integer | ~ | Police/wardens on ground | `4`, `0` |

---

---

## DATASET 4 — Emergency Resources

**Purpose:** Response Planning Agent queries this inventory to select and dispatch optimal resources per crisis type, availability, and proximity.

**Time Phases:** Single snapshot — status is mutable (available → deployed)

**Target Volume:** 45 resources across all types and both cities

**Top-level structure:**
```json
{
  "dataset_id": "DS-004",
  "dataset_name": "emergency_resources",
  "version": "1.0.0",
  "total_resources": 45,
  "last_updated": "2025-05-15T12:00:00",
  "resources": [ {...}, {...} ]
}
```

### Column Definitions

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `resource_id` | string | * | Unique ID | `"RSC-001"` |
| `resource_type` | string | * | Category | `"ambulance"`, `"rescue_team"`, `"fire_brigade"`, `"hospital"`, `"cooling_center"`, `"police_unit"`, `"traffic_warden"`, `"water_tanker"`, `"utility_repair_team"` |
| `name` | string | * | Resource name | `"Rescue 1122 Unit 4"`, `"PIMS Hospital"` |
| `callsign` | string | ~ | Short radio ID | `"Rescue-4"`, `"Ambulance-7"` |
| `zone` | string | * | Deployed zone/sector | `"G-10"`, `"Korangi"` |
| `city` | string | * | City | `"Islamabad"`, `"Karachi"` |
| `lat` | float | * | GPS latitude | `33.6938` |
| `lng` | float | * | GPS longitude | `73.0117` |
| `address` | string | * | Street address | `"G-10/2, Main Markaz, Islamabad"` |
| `status` | string | * | Current availability | `"available"`, `"busy"`, `"deployed"`, `"offline"` |
| `status_reason` | string | ~ | Why busy/offline | `"Responding to SCN-003"`, `"Maintenance"` |
| `response_time_mins` | integer | * | ETA to typical scene | `8`, `15`, `22` |
| `suitable_for` | array of strings | * | Crisis types this resource serves | `["FLOODING","ROAD_ACCIDENT"]` |
| `capacity` | integer | * | How many it can serve at once | `2` (ambulance patients), `50` (cooling center) |
| `capacity_unit` | string | * | Unit of capacity measure | `"patients"`, `"persons"`, `"beds"`, `"vehicles"` |
| `personnel_count` | integer | ~ | Staff headcount | `4`, `12` |
| `vehicles_count` | integer | ~ | Fleet size (for units) | `2`, `1` |
| `equipment` | array of strings | ~ | Key equipment list | `["stretcher","defibrillator","oxygen"]` |
| `contact_number` | string | * | Mock dispatch number | `"1122"`, `"115"`, `"021-99203000"` |
| `organization` | string | * | Owning organization | `"Rescue 1122"`, `"EDHI Foundation"`, `"CDA"` |
| `current_mission` | string | ~ | Active assignment if busy | `"Flood rescue G-10 Markaz"` |
| `fuel_level_percent` | integer | ~ | Operational readiness | `85`, `40` |
| `last_dispatch_time` | ISO 8601 | ~ | Most recent deployment | `"2025-05-15T11:30:00"` |
| `generator_available` | boolean | ~ | For hospitals/cooling centers | `true`, `false` |
| `scenario_assigned` | string | ~ | If pre-assigned to scenario | `"SCN-001"`, `null` |

### Resource Type Distribution (45 total)

| Type | Islamabad | Karachi | Total | Notes |
|------|-----------|---------|-------|-------|
| ambulance | 5 | 5 | 10 | 3 must be "busy" |
| rescue_team | 3 | 3 | 6 | 1 must be "deployed" |
| fire_brigade | 2 | 2 | 4 | |
| hospital | 3 | 3 | 6 | capacity in beds |
| cooling_center | 2 | 2 | 4 | 1 must be "offline" |
| police_unit | 2 | 2 | 4 | |
| traffic_warden | 2 | 2 | 4 | |
| water_tanker | 1 | 2 | 3 | |
| utility_repair_team | 2 | 2 | 4 | IESCO + KE |
| **Total** | **22** | **23** | **45** | |

---

---

## DATASET 5 — City Zones

**Purpose:** Location parsing engine, zone-to-resource matching, map display, and risk-level context for agent decision-making.

**Time Phases:** Static reference dataset (no phases), but risk fields reflect current hazard state

**Target Volume:** 25 zones — 15 Karachi · 10 Islamabad

**Top-level structure:**
```json
{
  "dataset_id": "DS-005",
  "dataset_name": "city_zones",
  "version": "1.0.0",
  "total_zones": 25,
  "zones": [ {...}, {...} ]
}
```

### Column Definitions

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `zone_id` | string | * | Unique zone ID | `"ZN-ISB-001"`, `"ZN-KHI-001"` |
| `zone_name` | string | * | Official area name | `"G-10"`, `"Korangi"`, `"Saddar"` |
| `zone_alias` | array of strings | ~ | Common alternate names | `["G-10 Markaz","G-10/2","G-10/4"]` |
| `city` | string | * | City | `"Islamabad"`, `"Karachi"` |
| `district` | string | * | Administrative district | `"ICT"`, `"Korangi District"` |
| `lat_center` | float | * | Zone centroid latitude | `33.6938` |
| `lng_center` | float | * | Zone centroid longitude | `73.0117` |
| `bbox_north` | float | ~ | Bounding box north | `33.7050` |
| `bbox_south` | float | ~ | Bounding box south | `33.6820` |
| `bbox_east` | float | ~ | Bounding box east | `73.0250` |
| `bbox_west` | float | ~ | Bounding box west | `73.0000` |
| `area_sq_km` | float | * | Zone area | `4.8`, `12.3` |
| `population_estimate` | integer | * | Residential population | `48000`, `210000` |
| `population_density` | string | * | Density category | `"low"`, `"medium"`, `"high"`, `"very_high"` |
| `zone_type` | string | * | Land use classification | `"residential"`, `"commercial"`, `"industrial"`, `"mixed"`, `"government"` |
| `flood_risk` | string | * | Flood vulnerability level | `"low"`, `"medium"`, `"high"`, `"critical"` |
| `heat_risk` | string | * | Heat vulnerability level | `"low"`, `"medium"`, `"high"`, `"critical"` |
| `accident_risk` | string | * | Road accident risk level | `"low"`, `"medium"`, `"high"`, `"critical"` |
| `infrastructure_risk` | string | * | Power/utility failure risk | `"low"`, `"medium"`, `"high"`, `"critical"` |
| `flood_risk_reason` | string | ~ | Why flood-prone | `"Low-lying area, poor drainage, nala overflow history"` |
| `heat_risk_reason` | string | ~ | Why heat-prone | `"Dense concrete, low tree cover, outdoor labor population"` |
| `drainage_quality` | string | ~ | Drainage infrastructure | `"poor"`, `"moderate"`, `"good"` |
| `elevation_m` | float | ~ | Meters above sea level | `508.0`, `14.0` |
| `adjacent_zones` | array of strings | * | Neighboring zone IDs | `["ZN-ISB-002","ZN-ISB-005"]` |
| `main_roads` | array of strings | * | Primary roads in zone | `["G-10 Markaz Road","Srinagar Highway"]` |
| `alternate_routes` | array of strings | * | Available diversion roads | `["Margalla Road","Golra Road"]` |
| `nearest_hospital_id` | string | * | Closest hospital resource ID | `"RSC-015"` |
| `nearest_hospital_distance_km` | float | * | Distance to nearest hospital | `2.3` |
| `active_resources` | array of strings | ~ | Resource IDs currently in zone | `["RSC-001","RSC-007"]` |
| `scenario_relevance` | array of strings | ~ | Which scenarios affect this zone | `["SCN-001","SCN-002"]` |
| `historical_events_count` | integer | ~ | Past crises in this zone | `4` |

### Risk Level Mapping (enforced)

| Zone | City | Flood Risk | Heat Risk | Scenario Link |
|------|------|-----------|-----------|---------------|
| Korangi | Karachi | **CRITICAL** | HIGH | SCN-001 analogue |
| Saddar | Karachi | MEDIUM | **CRITICAL** | SCN-002 analogue |
| Lyari | Karachi | **CRITICAL** | HIGH | SCN-001 |
| G-10 | Islamabad | **CRITICAL** | MEDIUM | SCN-001 |
| F-7/Blue Area | Islamabad | LOW | **CRITICAL** | SCN-002 |
| Faizabad | Islamabad | LOW | MEDIUM | SCN-003 |
| F-6 | Islamabad | LOW | HIGH | SCN-005 |

---

---

## DATASET 6 — Response Actions

**Purpose:** Execution Agent simulates each action by making a mock API call, logging the fake response, and updating system state. This dataset is what makes the "Simulated Execution" screen work.

**Time Phases:** Actions are ordered (priority 1 → 5), not phase-based. Linked to scenario.

**Target Volume:** 25 actions — 9 flooding · 8 heatwave · 8 accident (+ infrastructure and road blockage covered within those)

**Top-level structure:**
```json
{
  "dataset_id": "DS-006",
  "dataset_name": "response_actions",
  "version": "1.0.0",
  "total_actions": 25,
  "actions": [ {...}, {...} ]
}
```

### Column Definitions

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `action_id` | string | * | Unique action ID | `"ACT-001"` |
| `scenario_id` | string | * | Linked scenario | `"SCN-001"` |
| `action_type` | string | * | Execution category | `"reroute"`, `"dispatch"`, `"alert"`, `"activate"`, `"notify"`, `"restrict"` |
| `action_name` | string | * | Short label | `"Reroute G-10 Traffic"` |
| `description` | string | * | Full action description | `"Redirect all G-10 Markaz traffic via Margalla Road due to flood blockage"` |
| `priority` | integer | * | Execution order (1=highest) | `1`, `2`, `3` |
| `trigger_condition` | string | * | What makes this action fire | `"rainfall_mm_hr > 25 AND traffic_status == BLOCKED"` |
| `target_zone` | string | * | Zone this action operates on | `"G-10"`, `"F-7"` |
| `target_city` | string | * | City | `"Islamabad"` |
| `resource_used_id` | string | * | Resource ID from DS-004 | `"RSC-001"` |
| `resource_used_name` | string | * | Human-readable resource name | `"Rescue 1122 Unit 4"` |
| `mock_api_endpoint` | string | * | Simulated REST endpoint | `"POST /api/v1/traffic/reroute"` |
| `mock_api_request_body` | object | * | Request payload | `{"zone":"G-10","alternate":"Margalla Road","duration_mins":90}` |
| `mock_api_response` | object | * | Simulated API response | `{"status":"success","route_updated":true,"eta_change_mins":-18}` |
| `mock_api_status_code` | integer | * | HTTP status | `200`, `201`, `202` |
| `execution_time_ms` | integer | * | Simulated latency | `340`, `820` |
| `estimated_impact` | string | * | Human-readable expected outcome | `"Reduces G-10 congestion by ~74% over 30 mins"` |
| `estimated_people_affected` | integer | * | Citizens impacted | `12400`, `48000` |
| `estimated_vehicles_cleared` | integer | ~ | Vehicles freed (traffic actions) | `35`, `200` |
| `simulation_status` | string | * | Execution result | `"SIMULATED_SUCCESS"`, `"SIMULATED_PARTIAL"`, `"SIMULATED_FAILED"` |
| `failure_reason` | string | ~ | Why it partially/fully failed | `"Resource busy, fallback deployed"` |
| `agent_trace_note` | string | * | What the agent logs about this | `"Dispatch confirmed via Rescue API. Unit Rescue-4 ETA 12 min."` |
| `depends_on_action_id` | string | ~ | Must execute after another action | `"ACT-001"` |
| `rollback_action` | string | ~ | What to do if action fails | `"Deploy warden manually at G-10 Markaz"` |

### Mock API Response Templates (enforced realism)

```json
// dispatch
{"status":"dispatched","unit":"Rescue-4","eta":"12min","location":"G-10 Markaz","ticket_id":"TKT-2025-0415"}

// reroute
{"status":"success","route_id":"RT-G10-MAR","alternate_road":"Margalla Road","activated_at":"14:18:00","estimated_vehicles_diverted":200}

// alert
{"status":"sent","channel":"SMS","recipients":12400,"delivery_rate_percent":94.2,"message_id":"MSG-20250515-0812"}

// activate (cooling center)
{"status":"activated","facility":"F-7 Community Center","capacity":300,"opened_at":"15:00:00","generator_status":"running"}

// notify (utility)
{"status":"notified","dept":"CDA Drainage","ticket_id":"CDA-2025-0318","acknowledged":true,"team_dispatched_in_mins":15}
```

---

---

## DATASET 7 — Notification Registry

**Purpose:** Makes the "X citizens alerted" counter in the simulation screen realistic. Agents pull this to calculate reach of each alert action.

**Time Phases:** Static reference — no phases needed

**Target Volume:** 13 zone records

**Top-level structure:**
```json
{
  "dataset_id": "DS-007",
  "dataset_name": "notification_registry",
  "version": "1.0.0",
  "total_zones": 13,
  "registry": [ {...}, {...} ]
}
```

### Column Definitions

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `registry_id` | string | * | Unique record ID | `"NR-001"` |
| `zone_id` | string | * | Links to DS-005 | `"ZN-ISB-001"` |
| `zone_name` | string | * | Zone display name | `"G-10"` |
| `city` | string | * | City | `"Islamabad"` |
| `registered_users_total` | integer | * | Total app/registry users | `14200` |
| `sms_enabled_count` | integer | * | Users with SMS opted in | `11800` |
| `app_push_enabled_count` | integer | * | Users with push notifications | `7400` |
| `whatsapp_enabled_count` | integer | * | WhatsApp broadcast subscribers | `9200` |
| `email_enabled_count` | integer | ~ | Email subscribers | `3100` |
| `preferred_language` | string | * | Dominant comms language | `"urdu"`, `"english"`, `"mixed"` |
| `language_breakdown` | object | ~ | Language distribution | `{"urdu":0.65,"english":0.35}` |
| `mobile_penetration_percent` | float | * | % of population with smartphone | `72.4`, `58.1` |
| `avg_alert_open_rate_percent` | float | ~ | Historical open rate | `81.3`, `64.5` |
| `last_alert_sent` | ISO 8601 | ~ | Most recent broadcast time | `"2025-03-12T09:00:00"` |
| `last_alert_type` | string | ~ | Type of last alert | `"FLOOD_WARNING"` |
| `radio_fm_channel` | string | ~ | Local FM station for broadcast | `"FM 101.6 Capital Radio"` |
| `emergency_broadcast_enabled` | boolean | * | Can receive emergency broadcasts | `true`, `false` |
| `scenario_relevance` | array of strings | ~ | Active scenario IDs for this zone | `["SCN-001"]` |
| `estimated_reach_per_alert` | integer | * | Expected unique reach per push | `10900` |

### Believable Population Ranges (enforced)

| Zone Type | registered_users_total | sms_enabled | app_push |
|-----------|----------------------|-------------|----------|
| Dense urban (Saddar, G-10) | 12,000 – 18,000 | 9,000–14,000 | 6,000–10,000 |
| Residential (F-7, F-6) | 8,000 – 13,000 | 6,000–10,000 | 5,000–9,000 |
| Industrial (Korangi) | 18,000 – 35,000 | 14,000–28,000 | 7,000–15,000 |
| Peri-urban | 4,000 – 8,000 | 3,000–6,000 | 1,500–4,000 |

---

---

## DATASET 8 — Historical Crisis Events

**Purpose:** Provides the Detection Agent with precedent data. When a new crisis is detected, agents query history to calibrate response time, resource requirements, and reference lessons learned in their reasoning trace.

**Time Phases:** Historical records — no phases. Spans 2021–2024.

**Target Volume:** 15 past events

**Top-level structure:**
```json
{
  "dataset_id": "DS-008",
  "dataset_name": "historical_crisis_events",
  "version": "1.0.0",
  "total_events": 15,
  "date_range": "2021-01-01 to 2024-12-31",
  "events": [ {...}, {...} ]
}
```

### Column Definitions

| Column | Type | Required | Description | Example |
|--------|------|----------|-------------|---------|
| `event_id` | string | * | Unique event ID | `"HCE-001"` |
| `event_date` | ISO 8601 date | * | Date of occurrence | `"2022-08-14"` |
| `crisis_type` | string | * | Category | `"URBAN_FLOODING"`, `"HEATWAVE"`, `"ROAD_BLOCKAGE"`, `"ROAD_ACCIDENT"`, `"INFRASTRUCTURE_FAILURE"` |
| `subtype` | string | ~ | Specific sub-category | `"NALA_OVERFLOW"`, `"POWER_OUTAGE"`, `"PROTEST_BLOCKAGE"` |
| `location_area` | string | * | Affected area | `"Korangi Industrial Area"` |
| `location_city` | string | * | City | `"Karachi"` |
| `location_lat` | float | * | Approx center latitude | `24.8200` |
| `location_lng` | float | * | Approx center longitude | `67.1300` |
| `severity` | string | * | Event severity | `"LOW"`, `"MODERATE"`, `"HIGH"`, `"CRITICAL"` |
| `severity_score` | float 0–1 | * | Numeric severity | `0.82` |
| `duration_hours` | float | * | Total crisis duration | `6.5`, `18.0` |
| `affected_population` | integer | * | People directly affected | `45000`, `8200` |
| `vehicles_affected` | integer | ~ | Vehicles stranded or rerouted | `340`, `0` |
| `casualties` | integer | * | Injuries + fatalities total | `0`, `3`, `12` |
| `fatalities` | integer | * | Deaths | `0`, `1` |
| `property_damage_estimate_pkr` | integer | ~ | Estimated damage in PKR | `4500000`, `0` |
| `response_time_mins` | integer | * | Time from detection to first response | `22`, `8`, `45` |
| `detection_method` | string | * | How crisis was first detected | `"citizen_report"`, `"weather_api"`, `"traffic_sensor"`, `"official_report"` |
| `primary_responder` | string | * | First agency to respond | `"Rescue 1122"`, `"EDHI Foundation"`, `"Traffic Police"` |
| `resources_deployed` | object | * | Breakdown of resources used | `{"ambulances":3,"rescue_teams":2,"police_units":4}` |
| `total_resources_deployed` | integer | * | Sum of all resources | `9` |
| `alerts_sent` | integer | * | Total public alerts dispatched | `31000`, `0` |
| `congestion_reduction_achieved` | integer | ~ | % congestion reduction | `68`, `null` |
| `resolution_method` | string | * | How crisis was resolved | `"Drainage pumps deployed + traffic diverted"` |
| `outcome_rating` | string | * | Post-response assessment | `"GOOD"`, `"FAIR"`, `"POOR"` |
| `key_lesson_learned` | string | * | Agent-referenceable decision insight | `"Early social media cluster (3+ posts in 15 min from same zone) predicted flooding 40 min before traffic API confirmed. Trigger earlier dispatch next time."` |
| `similar_to_scenario_id` | string | ~ | Maps to current scenario | `"SCN-001"` |
| `data_sources_used` | array of strings | * | What signals were available | `["social_media","weather_api","traffic_api"]` |
| `false_alarm` | boolean | * | Was this a false alarm? | `false` |
| `false_alarm_reason` | string | ~ | Why it was a false alarm | `null`, `"Social posts were about a different area"` |

### Event Distribution (enforced)

| Crisis Type | Count | City Split | Severity Mix |
|-------------|-------|-----------|--------------|
| URBAN_FLOODING | 5 | 3 KHI, 2 ISB | 2 CRITICAL, 2 HIGH, 1 MODERATE |
| HEATWAVE | 3 | 2 KHI, 1 ISB | 2 CRITICAL, 1 HIGH |
| ROAD_BLOCKAGE | 2 | 1 KHI, 1 ISB | 1 HIGH, 1 MODERATE |
| ROAD_ACCIDENT | 3 | 2 ISB, 1 KHI | 1 HIGH, 2 MODERATE |
| INFRASTRUCTURE | 2 | 1 KHI, 1 ISB | 1 HIGH, 1 MODERATE |
| **Total** | **15** | | 1 false alarm required |

### Key Lesson Learned Templates (agents must be able to cite these)
- **Flooding:** `"Rainfall crossing 25mm/hr combined with 3+ social posts = 93% flood probability. Pre-position rescue before traffic confirms."`
- **Heatwave:** `"Hospital heatstroke admissions lag temperature peaks by 90 min. Deploy cooling centers when forecast shows >42°C, not after cases spike."`
- **Blockage:** `"Protest blockages last average 3.2 hours in Islamabad. Open both alternates immediately rather than waiting for resolution."`
- **Accident:** `"Wet road + dusk + high-speed zone = elevated accident risk. Reduce speed limit alerts can prevent secondary incidents."`
- **Infrastructure:** `"Power outages during heat advisories become medical emergencies in 2–3 hours. Cooling centers should auto-activate on combined triggers."`

---

---

## Cross-Dataset Linkage Map

```
DS-001 (Social Posts)
  └── scenario_id ──────────────────────────────► All Scenarios
  
DS-002 (Weather)
  └── scenario_id ──────────────────────────────► All Scenarios

DS-003 (Traffic & Roads)
  └── scenario_id ──────────────────────────────► All Scenarios
  └── road_id ──────────────────────────────────► DS-006.resource_used (reroute actions)
  └── zone ─────────────────────────────────────► DS-005.zone_name

DS-004 (Emergency Resources)
  └── resource_id ──────────────────────────────► DS-006.resource_used_id
  └── zone ─────────────────────────────────────► DS-005.zone_id
  └── city ─────────────────────────────────────► DS-003.city

DS-005 (City Zones)
  └── zone_id ──────────────────────────────────► DS-004.zone
  └── zone_id ──────────────────────────────────► DS-007.zone_id
  └── nearest_hospital_id ─────────────────────► DS-004.resource_id

DS-006 (Response Actions)
  └── resource_used_id ─────────────────────────► DS-004.resource_id
  └── scenario_id ──────────────────────────────► All Scenarios
  └── target_zone ──────────────────────────────► DS-005.zone_id

DS-007 (Notification Registry)
  └── zone_id ──────────────────────────────────► DS-005.zone_id
  └── estimated_reach_per_alert ───────────────► DS-006.estimated_people_affected

DS-008 (Historical Events)
  └── similar_to_scenario_id ──────────────────► All Scenarios
  └── key_lesson_learned ───────────────────────► Agent reasoning trace
  └── location_area ────────────────────────────► DS-005.zone_name
```

---

## Agent-to-Dataset Query Map

| Agent | Reads | Writes/Updates |
|-------|-------|----------------|
| Signal Ingestion Agent | DS-001, DS-002, DS-003 | Filters noise, tags signals |
| Detection Agent | DS-002, DS-001 (filtered), DS-008 | Produces confidence score |
| Situation Analysis Agent | DS-005, DS-008 | Generates severity + explanation |
| Response Planning Agent | DS-004, DS-005, DS-006, DS-008 | Selects resources + actions |
| Execution Agent | DS-006, DS-004, DS-007 | Fires mock APIs, updates DS-004 status |
| Outcome Visualization | DS-003 (T0 vs T2), DS-006 results, DS-007 | Renders before/after |

---

*Schema Version 1.0.0 — CIRO Hackathon | All 8 Datasets × 5 Scenarios*
