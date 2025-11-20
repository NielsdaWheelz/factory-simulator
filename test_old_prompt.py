#!/usr/bin/env python3
"""
Test if the OLD verbose prompt works with gpt-4o-mini.

This temporarily restores the old prompt to see if simplification was necessary.
"""

import sys
import os
from unittest.mock import patch

# Test factory text (exact from bug report)
factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).
"""

# OLD PROMPT (before simplification)
OLD_PROMPT_TEMPLATE = """You are a factory description parser. Your job is to interpret free-text descriptions
of factories and extract a structured FactoryConfig.

You will output ONLY valid JSON. No markdown, no prose, no explanation, no comments.

================================================================================
# ROLE & GUARDRAILS
================================================================================

You are conservative and deterministic. When uncertain, you:
1. Pick the simplest interpretation that fits the schema
2. Use defaults rather than guess missing values
3. Drop incomplete or ambiguous constructs
4. Prefer under-modeling to over-modeling

================================================================================
# SCHEMA DEFINITION (Required Output Structure)
================================================================================

You MUST output this exact structure:

{{
  "machines": [
    {{
      "id": "string (e.g., 'M1', 'M2', or descriptive: 'M_ASSEMBLY', 'M_DRILL')",
      "name": "string (human-readable name from text)"
    }}
  ],
  "jobs": [
    {{
      "id": "string (e.g., 'J1', 'J2', or descriptive: 'J_WIDGET_A')",
      "name": "string (human-readable name from text)",
      "steps": [
        {{
          "machine_id": "string (MUST match some machine.id exactly)",
          "duration_hours": "integer >= 1 (hours)"
        }}
      ],
      "due_time_hour": "integer (hour 0-24, or slightly beyond if explicit)"
    }}
  ]
}}

Notes on schema:
- machines.id: Must be unique. Use M1, M2, M3... or descriptive IDs like M_ASSEMBLY.
- machines.name: Human-readable name from the text.
- jobs.id: Must be unique. Use J1, J2, J3... or descriptive IDs like J_WIDGET_A.
- jobs.name: Human-readable name from the text.
- steps: Ordered list. Each step references a machine.id that exists.
- duration_hours: Must be >= 1 (integer). Never 0 or negative.
- due_time_hour: Integer representing hour of day. 24 = end of day. Default = 24.

================================================================================
# TIME INTERPRETATION RULES (MANDATORY - Apply Deterministically)
================================================================================

When you see time expressions, apply these rules EXACTLY:

### DUE TIMES (must be integers)
"by 10am" or "10am" or "due 10am"              → 10
"by noon" or "noon" or "12pm" or "midday"      → 12
"by 3pm" or "3pm"                              → 15
"by 4:30pm" or "4:30pm"                        → 4 (round down, conservative)
"end of day" or "EOD" or "close" or "by close" → 24
Missing due time (no deadline mentioned)       → 24 (default: end of day)

### DURATIONS (must be integers >= 1)
"5 hours" or "5h" or "5 hrs"           → 5
"about 3 hours" or "~3h" or "roughly 3" → 3 (round down; conservative)
"3-4 hours" or "3 to 4 hours" or "3–4h" → 3 (take lower bound; conservative)
"quick" or "fast" or "short"           → 1 (minimum viable duration)
"lengthy" or "long" or "slow"          → 3 (context-dependent; infer conservatively)
"a couple hours"                       → 2
"half hour" or "0.5h"                  → 1 (round up; no sub-hour durations)
Missing duration                       → 1 (default: minimum viable)
Zero or negative duration              → 1 (clamp upward)

RULE: Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations.

================================================================================
# HARD CONSTRAINTS (Final Checklist)
================================================================================

Before outputting JSON, ensure:

1. All machines have unique IDs
2. All jobs have unique IDs
3. All job steps reference existing machine IDs
4. All durations are integers >= 1
5. All due times are integers (typically 1-30)
6. Machine count: 1-10
7. Job count: 1-15
8. Steps per job: 1-8
9. JSON is valid and matches schema exactly

If a constraint is violated, fix it by:
- Dropping the offending job/step entirely
- Filling missing values with defaults
- Picking the simplest interpretation

================================================================================
# OUTPUT INSTRUCTION
================================================================================

Respond with ONLY the JSON object. No markdown, no backticks, no prose, no comments.

Output raw, valid JSON only.

================================================================================
# USER FACTORY DESCRIPTION
================================================================================

{factory_text}

================================================================================
# OUTPUT (JSON ONLY)
================================================================================
"""

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    from backend.models import FactoryConfig
    from backend.llm import call_llm_json

    print("=" * 80)
    print("TEST: OLD VERBOSE PROMPT with gpt-4o-mini")
    print("=" * 80)
    print(f"\nFactory text:\n{factory_text}\n")
    print(f"Prompt length: {len(OLD_PROMPT_TEMPLATE.format(factory_text=factory_text))} chars")

    try:
        prompt = OLD_PROMPT_TEMPLATE.format(factory_text=factory_text)
        cfg = call_llm_json(prompt, FactoryConfig)

        print("\n" + "=" * 80)
        print("RESULT:")
        print("=" * 80)
        print(f"Machines: {len(cfg.machines)}")
        for m in cfg.machines:
            print(f"  - {m.id}: {m.name}")
        print(f"Jobs: {len(cfg.jobs)}")
        for j in cfg.jobs:
            print(f"  - {j.id}: {j.name} ({len(j.steps)} steps)")

        if len(cfg.machines) >= 3 and len(cfg.jobs) >= 4:
            print(f"\n✓ SUCCESS: Got {len(cfg.machines)}m/{len(cfg.jobs)}j - works with old prompt!")
        else:
            print(f"\n✗ FAILURE: Got {len(cfg.machines)}m/{len(cfg.jobs)}j instead of 3m/4j")
            print("   → Old verbose prompt does NOT work with gpt-4o-mini")
            print("   → Simplification was NECESSARY")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
