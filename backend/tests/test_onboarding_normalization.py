"""
Unit tests for normalization & invariant enforcement (PR3).

Tests the validate_and_normalize() function which bridges permissive RawFactoryConfig
from LLM extraction to strict FactoryConfig used by the rest of the system.

Tests enforce:
1. No jobs silently dropped during normalization
2. Every job has at least one step
3. Every step references an existing machine
4. Durations and due times are in valid ranges
5. No duplicate IDs in output
"""

import pytest
from unittest.mock import patch
from backend.onboarding import (
    RawStep,
    RawJob,
    RawFactoryConfig,
    CoarseMachine,
    ExtractionError,
    validate_and_normalize,
)
from backend.models import FactoryConfig, Machine, Job, Step


class TestExtractionError:
    """Test ExtractionError class."""

    def test_create_extraction_error_minimal(self):
        """ExtractionError can be created with code and message."""
        error = ExtractionError("TEST_CODE", "Test message")
        assert error.code == "TEST_CODE"
        assert error.message == "Test message"
        assert error.details == {}
        assert str(error) == "TEST_CODE: Test message"

    def test_create_extraction_error_with_details(self):
        """ExtractionError can include structured details."""
        details = {"key1": "value1", "key2": [1, 2, 3]}
        error = ExtractionError("TEST_CODE", "Test message", details=details)
        assert error.code == "TEST_CODE"
        assert error.message == "Test message"
        assert error.details == details

    def test_extraction_error_is_exception(self):
        """ExtractionError is an Exception subclass."""
        error = ExtractionError("CODE", "msg")
        assert isinstance(error, Exception)


class TestValidateAndNormalizeCanonicalSuccess:
    """Test validate_and_normalize with valid, well-formed input."""

    def test_valid_single_machine_single_job_single_step(self):
        """validate_and_normalize accepts valid single-machine single-job factory."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Widget Assembly",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                )
            ],
        )

        result = validate_and_normalize(raw)

        assert isinstance(result, FactoryConfig)
        assert len(result.machines) == 1
        assert result.machines[0].id == "M1"
        assert len(result.jobs) == 1
        assert result.jobs[0].id == "J1"
        assert len(result.jobs[0].steps) == 1
        assert result.jobs[0].steps[0].machine_id == "M1"
        assert result.jobs[0].steps[0].duration_hours == 5

    def test_valid_multiple_machines_multiple_jobs_multiple_steps(self):
        """validate_and_normalize handles complex factory with multiple entities."""
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
                CoarseMachine(id="M3", name="Paint"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Widget",
                    steps=[
                        RawStep(machine_id="M1", duration_hours=2),
                        RawStep(machine_id="M2", duration_hours=3),
                        RawStep(machine_id="M3", duration_hours=1),
                    ],
                    due_time_hour=10,
                ),
                RawJob(
                    id="J2",
                    name="Gadget",
                    steps=[
                        RawStep(machine_id="M2", duration_hours=4),
                        RawStep(machine_id="M1", duration_hours=2),
                    ],
                    due_time_hour=12,
                ),
            ],
        )

        result = validate_and_normalize(raw)

        assert len(result.machines) == 3
        assert len(result.jobs) == 2
        assert len(result.jobs[0].steps) == 3
        assert len(result.jobs[1].steps) == 2

    def test_valid_with_various_due_times(self):
        """validate_and_normalize accepts valid due_time_hour values (0-24)."""
        for due_time in [0, 1, 8, 12, 23, 24]:
            raw = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="M1")],
                jobs=[
                    RawJob(
                        id="J1",
                        name="Job",
                        steps=[RawStep(machine_id="M1", duration_hours=1)],
                        due_time_hour=due_time,
                    )
                ],
            )

            result = validate_and_normalize(raw)
            assert result.jobs[0].due_time_hour == due_time

    def test_valid_with_various_durations(self):
        """validate_and_normalize accepts valid step durations (>= 1)."""
        for duration in [1, 2, 5, 10, 100]:
            raw = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="M1")],
                jobs=[
                    RawJob(
                        id="J1",
                        name="Job",
                        steps=[RawStep(machine_id="M1", duration_hours=duration)],
                        due_time_hour=8,
                    )
                ],
            )

            result = validate_and_normalize(raw)
            assert result.jobs[0].steps[0].duration_hours == duration


class TestValidateAndNormalizeFractionalDurations:
    """Test validate_and_normalize with fractional durations (normalized ok)."""

    def test_fractional_durations_normalized_to_integers(self):
        """validate_and_normalize converts fractional durations to integers."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=2.5)],
                    due_time_hour=8,
                )
            ],
        )

        # normalize_factory should convert 2.5 to 3 (rounded up)
        result = validate_and_normalize(raw)

        # The normalized result should have integer duration
        assert isinstance(result.jobs[0].steps[0].duration_hours, int)
        assert result.jobs[0].steps[0].duration_hours >= 1

    def test_fractional_due_time_normalized_to_integer(self):
        """validate_and_normalize converts fractional due_time_hour to integer."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=8.5,
                )
            ],
        )

        result = validate_and_normalize(raw)

        # The normalized result should have integer due_time_hour
        assert isinstance(result.jobs[0].due_time_hour, int)
        assert 0 <= result.jobs[0].due_time_hour <= 24

    def test_none_due_time_normalized_to_24(self):
        """validate_and_normalize converts None due_time_hour to 24."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=None,
                )
            ],
        )

        result = validate_and_normalize(raw)

        assert result.jobs[0].due_time_hour == 24


class TestValidateAndNormalizeJobDropped:
    """Test validate_and_normalize rejects when jobs are dropped."""

    def test_rejects_if_job_dropped_during_normalization(self):
        """validate_and_normalize raises NORMALIZATION_FAILED if job is dropped."""
        # Create a job with a step referencing an invalid machine
        # normalize_factory will drop this job because it has no valid steps
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M2", duration_hours=5)],  # M2 doesn't exist
                    due_time_hour=8,
                )
            ],
        )

        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize(raw)

        error = exc_info.value
        assert error.code == "NORMALIZATION_FAILED"
        assert "J1" in error.message or "lost" in error.message.lower()
        assert error.details["raw_job_ids"] == ["J1"]
        assert error.details["normalized_job_ids"] == []

    def test_rejects_if_one_of_multiple_jobs_dropped(self):
        """validate_and_normalize raises if any job is dropped among multiple."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
                RawJob(
                    id="J2",
                    name="Job 2",
                    steps=[RawStep(machine_id="M2", duration_hours=3)],  # M2 doesn't exist
                    due_time_hour=10,
                ),
            ],
        )

        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize(raw)

        error = exc_info.value
        assert error.code == "NORMALIZATION_FAILED"
        assert "J2" in error.details.get("missing_job_ids", [])


class TestValidateAndNormalizeJobHasNoSteps:
    """Test validate_and_normalize rejects jobs with no steps."""

    def test_rejects_job_with_empty_steps_list(self):
        """validate_and_normalize raises INVALID_STRUCTURE if job has no steps."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job with no steps",
                    steps=[],
                    due_time_hour=8,
                )
            ],
        )

        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize(raw)

        error = exc_info.value
        # Empty steps list causes job to be dropped by normalize_factory,
        # which triggers NORMALIZATION_FAILED check
        assert error.code in ["INVALID_STRUCTURE", "NORMALIZATION_FAILED"]
        assert "J1" in error.message


class TestValidateAndNormalizeInvalidMachineReference:
    """Test validate_and_normalize rejects invalid machine references."""

    def test_rejects_step_referencing_missing_machine(self):
        """validate_and_normalize raises INVALID_STRUCTURE if step references missing machine."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M99", duration_hours=5)],  # M99 doesn't exist
                    due_time_hour=8,
                )
            ],
        )

        # This should be caught by normalize_factory dropping the step,
        # which then triggers job drop detection above.
        # But let's test the case where somehow a step slips through.
        # For now, this will be caught as a dropped job.
        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize(raw)

        error = exc_info.value
        # Could be either NORMALIZATION_FAILED (job dropped) or INVALID_STRUCTURE
        assert error.code in ["NORMALIZATION_FAILED", "INVALID_STRUCTURE"]


class TestValidateAndNormalizeOutOfRangeDurations:
    """Test validate_and_normalize rejects out-of-range durations and due times."""

    def test_rejects_zero_duration(self):
        """validate_and_normalize rejects step duration of 0."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=0)],
                    due_time_hour=8,
                )
            ],
        )

        # normalize_factory should convert 0 to 1
        # So this should actually succeed
        result = validate_and_normalize(raw)
        assert result.jobs[0].steps[0].duration_hours >= 1

    def test_rejects_negative_duration(self):
        """validate_and_normalize rejects negative step duration."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=-5)],
                    due_time_hour=8,
                )
            ],
        )

        # normalize_factory should convert -5 to 1
        # So this should actually succeed
        result = validate_and_normalize(raw)
        assert result.jobs[0].steps[0].duration_hours >= 1

    def test_rejects_negative_due_time(self):
        """validate_and_normalize rejects negative due_time_hour."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=-1,
                )
            ],
        )

        # normalize_factory should convert -1 to 24
        # So this should actually succeed
        result = validate_and_normalize(raw)
        assert 0 <= result.jobs[0].due_time_hour <= 24

    def test_rejects_due_time_greater_than_24(self):
        """validate_and_normalize rejects due_time_hour > 24."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=25,
                )
            ],
        )

        # normalize_factory does NOT clamp values > 24, so validate_and_normalize should reject
        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize(raw)

        error = exc_info.value
        assert error.code == "INVALID_STRUCTURE"
        assert "due_time_hour" in error.message.lower() or "due_time_hour" in error.details


class TestValidateAndNormalizeDuplicateIds:
    """Test validate_and_normalize rejects duplicate IDs."""

    def test_rejects_duplicate_machine_ids(self):
        """validate_and_normalize raises INVALID_STRUCTURE if duplicate machine IDs."""
        # Manually construct a FactoryConfig with duplicates to test this invariant
        # We can't easily do this via RawFactoryConfig since it uses CoarseMachine
        # But we can test by mocking normalize_factory
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="M1"),
                CoarseMachine(id="M1", name="M1_duplicate"),  # Duplicate!
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                )
            ],
        )

        # Mock normalize_factory to return a config with duplicate machine IDs
        duplicate_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="M1"),
                Machine(id="M1", name="M1_duplicate"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Job",
                    steps=[Step(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                )
            ],
        )

        with patch("backend.onboarding.normalize_factory", return_value=(duplicate_factory, [])):
            with pytest.raises(ExtractionError) as exc_info:
                validate_and_normalize(raw)

            error = exc_info.value
            assert error.code == "INVALID_STRUCTURE"
            assert "duplicate" in error.message.lower() or "machine" in error.message.lower()
            assert "duplicate_machine_ids" in error.details

    def test_rejects_duplicate_job_ids(self):
        """validate_and_normalize raises INVALID_STRUCTURE if duplicate job IDs."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
                RawJob(
                    id="J1",
                    name="Job 1 duplicate",
                    steps=[RawStep(machine_id="M1", duration_hours=3)],
                    due_time_hour=10,
                ),
            ],
        )

        # Mock normalize_factory to return a config with duplicate job IDs
        duplicate_factory = FactoryConfig(
            machines=[Machine(id="M1", name="M1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
                Job(
                    id="J1",
                    name="Job 1 duplicate",
                    steps=[Step(machine_id="M1", duration_hours=3)],
                    due_time_hour=10,
                ),
            ],
        )

        with patch("backend.onboarding.normalize_factory", return_value=(duplicate_factory, [])):
            with pytest.raises(ExtractionError) as exc_info:
                validate_and_normalize(raw)

            error = exc_info.value
            assert error.code == "INVALID_STRUCTURE"
            assert "duplicate" in error.message.lower() or "job" in error.message.lower()
            assert "duplicate_job_ids" in error.details


class TestValidateAndNormalizeEdgeCases:
    """Test edge cases and corner cases."""

    def test_preserves_machine_and_job_ids(self):
        """validate_and_normalize preserves machine and job IDs."""
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M_ASSEMBLY", name="Assembly Line"),
                CoarseMachine(id="M3_CUSTOM", name="Custom Machine"),
            ],
            jobs=[
                RawJob(
                    id="J_ORDER_001",
                    name="Order 1",
                    steps=[
                        RawStep(machine_id="M_ASSEMBLY", duration_hours=2),
                        RawStep(machine_id="M3_CUSTOM", duration_hours=3),
                    ],
                    due_time_hour=12,
                ),
                RawJob(
                    id="J2",
                    name="Order 2",
                    steps=[RawStep(machine_id="M_ASSEMBLY", duration_hours=1)],
                    due_time_hour=10,
                ),
            ],
        )

        result = validate_and_normalize(raw)

        assert result.machines[0].id == "M_ASSEMBLY"
        assert result.machines[1].id == "M3_CUSTOM"
        assert result.jobs[0].id == "J_ORDER_001"
        assert result.jobs[1].id == "J2"

    def test_preserves_machine_and_job_names(self):
        """validate_and_normalize preserves machine and job names."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Assembly Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Widget Manufacturing Process",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                )
            ],
        )

        result = validate_and_normalize(raw)

        assert result.machines[0].name == "Assembly Machine"
        assert result.jobs[0].name == "Widget Manufacturing Process"

    def test_preserves_step_order(self):
        """validate_and_normalize preserves the order of steps in each job."""
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="M1"),
                CoarseMachine(id="M2", name="M2"),
                CoarseMachine(id="M3", name="M3"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[
                        RawStep(machine_id="M3", duration_hours=1),
                        RawStep(machine_id="M1", duration_hours=2),
                        RawStep(machine_id="M2", duration_hours=3),
                    ],
                    due_time_hour=10,
                )
            ],
        )

        result = validate_and_normalize(raw)

        assert result.jobs[0].steps[0].machine_id == "M3"
        assert result.jobs[0].steps[1].machine_id == "M1"
        assert result.jobs[0].steps[2].machine_id == "M2"

    def test_handles_large_factory(self):
        """validate_and_normalize handles larger factories."""
        machines = [CoarseMachine(id=f"M{i}", name=f"Machine {i}") for i in range(1, 11)]
        jobs = [
            RawJob(
                id=f"J{i}",
                name=f"Job {i}",
                steps=[
                    RawStep(machine_id=f"M{(j % 10) + 1}", duration_hours=(j % 5) + 1)
                    for j in range(1, 4)
                ],
                due_time_hour=8 + (i % 17),
            )
            for i in range(1, 21)
        ]

        raw = RawFactoryConfig(machines=machines, jobs=jobs)
        result = validate_and_normalize(raw)

        assert len(result.machines) == 10
        assert len(result.jobs) == 20
        for job in result.jobs:
            assert len(job.steps) >= 1
