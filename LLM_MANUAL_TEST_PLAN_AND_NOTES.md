# LLM Manual Test Plan and Notes

## Overview

This document is for **manual LLM-in-the-loop testing** of the factory simulator demo. It assumes:

- Unit tests already pass (with mocked LLM calls)
- `OPENAI_API_KEY` is set in your environment
- You are running the CLI with: `python -m main "..."`

The goal is to validate that:
1. **IntentAgent** correctly interprets user descriptions into scenario specs
2. **FuturesAgent** expands specs into reasonable scenario variations
3. Simulation and metrics computation work correctly
4. **BriefingAgent** generates coherent, actionable briefings

## Test Checklist

| ID | Prompt (copy-paste) | Expected qualitative behavior | Actual behavior (fill after run) | Notes / issues |
|----|---------------------|-------------------------------|----------------------------------|---|
| T1 | `today is a normal day, no rush orders, just run the factory as usual.` | **IntentAgent** → BASELINE; **FuturesAgent** → [BASELINE, maybe one mild variation]; **Metrics** show normal makespan (~13-14h), M2 bottleneck at high utilization (90%+); **Briefing** recommends baseline, mentions M2 as expected bottleneck | | |
| T2 | `we received a critical rush order for job J2, we can tolerate some lateness on J3 but not on J1.` | **IntentAgent** → RUSH_ARRIVES with rush_job_id="J2"; **FuturesAgent** → variants (rush vs. baseline); **Metrics** for rush scenario show possible lateness trade-offs; **Briefing** explicitly recommends prioritizing J2, calls out lateness risk on other jobs | | |
| T3 | `machine M2 is running slower than usual today, maybe half speed.` | **IntentAgent** → M2_SLOWDOWN with slowdown_factor≈2; **FuturesAgent** → variations exploring slowdown vs. baseline; **Metrics** show higher makespan (≥15h), much higher M2 utilization (95%+), possible lateness; **Briefing** flags M2 degradation as critical risk, suggests accelerating non-M2 prep | | |
| T4 | `things are a bit messy, not sure what to prioritize, just give me a view of the day.` | **IntentAgent** → BASELINE or conservative spec; **FuturesAgent** → 1-2 mild variations; **Briefing** is hedged, acknowledges uncertainty, recommends monitoring key metrics | | |
| T5 | `asdfasdfasdf, lorem ipsum` | **IntentAgent** gracefully falls back (BASELINE); **Pipeline does not crash**; **Briefing** still renders deterministic template or LLM-generated fallback | | |

## How to Run Each Test

For each test, open a terminal, set your API key, and run:

### T1: Baseline
```bash
export OPENAI_API_KEY="sk-..."
python -m main "today is a normal day, no rush orders, just run the factory as usual."
```

### T2: Rush Order
```bash
export OPENAI_API_KEY="sk-..."
python -m main "we received a critical rush order for job J2, we can tolerate some lateness on J3 but not on J1."
```

### T3: Slowdown
```bash
export OPENAI_API_KEY="sk-..."
python -m main "machine M2 is running slower than usual today, maybe half speed."
```

### T4: Ambiguous
```bash
export OPENAI_API_KEY="sk-..."
python -m main "things are a bit messy, not sure what to prioritize, just give me a view of the day."
```

### T5: Nonsense
```bash
export OPENAI_API_KEY="sk-..."
python -m main "asdfasdfasdf, lorem ipsum"
```

## What Info to Capture

After running each test, fill in the table above with:

1. **Actual behavior**:
   - What scenario type did IntentAgent choose?
   - What specs did FuturesAgent return (list them)?
   - What were the key metrics (makespan, bottleneck, lateness)?
   - Did the briefing render? Was it coherent?

2. **Obvious mismatches**:
   - If the prompt says "rush order for J2" but IntentAgent chose BASELINE, that's a mismatch.
   - If the prompt says "M2 is slow" but no SLOWDOWN scenario was generated, that's suspicious.

3. **Briefing quality**:
   - Does the briefing mention makespan and lateness?
   - Does it correctly identify M2 as the bottleneck (in baseline scenarios)?
   - Is the recommendation actionable and grounded in the metrics?
   - Are there any hallucinations (mentions of jobs/machines that don't exist)?

## Interpreting Results

### Expected Patterns

**Baseline (T1):**
- Makespan is deterministic: ~13–14 hours (depends on the factory seed; check test_sim_baseline.py for the exact value)
- M2 is the bottleneck (by design of the toy factory)
- Utilization of M2 is high (90%+)
- No job should be late in baseline (all jobs have generous due times)
- Briefing tone: "Everything looks normal; monitor M2 closely"

**Rush (T2):**
- Rushing J2 should compress J2's completion time
- May cause lateness on other jobs (especially J3, if delayed)
- Makespan may increase slightly
- Briefing tone: "J2 prioritized; watch for ripple effects on J1 and J3"

**Slowdown (T3):**
- M2 slowdown_factor=2 means M2's processing time doubles
- Makespan increases by 1–2 hours
- M2 utilization may hit 100% or higher (capped in the sim)
- Higher risk of lateness across all jobs
- Briefing tone: "M2 degradation is severe; prioritize upstream work"

**Ambiguous (T4):**
- IntentAgent may fall back to BASELINE or choose a conservative spec
- Briefing may hedge or ask for clarification
- No crash expected

**Nonsense (T5):**
- IntentAgent falls back to BASELINE
- Briefing still renders (either from LLM or fallback template)
- No crash

### Red Flags

- **Crash or exception:** Report the stack trace; indicates a bug in the pipeline
- **Hallucination:** Briefing mentions jobs like "J5" that don't exist (only J1–J4 exist)
- **Misaligned scenario:** Prompt says "rush" but IntentAgent chose M2_SLOWDOWN (unless the user's wording was genuinely ambiguous)
- **Lateness in baseline:** Baseline should have zero lateness (all due times are generous)
- **Bottleneck not M2:** In baseline and rush scenarios, M2 should be the bottleneck (unless slowdown is applied to M2)

## Notes for the Reviewer

When submitting these test results, please include:

1. **Test environment:**
   - Python version (e.g., `python --version`)
   - OpenAI model used (from config.py, typically gpt-4-turbo or gpt-4)
   - API key age (optional; just to flag if using an old/revoked key)

2. **Logs:**
   - If you see any warnings from the agents (e.g., "IntentAgent LLM call failed"), include them in the notes

3. **Metrics summary:**
   - For each test, list the key metrics of the primary scenario:
     ```
     T1 primary: makespan=13h, bottleneck=M2, M2_util=92%, lateness={J1:0, J2:0, J3:0, J4:0}
     T2 primary: makespan=14h, bottleneck=M2, M2_util=94%, lateness={J1:0, J2:0, J3:1, J4:0}
     ...
     ```

4. **Subjective quality:**
   - How clear was the briefing? On a scale 1–5?
   - Did the recommendation make sense? Was it actionable?
   - Any surprises or unexpected behavior?

This manual test plan ensures that the LLM agents are functioning correctly in the wild and that the briefing is genuinely useful to a factory planner.
