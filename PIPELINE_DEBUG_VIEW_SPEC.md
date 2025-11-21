# Pipeline Debug View Specification

**For:** Factory Simulator Frontend + Backend
**Scope:** Exposing 10-stage LLM orchestration (onboarding + decision) to end users
**Time Budget:** ~1–1.5 hours across 3 focused PRs
**Status:** Production spec (rewritten for clarity, implementability, and architectural discipline)

---

## 1. System Overview

The factory simulator runs two orchestrated pipelines, currently invisible to users:

1. **Onboarding (O0–O4):** Free-text factory description → validated `FactoryConfig`
2. **Decision (D1–D5):** Free-text situation + factory → scenarios, simulation, briefing

**Current gap:** Users see only final output. A reviewer must read logs to understand *which stages ran*, *which failed*, and *why*.

**Solution:** Add an optional `debug` field to `/api/simulate` response. Backend populates it with stage-level summaries. Frontend renders a **Pipeline Inspector** panel showing all 10 stages, their status, and summary metrics.

---

## 2. Backend Debug Payload

### Data Shape

```typescript
// Added to POST /api/simulate response
{
  "factory": { ... },        // existing
  "specs": [ ... ],          // existing
  "metrics": [ ... ],        // existing
  "briefing": "...",         // existing
  "meta": { ... },           // existing
  "debug": PipelineDebugPayload  // NEW, optional
}

// ============================================================================

interface PipelineDebugPayload {
  // Input summary (not full dumps)
  inputs: {
    factory_text_chars: number;
    factory_text_preview: string;  // first 200 chars
    situation_text_chars: number;
    situation_text_preview: string;  // first 200 chars
  };

  // Overall pipeline status
  overall_status: "SUCCESS" | "PARTIAL" | "FAILED";
  // SUCCESS: all stages succeeded
  // PARTIAL: onboarding failed, fell back to toy factory, decision succeeded
  // FAILED: decision pipeline crashed or unrecoverable error

  // Array of stage execution records
  stages: PipelineStageRecord[];
}

// ============================================================================

interface PipelineStageRecord {
  id: string;                // "O0", "O1", ..., "D5"
  name: string;              // Human-readable name
  kind: "ONBOARDING" | "DECISION";  // Stage category
  status: "SUCCESS" | "FAILED" | "SKIPPED";  // Only these three
  agent_model: string | null;  // "gpt-4.1" if LLM, null if deterministic
  summary: StageSummary;     // Minimal key fields only
  errors: string[];          // Empty if status is SUCCESS
}

// ============================================================================

// Stage-specific summaries (minimal, implementable)
type StageSummary =
  | O0Summary | O1Summary | O2Summary | O3Summary | O4Summary
  | D1Summary | D2Summary | D3Summary | D4Summary | D5Summary;

// Onboarding summaries

interface O0Summary {
  stage_type: "EXPLICIT_ID_EXTRACTION";
  machine_ids: string[];     // e.g., ["M1", "M2", "M3"]
  job_ids: string[];         // e.g., ["J1", "J2", "J3"]
}

interface O1Summary {
  stage_type: "COARSE_STRUCTURE";
  machine_count: number;     // Coarse count from LLM
  job_count: number;
}

interface O2Summary {
  stage_type: "FINE_EXTRACTION";
  machine_count: number;     // After step extraction
  job_count: number;
  total_steps: number;
}

interface O3Summary {
  stage_type: "NORMALIZATION";
  machine_count: number;     // After normalization
  job_count: number;
}

interface O4Summary {
  stage_type: "COVERAGE_ASSESSMENT";
  detected_machine_ids: string[];  // From regex (user text)
  detected_job_ids: string[];      // From regex (user text)
  parsed_machine_ids: string[];    // In final factory
  parsed_job_ids: string[];        // In final factory
  coverage_percent: number;        // 0–100
  missing_machines: string[];      // In user text but not parsed
  missing_jobs: string[];          // In user text but not parsed
}

// Decision summaries

interface D1Summary {
  stage_type: "INTENT_CLASSIFICATION";
  scenario_type: string;     // "BASELINE", "RUSH_ARRIVES", "M2_SLOWDOWN"
}

interface D2Summary {
  stage_type: "FUTURES_EXPANSION";
  scenario_count: number;    // How many specs generated
  scenario_types: string[];  // List of types
}

interface D3Summary {
  stage_type: "SIMULATION";
  scenario_count: number;    // Simulations run
}

interface D4Summary {
  stage_type: "METRICS_COMPUTATION";
  scenario_count: number;    // Metrics computed
}

interface D5Summary {
  stage_type: "BRIEFING_GENERATION";
  briefing_length: number;   // Character count
}
```

### Semantics

**Status values (strictly: SUCCESS | FAILED | SKIPPED)**
- `SUCCESS`: Stage executed, produced output.
- `FAILED`: Stage crashed, validation failed, or LLM returned invalid data. Error list is populated.
- `SKIPPED`: Stage did not run (e.g., D2–D5 skipped if D1 failed catastrophically).

**overall_status semantics:**
- `SUCCESS`: All O0–O4 succeeded (100% coverage or no fallback needed). All D1–D5 succeeded.
- `PARTIAL`: O0–O3 succeeded, but O4 failed (missing IDs). System fell back to toy factory. D1–D5 ran with toy factory and succeeded.
- `FAILED`: Any D1–D5 failed, or O0–O3 failed (unrecoverable).

**Fallback behavior (explicit):**
- If O4 fails (coverage < 100%), system falls back to `build_toy_factory()`.
- This is encoded as `overall_status = "PARTIAL"` + `used_default_factory = true` in response `meta`.
- All D1–D5 stages then run with the toy factory and report `status = "SUCCESS"` (or `FAILED` if the decision itself crashes).

### Truncation

- `factory_text_preview`: max 200 chars
- `situation_text_preview`: max 200 chars
- Individual `errors[]` entries: max 200 chars each

---

## 3. Concrete Examples

### Example 1: Success (100% Coverage)

```json
{
  "debug": {
    "inputs": {
      "factory_text_chars": 245,
      "factory_text_preview": "We run 3 machines (M1 assembly, M2 drill, M3 pack). Jobs J1, J2, J3..."
    },
    "overall_status": "SUCCESS",
    "stages": [
      {
        "id": "O0",
        "name": "Extract Explicit IDs",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "EXPLICIT_ID_EXTRACTION",
          "machine_ids": ["M1", "M2", "M3"],
          "job_ids": ["J1", "J2", "J3"]
        },
        "errors": []
      },
      {
        "id": "O1",
        "name": "Extract Coarse Structure",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "COARSE_STRUCTURE",
          "machine_count": 3,
          "job_count": 3
        },
        "errors": []
      },
      {
        "id": "O2",
        "name": "Extract Job Steps",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "FINE_EXTRACTION",
          "machine_count": 3,
          "job_count": 3,
          "total_steps": 9
        },
        "errors": []
      },
      {
        "id": "O3",
        "name": "Validate & Normalize",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "NORMALIZATION",
          "machine_count": 3,
          "job_count": 3
        },
        "errors": []
      },
      {
        "id": "O4",
        "name": "Coverage Assessment",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "COVERAGE_ASSESSMENT",
          "detected_machine_ids": ["M1", "M2", "M3"],
          "detected_job_ids": ["J1", "J2", "J3"],
          "parsed_machine_ids": ["M1", "M2", "M3"],
          "parsed_job_ids": ["J1", "J2", "J3"],
          "coverage_percent": 100,
          "missing_machines": [],
          "missing_jobs": []
        },
        "errors": []
      },
      {
        "id": "D1",
        "name": "Intent Classification",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "INTENT_CLASSIFICATION",
          "scenario_type": "BASELINE"
        },
        "errors": []
      },
      {
        "id": "D2",
        "name": "Futures Expansion",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "FUTURES_EXPANSION",
          "scenario_count": 3,
          "scenario_types": ["BASELINE", "RUSH_ARRIVES", "M2_SLOWDOWN"]
        },
        "errors": []
      },
      {
        "id": "D3",
        "name": "Simulation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "SIMULATION",
          "scenario_count": 3
        },
        "errors": []
      },
      {
        "id": "D4",
        "name": "Metrics Computation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "METRICS_COMPUTATION",
          "scenario_count": 3
        },
        "errors": []
      },
      {
        "id": "D5",
        "name": "Briefing Generation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "BRIEFING_GENERATION",
          "briefing_length": 1205
        },
        "errors": []
      }
    ]
  }
}
```

### Example 2: Coverage Failure (Fallback)

```json
{
  "debug": {
    "inputs": {
      "factory_text_chars": 156,
      "factory_text_preview": "Machines M1, M2, M5 for assembly. Jobs J1, J2, J7 due at times..."
    },
    "overall_status": "PARTIAL",
    "stages": [
      {
        "id": "O0",
        "name": "Extract Explicit IDs",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "EXPLICIT_ID_EXTRACTION",
          "machine_ids": ["M1", "M2", "M5"],
          "job_ids": ["J1", "J2", "J7"]
        },
        "errors": []
      },
      {
        "id": "O1",
        "name": "Extract Coarse Structure",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "COARSE_STRUCTURE",
          "machine_count": 3,
          "job_count": 3
        },
        "errors": []
      },
      {
        "id": "O2",
        "name": "Extract Job Steps",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "FINE_EXTRACTION",
          "machine_count": 2,
          "job_count": 2,
          "total_steps": 4
        },
        "errors": []
      },
      {
        "id": "O3",
        "name": "Validate & Normalize",
        "kind": "ONBOARDING",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "NORMALIZATION",
          "machine_count": 2,
          "job_count": 2
        },
        "errors": []
      },
      {
        "id": "O4",
        "name": "Coverage Assessment",
        "kind": "ONBOARDING",
        "status": "FAILED",
        "agent_model": null,
        "summary": {
          "stage_type": "COVERAGE_ASSESSMENT",
          "detected_machine_ids": ["M1", "M2", "M5"],
          "detected_job_ids": ["J1", "J2", "J7"],
          "parsed_machine_ids": ["M1", "M2"],
          "parsed_job_ids": ["J1", "J2"],
          "coverage_percent": 67,
          "missing_machines": ["M5"],
          "missing_jobs": ["J7"]
        },
        "errors": ["Coverage mismatch: M5 mentioned but not parsed", "Coverage mismatch: J7 mentioned but not parsed"]
      },
      {
        "id": "D1",
        "name": "Intent Classification",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "INTENT_CLASSIFICATION",
          "scenario_type": "BASELINE"
        },
        "errors": []
      },
      {
        "id": "D2",
        "name": "Futures Expansion",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "FUTURES_EXPANSION",
          "scenario_count": 3,
          "scenario_types": ["BASELINE", "RUSH_ARRIVES", "M2_SLOWDOWN"]
        },
        "errors": []
      },
      {
        "id": "D3",
        "name": "Simulation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "SIMULATION",
          "scenario_count": 3
        },
        "errors": []
      },
      {
        "id": "D4",
        "name": "Metrics Computation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": null,
        "summary": {
          "stage_type": "METRICS_COMPUTATION",
          "scenario_count": 3
        },
        "errors": []
      },
      {
        "id": "D5",
        "name": "Briefing Generation",
        "kind": "DECISION",
        "status": "SUCCESS",
        "agent_model": "gpt-4.1",
        "summary": {
          "stage_type": "BRIEFING_GENERATION",
          "briefing_length": 980
        },
        "errors": []
      }
    ]
  }
}
```

---

## 4. Frontend UI Architecture

### High-Level Layout

Add a **third panel** to the output section:
1. Left: Inferred Factory (existing)
2. Center: Scenarios & Metrics (existing)
3. Right: **Pipeline Inspector** (NEW)

### Core Components

#### `PipelineSummary`

Rendered at top of Pipeline Inspector panel. Provides health overview.

**Props:**
```typescript
interface PipelineSummaryProps {
  debug: PipelineDebugPayload | null;
  used_default_factory: boolean;  // from meta
}
```

**Render:**
- If `debug === null`: Show placeholder "Pipeline details not available."
- If `debug.overall_status === "SUCCESS"`: Green checkmark. "All 10 stages succeeded. 100% coverage."
- If `debug.overall_status === "PARTIAL"`: Yellow warning. "Onboarding failed at O4 (Coverage Assessment). Missing: M5, J7. Fell back to demo factory. Decision pipeline succeeded."
- If `debug.overall_status === "FAILED"`: Red X. "Pipeline failed. See details below."

#### `StageList`

Vertical list of all 10 stages. Each row clickable.

**Props:**
```typescript
interface StageListProps {
  stages: PipelineStageRecord[];
  expandedStageId: string | null;
  onSelectStage: (id: string) => void;
}
```

**Per-row rendering:**
```
[✓ O0] Extract Explicit IDs           SUCCESS
[✓ O1] Extract Coarse Structure       SUCCESS
[✓ O2] Extract Job Steps              SUCCESS
[✓ O3] Validate & Normalize           SUCCESS
[✓ O4] Coverage Assessment            SUCCESS
[✓ D1] Intent Classification          SUCCESS
[✓ D2] Futures Expansion              SUCCESS
[✓ D3] Simulation                     SUCCESS
[✓ D4] Metrics Computation            SUCCESS
[✓ D5] Briefing Generation            SUCCESS
```

Icons:
- `✓` green: SUCCESS
- `✗` red: FAILED
- `⊘` gray: SKIPPED

Clicking a row sets `expandedStageId = stage.id` and opens the detail panel.

#### `StageDetailPanel`

Opened when user clicks a row. Shows full stage information.

**Props:**
```typescript
interface StageDetailPanelProps {
  stage: PipelineStageRecord | null;
  isOpen: boolean;
  onClose: () => void;
}
```

**Rendering (example for O4):**
```
═════════════════════════════════════════
[✓] O4: Coverage Assessment
═════════════════════════════════════════

Status: SUCCESS
Agent: Deterministic (no LLM)

Detected Machine IDs (from user text):
  M1, M2, M3

Parsed Factory (after onboarding):
  Machines: M1, M2, M3
  Jobs: J1, J2, J3

Coverage: 100%

Errors: (none)
```

**For a failure (example O4 failure):**
```
═════════════════════════════════════════
[✗] O4: Coverage Assessment
═════════════════════════════════════════

Status: FAILED
Agent: Deterministic (no LLM)

Detected Machine IDs (from user text):
  M1, M2, M5

Parsed Factory (after onboarding):
  Machines: M1, M2
  Jobs: J1, J2

Coverage: 67% (2/3 machines, 2/3 jobs)

Missing:
  Machines: M5
  Jobs: J7

Errors:
  • Coverage mismatch: M5 mentioned but not parsed
  • Coverage mismatch: J7 mentioned but not parsed

ACTION: Fell back to demo factory. Decision pipeline ran successfully.
```

### Frontend State

```typescript
interface AppState {
  // Existing
  result: SimulateResponse | null;

  // NEW
  expandedStageId: string | null;
}
```

**Behavior:**
- User clicks "Simulate" → set `expandedStageId = null`.
- Response arrives → update `result`, populate debug.
- User clicks stage row → set `expandedStageId` to that row's ID.
- Detail panel closes → set `expandedStageId = null`.

### Integration with Fallback Banner

Existing fallback banner (in response.meta.used_default_factory) should link to the Pipeline Inspector:

```jsx
{result?.meta?.used_default_factory && (
  <div className="fallback-banner">
    <strong>⚠️ Using Demo Factory</strong>
    <p>We couldn't fully parse your factory description. Missing: M5, J7.</p>
    {result?.debug && (
      <button onClick={() => setExpandedStageId("O4")}>
        View Coverage Details →
      </button>
    )}
  </div>
)}
```

### Graceful Degradation

- If `result.debug === null` (uninstrumented backend), pipeline panel shows placeholder. No crash.
- If a stage record is missing from `debug.stages`, skip it in rendering. Log a warning.

---

## 5. Implementation Roadmap (3 PRs)

### PRF1: Backend Debug Instrumentation (30–45 min)

**What:** Wrap orchestrator to capture stage-level metadata. Add `debug` field to `/api/simulate` response.

**Changes:**
1. Update `orchestrator.py:run_onboarded_pipeline()`:
   - For each stage O0–O4, wrap execution with try/catch.
   - Capture status, summary, errors.
   - Build `PipelineDebugPayload`.

2. Update `server.py:simulate_endpoint()`:
   - Include `debug` field in response dict.
   - Serialize cleanly as JSON.

3. Update `models.py` (optional):
   - Add `PipelineDebugPayload` type hint (can be plain dict with comments).

**Testing:**
- Unit test: Verify debug payload shape for success case.
- Unit test: Verify debug payload for fallback case (O4 fails, D1–D5 succeed).
- Integration test: `/api/simulate` endpoint returns `response["debug"]` correctly formatted.

**Definition of Done:**
- Every `/api/simulate` call returns `debug` field.
- All 10 stages have records.
- No HTTP contract breaking (debug is optional).
- Truncation enforced (texts ≤ 200 chars, error messages ≤ 200 chars).

---

### PRF2: Frontend Basic Panel (25–35 min)

**What:** Render PipelineSummary + StageList in a new right-hand panel.

**Changes:**
1. Create `frontend/src/components/PipelineSummary.tsx`.
2. Create `frontend/src/components/StageList.tsx`.
3. Update `frontend/src/App.tsx`:
   - Add state: `expandedStageId`.
   - Render pipeline panel below factory and metrics panels.
4. Add CSS for layout and styling.

**Testing:**
- Component test: PipelineSummary renders correctly for SUCCESS/PARTIAL/FAILED.
- Component test: StageList renders all stages with correct icons.
- Integration test: Pipeline panel renders when `result.debug` is present.

**Definition of Done:**
- Pipeline panel visible.
- All stages rendered with correct status icons.
- No crashes when debug is missing.
- Existing panels unaffected.

---

### PRF3: Frontend Detail Panel + Integration (20–30 min)

**What:** Add expandable detail view. Link fallback banner to Pipeline Inspector.

**Changes:**
1. Create `frontend/src/components/StageDetailPanel.tsx`.
2. Update `frontend/src/App.tsx`:
   - Wire `expandedStageId` state.
   - Render StageDetailPanel conditionally.
3. Update fallback banner to include "View Details" link.
4. Add CSS for detail panel.

**Testing:**
- Component test: StageDetailPanel renders detail correctly for O4 and D1.
- Integration test: Click stage row → detail panel opens. Click close → closes.
- Integration test: Fallback banner "View Details" → opens O4 detail.

**Definition of Done:**
- Detail panel is fully functional.
- All stage information visible.
- UI is readable and not cramped.
- Fallback banner integrated.

---

## 6. Key Invariants

1. **No silent failures:** If any stage fails, it is recorded in the debug payload with explicit status and error messages.
2. **Onboarding isolation:** O0–O4 run in sequence. If any fails after O3, fallback to toy factory. D1–D5 always run (with either the parsed factory or the toy factory).
3. **Status semantics:** Only SUCCESS, FAILED, SKIPPED. No FALLBACK_USED per-stage (fallback is pipeline-level, tracked via overall_status = "PARTIAL").
4. **Observational only:** Debug payload does not alter execution or correctness. It is purely for visibility.
5. **Minimal summaries:** Each summary contains only the fields needed for meaningful debugging (counts, IDs, coverage %). No speculative fields.

---

## 7. Success Criteria

**Acceptance Test 1: Happy Path (100% Coverage)**
- User enters well-formed factory description.
- Pipeline panel shows all 10 stages with green checkmarks.
- O4 shows "Coverage: 100%".
- No fallback banner.
- `overall_status = "SUCCESS"`.

**Acceptance Test 2: Coverage Failure**
- User enters factory with missing IDs (e.g., M5 mentioned, not parsed).
- O4 shows red ✗.
- O4 detail shows: coverage 67%, missing: [M5], errors logged.
- Fallback banner appears: "Using Demo Factory. Missing: M5".
- D1–D5 show green (ran with toy factory).
- `overall_status = "PARTIAL"`.

**Acceptance Test 3: Graceful Degradation**
- Backend is old (no debug field).
- Frontend does not crash.
- Pipeline panel shows: "Pipeline details not available."

---

## 8. HTTP Contract

```
POST /api/simulate
Request:  { "factory_description": string, "situation_text": string }
Response: {
  "factory": FactoryConfig,
  "specs": list[ScenarioSpec],
  "metrics": list[ScenarioMetrics],
  "briefing": string,
  "meta": OnboardingMeta,
  "debug"?: PipelineDebugPayload  // NEW, optional field
}
```

The `debug` field is entirely optional and backward-compatible.

---

## 9. Responsibilities Demonstrated

This work demonstrates:
- **Multi-stage orchestration:** 10 stages in explicit order, clear separation of concerns.
- **Observability:** Every stage has status, summary, and error tracking.
- **Fallback semantics:** Explicit fallback to toy factory on onboarding failure, clear recovery path.
- **No silent failures:** All errors logged and surfaced to user.
- **Deterministic pipeline:** Same input + factory → same debug output (no randomness).

---

**End of Specification**
