# Factory Simulator: Onboarding + Minimal UI Sprint

**Status**: Specification for next sprint (< 2 hours implementation)
**Date**: 2025-11-20
**Goal**: Add factory configuration onboarding, minimal HTTP API, and a small React UI to unlock "describe your factory in natural language" capability.

---

## 1. Overview & Goals

### What and Why

This sprint adds two critical missing pieces to the factory simulator:

1. **OnboardingAgent** – Convert free-text factory descriptions ("I have 3 machines: M1 is assembly, M2 is drill, M3 is pack") into a valid `FactoryConfig` using the same LLM-backed, schema-validated approach as IntentAgent.
2. **Minimal HTTP API + React UI** – Expose `run_onboarded_pipeline` over a simple POST endpoint, and build a small React interface with two input textareas and three output panels.

Today, the system only works with the hard-coded toy factory (`build_toy_factory()`). After this sprint, users can describe *their* factory and the system automatically infers the configuration. This unlocks the "spearfish demo" narrative: **"You describe your factory once, and from then on, you describe your day's situation, and we show you scenarios."**

### Success Criteria

- ✅ Users can paste a simple text description of their factory and receive a valid, normalized `FactoryConfig`
- ✅ Users can describe today's situation and receive multiple scenarios, metrics, and briefing—all derived from the inferred factory
- ✅ Architecture cleanly separates engine (pure), agents (LLM at edges), onboarding (new layer), and UI (new layer)
- ✅ OnboardingAgent handles ambiguous/incomplete inputs gracefully; falls back to toy factory on failure
- ✅ Implementation realistic in < 2 hours on top of existing codebase
- ✅ Demo scripts show three end-to-end flows (baseline day, rush order, impossible constraint)

### In Scope

- **OnboardingAgent** – LLM agent that converts factory description text → `FactoryConfig` JSON, validated against Pydantic schema
- **Normalization layer** – Deterministic rules to fix missing/invalid fields, filter invalid steps, default missing constraints
- **Orchestrator update** – New `run_onboarded_pipeline(factory_text: str, situation_text: str)` that uses inferred factory when provided
- **HTTP endpoint** – Single FastAPI endpoint `POST /api/simulate` accepting `{factory_description, situation}` and returning JSON
- **React UI** – Minimal interface:
  - Two textareas (factory description, situation)
  - Simulate button + loading state
  - Three panels: Inferred Factory, Scenario Metrics, Briefing
- **Prompt tuning** – Light adjustments to IntentAgent, FuturesAgent, BriefingAgent to:
  - Explicitly handle user constraints (rush, slowdown, feasibility)
  - Improve BriefingAgent's "feasibility commentary" (e.g., "impossible to meet this constraint; best achievable is 9h")
  - Increase responsiveness and clarity

### Out of Scope

- New scheduling algorithms or scenario types
- Multi-day/shift planning
- Gantt charts or complex visualizations
- Editing the inferred factory inside the UI
- Onboarding from PDFs, ERP imports, or real data
- Authentication, multi-user support
- Database persistence
- Any changes to core `sim`, `metrics`, or `ScenarioMetrics` logic

---

## 2. Architecture Overview

The factory simulator now operates across four layers. Existing layers (Engine, Agents) remain unchanged.

### Layer 0 – Deterministic Engine (Existing)

**Responsibilities**: Simulation, metrics, scenario application.

**Modules**: `sim.py`, `metrics.py`, `models.py` (factory models).

**Interface**: Pure functions that accept `FactoryConfig`, `ScenarioSpec` and return `SimulationResult`, `ScenarioMetrics`.

**Immutable**: No changes in this sprint (and none are needed).

### Layer 1 – LLM Agent Layer (Existing, Light Updates)

**Responsibilities**: Interpret intent, generate scenario variations, produce briefings.

**Modules**: `agents.py`, `llm.py`.

**Changes in this sprint**:
- **IntentAgent**: Prompt slightly clarified to distinguish rush, slowdown, baseline scenarios; encouraged to flag user constraints that may be infeasible
- **FuturesAgent**: Prompt refinement to prefer baseline + aggressive + conservative mix; avoid mixing scenario types
- **BriefingAgent**: New requirement to compare metrics against inferred user constraints and explicitly state feasibility ("Cannot achieve makespan ≤ 6h; best achievable is 9h with current factory")

### Layer 2 – Onboarding Layer (New)

**Responsibilities**: Parse factory description text, infer `FactoryConfig`, apply defaults and normalization.

**Modules**: New `onboarding.py`.

**Components**:
- `OnboardingAgent` class with `infer_factory(description: str) -> FactoryConfig | None`
- `normalize_factory(proto_factory: dict) -> FactoryConfig` – Apply defaults, filter invalid steps, validate completeness
- `onboarding_prompt_template()` – Returns a prompt that instructs the LLM to emit a factory JSON

**Interface**:
- Input: Free-form factory description text
- Output: `FactoryConfig` (typed, validated) or `None` (on failure)
- Fallback: Returns `None`; orchestrator falls back to `build_toy_factory()`

### Layer 3 – Interface Layer (New)

**Responsibilities**: HTTP API and React UI.

**Modules**: `app.py` (FastAPI), React TypeScript/JSX (in `frontend/` or similar).

**Components**:
- `POST /api/simulate` – Accepts factory description + situation, returns `{factory, specs, metrics, briefing, meta}`
- React App:
  - Input panel: two textareas + button
  - Output panels: factory, metrics table, briefing markdown

**Interface**: HTTP JSON contract; see section 3.

### Data Flow (Request Lifecycle)

```
User opens React UI
     ↓
User fills two textareas:
  - "factory description" (optional)
  - "today's situation" (required)
     ↓
Click "Simulate" button
     ↓
POST /api/simulate with {factory_description, situation}
     ↓
Backend:
  1. If factory_description is non-empty:
     - OnboardingAgent.infer_factory(factory_description) → FactoryConfig?
     - Apply normalize_factory()
     - Use inferred factory
     Else:
     - Use build_toy_factory()

  2. IntentAgent.parse(situation, factory) → ScenarioSpec

  3. FuturesAgent.expand(intent_spec, factory) → list[ScenarioSpec] (1–3)

  4. For each ScenarioSpec in specs:
     - apply_scenario(factory, spec) → modified_factory
     - simulate_baseline(modified_factory) → SimulationResult
     - compute_metrics(result) → ScenarioMetrics

  5. BriefingAgent.brief(all_metrics, user_situation, factory) → markdown string

  6. Return JSON: {
       factory: FactoryConfig,
       specs: list[ScenarioSpec],
       metrics: list[ScenarioMetrics],
       briefing: str,
       meta: { used_default_factory: bool }
     }
     ↓
React UI renders:
  - Inferred factory (machines, jobs, steps)
  - Table: scenario name, makespan, total_lateness, bottleneck_machine, bottleneck_utilization
  - Briefing markdown
```

---

## 3. Data Contracts & Schemas

### 3.1 Canonical Factory Schema (Recap)

All new code must respect these existing, immutable types:

```python
# models.py (existing)

class Machine(BaseModel):
    id: str
    name: str

class Step(BaseModel):
    machine_id: str
    duration_hours: int  # Must be >= 1

class Job(BaseModel):
    id: str
    name: str
    steps: list[Step]
    due_time_hour: int  # Must be >= 0

class FactoryConfig(BaseModel):
    machines: list[Machine]
    jobs: list[Job]
```

**Constraints** (enforced by Pydantic and validation):
- `machines` must be non-empty
- `jobs` must be non-empty
- Each job's steps must reference only valid `machine_id`s
- Each step's `duration_hours` must be ≥ 1
- Each job's `due_time_hour` must be ≥ 0

### 3.2 OnboardingAgent Output Schema

The OnboardingAgent receives factory description text and must emit a JSON object that conforms directly to `FactoryConfig`:

```json
{
  "machines": [
    { "id": "M1", "name": "Assembly" },
    { "id": "M2", "name": "Drill/Mill" },
    { "id": "M3", "name": "Pack/Ship" }
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Widget A",
      "steps": [
        { "machine_id": "M1", "duration_hours": 1 },
        { "machine_id": "M2", "duration_hours": 3 },
        { "machine_id": "M3", "duration_hours": 1 }
      ],
      "due_time_hour": 12
    },
    {
      "id": "J2",
      "name": "Gadget B",
      "steps": [
        { "machine_id": "M1", "duration_hours": 1 },
        { "machine_id": "M2", "duration_hours": 2 },
        { "machine_id": "M3", "duration_hours": 1 }
      ],
      "due_time_hour": 14
    },
    {
      "id": "J3",
      "name": "Part C",
      "steps": [
        { "machine_id": "M2", "duration_hours": 1 },
        { "machine_id": "M3", "duration_hours": 2 }
      ],
      "due_time_hour": 16
    }
  ]
}
```

This is the canonical, single JSON output format. No DTO layer in this sprint; the LLM emits valid `FactoryConfig` data from the start, then the normalization layer applies defaults and filters.

### 3.3 Normalization Rules (Pure Function)

After the LLM emits factory JSON, it goes through deterministic normalization:

```python
def normalize_factory(raw_data: dict) -> FactoryConfig:
    """
    Apply defaults, filter invalid data, ensure completeness.

    Rules:
    1. If step duration_hours is missing or <= 0 → default to 1
    2. If step duration_hours is not an int → default to 1
    3. If job due_time_hour is missing or < 0 → default to 24
    4. If job due_time_hour is not an int → default to 24
    5. If a step references a machine_id not in machines list → drop that step
    6. If a job ends up with zero steps after filtering → drop that job
    7. If, after normalization, there are zero machines → log warning, return None
    8. If, after normalization, there are zero jobs → log warning, return None

    Returns:
      FactoryConfig (valid, normalized)

    Raises:
      ValueError if factory cannot be salvaged
    """
```

**Logging**: Every drop, default, or fix must be logged:
```
INFO: Normalized factory: dropped step M99 from J1 (machine not found)
INFO: Normalized factory: set J2.due_time_hour to 24 (was invalid: -5)
INFO: Normalized factory: dropped job J3 (zero steps after filtering)
```

### 3.4 Backend Response Schema

The `POST /api/simulate` endpoint returns:

```python
# JSON response

{
  "factory": {
    "machines": [...],     # FactoryConfig
    "jobs": [...]
  },

  "specs": [
    {
      "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
      "rush_job_id": "J2" | null,
      "rush_arrival_hour": 2 | null,
      "slowdown_factor": 1.5 | null,
      "slowdown_start_hour": 8 | null,
      "slowdown_end_hour": 14 | null
    },
    // ... up to 3 specs
  ],

  "metrics": [
    {
      "makespan_hour": 9,
      "job_lateness": {
        "J1": 0,
        "J2": 0,
        "J3": 0
      },
      "total_lateness_hours": 0,
      "bottleneck_machine_id": "M2",
      "bottleneck_utilization": 0.75
    },
    // ... one per spec
  ],

  "briefing": "# Morning Briefing: 2025-11-20\n\n...",

  "meta": {
    "used_default_factory": false,    // true if onboarding failed, fell back to toy factory
    "onboarding_errors": []           // optional: list of normalization warnings
  }
}
```

**TypeScript types for React**:
```typescript
interface ScenarioSpec {
  scenario_type: 'BASELINE' | 'RUSH_ARRIVES' | 'M2_SLOWDOWN';
  rush_job_id?: string;
  rush_arrival_hour?: number;
  slowdown_factor?: number;
  slowdown_start_hour?: number;
  slowdown_end_hour?: number;
}

interface ScenarioMetrics {
  makespan_hour: number;
  job_lateness: Record<string, number>;
  total_lateness_hours: number;
  bottleneck_machine_id: string;
  bottleneck_utilization: number;
}

interface SimulateResponse {
  factory: FactoryConfig;
  specs: ScenarioSpec[];
  metrics: ScenarioMetrics[];
  briefing: string;
  meta: {
    used_default_factory: boolean;
    onboarding_errors?: string[];
  };
}
```

---

## 4. Onboarding: Input Language, Agent, and Normalization

### 4.1 Expected Input Language

Users describe their factory in semi-structured English. The system is optimized for this mini-language but tolerates messier descriptions.

**Canonical example**:
```
machines:
- M1: assembly
- M2: drill / mill
- M3: pack / ship

jobs:
- J1 (widget A): M1 1h -> M2 3h -> M3 1h, due at 12
- J2 (gadget B): M1 1h -> M2 2h -> M3 1h, due at 14
- J3 (spares): M2 1h -> M3 2h, due at 16
```

**Variations the system should accept**:
```
We have 3 machines. Assembly takes 1 hour, does the first step.
Drill is our bottleneck. Pack and ship last. Three jobs:
  Widget A: assembly, then drill for 3 hours, then pack. Due tomorrow at noon.
  Gadget B: same route but drill takes 2 hours. Due at 2pm.
  Part C: skips assembly, goes straight to drill for 1 hour, then pack for 2 hours.
    Due at 4pm.
```

**Demo constraints** (hard limits for this sprint):
- Max 3 machines
- Max 5 jobs
- Max 4 steps per job
- No branching / parallel routes (linear pipeline only)
- All durations in integer hours
- No "optional" steps

### 4.2 OnboardingAgent Implementation

```python
# onboarding.py

class OnboardingAgent:
    def infer_factory(self, description: str) -> FactoryConfig | None:
        """
        Convert factory description text → FactoryConfig.

        Args:
            description: Free-form factory description

        Returns:
            FactoryConfig if successful, None on failure

        Behavior:
        1. Construct prompt from description + template
        2. Call call_llm_json with FactoryConfig schema
        3. Validate output against Pydantic FactoryConfig
        4. On success: return FactoryConfig
        5. On failure (LLM error or validation error):
           - Log the error
           - Return None (caller falls back to toy factory)
        """
```

**Prompt skeleton** (not full prose, but structured enough for implementation):

```
You are a factory configuration parser. Convert the following factory description
into a JSON object matching this schema:

{
  "machines": [
    { "id": "M1", "name": "...", ... },
    ...
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "...",
      "steps": [
        { "machine_id": "M1", "duration_hours": 1 },
        ...
      ],
      "due_time_hour": 12
    },
    ...
  ]
}

RULES:
- Each machine has an ID (M1, M2, ...) and a name.
- Each job has an ID (J1, J2, ...), a name, a sequence of steps (in order),
  and a due time in hours (0-24).
- Each step references a machine ID and takes an integer number of hours.
- Do NOT invent machines or jobs that aren't mentioned.
- If a detail is ambiguous or missing, use the simplest interpretation.
- Return ONLY the JSON object, no explanation.

FACTORY DESCRIPTION:
{description}

JSON:
```

**Example invocation**:
```python
agent = OnboardingAgent()
factory = agent.infer_factory(user_input_text)
if factory:
    print(f"Inferred {len(factory.machines)} machines, {len(factory.jobs)} jobs")
else:
    print("Failed to infer factory; using default")
    factory = build_toy_factory()
```

### 4.3 Normalization Function

```python
# onboarding.py

def normalize_factory(raw_dict: dict) -> FactoryConfig:
    """
    Apply defaults and filters to raw factory data.

    Ensures:
    - All step durations >= 1 (int)
    - All due_time_hours >= 0 (int)
    - All steps reference valid machines
    - All jobs have >= 1 step
    - All configs have >= 1 machine and >= 1 job

    Returns:
      FactoryConfig (valid, normalized)

    Raises:
      ValueError if factory cannot be salvaged
    """

    # Parse machines
    machines = []
    for m in raw_dict.get("machines", []):
        machines.append(Machine(id=m["id"], name=m["name"]))

    machine_ids = {m.id for m in machines}

    if not machines:
        logger.error("No machines after parsing; cannot salvage")
        raise ValueError("No machines in factory")

    # Parse jobs with filtering
    jobs = []
    for j in raw_dict.get("jobs", []):
        steps = []
        for s in j.get("steps", []):
            # Apply defaults
            duration = s.get("duration_hours", 1)
            if not isinstance(duration, int) or duration < 1:
                logger.warning(f"Invalid duration in job {j.get('id')}: {duration}; defaulting to 1")
                duration = 1

            machine_id = s.get("machine_id")
            if machine_id not in machine_ids:
                logger.warning(f"Step in job {j.get('id')} references unknown machine {machine_id}; dropping")
                continue

            steps.append(Step(machine_id=machine_id, duration_hours=duration))

        if not steps:
            logger.warning(f"Job {j.get('id')} has no valid steps after filtering; dropping")
            continue

        # Apply due_time defaults
        due_time = j.get("due_time_hour", 24)
        if not isinstance(due_time, int) or due_time < 0:
            logger.warning(f"Invalid due_time_hour in job {j.get('id')}: {due_time}; defaulting to 24")
            due_time = 24

        jobs.append(Job(
            id=j["id"],
            name=j.get("name", j["id"]),
            steps=steps,
            due_time_hour=due_time
        ))

    if not jobs:
        logger.error("No jobs after filtering; cannot salvage")
        raise ValueError("No jobs in factory after filtering")

    return FactoryConfig(machines=machines, jobs=jobs)
```

### 3.5 ScenarioMetrics Schema

The `ScenarioMetrics` object is returned for each scenario and contains:

```python
class ScenarioMetrics(BaseModel):
    makespan_hour: int                    # Total hours from start to last job completion
    job_lateness: dict[str, int]          # Job ID → hours late (0 if on-time)
    total_lateness_hours: int             # Sum of all per-job lateness (non-negative)
    bottleneck_machine_id: str            # ID of most-utilized machine
    bottleneck_utilization: float         # Fractional utilization (0.0–1.0)
```

**Field explanations**:
- **total_lateness_hours**: Non-negative integer representing the sum of all job lateness values. This field must always be present in responses and explicitly provided by the backend.
- **bottleneck_utilization**: Utilization of the bottleneck machine (0.0 = idle, 1.0 = 100% utilized).

---

## 5. LLM Usage Budget

**Strict constraint**: Each full request (one call to `run_onboarded_pipeline`) triggers at most 3 LLM calls:

1. **OnboardingAgent** (optional): Factory description → `FactoryConfig` JSON (1 call, only if factory_description provided)
2. **IntentAgent + FuturesAgent** (required): User situation → base `ScenarioSpec` + up to 3 variations (1–2 calls, treated as single logical step)
3. **BriefingAgent** (required): Metrics + context → markdown briefing (1 call)

**Critical rules**:
- All LLM calls use the existing `call_llm_json()` helper from `llm.py`
- No new LLM-powered agents or entrypoints are introduced in this sprint
- No direct LLM calls from UI or other new code (only through orchestrator)
- Fallback behavior: If any LLM call fails, the system logs the error and continues with sensible defaults or toy factory

---

## 6. Agent Updates & Feasibility Commentary

### 6.1 IntentAgent Changes

**Current behavior**: Converts user situation text → `ScenarioSpec`.

**Changes in this sprint**:
- Prompt is clarified to explicitly distinguish BASELINE, RUSH_ARRIVES, M2_SLOWDOWN
- Prompt is encouraged to notice when user asks for impossible constraints (e.g., "no lateness, makespan <= 6h" when factory minimum is 9h)
- Encode user's implied constraints in the situation text so BriefingAgent can reference them later

**Expected behavior**: Same shape, slightly better clarity.

**Example prompt refinement**:
```
Given the factory and user situation, infer which scenario type best represents
the situation:
- BASELINE: no special events, standard operation
- RUSH_ARRIVES: user indicates a job is a rush order
- M2_SLOWDOWN: user mentions a machine breakdown or maintenance

Also note any explicit constraints the user mentions (e.g., "J1 must not be late",
"makespan must be <= 8 hours"). These will be checked by the briefing agent.

FACTORY:
{factory_summary}

USER SITUATION:
{situation}

Return JSON:
{
  "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
  "rush_job_id": "J1" | null,
  "rush_arrival_hour": 2 | null,
  "slowdown_factor": 1.5 | null,
  "slowdown_start_hour": 8 | null,
  "slowdown_end_hour": 14 | null,
  "user_constraints": "string summarizing any constraints mentioned"
}
```

### 6.2 FuturesAgent Changes

**Current behavior**: Expands one `ScenarioSpec` into 1–3 variations.

**Changes in this sprint**:
- Prompt explicitly prefers (baseline + one aggressive + one conservative) mix
- Prompt explicitly forbids mixing scenario types within a single list (either all BASELINE, or all RUSH_ARRIVES, or all M2_SLOWDOWN)
- Small clarification on what "aggressive" and "conservative" mean in context

**Expected behavior**: Same shape, clearer intent.

**Example prompt refinement**:
```
Given a primary scenario, generate 1–3 related scenarios that explore the
consequence space:

- If the primary scenario is BASELINE: keep baseline, maybe add a mild rush
  scenario and a mild slowdown scenario (in separate lists? no, pick the best one).
- If the primary scenario is RUSH_ARRIVES: generate baseline, the given rush,
  and a more aggressive rush (earlier arrival or tighter due time).
- If the primary scenario is M2_SLOWDOWN: generate baseline, mild slowdown,
  and severe slowdown.

Do NOT mix scenario types (e.g., don't return both a rush and a slowdown
in the same list).

Return up to 3 ScenarioSpec objects in JSON array format.

PRIMARY SCENARIO:
{scenario_json}

FACTORY:
{factory_summary}

JSON:
```

### 6.3 BriefingAgent Changes

**Current behavior**: Accepts metrics and returns markdown briefing.

**Key new requirement**: Explicitly compare metrics against user's implied constraints and state feasibility.

**Expected behavior**:

**Before** (current):
```
User input: "rush J2, no job may be late, makespan must be <= 6 hours"
Metrics show: makespan = 9h, J1 is 3h late, J2 is on-time
Current briefing: "M2 is the bottleneck at 100% utilization. Recommend
prioritizing J2. J1 is delayed."

Problem: No mention of why the user's constraints are impossible.
```

**After** (new):
```
Same input and metrics.
New briefing includes:
"## Feasibility Assessment
Your constraints cannot all be met simultaneously:
- Requested: makespan <= 6h, zero lateness
- Best achievable: makespan = 9h (rush J2 requires this)
- Impact: J1 will be 3h late in all scenarios

Recommendation: Either accept J1 lateness, defer J3, or negotiate
rush due time with customer."
```

**Prompt skeleton** (new requirement):

```
You are a factory operations briefing assistant. Analyze metrics against
the user's stated constraints and priorities.

FACTORY:
{factory_summary}

USER SITUATION (constraints and priorities):
{situation}

SCENARIO ANALYZED:
{scenario_name}

METRICS:
- Makespan: {makespan_hour}h
- Total lateness: {total_lateness_hours}h
- Job lateness: {job_lateness_dict}
- Bottleneck: {bottleneck_machine} at {bottleneck_utilization}%

TASK:
1. Generate a morning briefing (markdown) for a plant manager.
2. Explicitly state whether the user's constraints are achievable.
3. If constraints are impossible, explain what is achievable instead and
   recommend tradeoffs.
4. Highlight risks (late jobs, high utilization).
5. Recommend actions (reorder jobs, defer tasks, negotiate rush timelines).

BRIEFING:
```

---

## 7. Constraint Handling Strategy

**Critical clarification**: In this sprint, we do **not** introduce a formal constraint schema (e.g., `ConstraintsSpec` or similar).

Instead:
- **User constraints** are parsed naturally from the situation text (e.g., "no lateness", "must finish in 6 hours", "rush J2").
- **Feasibility assessment** is handled qualitatively by the BriefingAgent, comparing scenario metrics against natural-language expectations.
- The BriefingAgent explicitly states whether constraints are achievable and, if not, explains what is achievable instead.

**Examples of feasibility logic** (handled by BriefingAgent reasoning, not new code):
- If user says "no lateness" and metrics show `total_lateness_hours > 0`, flag as infeasible
- If user says "finish by 6h" and `makespan_hour > 6`, flag as infeasible
- If bottleneck utilization is 100%, explain that capacity is maxed out

No new dataclasses, Pydantic models, or formal constraint validation in this sprint. Feasibility lives in the BriefingAgent's text output and metrics interpretation.

---

## 8. Orchestrator Changes

### 8.1 New Entrypoint

```python
# orchestrator.py

def run_onboarded_pipeline(factory_description: str, situation_text: str) -> dict:
    """
    Run the full pipeline with factory onboarding.

    Args:
        factory_description: User's factory description (may be empty string)
        situation_text: User's situation / priorities

    Returns:
        dict with keys:
        - factory: FactoryConfig
        - specs: list[ScenarioSpec]
        - results: list[SimulationResult]
        - metrics: list[ScenarioMetrics]
        - briefing: str (markdown)
        - meta: dict with used_default_factory, onboarding_errors

    Flow:
    1. If factory_description is non-empty:
       - agent = OnboardingAgent()
       - proto_factory = agent.infer_factory(factory_description)
       - if proto_factory: factory = normalize_factory(proto_factory)
       - if not factory: log warning, factory = build_toy_factory()
       Else:
       - factory = build_toy_factory()

    2. Reuse existing pipeline:
       - intent_spec = IntentAgent().parse(situation_text, factory)
       - specs = FuturesAgent().expand(intent_spec, factory)
       - For each spec: simulate and compute metrics
       - briefing = BriefingAgent().brief(metrics, situation_text, factory)

    3. Return the dict with used_default_factory flag set
    """
```

### 8.2 Logging

All new code logs at INFO level:
- When onboarding starts/succeeds/fails
- What was normalized (defaults applied, steps dropped, jobs dropped)
- When fallback to toy factory occurs
- LLM call latencies

Example:
```
INFO: OnboardingAgent.infer_factory: Starting
INFO: Onboarded factory: 3 machines, 3 jobs
INFO: normalize_factory: Fixed 1 invalid duration, 1 invalid due_time_hour
INFO: normalize_factory: Dropped 1 step (invalid machine reference)
INFO: run_onboarded_pipeline: Completed; factory=toy, intent=BASELINE, specs=3
```

### 8.3 No Changes to Core Logic

**Explicit guarantee**: No modifications to:
- `simulate_baseline()`, `apply_scenario()`, `compute_metrics()`
- `ScenarioMetrics` structure
- `ScenarioSpec` enum or validation
- Toy factory definition (still used as fallback and in demo scripts)

The existing test suite (`tests/`) should pass without modification.

---

## 9. UI Design & API Contract

### 9.1 Layout (Minimal React)

```
┌─────────────────────────────────────────────────┐
│  Factory Simulator: Onboarding + Analysis       │
└─────────────────────────────────────────────────┘

┌──────────────────────┬──────────────────────────┐
│ Factory Description  │ Today's Situation        │
│ (optional; leave     │ (required; e.g., "rush  │
│  blank for toy)      │  J2, accept J1 late")    │
│                      │                          │
│  [textarea]          │  [textarea]              │
└──────────────────────┴──────────────────────────┘

                 [Simulate] (loading ...)

┌──────────────────────────────────────────────────┐
│  Factory Configuration                           │
│  ├─ Machines: M1, M2, M3                        │
│  └─ Jobs:                                        │
│     ├─ J1: M1(1h) → M2(3h) → M3(1h) due 12h   │
│     ├─ J2: M1(1h) → M2(2h) → M3(1h) due 14h   │
│     └─ J3: M2(1h) → M3(2h) due 16h             │
│  (Used default toy factory)                      │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  Scenario Metrics                                │
│                                                  │
│  Scenario          │ Makespan │ Lateness │ ...   │
│  ─────────────────┼──────────┼──────────┤        │
│  Baseline         │ 9h       │ 0h       │        │
│  Rush J2          │ 11h      │ 4h (J1)  │        │
│  M2 Slowdown      │ 12h      │ 3h       │        │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  Briefing                                        │
│                                                  │
│  # Morning Briefing: 2025-11-20                 │
│                                                  │
│  ## Today at a Glance                           │
│  ...                                             │
│                                                  │
│  [Markdown rendered, supports headers, tables]  │
└──────────────────────────────────────────────────┘
```

### 9.2 Panels in Detail

#### Panel 1: Factory Configuration

**Content**:
- List of machines (id, name)
- List of jobs with step sequences:
  - `J1: M1(1h) → M2(3h) → M3(1h), due 12h`
- Badge: "Used default toy factory" (if onboarding failed)

**Behavior**:
- Read-only; no editing in UI
- Grows/shrinks based on factory size (max 3 machines, 5 jobs for demo)

#### Panel 2: Scenario Metrics

**Content**:
- Table with one row per scenario
- Columns:
  - **Scenario**: Label (e.g., "Baseline", "Rush J2", "M2 Slowdown (8h–14h)")
  - **Makespan (h)**: Integer hours
  - **Total Lateness (h)**: Sum of all job lateness
  - **Bottleneck Machine**: Machine ID
  - **Bottleneck Utilization**: Percent (0–100%)

**Example table**:
```
Scenario          | Makespan | Lateness | Bottleneck | Utilization
────────────────┼──────────┼──────────┼────────────┼──────────────
Baseline        │ 9h       │ 0h       │ M2         │ 75%
Rush J2         │ 11h      │ 4h       │ M2         │ 100%
M2 Slowdown     │ 12h      │ 3h       │ M2         │ 100%
```

#### Panel 3: Briefing

**Content**:
- Full markdown text returned by BriefingAgent
- Rendered as HTML (markdown parser)
- Typically includes:
  - Morning briefing header
  - Today at a Glance (summary)
  - Scenarios analyzed
  - Key risks
  - Jobs at risk (per-job lateness across scenarios)
  - Bottleneck machines
  - Recommended actions
  - Limitations

### 9.3 Interactions

**Button Behavior**:
- Disabled until both inputs are filled (factory description can be empty, situation must be non-empty)
- On click: Disable button, show spinner, POST to `/api/simulate`
- On success: Populate all three panels, enable button
- On error: Show error toast/alert, enable button, log to console

**Error Handling**:
- Generic error message if endpoint returns 500 or network error: "Simulation failed. Please check your input and try again."
- No detailed error messages to user (those go to backend logs)

**Styling**:
- Minimal; use semantic HTML + CSS Grid for layout
- Dark or light mode optional (not required for demo)
- Mobile-responsive nice-to-have (not required)

### 9.4 HTTP API Contract

**Endpoint**: `POST /api/simulate`

**Request**:
```json
{
  "factory_description": "string (may be empty)",
  "situation": "string (required, non-empty)"
}
```

**Response** (200): See section 3.4 (Backend Response Schema) for the complete JSON structure.

**Response** (4xx/5xx):
```json
{
  "error": "string"
}
```

---

## 10. Demo Scripts

Demo scripts are concrete, end-to-end flows. Each specifies input, expected behavior, and key talking points.

### Demo Script A: Baseline Production Day

**Narrative**: "Normal day, no special events. We want to understand the standard schedule and where bottlenecks are."

**Input**:
- Factory description: (empty; use toy factory)
- Situation: `"Normal production day. No rush orders. Want to understand baseline schedule and machine utilization."`

**Expected behavior**:
- Inferred factory: Toy factory (M1, M2, M3; J1, J2, J3)
- Scenarios: Baseline (only)
- Metrics: Baseline shows 9h makespan, 0h lateness, M2 at ~75% utilization
- Briefing: Emphasizes M2 as bottleneck, explains why, suggests no immediate action needed

**Key talking points**:
- "M2 is our constrained resource; all three jobs need it."
- "Baseline schedule is clean: no late jobs, but M2 is 75% utilized."
- "This is our 'healthy baseline'; anything else is a deviation."

### Demo Script B: Rush J2 Order

**Narrative**: "Urgent order for J2 arrives in the morning. We want to know: Can we deliver on time, and what's the impact on other jobs?"

**Input**:
- Factory description: (empty; use toy factory)
- Situation: `"Critical rush order for J2 arrived this morning. J2 must ship by 10am. We can accept some delay on J1 and J3 if needed. What does our day look like?"`

**Expected behavior**:
- Inferred factory: Toy factory
- Scenarios: Baseline, Rush J2 (arrival 2h, due 10h), and possibly aggressive variant
- Metrics:
  - Baseline: 9h makespan, 0h lateness
  - Rush J2: ~11h makespan, J1 delayed ~4h, J2 on-time, M2 at 100%
- Briefing: Acknowledges the constraint ("J2 by 10am is achievable"), explains J1 lateness, suggests starting J1 immediately or negotiating J3 defer

**Key talking points**:
- "Rush J2 by 10am is feasible, but it delays J1."
- "With current capacity, you can't have J1, J2, *and* J3 all on-time."
- "Recommendation: Start J1 at hour 0, inject rush J2 at hour 2, and accept ~4h delay on J1 or defer J3."

### Demo Script C: Impossible Constraints

**Narrative**: "User asks for something physically impossible. System should detect this and offer 'best achievable' alternative."

**Input**:
- Factory description: (empty; use toy factory)
- Situation: `"Critical: rush both J1 and J2 (both due by 10am), zero lateness on all jobs, and we need to finish everything by 6am. What's the best we can do?"`

**Expected behavior**:
- Inferred factory: Toy factory
- Scenarios: Baseline, rush attempts
- Metrics: All scenarios show lateness, likely >= 3h total
- Briefing:
  ```
  ## Feasibility Assessment
  Your constraints cannot all be met:
  - Requested: J1 due 10am, J2 due 10am, makespan <= 6h, zero lateness
  - Factory minimum: makespan = 9h (due to sequential M2 demand: 3h + 2h + 1h + buffer)

  ## Best Achievable
  - Makespan: 9–10h (depending on job order)
  - Minimum lateness: J1 or J3 delayed 2–3h

  ## Recommendation
  Negotiate one of:
  1. Extend due time for J1 or J3 to 12–14h
  2. Add M2 capacity (parallel M2 machine or hire contractor)
  3. Defer J3 to next day
  ```

**Key talking points**:
- "The math doesn't work: three jobs, 6h total M2 demand, but one machine."
- "We're honest about impossibility, not falsely optimistic."
- "System explains *why* it's impossible and offers realistic alternatives."

---

## 11. Implementation Phases / PR Roadmap

All work targets completion in < 2 hours of experienced engineering.

### PR-A: OnboardingAgent + Normalization

**Goal**: Parse factory descriptions, normalize outputs, validate completeness.

**Deliverables**:
1. New `onboarding.py` module with:
   - `OnboardingAgent` class + `infer_factory()` method
   - `normalize_factory()` pure function
   - Fallback behavior (returns `None` on any error; caller uses `build_toy_factory()`)
2. Pydantic schema (or direct use of `FactoryConfig`)
3. Comprehensive logging of normalization steps
4. Unit tests:
   - Valid factory description → correct `FactoryConfig`
   - Missing/invalid fields → normalized defaults
   - Invalid machine reference → step dropped
   - Zero jobs after filtering → fallback
   - Ambiguous inputs (semi-English) → reasonable interpretation
5. No UI/HTTP changes yet

**Implementation time**: ~45 minutes

---

### PR-B: HTTP Endpoint + Orchestrator Wiring

**Goal**: Expose `run_onboarded_pipeline` over HTTP; wire up logging.

**Deliverables**:
1. `app.py` (FastAPI):
   - `POST /api/simulate` endpoint
   - Request validation (factory_description: str, situation: str)
   - Response formatting (JSON matching schema from section 3)
   - Error handling (return 400 on bad input, 500 on internal error)
2. Update `orchestrator.py`:
   - New `run_onboarded_pipeline(factory_description, situation)` function
   - Uses `OnboardingAgent` if factory_description is non-empty
   - Falls back to `build_toy_factory()` on failure
   - Logs onboarding success/failure, factory size, scenario count, latencies
3. Tests:
   - Endpoint returns 200 with valid JSON on valid input
   - Endpoint falls back to toy factory on bad factory description
   - Endpoint returns 400 on missing situation
   - Response schema matches specification
4. No UI changes yet; CLI still works

**Implementation time**: ~45 minutes

---

### PR-C: React UI + Prompt Tuning

**Goal**: Build minimal React interface; refine agent prompts for responsiveness and feasibility.

**Deliverables**:
1. React app (TypeScript/JSX):
   - Layout: two textareas + button + three panels (as in section 7)
   - POST to `/api/simulate` on button click
   - Render factory, metrics table, briefing (markdown)
   - Loading state + error handling
   - No routing, no global state management (inline state is fine)
2. Prompt tuning:
   - IntentAgent: Clarify scenario types, note user constraints
   - FuturesAgent: Prefer baseline + aggressive + conservative mix
   - BriefingAgent: Add feasibility assessment against user constraints
   - No massive rewrites; targeted adjustments only
3. Manual QA:
   - Run demo scripts A, B, C
   - Verify briefing mentions feasibility
   - Check metrics table is readable
   - Ensure loading state shows

**Implementation time**: ~30 minutes

---

**Total estimate**: ~2 hours

---

## 12. Success & Handoff Criteria

- ✅ All three PRs merged and passing tests
- ✅ Demo scripts A, B, C run without errors
- ✅ Briefing explicitly mentions feasibility for at least one scenario
- ✅ No changes to core `sim`, `metrics`, or test suite
- ✅ Logging is informative for debugging onboarding failures
- ✅ React UI is minimal but fully functional
- ✅ Ready for live demo with ProDex (or similar prospect)

---

## Appendix: Example Onboarded Factory

Given this input:
```
We run a small assembly operation. We have:
- Station A (prep): very fast, 30 min per job
- Station B (weld/assemble): our bottleneck, takes 2-3 hours
- Station C (inspection/ship): 30 min per job

Three regular jobs today:
- Basic Widget (BW): prep, weld for 2 hours, inspect & ship. Needed by end of shift (5pm).
- Deluxe Gadget (DG): prep, weld for 3 hours, inspect & ship. Can wait until 6pm.
- Spare Parts (SP): just goes to weld for 1 hour, then inspect. Due at 5pm.
```

**Parsed (before normalization)**:
```json
{
  "machines": [
    { "id": "A", "name": "Station A (Prep)" },
    { "id": "B", "name": "Station B (Weld)" },
    { "id": "C", "name": "Station C (Inspect/Ship)" }
  ],
  "jobs": [
    {
      "id": "BW",
      "name": "Basic Widget",
      "steps": [
        { "machine_id": "A", "duration_hours": 0.5 },  // <- fractional
        { "machine_id": "B", "duration_hours": 2 },
        { "machine_id": "C", "duration_hours": 0.5 }   // <- fractional
      ],
      "due_time_hour": 17
    },
    {
      "id": "DG",
      "name": "Deluxe Gadget",
      "steps": [
        { "machine_id": "A", "duration_hours": 0.5 },
        { "machine_id": "B", "duration_hours": 3 },
        { "machine_id": "C", "duration_hours": 0.5 }
      ],
      "due_time_hour": 18
    },
    {
      "id": "SP",
      "name": "Spare Parts",
      "steps": [
        { "machine_id": "B", "duration_hours": 1 },
        { "machine_id": "C", "duration_hours": 0.5 }  // <- fractional
      ],
      "due_time_hour": 17
    }
  ]
}
```

**After normalization**:
```json
{
  "machines": [
    { "id": "A", "name": "Station A (Prep)" },
    { "id": "B", "name": "Station B (Weld)" },
    { "id": "C", "name": "Station C (Inspect/Ship)" }
  ],
  "jobs": [
    {
      "id": "BW",
      "name": "Basic Widget",
      "steps": [
        { "machine_id": "A", "duration_hours": 1 },     // normalized 0.5 → 1
        { "machine_id": "B", "duration_hours": 2 },
        { "machine_id": "C", "duration_hours": 1 }      // normalized 0.5 → 1
      ],
      "due_time_hour": 17
    },
    // ... etc
  ]
}
```

**Log output**:
```
INFO: OnboardingAgent.infer_factory: Starting
INFO: Onboarded factory: 3 machines, 3 jobs
INFO: normalize_factory: Normalized BW step 0: 0.5 hours → 1 (not integer)
INFO: normalize_factory: Normalized BW step 2: 0.5 hours → 1 (not integer)
INFO: normalize_factory: Normalized DG step 0: 0.5 hours → 1 (not integer)
INFO: normalize_factory: Normalized DG step 2: 0.5 hours → 1 (not integer)
INFO: normalize_factory: Normalized SP step 1: 0.5 hours → 1 (not integer)
INFO: normalize_factory: Factory ready; 3 machines, 3 jobs, 0 dropped
```

---

**End of Specification**

This specification is implementation-ready. Each section specifies behavior, not code; PR roadmap is realistic and concrete. The goal is a sharp, focused demo that showcases multi-agent orchestration and deterministic simulation, without scope creep.
