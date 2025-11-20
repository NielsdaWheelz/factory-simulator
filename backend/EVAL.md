# Adversarial Evaluation Harness

This document describes the adversarial evaluation harness for factory-simulator, a tooling and evaluation framework for stress-testing the onboarding and simulation pipelines with messy, challenging, and edge-case inputs.

## Overview

The harness is **opt-in and not part of normal pytest**. It runs only when explicitly invoked via the CLI, and is designed to:

- Run curated adversarial test cases through the onboarding pipeline (OnboardingAgent → normalize_factory → run_onboarding)
- Optionally run the full decision pipeline (IntentAgent → FuturesAgent → simulate → compute_metrics → BriefingAgent)
- Optionally exercise HTTP endpoints (/api/onboard, /api/simulate) via FastAPI TestClient
- Check structural invariants on factories and metrics
- Generate timestamped JSON reports for manual inspection and diffing

## Files

- **backend/eval/adversarial_cases.yaml** - Corpus of ~12 test cases covering clean inputs, messy SOP prose, contradictions, missing machines, large factories, invalid durations, circular routing, empty inputs, impossible constraints, and realistic noise.
- **backend/eval/run_adversarial.py** - CLI harness. Entry point via `python -m backend.eval.run_adversarial`.
- **backend/eval/invariants.py** - Pure validation helpers that check factories and metrics against structural rules.
- **backend/eval/__init__.py** - Package marker.

## Quick Start

### Run all cases with LLM enabled

```bash
uv run python -m backend.eval.run_adversarial --use-llm
```

### Run a single case

```bash
uv run python -m backend.eval.run_adversarial --use-llm --case-id messy_sop
```

### Run with HTTP endpoint testing

```bash
uv run python -m backend.eval.run_adversarial --use-llm --http
```

### Run multiple specific cases

```bash
uv run python -m backend.eval.run_adversarial --use-llm \
  --case-id clean_canonical \
  --case-id messy_sop \
  --case-id impossible_constraints
```

### Write reports to custom directory

```bash
uv run python -m backend.eval.run_adversarial --use-llm --out-dir /tmp/eval_reports
```

## Command-Line Options

```
python -m backend.eval.run_adversarial [OPTIONS]

Options:
  --http              Exercise FastAPI endpoints via TestClient (default: False)
  --use-llm           Call the real LLM (default: True)
  --case-id ID        Run only specific case(s); may be repeated
  --out-dir DIR       Output directory for reports (default: backend/eval/reports)
  --help              Show help message
```

## Adversarial Cases Corpus

The YAML file defines a list of test cases, each with:

- **id** (string): Unique identifier, kebab-case (e.g., `clean_canonical`)
- **kind** (string): Either `onboard_only` (run onboarding only) or `simulate` (run full pipeline)
- **factory_description** (string): Free-text description of the factory
- **situation_text** (string): Optional; context/constraints for the decision pipeline
- **tags** (list): Optional metadata tags for grouping/filtering

### Example Case

```yaml
- id: messy_sop
  kind: simulate
  factory_description: |
    MANUFACTURING OPERATIONAL MANUAL
    ...
    (long, noisy, prose-like description)
  situation_text: |
    It's rush hour. Can we make them all on time?
  tags: ["messy", "sop", "prose"]
```

### Adding a New Case

1. Edit `backend/eval/adversarial_cases.yaml`
2. Add a new entry to the `cases` list
3. Fill in `id`, `kind`, `factory_description`, and optionally `situation_text` and `tags`
4. Run the harness to exercise the new case:

```bash
uv run python -m backend.eval.run_adversarial --use-llm --case-id my_new_case
```

## Report Structure

Each case generates a JSON report at `<out_dir>/<YYYYMMDD_HHMMSS>/<case_id>.json`:

```json
{
  "case": {
    "id": "messy_sop",
    "kind": "simulate",
    "factory_description": "...",
    "situation_text": "...",
    "tags": ["messy", "sop"]
  },
  "onboarding": {
    "factory": { "machines": [...], "jobs": [...] },
    "meta": {
      "used_default_factory": false,
      "onboarding_errors": [],
      "inferred_assumptions": [...]
    },
    "debug": {
      "used_default_factory": false
    }
  },
  "agents": { /* agent-level outputs if available */ },
  "simulation": {
    "specs": [{ "scenario_type": "BASELINE", ... }],
    "metrics": [{ "makespan_hour": 10, "job_lateness": {...}, ... }],
    "briefing": "# Simulation Results\n..."
  },
  "http": {
    "onboard_response": { /* response from /api/onboard */ },
    "simulate_response": { /* response from /api/simulate */ }
  },
  "invariants": {
    "factory_invariants_ok": true,
    "metrics_invariants_ok": true,
    "errors": [ /* list of violation messages */ ]
  }
}
```

### Key Fields

- **case**: The original input case from YAML
- **onboarding**: Parsed/normalized factory and metadata from the onboarding pipeline
- **agents**: Agent-level outputs (if exposed and available)
- **simulation**: Scenario specs, metrics, and markdown briefing from the decision pipeline
- **http**: Responses from FastAPI endpoints (if --http was used)
- **invariants**: Validation results and any violation messages

## Invariants

The harness checks two categories of structural invariants:

### Factory Invariants

- All `step.machine_id` must be in `{m.id for m in factory.machines}`
- All `step.duration_hours >= 1`
- Every job has at least 1 step
- `len(factory.machines) <= 10` (demo cap)
- `len(factory.jobs) <= 15` (demo cap)
- Each job has `len(job.steps) <= 10` (demo cap)
- All `job.due_time_hour >= 0`

### Metrics Invariants

- `len(metrics) == len(specs)`
- For each metric:
  - `makespan_hour >= 0`
  - `bottleneck_machine_id` ∈ {m.id for m in factory.machines}
  - `0.0 <= bottleneck_utilization <= 1.0`
  - `job_lateness` keys ⊆ set of job IDs
  - All lateness values >= 0

Violations are collected and reported without raising exceptions, allowing full case execution even with failures.

## Interpreting Reports

### Standard Output

The harness prints a summary line for each case during execution:

```
[messy_sop] kind=simulate onboarding=DEGRADED used_default_factory=false invariants=OK
[impossible_constraints] kind=simulate onboarding=OK used_default_factory=false invariants=FAILED (2 violations)
```

Possible onboarding statuses:
- **OK**: Factory parsed cleanly with no warnings
- **DEGRADED**: Factory has warnings but was successfully normalized
- **FALLBACK**: Fell back to toy factory (empty or unparseable input)

Invariants status:
- **OK**: All invariants passed
- **FAILED**: One or more invariants violated (see error messages in JSON report)

### JSON Report Analysis

1. Open a generated report: `backend/eval/reports/<timestamp>/<case_id>.json`
2. Check `invariants.errors` for violation details
3. Inspect `onboarding.meta.onboarding_errors` for normalization issues
4. Review `simulation.metrics` for metric outputs
5. Compare reports across runs to detect regressions (useful for diffing with `jq` or `diff`)

## LLM Usage

**Important**: The harness is designed to call the real LLM when `--use-llm` is passed. This is intentional for evaluating agent robustness.

- **LLM calls are NOT invoked by pytest**. Normal test runs remain deterministic and mocked.
- The harness is completely **opt-in** and not part of CI/CD unless explicitly wired.
- No LLM calls are added to `backend/tests/**` files.

To run without LLM calls, developers would need to mock agent outputs (not currently implemented; focus is on LLM mode for evaluation).

## Integration Notes

- The harness reuses existing orchestrator functions (`run_onboarding`, `run_decision_pipeline`) without modifying them.
- HTTP tests use `TestClient` from `fastapi.testclient`, the same pattern as existing server tests.
- All Pydantic models are serialized using `.model_dump()` to ensure JSON compatibility.
- No changes to API contracts, agent logic, simulation, metrics, or frontend.

## Troubleshooting

### Case execution error

If a case fails to run:
1. Check the error message in the status line output
2. Open the corresponding JSON report (if partially generated)
3. Review `onboarding.meta.onboarding_errors` for parsing issues
4. Verify factory_description and situation_text are valid

### Invariant violations

If invariants fail:
1. Check `invariants.errors` in the JSON report
2. Review the specific violation (e.g., "Job J1 step 0: duration_hours=0 is less than minimum of 1 hour")
3. Check if this is expected (e.g., a known limitation in the LLM parsing for edge cases)
4. Consider adding a normalization rule or LLM prompt improvement

### Report directory not created

Ensure the output directory is writable:

```bash
mkdir -p backend/eval/reports
```

## Testing the Harness

To verify the harness is working correctly:

```bash
# Run a single simple case (no LLM required for deterministic output)
uv run python -m backend.eval.run_adversarial --use-llm --case-id clean_canonical

# Check the generated report
cat backend/eval/reports/<latest_timestamp>/clean_canonical.json | jq .invariants
```

The report should show:
```json
{
  "factory_invariants_ok": true,
  "metrics_invariants_ok": true,
  "errors": []
}
```
