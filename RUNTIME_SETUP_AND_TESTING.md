# Runtime Setup and Testing

## Prerequisites

### Python Version
- **Minimum:** Python 3.10
- **Tested with:** Python 3.13

### Dependencies

Install required packages using `uv`:

```bash
uv pip install -U openai pydantic pytest
```

Or, if `uv` is not available, use `pip`:

```bash
pip install -U openai pydantic pytest
```

These packages provide:
- `openai`: OpenAI API client for LLM-backed agents
- `pydantic`: Data validation and parsing
- `pytest`: Testing framework

The repo uses `python-dotenv` in `config.py` to load environment variables from a `.env` file (optional; see below).

## Environment Setup

### Setting OPENAI_API_KEY

The application requires an OpenAI API key to run LLM-backed agents (IntentAgent, FuturesAgent, BriefingAgent).

**Option 1: Export in shell (recommended for testing)**

```bash
export OPENAI_API_KEY="sk-..."
```

Replace `sk-...` with your actual API key from OpenAI.

**Option 2: Use .env file**

The `config.py` module calls `load_dotenv()`, so you can also create a `.env` file in the repo root:

```
OPENAI_API_KEY=sk-...
```

**Important:** Do not commit `.env` to version control. The repo's `.gitignore` should already exclude it.

### Verifying Setup

To verify the API key is accessible:

```bash
python -c "from config import get_openai_api_key; print('API key loaded:', bool(get_openai_api_key()))"
```

If you see `RuntimeError: OPENAI_API_KEY not set`, ensure the environment variable is exported.

## Running Tests

Run all unit tests (these use mocked LLM calls, so no API key required):

```bash
pytest
```

Run specific test file:

```bash
pytest tests/test_sim_baseline.py -v
```

Run tests with verbose output:

```bash
pytest -v
```

All tests should pass with zero LLM API calls (mocked).

## Running the CLI

### Syntax

```bash
python -m main "your description here"
```

Or, for interactive mode (no arguments):

```bash
python -m main
```

Then paste your description and press Enter.

### Example Commands

**Example 1: Rush order**
```bash
python -m main "we just got a rush order for job J2, J1 cannot be late"
```

**Example 2: Machine slowdown**
```bash
python -m main "machine M2 is running slower today, maybe 2x slower"
```

**Example 3: Baseline (normal day)**
```bash
python -m main "today is a normal day, run the factory as usual"
```

**Example 4: Interactive**
```bash
python -m main
# Then at the prompt:
> describe the situation...
```

## What to Expect

### On Success

The CLI will:
1. Parse your description into a scenario spec (IntentAgent)
2. Expand into 1–3 candidate scenarios (FuturesAgent)
3. Run deterministic simulations for each
4. Compute metrics (makespan, lateness, bottleneck)
5. Generate a markdown "Decision Briefing" and print it to stdout

Example output:
```
=== DECISION BRIEFING ===

# Morning Briefing

## Today at a Glance
...

## Key Risks
...

=== END ===
```

### On Error

If the OPENAI_API_KEY is missing or invalid:

```
ERROR: OPENAI_API_KEY not set; please export it before running LLM-backed code.
```

If the OpenAI library is not installed:

```
ERROR: openai package is not installed. Install it to use LLM-backed agents.
```

All other errors will be logged with the exception traceback; check the output for details.

## Logging

The CLI enables INFO-level logging by default. You will see messages like:

```
2025-11-19 14:30:15,123 [INFO] llm: calling LLM for schema ScenarioSpec
```

These are informational and do not affect the output briefing. To suppress logs, run:

```bash
python -m main "..." 2>/dev/null
```

## Notes

- **Simulation is deterministic:** For a given scenario, the same factory configuration will always produce identical results.
- **LLM calls may differ:** The LLM may produce slightly different scenario specifications or briefing wording on each call (expected behavior).
- **No network needed except for LLM:** The factory simulation is entirely local; only the LLM agent calls require network access.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'openai'` | Run `pip install openai` |
| `RuntimeError: OPENAI_API_KEY not set` | Run `export OPENAI_API_KEY="sk-..."` in shell before running |
| Tests fail with mocked assertions | Run tests with `pytest -v` to see detailed failure reasons |
| CLI hangs | Check network connectivity; the LLM call may be slow or stuck. Press Ctrl+C to abort. |
