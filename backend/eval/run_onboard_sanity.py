"""
PR5 Onboarding Sanity Harness - Quick Real-LLM Verification

Runs a small set of canonical factory descriptions through the full onboarding pipeline
with real LLM calls. Prints a concise summary for eyeballing behavior.

This is a MANUAL-ONLY sanity script (not part of pytest).
Do NOT import or run this from test suites.

Usage:
    python -m backend.eval.run_onboard_sanity

Output:
    For each test case, prints:
    - Case name and description
    - Detected machine/job IDs (from stage 0)
    - Final factory machines/jobs (from stage 3+)
    - Coverage assessment
    - Whether fallback was triggered
    - Any onboarding errors

No assertions, no structured output - just eyeball-friendly summaries.
"""

import sys
from typing import Any

from backend.onboarding import extract_explicit_ids, ExtractionError
from backend.orchestrator import run_onboarding, is_toy_factory
from backend.models import OnboardingMeta, FactoryConfig


# ============================================================================
# TEST CASES: Canonical Examples + Edge Cases
# ============================================================================

TEST_CASES = [
    {
        "id": "canonical_good",
        "name": "Canonical: Clean 3-machine, 3-job factory",
        "text": """
We operate a small manufacturing facility with 3 machines and 3 products.

Machines:
- M1: Assembly line (30 units/day capacity)
- M2: Quality check drill (20 units/day)
- M3: Packaging station (25 units/day)

Jobs:
- J1: Standard widget assembly (due 8h)
  - 2 hours on M1 (assembly)
  - 1 hour on M2 (QC check)
  - 0.5 hour on M3 (pack)

- J2: Premium gadget (due 12h)
  - 3 hours on M1
  - 2 hours on M2
  - 1 hour on M3

- J3: Bulk parts order (due 10h)
  - 1 hour on M1
  - 1.5 hours on M2
  - 2 hours on M3
""",
    },
    {
        "id": "messy_sop",
        "name": "Messy: SOP-like text with chatter but parseable",
        "text": """
STANDARD OPERATING PROCEDURE - PRODUCTION FLOW

Okay so we have this facility with equipment. Here's the basic flow:

**Machine M_ASSEMBLY**: This is our main assembly station. It's pretty busy.
**Machine M_QUALITY**: Quality check machine, sometimes slow.
**Machine M_PACKING**: Packing/shipping station.

For products:
- We handle J_WIDGET jobs. For J_WIDGET: 2.5h on M_ASSEMBLY, then 1h on M_QUALITY, then 0.75h on M_PACKING. Due by end of shift (8h).
- Also J_GADGET jobs: 3h on M_ASSEMBLY, 2h on M_QUALITY, then 1.5h on M_PACKING. Due 12h.

Note: M_QUALITY is often the bottleneck. M_PACKING is pretty quick.
We need to watch for due date violations on J_GADGET especially.
""",
    },
    {
        "id": "broken_minimal",
        "name": "Broken: Intentionally vague/unparseable",
        "text": """
We make stuff with machines. Sometimes it takes a while.
Not sure how many machines or jobs we have.
Production is chaotic.
No specific details available.
""",
    },
]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def print_section(title: str) -> None:
    """Print a visual section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_case_summary(case_id: str, name: str) -> None:
    """Print case identifier."""
    print(f"[CASE: {case_id}]")
    print(f"  Name: {name}")
    print()


def run_case(case: dict[str, Any]) -> None:
    """
    Run a single test case through onboarding and print results.

    Does NOT raise exceptions; all errors are printed in summary form.
    """
    case_id = case["id"]
    case_name = case["name"]
    factory_text = case["text"]

    print_case_summary(case_id, case_name)

    # ========================================================================
    # STAGE 0: Explicit ID extraction (deterministic, no LLM)
    # ========================================================================
    try:
        explicit_ids = extract_explicit_ids(factory_text)
        detected_machines = sorted(explicit_ids.machine_ids)
        detected_jobs = sorted(explicit_ids.job_ids)
        print(f"  Stage 0 (Explicit ID extraction):")
        print(f"    Detected machines: {detected_machines if detected_machines else '(none)'}")
        print(f"    Detected jobs:     {detected_jobs if detected_jobs else '(none)'}")
    except Exception as e:
        print(f"  Stage 0 FAILED: {e}")
        detected_machines, detected_jobs = [], []

    # ========================================================================
    # FULL PIPELINE: Stages 1-4 via run_onboarding (with fallback)
    # ========================================================================
    print()
    print(f"  Stages 1-4 (Multi-stage LLM pipeline with fallback):")
    try:
        factory, meta = run_onboarding(factory_text)

        # Extract final IDs from factory
        final_machines = sorted([m.id for m in factory.machines])
        final_jobs = sorted([j.id for j in factory.jobs])

        print(f"    Final factory machines: {final_machines}")
        print(f"    Final factory jobs:     {final_jobs}")
        print(f"    Used default factory:   {meta.used_default_factory}")

        # Coverage assessment
        if detected_machines or detected_jobs:
            detected_set_m = set(detected_machines)
            detected_set_j = set(detected_jobs)
            final_set_m = set(final_machines)
            final_set_j = set(final_jobs)
            missing_m = detected_set_m - final_set_m
            missing_j = detected_set_j - final_set_j

            if missing_m or missing_j:
                coverage_msg = "Coverage < 100%:"
                if missing_m:
                    coverage_msg += f" missing machines {sorted(missing_m)}"
                if missing_j:
                    coverage_msg += f" missing jobs {sorted(missing_j)}"
                print(f"    Coverage: {coverage_msg}")
            else:
                print(f"    Coverage: 100% (all detected IDs in final factory)")
        else:
            print(f"    Coverage: N/A (no explicit IDs detected in text)")

        # Onboarding errors
        if meta.onboarding_errors:
            print(f"    Onboarding errors:")
            for err in meta.onboarding_errors:
                print(f"      - {err}")
        else:
            print(f"    Onboarding errors: (none)")

        # Is it toy factory?
        is_toy = is_toy_factory(factory)
        print(f"    Is toy factory:     {is_toy}")

    except ExtractionError as e:
        print(f"    Pipeline raised ExtractionError: {e.code}")
        print(f"    Message: {e.message}")
        if e.details:
            print(f"    Details: {e.details}")

    except Exception as e:
        print(f"    Pipeline raised {type(e).__name__}: {e}")

    print()


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    """Run all test cases and print summaries."""
    print_section("PR5 Onboarding Sanity Harness")
    print("Running canonical test cases through multi-stage LLM pipeline.")
    print("(With real LLM calls - this may take a minute.)\n")

    for case in TEST_CASES:
        run_case(case)

    print_section("Sanity Check Complete")
    print("Eyeball the outputs above to verify expected behavior:")
    print("  1. Canonical good case: Should parse cleanly with 100% coverage.")
    print("  2. Messy case: Should parse despite chatter, maybe with some coverage loss.")
    print("  3. Broken case: Should fall back to toy factory with clear error message.")
    print()


if __name__ == "__main__":
    main()
