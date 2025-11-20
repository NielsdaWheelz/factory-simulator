"""
Tests for the normalize_factory function.

Tests verify:
- Duration normalization: invalid or missing durations are set to 1
- Due time normalization: invalid or missing due times are set to 24
- Invalid machine references are dropped
- Jobs with no valid steps are dropped
- Fallback to toy factory when factory becomes empty
- Normalization warnings are properly returned
"""

import pytest
from backend.models import FactoryConfig, Machine, Job, Step
from backend.world import build_toy_factory
from backend.onboarding import normalize_factory


class TestNormalizeFactoryDurationFix:
    """Tests for step duration_hours normalization."""

    def test_zero_duration_becomes_one(self):
        """Step with duration_hours=0 should become 1."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=0)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].steps[0].duration_hours == 1
        assert len(warnings) > 0  # Should have a warning about fixed duration

    def test_negative_duration_becomes_one(self):
        """Step with negative duration_hours should become 1."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=-5)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].steps[0].duration_hours == 1

    def test_valid_duration_preserved(self):
        """Step with valid positive duration_hours should be preserved."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=3)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].steps[0].duration_hours == 3

    def test_mixed_durations(self):
        """Job with mixed valid/invalid durations should normalize correctly."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[
                        Step(machine_id="M1", duration_hours=2),
                        Step(machine_id="M1", duration_hours=0),
                        Step(machine_id="M1", duration_hours=-1),
                        Step(machine_id="M1", duration_hours=5),
                    ],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].steps[0].duration_hours == 2
        assert result.jobs[0].steps[1].duration_hours == 1
        assert result.jobs[0].steps[2].duration_hours == 1
        assert result.jobs[0].steps[3].duration_hours == 5


class TestNormalizeFactoryDueTimeFix:
    """Tests for job due_time_hour normalization."""

    def test_negative_due_time_becomes_24(self):
        """Job with negative due_time_hour should become 24."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=-5,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].due_time_hour == 24

    def test_valid_due_time_preserved(self):
        """Job with valid due_time_hour should be preserved."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].due_time_hour == 10

    def test_zero_due_time_preserved(self):
        """Job with due_time_hour=0 should be preserved (valid edge case)."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=0,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert result.jobs[0].due_time_hour == 0


class TestNormalizeFactoryInvalidMachines:
    """Tests for invalid machine reference cleanup."""

    def test_step_with_invalid_machine_dropped(self):
        """Step referencing non-existent machine should be dropped."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[
                        Step(machine_id="M1", duration_hours=1),
                        Step(machine_id="M2", duration_hours=1),  # M2 doesn't exist
                        Step(machine_id="M1", duration_hours=1),
                    ],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 1
        assert len(result.jobs[0].steps) == 2
        assert all(s.machine_id == "M1" for s in result.jobs[0].steps)

    def test_all_steps_invalid_drops_job(self):
        """Job with all steps referencing invalid machines should be dropped."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[
                        Step(machine_id="M2", duration_hours=1),
                        Step(machine_id="M3", duration_hours=1),
                    ],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        # Job should be dropped, fallback to toy factory
        assert result == build_toy_factory()
        assert any("empty factory" in w.lower() for w in warnings)

    def test_multiple_jobs_one_invalid(self):
        """Multiple jobs where one becomes empty should drop only that job."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1"), Machine(id="M2", name="Machine 2")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=10,
                ),
                Job(
                    id="J2",
                    name="Job 2",
                    steps=[
                        Step(machine_id="M3", duration_hours=1),  # Invalid
                        Step(machine_id="M4", duration_hours=1),  # Invalid
                    ],
                    due_time_hour=12,
                ),
                Job(
                    id="J3",
                    name="Job 3",
                    steps=[Step(machine_id="M2", duration_hours=1)],
                    due_time_hour=14,
                ),
            ],
        )
        result, warnings = normalize_factory(factory)
        assert len(result.jobs) == 2
        job_ids = {j.id for j in result.jobs}
        assert job_ids == {"J1", "J3"}


class TestNormalizeFactoryFallback:
    """Tests for fallback to toy factory."""

    def test_empty_machines_falls_back(self):
        """Factory with no machines should fall back to toy factory."""
        factory = FactoryConfig(
            machines=[],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert result == build_toy_factory()

    def test_empty_jobs_falls_back(self):
        """Factory with no jobs should fall back to toy factory."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[],
        )
        result, warnings = normalize_factory(factory)
        assert result == build_toy_factory()

    def test_all_jobs_become_empty_falls_back(self):
        """Factory where all jobs become empty after cleanup should fall back."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M2", duration_hours=1)],
                    due_time_hour=10,
                ),
                Job(
                    id="J2",
                    name="Job 2",
                    steps=[Step(machine_id="M3", duration_hours=1)],
                    due_time_hour=12,
                ),
            ],
        )
        result, warnings = normalize_factory(factory)
        assert result == build_toy_factory()


class TestNormalizeFactoryImmutability:
    """Tests for immutability and non-mutation of input."""

    def test_input_not_mutated(self):
        """Input factory should not be mutated by normalization."""
        original = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=0)],
                    due_time_hour=-5,
                )
            ],
        )
        # Store original values
        original_duration = original.jobs[0].steps[0].duration_hours
        original_due_time = original.jobs[0].due_time_hour

        # Normalize
        result, warnings = normalize_factory(original)

        # Verify input was not mutated
        assert original.jobs[0].steps[0].duration_hours == original_duration
        assert original.jobs[0].due_time_hour == original_due_time
        # Verify result was modified
        assert result.jobs[0].steps[0].duration_hours == 1
        assert result.jobs[0].due_time_hour == 24

    def test_result_is_different_instance(self):
        """Result should be a new instance, not the same as input."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=1)],
                    due_time_hour=10,
                )
            ],
        )
        result, warnings = normalize_factory(factory)
        assert result is not factory


class TestNormalizeFactoryDeterminism:
    """Tests for deterministic behavior."""

    def test_normalization_is_deterministic(self):
        """Multiple calls should produce identical results."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1"), Machine(id="M2", name="Machine 2")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[
                        Step(machine_id="M1", duration_hours=0),
                        Step(machine_id="M3", duration_hours=1),  # Invalid
                        Step(machine_id="M2", duration_hours=-1),
                    ],
                    due_time_hour=-5,
                )
            ],
        )
        result1, warnings1 = normalize_factory(factory)
        result2, warnings2 = normalize_factory(factory)

        assert result1.machines == result2.machines
        assert len(result1.jobs) == len(result2.jobs)
        assert warnings1 == warnings2  # Warnings should be identical
        if result1.jobs:
            assert result1.jobs[0].steps == result2.jobs[0].steps
            assert result1.jobs[0].due_time_hour == result2.jobs[0].due_time_hour
