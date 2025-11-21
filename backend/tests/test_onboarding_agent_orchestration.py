"""
Tests for OnboardingAgent.run() orchestration with multi-stage pipeline and coverage enforcement.

Tests verify:
- Happy path: agent successfully orchestrates all stages and returns FactoryConfig
- Coverage mismatch: agent raises ExtractionError with code="COVERAGE_MISMATCH"
- LLM failures: agent wraps LLM errors into ExtractionError with code="LLM_FAILURE"
- Normalization failures: agent wraps normalization errors into ExtractionError
- All stages are called in order with expected arguments
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from backend.agents import OnboardingAgent
from backend.models import FactoryConfig, Machine, Job, Step
from backend.onboarding import (
    ExplicitIds,
    CoarseStructure,
    CoarseMachine,
    CoarseJob,
    RawFactoryConfig,
    RawJob,
    RawStep,
    CoverageReport,
    ExtractionError,
)


class TestOnboardingAgentOrchestration:
    """Test happy path and multi-stage orchestration."""

    def test_happy_path_all_stages_succeed_and_coverage_100(self):
        """When all stages succeed with 100% coverage, return FactoryConfig."""
        # Setup mocks
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                )
            ],
        )
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="assembly")],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=24)],
        )
        coverage = CoverageReport(
            detected_machines={"M1"},
            detected_jobs={"J1"},
            parsed_machines={"M1"},
            parsed_jobs={"J1"},
            missing_machines=set(),
            missing_jobs=set(),
            machine_coverage=1.0,
            job_coverage=1.0,
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids) as mock_stage0, \
             patch("backend.agents.extract_coarse_structure", return_value=coarse) as mock_stage1, \
             patch("backend.agents.extract_steps", return_value=raw) as mock_stage2, \
             patch("backend.agents.validate_and_normalize", return_value=factory) as mock_stage3, \
             patch("backend.agents.assess_coverage", return_value=coverage) as mock_stage4:

            agent = OnboardingAgent()
            result = agent.run("We have M1 assembly. J1 takes 2h on M1.")

            # Verify result
            assert result == factory
            assert len(result.machines) == 1
            assert len(result.jobs) == 1

            # Verify all stages called once
            mock_stage0.assert_called_once()
            mock_stage1.assert_called_once_with("We have M1 assembly. J1 takes 2h on M1.", explicit_ids)
            mock_stage2.assert_called_once_with("We have M1 assembly. J1 takes 2h on M1.", coarse)
            mock_stage3.assert_called_once_with(raw)
            mock_stage4.assert_called_once_with(explicit_ids, factory)

    def test_coverage_mismatch_raises_extraction_error(self):
        """When coverage < 100%, agent raises ExtractionError with code='COVERAGE_MISMATCH'."""
        explicit_ids = ExplicitIds(machine_ids={"M1", "M2"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                )
            ],
        )
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="assembly")],
            jobs=[Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=24)],
        )
        # Coverage mismatch: M2 detected but not in factory
        coverage = CoverageReport(
            detected_machines={"M1", "M2"},
            detected_jobs={"J1"},
            parsed_machines={"M1"},
            parsed_jobs={"J1"},
            missing_machines={"M2"},
            missing_jobs=set(),
            machine_coverage=0.5,  # Only 1 of 2 machines covered
            job_coverage=1.0,
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=factory), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1, M2. J1 uses only M1.")

            error = exc_info.value
            assert error.code == "COVERAGE_MISMATCH"
            assert "missing machines" in error.message
            assert "M2" in error.message
            assert error.details["missing_machines"] == ["M2"]
            assert error.details["machine_coverage"] == 0.5

    def test_llm_failure_in_coarse_extraction_wrapped_correctly(self):
        """When extract_coarse_structure raises non-ExtractionError, wrap it."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", side_effect=RuntimeError("LLM timeout")):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1. J1.")

            error = exc_info.value
            assert error.code == "LLM_FAILURE"
            assert "LLM timeout" in error.message
            assert error.details["stage"] == "coarse_extraction"
            assert error.details["error_type"] == "RuntimeError"

    def test_llm_failure_in_fine_extraction_wrapped_correctly(self):
        """When extract_steps raises non-ExtractionError, wrap it."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", side_effect=ValueError("Invalid step duration")):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1. J1.")

            error = exc_info.value
            assert error.code == "LLM_FAILURE"
            assert "Invalid step duration" in error.message
            assert error.details["stage"] == "fine_extraction"

    def test_normalization_failure_wrapped_correctly(self):
        """When validate_and_normalize raises non-ExtractionError, wrap it."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                )
            ],
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", side_effect=RuntimeError("Validation boom")):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1. J1.")

            error = exc_info.value
            assert error.code == "NORMALIZATION_FAILED"
            assert "Validation boom" in error.message
            assert error.details["stage"] == "normalization"

    def test_extraction_error_from_coarse_extraction_reraise_as_is(self):
        """When extract_coarse_structure raises ExtractionError, re-raise it as-is."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        original_error = ExtractionError(
            code="INVALID_STRUCTURE",
            message="Invalid coarse structure",
            details={"reason": "test"},
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", side_effect=original_error):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1.")

            error = exc_info.value
            assert error is original_error
            assert error.code == "INVALID_STRUCTURE"

    def test_extraction_error_from_validate_normalize_reraise_as_is(self):
        """When validate_and_normalize raises ExtractionError, re-raise it as-is."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[RawJob(id="J1", name="J1", steps=[RawStep(machine_id="M1", duration_hours=2)], due_time_hour=24)],
        )
        original_error = ExtractionError(
            code="JOBS_LOST",
            message="Jobs dropped during normalization",
            details={"lost_job_ids": ["J1"]},
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", side_effect=original_error):

            agent = OnboardingAgent()
            with pytest.raises(ExtractionError) as exc_info:
                agent.run("We have M1.")

            error = exc_info.value
            assert error is original_error
            assert error.code == "JOBS_LOST"

    def test_happy_path_with_multiple_machines_and_jobs(self):
        """Test successful orchestration with multiple machines and jobs."""
        explicit_ids = ExplicitIds(machine_ids={"M1", "M2", "M3"}, job_ids={"J1", "J2"})
        coarse = CoarseStructure(
            machines=[
                CoarseMachine(id="M1", name="assembly"),
                CoarseMachine(id="M2", name="drill"),
                CoarseMachine(id="M3", name="pack"),
            ],
            jobs=[CoarseJob(id="J1", name="Job 1"), CoarseJob(id="J2", name="Job 2")],
        )
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="assembly"),
                CoarseMachine(id="M2", name="drill"),
                CoarseMachine(id="M3", name="pack"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[
                        RawStep(machine_id="M1", duration_hours=2),
                        RawStep(machine_id="M2", duration_hours=3),
                    ],
                    due_time_hour=10,
                ),
                RawJob(
                    id="J2",
                    name="Job 2",
                    steps=[RawStep(machine_id="M3", duration_hours=4)],
                    due_time_hour=20,
                ),
            ],
        )
        factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="assembly"),
                Machine(id="M2", name="drill"),
                Machine(id="M3", name="pack"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=2), Step(machine_id="M2", duration_hours=3)],
                    due_time_hour=10,
                ),
                Job(id="J2", name="Job 2", steps=[Step(machine_id="M3", duration_hours=4)], due_time_hour=20),
            ],
        )
        coverage = CoverageReport(
            detected_machines={"M1", "M2", "M3"},
            detected_jobs={"J1", "J2"},
            parsed_machines={"M1", "M2", "M3"},
            parsed_jobs={"J1", "J2"},
            missing_machines=set(),
            missing_jobs=set(),
            machine_coverage=1.0,
            job_coverage=1.0,
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=factory), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            agent = OnboardingAgent()
            result = agent.run("Factory with 3 machines and 2 jobs...")

            assert len(result.machines) == 3
            assert len(result.jobs) == 2
            assert result.machines[0].id == "M1"
            assert result.jobs[0].id == "J1"


class TestOnboardingAgentLogging:
    """Test that logging is minimal and appropriate."""

    def test_logging_on_success(self, caplog):
        """Verify logging on successful run."""
        explicit_ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[RawJob(id="J1", name="J1", steps=[RawStep(machine_id="M1", duration_hours=2)], due_time_hour=24)],
        )
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="assembly")],
            jobs=[Job(id="J1", name="J1", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=24)],
        )
        coverage = CoverageReport(
            detected_machines={"M1"},
            detected_jobs={"J1"},
            parsed_machines={"M1"},
            parsed_jobs={"J1"},
            missing_machines=set(),
            missing_jobs=set(),
            machine_coverage=1.0,
            job_coverage=1.0,
        )

        with patch("backend.agents.extract_explicit_ids", return_value=explicit_ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=factory), \
             patch("backend.agents.assess_coverage", return_value=coverage), \
             patch("backend.agents.logger") as mock_logger:

            agent = OnboardingAgent()
            agent.run("test text")

            # Verify info log at start and end
            assert mock_logger.info.call_count >= 2
            # Verify no full text dump
            calls_str = str(mock_logger.info.call_args_list)
            assert "test text" not in calls_str  # Should not log full text
