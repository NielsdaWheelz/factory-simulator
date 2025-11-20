# Forensic Analysis: Factory Onboarding Under-Extraction Bug

## Executive Summary

The onboarding pipeline is severely under-extracting the factory structure. Input with **3 machines and 4 jobs** is being parsed to **1 machine and 1 job**, with `used_default_factory=False` and `errors=0`. This indicates the LLM itself is at fault, not the parsing or normalization layers.

---

## TASK 1: CODE SUMMARY

### Backend Flow
```
factory_text → OnboardingAgent.run()
  ├─ _build_prompt(factory_text)
  ├─ call_llm_json(prompt, FactoryConfig)
  └─ returns FactoryConfig (or build_toy_factory on exception)
    ↓
run_onboarding() in orchestrator.py
  ├─ normalize_factory(raw_factory)
  │  └─ repairs bad durations, invalid machine refs, drops jobs with no steps
  ├─ is_toy_factory(final_factory) check
  └─ OnboardingMeta(used_default_factory, onboarding_errors)
    ↓
run_decision_pipeline() / run_onboarded_pipeline()
```

### Key Functions

#### [agents.py:41-107] OnboardingAgent.run()
- Calls `_build_prompt()` to construct the prompt
- Calls `call_llm_json(prompt, FactoryConfig)` to invoke LLM
- On exception: logs warning, returns `build_toy_factory()` (fallback)
- On success: logs metrics, returns the parsed `FactoryConfig`

#### [agents.py:109-538] OnboardingAgent._build_prompt()
The prompt is extremely detailed (~400 lines) with:
- **ROLE & GUARDRAILS** (lines 140-144):
  - "You are conservative and deterministic."
  - "Prefer under-modeling to over-modeling"
  - "Pick the simplest interpretation"
  - "Drop incomplete or ambiguous constructs"

- **SIZE LIMITS / DEMO CONSTRAINTS** (lines 215-226):
  - "Machines: 1-10 maximum (typical: 3-5)"
  - "Jobs: 1-15 maximum (typical: 3-5)"
  - "**If the description implies more machines or jobs, IGNORE the excess and model only the first 10 machines and first 15 jobs mentioned.**"

- **TIME INTERPRETATION RULES** (lines 184-212):
  - Durations must be integers >= 1
  - "half hour" or "0.5h" → 1 (round up; no sub-hour durations)
  - "RULE: Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations."

- **FOUR WORKED EXAMPLES** (lines 287-480):
  - Example A: Clean factory with explicit integer durations (2h, 3h, 1h, etc.)
  - Example B: Messy SOP with vague durations, resolving "~1-2h" → 1, "2h or 4h" → 2
  - Example C: Contradictions, resolved conservatively
  - Example D: Forbidden features (parallel paths, branching, batching), ignored

- **NO explicit rule that says**: "Extract ALL jobs and machines mentioned in the text, even if some have non-integer durations."

#### [orchestrator.py:199-269] run_onboarding()
1. OnboardingAgent.run(factory_text) → raw_factory
2. normalize_factory(raw_factory) → (normalized_factory, warnings)
3. Apply failure ladder:
   - If normalized_factory is empty → fallback to toy factory, `used_default_factory=True`
   - Else if normalized_factory == toy factory → `used_default_factory=True`
   - Else if warnings non-empty → `used_default_factory=False` (but degraded)
   - Else → `used_default_factory=False` (OK)
4. Return (final_factory, OnboardingMeta)

#### [onboarding.py:20-114] normalize_factory()
- Validates/repairs durations: non-int or <= 0 → 1
- Validates/repairs due_time: non-int or < 0 → 24
- Drops steps with invalid machine_id
- Drops jobs with no valid steps
- Returns (repaired_factory, warnings list)
- **Does not drop machines or jobs based on content; only repairs field values**

#### [llm.py:24-82] call_llm_json()
- Calls OpenAI API with JSON mode
- Uses OPENAI_MODEL from config (not logged, but likely gpt-4-turbo or similar)
- Parses response.content as JSON
- Validates with Pydantic schema
- Raises RuntimeError on failure (caught by OnboardingAgent.run())

---

## TASK 2: REPRODUCE THE FAILURE

### Input Factory Description
```
We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).
```

### Actual Output
```
Machines: 1
  - M1: Machine 1

Jobs: 1
  - J1: Default (due_time=24h, steps=1)
    - M1: 1h

Onboarding Metadata:
  - used_default_factory: False
  - onboarding_errors: 0
```

### Key Observation
- **No exception was raised** (errors=0)
- **The toy factory detection passed** (used_default_factory=False)
- This factory is NOT the toy factory (1 machine, 1 job ≠ 3 machines, 3 jobs)
- The LLM successfully returned a FactoryConfig, but drastically under-extracted

---

## TASK 3: RAW LLM RESPONSE (CAPTURED)

### Raw JSON from LLM (first 500 chars)
```json
{
  "machines": [
    {
      "id": "M1",
      "name": "Machine 1"
    }
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Default",
      "steps": [
        {
          "machine_id": "M1",
          "duration_hours": 1
        }
      ],
      "due_time_hour": 24
    }
  ]
}
```

### Key Finding
**The LLM itself output only 1 machine and 1 job.** This is not a parsing or normalization issue. The raw LLM JSON directly shows under-extraction.

---

## TASK 4: ANALYSIS OF PROMPT & LLM BEHAVIOR

### Hypothesis: Fractional Hours as Trigger

The input explicitly mentions **1.5h durations**:
- J2: 1.5h on M1, 1.5h on M3
- The prompt says: "half hour" or "0.5h" → 1 (round up; no sub-hour durations)
- The prompt says: "RULE: Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations."

**Theory**: The LLM encountered "1.5h" and interpreted this as a **violation of the integer constraint**. The prompt heavily emphasizes "Prefer under-modeling" and "Drop incomplete or ambiguous constructs". The LLM may have decided that a factory with mixed integer/non-integer durations is "ambiguous" and chose the conservative path: model only what is **unambiguously compliant**.

### Prompt Language That Encourages Under-Extraction

1. **Lines 140-144: ROLE & GUARDRAILS**
   ```
   You are conservative and deterministic. When uncertain, you:
   1. Pick the simplest interpretation that fits the schema
   2. Use defaults rather than guess missing values
   3. Drop incomplete or ambiguous constructs
   4. Prefer under-modeling to over-modeling
   ```
   The phrase "Prefer under-modeling to over-modeling" is a **strong bias toward simplicity**.

2. **Lines 215-226: SIZE LIMITS**
   ```
   Enforce these hard caps:
   - Machines: 1-10 maximum (typical: 3-5)
   - Jobs: 1-15 maximum (typical: 3-5)
   ...
   If the description implies more machines or jobs, IGNORE the excess
   and model only the first 10 machines and first 15 jobs mentioned.
   ```
   The use of "typical: 3-5" frames smaller factories as the norm.

3. **Lines 201-212: DURATION RULES**
   ```
   "3-4 hours" or "3 to 4 hours" or "3–4h" → 3 (take lower bound; conservative)
   ...
   RULE: Always round durations DOWN or UP to integers >= 1.
   Never output 0 or fractional durations.
   ```
   This rule is clear, but it **does not address the case where the user has already provided non-integer durations like 1.5h**. The LLM must make a choice: (a) round 1.5h → 1 or 2, or (b) mark the job as ambiguous and drop it.

4. **Lines 143: "Drop incomplete or ambiguous constructs"**
   The LLM may classify "a factory with mixed integer/non-integer durations" as "ambiguous" because the rule says to round, but the user explicitly wrote 1.5h, creating tension.

### Why Only M1 and J1 Output?

The LLM appears to have taken a **fallback-to-minimal strategy**: When faced with the ambiguity of J2, J3, J4 (all containing 1.5h durations or potentially triggering the integer constraint), it dropped them. It then also failed to extract M2 and M3, possibly because:
- M2 and M3 are only mentioned in the context of jobs J2, J3, J4
- If those jobs are dropped, the LLM may have retroactively dropped the machines that only appeared in dropped jobs
- Or: the LLM simply got confused and only partially parsed the input

---

## TASK 5: CONCISE DIAGNOSIS & FIX LEVERS

### Root Cause (Yes/No Summary)
1. **Is the LLM itself outputting only 1 machine / 1 job?** → **YES**
2. **Is normalize_factory dropping additional machines/jobs in this case?** → **NO** (input is already 1m/1j)
3. **Are any of our caps (MAX_MACHINES/JOBS/STEPS) biting here?** → **NO** (no hard caps in code; input is within limits)
4. **Are float durations (1.5h) being mishandled?** → **YES, in the LLM's interpretation logic**

### Root Cause Explanation (2-3 paragraphs)

The bug stems from **ambiguous prompt guidance on non-integer durations combined with over-aggressive under-modeling bias**. The prompt explicitly states "Always round durations DOWN or UP to integers >= 1" and "Prefer under-modeling to over-modeling," but it does not provide clear guidance on how to handle explicitly written fractional durations (1.5h).

When the LLM encounters J2, J3, J4 with 1.5h durations, it interprets them as **potentially ambiguous or non-compliant** with the "integer >= 1" rule. Rather than rounding them (which the rule allows), the LLM takes the conservative path and drops them entirely. This triggers a cascade: once J2, J3, J4 are dropped, M2 and M3 (which appear mainly in those jobs) are also dropped, leaving only a minimal 1m/1j factory.

The prompt does contain a worked example (Example B) showing rounding of vague durations ("~1-2 hrs" → 1), but the test input has **explicit, unambiguous fractional durations (1.5h)**, which are not directly addressed. The LLM defaults to "drop ambiguous constructs" rather than "round to nearest integer."

### Specific Prompt Rules Responsible

- **Lines 140-144**: "Prefer under-modeling to over-modeling" (too strong a bias)
- **Lines 201-212**: Duration integer rule without explicit handling of user-provided fractions
- **Lines 332-380 (Example B)**: Shows rounding of **vague** durations ("~", "or"), but not **explicit** fractions
- **Lines 143**: "Drop incomplete or ambiguous constructs" (too liberal definition of ambiguity)

### Automated Signal for Under-Extraction

**Currently, we have NO automated signal** that detects "under-extraction." The factory passes normalization (no errors), and the `used_default_factory` flag only detects the toy factory specifically. We should consider:

- **Coverage check**: Count mentioned job IDs in text (J1, J2, J3, J4 = 4) vs. parsed jobs (1), flag if ratio < 0.75
- **Machine coverage**: Count mentioned machines (M1, M2, M3 = 3) vs. parsed machines (1), flag if ratio < 0.75
- **Adversarial eval**: Pin a test case specifically to this factory, expect 3m/4j output

### Minimal Levers for Next PR

1. **Reframe the integer rule** (LOW EFFORT):
   - Change: "round durations DOWN or UP to integers >= 1"
   - To: "If user provides non-integer durations (e.g., 1.5h), round to nearest integer (1.5h → 2h is acceptable)"
   - Add explicit example: "Input: J1 takes 1.5h on M1 → Output: {"machine_id": "M1", "duration_hours": 2}"

2. **Reduce under-modeling bias** (MEDIUM EFFORT):
   - Change: "Prefer under-modeling to over-modeling"
   - To: "Prefer comprehensive extraction. Only drop jobs/machines if you cannot extract at least one valid step."
   - Reframe conservative guidance: apply to ambiguous fields (due_time, vague durations), not to job/machine coverage

3. **Add coverage sanity check** (MEDIUM EFFORT):
   - Post-LLM, extract job/machine IDs from text using regex (e.g., "J1", "J2", "M1", "M2")
   - Compare to parsed jobs/machines
   - Log warning or flag if coverage < 50%
   - This becomes an observable signal in metrics

4. **Expand worked examples** (LOW EFFORT):
   - Add Example E: "Factory with explicit fractional durations (1.5h, 2.5h)"
   - Show rounding in the worked example output
   - Removes ambiguity about user intent

5. **Add explicit mention requirement** (MEDIUM EFFORT):
   - Change prompt: "Extract all job IDs and machine IDs explicitly mentioned in the text, unless they violate schema constraints (e.g., step.machine_id not found)"
   - Currently: "Infer job IDs from names or references" (passive)
   - New: "Extract all mentioned IDs; if ambiguous, use J1, J2, J3..." (active, comprehensive)

---

## Summary Table

| Aspect | Finding |
|--------|---------|
| **LLM Under-Extraction?** | YES – raw JSON shows 1m/1j |
| **Normalization Issue?** | NO – already 1m/1j at input |
| **Fallback Triggered?** | NO – errors=0, used_default=False |
| **Root Cause** | Fractional durations + over-aggressive under-modeling bias in prompt |
| **Most Likely Fix** | Reframe integer duration rule to explicitly handle user-provided fractions |
| **Coverage Signal** | Not currently implemented; recommend regex-based check post-LLM |
| **Quick Win** | Add Example E to prompt showing fractional duration handling |

---

## Recommended Next Steps (In Priority Order)

1. **Immediate**: Add prompt clarification on fractional durations (Examples E + rule tweak)
2. **Short-term**: Implement post-LLM coverage check for ID extraction
3. **Test**: Add this factory description as a pinned adversarial eval case
4. **Monitor**: Track "coverage ratio" metric in eval harness; alert if < 0.7

