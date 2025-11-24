# Factory Day Simulator

Multi-agent LLM orchestration paired with deterministic factory scheduling simulation. The system accepts free-form factory descriptions and operating situations, generates 1–3 scenario variations via LLM, simulates each with a deterministic EDD scheduler, and produces an actionable markdown briefing. **LLM agents interpret inputs and generate outputs; the simulation core remains pure computation, fully deterministic, and auditable.**

## System Overview

### What It Does

Input: Free-form factory description + today's situation/priorities (text)

Output: JSON response containing:
- Parsed factory config (machines, jobs, routing)
- 1–3 scenario specifications (baseline, rush order, machine slowdown)
- Performance metrics per scenario (makespan, lateness, bottlenecks, utilization)
- Operational briefing (markdown summary with risks and recommendations)
- Optional debug payload (10-stage pipeline execution trace with per-stage details)

### Use Case

Factory planners and operations managers need to answer: "What will go wrong today? Which jobs are at risk? What can I do about it?" This system provides answers by simulating alternative futures and explaining risks in operational language, without manual what-if analysis.

### Core Value Proposition

1. **Multi-stage extraction with fallback** – Parses custom factory descriptions in 5 onboarding stages (O0–O4), falls back to toy factory on coverage failure
2. **Strict validation, no hallucination** – All LLM outputs validated against Pydantic schemas; agents can only reference real entities from the factory config
3. **Deterministic + LLM coordination** – Deterministic EDD scheduler at the core; LLM agents at interpretation (D1) and reporting (D5) boundaries only
4. **Full pipeline visibility** – Optional debug payload exposes all 10 stages (5 onboarding + 5 decision) with status, summaries, and errors

## High-Level Architecture

### Two Integrated Pipelines

**Onboarding Pipeline (O0–O4)**: Factory description → FactoryConfig

| Stage | Function | LLM? | Output |
|-------|----------|------|--------|
| **O0** | Explicit ID extraction | No | Set of detected machine/job IDs via regex |
| **O1** | Coarse structure enumeration | Yes | Machine & job names from description |
| **O2** | Fine extraction (jobs → steps) | Yes | Job routing with step durations |
| **O3** | Validate & normalize | No | Valid FactoryConfig (or empty) |
| **O4** | Coverage assessment | No | Assert 100% ID coverage or raise error |

**Decision Pipeline (D1–D5)**: Factory + situation → metrics + briefing

| Stage | Function | LLM? | Output |
|-------|----------|------|--------|
| **D1** | Intent classification | Yes | Scenario type (BASELINE / RUSH_ARRIVES / M2_SLOWDOWN) |
| **D2** | Futures expansion | Yes | 1–3 scenario variations |
| **D3** | Simulation | No | Scheduled steps, makespan, completion times (all deterministic) |
| **D4** | Metrics computation | No | Lateness, bottleneck machine, utilization per scenario |
| **D5** | Briefing generation | Yes | Markdown summary (risks, recommendations, caveats) |

**Fallback Behavior**:
- Onboarding stage O1–O4 fails → Set `used_default_factory=true`, fall back to toy factory (3 machines, 3 jobs)
- Decision stages D1–D5 fail → Use safe defaults (BASELINE spec, deterministic briefing template)
- Overall status = SUCCESS (all stages OK) | PARTIAL (onboarding fell back) | FAILED (decision stages failed)

### Mental Model: Three Scenario Types

**BASELINE**: Standard job queue, no disruptions. Expected: all jobs on-time, M2 bottleneck ~85% utilization.

**RUSH_ARRIVES**: One job promoted to rush (tighter due time). Example: "Rush J2 at hour 2, due at hour 12." Expected: 2–4h lateness on other jobs due to M2 contention.

**M2_SLOWDOWN**: Machine M2 operates slower (e.g., maintenance). Slowdown factor 2–3x multiplies step durations. Expected: M2 utilization → 100%, 1–3h lateness.

All scenarios run against the same factory; metrics are compared to identify risks and tradeoffs.

## Minimal Mental Model: The Toy Factory

The system includes a hardcoded toy factory for demonstration and fallback:

**Machines** (3):
- M1 (Assembly) – 1h capacity/day
- M2 (Drill/Mill) – bottleneck; 6h demand vs 24h available
- M3 (Pack/Ship) – 3h needed

**Jobs** (3):
- J1 (Widget A) – M1(1h) → M2(3h) → M3(1h), due 12h
- J2 (Gadget B) – M1(1h) → M2(2h) → M3(1h), due 14h
- J3 (Part C) – M2(1h) → M3(2h), due 16h

All three jobs compete for M2, creating a natural bottleneck that drives interesting scheduling conflicts.

## Debug Pipeline View & Accordion UI

The system optionally exposes a 10-stage execution trace via the `debug` field in API responses.

### Frontend Accordion Pattern

**PipelineSummary**: One-line status badge showing overall result
- Color-coded: 🟢 SUCCESS | 🟡 PARTIAL | 🔴 FAILED
- Shows onboarding/decision stage counts
- Warns if fallback to toy factory was triggered

**StageList (Accordion)**: All 10 stages grouped by pipeline

Each stage row displays:
- Status icon (✓ SUCCESS, ✗ FAILED, ○ SKIPPED)
- Stage ID (O0, D1, etc.) and human-readable name
- Summary text (auto-generated from summary dict)

Click stage → inline **StageDetailPanel** expands with:

| Section | Content | Example |
|---------|---------|---------|
| Header | Stage ID, name, status icon, metadata | "D1: Intent Classification – SUCCESS (gpt-4.1)" |
| Summary | Stage-specific key/value summary | "intent_scenario_type: RUSH_ARRIVES" |
| Errors | Error messages (if status=FAILED) | "[ValidationError] Invalid job_id: 'J999'" |
| Preview | Optional full payload JSON (if available) | Raw output from LLM |

### Stage Summaries (Per-Stage Details)

**O0 (Explicit ID Extraction)**:
- Detected machine IDs, job IDs, total count
- Pure regex, no LLM

**O1 (Coarse Structure)**:
- Count of coarse machines, coarse jobs extracted by LLM

**O2 (Fine Extraction)**:
- Machines with steps, jobs with steps, total steps extracted

**O3 (Normalization)**:
- Count of normalized machines, jobs after repair and deduplication

**O4 (Coverage Assessment)**:
- Detected vs. parsed ID sets; coverage ratios (0.0–1.0) per type
- Missing IDs (if any) that triggered fallback
- Boolean: 100% coverage achieved?

**D1 (Intent Classification)**:
- Detected scenario type (BASELINE, RUSH_ARRIVES, M2_SLOWDOWN)
- Whether intent context was successfully captured

**D2 (Futures Expansion)**:
- Number of scenario variations generated (1–3)
- Futures context available?

**D3 (Simulation)**:
- Number of scenarios simulated
- All succeeded? (boolean)

**D4 (Metrics Computation)**:
- Count of metrics computed (one per scenario)
- All succeeded?

**D5 (Briefing Generation)**:
- Length of generated briefing (chars)
- Non-empty? (boolean)

### Invariant Guarantees

The debug UI enforces these invariants:

1. **Overall Status Logic**: SUCCESS only if all stages are SUCCESS; FAILED if any DECISION/SIMULATION stage failed; PARTIAL if ONBOARDING failed but DECISION stages exist
2. **Stage Record Completeness**: Every stage record has id, name, kind, status, summary (dict), errors list, optional payload_preview
3. **Pipeline Continuity**: All 10 stages appear in output (SKIPPED only if early fallback)
4. **Scenario Count Consistency**: len(specs) == len(metrics) always (every scenario simulated has metrics)

## Project Structure

```
factory-simulator/
├── backend/
│   ├── models.py                    # Pydantic data models (contracts)
│   ├── world.py                     # Toy factory (3 machines, 3 jobs)
│   ├── sim.py                       # EDD scheduler + scenario application
│   ├── metrics.py                   # Metrics computation (makespan, lateness, etc.)
│   ├── llm.py                       # OpenAI JSON mode wrapper
│   ├── agents.py                    # 4 LLM-backed agents (Onboarding, Intent, Futures, Briefing)
│   ├── onboarding.py                # Multi-stage extraction (O0–O4)
│   ├── orchestrator.py              # Pipeline orchestration (run_pipeline, run_onboarded_pipeline)
│   ├── server.py                    # FastAPI HTTP server (POST /api/simulate, /api/onboard)
│   ├── debug_types.py               # Debug payload types (PipelineDebugPayload, etc.)
│   ├── pipeline_instrumentation.py  # Stage wrapping + debug collection
│   ├── serializer.py                # JSON serialization for enums/models
│   ├── main.py                      # CLI entrypoint
│   ├── config.py                    # Env vars (OPENAI_API_KEY, BACKEND_CORS_ORIGINS, etc.)
│   ├── tests/                       # ~9,000 LOC across 24 test files
│   │   ├── test_sim_*.py            # Scheduler & scenario tests
│   │   ├── test_metrics.py          # Metrics computation tests
│   │   ├── test_agents_*.py         # Agent behavior (mocked LLM)
│   │   ├── test_orchestrator.py     # End-to-end pipeline (926 LOC)
│   │   ├── test_onboarding_*.py     # 8 files – ID extraction, coverage, normalization
│   │   ├── test_server_*.py         # FastAPI endpoint tests
│   │   └── test_api_contracts.py    # Contract enforcement (snapshot assertions)
│   └── eval/
│       ├── invariants.py            # Factory & metrics invariant validators
│       ├── run_adversarial.py       # Adversarial test harness (475 LOC)
│       └── run_onboard_sanity.py    # Onboarding sanity checks
│
├── frontend/                         # React + Vite (TypeScript, 1,121 LOC)
│   ├── src/
│   │   ├── App.tsx                  # Main shell (282 LOC)
│   │   ├── api.ts                   # HTTP client (112 LOC)
│   │   ├── components/
│   │   │   ├── PipelineSummary.tsx  # Status badge (55 LOC)
│   │   │   ├── StageList.tsx        # Accordion (232 LOC)
│   │   │   └── StageDetailPanel.tsx # Detail view (335 LOC)
│   │   ├── types/
│   │   │   └── pipeline.ts          # Debug types (95 LOC)
│   │   └── *.css                    # Styling
│   └── vite.config.ts
│
├── API_CONTRACTS.md                 # Frozen HTTP contract specs
├── FACTORY_SIMULATOR_SPEC.md        # Complete technical specification
├── RUNTIME_SETUP_AND_TESTING.md     # Setup & testing guide
└── README.md                         # This file
```

## Setup & Run

### Installation

```bash
# Python dependencies
pip install -U openai pydantic pytest fastapi uvicorn

# Frontend dependencies (Node.js 16+)
cd frontend && npm install

# Environment
export OPENAI_API_KEY="sk-..."  # Required for LLM calls
```

Optional environment files (see `.env.example` in each directory):

**Backend** (`backend/.env`):
- `OPENAI_API_KEY` – OpenAI API key (or export in shell)
- `BACKEND_CORS_ORIGINS` – CORS whitelist; default `*`

**Frontend** (`frontend/.env`):
- `VITE_API_BASE_URL` – Backend URL; default `http://localhost:8000`

### Running the Backend

```bash
# API server (FastAPI)
uvicorn backend.server:app --reload
# → http://localhost:8000
# → Docs at http://localhost:8000/docs

# CLI (interactive or with argument)
python -m backend.main "we have a rush order for J2"
python -m backend.main  # interactive prompt
```

### Running the Frontend

```bash
cd frontend
npm run dev
# → http://localhost:5173
```

### Running Tests

```bash
# All tests (mocked LLM, no API calls)
python -m pytest -v

# Single file
python -m pytest backend/tests/test_sim_baseline.py -v

# With coverage
python -m pytest --cov=backend --cov-report=html
```

### Calling /api/simulate

```bash
curl -X POST http://localhost:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "factory_description": "3 machines (M1, M2, M3), 3 jobs (J1, J2, J3)",
    "situation_text": "we have a rush order for J2 today"
  }'
```

Response structure:
```json
{
  "factory": { "machines": [...], "jobs": [...] },
  "specs": [ { "scenario_type": "BASELINE", ... }, ... ],
  "metrics": [ { "makespan_hour": 5, "job_lateness": {...}, ... }, ... ],
  "briefing": "# Morning Briefing\n...",
  "meta": { "used_default_factory": false, "onboarding_errors": [], ... },
  "debug": { "overall_status": "SUCCESS", "stages": [...] }  // optional
}
```

### Programmatic Usage

```python
from backend.orchestrator import run_pipeline

result = run_pipeline("We have a rush order for J2 today")

# Returns dict with keys: factory, specs, results, metrics, briefing
print(result['briefing'])  # markdown string
print(len(result['specs']))  # 1–3 scenarios
```

## Core Concepts

### Deterministic Scheduler (EDD)

The simulation engine uses **Earliest Due Date (EDD)** heuristic with greedy machine allocation.

**Algorithm**:
1. Sort jobs by due_time_hour (earliest first)
2. For each job's steps (in order):
   - Find earliest available time on required machine
   - Respect step dependencies (previous step must complete first)
   - Allocate step to [earliest_start, earliest_start + duration)
3. Compute job completion times, makespan, bottleneck machine

**Invariants**:
- All times are integer hours (no fractional scheduling)
- No preemption; no step migration
- Fully deterministic: identical input → identical output always
- No randomness anywhere in simulation or metrics

**Example** (toy factory BASELINE scenario):
```
J1: M1[0–1] → M2[1–4] → M3[4–5]          (due 12, on-time)
J2: M1[1–2] → M2[4–6] → M3[5–6]          (due 14, on-time)
J3: M2[6–7] → M3[6–8]                     (due 16, on-time)

Makespan: 8 hours
Bottleneck: M2 (6h busy out of 8h available = 75% utilization)
```

### Metrics

Computed per scenario:

| Metric | Definition | Range |
|--------|-----------|-------|
| **makespan_hour** | Total elapsed time (last job completion) | ≥ 1 |
| **job_lateness** | dict[job_id → max(0, completion_time - due_time)] | ≥ 0 |
| **bottleneck_machine_id** | Machine with highest utilization | String (e.g., "M2") |
| **bottleneck_utilization** | Busy hours / makespan | [0.0, 1.0] |

### Scenario Application

Each scenario modifies the baseline factory before simulation:

| Scenario | Modification | Example |
|----------|--------------|---------|
| **BASELINE** | None | Standard schedule |
| **RUSH_ARRIVES** | Tighten one job's due time | Rush J2 to due 12h (instead of 14h) |
| **M2_SLOWDOWN** | Multiply M2 step durations by factor | M2 runs 2x slower for 6 hours |

### Fallback Behavior (Critical)

**Onboarding Failures**:
- Any of O1–O4 fails (bad factory desc, LLM timeout, validation error, etc.)
- System sets `used_default_factory=true` and uses toy factory
- Decision pipeline (D1–D5) runs with toy factory
- Overall status = PARTIAL, but user gets a result

**Decision Failures**:
- D1 (intent classification) fails → use BASELINE spec, run D3–D5
- D2 (futures expansion) fails → use [D1 result] as sole scenario
- D3 (simulation) fails → re-raise (critical; this should never fail)
- D4 (metrics) fails → re-raise (critical; this should never fail)
- D5 (briefing) fails → return deterministic template with metrics

**Safe Defaults**:
- If all LLM calls fail → BASELINE scenario with toy factory
- Briefing template: sections for each scenario + basic metrics
- No unhandled exceptions; user always gets a response

## Design Principles

1. **LLM at the edges, deterministic core** – Agents interpret input (D1) and generate output (D5); simulation/metrics/scheduling are pure computation
2. **Strict validation, no hallucination** – All LLM outputs validated against Pydantic schemas; agents reference only real jobs/machines from factory config
3. **100% coverage enforced** – Onboarding ensures all mentioned machine/job IDs appear in final factory; otherwise falls back to toy factory
4. **Full reproducibility** – Same input → deterministic output, no randomness, fully auditable
5. **Explicit orchestration** – Hand-rolled 10-stage pipeline; easy to trace, instrument, and extend
6. **Error resilience** – Safe fallbacks at every stage; never silent failures, always report status

## Extending & Modifying

### Adding a New Scenario Type

1. **Update models.py**: Add variant to `ScenarioType` enum
   ```python
   class ScenarioType(str, Enum):
       BASELINE = "BASELINE"
       RUSH_ARRIVES = "RUSH_ARRIVES"
       M2_SLOWDOWN = "M2_SLOWDOWN"
       YOUR_SCENARIO = "YOUR_SCENARIO"  # Add here
   ```

2. **Update sim.py**: Implement scenario application logic
   ```python
   elif spec.scenario_type == ScenarioType.YOUR_SCENARIO:
       factory = apply_your_scenario(factory, spec)
   ```

3. **Update agents.py**: Teach IntentAgent & FuturesAgent about new type
   - Update prompts to mention new scenario type
   - Test agent behavior with mocked calls

4. **Add tests**: New test_sim_your_scenario.py with determinism + purity checks

### Updating Prompts

All agent prompts live in `agents.py`. To modify:

1. Edit the prompt string (lines ~50–100 for each agent)
2. Re-run tests with `pytest --record-mode=new` if output format changes
3. Update prompt examples to match actual data from toy factory

### Changing the Toy Factory

1. Edit `world.py:build_toy_factory()` to change machines/jobs/steps
2. Update all tests expecting specific lateness/makespan values
3. Update `FACTORY_SIMULATOR_SPEC.md` to reflect new toy factory
4. Run full test suite: `pytest backend/tests/test_sim_baseline.py -v`

### Adding a New LLM Agent

1. Create new agent class in `agents.py` (extend `BaseAgent`)
2. Define input/output Pydantic models
3. Implement `execute()` method with prompt + LLM call
4. Add fallback behavior
5. Wrap in orchestrator pipeline
6. Add comprehensive tests with mocked LLM responses

### Adding Instrumentation

The `pipeline_instrumentation.py` module provides wrapping & stage collection:

```python
from backend.pipeline_instrumentation import make_stage_wrapper

# Wrap a stage function:
stage_fn, record = make_stage_wrapper(stage_id="O5", name="New Stage")(my_func)

# Run wrapped function and collect debug data:
result, stage_record = stage_fn(input_data)

# stage_record contains: id, name, kind, status, summary, errors
```

## Failure Modes & Invariants

### Guaranteed Invariants

1. **Pipeline always completes** – No unhandled exceptions; fallback at every stage
2. **Scenario count consistency** – len(specs) == len(metrics) always
3. **Valid FactoryConfig or fallback** – Final factory is either valid or toy factory
4. **100% ID coverage in onboarding** – All detected IDs in final factory, or fallback triggered
5. **All metrics non-negative** – lateness ≥ 0, utilization ∈ [0.0, 1.0]
6. **Simulation is deterministic** – Same factory + spec → identical scheduled_steps, makespan
7. **No partial responses** – Either all decision stages run or fallback to BASELINE + toy

### Known Limitations

- **Toy factory is fixed** – Cannot scale to >10 machines, >15 jobs without code changes
- **Integer hours only** – No fractional scheduling; if job needs 0.5h, rounds to 1h
- **No stochastic durations** – Assumes deterministic job durations; no variability modeling
- **EDD heuristic, not optimal** – May not find best schedule; for optimization use OR-Tools
- **Single-day scope** – 24-hour window only; no rolling horizon or multi-day planning
- **No real-time data** – Factory config is static; no live MES integration
- **No preemption** – Jobs cannot be paused/resumed mid-step

### What Can Go Wrong

| Issue | Symptom | Mitigation |
|-------|---------|-----------|
| LLM timeout | D1/D2/D5 stage fails | Fallback to safe defaults |
| Invalid job description | O2 fails → coverage mismatch | Fall back to toy factory |
| Ambiguous IDs (e.g., J1 vs J_1) | O4 coverage check catches it | Explicit ID grammar rules |
| Missing machine reference | O3 validation repair removes step | Logged in onboarding_errors |
| API key not set | LLM calls fail immediately | Fallback behavior handles gracefully |
| Custom factory too large | Validation rejects (>10 machines) | Error in OnboardingMeta; toy factory fallback |

## Strict Invariants (Enforced by Tests)

```python
# Simulation invariants
assert len(scheduled_steps) > 0
assert all(step.start_hour >= 0 for step in scheduled_steps)
assert all(step.end_hour > step.start_hour for step in scheduled_steps)
assert makespan_hour == max(job_completion_times.values())

# Metrics invariants
assert all(lateness >= 0 for lateness in job_lateness.values())
assert 0.0 <= bottleneck_utilization <= 1.0
assert bottleneck_machine_id in [m.id for m in factory.machines]

# Pipeline invariants
assert len(specs) == len(metrics)
assert len(specs) >= 1 and len(specs) <= 3
assert overall_status in ["SUCCESS", "PARTIAL", "FAILED"]
assert (overall_status == "SUCCESS") == (all(s.status == "SUCCESS" for s in stages))
```

## API Contracts (Frozen)

### POST /api/simulate

**Request**:
```json
{
  "factory_description": "string",
  "situation_text": "string"
}
```

**Response** (fixed key set):
```json
{
  "factory": FactoryConfig,
  "specs": [ScenarioSpec, ...],
  "metrics": [ScenarioMetrics, ...],
  "briefing": "string (markdown)",
  "meta": OnboardingMeta,
  "debug": PipelineDebugPayload | null
}
```

**Contract guarantees**:
- Response always has exactly 5 top-level keys + optional `debug`
- All field types match Pydantic models in `models.py`
- `debug` field only present if instrumentation is enabled

### POST /api/onboard

**Request**:
```json
{
  "factory_description": "string"
}
```

**Response**:
```json
{
  "factory": FactoryConfig,
  "meta": OnboardingMeta
}
```

**Contract enforcement**: Snapshot tests in `test_api_contracts.py` validate exact key sets and types.

## Testing Strategy

### Test Categories

| Category | File(s) | Purpose | Test Count |
|----------|---------|---------|-----------|
| **Simulation** | test_sim_*.py (2 files) | EDD scheduler, scenario application | ~40 |
| **Metrics** | test_metrics.py | Lateness, bottleneck, utilization computation | ~25 |
| **Agents** | test_agents_*.py (3 files) | Agent behavior, LLM mocking, fallbacks | ~35 |
| **Orchestration** | test_orchestrator.py | End-to-end pipeline, stage sequencing | ~28 |
| **Onboarding** | test_onboarding_*.py (8 files) | ID extraction, normalization, coverage | ~90 |
| **API** | test_server_*.py (2 files) | HTTP endpoints, request/response contracts | ~20 |
| **Contracts** | test_api_contracts.py | Frozen HTTP contract enforcement | ~10 |
| **Evaluation** | eval/*.py | Invariant validation, adversarial tests | N/A |

### Key Testing Patterns

1. **Determinism**: Run same inputs multiple times, assert identical outputs
2. **Purity**: Deep-copy inputs, verify unchanged after function execution
3. **Validation**: Test Pydantic constraints, error handling, edge cases
4. **Mocking**: All LLM calls mocked via `monkeypatch` on `llm.call_llm_json`
5. **Snapshot assertions**: Frozen API contracts validated against exact key sets
6. **Coverage**: Comprehensive bounds checking (lateness ≥ 0, utilization ∈ [0, 1], etc.)

### Running Evaluation

```bash
# Invariant validation on sample outputs
python -m backend.eval.invariants

# Adversarial test harness (simulates many scenarios)
python -m backend.eval.run_adversarial

# Onboarding sanity checks
python -m backend.eval.run_onboard_sanity
```

## Example Walkthrough

### Input

```
factory_description: "3 machines: M1 (assembly), M2 (mill), M3 (pack)"
                    "3 jobs: J1 due 12h, J2 due 14h, J3 due 16h"
situation_text: "we have a rush order for J2 arriving at hour 2"
```

### Onboarding Pipeline (O0–O4)

**O0** (Explicit ID Extraction):
- Detect: M1, M2, M3, J1, J2, J3
- Output: `explicit_machine_ids = ["M1", "M2", "M3"]`, `explicit_job_ids = ["J1", "J2", "J3"]`

**O1** (Coarse Structure):
- LLM enumerates machines and jobs from text
- Output: 3 coarse machines, 3 coarse jobs

**O2** (Fine Extraction):
- LLM extracts steps for each job: J1 → [M1(1h), M2(3h), M3(1h)], etc.
- Output: RawFactoryConfig with all steps

**O3** (Normalization):
- Validate, deduplicate, repair invalid references
- Output: Valid FactoryConfig (or empty if severe errors)

**O4** (Coverage Assessment):
- Compare detected {M1, M2, M3, J1, J2, J3} with parsed IDs
- Assert 100% coverage; if not, raise ExtractionError
- Status: SUCCESS (coverage met) or PARTIAL (fell back to toy factory)

### Decision Pipeline (D1–D5)

**D1** (Intent Classification):
- LLM reads: "rush order for J2 arriving at hour 2"
- Output: `ScenarioSpec(scenario_type=RUSH_ARRIVES, rush_job_id="J2")`

**D2** (Futures Expansion):
- LLM generates 1–3 variations: [BASELINE, RUSH_ARRIVES, M2_SLOWDOWN]
- Output: 3 scenario specs

**D3** (Simulation):
- For each spec: apply scenario, run EDD scheduler, record completion times
- Output: 3 SimulationResults

**D4** (Metrics Computation):
- For each result: compute lateness, bottleneck, utilization
- Output: 3 ScenarioMetrics

**D5** (Briefing Generation):
- LLM synthesizes risks, recommendations from metrics
- Output: Markdown briefing

### Output

```json
{
  "factory": {
    "machines": [
      {"id": "M1", "name": "assembly"},
      {"id": "M2", "name": "mill"},
      {"id": "M3", "name": "pack"}
    ],
    "jobs": [...]
  },
  "specs": [
    {"scenario_type": "BASELINE", ...},
    {"scenario_type": "RUSH_ARRIVES", "rush_job_id": "J2", ...},
    {"scenario_type": "M2_SLOWDOWN", ...}
  ],
  "metrics": [
    {"makespan_hour": 8, "job_lateness": {...}, "bottleneck_machine_id": "M2", ...},
    {"makespan_hour": 10, "job_lateness": {"J1": 2, ...}, "bottleneck_machine_id": "M2", ...},
    {"makespan_hour": 10, "job_lateness": {"J1": 1, ...}, "bottleneck_machine_id": "M2", ...}
  ],
  "briefing": "# Morning Briefing\n\nRush order for J2 will cause...",
  "meta": {"used_default_factory": false, "onboarding_errors": [], ...},
  "debug": {
    "overall_status": "SUCCESS",
    "stages": [
      {"id": "O0", "status": "SUCCESS", "summary": {...}},
      ...
      {"id": "D5", "status": "SUCCESS", "summary": {...}}
    ]
  }
}
```

## Documentation

- **[FACTORY_SIMULATOR_SPEC.md](FACTORY_SIMULATOR_SPEC.md)** – Complete technical specification (data models, algorithms, contracts)
- **[RUNTIME_SETUP_AND_TESTING.md](RUNTIME_SETUP_AND_TESTING.md)** – Installation, environment, running tests
- **[API_CONTRACTS.md](API_CONTRACTS.md)** – Frozen HTTP API specifications with examples

## Technology Stack

**Backend**: Python 3.10+, FastAPI, Pydantic, OpenAI API (JSON mode)
**Frontend**: React 18+, TypeScript, Vite, CSS3
**Testing**: pytest, monkeypatch (for LLM mocking)

## Dependencies

**Python**:
- `pydantic` – Data validation
- `openai` – LLM integration (optional; only imported for LLM calls)
- `fastapi` – HTTP server
- `uvicorn` – ASGI server
- `pytest` – Testing

**Node.js**:
- `react`, `typescript`, `vite` – Frontend

## What's Delivered

✅ Multi-stage onboarding pipeline (O0–O4) with fallback behavior
✅ Multi-stage decision pipeline (D1–D5) with all agents implemented
✅ Deterministic EDD scheduler with integer-hour precision
✅ Scenario system (BASELINE, RUSH_ARRIVES, M2_SLOWDOWN)
✅ Metrics computation (makespan, lateness, bottleneck, utilization)
✅ Pipeline debug UI with accordion pattern (PipelineSummary, StageList, StageDetailPanel)
✅ FastAPI server with frozen HTTP contracts
✅ React frontend with debug stage visualization
✅ ~9,000 LOC of comprehensive tests (determinism, purity, integration, contracts)
✅ Full specification & setup documentation

## What's Out of Scope

- Real-time MES integration or live factory data
- Stochastic duration distributions or Monte Carlo simulation
- Multi-day or rolling-horizon scheduling
- Optimal scheduling algorithms (use OR-Tools for that)
- Machine concurrency or step preemption
- Production database persistence
- Multi-user authentication or RBAC

---

**This system demonstrates clean separation of concerns: LLM agents at interpretation and reporting boundaries, deterministic simulation core, full pipeline visibility via debug UI, and production-grade error handling with safe fallbacks at every stage.**
