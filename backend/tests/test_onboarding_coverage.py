"""
Tests for the estimate_onboarding_coverage function.

Tests verify:
- Explicit machine IDs (M1, M2, etc.) mentioned in text are detected
- Explicit job IDs (J1, J2, etc.) mentioned in text are detected
- Warnings are generated for missing machines/jobs
- No warnings when all mentioned entities are present
- No warnings when no explicit IDs are found in text
"""

import pytest
from backend.models import FactoryConfig, Machine, Job, Step
from backend.onboarding import estimate_onboarding_coverage


class TestEstimateOnboardingCoverageMachines:
    """Tests for machine coverage detection."""

    def test_no_warning_when_all_machines_present(self):
        """When all mentioned machines are in the factory, no warnings."""
        factory_text = "We have M1 assembly, M2 drill, M3 pack."
        factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="assembly"),
                Machine(id="M2", name="drill"),
                Machine(id="M3", name="pack"),
            ],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24)],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 0

    def test_warning_when_machines_missing(self):
        """When mentioned machines are missing from factory, warning is generated."""
        factory_text = "We have 3 machines: M1 assembly, M2 drill, M3 pack."
        factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="assembly"),
            ],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24)],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        assert "machines" in warnings[0].lower()
        assert "M2" in warnings[0] and "M3" in warnings[0]

    def test_warning_lists_missing_machines_sorted(self):
        """Missing machines are listed in sorted order."""
        factory_text = "M3, M1, M2 are the machines"
        factory = FactoryConfig(
            machines=[],
            jobs=[],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        # Should be sorted: M1, M2, M3
        assert warnings[0].index("M1") < warnings[0].index("M2") < warnings[0].index("M3")


class TestEstimateOnboardingCoverageJobs:
    """Tests for job coverage detection."""

    def test_no_warning_when_all_jobs_present(self):
        """When all mentioned jobs are in the factory, no warnings."""
        factory_text = "Jobs J1, J2, J3, J4 are processed."
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
                Job(id="J2", name="Job 2", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
                Job(id="J3", name="Job 3", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
                Job(id="J4", name="Job 4", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
            ],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 0

    def test_warning_when_jobs_missing(self):
        """When mentioned jobs are missing from factory, warning is generated."""
        factory_text = "We have jobs J1, J2, J3, J4 to process."
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
            ],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        assert "jobs" in warnings[0].lower()
        assert "J2" in warnings[0] and "J3" in warnings[0] and "J4" in warnings[0]

    def test_warning_lists_missing_jobs_sorted(self):
        """Missing jobs are listed in sorted order."""
        factory_text = "J4, J2, J3, J1 are the orders"
        factory = FactoryConfig(
            machines=[],
            jobs=[],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        # Should be sorted: J1, J2, J3, J4
        assert warnings[0].index("J1") < warnings[0].index("J2") < warnings[0].index("J3") < warnings[0].index("J4")


class TestEstimateOnboardingCoverageBoth:
    """Tests for coverage when both machines and jobs are missing."""

    def test_warnings_for_both_machines_and_jobs(self):
        """When both machines and jobs are missing, both warnings are generated."""
        factory_text = "Machines M1, M2, M3. Jobs J1, J2, J3, J4."
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24)],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 2
        machine_warnings = [w for w in warnings if "machines" in w.lower()]
        job_warnings = [w for w in warnings if "jobs" in w.lower()]
        assert len(machine_warnings) == 1
        assert len(job_warnings) == 1


class TestEstimateOnboardingCoverageEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_no_warning_when_no_explicit_ids_in_text(self):
        """When text has no M* or J* patterns, no warnings even if factory is empty."""
        factory_text = "We operate some machines and process some jobs."
        factory = FactoryConfig(machines=[], jobs=[])
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 0

    def test_regex_word_boundary_respected(self):
        """Machine/job IDs must be word-bounded (e.g., M1 but not EM1)."""
        factory_text = "Emma's machine (EM1) is broken, but M1 works."
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        # Should only find M1, not EM1 due to word boundary
        assert len(warnings) == 0

    def test_descriptive_machine_ids(self):
        """Descriptive machine IDs like M_ASSEMBLY are detected."""
        factory_text = "We have M_ASSEMBLY, M_DRILL, M_PACK machines."
        factory = FactoryConfig(
            machines=[
                Machine(id="M_ASSEMBLY", name="Assembly"),
                Machine(id="M_DRILL", name="Drill"),
            ],
            jobs=[],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        assert "M_PACK" in warnings[0]

    def test_descriptive_job_ids(self):
        """Descriptive job IDs like J_WIDGET_A are detected."""
        factory_text = "Jobs: J_WIDGET_A, J_WIDGET_B, J_GADGET_C."
        factory = FactoryConfig(
            machines=[],
            jobs=[
                Job(id="J_WIDGET_A", name="Widget A", steps=[], due_time_hour=24),
            ],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 1
        assert "J_WIDGET_B" in warnings[0] and "J_GADGET_C" in warnings[0]

    def test_case_sensitivity(self):
        """Machine/job IDs are matched case-sensitively (M1 != m1)."""
        factory_text = "M1 is the main machine, m1 is lowercase."
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        # m1 should not match M1
        assert len(warnings) == 0

    def test_exact_text_example_from_spec(self):
        """Test with the exact 3m/4j factory description from the spec."""
        factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h)."""

        # Simulate under-extraction: only J1 and M1 parsed
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="assembly")],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24)],
        )
        warnings = estimate_onboarding_coverage(factory_text, factory)
        assert len(warnings) == 2
        # Should have both machine and job warnings
        machine_warn = [w for w in warnings if "machines" in w.lower()][0]
        job_warn = [w for w in warnings if "jobs" in w.lower()][0]
        assert "M2" in machine_warn and "M3" in machine_warn
        assert "J2" in job_warn and "J3" in job_warn and "J4" in job_warn
