# Onboarding + UI Flow Sprint Specification

## 1. Context & Goals

### Existing System

The factory simulator already implements:

- **Core simulation engine**: `FactoryConfig`, `Machine`, `Job`, `Step`, `ScenarioSpec`, `ScenarioMetrics`, deterministic EDD scheduler.
- **Multi-agent LLM boundary**: `IntentAgent` (situation text → scenario intent), `FuturesAgent` (intent → scenario variations), `BriefingAgent` (metrics → markdown briefing).
- **Orchestration pipeline**: `run_pipeline`, `run_onboarded_pipeline` that wire agents → simulation → metrics → briefing.
- **FastAPI server**: Single endpoint `POST /api/simulate` that accepts `factory_description` and `situation_text`, returns factory, specs, metrics, and briefing.
- **React + Vite frontend**: Two textareas (factory description, situation) with mock factory summaries and scenario visualization.

All of this is **tested, deployed, and working as a complete demo**.

### This Sprint's Goal

**Add structured onboarding flow**: Transform free-text factory descriptions into safe, normalized `FactoryConfig` objects, surface the structured factory to the user, and ensure the simulation pipeline uses the onboarded factory.

In concrete terms:

1. **User provides factory description** (free-form text: machines, jobs, routing, due times, durations).
2. **OnboardingAgent (LLM)** interprets the text and outputs a best-effort `FactoryConfig`.
3. **normalize_factory** validates and repairs the config (fix durations, invalid references, cap sizes).
4. **Frontend shows the structured factory**: machines, jobs, steps, due times—plus any warnings.
5. **User provides situation text** (priorities, rush orders, constraints).
6. **Backend runs decision pipeline**: IntentAgent → FuturesAgent → simulate + metrics → BriefingAgent.
7. **Briefing reflects onboarding state**: References the onboarded factory structure, reports any constraints or fallbacks.

### Demo Constraints (This Sprint Only)

This sprint operates with the following **demo-scope constraints**, which are intentionally scoped for this onboarding flow but are **not architectural limits** of the long-term system design:

- **Single day horizon**: All times in integer hours, 0–24 *(demo limit; future phases will support rolling schedules and multi-day planning)*.
- **Toy factory baseline**: Max ~10 machines, ~15 jobs, ~10 steps per job *(demo caps; enforced by normalization, but not reflective of production factory complexity)*.
- **No multi-day, costs, quantities, or branching jobs** *(demo constraints; future phases will support batching, resource pools, and complex routing)*.
- **LLM only at boundaries**: OnboardingAgent, IntentAgent, FuturesAgent, BriefingAgent. Core sim is pure logic *(design principle that scales; enables testability and reproducibility)*.

**Key point**: These limits (max machines, jobs, steps; no branching; single-day horizon) are **demo constraints for this onboarding sprint, not hard architectural limits**. The core data model (`FactoryConfig`, `Machine`, `Job`, `Step`) and the interpretation→repair→simulation flow are designed to generalize to larger factories and richer constraints in future phases.

### Success Criteria (High Level)

**For the user**:
- Can paste a factory description and see it parsed into machines, jobs, and steps.
- Can see warnings if the description was ambiguous or required fallback.
- Can run scenarios against the onboarded factory.
- Briefing references the onboarded structure and explains what was inferred.

**For the CTO**:
- Clear, non-negotiable contract between unstructured input (text) and structured output (FactoryConfig).
- Normalization ladder with three failure modes: OK, degraded, fallback.
- LLM strictly scoped; no hallucination or out-of-bounds inferences.
- System never crashes on user text; worst case is clear warning + toy factory fallback.
- Enough logging to debug what happened during onboarding.

---

## 2. Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite)                                    │
│  - Step 1: Factory Description Textarea + "Onboard" button  │
│  - Show: Factory summary, warnings, errors                  │
│  - Step 2: Situation Textarea + "Run Scenarios" button      │
│  - Show: Scenarios, metrics, briefing markdown              │
└─────────────────────────────────────────────────────────────┘
                            ↕ HTTP
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                          │
│  POST /api/onboard → OnboardingAgent + normalize_factory    │
│  POST /api/simulate → run_onboarded_pipeline                │
└─────────────────────────────────────────────────────────────┘
```

### Onboarding Pipeline

```
factory_description (str)
    ↓
[OnboardingAgent.run(text)]  ← LLM-backed: interpret free-text
    ↓ output: FactoryConfig (raw, may have issues)
[normalize_factory(config)]  ← Pure: repair and validate
    ↓ output: FactoryConfig (safe)
[OnboardingMeta]
    ├ used_default_factory: bool (was toy factory fallback used?)
    ├ onboarding_errors: list[str] (all repairs/issues logged)
    └ inferred_assumptions: list[str] (optional: what was inferred)
    ↓
[return to frontend for user review]
    ↓
[if user confirms, feed to decision pipeline]
```

### Decision Pipeline (Existing, Unchanged)

```
FactoryConfig (onboarded) + situation_text
    ↓
[IntentAgent.run(...)]  ← LLM: extract intent + constraints
    ↓ output: ScenarioSpec + explanation string
[FuturesAgent.run(...)]  ← LLM: expand to 1–3 scenarios
    ↓ output: list[ScenarioSpec] + justification string
[FOR EACH scenario]
  ├ simulate(factory, spec)  ← Pure: EDD scheduler
  ├ compute_metrics(result)  ← Pure: lateness, bottleneck
  ↓
[BriefingAgent.run(...)]  ← LLM: markdown briefing
    ↓ output: briefing markdown (now includes onboarding context)
[return to frontend]
```

### Agent Responsibility Boundaries

- **OnboardingAgent**: Text → FactoryConfig (new in this sprint; LLM-backed in Phase 1).
- **normalize_factory**: FactoryConfig → FactoryConfig + track issues (pure function; owns fallback logic).
- **IntentAgent**: Situation text + factory → ScenarioSpec + constraints (existing; unchanged in this sprint).
- **FuturesAgent**: ScenarioSpec + factory → list[ScenarioSpec] (existing; unchanged).
- **Simulation & Metrics**: Pure computation, untouched by LLM.
- **BriefingAgent**: Metrics + context → markdown (existing; enhanced to reference onboarding state).

---

## 3. Data Contracts (Schemas & APIs)

### Core Data Models (Given)

#### FactoryConfig

```python
class FactoryConfig:
    machines: list[Machine]
    jobs: list[Job]

class Machine:
    id: str                 # e.g., "M1", "M_ASSEMBLY"
    name: str               # e.g., "Assembly Line"

class Job:
    id: str                 # e.g., "J1", "J_VIP_A"
    name: str               # e.g., "Widget A"
    steps: list[Step]       # ordered sequence
    due_time_hour: int      # integer hour, 0–24 (or beyond)

class Step:
    machine_id: str         # must exist in machines
    duration_hours: int     # must be >= 1
```

**State Invariants**:
- Each `job.steps` must have ≥ 1 step.
- Each `step.machine_id` must be a valid `machine.id`.
- `duration_hours` ≥ 1 (enforced by normalization).
- `due_time_hour` ≥ 0 (enforced by normalization).
- No parallel steps, no branching jobs.

#### ScenarioSpec & ScenarioMetrics (Given)

**ScenarioSpec**: Type-safe scenario definition (closed enum: BASELINE, RUSH_ARRIVES, M2_SLOWDOWN).
- `scenario_type: ScenarioType`
- `rush_job_id: Optional[str]` (valid only for RUSH_ARRIVES)
- `slowdown_factor: Optional[int]` (valid only for M2_SLOWDOWN; must be ≥ 2)

**ScenarioMetrics**: Aggregated performance metrics for one simulation.
- `makespan_hour: int` (total hours from start to last job completion)
- `job_lateness: dict[str, int]` (job ID → lateness hours, ≥ 0)
- `bottleneck_machine_id: str` (machine with highest utilization)
- `bottleneck_utilization: float` (utilization of bottleneck, 0.0–1.0)

### New: Onboarding Metadata

**OnboardingMeta** (in-memory structure; may become a Pydantic model):

```python
class OnboardingMeta:
    used_default_factory: bool
        # True if final FactoryConfig is the toy factory fallback (level 2 failure)
        # False if the config was onboarded and normalized (level 0 or 1)

    onboarding_errors: list[str]
        # Human-readable list of issues encountered during normalization:
        # - "Dropped step with invalid machine_id M9 for job J1"
        # - "Dropped job J_INVALID because it has no valid steps"
        # - "Clamped due_time_hour to 24 for job J2"
        # - "Normalization resulted in empty factory; using toy factory"

    inferred_assumptions: list[str]  # optional
        # What the LLM inferred when the text was ambiguous:
        # - "Inferred step duration 2 hours for 'about 2h' on M2"
        # - "Inferred due time 12h for 'by noon'"
        # - "Inferred machine ID M_DRILL from 'drilling machine'"
```

### HTTP APIs

#### POST /api/onboard (New)

**Request**:
```json
{
  "factory_description": "We have 3 machines: Assembly (1h capacity), Drill/Mill (bottleneck, 6h demand), and Pack (3h). We run 3 jobs daily: Widget A takes Assembly→Drill→Pack (1+3+1h), due at 12. Gadget B is Assembly→Drill→Pack (1+2+1h), due at 14. Part C starts on Drill→Pack (1+2h), due at 16."
}
```

**Response**:
```json
{
  "factory": {
    "machines": [
      {"id": "M1", "name": "Assembly"},
      {"id": "M2", "name": "Drill/Mill"},
      {"id": "M3", "name": "Pack"}
    ],
    "jobs": [
      {
        "id": "J1",
        "name": "Widget A",
        "steps": [
          {"machine_id": "M1", "duration_hours": 1},
          {"machine_id": "M2", "duration_hours": 3},
          {"machine_id": "M3", "duration_hours": 1}
        ],
        "due_time_hour": 12
      },
      {
        "id": "J2",
        "name": "Gadget B",
        "steps": [
          {"machine_id": "M1", "duration_hours": 1},
          {"machine_id": "M2", "duration_hours": 2},
          {"machine_id": "M3", "duration_hours": 1}
        ],
        "due_time_hour": 14
      },
      {
        "id": "J3",
        "name": "Part C",
        "steps": [
          {"machine_id": "M2", "duration_hours": 1},
          {"machine_id": "M3", "duration_hours": 2}
        ],
        "due_time_hour": 16
      }
    ]
  },
  "meta": {
    "used_default_factory": false,
    "onboarding_errors": [],
    "inferred_assumptions": [
      "Inferred step duration 1 hour for 'about 1h' on Assembly",
      "Inferred machine 'Drill/Mill' as M2"
    ]
  }
}
```

#### POST /api/simulate (Enhanced)

**Request** (unchanged signature):
```json
{
  "factory_description": "...",
  "situation_text": "We have a rush order for J2 today..."
}
```

**Response** (enhanced to include onboarding metadata):
```json
{
  "factory": { /* FactoryConfig */ },
  "specs": [ /* list[ScenarioSpec] */ ],
  "metrics": [ /* list[ScenarioMetrics] */ ],
  "briefing": "# Morning Briefing...",
  "meta": {
    "used_default_factory": false,
    "onboarding_errors": [],
    "inferred_assumptions": [...]
  }
}
```

**Behavior**:
- `/api/simulate` now internally calls `run_onboarded_pipeline(factory_description, situation_text)`.
- Onboarding happens first; if it succeeds (level 0 or 1), that factory drives the decision pipeline.
- If onboarding falls back (level 2), the toy factory is used, but `meta.used_default_factory = true`.
- The briefing may reference `meta.onboarding_errors` or `used_default_factory` to explain constraints.

---

## 4. Time Semantics & Limits

### 4.1 Time Units & Origin

- **Time unit**: Integer hours only. All durations and due times are expressed in hours; no fractional or sub-hour precision.
- **Time origin**: Start of day = hour 0 (00:00 / midnight).
- **Time horizon**: End of day = hour 24 (24:00 / next midnight). Makespan is computed within a 24-hour window; jobs may complete after hour 24 (overtime).

### 4.2 Time Interpretation Rules (LLM & OnboardingAgent)

When the LLM encounters time expressions in factory description, it **must** apply these rules:

| Expression | Context | Rule |
|---|---|---|
| "by 10am" | due time | 10 |
| "by noon" | due time | 12 |
| "by 3pm" | due time | 15 |
| "end of day" / "EOD" / "by close" | due time | 24 |
| "5 hours" | duration | 5 |
| "about 3 hours" | duration | 3 (round down: conservative) |
| "3–4 hours" | duration | 3 (take lower bound: conservative) |
| "quick" / "fast" | duration | 1 (minimum) |
| "lengthy" / "long" | duration | 3–4 (context-dependent; infer conservatively) |
| Missing / ambiguous | duration | **default 1** |
| Missing / ambiguous | due time | **default 24** |
| Negative (e.g., "-5") | any | **clamp to 0 (due time) or 1 (duration)** |

**Rationale for defaults**:
- Duration defaults to 1 hour (minimum viable job step).
- Due time defaults to 24 hours (end of day; jobs can complete after, but due time gives scheduler guidance).
- Negative times are clamped, not rejected, to prevent crashes.

**LLM Instruction**: "When duration or due time is ambiguous or missing, apply these defaults rather than inventing ranges, fractional hours, or probabilistic estimates."

### 4.3 Time Normalization (normalize_factory)

After OnboardingAgent produces a raw `FactoryConfig`, `normalize_factory` enforces time invariants deterministically.

#### Duration Normalization

For each `step.duration_hours`:
- **Rule**: If missing, not an integer, not present, or ≤ 0, set to 1.
- **Rationale**: Durations must be positive; 1 hour is the minimum viable work unit.

#### Due Time Normalization

For each `job.due_time_hour`:
- **Rule**: If missing, not an integer, not present, or < 0, set to 24.
- **Rationale**: Due times must be non-negative; 24 (EOD) is the safe default (job can complete after, but scheduler aims for on-time delivery).
- **Edge case**: If `due_time_hour > 24` (e.g., 30, meaning "very late"), keep as-is but note in logs. Job is considered very late if not complete by EOD.

### 4.4 Size Limits & Enforcement (Demo Constraints)

**Hard caps** (enforced by normalization; **demo constraints for this sprint**):

| Resource | Cap | Excess Behavior |
|---|---|---|
| Machines | 10 | Keep first 10 in text order; drop rest, log warning |
| Jobs | 15 | Keep first 15 in text order; drop rest, log warning |
| Steps per job | 10 | Keep first 10; drop rest, log warning |

**Rationale**: These caps prevent runaway parsing of very large or degenerate factory descriptions. They are **demo-scope constraints**, not architectural limits; future phases may increase or remove them.

---

## 5. Unstructured → Structured Philosophy

### 5.1 Interpretation vs. Repair (Two-Step Pattern)

This is **non-negotiable**: onboarding follows a strict two-step pattern. This design ensures the LLM can be creative and inferential while guaranteeing deterministic, safe output.

#### Step 1: Interpretation (OnboardingAgent; LLM-Backed)

- **Input**: Free-form factory description (could be messy, incomplete, ambiguous, several paragraphs, or SOP-style text).
- **Allowed behavior**:
  - Infer missing machine and job IDs from names and references.
  - Infer durations and due times using the rules in Section 4.2.
  - Map job routing (steps) to inferred machine IDs.
  - Create FactoryConfig with best-effort interpretation of user intent.
- **Output**: `FactoryConfig` object (raw; may have invalid references, bad durations, oversized counts, or violate invariants).
- **Guarantees**:
  - **Never crashes**: LLM is called with explicit constraints and fallback handling; exceptions are caught and logged.
  - **Does NOT validate**: The output is raw and unvetted. It may violate invariants (duplicate machine IDs, invalid references, negative durations, empty jobs).
  - **Deterministic at layer boundary**: Given the same input and same LLM call, produces the same output (within LLM stochasticity; use temperature 0 for reproducibility).

#### Step 2: Repair (normalize_factory; Pure Function, Deterministic)

- **Input**: `FactoryConfig` (raw; possibly invalid) from Step 1.
- **Process**: Pure function with no LLM, no I/O, no external calls. Enforces invariants:
  1. **Duration repair**: For each step, if `duration_hours` is missing, not int, or ≤ 0 → set to 1, log repair.
  2. **Due time repair**: For each job, if `due_time_hour` is missing, not int, or < 0 → set to 24, log repair.
  3. **Machine reference validation**: For each step, if `machine_id` not in valid machines → drop step, log.
  4. **Job emptiness check**: For each job, if no valid steps remain after reference cleanup → drop job, log.
  5. **Size caps**: If machines > 10, jobs > 15, or steps/job > 10 → truncate, keep first N in text order, log.
  6. **Fallback**: If machines or jobs is empty after all repairs → return toy factory + log.
- **Output**: Safe `FactoryConfig` (guaranteed valid).
  - All steps reference existing machines.
  - All durations ≥ 1.
  - All due times ≥ 0.
  - All jobs have ≥ 1 step.
  - Counts within caps.
- **Guarantee**: Result is always simulatable. No invariant violations possible.
- **No mutation**: Input `FactoryConfig` is never modified; always returns a new object.

**Why this pattern?**
- **Separation of concerns**: The LLM's job is inference (what the user probably meant); the pure function's job is enforcement (what we can safely simulate).
- **Testability**: normalize_factory is deterministic and can be tested exhaustively without mocking LLM calls.
- **Transparency**: Users see both what the LLM inferred (assumptions) and what normalization fixed (repairs).
- **Resilience**: Even if LLM hallucinations occur, the repair layer catches them and falls back gracefully.

### 5.2 Inference Envelope (Scope Boundary for OnboardingAgent)

The LLM's creativity is **strictly scoped** to ensure output stays within bounds that the repair layer can handle. The OnboardingAgent prompt must include this envelope explicitly.

#### Allowed Inferences (This Sprint)

- **Durations from qualitative descriptions** (per Section 4.2 rules):
  - "about 3 hours" → 3
  - "quick assembly" (no duration) → 1 (minimum)
  - "lengthy" or "slow" process → 3–4 (context-dependent; infer conservatively)
  - Missing duration → 1 (default)

- **Due times from temporal phrases** (per Section 4.2 rules):
  - "by 10am", "by noon", "by 3pm" → map to hour
  - "end of day", "EOD", "close of business" → 24
  - "very tight" (no explicit time) → 8–12 (aggressive deadline, infer 8)
  - Missing due time → 24 (default; end of day)

- **Machine IDs from names and context**:
  - Infer opaque IDs (e.g., "Assembly line" → M_ASSEMBLY or M1).
  - Use descriptor-based naming (M_DRILL, M_PACK) when possible; fall back to M1, M2, M3, ... in text order.
  - Consistency: same machine mentioned twice → same ID both times.

- **Job IDs from references and context**:
  - Infer opaque IDs (e.g., "Widget A" → J_WIDGET_A or J1, "Order #42" → J_42).
  - Explicit references (e.g., "J2", "job J2") → use J2 as-is.
  - Consistency: same job mentioned twice → same ID both times.

- **Job steps and routing**:
  - Infer step sequence from text order (e.g., "Widget A: Assembly → Drill → Pack").
  - Infer machine per step from context (e.g., "Drill" → look for machine with "drill" in name).
  - Do not reorder steps; preserve text order.

#### Forbidden Inferences (This Sprint; Demo Constraints)

- **Parallel steps or branching within a job**: "Job A splits into sub-jobs A1 and A2" → NOT allowed.
- **Multi-day or rolling schedules**: "Monday and Tuesday jobs" → NOT allowed.
- **Quantities, batch sizes, or material flow**: "50 units of Widget A" → NOT allowed.
- **Costs, labor, or resource pools**: "2 workers available", "cost $100/hr" → NOT allowed.
- **Setup times or machine reconfiguration**: "30min setup between jobs" → NOT allowed.
- **Machine parallelism or duplicate instances**: "M1 has 3 copies in parallel" → NOT allowed.
- **Non-integer durations**: Must round all durations to integers per Section 4.2.
- **Job dependencies beyond sequential steps**: "J2 must finish before J3 starts" → NOT allowed (only step sequence matters).
- **External constraints or constraints beyond machines**: "warehouse capacity", "labor limits" → NOT allowed.

**On encountering forbidden constructs**: The LLM should acknowledge them in a note or comment within the FactoryConfig output (for logging), but **must not** include them in the machine, job, or step definitions. The normalize_factory function will log the note but will not fail the entire onboarding; it will work with what's available.

### 5.3 Machine & Job Identity and Unknown References

#### Machine Identity

- Machine IDs are **opaque strings** (e.g., "M1", "M_ASSEMBLY", "DRILL_02").
- Once inferred by OnboardingAgent, a machine ID is fixed for the lifetime of that factory config.
- Same machine mentioned twice in factory description → OnboardingAgent must produce the same machine ID both times.
- Machine IDs are unique within a factory (no duplicates).
- **Normalization does not rename machines**: If the OnboardingAgent assigns M1, M2, M3, normalization preserves those IDs; it only drops or keeps machines as-is.

#### Job Identity

- Job IDs are **opaque strings** (e.g., "J1", "J_WIDGET_A", "ORDER_42").
- Once inferred by OnboardingAgent, a job ID is fixed for the lifetime of that factory config.
- Same job mentioned twice in factory description → OnboardingAgent must produce the same job ID both times.
- Job IDs are unique within a factory (no duplicates).
- **Normalization does not rename jobs**: If the OnboardingAgent assigns J1, J2, J3, normalization preserves those IDs; it only drops or keeps jobs as-is.

#### Unknown Job References in Situation Text

- The situation text (input to IntentAgent) may reference job IDs (e.g., "Rush order for J2", "Focus on Widget A").
- If a referenced job ID does not exist in the onboarded factory, the behavior is **read-only interpretation**:
  - The reference is NOT silently ignored; it is logged in the briefing or decision context as a note.
  - A scenario like RUSH_ARRIVES(rush_job_id="J_UNKNOWN") may be dropped by validation, or flagged in the briefing as infeasible.
  - **Do not create new jobs on-the-fly** during situation parsing; this would mutate the onboarded factory.
- **Explicit rule for this sprint**: Job IDs in situation text are treated as references to existing jobs. If not found, the scenario is either dropped or explicitly noted as "referenced job not found".

#### Size Caps & Truncation

- Machines are capped at 10; if more are inferred, keep the first 10 in text order.
- Jobs are capped at 15; if more are inferred, keep the first 15 in text order.
- Steps per job are capped at 10; if more are inferred, keep the first 10 per job.
- Log each truncation clearly: `"Capped machines at 10; dropped {names of dropped machines}"`.

### 5.4 Failure Ladder

Onboarding outcomes fall into three levels:

#### Level 0: OK
- **Condition**: OnboardingAgent produces a valid, complete `FactoryConfig`; `normalize_factory` makes no repairs.
- **Output**:
  - `used_default_factory = false`
  - `onboarding_errors = []` (empty list)
  - `inferred_assumptions` populated only if anything was inferred
- **User experience**: "Your factory was understood correctly."

#### Level 1: Degraded
- **Condition**: Normalization fixes some issues (repair durations, drop invalid steps, cap counts, etc.), **but** at least one valid job remains.
- **Output**:
  - `used_default_factory = false`
  - `onboarding_errors` = list of repair messages (e.g., "Dropped step with invalid machine_id M9", "Clamped due_time to 24", "Capped jobs at 15; dropped 2 jobs")
  - Factory is still non-empty and usable.
- **User experience**: "We understood most of your factory, but made some adjustments. See warnings."

#### Level 2: Fallback
- **Condition**: Normalization results in zero valid jobs or zero machines (factory is empty).
- **Output**:
  - `used_default_factory = true`
  - `onboarding_errors = ["Normalization resulted in empty factory; using toy factory fallback"]`
  - Factory is replaced with `build_toy_factory()` (3 machines, 3 jobs).
- **User experience**: "We couldn't parse your factory. Using a simple example to get started."

**Decision logic in `run_onboarded_pipeline`**:
```python
def run_onboarded_pipeline(factory_text, situation_text):
    # Step 1: Onboard
    raw_factory = OnboardingAgent().run(factory_text)

    # Step 2: Normalize
    safe_factory = normalize_factory(raw_factory)

    # Step 3: Determine failure level and populate meta
    meta = OnboardingMeta()
    toy_factory = build_toy_factory()

    if safe_factory is toy_factory or (len(safe_factory.machines) == 0 or len(safe_factory.jobs) == 0):
        meta.used_default_factory = true
        meta.onboarding_errors = ["Normalization resulted in empty factory; using toy factory fallback"]
        # level = FALLBACK (level 2)
    else:
        meta.used_default_factory = false
        # Check if any repairs were made (detect from normalization logs)
        if repairs_made:
            meta.onboarding_errors = [list of repair messages]
            # level = DEGRADED (level 1)
        else:
            meta.onboarding_errors = []
            # level = OK (level 0)

    # Step 4: Continue with decision pipeline using safe_factory
    # ...
```

---

## 6. Agent Behavior in the New Flow

### OnboardingAgent

**Role**: Interpret free-text factory description into a `FactoryConfig`.

**Signature**:
```python
def run(self, factory_text: str) -> FactoryConfig
```

**Input**:
- `factory_text`: Free-form user text describing machines, jobs, steps, due times, durations.

**Output**:
- `FactoryConfig` (best-effort; may have invalid references or bad values).

**LLM Call**:
- Uses `call_llm_json(prompt, FactoryConfig)` with strict schema validation.
- Prompt includes:
  - Time interpretation rules (by 10am → 10, etc.).
  - Inference envelope (what's allowed vs forbidden).
  - Example of well-formed output.
- **Fallback**: If LLM fails, returns `build_toy_factory()` (level 2 failure).

**Logging**:
- Log truncated input (first 200 chars).
- Log summary: "OnboardingAgent: produced factory with {n} machines, {m} jobs, {k} total steps".
- Log any LLM errors (timeout, parsing failure, schema mismatch).

### normalize_factory

**Role**: Repair and validate a `FactoryConfig` to ensure it's safe for simulation.

**Signature**:
```python
def normalize_factory(factory: FactoryConfig) -> FactoryConfig
```

**Input**:
- `factory`: `FactoryConfig` (possibly invalid).

**Output**:
- `FactoryConfig` (guaranteed valid for simulation). Repairs are logged internally.

**Repairs** (logged at DEBUG level for observability):

1. **Duration fixes**:
   - For each step: if `duration_hours` is missing, not int, or `<= 0`, set to 1 and log.

2. **Due time fixes**:
   - For each job: if `due_time_hour` is missing, not int, or `< 0`, set to 24 and log.

3. **Invalid machine references**:
   - Compute set of valid machine IDs.
   - For each step: if `step.machine_id` not in valid IDs, drop the step and log.

4. **Empty jobs**:
   - Drop any job with zero valid steps (after reference cleanup) and log.

5. **Size caps**:
   - If `len(machines) > 10` (MAX_MACHINES): keep first 10, drop rest, log.
   - If `len(jobs) > 15` (MAX_JOBS): keep first 15, drop rest, log.
   - If any `len(job.steps) > 10` (MAX_STEPS_PER_JOB): keep first 10, drop rest, log.

6. **Fallback**:
   - If after all repairs `machines` or `jobs` is empty, return `build_toy_factory()` and log warning.

**No mutations**: Input is not modified; always return a new `FactoryConfig`.

### IntentAgent & FuturesAgent

**No changes in this sprint**.

- `IntentAgent.run(situation_text, factory)` still produces `ScenarioSpec + explanation_string`.
- `FuturesAgent.run(spec, factory)` still produces `list[ScenarioSpec] + justification_string`.
- Both now receive the **onboarded factory** instead of toy factory, enabling more specific scenario generation.

### BriefingAgent

**Enhanced (but not redesigned)**.

**New context passed**:
- `meta.used_default_factory`: If true, briefing should note "Based on a simplified example factory" or similar.
- `meta.onboarding_errors`: If non-empty, briefing may reference "Your factory was partially understood; see configuration warnings."

**Prompt enhancement** (minor):
- Include a note: "If the factory was onboarded from user text and warnings were noted, consider acknowledging them."

**Output**: Same markdown briefing, but may include a caveat section if onboarding was degraded or fallback.

### run_onboarded_pipeline

**Orchestrator function** (central coordinator).

**Signature**:
```python
def run_onboarded_pipeline(
    factory_description: str,
    situation_text: str
) -> dict
```

**Steps**:

1. **Onboard**:
   ```python
   raw_factory = OnboardingAgent().run(factory_description)
   log: f"OnboardingAgent produced {len(raw_factory.machines)} machines, {len(raw_factory.jobs)} jobs"
   ```

2. **Normalize**:
   ```python
   safe_factory = normalize_factory(raw_factory)
   log: f"normalize_factory complete; factory has {len(safe_factory.machines)} machines, {len(safe_factory.jobs)} jobs"
   ```

3. **Determine failure level** and populate `OnboardingMeta`:
   ```python
   toy_factory = build_toy_factory()
   used_default = (safe_factory IDs match toy_factory IDs)

   meta = OnboardingMeta(
       used_default_factory=used_default,
       onboarding_errors=[...],  # from logs during normalization
       inferred_assumptions=[...]  # populated by OnboardingAgent if tracked
   )
   ```

4. **Decision pipeline** (using `safe_factory`):
   ```python
   intent_spec, intent_explain = IntentAgent().run(situation_text, safe_factory)
   scenario_specs, scenario_justify = FuturesAgent().run(intent_spec, safe_factory)

   for spec in scenario_specs:
       result = simulate(safe_factory, spec)
       metrics = compute_metrics(safe_factory, result)

   briefing = BriefingAgent().run(
       primary_metrics=metrics[0],
       all_metrics=metrics,
       context=f"{intent_explain}\n{scenario_justify}",
       onboarding_meta=meta
   )
   ```

5. **Return**:
   ```python
   return {
       "factory": safe_factory,
       "specs": scenario_specs,
       "metrics": [computed metrics],
       "briefing": briefing_markdown,
       "meta": meta
   }
   ```

**Logging**:
- Mark start with timestamp and input summary.
- Log each step completion with status.
- Log final factory: "{n} machines, {m} jobs, {k} total steps; {p} scenarios generated".
- Log any fallback: "Fallback to toy factory triggered".
- Mark end with total elapsed time.

---

## 7. Frontend UX Contract

### State Model

The frontend has two main states:

1. **Onboarding State**: Waiting for user factory description; display factory summary + warnings.
2. **Simulation State**: Waiting for situation text; display scenarios, metrics, briefing.

### UI Panels & Interactions

#### Initial State

**Layout**:
- **Left panel**: Two textareas
  - Textarea 1: "Describe your factory" (placeholder: "E.g., 3 machines: Assembly (1h), Drill (bottleneck, 6h demand), Pack (3h)...")
  - Textarea 2: "What's your situation today?" (placeholder: "E.g., Rush order for J2, or M2 maintenance from 8–14h...")
  - Button "Onboard Factory" (enabled)
  - Button "Run Scenarios" (disabled until onboarding succeeds)

- **Right panel**: Empty, waiting for onboarding

**User action**: Enter factory description, click "Onboard Factory"

#### After Onboarding (Level 0 or 1)

**API call**: POST /api/onboard with `{ factory_description: "..." }`

**Response**:
```json
{
  "factory": { machines, jobs },
  "meta": { used_default_factory, onboarding_errors, inferred_assumptions }
}
```

**Right panel displays**:
- **"Factory Configuration"** header
- **Machines list**:
  ```
  Machine: M1 (Assembly)
  Machine: M2 (Drill/Mill)
  Machine: M3 (Pack)
  ```
- **Jobs list**:
  ```
  Job J1 (Widget A), due at hour 12:
    Step 1: M1 for 1h
    Step 2: M2 for 3h
    Step 3: M3 for 1h
  ...
  ```
- **Warnings (if any)** (yellow/orange banner):
  ```
  ⚠️ Configuration Warnings:
  - Dropped step with invalid machine_id M9 for job J1
  - Clamped due_time_hour to 24 for job J3
  ```

**User action**:
- Review factory + warnings
- Either click "Run Scenarios" to continue (or edit textarea and click "Onboard Factory" again to retry)

#### After Onboarding (Level 2 Fallback)

**Response**:
```json
{
  "factory": { toy factory },
  "meta": { used_default_factory: true, onboarding_errors: [...] }
}
```

**Right panel displays**:
- **Fallback notice** (large, red banner):
  ```
  ⚠️ We couldn't fully parse your factory description.
  Using a simple example to get started.
  Error: Normalization resulted in empty factory; falling back to toy factory.
  ```
- **Toy factory displayed** (3 machines, 3 jobs as usual)
- Button "Run Scenarios" still enabled (user can proceed or retry)

#### After Running Scenarios

**API call**: POST /api/simulate with `{ factory_description: "...", situation_text: "..." }`

**Response**: Full result with factory, specs, metrics, briefing, meta.

**Display** (reuse existing panels):
- **Scenario list**: Baseline, Rush J2, M2 Slowdown (or whatever FuturesAgent generated)
- **Metrics table**: Makespan, job lateness by scenario, bottleneck machine, utilization
- **Briefing markdown**: Rendered as-is
- **Reference to onboarding** (if `meta.used_default_factory` true or `meta.onboarding_errors` non-empty):
  - Briefing may include: "Note: factory was partially understood; see configuration warnings above."
  - Or banner: "This briefing is based on a simplified example factory."

### Loading & Error States

**During onboarding**:
- Disable "Onboard Factory" button, show spinner.
- Right panel shows "Loading...".

**During simulation**:
- Disable "Run Scenarios" button, show spinner.
- Scenario list, metrics, briefing areas show "Loading...".

**On HTTP error**:
- Display error banner (no raw tracebacks):
  ```
  ❌ Error: Failed to process your factory description.
  (Reason: Backend unavailable or invalid input.)
  Please try again or check your text.
  ```
- Buttons remain clickable to retry.

**On schema validation error** (unexpected):
- Display: "Unexpected error: invalid response format. Please try again."
- Log to console for debugging.

### Accessibility & Clarity

- **All user-facing messages are plain English**, no jargon.
- **Warnings are visually distinct** (color, icon, indentation).
- **Buttons are clearly labeled** and state is obvious (disabled/enabled, loading).
- **Latency**: Expect 3–5 seconds for onboarding + simulation; show spinner for all intervals > 0.5s.

---

## 8. Implementation Phases

### Phase 0: /api/onboard Skeleton & Types

**Scope**:
- Add `OnboardingMeta` pydantic model (used_default_factory, onboarding_errors, inferred_assumptions).
- Implement POST `/api/onboard` endpoint (stub OnboardingAgent always returns toy factory).
- Wire up `normalize_factory` in the endpoint.
- Return `{ factory, meta }` contract.
- Add minimal tests for request/response contracts and normalization behavior.

**Out of scope**:
- Real LLM-backed OnboardingAgent (phase 1).
- Frontend integration (phase 2).

**Risks**:
- HTTP contract confusion: ensure `/api/onboard` and `/api/simulate` both handle onboarding correctly.
- Pydantic serialization: verify enums and complex types serialize cleanly.

**Definition of done**:
- `/api/onboard` accepts `{ factory_description }` and returns `{ factory, meta }`.
- Stub OnboardingAgent always returns toy factory.
- normalize_factory is tested: levels 0, 1, 2 all work.
- One manual test: curl POST /api/onboard with factory text, verify schema.

---

### Phase 1: LLM-Backed OnboardingAgent

**Scope**:
- Implement real OnboardingAgent using `call_llm_json(prompt, FactoryConfig)`.
- Craft prompt:
  - Time interpretation rules (by 10am → 10, etc.).
  - Inference envelope (what's allowed/forbidden).
  - Output schema (FactoryConfig with machines, jobs, steps).
  - Example of well-formed factory description + output.
- Error handling: OnboardingAgent.run never throws; catches exceptions and returns toy factory (with log).
- Test with mocked LLM: verify behavior on clean inputs, messy inputs, edge cases.

**Out of scope**:
- Fine-tuning prompts based on real factory data (future enhancement).
- Support for multiple languages.

**Risks**:
- LLM hallucination: agent invents unsupported attributes (quantities, costs, branches). Mitigate with strict prompt and schema.
- Token limits: very long factory descriptions. Mitigate by truncating input or rejecting > 5000 chars.
- Schema mismatch: LLM returns partial or malformed JSON. Mitigate with strict schema + error handling.

**Definition of done**:
- OnboardingAgent.run(factory_text) calls LLM and returns FactoryConfig.
- Fallback to toy factory on any error.
- 5 test cases (clean, messy, edge cases) with mocked LLM; all pass.
- One integration test with real LLM (optional, marked slow).

---

### Phase 2: Frontend Two-Step Flow

**Scope**:
- Refactor frontend to separate "Onboard Factory" and "Run Scenarios" flows.
- Add `/api/onboard` call on "Onboard Factory" button.
- Display factory summary + warnings (machines, jobs, steps, onboarding errors).
- Enable "Run Scenarios" only after successful onboarding.
- Refactor `/api/simulate` to accept pre-onboarded factory or run onboarding internally (keep API backward-compatible).
- Add loading spinners, error banners.
- Preserve existing scenario visualization (metrics table, briefing markdown).

**Out of scope**:
- Editable factory UI (users can only edit textarea and re-onboard).
- Drag-and-drop or visual factory builder.

**Risks**:
- State management: frontend must track onboarded factory between calls. Use React state (useState) or context.
- Latency: onboarding + simulation can take 6–10s total. Mitigate with clear spinner + messaging.
- Backward compatibility: ensure old `/api/simulate` calls still work if factory_description is provided.

**Definition of done**:
- Frontend has two textareas + two buttons (Onboard, Run Scenarios).
- Click "Onboard" → calls POST /api/onboard → displays factory summary + warnings.
- Click "Run Scenarios" → calls POST /api/simulate with situation text → displays metrics + briefing.
- All UX states work (loading, errors, fallback).
- 3 manual tests: clean factory, messy factory, fallback factory.

---

### Phase 3: Adversarial Prompt Set & Manual Eval

**Scope**:
- Define 8–10 canonical factory descriptions (clean, messy, SOP-like, edge cases).
- Run each through onboarding pipeline.
- Verify behavior:
  - Clean → Level 0 (no errors).
  - Messy → Level 1 (some repairs, but factory non-empty).
  - SOP-like → Level 0 or 1 depending on ID format.
  - Edge cases → Level 2 fallback (or graceful handling).
- Document observations; adjust prompts minimally if needed.
- Create test cases from these scenarios.

**Out of scope**:
- Tuning LLM temperature, max_tokens, etc. (use defaults).
- Testing against proprietary/confidential real factory data.

**Risks**:
- LLM consistency: same prompt may produce different outputs on different calls. Mitigate by testing 3× each and accepting majority outcome.
- Time cost: 8–10 scenarios × 3 runs × 2–3 seconds = 1–1.5 minutes per prompt iteration. Budget accordingly.

**Definition of done**:
- 8–10 test cases defined and documented (ADVERSARIAL_PROMPTS.md or similar).
- Each case run through pipeline; outcome logged (level, errors, final factory).
- Briefing generated for each case; reviewed for sanity.
- No unexpected crashes or hallucinations.
- Prompt adjusted ≤2 times if needed (document rationale).

---

## 9. Quality & Success Criteria

### Functional

- **Canonical factory texts parse correctly**:
  - N=8 well-formed factory descriptions → all produce valid FactoryConfig with 0 errors (level 0).
  - M=4 ambiguous/messy descriptions → all produce valid FactoryConfig with ≤5 errors each (level 1).
  - K=2 adversarial descriptions (100+ machines, circular routing) → all degrade to toy factory with clear error message (level 2).

- **Scenarios generated from onboarded factories are distinct**:
  - Same situation text + onboarded factory → generates 1–3 scenario specs (not always identical, but deterministic given same factory).
  - Briefing varies by scenario and factory configuration.

- **System never crashes on user text**:
  - Fuzz test: 100 random strings, each ≤500 chars. None cause unhandled exceptions.
  - Worst case: fallback to toy factory + clear warning.

### Robustness

- **Invalid or adversarial input**:
  - Negative due times → clamped to 0 or 24, no error.
  - Missing durations → default to 1, logged.
  - Unknown machine IDs → steps dropped, job still valid if ≥1 step remains.
  - 1000 jobs in input → capped at 15, logged.

- **Simulation invariants preserved**:
  - After onboarding + normalization, every job has ≥1 valid step.
  - Every step references a valid machine.
  - All durations and due times are integers ≥0.

- **No data mutation**:
  - Input FactoryConfig is never modified; all functions return new objects.
  - Same factory + spec → deterministic simulation result (run 10×, all identical).

### Observability

- **Logging captures the onboarding journey**:
  - OnboardingAgent logs: "OnboardingAgent: produced factory with {n} machines, {m} jobs, {k} total steps".
  - normalize_factory logs: "Dropped step with invalid machine_id X for job Y" (one per fix).
  - Fallback logs: "Normalization resulted in empty factory; falling back to toy factory".
  - Total elapsed time from factory description to briefing markdown (target: <10s).

- **OnboardingMeta tracks all decisions**:
  - `used_default_factory` tells whether fallback occurred.
  - `onboarding_errors` lists all repairs (for UI display).
  - `inferred_assumptions` (optional) lists what was inferred (for transparency).

- **BriefingAgent references onboarding state** (in output markdown):
  - If `used_default_factory = true`: "Based on a simplified example factory."
  - If `onboarding_errors` non-empty: "Your factory was partially understood; key adjustments: [list]."

### Adversarial & Robustness Testing

This subsection defines a suite of adversarial and messy factory descriptions that the onboarding system must handle **without crashing** and with **clear, human-readable error messages**.

#### Canonical Adversarial Test Cases

1. **Overly long SOP-style text** (>2000 chars):
   - Input: A verbose manufacturing SOP with detailed procedures, regulatory notes, footnotes, etc.
   - Expected outcome: OnboardingAgent parses core info (machines, jobs); ignores noise.
   - Failure mode: Level 0 or 1; fallback is Level 2 if no valid jobs extracted.

2. **Contradictory descriptions**:
   - Input: "Job A: Assembly (1h) → Drill (2h), due 12. Job A: Assembly (3h), due 14."
   - Expected outcome: OnboardingAgent resolves as best as it can (e.g., picks first mention or merges).
   - Failure mode: Level 1 (degraded; contradictions logged) or Level 0 if consistent resolution possible.

3. **Missing machines with invalid references**:
   - Input: "We have Assembly and Packaging. Jobs: Widget (Assembly → Drill → Packaging, due 12)."
   - Expected outcome: OnboardingAgent infers Drill from context; normalize_factory drops Drill step if it can't match, job still has Assembly + Packaging.
   - Failure mode: Level 1 (step dropped); not Level 2 unless all steps are invalid.

4. **Random noise & irrelevant text**:
   - Input: "asdf qwerty 1234 --- We have a factory with 3 machines: Assembly, Drill, Pack. 3 jobs: J1 due 12, J2 due 14, J3 due 16. --- xyzabc nonsense."
   - Expected outcome: OnboardingAgent filters noise, extracts structured data.
   - Failure mode: Level 0 or 1; worst case Level 2 fallback with clear "Could not parse" error.

5. **Half-complete / TBD factories**:
   - Input: "We have assembly (1h) and packaging (2h). Drilling TBD. Jobs: Widget (Assembly → Drill → Pack), Gadget (Assembly → Pack)."
   - Expected outcome: OnboardingAgent works with Assembly and Pack; Drill is either inferred as a placeholder or dropped.
   - Failure mode: Level 1 (Drill step dropped for Widget; Gadget still has 2 steps).

6. **Duplicate or conflicting job IDs**:
   - Input: "Job J1: Assembly (1h), Drill (2h), due 10. Job J1: Packaging (1h), due 12."
   - Expected outcome: OnboardingAgent resolves to single J1 (merge or pick first).
   - Failure mode: Level 1 (merged or first-mention wins); no crash.

7. **Extremely large counts** (100 machines, 1000 jobs):
   - Input: "We have machines M1, M2, ..., M100. Jobs: J1, J2, ..., J1000. All jobs go M1 → M2 → ... → M50."
   - Expected outcome: OnboardingAgent produces raw config; normalize_factory caps at 10 machines, 15 jobs.
   - Failure mode: Level 1 (capped and logged); not a crash.

8. **Negative, zero, and fractional durations/due times**:
   - Input: "Machine M1. Job J1: M1 for -2 hours, due -5. Job J2: M1 for 0 hours, due 2.5. Job J3: M1 for 3 hours, due 30."
   - Expected outcome: normalize_factory repairs: J1 duration → 1, due → 0; J2 duration → 1, due → 2; J3 due → 30 (allowed, noted).
   - Failure mode: Level 1 (repairs logged); no crash.

9. **Circular or impossible routing**:
   - Input: "Job J1: A → B → A → B (circular step sequence)."
   - Expected outcome: OnboardingAgent produces it; normalize_factory keeps as-is (no validation of routing logic; only checks references exist).
   - Failure mode: Level 0 or 1; simulation may detect infeasibility, but onboarding succeeds.

10. **Missing or empty factory description**:
    - Input: "" or "..." or just punctuation.
    - Expected outcome: OnboardingAgent returns empty or minimal config; normalize_factory falls back.
    - Failure mode: Level 2 (fallback to toy factory); clear "Empty description" error.

#### Expected Behavior Across All Cases

- **System never throws an unhandled exception**: All errors are caught, logged, and reported in `onboarding_errors`.
- **Always returns OnboardingMeta**: Either with a valid factory (Level 0/1) or toy factory + `used_default_factory=true` (Level 2).
- **Error messages are human-readable**: E.g., "Dropped step referencing unknown machine 'CNC' for job J1", not raw stack traces.
- **Worst case is graceful fallback**: If no valid factory can be constructed, user sees toy factory with clear explanation.

#### Testing Strategy

- Define these 10 cases in a test data file or test suite.
- For each case, run through the full onboarding pipeline (OnboardingAgent → normalize_factory → meta).
- Verify:
  - No exceptions occur.
  - Output level (0, 1, or 2) is reasonable.
  - onboarding_errors are informative.
  - Final factory is simulatable.
- Document actual outcomes vs expected; note if LLM behavior differs across runs.
- Use these cases to validate OnboardingAgent prompt tuning (Phase 1).

### Demo-Readiness

You can run these canonical scenarios end-to-end and explain behavior to a CTO:

1. **Clean normal day**:
   - Factory: 3 machines, 3 jobs, standard routing.
   - Situation: "Normal day, no rush."
   - Expected: BASELINE scenario, all jobs on-time, briefing is straightforward.

2. **Rush order**:
   - Factory: Same as above.
   - Situation: "Rush order for J2, due at 12 instead of 14."
   - Expected: RUSH_ARRIVES scenario, J1 likely delayed, M2 is bottleneck.
   - Briefing: Explains risk, suggests action.

3. **Machine maintenance**:
   - Factory: Same as above.
   - Situation: "M2 maintenance 8–14h; runs at 2x speed."
   - Expected: M2_SLOWDOWN scenario, multiple jobs delayed.
   - Briefing: Quantifies impact, recommends job sequencing.

4. **Impossible constraints**:
   - Factory: 3 machines, 3 jobs.
   - Situation: "All jobs must finish by 6am; no delays allowed."
   - Expected: Briefing acknowledges constraint is infeasible; recommends realistic alternative.
   - (May involve BriefingAgent saying "This configuration makes it impossible to meet your goal; here's the best we can do.")

5. **Messy factory description**:
   - Factory: "We have some machines: Assembly is fast, Drill is slow, Pack is normal. Jobs take about 1–3 hours each on different machines, due various times."
   - Expected: OnboardingAgent infers structure; normalize_factory repairs missing/bad values; level 1 outcome with warnings.
   - Briefing: References the onboarded factory structure and explains what was inferred.

---

## 10. Non-Goals & Out of Scope

- **Multi-day schedules**: All times are integer hours in a single 24h day.
- **Quantities, costs, material flow**: Only job routing and duration matter.
- **Alternative scheduling heuristics**: EDD (Earliest Due Date) is the only scheduler; no SPT, LPT, or constraint programming.
- **Stochastic durations or Monte Carlo**: All durations are deterministic.
- **Visual factory builder**: Users enter free text; UI displays summaries, not interactive diagrams.
- **Persistent storage**: No database; all state is request-scoped.
- **Authentication & authorization**: Single-user demo; no user accounts.
- **Multi-language support**: English only.
- **Export to PDF, Gantt charts, or other formats**: Markdown briefing is the only output.

---

## 11. Success Checklist

By the end of this sprint:

- [ ] OnboardingAgent (stub in phase 0, LLM-backed in phase 1) implemented.
- [ ] normalize_factory tested for all three failure levels (OK, degraded, fallback).
- [ ] POST /api/onboard endpoint live and returns `{ factory, meta }`.
- [ ] POST /api/simulate updated to call run_onboarded_pipeline.
- [ ] Frontend refactored with two-step flow: Onboard → Run Scenarios.
- [ ] Factory summary + warnings displayed in UI.
- [ ] 8–10 canonical factory texts tested end-to-end.
- [ ] No unhandled exceptions on user text.
- [ ] Briefing references onboarding state (used_default_factory, errors).
- [ ] Logging shows full onboarding journey (agent decisions, repairs, fallback).
- [ ] CTO can review spec, approve implementation, and sign off on quality.

---

## 12. Example Walkthrough

### User Input

**Textarea 1** (Factory description):
```
We have three production machines:
1. Assembly line (M1) can do about 1 hour of work per job
2. Drilling and milling (M2) is our bottleneck, takes 2-4 hours per job
3. Packing and shipping (M3) takes 1-3 hours

We have three jobs to schedule:
- Widget A: goes through Assembly (1h) → Drill/Mill (3h) → Packing (1h), due by 12 noon
- Gadget B: Assembly (1h) → Drill/Mill (2h) → Packing (1h), due at 2pm
- Part C: Drill/Mill (1h) → Packing (2h), no specific due time but ASAP
```

**Textarea 2** (Situation):
```
We just got a rush order. Gadget B is now high priority and must be done by noon.
Also, our Drill/Mill machine M2 has a maintenance window 10am-2pm where it runs at half speed.
What should we expect?
```

### Onboarding Flow (Phase 2+)

1. **Click "Onboard Factory"** → POST /api/onboard
2. **OnboardingAgent.run()**:
   - Parses description.
   - Infers: M1, M2, M3 (machine IDs), J1, J2, J3 (job IDs).
   - Maps durations: "about 1 hour" → 1, "2-4 hours" → 2 (lower bound), etc.
   - Maps due times: "12 noon" → 12, "2pm" → 14, "ASAP" (missing) → 24.
   - Produces FactoryConfig (raw).

3. **normalize_factory()**:
   - Validates all step machine IDs exist.
   - Validates all durations ≥ 1.
   - Validates all due times ≥ 0.
   - No repairs needed; factory is valid.
   - Returns factory — level 0.

4. **Frontend displays**:
   ```
   ✓ Factory Configuration

   Machines (3):
   - M1: Assembly line
   - M2: Drilling and milling
   - M3: Packing and shipping

   Jobs (3):
   - J1 (Widget A), due 12h
     Step 1: M1 for 1h
     Step 2: M2 for 3h
     Step 3: M3 for 1h
   - J2 (Gadget B), due 14h
     Step 1: M1 for 1h
     Step 2: M2 for 2h
     Step 3: M3 for 1h
   - J3 (Part C), due 24h
     Step 1: M2 for 1h
     Step 2: M3 for 2h

   No warnings.
   ```

5. **Click "Run Scenarios"** → POST /api/simulate

6. **IntentAgent.run(situation_text, factory)**:
   - Parses: "rush order", "Gadget B now high priority", "due by noon".
   - But "due by noon" and "Gadget B is due at 14h" conflict.
   - Agent resolves: Interpret as "rush Gadget B, tighten due time to 12h".
   - Also detects: "M2 maintenance 10am-2pm at half speed" → M2_SLOWDOWN scenario.
   - Returns: ScenarioSpec(RUSH_ARRIVES, rush_job_id="J2", ...), explanation.

7. **FuturesAgent.run(spec, factory)**:
   - Expands RUSH_ARRIVES + M2_SLOWDOWN into 3 scenarios:
     1. BASELINE (control)
     2. RUSH_ARRIVES with J2 tightened to 12h
     3. M2_SLOWDOWN with 2x slowdown 10–14h
   - Returns: [spec1, spec2, spec3], justification.

8. **Simulate & metrics** for each scenario (pure computation).

9. **BriefingAgent.run()** with all metrics + context:
   - Generates markdown briefing.
   - Notes: "Your factory was understood correctly from your description."
   - Highlights risks: J1 delayed in RUSH_ARRIVES, all jobs delayed in M2_SLOWDOWN.
   - Recommends: "Start J1 immediately; accept 2–3h delay on Widget A if rush J2 is critical."

10. **Frontend displays**:
    ```
    Scenarios (3):
    - Baseline: makespan 5h, M2 bottleneck 85%
    - Rush J2: makespan 6h, J1 delayed 4h
    - M2 Slowdown: makespan 7h, J1 & J2 both delayed 2–3h

    [Briefing markdown with risks and actions]
    ```

---

## 13. Future Evolution & Extensibility (Out of Scope for This Sprint)

This specification describes **Option A: a sane, scoped demo** for an onboarding sprint, not a comprehensive production system. The architecture is intentionally designed to scale and generalize. This section sketches how this design evolves.

### Richer Factory Models

**Current sprint**:
- Single-day, integer-hour horizons.
- Linear job routing (no branching, parallel steps, or optional routes).
- Binary machine states (idle or busy).

**Future directions**:
- **Multi-day and rolling schedules**: Time horizon expands to days/weeks. `due_time_hour` becomes `due_time: datetime`. `duration_hours` becomes `duration: Duration` with sub-hour precision.
- **Parallel and conditional routing**: Jobs may have multiple independent sub-routes (e.g., "assemble 2 subassemblies in parallel, then final assembly"). Represented as DAGs instead of linear step sequences.
- **Machine pools and batching**: Machines can have multiple instances or queues. Jobs can specify batch sizes.
- **Material flow and inventory**: Track material movement between machines, storage constraints, lead times.

### More Scenario Types & Constraints

**Current sprint**:
- BASELINE, RUSH_ARRIVES, M2_SLOWDOWN (hardcoded).

**Future directions**:
- **Parameterized scenarios**: User specifies "rush order with 20% due-time reduction", "machine X at 50% efficiency", "material shortage for component Y".
- **Multi-factor trade-offs**: Scenarios that vary labor, shift schedules, overtime policies.
- **Constraint programming integration**: Optimization solvers (CPLEX, OR-Tools) instead of EDD heuristic.

### More Sophisticated Interpretation

**Current sprint**:
- OnboardingAgent is a basic LLM-to-JSON transformer.

**Future directions**:
- **Multi-turn refinement**: User provides factory, LLM asks clarifying questions, system refines config.
- **Semantic understanding**: NLP for implicit constraints ("Friday jobs have different priority").
- **Historical learning**: System learns from past factory descriptions and decisions.

### Editable & Versioned Factories

**Current sprint**:
- UI is read-only after onboarding; users re-input text to make changes.

**Future directions**:
- **Grid-based editors**: Visual machines × jobs table; users add/remove/edit directly.
- **Version control**: Factory configs are versioned (Git-like).
- **Simulation history**: Trace every scenario + result; annotate with decisions made.

### Multi-Factory, Shifts, and Networks

**Current sprint**:
- Single factory, single shift (one 24h day).

**Future directions**:
- **Multiple factories/lines**: Intra-factory routing and transport delays.
- **Shift scheduling**: Different crews, shift lengths, break times.
- **Supply chain network**: Upstream suppliers, downstream customers, inter-factory dependencies.

### Design Invariants (Preserved Across Evolution)

The following principles remain stable:

1. **Unstructured → Structured pipeline**: Free-text input always feeds through interpretation + repair, never directly to simulation.
2. **Pure simulation layer**: Core scheduling logic is deterministic and LLM-free; reproducible and testable.
3. **Clear contracts**: APIs define explicit input/output schemas; changes are backward-compatible or version-gated.
4. **Graceful degradation**: System never crashes on user input; worst case is fallback + clear warning.
5. **Transparency**: Users see what the system inferred and repaired; no hidden assumptions.

---

## Changelog

### Changes in This Revision

1. **Alignment with Actual Implementation**:
   - Updated `normalize_factory` signature to return only `FactoryConfig` (not tuple with warnings).
   - Removed promise of `results` key in `/api/simulate` response; actual pipeline doesn't return it.
   - Clarified that `OnboardingMeta` is an in-memory structure (not yet a formal Pydantic model in all code paths).
   - Updated endpoint description: `/api/onboard` is new in this sprint; `/api/simulate` is enhanced.

2. **Consolidated Time & Size Semantics**:
   - Merged Section 4 (Time Semantics & Limits) into a single cohesive 4-part section with explicit subsections: units/origin, interpretation rules, normalization, size limits.
   - Removed scattered time definitions and restatements; kept one canonical table + one set of repair rules.
   - Made demo-vs-future distinction explicit: all size caps (10 machines, 15 jobs, 10 steps per job) and single-day horizon are labeled as **demo constraints**.

3. **Deepened Unstructured → Structured Philosophy**:
   - Reorganized Section 5 (previously Section 3) into 5.1–5.4 with clearer subsection boundaries.
   - **5.1**: Two-step pattern (Interpretation + Repair) with explicit guarantees, rationale, and decision logic.
   - **5.2**: Separated **Allowed** from **Forbidden** inferences; added explicit guidance on handling forbidden constructs.
   - **5.3** (new): Dedicated section on machine & job identity, consistency, unknown references, and size truncation.
   - **5.4**: Failure ladder with clearer level definitions and decision pseudocode.

4. **Tightened Agent Behavior**:
   - **OnboardingAgent**: Clarified fallback behavior (returns toy factory on any error), not a validation layer.
   - **normalize_factory**: Emphasized that all repairs are logged internally; function returns only the safe factory.
   - **BriefingAgent**: Minor enhancement; passes onboarding metadata for context, not a major redesign.
   - **run_onboarded_pipeline**: Spelled out exact steps, logging strategy, and return dict structure.

5. **Comprehensive Adversarial Testing Section**:
   - Added Section 9.1 (Adversarial & Robustness Testing) with 10 canonical test cases covering: long text, contradictions, missing machines, noise, incomplete factories, duplicate IDs, large counts, edge-case time values, circular routing, empty descriptions.
   - Defined expected outcomes for each case (Level 0/1/2 failure modes).
   - Emphasized: system never crashes; error messages are human-readable.

6. **Cleaner Future Evolution**:
   - Added Section 13 (Future Evolution & Extensibility) as a distinct section, clearly marked as **out of scope**.
   - Sketched richer factory models (DAGs, multi-day, batching), more scenario types, smarter interpretation, editable UIs, networks.
   - Listed design invariants that remain stable across evolution.
   - Reduced sprawl by avoiding "wishlist" content in main sections.

7. **Minor Clarifications**:
   - Softened language around demo constraints; clarified they are intentional scoping, not limitations of the design.
   - Updated HTTP API sections: separated request/response JSON; removed ambiguity about which endpoint does what.
   - Added cross-references and section pointers to avoid redundancy.
   - Improved consistency of terminology (onboarding_errors, inferred_assumptions, used_default_factory).

### Key Tensions Resolved

- **Results in /api/simulate response**: The spec originally promised a `results` key; actual implementation doesn't return `SimulationResult` objects. Spec now matches implementation (only `metrics` returned).
- **normalize_factory return type**: Spec promised `(FactoryConfig, warnings)` tuple; implementation returns only `FactoryConfig` with internal logging. Spec now reflects reality.
- **OnboardingAgent phase 0 vs phase 1**: Spec now clearly separates stub behavior (phase 0: always returns toy factory) from LLM-backed behavior (phase 1: real interpretation).
- **Demo constraints clarity**: Spec now explicitly marks size caps and single-day horizon as **demo constraints**, reducing confusion about architectural vs. demo-only limits.
- **Failure ladder implementation**: Spec now includes pseudocode decision logic in run_onboarded_pipeline, clarifying how used_default_factory is computed.

### Outcome

The specification is now **tighter, more precise, and aligned with actual implementation**. It remains **readable by humans and LLMs**, with clear sections, minimal repetition, and explicit contracts. A senior engineer can skim it and see the architecture; a junior engineer (or LLM) can implement from it without ambiguity. A CTO can verify that LLM scope is bounded, failure modes are graceful, and contracts are non-negotiable.
