"""
Unit tests for fine extraction (PR2: Fine Extraction - steps & timings).

Tests the Raw* DTOs (RawStep, RawJob, RawFactoryConfig) and the
extract_steps() function with mocked LLM calls.

No real LLM calls are made; all network interaction is patched.
"""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from backend.onboarding import (
    RawStep,
    RawJob,
    RawFactoryConfig,
    CoarseMachine,
    CoarseJob,
    CoarseStructure,
    extract_steps,
)


class TestRawStepDTO:
    """Test RawStep DTO validation."""

    def test_create_raw_step_with_int_duration(self):
        """RawStep accepts integer duration."""
        step = RawStep(machine_id="M1", duration_hours=5)
        assert step.machine_id == "M1"
        assert step.duration_hours == 5

    def test_create_raw_step_with_float_duration(self):
        """RawStep accepts float duration."""
        step = RawStep(machine_id="M1", duration_hours=2.5)
        assert step.machine_id == "M1"
        assert step.duration_hours == 2.5

    def test_create_raw_step_with_zero_duration(self):
        """RawStep accepts zero duration (permissive; normalization later)."""
        step = RawStep(machine_id="M1", duration_hours=0)
        assert step.duration_hours == 0

    def test_create_raw_step_with_negative_duration(self):
        """RawStep accepts negative duration (permissive; normalization later)."""
        step = RawStep(machine_id="M1", duration_hours=-1)
        assert step.duration_hours == -1

    def test_raw_step_requires_machine_id(self):
        """RawStep requires machine_id field."""
        with pytest.raises(ValidationError):
            RawStep(duration_hours=5)

    def test_raw_step_requires_duration(self):
        """RawStep requires duration_hours field."""
        with pytest.raises(ValidationError):
            RawStep(machine_id="M1")


class TestRawJobDTO:
    """Test RawJob DTO validation."""

    def test_create_raw_job_with_steps(self):
        """RawJob accepts valid id, name, steps, and due_time_hour."""
        job = RawJob(
            id="J1",
            name="Assembly",
            steps=[RawStep(machine_id="M1", duration_hours=5)],
            due_time_hour=8,
        )
        assert job.id == "J1"
        assert job.name == "Assembly"
        assert len(job.steps) == 1
        assert job.due_time_hour == 8

    def test_raw_job_accepts_float_due_time(self):
        """RawJob accepts float due_time_hour (permissive)."""
        job = RawJob(
            id="J1",
            name="Job 1",
            steps=[],
            due_time_hour=8.5,
        )
        assert job.due_time_hour == 8.5

    def test_raw_job_accepts_none_due_time(self):
        """RawJob accepts None for due_time_hour."""
        job = RawJob(
            id="J1",
            name="Job 1",
            steps=[],
            due_time_hour=None,
        )
        assert job.due_time_hour is None

    def test_raw_job_accepts_empty_steps_list(self):
        """RawJob accepts empty steps list (permissive)."""
        job = RawJob(
            id="J1",
            name="Job 1",
            steps=[],
            due_time_hour=8,
        )
        assert len(job.steps) == 0

    def test_raw_job_accepts_multiple_steps(self):
        """RawJob accepts multiple steps."""
        job = RawJob(
            id="J1",
            name="Multi-step job",
            steps=[
                RawStep(machine_id="M1", duration_hours=2),
                RawStep(machine_id="M2", duration_hours=3.5),
                RawStep(machine_id="M1", duration_hours=1),
            ],
            due_time_hour=10,
        )
        assert len(job.steps) == 3
        assert job.steps[0].machine_id == "M1"
        assert job.steps[1].duration_hours == 3.5

    def test_raw_job_requires_id(self):
        """RawJob requires id field."""
        with pytest.raises(ValidationError):
            RawJob(
                name="Job 1",
                steps=[],
                due_time_hour=8,
            )

    def test_raw_job_requires_name(self):
        """RawJob requires name field."""
        with pytest.raises(ValidationError):
            RawJob(
                id="J1",
                steps=[],
                due_time_hour=8,
            )

    def test_raw_job_requires_steps(self):
        """RawJob requires steps field."""
        with pytest.raises(ValidationError):
            RawJob(
                id="J1",
                name="Job 1",
                due_time_hour=8,
            )


class TestRawFactoryConfigDTO:
    """Test RawFactoryConfig DTO."""

    def test_create_raw_factory_config_minimal(self):
        """RawFactoryConfig accepts machines and jobs lists."""
        config = RawFactoryConfig(machines=[], jobs=[])
        assert config.machines == []
        assert config.jobs == []

    def test_create_raw_factory_config_with_data(self):
        """RawFactoryConfig accepts populated lists."""
        config = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )
        assert len(config.machines) == 2
        assert len(config.jobs) == 1
        assert config.machines[0].id == "M1"
        assert config.jobs[0].id == "J1"

    def test_raw_factory_config_requires_machines(self):
        """RawFactoryConfig requires machines field."""
        with pytest.raises(ValidationError):
            RawFactoryConfig(jobs=[])

    def test_raw_factory_config_requires_jobs(self):
        """RawFactoryConfig requires jobs field."""
        with pytest.raises(ValidationError):
            RawFactoryConfig(machines=[])


class TestExtractSteps:
    """Test extract_steps() function with mocked LLM."""

    def test_extract_steps_happy_path(self):
        """extract_steps returns valid RawFactoryConfig from mocked LLM."""
        factory_text = "M1 assembly and M2 drill. J1 and J2 process through these machines."
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )

        expected_raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[
                        RawStep(machine_id="M1", duration_hours=2),
                        RawStep(machine_id="M2", duration_hours=3),
                    ],
                    due_time_hour=8,
                ),
                RawJob(
                    id="J2",
                    name="Job 2",
                    steps=[
                        RawStep(machine_id="M1", duration_hours=1.5),
                    ],
                    due_time_hour=6,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            result = extract_steps(factory_text, coarse)

            # Verify result matches expected
            assert result == expected_raw
            assert len(result.machines) == 2
            assert len(result.jobs) == 2
            assert result.jobs[0].id == "J1"
            assert len(result.jobs[0].steps) == 2

            # Verify call_llm_json was called exactly once
            assert mock_llm.call_count == 1

            # Verify it was called with the correct schema
            call_args = mock_llm.call_args
            assert call_args is not None
            prompt, schema = call_args[0]
            assert isinstance(prompt, str)
            assert schema == RawFactoryConfig

    def test_extract_steps_with_fractional_durations(self):
        """extract_steps preserves fractional durations from LLM output."""
        factory_text = "M1 runs for 2.5 hours. J1 needs 3.7 hours total."
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=2.5)],
                    due_time_hour=3.7,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw):
            result = extract_steps(factory_text, coarse)

            assert result.jobs[0].steps[0].duration_hours == 2.5
            assert result.jobs[0].due_time_hour == 3.7

    def test_extract_steps_with_none_due_time(self):
        """extract_steps handles None due_time_hour from LLM."""
        factory_text = "J1 has no specified due time."
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=None,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw):
            result = extract_steps(factory_text, coarse)

            assert result.jobs[0].due_time_hour is None

    def test_extract_steps_empty_coarse_structure(self):
        """extract_steps handles empty coarse structure."""
        factory_text = "Empty factory"
        coarse = CoarseStructure(machines=[], jobs=[])

        expected_raw = RawFactoryConfig(machines=[], jobs=[])

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw):
            result = extract_steps(factory_text, coarse)

            assert result.machines == []
            assert result.jobs == []

    def test_extract_steps_rejects_extra_machines(self):
        """extract_steps raises ValueError if LLM invents extra machine."""
        factory_text = "M1 and M2 and M3 exist."
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="M1"),
                CoarseMachine(id="M2", name="M2"),
            ],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        # LLM invents M3
        invalid_raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="M1"),
                CoarseMachine(id="M2", name="M2"),
                CoarseMachine(id="M3", name="M3"),  # Extra!
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            assert "machine id" in str(exc_info.value).lower()
            assert "extra" in str(exc_info.value).lower()

    def test_extract_steps_rejects_missing_machines(self):
        """extract_steps raises ValueError if LLM drops machine."""
        factory_text = "M1 and M2 exist."
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="M1"),
                CoarseMachine(id="M2", name="M2"),
            ],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        # LLM drops M2
        invalid_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            assert "machine id" in str(exc_info.value).lower()
            assert "missing" in str(exc_info.value).lower()

    def test_extract_steps_rejects_extra_jobs(self):
        """extract_steps raises ValueError if LLM invents extra job."""
        factory_text = "J1 and J2 and J3 exist."
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )

        # LLM invents J3
        invalid_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
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
                    steps=[RawStep(machine_id="M1", duration_hours=3)],
                    due_time_hour=6,
                ),
                RawJob(
                    id="J3",
                    name="Job 3",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=4,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            assert "job id" in str(exc_info.value).lower()
            assert "extra" in str(exc_info.value).lower()

    def test_extract_steps_rejects_missing_jobs(self):
        """extract_steps raises ValueError if LLM drops job."""
        factory_text = "J1 and J2 exist."
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )

        # LLM drops J2
        invalid_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            assert "job id" in str(exc_info.value).lower()
            assert "missing" in str(exc_info.value).lower()

    def test_extract_steps_propagates_llm_error(self):
        """extract_steps propagates LLM errors without wrapping."""
        factory_text = "Some text"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        with patch("backend.onboarding.call_llm_json", side_effect=RuntimeError("LLM failure")):
            with pytest.raises(RuntimeError, match="LLM failure"):
                extract_steps(factory_text, coarse)

    def test_extract_steps_propagates_validation_error(self):
        """extract_steps propagates validation errors from schema mismatch."""
        factory_text = "Some text"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        # Simulate LLM returning invalid schema (missing required fields)
        invalid_response = {"machines": [], "jobs": [{"id": "J1"}]}  # missing fields in job

        def side_effect(*args, **kwargs):
            # This simulates call_llm_json validating the response
            schema = args[1]
            return schema.model_validate(invalid_response)

        with patch("backend.onboarding.call_llm_json", side_effect=side_effect):
            with pytest.raises(ValidationError):
                extract_steps(factory_text, coarse)

    def test_extract_steps_prompt_contains_machine_ids(self):
        """extract_steps prompt includes all machine IDs."""
        factory_text = "Factory with M1, M2, M3"
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
                CoarseMachine(id="M3", name="Machine 3"),
            ],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
                CoarseMachine(id="M3", name="Machine 3"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            extract_steps(factory_text, coarse)

            # Verify prompt contains all machine IDs
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert "M1" in prompt
            assert "M2" in prompt
            assert "M3" in prompt

    def test_extract_steps_prompt_contains_job_ids(self):
        """extract_steps prompt includes all job IDs."""
        factory_text = "Factory with J1, J2, J3"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
                CoarseJob(id="J3", name="Job 3"),
            ],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
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
                    steps=[RawStep(machine_id="M1", duration_hours=3)],
                    due_time_hour=6,
                ),
                RawJob(
                    id="J3",
                    name="Job 3",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=4,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            extract_steps(factory_text, coarse)

            # Verify prompt contains all job IDs
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert "J1" in prompt
            assert "J2" in prompt
            assert "J3" in prompt

    def test_extract_steps_prompt_contains_factory_text(self):
        """extract_steps prompt includes factory_text."""
        factory_text = "Custom factory description with unique keywords XYZ123"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            extract_steps(factory_text, coarse)

            # Verify prompt includes the factory text
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert factory_text in prompt

    def test_extract_steps_prompt_contains_schema_marker(self):
        """extract_steps prompt includes OUTPUT SCHEMA marker."""
        factory_text = "Factory text"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            extract_steps(factory_text, coarse)

            # Verify prompt includes schema section
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert "SCHEMA" in prompt or "schema" in prompt

    def test_extract_steps_called_once(self):
        """extract_steps calls call_llm_json exactly once."""
        factory_text = "Factory text"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        expected_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw) as mock_llm:
            extract_steps(factory_text, coarse)

            assert mock_llm.call_count == 1

    def test_extract_steps_preserves_order(self):
        """extract_steps preserves machine and job order from coarse structure."""
        factory_text = "Factory with M3, M1, M2 and J2, J1, J3"
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M3", name="Machine 3"),
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
            ],
            jobs=[
                CoarseJob(id="J2", name="Job 2"),
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J3", name="Job 3"),
            ],
        )

        # Return same order as coarse
        expected_raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M3", name="Machine 3"),
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
            ],
            jobs=[
                RawJob(
                    id="J2",
                    name="Job 2",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=4,
                ),
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
                RawJob(
                    id="J3",
                    name="Job 3",
                    steps=[RawStep(machine_id="M3", duration_hours=1)],
                    due_time_hour=2,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_raw):
            result = extract_steps(factory_text, coarse)

            # Verify order is preserved
            assert result.machines[0].id == "M3"
            assert result.machines[1].id == "M1"
            assert result.machines[2].id == "M2"
            assert result.jobs[0].id == "J2"
            assert result.jobs[1].id == "J1"
            assert result.jobs[2].id == "J3"

    def test_extract_steps_rejects_renamed_machine(self):
        """extract_steps raises ValueError if machine ID changed."""
        factory_text = "M1 and M2"
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
            ],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        # M2 changed to M2_renamed (different ID)
        invalid_raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2_renamed", name="Machine 2"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            error_msg = str(exc_info.value).lower()
            assert "machine id" in error_msg

    def test_extract_steps_rejects_renamed_job(self):
        """extract_steps raises ValueError if job ID changed."""
        factory_text = "J1 and J2"
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )

        # J2 changed to J2_renamed (different ID)
        invalid_raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=5)],
                    due_time_hour=8,
                ),
                RawJob(
                    id="J2_renamed",
                    name="Job 2",
                    steps=[RawStep(machine_id="M1", duration_hours=3)],
                    due_time_hour=6,
                ),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=invalid_raw):
            with pytest.raises(ValueError) as exc_info:
                extract_steps(factory_text, coarse)

            error_msg = str(exc_info.value).lower()
            assert "job id" in error_msg
