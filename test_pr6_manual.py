#!/usr/bin/env python3
"""
Manual test for PR6: Run the 3m/4j factory against the real LLM
with the updated prompt to verify the fix works.

This requires OPENAI_API_KEY to be set.

Usage:
    python test_pr6_manual.py

Expected output (after PR6 fix):
    Machines: 3 (M1, M2, M3)
    Jobs: 4 (J1, J2, J3, J4)
    Coverage warnings: None (or minimal)
"""

import sys
import os
from backend.orchestrator import run_onboarding

factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).
"""

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    print("=" * 80)
    print("PR6 MANUAL TEST: 3 machines, 4 jobs with fractional durations")
    print("=" * 80)

    factory, meta = run_onboarding(factory_text)

    print(f"\n✓ Machines: {len(factory.machines)}")
    for m in factory.machines:
        print(f"  - {m.id}: {m.name}")

    print(f"\n✓ Jobs: {len(factory.jobs)}")
    for j in factory.jobs:
        print(f"  - {j.id}: {j.name} ({len(j.steps)} steps)")

    print(f"\n✓ Onboarding Errors: {len(meta.onboarding_errors)}")
    if meta.onboarding_errors:
        for err in meta.onboarding_errors:
            if "coverage warning" in err.lower():
                print(f"  ⚠ {err}")
            else:
                print(f"  ✗ {err}")

    print(f"\n✓ Used Default: {meta.used_default_factory}")

    print("\n" + "=" * 80)
    if len(factory.machines) >= 3 and len(factory.jobs) >= 4:
        print("SUCCESS! LLM extracted all machines and jobs correctly.")
        print("Coverage warnings may be present (expected) but factory is complete.")
    else:
        print(f"FAILURE! LLM under-extracted: got {len(factory.machines)}m/{len(factory.jobs)}j, expected 3m/4j")
        sys.exit(1)
