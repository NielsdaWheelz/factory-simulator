# API Contracts for Factory Simulator

This document is the **canonical source of truth** for the HTTP and data contracts of the factory simulator backend. These contracts define the exact shape of all request and response bodies for API endpoints.

**Versioning**: These contracts are frozen. Any change requires:
1. Updating this document
2. Updating `frontend/src/types.ts` with matching TypeScript interfaces
3. Updating `backend/tests/test_api_contracts.py` with new expected keys/shape assertions

**Philosophy**: See [ONBOARDING_SPRINT_SPEC.md](../ONBOARDING_SPRINT_SPEC.md) for comprehensive design rationale.

## POST /api/simulate

**Purpose**: Run the complete onboarding + simulation + briefing pipeline in a single request.

### Request

**Required Fields**:
- `factory_description` (string): Free-text description of the factory, machines, jobs, and routing
- `situation_text` (string): Free-text description of today's situation, priorities, or special requests

**Example**:
```json
{
  "factory_description": "We have 3 machines: Assembly (M1), Drill (M2), Pack (M3). We run 3 jobs: J1 (2h, 3h, 1h), J2 (1.5h, 2h, 1.5h), J3 (3h, 1h, 2h). All jobs due at 24 hours.",
  "situation_text": "Normal production day. Interested in baseline schedule and bottleneck identification."
}
```

### Response

**Status**: 200 OK

**Body**:

**Schema** (top-level keys; exact order not guaranteed):

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `factory` | FactoryConfig | Yes | Onboarded factory structure |
| `specs` | ScenarioSpec[] | Yes | List of scenario specifications (non-empty) |
| `metrics` | ScenarioMetrics[] | Yes | Performance metrics for each scenario (same length as specs) |
| `briefing` | string | Yes | Markdown briefing summarizing scenarios and recommendations |
| `meta` | OnboardingMeta | Yes | Metadata about onboarding process |

**Example**:
```json
{
  "factory": {
    "machines": [
      { "id": "M1", "name": "Assembly" },
      { "id": "M2", "name": "Drill" },
      { "id": "M3", "name": "Pack" }
    ],
    "jobs": [
      {
        "id": "J1",
        "name": "Product A",
        "steps": [
          { "machine_id": "M1", "duration_hours": 2 },
          { "machine_id": "M2", "duration_hours": 3 },
          { "machine_id": "M3", "duration_hours": 1 }
        ],
        "due_time_hour": 24
      }
    ]
  },
  "specs": [
    { "scenario_type": "BASELINE", "rush_job_id": null, "slowdown_factor": null },
    { "scenario_type": "RUSH_ARRIVES", "rush_job_id": "J1", "slowdown_factor": null },
    { "scenario_type": "M2_SLOWDOWN", "rush_job_id": null, "slowdown_factor": 2 }
  ],
  "metrics": [
    {
      "makespan_hour": 6,
      "job_lateness": { "J1": 0 },
      "bottleneck_machine_id": "M2",
      "bottleneck_utilization": 0.75
    },
    {
      "makespan_hour": 6,
      "job_lateness": { "J1": 0 },
      "bottleneck_machine_id": "M2",
      "bottleneck_utilization": 0.75
    },
    {
      "makespan_hour": 9,
      "job_lateness": { "J1": 3 },
      "bottleneck_machine_id": "M2",
      "bottleneck_utilization": 1.0
    }
  ],
  "briefing": "# Simulation Results\n\n...",
  "meta": {
    "used_default_factory": false,
    "onboarding_errors": [],
    "inferred_assumptions": []
  }
}
```

**Contract Guarantees**:
- Response always has exactly these 5 top-level keys: `factory`, `specs`, `metrics`, `briefing`, `meta`
- `factory` is a FactoryConfig object with `machines` and `jobs` lists
- `specs` is a non-empty list of ScenarioSpec objects (at least 1 scenario)
- `metrics` is a list of ScenarioMetrics, same length as `specs`, same order
- `briefing` is a markdown string
- `meta` always includes:
  - `used_default_factory`: boolean indicating if toy factory fallback was used
  - `onboarding_errors`: list of strings (may be empty); documents repairs made during normalization
  - `inferred_assumptions`: list of strings (may be empty); documents assumptions made by LLM during interpretation

**Invariants**:
- `len(specs) == len(metrics)` (one metrics object per scenario spec)
- `used_default_factory` is `true` only if normalization fell back to toy factory (Level 2 failure)
- `onboarding_errors` is empty only if normalization made no repairs (Levels 0)
- All enum values (e.g., `scenario_type`) are serialized as strings

---

## POST /api/onboard

**Purpose**: Separate onboarding from simulation to allow users to review and confirm the factory structure before running scenarios.

### Request

**Required Fields**:
- `factory_description` (string): Free-text description of the factory, machines, jobs, and routing

**Example**:
```json
{
  "factory_description": "We have 3 machines: Assembly (M1), Drill (M2), Pack (M3). We run 3 jobs: J1 (2h, 3h, 1h), J2 (1.5h, 2h, 1.5h), J3 (3h, 1h, 2h). All jobs due at 24 hours."
}
```

### Response

**Status**: 200 OK

**Body**:

**Schema** (top-level keys; exact order not guaranteed):

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `factory` | FactoryConfig | Yes | Onboarded and normalized factory structure |
| `meta` | OnboardingMeta | Yes | Metadata about onboarding process |

**Example**:
```json
{
  "factory": {
    "machines": [
      { "id": "M1", "name": "Assembly" },
      { "id": "M2", "name": "Drill" },
      { "id": "M3", "name": "Pack" }
    ],
    "jobs": [
      {
        "id": "J1",
        "name": "Product A",
        "steps": [
          { "machine_id": "M1", "duration_hours": 2 },
          { "machine_id": "M2", "duration_hours": 3 },
          { "machine_id": "M3", "duration_hours": 1 }
        ],
        "due_time_hour": 24
      }
    ]
  },
  "meta": {
    "used_default_factory": false,
    "onboarding_errors": [],
    "inferred_assumptions": []
  }
}
```

**Contract Guarantees**:
- Response always has exactly these 2 top-level keys: `factory`, `meta` (no other keys allowed)
- `factory` is a FactoryConfig object with `machines` and `jobs` lists (both always present as arrays, possibly empty only in fallback cases)
- `meta` always includes exactly these 3 fields:
  - `used_default_factory`: boolean indicating if toy factory fallback was used
  - `onboarding_errors`: list of strings (may be empty); documents repairs made during normalization
  - `inferred_assumptions`: list of strings (may be empty); documents assumptions inferred by LLM during interpretation

**Invariants**:
- `used_default_factory` is `true` only if normalization fell back to toy factory (zero machines or zero jobs after normalization)
- `used_default_factory` is `false` if onboarded/normalized factory is usable (has at least one machine and one job)
- `onboarding_errors` is empty only if normalization made no repairs
- `inferred_assumptions` lists assumptions made during interpretation (empty if none or if fallback occurred)
- Response is guaranteed to have a non-empty factory (either the onboarded one or toy factory fallback)

---

## Error Responses

All endpoints return standard HTTP error codes:

- **400 Bad Request**: Malformed JSON or invalid request body
- **422 Unprocessable Entity**: Request validation failed (e.g., missing required fields)
- **500 Internal Server Error**: Unexpected backend error (should not happen in normal operation; the pipeline handles user text gracefully)

Error responses include a plain-text or JSON error message in the response body (FastAPI default).

---

## Data Types

### OnboardingMeta

```python
class OnboardingMeta(BaseModel):
    used_default_factory: bool
    onboarding_errors: list[str]
    inferred_assumptions: list[str]
```

**Semantics**:
- `used_default_factory=true` indicates a Level 2 failure (fallback); the factory displayed is the toy factory.
- `used_default_factory=false` indicates a Level 0 or Level 1 outcome; the factory is either pristine (Level 0, no errors) or degraded (Level 1, some repairs made).
- `onboarding_errors` lists all repairs made by `normalize_factory` (empty for Level 0, non-empty for Level 1 and 2).
- `inferred_assumptions` lists what the OnboardingAgent inferred from ambiguous user text (empty if nothing was inferred or if `used_default_factory=true`).

See ONBOARDING_SPRINT_SPEC.md section 5.4 (Failure Ladder) for detailed level definitions.

### FactoryConfig, Machine, Job, Step

As defined in models.py; see ONBOARDING_SPRINT_SPEC.md section 3 (Data Contracts) for semantics.

### ScenarioSpec

Three scenario types supported:
- **BASELINE**: No changes; baseline schedule.
- **RUSH_ARRIVES**: Treat a job as high-priority by tightening its due time. Requires `rush_job_id` field.
- **M2_SLOWDOWN**: Simulate slowdown of machine M2. Requires `slowdown_factor` field (integer ≥ 2).

### ScenarioMetrics

Performance metrics for a single scenario:
- `makespan_hour`: Total hours from start (hour 0) to completion of last job
- `job_lateness`: Map of job ID to lateness in hours (≥ 0; 0 if on-time)
- `bottleneck_machine_id`: ID of the machine with highest utilization
- `bottleneck_utilization`: Utilization of bottleneck as a fraction (0.0 to 1.0)

---

## Version History

**PR0**: Introduced frozen contracts for `/api/simulate` response and reserved shape for future `/api/onboard`.

**PR1**: Implemented `/api/onboard` endpoint with OnboardingAgent and normalization wiring. Endpoint returns factory configuration and onboarding metadata.

---

## Contract Summary

### Frozen Key Sets

**These keys are locked and must never change:**

```python
# /api/simulate response top-level keys (exact set)
EXPECTED_SIMULATE_KEYS = {"factory", "specs", "metrics", "briefing", "meta"}

# /api/onboard response top-level keys (exact set)
EXPECTED_ONBOARD_KEYS = {"factory", "meta"}

# OnboardingMeta/meta keys (exact set, same for both endpoints)
EXPECTED_META_KEYS = {"used_default_factory", "onboarding_errors", "inferred_assumptions"}

# FactoryConfig keys (exact set)
EXPECTED_FACTORY_KEYS = {"machines", "jobs"}

# Machine keys (exact set)
EXPECTED_MACHINE_KEYS = {"id", "name"}

# Job keys (exact set)
EXPECTED_JOB_KEYS = {"id", "name", "steps", "due_time_hour"}

# Step keys (exact set)
EXPECTED_STEP_KEYS = {"machine_id", "duration_hours"}

# ScenarioSpec keys (exact set)
EXPECTED_SCENARIO_SPEC_KEYS = {"scenario_type", "rush_job_id", "slowdown_factor"}

# ScenarioMetrics keys (exact set)
EXPECTED_SCENARIO_METRICS_KEYS = {"makespan_hour", "job_lateness", "bottleneck_machine_id", "bottleneck_utilization"}
```

Any addition, removal, or renaming of these keys requires a major version bump and must be coordinated with frontend and all consuming systems.

## Notes for Developers

- These contracts are **frozen and locked** for this PR.
- Future PRs **must not** change response keys, types, or schemas without explicit major version bump.
- If new fields are needed, they must be added **additively** (new keys, not changes to existing ones).
- The existing fields must remain, their types must not change, and their serialization must remain compatible.
- The serialization logic in `backend/serializer.py` ensures all Pydantic models and enums are converted to JSON-native types automatically.
- All tests in `backend/tests/test_api_contracts.py` enforce these contracts and will fail if the shape changes.
