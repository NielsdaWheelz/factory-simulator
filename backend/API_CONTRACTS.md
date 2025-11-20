# API Contracts for Factory Simulator

This document specifies the frozen HTTP and data contracts for the factory simulator backend. These contracts define the exact shape of all request and response bodies for API endpoints.

**Source of Truth**: See [ONBOARDING_SPRINT_SPEC.md](../ONBOARDING_SPRINT_SPEC.md) for the comprehensive design and philosophy behind these contracts.

## POST /api/simulate

**Purpose**: Run the complete onboarding + simulation + briefing pipeline in a single request.

### Request

```json
{
  "factory_description": "string (free-text description of the factory)",
  "situation_text": "string (free-text description of today's situation)"
}
```

### Response

**Status**: 200 OK

**Body**:

```json
{
  "factory": {
    "machines": [
      { "id": "string", "name": "string" },
      ...
    ],
    "jobs": [
      {
        "id": "string",
        "name": "string",
        "steps": [
          { "machine_id": "string", "duration_hours": "integer" },
          ...
        ],
        "due_time_hour": "integer"
      },
      ...
    ]
  },
  "specs": [
    {
      "scenario_type": "string (BASELINE | RUSH_ARRIVES | M2_SLOWDOWN)",
      "rush_job_id": "string|null",
      "slowdown_factor": "integer|null"
    },
    ...
  ],
  "metrics": [
    {
      "makespan_hour": "integer",
      "job_lateness": { "job_id": "integer", ... },
      "bottleneck_machine_id": "string",
      "bottleneck_utilization": "float (0.0-1.0)"
    },
    ...
  ],
  "briefing": "string (markdown)",
  "meta": {
    "used_default_factory": "boolean",
    "onboarding_errors": ["string", ...],
    "inferred_assumptions": ["string", ...]
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

**Status**: Not yet implemented; reserved for future use.

**Purpose** (future): Separate onboarding from simulation to allow users to review and confirm the factory structure before running scenarios.

### Request (planned)

```json
{
  "factory_description": "string (free-text description of the factory)"
}
```

### Response (planned)

**Status**: 200 OK

**Body**:

```json
{
  "factory": {
    "machines": [
      { "id": "string", "name": "string" },
      ...
    ],
    "jobs": [
      {
        "id": "string",
        "name": "string",
        "steps": [
          { "machine_id": "string", "duration_hours": "integer" },
          ...
        ],
        "due_time_hour": "integer"
      },
      ...
    ]
  },
  "meta": {
    "used_default_factory": "boolean",
    "onboarding_errors": ["string", ...],
    "inferred_assumptions": ["string", ...]
  }
}
```

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

**PR0** (this PR): Introduced frozen contracts for `/api/simulate` response and reserved shape for future `/api/onboard`.

---

## Notes for Developers

- Future PRs **must not** change the response keys or types of these contracts without explicit versioning or migration.
- If new fields are needed, they should be added to the response (extending it) but the existing fields must remain and their types must not change.
- The serialization logic in `backend/serializer.py` ensures all Pydantic models and enums are converted to JSON-native types automatically.
