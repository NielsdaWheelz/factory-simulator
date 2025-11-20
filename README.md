# Factory Day Simulator

A demonstration of multi-agent LLM orchestration paired with deterministic factory scheduling simulation. This "spearfish demo" shows how to build intelligent factory operations software by combining a clean, deterministic simulation core with LLM agents strategically placed at interpretation and reporting boundaries.

## Overview

**What is this?**

A toy factory day simulator that generates morning briefings for plant managers. You describe your day's priorities in free-form text, and the system:

1. Parses your intent (via LLM)
2. Generates 1–3 scenario variations (via LLM)
3. Simulates each scenario (deterministic scheduling)
4. Computes metrics (lateness, bottlenecks, utilization)
5. Produces an actionable markdown briefing (via LLM)

**What problem does it solve?**

Plant managers need to understand "What will go wrong today, which jobs are at risk, and what can I do about it?" This system answers those questions by simulating alternative futures and explaining the risks in clear, operational language.

**Who is it for?**

- **Factory planners & operations managers** – Get insight into your day without manually running what-if scenarios
- **CTOs evaluating factory scheduling software** – See how to weave LLM agents around a deterministic simulation core without letting agents touch the core logic

## Key Features

- **Deterministic simulation**: Same input → same output always (no randomness)
- **Three scenario types**: Baseline, rush orders, machine disruptions
- **LLM at the edges**: Agents only for input interpretation and output generation; simulation is pure computation
- **Strict typed contracts**: All agent inputs/outputs validated against Pydantic schemas
- **No hallucination**: Agents can only reference real jobs and machines from the factory config
- **Explicit orchestration**: Hand-rolled pipeline, no external frameworks (no LangGraph)
- **Reproducible**: Identical user text and factory config yield identical briefings

## Architecture

### Five Layers

```
┌─────────────────────────────────────────────┐
│ Layer 5: Briefing Narrative (LLM)           │
│ Input: Metrics → Output: Markdown briefing  │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│ Layer 4: LLM Agent Boundary                 │
│ Intent Agent, Futures Agent, Briefing Agent │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│ Layer 3: Metrics & Scheduling (Pure)        │
│ Deterministic simulation + metric compute   │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│ Layer 2: Scenario Definitions                │
│ ScenarioSpec (closed enum, no LLM)          │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│ Layer 1: Factory Model (Canonical)          │
│ Machines, Jobs, Steps (hardcoded toy world) │
└─────────────────────────────────────────────┘
```

### Data Flow

```
User Text Input
     ↓
IntentAgent (LLM) → ScenarioIntent
     ↓
FuturesAgent (LLM) → list[ScenarioSpec]
     ↓
FOR EACH Scenario:
├→ apply_scenario (pure, deterministic)
├→ simulate_baseline (EDD scheduling)
└→ compute_metrics (lateness, bottleneck)
     ↓
Build context summary
     ↓
BriefingAgent (LLM) → Markdown briefing
     ↓
Return { factory, specs, results, metrics, briefing }
```

## Project Structure

```
factory-simulator/
├── main.py                      # CLI entrypoint (stub)
├── config.py                    # Environment & configuration
├── models.py                    # Pydantic data models (all types)
├── world.py                     # Toy factory definition (3 machines, 3 jobs)
├── sim.py                       # Deterministic simulation engine (EDD scheduler)
├── metrics.py                   # Metrics computation (lateness, bottleneck, utilization)
├── llm.py                       # LLM communication helper (OpenAI JSON mode)
├── agents.py                    # Three LLM-backed agents (Intent, Futures, Briefing)
├── orchestrator.py              # Multi-scenario pipeline (run_pipeline)
├── tests/                       # Comprehensive test suite (~1,800 lines)
│   ├── test_sim_baseline.py     # Toy factory & baseline scheduling tests
│   ├── test_sim_scenarios.py    # Scenario application & pure function tests
│   ├── test_metrics.py          # Metrics computation validation
│   ├── test_agents_llm.py       # Agent behavior with mocked LLM calls
│   └── test_orchestrator.py     # End-to-end pipeline integration tests
├── FACTORY_SIMULATOR_SPEC.md    # Complete specification document
└── README.md                    # This file
```

## Quick Start

### Installation & Setup

For comprehensive setup instructions including environment variables and dependency installation, see [RUNTIME_SETUP_AND_TESTING.md](RUNTIME_SETUP_AND_TESTING.md).

**Quick version**:

```bash
# Install dependencies
uv pip install -U openai pydantic pytest

# or with pip:
pip install -U openai pydantic pytest

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."
```

### Running the CLI

```bash
# With a description
python -m main "we just got a rush order for J2, do not delay J1"

# Or interactive mode
python -m main
```

### Running Programmatically

```python
from orchestrator import run_pipeline

# Run the pipeline with free-form user text
result = run_pipeline("We have a rush order for J2 today. J3 is important. I can delay J1 if needed.")

# Result contains:
print(result.keys())
# → dict_keys(['factory', 'base_spec', 'specs', 'results', 'metrics', 'briefing'])

# Print the morning briefing
print(result['briefing'])
```

### Running Tests

```bash
# Run all tests (uses mocked LLM calls, no API key needed)
pytest tests/ -v

# Run specific test file
pytest tests/test_sim_baseline.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## Development Setup

### Backend (Python)

The backend is the simulation engine with LLM agents. Set it up as described above:

```bash
# Install dependencies
pip install -U openai pydantic pytest

# Set your OpenAI API key
export OPENAI_API_KEY="sk-..."

# Run tests
python -m pytest

# Run CLI
python -m main "your factory situation here"
```

### Backend API (FastAPI)

The backend exposes a REST API via FastAPI for running simulations with custom factory configs:

```bash
# Install FastAPI and Uvicorn
pip install fastapi uvicorn

# Start the API server
uvicorn server:app --reload

# Server runs at http://localhost:8000
# API documentation available at http://localhost:8000/docs
```

**Endpoint**: `POST /api/simulate`

Request body:
```json
{
  "factory_description": "3 machines, 3 jobs",
  "situation_text": "normal day"
}
```

Response: JSON object with `factory`, `specs`, `metrics`, `briefing`, and `meta`.

### Frontend (React + Vite)

The frontend is a React application built with Vite and TypeScript. To run the frontend dev server:

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install   # or pnpm install / yarn install

# Start dev server (opens at http://localhost:5173)
npm run dev

# Build for production
npm run build
```

**Note**: The frontend can call `http://localhost:8000/api/simulate` once both the backend API and frontend dev servers are running.

## How It Works

### The Toy Factory

**Machines** (3):
- **M1** (Assembly) – 1 hour available per day
- **M2** (Drill/Mill) – bottleneck (6 hours of demand vs 24 available)
- **M3** (Pack/Ship) – 3 hours needed

**Jobs** (3):
- **J1** (Widget A) – M1(1h) → M2(3h) → M3(1h), due at 12h
- **J2** (Gadget B) – M1(1h) → M2(2h) → M3(1h), due at 14h
- **J3** (Part C) – M2(1h) → M3(2h), due at 16h

All three jobs compete for M2, creating a bottleneck that drives interesting scheduling conflicts.

### Simulation Algorithm

Uses **Earliest Due Date (EDD)** heuristic with greedy machine allocation:

1. Sort jobs by due time (earliest first)
2. For each job's steps (in order):
   - Find earliest available slot on required machine
   - Respect step dependencies and machine availability
   - Allocate step to that slot
3. Compute completion times and lateness
4. Track bottleneck machine (highest utilization)

All times are **integer hours**; no fractional scheduling.

### Three Scenario Types

**BASELINE**
- No modifications; standard job queue
- Expected: all jobs on-time, makespan ≈ 5–6h, M2 utilization ≈ 85%

**RUSH_ARRIVES**
- An existing job becomes a rush instance with tighter due time
- Creates scheduling conflict; expected 2–4h lateness on another job
- Example: "Rush J2 at hour 2, due at hour 12"

**M2_SLOWDOWN**
- Machine M2 operates slower for a time window (e.g., maintenance)
- Slowdown factor (1.5–3.0x) multiplies step durations
- Expected: 1–3h lateness, M2 utilization reaches 100%

### Agents

**IntentAgent** (`agents.py:46–102`)
- Input: Free-form user text + factory context
- Output: `ScenarioSpec` (BASELINE, RUSH_ARRIVES, or M2_SLOWDOWN)
- Fallback: Returns BASELINE if LLM fails

**FuturesAgent** (`agents.py:105–186`)
- Input: `ScenarioSpec` + factory context
- Output: list of 1–3 `ScenarioSpec` variations
- Fallback: Returns [original_spec] if LLM fails

**BriefingAgent** (`agents.py:189–276`)
- Input: `ScenarioMetrics` (primary scenario) + optional context about all scenarios
- Output: Markdown briefing with sections: Today at a Glance, Key Risks, Recommended Actions, Limitations
- Fallback: Deterministic template with metrics plugged in

All agents catch exceptions and use safe fallbacks—no unhandled errors.

### Metrics

For each scenario, the system computes:

- **makespan_hour**: Total hours from start to final job completion
- **job_lateness**: Per-job lateness (completion_time - due_time, minimum 0)
- **bottleneck_machine_id**: Machine with highest utilization
- **bottleneck_utilization**: Bottleneck utilization as fraction [0.0, 1.0]

## Example Output

### Input
```
"We have a rush order for J2 today. J3 is also important.
I can accept some delay on J1 if needed. What should I expect?"
```

### Output (Briefing)
```markdown
# Morning Briefing: 2025-11-19

## Today at a Glance
The rush J2 scenario puts heavy pressure on M2 and risks pushing J1 past
its due time. Recommend either expediting J1 before the rush arrives or
accepting 2–3 hour delay on J1.

## Scenarios Analyzed
- **Baseline Day**: Standard job queue (J1, J2, J3), no rush.
- **Rush J2 Order**: J2 injected as rush at 2h, due at 12h.
- **M2 Slowdown (8–14h)**: M2 operates at 2x duration for 6 hours due to maintenance.

## Key Risks
- **Rush J2 scenario**: J1 delayed to 16h (4h late) because M2 is monopolized
  by rush. J3 stays on-time.
- **M2 Slowdown scenario**: Both J1 and J2 slide; M2 utilization reaches 100%
  during 8–14h window.
- **Machine M2 is the bottleneck in all three scenarios**: 85% baseline, 100%
  rush, 100% slowdown.

## Jobs at Risk
| Job | Baseline  | Rush J2 | M2 Slowdown |
|-----|-----------|---------|-------------|
| J1  | On-time   | 4h late | 2h late     |
| J2  | On-time   | On-time | 1h late     |
| J3  | On-time   | On-time | On-time     |

## Bottleneck Machines
- **Baseline**: M2 (85% utilization)
- **Rush J2**: M2 (100% utilization)
- **M2 Slowdown**: M2 (100% utilization during 8–14h window)

## Recommended Actions
- **For rush scenario**: Start J1 at hour 0; prioritize rush J2 at hour 2+.
  If J1 lateness is unacceptable, negotiate rush due time or defer J3.
- **For slowdown scenario**: Avoid starting M2 jobs between 8–14h if possible;
  shift J3 earlier or later.
- **General**: Escalate to materials team if rush J2 dependencies not secured by hour 1.

## Limitations of This Model
This briefing assumes deterministic job durations (no variability) and no real
equipment breakdowns. The model is a toy world with 3 machines and 3 jobs.
Use as a guide; always verify with floor manager.
```

## Design Principles

1. **LLM at the edges, deterministic core**
   - Agents interpret input (IntentAgent) and generate output (BriefingAgent)
   - Simulation and metrics are pure computation, never touched by LLM

2. **Strict typed contracts**
   - All agent inputs/outputs validated against Pydantic schemas
   - Validation failures trigger fallbacks, not exceptions

3. **No agent hallucination**
   - Agents can only reference real jobs and machines from FactoryConfig
   - Scenario types are a closed enum; no arbitrary modifications

4. **Reproducibility**
   - Same user text + factory config → deterministic briefing
   - No randomness anywhere in simulation or scheduling

5. **Explicit orchestration**
   - Hand-rolled pipeline, easy to trace and extend
   - No external framework (LangGraph, Airflow, etc.)

6. **Minimal scope**
   - Single day (24 hours), toy factory (3 machines, 3 jobs)
   - Fits 4-hour implementation window, demonstrates core concepts

## Documentation

This project includes comprehensive documentation:

- **[RUNTIME_SETUP_AND_TESTING.md](RUNTIME_SETUP_AND_TESTING.md)** – Installation, environment setup, running CLI and tests
- **[LLM_MANUAL_TEST_PLAN_AND_NOTES.md](LLM_MANUAL_TEST_PLAN_AND_NOTES.md)** – Manual testing checklist with expected behavior for each scenario (T1–T5)
- **[FACTORY_SIMULATOR_SPEC.md](FACTORY_SIMULATOR_SPEC.md)** – Complete technical specification
- **[README.md](README.md)** – This file; overview and architecture

Start with **RUNTIME_SETUP_AND_TESTING.md** to get the system running, then refer to **LLM_MANUAL_TEST_PLAN_AND_NOTES.md** for validation testing.

## Testing

**Coverage**: ~1,815 lines of test code across 5 test files

**Test Categories**:
- **Unit tests** – Individual functions (simulate_baseline, apply_scenario, compute_metrics)
- **Purity tests** – Verify no mutations and determinism
- **Integration tests** – End-to-end pipeline with mocked agents
- **Mocking strategy** – All LLM calls mocked; no real OpenAI API calls in tests

**Key Testing Patterns**:
1. Determinism: Run same inputs multiple times, assert identical outputs
2. Purity: Deep copy inputs, run function, assert inputs unchanged
3. Validation: Test Pydantic model constraints and error handling
4. Bounds checking: lateness ≥ 0, utilization ∈ [0.0, 1.0], etc.
5. Fallbacks: Test agent exception handling and safe defaults

**Run tests**:
```bash
pytest tests/ -v
```

## What's Implemented

✅ All core modules (config, models, world, sim, metrics, llm)
✅ All three LLM agents (Intent, Futures, Briefing) with LLM-backed JSON mode
✅ Multi-scenario orchestrator (run_pipeline)
✅ Deterministic EDD scheduler with integer-hour precision
✅ Comprehensive test suite (1,815 lines, 5 files)
✅ Complete specification document (FACTORY_SIMULATOR_SPEC.md)
✅ CLI implementation (`main.py`) – interactive and argument-based modes
✅ Full setup and testing documentation

## What Remains to Be Done

### Near-term (Priority)

1. **Performance & Latency**
   - Benchmark LLM agent call latency (target: <5s end-to-end)
   - Optimize if needed (parallel agent execution, response caching)
   - Profile agent calls (expect 1–2s each with gpt-5-nano)

2. **Error Handling & Logging**
   - Add structured logging to each agent and simulation
   - Log latencies, validation outcomes, fallback triggers
   - Pretty-print logs with timestamps and status

3. **Code Documentation**
   - Add docstrings to all public functions
   - Add inline comments to complex scheduling logic

### Medium-term (Enhancement)

4. **Extended Factory Scenarios**
   - Add more job/machine configurations (beyond toy factory)
   - Support configurable factory loading (JSON or YAML)
   - Create scenario templates (e.g., "high-mix low-volume", "lean manufacturing")

5. **Simulation Enhancements**
   - Add stochastic duration distributions (Monte Carlo)
   - Support alternative scheduling heuristics (SPT, LPT, critical path)
   - Implement job preemption and machine concurrency
   - Model material delays and setup times

6. **Agent Improvements**
   - Fine-tune prompts based on real factory data
   - Add confidence scores to agent outputs
   - Support follow-up questions ("Why is M2 the bottleneck?")
   - Implement agent chaining for more complex reasoning

7. **Persistent State**
   - Store briefings and simulation results to database
   - Enable historical trend analysis
   - Support audit trails and compliance logging

### Long-term (Product)

8. **Web UI**
   - Interactive dashboard for scenario exploration
   - Real-time what-if analysis (adjust parameters, see results)
   - Visualization of machine utilization and job timelines
   - Export briefing as PDF or email

9. **Real Data Integration**
    - Connect to MES (Manufacturing Execution System)
    - Pull live factory config, in-progress jobs
    - Support actual machine and job data
    - Handle real disruptions (breakdowns, material delays)

10. **Optimization**
    - Use OR-Tools or Cplex for optimal scheduling
    - Support multi-objective optimization (minimize lateness, balance load, etc.)
    - Recommend proactive actions (reorder jobs, add capacity)

11. **Multi-day & Rolling Horizon**
    - Extend simulation beyond 24 hours
    - Support rolling schedules for continuous operations
    - Integrate with medium-term planning

## Dependencies

**Core**:
- `pydantic` – Data validation and models
- `openai` – Optional, only imported at runtime for LLM calls

**Testing**:
- `pytest` – Test framework
- `pytest-9.0.1` – Test runner

**Python**: 3.10+ (uses modern type hints and dataclass features)

## Configuration

**Environment Variables**:
- `OPENAI_API_KEY` – Required for LLM agent calls (set before running)

**Constants** (`config.py`):
- `OPENAI_MODEL = "gpt-5-nano"` – Model ID (configurable; using GPT-5 nano as default for optimal JSON mode compliance)

## License

[Not specified in repo; add as needed]

## Contact & Feedback

This is a demonstration project. For questions about the design, implementation, or specifications:
- See [FACTORY_SIMULATOR_SPEC.md](FACTORY_SIMULATOR_SPEC.md) for comprehensive technical details
- Open an issue on GitHub for bugs or feature requests
- Review the test files for usage examples

## Related Resources

- [FACTORY_SIMULATOR_SPEC.md](FACTORY_SIMULATOR_SPEC.md) – Complete specification and design document
- [tests/](tests/) – Comprehensive test suite with examples
- [agents.py](agents.py) – LLM agent implementations with prompt templates
- [sim.py](sim.py) – Deterministic scheduling algorithm

---

**This project demonstrates multi-agent LLM orchestration at the service of a deterministic simulation core—showing how to build intelligent factory software without letting LLMs touch the critical path of decision-making.**
