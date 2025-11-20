# Factory Day Simulator: Morning Briefing Demo

## 1. Problem Statement & Goals

### Context
ProDex and similar companies are building factory scheduling and logistics software. They want to become the "operating system" for factory operations—combining deterministic simulation with AI-driven what-if analysis and human communication. This demo shows how to weave **LLM agents at the edges** of a **deterministic core simulator** to produce actionable morning briefings for a plant manager.

### Purpose
This is a **spearfish demo** designed to:
- Show taste in system design (clean separation, typed contracts, explicit orchestration)
- Demonstrate multi-agent LLM orchestration *without* a framework (no LangGraph)
- Prove that wrapping agents around simulation yields insight—not just pretty charts
- Convince a strong CTO that we understand the problem space (factory logic + agent boundaries + what to automate vs. compute)

### Scope
- **Single day** of factory operations (discrete time, ~24 hours, configurable)
- **Toy world**: 3 machines, 3 baseline jobs, 2–3 futures per day (baseline + rush + disruption)
- **No real data**: factory, jobs, machines are hardcoded toy examples
- **Deterministic**: identical input → identical output, always
- **Multi-agent**: Intent (text→structure), Futures (structure→scenarios), Briefing (metrics→prose)
- **Simple orchestrator**: hand-rolled, no external frameworks, explicit state machine

### Success Criteria
1. Pipeline runs end-to-end without errors in <4 hours of implementation
2. Three distinct scenarios produce meaningfully different metrics
3. Briefing correctly names jobs, machines, and risks; no hallucinated IDs
4. A factory planner reading the output thinks: *"This understands my day and tells me something I didn't expect."*
5. A CTO reading the code thinks: *"This person gets multi-agent design and knows where LLMs belong."*

---

## 2. User & Customer Perspective

### Primary User: Factory Planner / Ops Manager

**Experience:**
- Arrives at factory or office before shift start
- Describes their day priorities in 1–2 sentences: *"We have a rush order for customer X, protect job J1 at all costs, but I'm okay with slack elsewhere"* or *"Machine M2 might have issues; what's our downside?"*
- System ingests this, generates baseline + 2–3 futures, simulates all, produces a **morning briefing**
- Briefing is markdown/text, ~500–800 words, split into sections:
  - **Today at a Glance**: headline risks and one recommended action
  - **Scenarios Analyzed**: which futures and why
  - **Key Risks**: jobs at risk of lateness, bottleneck shifts
  - **Jobs at Risk**: per-job breakdown (if any late in any scenario)
  - **Bottleneck Machines**: which machine is the constraint in each scenario
  - **Recommended Actions**: small, concrete tweaks (reorder jobs, expedite, shift capacity)
  - **Limitations**: what the model can't predict (breakdowns, material issues, etc.)

**Questions implicitly answered:**
- What will blow up today? (lateness, bottlenecks)
- Which jobs should I worry about? (by scenario)
- What's my lever to change the outcome? (machine allocation, job priority)
- What's the downside of my stated priority? (which other jobs suffer)

### Secondary User: CTO / Technical Evaluator

**What they're evaluating:**
- **Separation of concerns**: Is the LLM truly at the edge, or does it touch the simulator's internals?
- **Typed contracts**: Are agent I/O strictly schema'd? Is validation explicit?
- **Orchestration clarity**: Is the flow obvious without a framework? Can I extend it?
- **Determinism**: Do identical inputs yield identical outputs? Is randomness absent?
- **Taste**: Does the codebase read like it's made by someone who's thought about this problem deeply?

**Red flags they'll look for:**
- ❌ LLM inventing machine IDs or job names
- ❌ Agent outputs validated loosely or buried in code
- ❌ Simulation state mutated implicitly by agents
- ❌ Ambiguous error handling or silent fallbacks
- ❌ Heavy reliance on external orchestration framework

**Green flags:**
- ✅ Tight, explicit validation between each agent and sim
- ✅ Shared state (`FactoryState`) passed explicitly, never mutated in place
- ✅ Simple logs showing each step, latencies, decision points
- ✅ Deterministic, reproducible results
- ✅ Agentic intent strictly bounded (enum, fixed job refs)

### User Journey

1. **Planner inputs intent**: "We have a rush order for J2; baseline job J3 is important, but I can delay J1 if needed. What should I expect?"
2. **Orchestrator**:
   - Calls Intent Agent → parses to `ScenarioIntent(objective=RUSH_FIRST, protected_job=J3, risk_tolerance=HIGH)`
   - Calls Futures Agent → generates `[BASELINE, RUSH_ARRIVES(rush_job_id=J2, arrival_time=2, due_time=12), M2_SLOWDOWN(window=8-14)]`
   - Simulates each, computes metrics (lateness, bottleneck)
   - Calls Briefing Agent with metrics, receives markdown
3. **Planner reads briefing**: sees that rush scenario delays J1 by 2h but J3 stays safe, M2 is bottleneck in all scenarios, recommends scheduling J1 earlier if possible.
4. **Decision**: planner reorders morning jobs or escalates to materials team about the bottleneck.

---

## 3. High-Level Architecture

### Five Layers (Explicit Boundaries)

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 5: Briefing Narrative (LLM)                              │
│  Input: Metrics, Config  →  Output: Markdown text               │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: Agentic Interpretation (LLMs at edges)                │
│  Intent Agent    | Futures Agent    | Briefing Agent            │
│  text→intent     | intent→scenarios | metrics→prose             │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Simulation & Metrics (Deterministic)                  │
│  schedule(factory, intent) → SimulationResult                   │
│  metrics(result) → ScenarioMetrics                              │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: Scenarios & Futures (Structured, no LLM)              │
│  ScenarioIntent → [BASELINE, RUSH_ARRIVES, M2_SLOWDOWN]         │
│  ScenarioSpec: closed enum, bounded parameters                  │
└─────────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: Canonical Factory Model (Deterministic)               │
│  Machine, Job, Step, FactoryConfig                              │
│  3 machines, 3 jobs, simple step DAG, ~24h horizon              │
└─────────────────────────────────────────────────────────────────┘
```

### Orchestrator (Mini-Framework)

A simple, **synchronous, stateless-except-for-FactoryState** orchestrator:

- Owns shared `FactoryState` (config, intent, scenarios, sim results, metrics, briefing, errors)
- Calls agents → sim → metrics → briefing in strict sequence
- Validates outputs against schemas before using them
- Logs each step (agent, latency, validation outcome)
- No external framework (no LangGraph, no Airflow)
- Halts on unrecoverable error, continues on agent validation failure (fallback to default)

### Key Principles

1. **LLM at edges, deterministic core**: Agents interpret and narrate; simulation computes.
2. **Strict schemas**: Every agent input/output is validated against a schema.
3. **No agent hallucination**: Agents can only reference jobs/machines from the config; agents cannot invent new ones.
4. **Closed scenario space**: Futures agent picks from a fixed enum of scenario types, not arbitrary modifications.
5. **Reproducibility**: Same user text, same time of day, same factory config → same briefing (deterministic).
6. **Single day, small world**: Scope is intentionally tight to fit 4-hour implementation.

---

## 4. Data Models & Types

### Machine

```
Machine:
  id: str                    # e.g., "M1", "M2", "M3"
  name: str                  # e.g., "Assembly", "Drill", "Pack"
  available_start: int       # earliest hour available (e.g., 0)
  available_end: int         # latest hour available (e.g., 24)

Invariants:
  - id is unique across all machines
  - available_start < available_end
  - available_end <= 24 (single day)
```

### Step

```
Step:
  id: str                    # e.g., "J1-step1", "J2-step2"
  job_id: str                # which job does this belong to
  machine_id: str            # which machine to use
  duration_hours: int        # how many hours to complete this step
  precedence: list[str]      # IDs of steps that must complete first (step DAG)

Invariants:
  - machine_id refers to an actual Machine in the factory
  - job_id refers to an actual Job in the factory
  - precedence list contains only step IDs in the same job
  - no circular dependencies in precedence
  - duration_hours > 0
```

### Job

```
Job:
  id: str                    # e.g., "J1", "J2", "J3"
  name: str                  # e.g., "Widget A", "Gadget B"
  due_time: int              # hours (e.g., 12 = due at noon on day 0)
  priority: int              # 0=low, 1=medium, 2=high (hint for scheduling, not hard constraint)
  steps: list[Step]          # ordered steps for this job

Invariants:
  - id is unique across all jobs
  - due_time is in [0, 24] (single day)
  - priority is in {0, 1, 2}
  - steps must form a valid DAG (no cycles)
  - all step machine_ids refer to actual machines
```

### FactoryConfig

```
FactoryConfig:
  machines: list[Machine]
  jobs: list[Job]
  time_horizon: int          # hours, e.g., 24
  scheduling_heuristic: str  # e.g., "earliest_due_date" or "fcfs"

Invariants:
  - machines and jobs are non-empty and have unique ids
  - no job due_time exceeds time_horizon
  - all step machine IDs are in machines list
```

### ScenarioIntent

```
ScenarioIntent:
  objective: enum {BASELINE, RUSH_FIRST, BALANCED, PROTECT_JOB}
  protected_job_id: str | None  # if objective=PROTECT_JOB, which job
  risk_tolerance: enum {LOW, MEDIUM, HIGH}

Invariants:
  - if objective=PROTECT_JOB, protected_job_id must not be None
  - protected_job_id, if present, must refer to an actual job in config
```

### ScenarioSpec

```
ScenarioSpec:
  type: enum {BASELINE, RUSH_ARRIVES, M2_SLOWDOWN}
  label: str                 # human-readable e.g., "Baseline", "Rush Job J2"
  modifications: dict        # scenario-specific parameters:
    - BASELINE: {}
    - RUSH_ARRIVES: {
        rush_job_id: str,    # e.g., "J2" (must be an existing job ID)
        arrival_time: int,   # e.g., 2 (arrives at hour 2)
        due_time: int,       # e.g., 10 (due at hour 10)
      }
    - M2_SLOWDOWN: {
        machine_id: str,     # which machine (usually "M2")
        slowdown_factor: float,  # e.g., 2.0 = 2x slower
        start_time: int,     # e.g., 8
        end_time: int,       # e.g., 14
      }

Invariants:
  - type is one of the three enums
  - modifications dict must match the schema for that type
  - rush_job_id (if present) MUST be an existing job ID from FactoryConfig
  - machine_id (if present) must refer to an actual machine
  - start_time < end_time and both in [0, time_horizon]
```

### SimulationResult

```
SimulationResult:
  scenario_label: str        # e.g., "Baseline"
  job_timelines: dict[str, JobTimeline]  # job_id → timeline
  machine_allocations: dict[str, list[Allocation]]  # machine_id → allocations
  makespan: int              # total time to complete all jobs (in hours)

JobTimeline:
  job_id: str
  steps_timeline: list[StepTimeline]
  completion_time: int       # hour when job finishes (integer)
  due_time: int              # hour job is due (integer)
  is_late: bool

StepTimeline:
  step_id: str
  machine_id: str
  start_time: int            # hour (integer)
  end_time: int              # hour (integer)
  duration_hours: int        # hours (integer)

Allocation:
  step_id: str
  start_time: int            # hour (integer)
  end_time: int              # hour (integer)

Invariants:
  - all job_ids in job_timelines refer to actual jobs in scenario
  - all step/machine IDs are valid
  - no overlapping allocations on same machine
  - completion_time >= due_time iff is_late = True
```

### ScenarioMetrics

```
ScenarioMetrics:
  scenario_label: str
  num_jobs: int
  num_late_jobs: int
  late_job_ids: list[str]
  max_lateness_hours: int    # worst-case lateness
  avg_lateness_hours: float  # average lateness across all jobs
  makespan_hours: int        # total hours
  bottleneck_machine_id: str # machine with highest utilization or critical path
  utilization_by_machine: dict[str, float]  # e.g., {"M1": 0.75, "M2": 0.95}

Invariants:
  - num_late_jobs = len(late_job_ids)
  - late_job_ids ⊆ all job_ids from scenario
  - bottleneck_machine_id is an actual machine
  - utilization values in [0.0, 1.0]
```

### Briefing

```
Briefing:
  markdown: str              # full markdown output from Briefing Agent

Invariants:
  - markdown is non-empty and valid markdown
  - briefing should reference only known job/machine IDs (validated via prompt design and review, not automated parsing)
```

### FactoryState (Orchestrator Shared State)

```
FactoryState:
  factory: FactoryConfig
  user_input: str            # original planner text

  # Step 2: Intent parsing
  intent: ScenarioIntent | None
  intent_error: str | None

  # Step 3: Futures generation
  scenarios: list[ScenarioSpec]
  futures_error: str | None

  # Step 4 & 5: Simulation and metrics
  sim_results: dict[str, SimulationResult]  # scenario_label → result

  # Step 5: Metrics
  metrics: dict[str, ScenarioMetrics]  # scenario_label → metrics

  # Step 6: Briefing
  briefing_markdown: str | None
  briefing_error: str | None

  # Metadata
  pipeline_completed: bool
  pipeline_errors: list[str]  # list of all non-fatal errors
  logs: list[str]  # one log per step
```

---

## 5. Agent Definitions & Prompt Skeletons

### 5.1 Intent Agent

**Responsibility**: Parse planner's free-form text into a structured `ScenarioIntent`.

**Role**: Understand what the planner cares about today, translate ambiguous language into enums and job references.

**Input**:
- Planner's free-form text (1–3 sentences)
- Brief summary of available jobs (names, ids)
- Brief summary of available machines (names, ids)

**Output**:
- `ScenarioIntent` as JSON (schema strictly validated)

**Constraints**:
- ✅ Must choose `objective` from {`BASELINE`, `RUSH_FIRST`, `BALANCED`, `PROTECT_JOB`}
- ✅ If `objective=PROTECT_JOB`, must set `protected_job_id` to an actual job ID (or None if unclear, then default to `BALANCED`)
- ✅ `risk_tolerance` from {`LOW`, `MEDIUM`, `HIGH`}
- ❌ Cannot invent new jobs or machines
- ❌ Cannot set protected_job_id to a non-existent job; must fail validation or fallback to `BALANCED`
- ✅ If ambiguous, use defaults: `objective=BALANCED`, `risk_tolerance=MEDIUM`

**Prompt Skeleton**:

```
# System
You are a factory operations interpreter. Your job is to read a planner's
text description of their priorities for today and extract structured intent.

You will output ONLY valid JSON matching the schema below. Do not add explanation
or prose.

# Schema
{
  "objective": "BASELINE | RUSH_FIRST | BALANCED | PROTECT_JOB",
  "protected_job_id": "null or <job_id>",
  "risk_tolerance": "LOW | MEDIUM | HIGH"
}

# Definitions
- BASELINE: Run the day as planned with no special modifications.
- RUSH_FIRST: Prioritize expediting a rush order or critical job above all else.
- BALANCED: Minimize total lateness and bottlenecks fairly across all jobs.
- PROTECT_JOB: Ensure a specific named job completes on time, accepting risk elsewhere.
- risk_tolerance:
  - LOW: Avoid any scenarios with lateness; want high confidence.
  - MEDIUM: Accept some lateness in non-critical jobs if it protects the objective.
  - HIGH: Will accept significant disruption elsewhere to protect the objective.

# Available Jobs
[Factory config: list job names and IDs here]

# Available Machines
[Factory config: list machine names and IDs here]

# Planner Input
{user_text}

# Respond with ONLY the JSON object, no explanation.
```

**Example**:
- Input: "We have a rush order for J2 today, it's critical. J3 is also important. I can accept some delay on J1."
- Output: `{"objective": "RUSH_FIRST", "protected_job_id": null, "risk_tolerance": "HIGH"}`

---

### 5.2 Futures Agent

**Responsibility**: Given a `ScenarioIntent`, produce 2–3 `ScenarioSpec`s from a **closed set** of scenario types.

**Role**: Translate abstract intent into concrete, simulatable scenarios. No new scenario types; only parameterization of fixed types.

**Input**:
- `FactoryConfig` summary
- `ScenarioIntent`

**Output**:
- List of 2–3 `ScenarioSpec` objects (JSON)

**Constraints**:
- ✅ Always include `BASELINE` scenario
- ✅ Choose secondary scenarios from {`RUSH_ARRIVES`, `M2_SLOWDOWN`}
- ✅ For `RUSH_ARRIVES`: pick an **existing job ID** from the factory config, set arrival time and due time within plausible bounds (e.g., arrival in [1,6], due within time_horizon)
- ✅ For `M2_SLOWDOWN`: pick slowdown_factor (1.5–3.0), start_time, end_time forming a contiguous window in [0, time_horizon]
- ❌ Cannot invent new scenario types
- ❌ Cannot reference non-existent jobs or machines
- ❌ Cannot create new synthetic rush job definitions
- ✅ Label each scenario with a short, human-readable name

**Prompt Skeleton**:

```
# System
You are a factory scenario planner. Your job is to take a planner's intent
and generate 2–3 concrete scenarios that explore the day's possibilities.

You will output ONLY valid JSON. Do not add explanation.

# Scenario Types (Closed Set)
1. BASELINE: No modifications.
2. RUSH_ARRIVES: An existing job from the factory is injected as a rush instance,
   arriving later in the day and with a tighter due time, creating scheduling conflict.
   You choose: which existing job to rush, when it arrives, when it must be done.
3. M2_SLOWDOWN: Machine M2 is slow or partially unavailable.
   You choose: slowdown factor (1.5–3.0), when it starts, how long it lasts.

# Schema (return a list of 2–3 objects)
[
  {
    "type": "BASELINE | RUSH_ARRIVES | M2_SLOWDOWN",
    "label": "<human-readable label>",
    "modifications": {
      // BASELINE: {} (no modifications)
      // RUSH_ARRIVES: { "rush_job_id": str (existing job ID), "arrival_time": int, "due_time": int }
      // M2_SLOWDOWN: { "machine_id": str, "slowdown_factor": float, "start_time": int, "end_time": int }
    }
  },
  ...
]

# FactoryConfig Summary
[Provide machine list, job list, time_horizon]

# Planner Intent
{intent JSON}

# Respond with ONLY the JSON array, no explanation.
```

**Example**:
- Intent: `{"objective": "RUSH_FIRST", "protected_job_id": null, "risk_tolerance": "HIGH"}`
- Output:
  ```json
  [
    {"type": "BASELINE", "label": "Baseline Day", "modifications": {}},
    {"type": "RUSH_ARRIVES", "label": "Rush J2 Order", "modifications": {"rush_job_id": "J2", "arrival_time": 2, "due_time": 12}},
    {"type": "M2_SLOWDOWN", "label": "M2 Slowdown (8–14h)", "modifications": {"machine_id": "M2", "slowdown_factor": 2.0, "start_time": 8, "end_time": 14}}
  ]
  ```

---

### 5.3 Briefing Agent

**Responsibility**: Convert metrics from multiple scenarios into a human-readable morning briefing.

**Role**: Translate simulation results into actionable, narrative insight. No invented IDs or jobs.

**Input**:
- `FactoryConfig` summary
- List of scenarios (labels and types)
- `ScenarioMetrics` for each scenario
- Planner's original intent

**Output**:
- Markdown text following a fixed structure (stored as `briefing_markdown: str`)
- ~500–800 words

**Constraints**:
- ✅ All job/machine IDs should be real (from config or scenario); briefing correctness is a behavioral goal enforced via prompt and review
- ✅ All metrics must be cited correctly (lateness, bottleneck, utilization)
- ✅ Tone: operational, concise, no fluff
- ❌ No invented jobs, machines, or metrics
- ❌ No made-up recommendations that contradict the metrics
- ✅ Acknowledge limitations of the model (single day, toy world, no breakdowns)

**Fixed Section Template**:

```
# Morning Briefing: [Date/Time]

## Today at a Glance
[1–2 sentences summarizing the single biggest risk and one key recommendation]

## Scenarios Analyzed
[List the scenarios with brief explanations (1 sentence each)]

## Key Risks
- [bullet 1: if job X late in scenario Y, by Z hours, due to machine M bottleneck]
- [bullet 2: if slowdown scenario, which jobs are most impacted and why]
- [bullet 3: machine utilization trends across scenarios]

## Jobs at Risk
[Table or list: which jobs are late in which scenarios, and by how much]

## Bottleneck Machines
[Per scenario: which machine is the constraint and why (utilization or critical path)]

## Recommended Actions
- [Action 1: based on metrics, suggest concrete reordering or escalation]
- [Action 2: if protecting a job, what can be de-prioritized]
- [Action 3: if slowdown risk, what's the mitigation]

## Limitations of This Model
[2–3 sentences: single day, no real disruptions, toy world, cannot predict material delays,
employee absence, equipment failure, etc.]
```

**Prompt Skeleton**:

```
# System
You are a factory operations briefing writer. Your job is to translate
simulation metrics into a clear, actionable morning briefing for a plant manager.

Use ONLY the data provided. Do not invent jobs, machines, or scenarios.
Output markdown following the template below.

# FactoryConfig Summary
[Machines and jobs summary]

# Scenarios Analyzed
{scenario_labels and types}

# Metrics Per Scenario
{ScenarioMetrics for each scenario}

# Planner's Original Intent
{ScenarioIntent}

# Template (do not skip sections)
## Today at a Glance
...

## Scenarios Analyzed
...

## Key Risks
...

## Jobs at Risk
...

## Bottleneck Machines
...

## Recommended Actions
...

## Limitations of This Model
...

# Output only markdown, following the template above.
```

**Example Briefing Snippet**:

```markdown
# Morning Briefing: 2025-11-19

## Today at a Glance
Baseline day is feasible with M2 as the bottleneck; however, a rush J2 scenario
creates significant risk of J1 lateness (4+ hours). Recommend expediting J1 before
shift start or deprioritizing non-critical work.

## Scenarios Analyzed
- **Baseline**: No modifications, standard job queue.
- **Rush J2**: J2 injected as rush at hour 2, due at hour 12.
- **M2 Slowdown (8–14h)**: M2 operates at 2x duration due to maintenance.

## Key Risks
- J1 is 4 hours late in the rush scenario; M2 bottleneck worsens in slowdown scenario.
- M2 utilization jumps from 85% (baseline) to 100% (slowdown) between hours 8–14.
- Slowdown scenario leaves J3 incomplete by end-of-day if not mitigated.

## Jobs at Risk
| Job | Baseline | Rush J2 | M2 Slowdown |
|-----|----------|---------|-------------|
| J1  | On-time  | 4h late | 2h late     |
| J2  | On-time  | On-time | 1h late     |
| J3  | On-time  | On-time | On-time     |

## Bottleneck Machines
- **Baseline**: M2 (85% utilization, critical path)
- **Rush J2**: M2 (95% utilization)
- **M2 Slowdown**: M2 (100% utilization, 8–14h window)

## Recommended Actions
- Start J1 at hour 0; defer discretionary work to create buffer.
- If M2 slowdown occurs, consider shifting non-M2 work (e.g., final packing) to afternoon.
- Escalate to materials team if rush J2 dependencies are not secured by hour 1.

## Limitations of This Model
This briefing assumes deterministic job durations and no external disruptions (material
delays, equipment breakdowns, employee absence). Real factory operations face variability;
treat recommendations as guidance only.
```

---

## 6. Orchestrator & Flow

### FactoryState Definition

```python
@dataclass
class FactoryState:
    # Immutable
    factory: FactoryConfig
    user_input: str

    # Step 2: Intent parsing
    intent: ScenarioIntent | None = None
    intent_error: str | None = None

    # Step 3: Futures generation
    scenarios: list[ScenarioSpec] = field(default_factory=list)
    futures_error: str | None = None

    # Step 4 & 5: Simulation and metrics
    sim_results: dict[str, SimulationResult] = field(default_factory=dict)
    metrics: dict[str, ScenarioMetrics] = field(default_factory=dict)

    # Step 6: Briefing
    briefing_markdown: str | None = None
    briefing_error: str | None = None

    # Metadata
    pipeline_completed: bool = False
    pipeline_errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
```

### Pipeline Flow: `run_pipeline(user_text: str) -> FactoryState`

**Step 0: Initialize**
- Build hardcoded `FactoryConfig` (3 machines, 3 baseline jobs, 24h horizon)
- Create `FactoryState` with `user_input=user_text`, all else empty

**Step 1: Intent Parsing**
- Call `Intent Agent` with user_text + factory summary
- Validate output against `ScenarioIntent` schema
  - If valid: set `state.intent`
  - If invalid: set `state.intent_error`, log error, **fall back to default** `ScenarioIntent(objective=BALANCED, risk_tolerance=MEDIUM, protected_job_id=None)`
- Log: `"Intent Agent: {latency}ms, valid={outcome}, intent={intent}"`

**Step 2: Futures Generation**
- Call `Futures Agent` with factory summary + current `state.intent`
- Validate output against `list[ScenarioSpec]` schema
  - Each scenario's `modifications` dict must match its type schema
  - All job_ids in `RUSH_ARRIVES` must be **existing job IDs** from factory config
  - All machine_ids must exist in factory
  - If invalid: set `state.futures_error`, log, **fall back to default**: `[BASELINE, RUSH_ARRIVES(J2, 2, 12), M2_SLOWDOWN(M2, 2.0, 8, 14)]`
- Log: `"Futures Agent: {latency}ms, valid={outcome}, scenarios={[label for s in scenarios]}"`

**Step 3: Simulation**
- For each scenario in `state.scenarios`:
  - Apply modifications to base factory config (e.g., treat rush job as arriving later with tight due time; slow machine M2)
  - Call `simulate(modified_factory, scenario_spec)` (deterministic, no randomness)
  - Store result in `state.sim_results[scenario.label]`
  - Log: `"Simulation [{scenario.label}]: {latency}ms, makespan={result.makespan}h, late_jobs={len(result.late_jobs)}"`

**Step 4: Metrics Computation**
- For each `SimulationResult` in `state.sim_results`:
  - Call `compute_metrics(result)` → `ScenarioMetrics`
  - Store in `state.metrics[scenario.label]`
  - Log: `"Metrics [{scenario.label}]: late_count={metrics.num_late_jobs}, bottleneck={metrics.bottleneck_machine_id}"`

**Step 5: Briefing Generation**
- Call `Briefing Agent` with:
  - Factory summary
  - List of scenarios (labels, types)
  - All `state.metrics`
  - Current `state.intent`
- Validate output:
  - Must be valid markdown (non-empty string)
  - Store in `state.briefing_markdown`
  - If invalid: set `state.briefing_error`, use fallback template
- Log: `"Briefing Agent: {latency}ms, valid={outcome}, word_count={N}"`

**Step 6: Finalize**
- Set `state.pipeline_completed = True`
- If any step had non-fatal errors, append to `state.pipeline_errors`
- Return `state`

### Validation Functions (Explicit)

**validate_scenario_intent(intent_dict) -> (ScenarioIntent, str | None)**
- Check that `objective` is in allowed enum
- Check that `risk_tolerance` is in allowed enum
- If `objective=PROTECT_JOB`, check that `protected_job_id` is a real job ID
- Return (valid object, None) or (None, error message)

**validate_scenario_spec(spec_dict, factory) -> (ScenarioSpec, str | None)**
- Check that `type` is in {BASELINE, RUSH_ARRIVES, M2_SLOWDOWN}
- Check that `modifications` dict matches the schema for that type
- For RUSH_ARRIVES: validate that `rush_job_id` is an **existing** job ID in factory
- For RUSH_ARRIVES: validate arrival_time, due_time in [0, time_horizon]
- For M2_SLOWDOWN: validate slowdown_factor > 1, start_time < end_time
- Check that all referenced machine_ids exist
- Return (valid object, None) or (None, error message)

### Logging Standards

Each agent call logs:
```
{Timestamp} | {Agent Name} | Latency: {ms} | Status: {valid|invalid|error} | Input: {summary, truncated} | Output: {summary, truncated}
```

Example:
```
2025-11-19 06:30:15 | Intent Agent | Latency: 245ms | Status: valid | Intent: RUSH_FIRST, risk=HIGH | Fallback: false
2025-11-19 06:30:16 | Futures Agent | Latency: 312ms | Status: valid | Scenarios: [Baseline, Rush J2, M2 Slowdown]
2025-11-19 06:30:17 | Simulation [Baseline] | Latency: 45ms | Makespan: 18h | Late jobs: 0
2025-11-19 06:30:17 | Simulation [Rush J2] | Latency: 48ms | Makespan: 20h | Late jobs: 1 (J1)
2025-11-19 06:30:18 | Briefing Agent | Latency: 289ms | Status: valid | Word count: 650
Pipeline completed in 1209ms, errors: 0
```

---

## 7. World & Scenario Design

### Toy Factory World

**Machines** (3):
- **M1 ("Assembly")**: available all day, moderate load
- **M2 ("Drill/Mill")**: available all day, **high load** (bottleneck)
- **M3 ("Pack/Ship")**: available all day, moderate load

**Baseline Jobs** (3):
- **J1 ("Widget A")**: 3 steps (M1: 1h, M2: 3h, M3: 1h), due at 12h
  - Sequence: M1(1h) → M2(3h) → M3(1h) = 5h total
  - Deliberate M2 conflict with J2
- **J2 ("Gadget B")**: 3 steps (M1: 1h, M2: 2h, M3: 1h), due at 14h
  - Sequence: M1(1h) → M2(2h) → M3(1h) = 4h total
  - Deliberate M2 conflict with J1
- **J3 ("Part C")**: 2 steps (M2: 1h, M3: 2h), due at 16h
  - Sequence: M2(1h) → M3(2h) = 3h total
  - Shares M2 with J1, J2

**Conflict & Bottleneck**:
- All three jobs need M2; total M2 demand is 3 + 2 + 1 = 6 hours
- M2 is available for 24 hours, but scheduling wins and losses create lateness in tight scenarios
- M1 and M3 have less contention
- Expected bottleneck: **M2 in all scenarios**

**Time Horizon**: 24 hours (hours 0–24, all integer)

**Scheduling Heuristic**: Earliest Due Date (EDD)
- Sort jobs by due time
- Schedule each job's steps greedily: start as early as possible given dependencies and machine availability
- All times are in integer hours; no fractional scheduling

### Scenario Types & Expectations

#### BASELINE
- No modifications; baseline jobs run as scheduled
- **Expected outcome**:
  - All jobs complete on time (well within due times)
  - Makespan ≈ 5–6 hours (critical path ≈ J1: 5h)
  - M2 utilization ≈ 85% (6h allocated)
  - Zero late jobs

#### RUSH_ARRIVES
- An existing job (e.g., J2) is injected as a rush instance: arrives at an integer hour (e.g., hour 2) and has a tighter due time (e.g., hour 12), creating scheduling conflict
- This reuses the existing job's step definitions; no new job definition is created
- **Expected outcome**:
  - Baseline job (e.g., J1) may be delayed due to rush priority
  - At least one job late by 2–4 hours
  - Makespan ≈ 8–10 hours
  - M2 utilization ≈ 95% (close to saturation)
  - Example: J1 delayed if rush takes priority

#### M2_SLOWDOWN
- Machine M2 operation is slowed for a contiguous integer-hour window (e.g., hours 8–14)
- Slowdown applies as a multiplicative factor (e.g., 2.0x = double duration) rounded to the nearest integer hour
- Represents maintenance, tooling change, operator shortage, etc.
- **Expected outcome**:
  - Jobs using M2 in that window are severely impacted
  - J1 and J2 most affected (both use M2 heavily)
  - J3 may shift to earlier or later
  - At least one job late by 1–3 hours
  - Makespan ≈ 10–12 hours
  - M2 utilization ≈ 100% in affected window

### Tunability Notes

These outcomes are targets; exact numbers depend on:
- Machine scheduling order (EDD vs. FCFS)
- How disruptions are applied (does slowdown prevent scheduling or just slow execution?)
- Exact step sizes and due times

**Tuning strategy**:
- If baseline jobs are too loose, increase baseline job sizes or reduce due times
- If rush scenario shows no lateness, decrease rush due time or increase baseline contention
- If M2 slowdown doesn't propagate impact, increase slowdown_factor or reduce available_end for M2

---

## 8. Simulation & Metrics

### Scheduling Algorithm

**Algorithm: Earliest Due Date (EDD) + Greedy Machine Allocation**

Input: `factory_config` (machines, jobs), `scenario_spec` (modifications)
Output: `SimulationResult` (job timelines, allocations)

**Pseudocode**:

```
1. Apply modifications to factory_config:
   - If RUSH_ARRIVES: treat rush_job as arriving at arrival_time with tight due_time
   - If M2_SLOWDOWN: adjust M2's effective duration (multiply step times by slowdown_factor)

2. Sort all jobs by due_time (earliest first)

3. For each job in sorted order:
   For each step in job's step sequence:
     Find earliest hour slot on step.machine_id such that:
       - Slot is after all precedent steps complete
       - Slot is within [available_start, available_end]
       - No other step occupies [slot, slot + duration)
     Allocate step to [slot, slot + duration)
     Record start_time, end_time (both in hours)

4. Compute metrics:
   - job.completion_time = max(end_time of all steps)
   - job.is_late = completion_time > due_time
   - Bottleneck machine = machine with highest total allocated time
```

**Time Model**:
- Discrete time units: integer hours only (0, 1, 2, ..., 24)
- Single day: hours 0–24
- No preemption: once a step starts, it runs to completion
- Step duration = `job_step.duration_hours` (integer hours)
- All start times, end times, and arrival times are integers
- No fractional hours or time conversions
- No concurrent jobs on same machine (first-come, first-served within available window)

### Determinism

- Same input (FactoryConfig, ScenarioSpec) always yields same output
- No randomness in scheduling or execution
- Reproducible for testing and logging

### SimulationResult Details

```python
@dataclass
class SimulationResult:
    scenario_label: str
    job_timelines: dict[str, JobTimeline]  # job_id → timeline
    machine_allocations: dict[str, list[Allocation]]  # machine_id → allocations
    makespan: int  # hours from 0 to last completion (integer)

    @property
    def late_jobs(self) -> list[str]:
        return [jid for jid, tl in self.job_timelines.items() if tl.is_late]
```

### ScenarioMetrics Details

```python
@dataclass
class ScenarioMetrics:
    scenario_label: str
    num_jobs: int
    num_late_jobs: int
    late_job_ids: list[str]
    max_lateness_hours: int  # max(completion - due) over all jobs
    avg_lateness_hours: float  # avg over all jobs (0 if none late)
    makespan_hours: int
    bottleneck_machine_id: str  # machine with longest cumulative allocation
    utilization_by_machine: dict[str, float]  # allocated_hours / available_hours

    @staticmethod
    def from_result(result: SimulationResult, factory: FactoryConfig) -> ScenarioMetrics:
        """Compute metrics from simulation result."""
        # Count late jobs
        num_late = len(result.late_jobs)
        max_late = max([tl.completion_time - tl.due_time
                        for tl in result.job_timelines.values()
                        if tl.is_late], default=0)
        avg_late = sum([max(0, tl.completion_time - tl.due_time)
                        for tl in result.job_timelines.values()]) / len(result.job_timelines)

        # Bottleneck: machine with most allocation
        total_per_machine = {}
        for allocs in result.machine_allocations.values():
            machine_id = allocs[0].machine_id  # all allocations on same machine
            total_per_machine[machine_id] = sum(a.duration for a in allocs)
        bottleneck = max(total_per_machine.keys(),
                        key=lambda m: total_per_machine[m])

        # Utilization: allocated / available per machine
        util = {}
        for machine in factory.machines:
            allocated = total_per_machine.get(machine.id, 0)
            available = machine.available_end - machine.available_start
            util[machine.id] = allocated / available if available > 0 else 0.0

        return ScenarioMetrics(
            scenario_label=result.scenario_label,
            num_jobs=len(result.job_timelines),
            num_late_jobs=num_late,
            late_job_ids=result.late_jobs,
            max_lateness_hours=max_late,
            avg_lateness_hours=avg_late,
            makespan_hours=result.makespan,
            bottleneck_machine_id=bottleneck,
            utilization_by_machine=util
        )
```

---

## 9. Briefing Structure

The Briefing Agent must produce markdown with exactly these sections (in order):

1. **Today at a Glance** (1–2 sentences)
   - Summary: single biggest risk or recommendation
   - Data: highest lateness any job in any scenario, bottleneck machine
   - Tone: urgent but professional

2. **Scenarios Analyzed** (bulleted list, ~1 sentence each)
   - List each scenario with brief explanation (type + key parameters)
   - Example: "Baseline Day: No modifications, standard job queue"
   - Example: "Rush J2 Order: J2 injected as rush at 2h, due at 12h"

3. **Key Risks** (bulleted list, 3–5 bullets)
   - For each scenario, call out if any job is late and why (machine bottleneck)
   - Example: "M2 bottleneck worsens in rush scenario; J1 is 4 hours late"
   - Cite utilization trends (e.g., "M2 jumps from 85% to 95%")

4. **Jobs at Risk** (table or list)
   - Per job: which scenarios have it late, by how many hours
   - Example: "J1: on-time in baseline, 4h late in rush, 2h late in slowdown"

5. **Bottleneck Machines** (per-scenario summary)
   - Which machine is the constraint in each scenario
   - Why (utilization, critical path, specific step)
   - Example: "Baseline: M2 at 85% utilization; Rush: M2 at 100%"

6. **Recommended Actions** (bulleted list, 2–4 bullets)
   - Actionable, concrete steps based on metrics
   - Example: "Start J1 at hour 0; defer discretionary work"
   - Example: "If M2 slowdown occurs, shift final packing to afternoon"

7. **Limitations of This Model** (2–3 sentences)
   - Single day, toy world, deterministic, no real disruptions, no breakdowns
   - Encourage human judgment

**Word count**: ~500–800 words total (including template structure).

**Constraints**:
- All job/machine IDs must exist in factory or scenario
- All metrics must be cited correctly (lateness, utilization, makespan)
- No invented scenarios, jobs, or metrics
- Markdown must be valid (no syntax errors)

---

## 10. Quality Bar, Logging, & Success Criteria

### Invariants (Must Always Hold)

1. **No overlapping machine allocations**: No step interval [t1, t2) on a machine overlaps with any other step [t1', t2').
2. **All IDs refer to real entities**: Every job_id, machine_id, step_id in results/metrics must exist in factory config.
3. **Briefing ID correctness (soft goal)**: All job/machine IDs in briefing text should correspond to real jobs/machines. This is enforced via prompt design and human review, not automated parsing.
4. **Transitive lateness**: If job A is late, at least one of its steps must have completion_time > due_time; transitive via dependencies.
5. **Agent output validation before use**: Every agent response validated against schema before entering simulation or subsequent agents.

### Minimal Logging

**Per agent call**:
```
{timestamp} | {Agent Name} | Latency: {ms} | Status: {valid/invalid/error} | Input: {truncated} | Output: {truncated}
```

**Per simulation**:
```
{timestamp} | Simulation [{scenario_label}] | Latency: {ms} | Makespan: {h}, Late: {count}, Bottleneck: {machine_id}
```

**Pipeline summary** (at end):
```
Pipeline completed in {total_ms}ms | Scenarios: {N} | Errors: {count} | Briefing: {word_count} words
```

### Success Criteria for Demo

**Technical**:
- ✅ Pipeline runs end-to-end without unhandled exceptions
- ✅ All three scenarios produce distinct metrics (lateness, bottleneck, makespan differ)
- ✅ Briefing references real job/machine IDs only (soft goal: enforced via prompt and review, not code validation)
- ✅ Deterministic: same user text → same briefing (reproducible)
- ✅ Total latency <2 seconds (orchestration + 3 agents + 3 simulations)
- ✅ All times are integer hours (no fractional durations or conversions)

**Functional**:
- ✅ Briefing correctly identifies bottleneck machine(s) and late jobs per scenario
- ✅ Recommended actions are sensible (reorder, de-prioritize, expedite based on metrics)
- ✅ Limitations section present and honest

**Experiential** (for CTO reader):
- ✅ Code is clean, explicit, no magic
- ✅ Orchestrator is easy to trace step-by-step
- ✅ Agent boundaries are clear; LLM does not touch simulation
- ✅ Validation happens visibly at every contract boundary
- ✅ System feels like it "understands" the factory world (not just text generation)

---

## 11. Non-Goals

This demo explicitly does **NOT** include:

- ❌ **Real data integration**: No MES, ERP, or manufacturing execution system API integration
- ❌ **Optimization solver**: No OR-Tools, Cplex, Gurobi, or constraint programming
- ❌ **Stochastic modeling**: No Monte Carlo, no probability distributions
- ❌ **LangGraph or orchestration framework**: Explicit hand-rolled orchestrator only
- ❌ **RAG or document retrieval**: No vector databases, no knowledge bases
- ❌ **Web UI**: CLI or markdown text output only
- ❌ **Multi-agent concurrency**: All agents called sequentially
- ❌ **Persistent storage**: No database; state lives in memory during pipeline
- ❌ **Real disruption modeling**: No stochastic breakdowns, no material delay simulation
- ❌ **Fairness constraints**: No optimization for equity or job prioritization beyond baseline heuristic
- ❌ **Multi-day or rolling horizon**: Single day only
- ❌ **Machine concurrency fields**: Concurrent_jobs and related fields not implemented (assumed 1 job per machine)
- ❌ **Automated briefing ID validation**: No regex parsing or programmatic ID verification of briefing text
- ❌ **Elaborate logging structures**: Simple text-based logs only, no structured logging infrastructure

---

## 12. Implementation Roadmap (For Clarity)

This spec can be implemented in the following order:

1. **Data models** (30 min): Define all types in a single module
2. **Toy factory config** (15 min): Hardcode 3 machines, 3 jobs with conflict
3. **Simulation engine** (60 min): EDD scheduler, machine allocation, timeline computation
4. **Metrics** (20 min): Compute lateness, bottleneck, utilization from results
5. **Orchestrator & state** (30 min): FactoryState, validation, pipeline flow
6. **Briefing template** (20 min): Fixed sections, markdown formatting
7. **Agent prompts** (30 min): Three prompt templates, send to Claude API
8. **Integration & testing** (30 min): E2E pipeline, error handling, sample run
9. **Logging & polish** (15 min): Add logging, clean output

**Total**: ~4 hours for a strong engineer.

---

## 13. Example: End-to-End User Interaction

**User Input**:
```
"We have a rush order for J2 today. J3 is also important.
I can accept some delay on J1 if needed. What should I expect?"
```

**Orchestrator Output (Briefing)**:
```markdown
# Morning Briefing: 2025-11-19

## Today at a Glance
The rush J2 scenario puts heavy pressure on M2 and risks pushing J1 past its due time.
Recommend either expediting J1 before the rush arrives or accepting 2–3 hour delay on J1.

## Scenarios Analyzed
- **Baseline Day**: Standard job queue (J1, J2, J3), no rush.
- **Rush J2 Order**: J2 injected as rush at 2h, due at 12h.
- **M2 Slowdown (8–14h)**: M2 operates at 2x duration for 6 hours due to maintenance.

## Key Risks
- **Rush J2 scenario**: J1 delayed to 16h (4h late) because M2 is monopolized by rush. J3 stays on-time.
- **M2 Slowdown scenario**: Both J1 and J2 slide; M2 utilization reaches 100% during 8–14h window.
- **Machine M2 is the bottleneck in all three scenarios**: 85% baseline, 100% rush, 100% slowdown.

## Jobs at Risk
| Job | Baseline  | Rush J2 | M2 Slowdown |
|-----|-----------|---------|-------------|
| J1  | On-time   | 4h late | 2h late     |
| J2  | On-time   | On-time | 1h late     |
| J3  | On-time   | On-time | On-time     |

## Bottleneck Machines
- **Baseline**: M2 (85% utilization, 6h allocated of ~7h available in critical window)
- **Rush J2**: M2 (100% utilization; rush + baseline jobs compete)
- **M2 Slowdown**: M2 (100% utilization during 8–14h maintenance window)

## Recommended Actions
- **For rush scenario**: Start J1 at hour 0 (don't delay); prioritize rush J2 at hour 2+. If J1 lateness is unacceptable, negotiate rush due time or defer J3 to next day.
- **For slowdown scenario**: Avoid starting M2 jobs between 8–14h if possible; shift J3 earlier (before 8h) or later (after 14h).
- **General**: Escalate to materials team if rush J2 dependencies are not secured by hour 1.

## Limitations of This Model
This briefing assumes deterministic job durations (no variability), no real equipment breakdowns, and no material or supply chain delays. The model is a toy world with 3 machines and 3 jobs; it does not account for employee absence, lunch breaks, or other operational realities. Use as a guide; always verify with floor manager.
```

**Planner Reads Briefing**:
> "Good, so M2 is the real constraint. If I need to protect J3 (which I do), I should just accept that J1 might slip in the rush case. But the slowdown is also bad—I should talk to the maintenance team about scheduling it off-peak, or I need buffer."

**Decision**: Reorder jobs, escalate maintenance timing.

---

# End of Spec

This spec provides a complete, implementable blueprint for a 4-hour demo that demonstrates taste in multi-agent LLM orchestration, clean architecture, and the value of pairing agents with deterministic simulation. It is tight, unambiguous, and ready for a strong engineer (with Claude Code) to build.
