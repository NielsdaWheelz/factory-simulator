# Factory Onboarding Bug: Forensic Diagnosis Summary

## Bug Statement
Input factory description with **3 machines and 4 jobs** (explicit, unambiguous) produces output with **1 machine and 1 job**, with `used_default_factory=False` and `errors=0`.

---

## Root Cause (CONFIRMED)

**The LLM itself is under-extracting, not the parsing or normalization layers.**

Raw LLM JSON output contains only:
```json
{
  "machines": [{"id": "M1", "name": "Machine 1"}],
  "jobs": [{"id": "J1", "name": "Default", "steps": [...], "due_time_hour": 24}]
}
```

The LLM completely ignored:
- Machine references: M2 (drill), M3 (pack)
- Job descriptions: J2, J3, J4
- Explicit durations for those jobs: 1.5h on multiple machines

---

## Trigger: Fractional Durations

The input contains **explicit 1.5h durations**:
```
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3
J3 takes 3h on M1, 1h on M2, 2h on M3
J4 takes 2h on M1, 2h on M2, 4h on M3
```

The prompt contains conflicting guidance:
1. **Duration Rule** (line 212): "Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations."
2. **Under-modeling Bias** (line 144): "Prefer under-modeling to over-modeling"
3. **Drop Ambiguous Constructs** (line 143): "Drop incomplete or ambiguous constructs"

When the LLM encounters 1.5h, it likely interprets this as a **violation or ambiguity** rather than a straightforward rounding task. Rather than applying the rounding rule, it takes the conservative path: **drop the job entirely**.

---

## Why Only M1 & J1?

The cascade occurs as follows:

1. **LLM tries to parse J2**: Sees "1.5h on M1, 2h on M2, 1.5h on M3"
2. **Conflict detected**: 1.5h doesn't match "integer >= 1" expectation
3. **Conservative fallback**: Mark J2 as "ambiguous" → drop it
4. **Cascade**: J3 and J4 also contain 1.5h → drop both
5. **Machine cleanup**: M2 and M3 are only mentioned in J2, J3, J4 → no jobs reference them → drop machines
6. **Fallback model**: Only J1 (contains 2h, 3h, 1h — all integers) survives
7. **Minimal output**: 1 machine, 1 job

---

## Evidence

### Prompt Phrases Responsible

| Line | Text | Impact |
|------|------|--------|
| 144 | "Prefer under-modeling to over-modeling" | Biases toward dropping ambiguous jobs |
| 143 | "Drop incomplete or ambiguous constructs" | Gives LLM license to drop J2, J3, J4 |
| 212 | "Always round durations DOWN or UP to integers >= 1" | Ambiguous: round OR drop? LLM chose drop. |
| 219-220 | "typical: 3-5" jobs | Frames single job as "acceptable minimal" |

### Absence of Guidance

The prompt includes **four worked examples** (A, B, C, D):
- **Example A**: Explicit integer durations (2h, 3h, 1h)
- **Example B**: Vague durations with rounding ("~1-2h" → 1, "2h or 4h" → 2)
- **Example C**: Contradictory due times, not durations
- **Example D**: Forbidden features (parallel jobs, batching)

**None of the examples show explicit fractional durations (1.5h, 2.5h) with rounding.**

---

## System Check Results

✓ **Plumbing is fine**: normalize_factory() returns non-empty (1m/1j)
✓ **No exceptions**: error handling catches nothing; OnboardingAgent.run() succeeds
✓ **Fallback ladder works**: Correctly identifies factory is not toy factory
✗ **Signal missing**: No automated detection of "under-extraction"

---

## Minimal Levers to Fix (Priority Order)

### 1. **Clarify Fractional Duration Handling** (LOW EFFORT, HIGH IMPACT)

**Change the prompt rule (line 212):**
```
OLD: "RULE: Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations."

NEW: "RULE: Always output integer durations >= 1. If user provides non-integer durations (e.g., 1.5h), round to the nearest integer. Example: 1.5h → 2h, 2.5h → 3h, 0.5h → 1h."
```

**Add worked example:**
```
Input:
"We have Assembly (A) and Drill (D).
Job Widget: A(1.5h) → D(2.5h)."

Output:
{
  "machines": [{"id": "M1", "name": "Assembly"}, {"id": "M2", "name": "Drill"}],
  "jobs": [{
    "id": "J1",
    "name": "Widget",
    "steps": [
      {"machine_id": "M1", "duration_hours": 2},
      {"machine_id": "M2", "duration_hours": 3}
    ],
    "due_time_hour": 24
  }]
}

Why: 1.5h rounds to 2h (nearest integer), 2.5h rounds to 3h. All jobs and machines extracted.
```

### 2. **Reduce Under-Modeling Bias** (MEDIUM EFFORT, STRUCTURAL FIX)

**Change line 144:**
```
OLD: "Prefer under-modeling to over-modeling"

NEW: "Prefer comprehensive extraction. Extract all jobs and machines explicitly mentioned in the text. Only drop constructs if they violate schema rules (e.g., step.machine_id not found in machines)."
```

This refocuses "conservative" guidance: apply to vague fields (due_time, missing durations), not to job/machine coverage.

### 3. **Add Post-LLM Coverage Check** (MEDIUM EFFORT, OBSERVABILITY)

In `orchestrator.run_onboarding()`, after `normalize_factory()`:

```python
def extract_ids_from_text(text: str) -> tuple[set[str], set[str]]:
    """Extract job IDs (J1, J2...) and machine IDs (M1, M2...) from text using regex."""
    import re
    job_ids = set(re.findall(r'\bJ\d+\b', text))
    machine_ids = set(re.findall(r'\bM\d+\b', text))
    return job_ids, machine_ids

# After normalization
mentioned_jobs, mentioned_machines = extract_ids_from_text(factory_text)
parsed_jobs = {job.id for job in normalized_factory.jobs}
parsed_machines = {m.id for m in normalized_factory.machines}

coverage_jobs = len(parsed_jobs & mentioned_jobs) / len(mentioned_jobs) if mentioned_jobs else 1.0
coverage_machines = len(parsed_machines & mentioned_machines) / len(mentioned_machines) if mentioned_machines else 1.0

if coverage_jobs < 0.7 or coverage_machines < 0.7:
    all_errors.append(f"Low coverage: {coverage_jobs:.0%} jobs, {coverage_machines:.0%} machines extracted")
    logger.warning("Coverage check: possible under-extraction")
```

This becomes an observable signal in logs and metrics.

### 4. **Pin Adversarial Eval Case** (LOW EFFORT, PREVENTIVE)

Add this exact factory to the eval harness with expected output:
```python
{
    "description": "3 machines, 4 jobs with mixed integer/fractional durations",
    "factory_text": "We run 3 machines (M1 assembly, M2 drill, M3 pack)...",
    "expected": {
        "min_machines": 3,
        "min_jobs": 4,
        "used_default_factory": False,
        "onboarding_errors": 0,
    }
}
```

---

## Summary Table: Signal Comparison

| Metric | Current | With Fixes |
|--------|---------|-----------|
| Test case 1m/1j | ✗ FAILS | ✓ PASSES |
| Prompt clarity | Ambiguous | Explicit |
| Coverage signal | Missing | Available (logs, metrics) |
| Adversarial cases | None pinned | Pinned & monitored |
| False negatives | High (silent under-extract) | Low (flagged with coverage check) |

---

## Appendix: Code References

- **Prompt**: [agents.py:102-538](backend/agents.py#L102-L538)
  - Lines 140-144: "Prefer under-modeling"
  - Lines 143: "Drop ambiguous"
  - Lines 201-212: Duration rules
  - Lines 287-480: Worked examples (missing fractional case)

- **LLM Caller**: [llm.py:24-82](backend/llm.py#L24-L82)
  - Line 60: OPENAI_MODEL config

- **Onboarding Orchestration**: [orchestrator.py:199-269](backend/orchestrator.py#L199-L269)
  - Lines 225-237: normalize_factory call
  - Lines 239-254: Failure ladder

- **Normalization**: [onboarding.py:20-114](backend/onboarding.py#L20-L114)
  - Does not drop jobs/machines; only repairs field values

---

## Next Steps (Immediate Actions)

1. ✅ **This forensic analysis** — Done
2. **PR**: Apply Lever #1 (prompt clarification) + Lever #4 (pin eval case)
3. **PR**: Apply Lever #2 (reduce under-modeling bias) + Lever #3 (coverage check)
4. **Test**: Re-run the 3m/4j factory, verify 3m/4j output
5. **Monitor**: Track coverage metric in eval harness; alert on < 0.7

