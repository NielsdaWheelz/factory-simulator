# World-Class Factory Description Parser Prompt

## Overview

This document describes what a world-class prompt for parsing factory descriptions should include. The current prompt is functional but good; a world-class version would add several dimensions for robustness, clarity, and extensibility.

---

## 1. **Clarity: Separate Concerns Into Sections**

### Current Approach
All rules crammed into "CRITICAL RULES" section.

### World-Class Approach
Separate into distinct sections:

```
├─ PARSING PRINCIPLES (meta-level rules about how to interpret)
├─ EXPLICIT RULES (mandatory dos and don'ts)
├─ IMPLICIT RULES (what to infer, what not to infer)
├─ ERROR HANDLING (what to do when input is ambiguous/contradictory)
├─ SCHEMA (data structure definition)
├─ EXAMPLES (taught patterns)
└─ USER INPUT & OUTPUT (the actual task)
```

**Why**: Each section serves a different cognitive function. Grouping them helps the LLM focus.

---

## 2. **Robustness: Conflict Resolution Rules**

### Current Approach
Rule 2 says "trust explicit steps over patterns" but doesn't specify how to resolve all conflicts.

### World-Class Approach
Explicit conflict resolution hierarchy:

```
CONFLICT RESOLUTION HIERARCHY (in order of priority)

When the description contains contradictory information, apply these rules in order:

1. EXPLICIT STEPS BEAT PATTERNS
   - If a job explicitly lists machines (e.g., "J1: M1 2h, M2 3h, M4 1h"), use exactly those.
   - Ignore any narrative description that contradicts explicit steps.

2. DECLARED MACHINES BEAT INFERRED MACHINES
   - If text declares "4 machines: M1, M2, M3, M4", include all four.
   - Even if some machines appear only in job descriptions (never mentioned in machine list).

3. EXPLICIT DURATIONS BEAT NARRATIVES
   - If "3-4 hours" is stated, round to 3 (floor not ceiling).
   - If "about 2h" is stated, use 2 exactly.

4. USE DEFAULTS FOR MISSING VALUES
   - Missing duration → 1 hour
   - Missing due time → 24 (end of day)
   - But: Never use a default that drops information

5. PRESERVE ALL MENTIONED ENTITIES
   - Never drop a machine because only some jobs use it
   - Never drop a job because it has no valid steps
   - Never drop a step because its duration was rounded from fractional
```

**Why**: Prevents the LLM from "deciding" how to resolve conflicts; explicit hierarchy removes ambiguity.

---

## 3. **Teachability: Multiple Worked Examples**

### Current Approach
Two examples (uniform jobs, non-uniform jobs).

### World-Class Approach
Six worked examples covering:

1. **Baseline**: Uniform 3m/4j
2. **Non-Uniform**: Mixed job paths (current example 2)
3. **Sparse Usage**: A machine used by only 1 job
4. **Ambiguous Durations**: "3-4 hours", "about 2", "quick"
5. **Missing Machines**: Job mentions a machine not in machine list
6. **Partial Data**: No due times, no machine names

**Example for #3 (Sparse Usage)**:
```
INPUT:
We have 3 machines: M1 (saw), M2 (drill), M3 (paint).
Jobs: J1 (assembly), J2 (finishing).
J1: 2h on M1, 3h on M2 (total 5h)
J2: 1h on M1, 2h on M2, 1h on M3 (total 4h)

Notice: M3 is only used by J1, not by J2. That's OK—preserve M3.

OUTPUT:
{
  "machines": [
    {"id": "M1", "name": "saw"},
    {"id": "M2", "name": "drill"},
    {"id": "M3", "name": "paint"}
  ],
  ...
}
```

**Why**: Each example teaches a different pattern. More examples = better generalization.

---

## 4. **Precision: Machine and Job ID Extraction Rules**

### Current Approach
Implicit assumption that IDs are in format like "M1", "J1".

### World-Class Approach
Explicit ID format specification:

```
MACHINE AND JOB ID EXTRACTION

Machine IDs:
- Format: M (uppercase) followed by one or more digits or letters
  Examples: M1, M2, M_ASSEMBLY, M01, M_PREP_PAINT
- Must be explicitly mentioned or implied from machine list
- Extract from both machine declaration and job step descriptions

Job IDs:
- Format: J (uppercase) followed by one or more digits or letters
  Examples: J1, J2, J_WIDGET_A, J01
- Must be explicitly mentioned in job names or descriptions
- Never invent job IDs

Machine Names:
- Text immediately following or describing the machine ID
- Examples: "M1 (assembly)" → name="assembly"
- Examples: "M1 assembly station" → name="assembly station"
- Keep names concise, extracted directly from text

Job Names:
- Text immediately following or describing the job ID
- Examples: "J1 widget assembly" → name="widget assembly"
- Default if missing: "Job {ID}"
```

**Why**: Removes ambiguity about what counts as an ID and prevents hallucinated IDs.

---

## 5. **Safety: Invalid Input Handling**

### Current Approach
No explicit guidance on what to do if input is nonsensical.

### World-Class Approach
Add a section on invalid input:

```
INVALID INPUT HANDLING

If the input contains logical impossibilities, use these rules:

1. INCONSISTENT MACHINE COUNTS
   Input: "We have 3 machines. Machines: M1, M2, M3, M4"
   → Use all 4 (declaration beats count)

2. JOBS WITH NO MACHINES
   Input: "J1 is a job" (but no machines listed for J1)
   → Assign 1 hour to a default/first available machine if possible
   → Otherwise drop the job and warn

3. CIRCULAR DEPENDENCIES
   Input: "J1 requires J2 first" (not applicable for this schema)
   → Ignore ordering requirements, extract only machine/time info

4. NEGATIVE OR ZERO DURATIONS
   Input: "J1 takes 0h on M1"
   → Set to 1 hour

5. OUT-OF-RANGE DUE TIMES
   Input: "Due at 25:00 (midnight next day)"
   → Clamp to 24 or infer from context
   → If impossible to infer, use 24
```

**Why**: Prevents the LLM from inventing solutions or silently failing on edge cases.

---

## 6. **Transparency: Assumption Documentation**

### Current Approach
No section on what assumptions the LLM is making.

### World-Class Approach
Add assumptions section:

```
ASSUMPTIONS YOU MAY NEED TO MAKE

If input is underspecified, these are acceptable inferences:

1. Machine Names
   - If a machine is referred to only as "M1" with no description, use "Machine M1"
   - Extract actual names from descriptions like "M1 assembly station"

2. Job Names
   - If a job is referred to only as "J1" with no description, use "Job J1"

3. Step Ordering
   - Preserve the order machines are mentioned in job descriptions
   - Example: "J1: M2 first (1h), then M1 (2h)" → steps in order [M2, M1]

4. Missing Durations
   - Default to 1 hour if a job mentions a machine but no duration
   - Flag in mental notes that a default was used

5. Ambiguous Time Language
   - "Quick" → 1 hour
   - "About 2 hours" → 2 hours
   - "2-3 hours" → 2 hours (floor not ceiling)
   - "Less than an hour" → 1 hour (minimum)

DO NOT ASSUME:
- That all machines are used by all jobs
- That job order is sequential (J1 before J2)
- That machines must be used in alphabetical order
- That jobs have uniform patterns
- Machine or job properties beyond name and ID
```

**Why**: Clarifies what inferences are OK vs. forbidden. Prevents hallucinations.

---

## 7. **Validation: Self-Check Rules**

### Current Approach
No guidance on how to validate the output before returning it.

### World-Class Approach
Add validation section:

```
BEFORE YOU OUTPUT, VALIDATE:

Checklist for your JSON output:

1. MACHINES
   □ Every machine mentioned in the input appears in the machines list
   □ Each machine has an id (e.g., "M1") and name (e.g., "assembly")
   □ No duplicate machine IDs

2. JOBS
   □ Every job mentioned in the input appears in the jobs list
   □ Each job has an id (e.g., "J1"), name, steps list, and due_time_hour
   □ No duplicate job IDs
   □ due_time_hour is an integer between 0 and 24

3. STEPS
   □ Each step has a machine_id that corresponds to a declared machine
   □ Each step has duration_hours as an integer >= 1
   □ No step references a machine that doesn't exist
   □ Steps are listed in the order they occur (as stated in input)

4. COVERAGE
   □ If input declares "4 machines", the output has 4 machines
   □ If input names "4 jobs", the output has 4 jobs

5. INTERNAL CONSISTENCY
   □ All job IDs referenced in steps exist in the jobs list
   □ All machine IDs referenced in steps exist in the machines list
   □ No null or missing fields in the output JSON

If validation fails on any point, output an error explaining which validation failed
and why, rather than returning incomplete JSON.
```

**Why**: LLMs often produce JSON that passes basic validation but violates domain rules. This checklist catches those.

---

## 8. **Format: Structure for Scannability**

### Current Approach
Sections marked with "===", linear text layout.

### World-Class Approach
Add visual hierarchy:

```
Use consistent visual markers:
├─ Sections: === SECTION NAME ===
├─ Subsections: -- Subsection --
├─ Lists: • bullet or - dash
├─ Code blocks: ```json ... ```
├─ Emphasis: **bold** for critical terms
└─ Examples: EXAMPLE: ... or COUNTEREXAMPLE: ...

Organize by cognitive load:
1. Principles (why)
2. Rules (what)
3. Examples (how)
4. Validation (check)
```

**Why**: Helps the LLM navigate the prompt more efficiently and reduces parsing errors.

---

## 9. **Tone: Direct and Action-Oriented**

### Current Approach
Mix of prescriptive ("NEVER drop") and descriptive ("If text says").

### World-Class Approach
Consistent imperative tone:

```
INSTEAD OF:
"If text says M1, M2, M3, you should include all three."

USE:
"Include all machines mentioned in the text. Example: If text says 'M1, M2, M3',
output all three in the machines list."

INSTEAD OF:
"Missing machine in step → drop that step only, keep job"

USE:
"When a step references a non-existent machine, drop that step (not the job).
Example: If J1 has a step on 'M99' but M99 is not declared, drop that step
but keep J1 with its remaining steps."
```

**Why**: Reduces ambiguity. Imperative form is easier for LLMs to follow than conditional form.

---

## 10. **Completeness: Cover Edge Cases**

### Current Approach
Covers main cases (uniform jobs, non-uniform jobs).

### World-Class Approach
Add edge case section:

```
EDGE CASES

These are rare but possible. Handle them as follows:

1. A job with zero valid steps
   → Drop the entire job
   → Log: "Job J1 has no valid steps after filtering"

2. A machine with zero jobs
   → Keep it in the machines list (declared, not inferred)
   → Log: "Machine M4 is declared but not used by any job"

3. Duplicate machine mentions
   Input: "Machines: M1, M2, M1, M3"
   → Include M1 only once (deduplicate)

4. Mixed naming conventions
   Input: "M-1, M1, machine-1 all refer to the same thing"
   → Normalize to canonical form (M1)
   → Log the normalization

5. No machines or jobs mentioned
   Input: "Run a simulation" (no machine or job details)
   → Return empty factory or default factory
   → Do not hallucinate machines/jobs

6. Extremely large factories
   Input: "100 machines, 1000 jobs"
   → Still parse completely, do not truncate
   → Preserve all details
```

**Why**: Edge cases are where LLMs typically fail. Explicit handling prevents failures.

---

## 11. **Explicitness: Remove Implicit Assumptions**

### Current Approach
Assumes LLM understands "parse factory text into FactoryConfig."

### World-Class Approach
Make implicit assumptions explicit:

```
WHAT YOU SHOULD DO

You are acting as a deterministic factory parser. Your job is to:
1. Read the user's natural language factory description
2. Extract all explicitly mentioned machines and jobs
3. Map each job to its sequence of machines and durations
4. Output a structured FactoryConfig in JSON

You are NOT:
- Writing a simulation or scheduler
- Optimizing anything
- Making business decisions
- Inferring missing factories or jobs
- Creating new entities

Your output is ONLY the configuration, not analysis or recommendations.
```

**Why**: Prevents the LLM from "being helpful" by adding extra information (which introduces errors).

---

## 12. **Failure Modes: What NOT to Do**

### Current Approach
Rule 1 says "NEVER drop a machine" but doesn't explain why or show failure cases.

### World-Class Approach
Add failure modes section:

```
COMMON FAILURE MODES (DO NOT DO THESE)

1. Normalizing inconsistent patterns
   BAD: Input says "J1→M2→M4, J2→M1→M2→M3" but you output "All jobs use M1→M2→M3"
   GOOD: Output J1 with steps on M2, M4 and J2 with steps on M1, M2, M3

2. Inferring missing machines
   BAD: Input says "M1, M2, M3" and job mentions "M4" → you infer M4 is "system state"
   GOOD: Include M4 in machines list if it's mentioned, drop the job step if M4 isn't declared

3. Dropping entities for being "incomplete"
   BAD: "J1 has no due time" → drop J1
   GOOD: Use default due time (24)

4. Reordering job steps
   BAD: Input says "J1: M3 then M1 then M2" → you output "M1, M2, M3"
   GOOD: Preserve the order stated in input

5. Combining jobs or machines
   BAD: Input mentions "J1" and "Job 1" → you consolidate as one
   GOOD: Treat as separate entities unless explicitly stated otherwise

6. Inventing names
   BAD: "M1 (no name given)" → you output name="assembly" (guessing)
   GOOD: Use name="M1" or extract name from text only
```

**Why**: Shows what the LLM should explicitly avoid. Negative examples are often more effective than positive ones.

---

## 13. **Output Format: Be Specific**

### Current Approach
"Output ONLY valid JSON" at the start.

### World-Class Approach
Detailed output format section:

```
OUTPUT FORMAT

You must output ONLY valid JSON matching this schema. No markdown, no explanation.

{
  "machines": [
    {
      "id": "string, e.g., M1, M2, M_ASSEMBLY",
      "name": "string, extracted from text or provided as default"
    }
  ],
  "jobs": [
    {
      "id": "string, e.g., J1, J2",
      "name": "string, extracted from text or provided as default",
      "steps": [
        {
          "machine_id": "string, must reference a machine in machines list",
          "duration_hours": "integer >= 1"
        }
      ],
      "due_time_hour": "integer, 0-24 inclusive"
    }
  ]
}

Rules for your output:
- ONLY output JSON, no explanation or markdown
- JSON must be parseable by Python's json.loads()
- All string values must be in double quotes
- All integer values must not be quoted
- Field order doesn't matter
- No trailing commas
- If you cannot produce valid JSON, output an error JSON: {"error": "reason"}

Example of VALID JSON:
{
  "machines": [{"id": "M1", "name": "assembly"}],
  "jobs": [
    {
      "id": "J1",
      "name": "widget",
      "steps": [{"machine_id": "M1", "duration_hours": 2}],
      "due_time_hour": 24
    }
  ]
}

Example of INVALID JSON (DO NOT DO THIS):
{
  "machines": [{"id": M1, "name": assembly}],  // Missing quotes
  "jobs": [...],
}
```

**Why**: Many LLM errors come from malformed JSON. Being explicit prevents this.

---

## 14. **Recovery: What to Do If Parsing Fails**

### Current Approach
No section on what to do if parsing is impossible.

### World-Class Approach
Add recovery section:

```
IF YOU CANNOT PARSE THE INPUT

If the input is ambiguous or impossible to parse, output this error JSON:

{
  "error": "Cannot parse factory description",
  "reason": "Specific explanation of what is ambiguous or missing",
  "suggestions": "How to clarify the input"
}

Example:
{
  "error": "Cannot parse factory description",
  "reason": "Job J1 references machines M1 and M2, but neither is declared in the machine list",
  "suggestions": "Declare all machines before listing jobs, or reference only declared machines"
}

Common reasons for parsing failure:
- No machines are mentioned
- No jobs are mentioned
- A job references a machine that's never mentioned
- The input is too ambiguous to extract any structure
```

**Why**: Helps the system gracefully degrade rather than returning hallucinated data.

---

## Summary: What Makes a Prompt World-Class

| Dimension | Current | World-Class |
|-----------|---------|------------|
| Clarity | Rules grouped together | Separated by concern |
| Robustness | "Trust explicit" mentioned | Full conflict resolution hierarchy |
| Teachability | 2 examples | 6+ examples covering edge cases |
| Precision | Implicit ID format | Explicit ID extraction rules |
| Safety | Limited edge case handling | Comprehensive edge case section |
| Transparency | No assumptions stated | Explicit assumptions & forbidden inferences |
| Validation | No validation guidance | Pre-output validation checklist |
| Format | Linear text | Visual hierarchy with markers |
| Tone | Mixed | Consistent imperative |
| Completeness | Main cases covered | Rare cases explicitly handled |
| Explicitness | Implicit goals | Explicit role & responsibilities |
| Failure Modes | Scattered in rules | Dedicated section with anti-patterns |
| Output Format | "valid JSON" | Detailed schema with examples |
| Recovery | None | Error handling with suggestions |

---

## Implementation Path

To upgrade the current prompt to world-class:

1. **Phase 1** (Critical): Add conflict resolution hierarchy + second worked example (DONE)
2. **Phase 2** (High): Add edge case section + validation checklist + failure modes
3. **Phase 3** (Medium): Add 4 more worked examples + assumptions section + recovery section
4. **Phase 4** (Nice-to-have): Reformat for visual hierarchy + add explicit role/responsibilities

Current estimated token cost: ~1,200 tokens
World-class estimated token cost: ~2,500 tokens

**Trade-off**: +1,300 tokens for significantly higher parsing accuracy and robustness.
