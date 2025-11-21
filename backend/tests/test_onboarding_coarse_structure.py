"""
Unit tests for coarse structure extraction (PR1).

Tests the DTOs (CoarseMachine, CoarseJob, CoarseStructure) and the
extract_coarse_structure() function with mocked LLM calls.

No real LLM calls are made; all network interaction is patched.
"""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from backend.onboarding import (
    CoarseMachine,
    CoarseJob,
    CoarseStructure,
    extract_coarse_structure,
    ExplicitIds,
)


class TestCoarseMachineDDTO:
    """Test CoarseMachine DTO validation."""

    def test_create_valid_coarse_machine(self):
        """CoarseMachine accepts valid id and name."""
        machine = CoarseMachine(id="M1", name="Assembly")
        assert machine.id == "M1"
        assert machine.name == "Assembly"

    def test_coarse_machine_rejects_empty_id(self):
        """CoarseMachine rejects empty id."""
        with pytest.raises(ValidationError):
            CoarseMachine(id="", name="Assembly")

    def test_coarse_machine_rejects_whitespace_only_id(self):
        """CoarseMachine rejects whitespace-only id."""
        with pytest.raises(ValidationError):
            CoarseMachine(id="   ", name="Assembly")

    def test_coarse_machine_rejects_empty_name(self):
        """CoarseMachine rejects empty name."""
        with pytest.raises(ValidationError):
            CoarseMachine(id="M1", name="")

    def test_coarse_machine_rejects_whitespace_only_name(self):
        """CoarseMachine rejects whitespace-only name."""
        with pytest.raises(ValidationError):
            CoarseMachine(id="M1", name="   ")

    def test_coarse_machine_equality(self):
        """Two CoarseMachines with same id and name are equal."""
        m1 = CoarseMachine(id="M1", name="Assembly")
        m2 = CoarseMachine(id="M1", name="Assembly")
        assert m1 == m2


class TestCoarseJobDTO:
    """Test CoarseJob DTO validation."""

    def test_create_valid_coarse_job(self):
        """CoarseJob accepts valid id and name."""
        job = CoarseJob(id="J1", name="Job 1")
        assert job.id == "J1"
        assert job.name == "Job 1"

    def test_coarse_job_rejects_empty_id(self):
        """CoarseJob rejects empty id."""
        with pytest.raises(ValidationError):
            CoarseJob(id="", name="Job 1")

    def test_coarse_job_rejects_whitespace_only_id(self):
        """CoarseJob rejects whitespace-only id."""
        with pytest.raises(ValidationError):
            CoarseJob(id="   ", name="Job 1")

    def test_coarse_job_rejects_empty_name(self):
        """CoarseJob rejects empty name."""
        with pytest.raises(ValidationError):
            CoarseJob(id="J1", name="")

    def test_coarse_job_rejects_whitespace_only_name(self):
        """CoarseJob rejects whitespace-only name."""
        with pytest.raises(ValidationError):
            CoarseJob(id="J1", name="   ")

    def test_coarse_job_equality(self):
        """Two CoarseJobs with same id and name are equal."""
        j1 = CoarseJob(id="J1", name="Job 1")
        j2 = CoarseJob(id="J1", name="Job 1")
        assert j1 == j2


class TestCoarseStructureDTO:
    """Test CoarseStructure DTO."""

    def test_create_coarse_structure_with_machines_and_jobs(self):
        """CoarseStructure accepts machines and jobs lists."""
        structure = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )
        assert len(structure.machines) == 2
        assert len(structure.jobs) == 2
        assert structure.machines[0].id == "M1"
        assert structure.jobs[0].id == "J1"

    def test_coarse_structure_allows_empty_machines_list(self):
        """CoarseStructure allows empty machines list."""
        structure = CoarseStructure(machines=[], jobs=[])
        assert structure.machines == []
        assert structure.jobs == []

    def test_coarse_structure_allows_empty_jobs_list(self):
        """CoarseStructure allows empty jobs list."""
        structure = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[],
        )
        assert len(structure.machines) == 1
        assert len(structure.jobs) == 0


class TestExtractCoarseStructure:
    """Test extract_coarse_structure() function with mocked LLM."""

    def test_extract_coarse_structure_minimal_success(self):
        """extract_coarse_structure returns mocked CoarseStructure."""
        factory_text = "We run M1 assembly and M2 drill. Jobs J1 and J2 exist."
        ids = ExplicitIds(machine_ids={"M1", "M2"}, job_ids={"J1", "J2"})

        expected_structure = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure) as mock_llm:
            result = extract_coarse_structure(factory_text, ids)

            # Verify result matches expected
            assert result == expected_structure
            assert len(result.machines) == 2
            assert len(result.jobs) == 2
            assert result.machines[0].id == "M1"
            assert result.jobs[0].id == "J1"

            # Verify call_llm_json was called exactly once
            assert mock_llm.call_count == 1

            # Verify it was called with the correct arguments
            call_args = mock_llm.call_args
            assert call_args is not None
            prompt, schema = call_args[0]
            assert isinstance(prompt, str)
            assert schema == CoarseStructure

            # Verify prompt contains the required machine and job IDs
            assert "M1" in prompt
            assert "M2" in prompt
            assert "J1" in prompt
            assert "J2" in prompt

    def test_extract_coarse_structure_allows_empty_lists(self):
        """extract_coarse_structure allows empty machines/jobs lists."""
        factory_text = "Empty factory"
        ids = ExplicitIds(machine_ids=set(), job_ids=set())

        expected_structure = CoarseStructure(machines=[], jobs=[])

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure):
            result = extract_coarse_structure(factory_text, ids)

            assert result.machines == []
            assert result.jobs == []

    def test_extract_coarse_structure_propagates_llm_error(self):
        """extract_coarse_structure propagates LLM errors without wrapping."""
        factory_text = "Some text"
        ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})

        with patch("backend.onboarding.call_llm_json", side_effect=RuntimeError("LLM failure")):
            with pytest.raises(RuntimeError, match="LLM failure"):
                extract_coarse_structure(factory_text, ids)

    def test_extract_coarse_structure_propagates_validation_error(self):
        """extract_coarse_structure propagates validation errors from schema mismatch."""
        factory_text = "Some text"
        ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})

        # Simulate LLM returning invalid schema (missing required fields)
        invalid_response = {"machines": [{"id": "M1"}]}  # missing 'name' field

        def side_effect(*args, **kwargs):
            # This simulates call_llm_json validating the response
            schema = args[1]
            return schema.model_validate(invalid_response)

        with patch("backend.onboarding.call_llm_json", side_effect=side_effect):
            with pytest.raises(ValidationError):
                extract_coarse_structure(factory_text, ids)

    def test_extract_coarse_structure_prompt_contains_factory_text(self):
        """extract_coarse_structure passes the factory_text in the prompt."""
        factory_text = "Custom factory description here"
        ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})

        expected_structure = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="M1")],
            jobs=[CoarseJob(id="J1", name="J1")],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure) as mock_llm:
            extract_coarse_structure(factory_text, ids)

            # Verify the prompt contains the factory text
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert factory_text in prompt

    def test_extract_coarse_structure_prompt_handles_empty_ids(self):
        """extract_coarse_structure builds prompt with empty ID lists."""
        factory_text = "Factory with no detected IDs"
        ids = ExplicitIds(machine_ids=set(), job_ids=set())

        expected_structure = CoarseStructure(machines=[], jobs=[])

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure) as mock_llm:
            extract_coarse_structure(factory_text, ids)

            # Verify the prompt was built (no crash on empty sets)
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert isinstance(prompt, str)
            assert len(prompt) > 0

    def test_extract_coarse_structure_single_machine_multiple_jobs(self):
        """extract_coarse_structure handles single machine with multiple jobs."""
        factory_text = "M1 runs J1, J2, J3"
        ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1", "J2", "J3"})

        expected_structure = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Workstation")],
            jobs=[
                CoarseJob(id="J1", name="Job 1"),
                CoarseJob(id="J2", name="Job 2"),
                CoarseJob(id="J3", name="Job 3"),
            ],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure):
            result = extract_coarse_structure(factory_text, ids)

            assert len(result.machines) == 1
            assert len(result.jobs) == 3
            assert result.machines[0].id == "M1"

    def test_extract_coarse_structure_multiple_machines_single_job(self):
        """extract_coarse_structure handles multiple machines with single job."""
        factory_text = "M1, M2, M3 process J1"
        ids = ExplicitIds(machine_ids={"M1", "M2", "M3"}, job_ids={"J1"})

        expected_structure = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="Machine 1"),
                CoarseMachine(id="M2", name="Machine 2"),
                CoarseMachine(id="M3", name="Machine 3"),
            ],
            jobs=[CoarseJob(id="J1", name="Assembly")],
        )

        with patch("backend.onboarding.call_llm_json", return_value=expected_structure):
            result = extract_coarse_structure(factory_text, ids)

            assert len(result.machines) == 3
            assert len(result.jobs) == 1
            assert result.jobs[0].id == "J1"
