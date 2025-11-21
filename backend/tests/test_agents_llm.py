"""
Tests for LLM-backed agents with mocked call_llm_json.

These tests verify agent behavior when the LLM returns expected responses,
and also verify fallback behavior when the LLM fails.
All network calls are mocked; no real OpenAI API key is required.
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.models import ScenarioSpec, ScenarioType, ScenarioMetrics, FactoryConfig, Machine, Job, Step
from backend.agents import (
    IntentAgent,
    FuturesAgent,
    BriefingAgent,
    OnboardingAgent,
    FuturesResponse,
    BriefingResponse,
    normalize_scenario_spec,
)
from backend.world import build_toy_factory


class TestOnboardingAgentWithMockedLLM:
    """Test OnboardingAgent with mocked multi-stage pipeline (PR4).

    PR4 refactored OnboardingAgent to orchestrate multiple stages:
    - Stage 0: extract_explicit_ids (deterministic)
    - Stage 1: extract_coarse_structure (LLM)
    - Stage 2: extract_steps (LLM)
    - Stage 3: validate_and_normalize (deterministic)
    - Stage 4: assess_coverage (deterministic)

    These tests mock the helper functions, not call_llm_json directly.
    """

    @pytest.fixture
    def sample_factory_config(self):
        """Return a sample FactoryConfig for testing."""
        return FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
                Machine(id="M2", name="Drill"),
                Machine(id="M3", name="Pack"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Widget A",
                    steps=[
                        Step(machine_id="M1", duration_hours=1),
                        Step(machine_id="M2", duration_hours=3),
                        Step(machine_id="M3", duration_hours=1),
                    ],
                    due_time_hour=12,
                ),
                Job(
                    id="J2",
                    name="Gadget B",
                    steps=[
                        Step(machine_id="M1", duration_hours=1),
                        Step(machine_id="M2", duration_hours=2),
                        Step(machine_id="M3", duration_hours=1),
                    ],
                    due_time_hour=14,
                ),
            ],
        )

    def test_onboarding_agent_returns_factory_from_pipeline(self, sample_factory_config):
        """Test that OnboardingAgent orchestrates stages and returns valid FactoryConfig."""
        from backend.onboarding import (
            ExplicitIds, CoarseStructure, CoarseMachine, CoarseJob,
            RawFactoryConfig, RawJob, RawStep, CoverageReport,
        )

        # Setup mocks for all stages
        ids = ExplicitIds(machine_ids={"M1", "M2", "M3"}, job_ids={"J1", "J2"})
        coarse = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Assembly"), CoarseMachine(id="M2", name="Drill"), CoarseMachine(id="M3", name="Pack")],
            jobs=[CoarseJob(id="J1", name="Widget A"), CoarseJob(id="J2", name="Gadget B")],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Assembly"), CoarseMachine(id="M2", name="Drill"), CoarseMachine(id="M3", name="Pack")],
            jobs=[
                RawJob(id="J1", name="Widget A", steps=[RawStep(machine_id="M1", duration_hours=1), RawStep(machine_id="M2", duration_hours=3), RawStep(machine_id="M3", duration_hours=1)], due_time_hour=12),
                RawJob(id="J2", name="Gadget B", steps=[RawStep(machine_id="M1", duration_hours=1), RawStep(machine_id="M2", duration_hours=2), RawStep(machine_id="M3", duration_hours=1)], due_time_hour=14),
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

        with patch("backend.agents.extract_explicit_ids", return_value=ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=sample_factory_config), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            agent = OnboardingAgent()
            result = agent.run("Some factory description text")

            # Verify the result is the factory from the pipeline
            assert result == sample_factory_config
            assert len(result.machines) == 3
            assert len(result.jobs) == 2
            assert result.machines[0].id == "M1"
            assert result.jobs[0].id == "J1"

    def test_onboarding_agent_raises_on_llm_error(self):
        """Test that OnboardingAgent raises ExtractionError on LLM failure."""
        from backend.onboarding import ExtractionError

        with patch("backend.agents.extract_explicit_ids") as mock_stage0, \
             patch("backend.agents.extract_coarse_structure", side_effect=RuntimeError("API error")):

            mock_stage0.return_value = MagicMock(machine_ids={"M1"}, job_ids={"J1"})
            agent = OnboardingAgent()

            with pytest.raises(ExtractionError) as exc_info:
                agent.run("Some text")

            # Should wrap the error with LLM_FAILURE
            assert exc_info.value.code == "LLM_FAILURE"
            assert "API error" in exc_info.value.message

    def test_onboarding_agent_raises_on_validation_error(self):
        """Test that OnboardingAgent raises ExtractionError on validation error."""
        from backend.onboarding import ExtractionError

        with patch("backend.agents.extract_explicit_ids") as mock_stage0, \
             patch("backend.agents.extract_coarse_structure") as mock_stage1, \
             patch("backend.agents.extract_steps") as mock_stage2, \
             patch("backend.agents.validate_and_normalize", side_effect=ValueError("Invalid structure")):

            mock_stage0.return_value = MagicMock(machine_ids={"M1"}, job_ids={"J1"})
            mock_stage1.return_value = MagicMock(machines=[MagicMock(id="M1")], jobs=[MagicMock(id="J1")])
            mock_stage2.return_value = MagicMock(machines=[MagicMock(id="M1")], jobs=[MagicMock(id="J1", steps=[MagicMock(machine_id="M1", duration_hours=1)])])

            agent = OnboardingAgent()

            with pytest.raises(ExtractionError) as exc_info:
                agent.run("Some text")

            # Should wrap the error with NORMALIZATION_FAILED
            assert exc_info.value.code == "NORMALIZATION_FAILED"
            assert "Invalid structure" in exc_info.value.message

    def test_onboarding_agent_raises_on_coverage_mismatch(self):
        """Test that OnboardingAgent raises ExtractionError on coverage mismatch."""
        from backend.onboarding import ExtractionError, CoverageReport

        # Setup: M2 is detected but not in factory
        ids = MagicMock(machine_ids={"M1", "M2"}, job_ids={"J1"})
        coverage = CoverageReport(
            detected_machines={"M1", "M2"},
            detected_jobs={"J1"},
            parsed_machines={"M1"},
            parsed_jobs={"J1"},
            missing_machines={"M2"},
            missing_jobs=set(),
            machine_coverage=0.5,
            job_coverage=1.0,
        )
        factory = MagicMock(machines=[MagicMock(id="M1")], jobs=[MagicMock(id="J1")])

        with patch("backend.agents.extract_explicit_ids", return_value=ids), \
             patch("backend.agents.extract_coarse_structure") as mock_stage1, \
             patch("backend.agents.extract_steps") as mock_stage2, \
             patch("backend.agents.validate_and_normalize", return_value=factory), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            mock_stage1.return_value = MagicMock(machines=[MagicMock(id="M1")], jobs=[MagicMock(id="J1")])
            mock_stage2.return_value = MagicMock(machines=[MagicMock(id="M1")], jobs=[MagicMock(id="J1")])

            agent = OnboardingAgent()

            with pytest.raises(ExtractionError) as exc_info:
                agent.run("Some text with M1, M2")

            # Should raise COVERAGE_MISMATCH
            assert exc_info.value.code == "COVERAGE_MISMATCH"
            assert "M2" in exc_info.value.message

    def test_onboarding_agent_with_minimal_factory(self):
        """Test OnboardingAgent with a minimal factory (1 machine, 1 job)."""
        from backend.onboarding import (
            ExplicitIds, CoarseStructure, CoarseMachine, CoarseJob,
            RawFactoryConfig, RawJob, RawStep, CoverageReport,
        )

        minimal_factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine")],
            jobs=[
                Job(
                    id="J1",
                    name="Job",
                    steps=[Step(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                )
            ],
        )

        ids = ExplicitIds(machine_ids={"M1"}, job_ids={"J1"})
        coarse = CoarseStructure(machines=[CoarseMachine(id="M1", name="Machine")], jobs=[CoarseJob(id="J1", name="Job")])
        raw = RawFactoryConfig(machines=[CoarseMachine(id="M1", name="Machine")], jobs=[RawJob(id="J1", name="Job", steps=[RawStep(machine_id="M1", duration_hours=2)], due_time_hour=24)])
        coverage = CoverageReport(detected_machines={"M1"}, detected_jobs={"J1"}, parsed_machines={"M1"}, parsed_jobs={"J1"}, missing_machines=set(), missing_jobs=set(), machine_coverage=1.0, job_coverage=1.0)

        with patch("backend.agents.extract_explicit_ids", return_value=ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=minimal_factory), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            agent = OnboardingAgent()
            result = agent.run("minimal factory")

            assert len(result.machines) == 1
            assert len(result.jobs) == 1
            assert result.jobs[0].steps[0].duration_hours == 2

    def test_onboarding_agent_with_large_factory(self):
        """Test OnboardingAgent with a larger factory."""
        from backend.onboarding import (
            ExplicitIds, CoarseStructure, CoarseMachine, CoarseJob,
            RawFactoryConfig, RawJob, RawStep, CoverageReport,
        )

        large_factory = FactoryConfig(
            machines=[Machine(id=f"M{i}", name=f"Machine {i}") for i in range(1, 6)],
            jobs=[
                Job(
                    id=f"J{i}",
                    name=f"Job {i}",
                    steps=[Step(machine_id=f"M{(i % 5) + 1}", duration_hours=2 + j) for j in range(3)],
                    due_time_hour=12 + i,
                )
                for i in range(1, 8)
            ],
        )

        machine_ids = {f"M{i}" for i in range(1, 6)}
        job_ids = {f"J{i}" for i in range(1, 8)}
        ids = ExplicitIds(machine_ids=machine_ids, job_ids=job_ids)
        coarse = CoarseStructure(
            machines=[CoarseMachine(id=f"M{i}", name=f"Machine {i}") for i in range(1, 6)],
            jobs=[CoarseJob(id=f"J{i}", name=f"Job {i}") for i in range(1, 8)],
        )
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id=f"M{i}", name=f"Machine {i}") for i in range(1, 6)],
            jobs=[RawJob(id=f"J{i}", name=f"Job {i}", steps=[RawStep(machine_id=f"M{(i % 5) + 1}", duration_hours=2 + j) for j in range(3)], due_time_hour=12 + i) for i in range(1, 8)],
        )
        coverage = CoverageReport(detected_machines=machine_ids, detected_jobs=job_ids, parsed_machines=machine_ids, parsed_jobs=job_ids, missing_machines=set(), missing_jobs=set(), machine_coverage=1.0, job_coverage=1.0)

        with patch("backend.agents.extract_explicit_ids", return_value=ids), \
             patch("backend.agents.extract_coarse_structure", return_value=coarse), \
             patch("backend.agents.extract_steps", return_value=raw), \
             patch("backend.agents.validate_and_normalize", return_value=large_factory), \
             patch("backend.agents.assess_coverage", return_value=coverage):

            agent = OnboardingAgent()
            result = agent.run("large factory")

            assert len(result.machines) == 5
            assert len(result.jobs) == 7
            # Each job should have 3 steps
            for job in result.jobs:
                assert len(job.steps) == 3


class TestNormalizeScenarioSpec:
    """Test normalize_scenario_spec function."""

    def test_m2_slowdown_clears_rush_job_id(self):
        """Test that M2_SLOWDOWN with rush_job_id set gets rush_job_id cleared."""
        factory = build_toy_factory()

        # LLM incorrectly produced M2_SLOWDOWN with rush_job_id set
        # Use model_construct to bypass validation (simulating LLM returning invalid JSON)
        spec = ScenarioSpec.model_construct(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id="J1",  # This shouldn't be here
            slowdown_factor=2,
        )

        # Normalize should clear the rush_job_id
        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.M2_SLOWDOWN
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor == 2

    def test_rush_arrives_with_valid_job_id_unchanged(self):
        """Test that RUSH_ARRIVES with valid rush_job_id is unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J1",
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.RUSH_ARRIVES
        assert normalized.rush_job_id == "J1"
        assert normalized.slowdown_factor is None

    def test_rush_arrives_with_invalid_job_id_downgrades_to_baseline(self):
        """Test that RUSH_ARRIVES with invalid rush_job_id downgrades to BASELINE."""
        factory = build_toy_factory()

        # J99 doesn't exist in the factory
        spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J99",
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_rush_arrives_with_none_rush_job_id_downgrades_to_baseline(self):
        """Test that RUSH_ARRIVES with None rush_job_id downgrades to BASELINE."""
        factory = build_toy_factory()

        # Use model_construct to bypass validation (simulating invalid LLM JSON)
        spec = ScenarioSpec.model_construct(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id=None,
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_baseline_unchanged(self):
        """Test that BASELINE specs are unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.BASELINE,
            rush_job_id=None,
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_m2_slowdown_with_none_rush_job_id_unchanged(self):
        """Test that M2_SLOWDOWN with None rush_job_id is unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id=None,
            slowdown_factor=3,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.M2_SLOWDOWN
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor == 3


class TestIntentAgentWithMockedLLM:
    """Test IntentAgent with mocked call_llm_json."""

    def test_intent_agent_returns_rush_scenario(self):
        """Test that IntentAgent returns a RUSH_ARRIVES spec when mocked LLM does."""
        from backend.agents import IntentAgent as IA
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.RUSH_ARRIVES
        expected_response.rush_job_id = "J2"
        expected_response.slowdown_factor = None
        expected_response.constraint_summary = "Rush order for J2"

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = IntentAgent()
            spec, context = agent.run("we have a rush order for J2")

            assert spec.scenario_type == ScenarioType.RUSH_ARRIVES
            assert spec.rush_job_id == "J2"
            assert spec.slowdown_factor is None
            assert isinstance(context, str)

    def test_intent_agent_returns_m2_slowdown_scenario(self):
        """Test that IntentAgent returns M2_SLOWDOWN spec when mocked LLM does."""
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.M2_SLOWDOWN
        expected_response.rush_job_id = None
        expected_response.slowdown_factor = 3
        expected_response.constraint_summary = ""

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = IntentAgent()
            spec, context = agent.run("machine M2 is having issues")

            assert spec.scenario_type == ScenarioType.M2_SLOWDOWN
            assert spec.slowdown_factor == 3
            assert spec.rush_job_id is None
            assert isinstance(context, str)

    def test_intent_agent_returns_baseline_scenario(self):
        """Test that IntentAgent returns BASELINE spec when mocked LLM does."""
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.BASELINE
        expected_response.rush_job_id = None
        expected_response.slowdown_factor = None
        expected_response.constraint_summary = ""

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = IntentAgent()
            spec, context = agent.run("just a normal day")

            assert spec.scenario_type == ScenarioType.BASELINE
            assert spec.rush_job_id is None
            assert spec.slowdown_factor is None
            assert isinstance(context, str)

    def test_intent_agent_fallback_on_llm_failure(self):
        """Test that IntentAgent falls back to BASELINE when LLM call fails."""
        with patch("backend.agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = IntentAgent()
            spec, context = agent.run("some text")

            # Should fallback to BASELINE
            assert spec.scenario_type == ScenarioType.BASELINE
            assert spec.rush_job_id is None
            assert spec.slowdown_factor is None
            assert isinstance(context, str)

    def test_intent_agent_fallback_on_validation_error(self):
        """Test that IntentAgent falls back when LLM response validation fails."""
        # Raise a validation error during model_validate
        with patch("backend.agents.call_llm_json", side_effect=ValueError("Invalid scenario")):
            agent = IntentAgent()
            spec, context = agent.run("some text")

            # Should fallback to BASELINE
            assert spec.scenario_type == ScenarioType.BASELINE
            assert isinstance(context, str)

    def test_intent_agent_normalizes_m2_slowdown_with_rush_job_id(self):
        """Test that IntentAgent handles M2_SLOWDOWN with rush_job_id (normalization in internal helper)."""
        # Note: Due to Pydantic validation, an invalid spec that tries to have both
        # M2_SLOWDOWN + rush_job_id will fail LLM JSON parsing, causing fallback.
        # This is actually the correct behavior - it validates and falls back to BASELINE
        # since the constraint is impossible to satisfy
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.M2_SLOWDOWN
        expected_response.rush_job_id = "J1"  # Invalid with M2_SLOWDOWN
        expected_response.slowdown_factor = 2
        expected_response.constraint_summary = ""

        # This will cause the ScenarioSpec to fail validation, triggering fallback
        def mock_llm_json(prompt, schema):
            # Try to parse with the invalid data
            try:
                return schema(scenario_type=ScenarioType.M2_SLOWDOWN, rush_job_id="J1", slowdown_factor=2)
            except ValueError:
                # Pydantic will raise validation error, which gets caught and fallback occurs
                raise ValueError("Invalid scenario combination")

        with patch("backend.agents.call_llm_json", side_effect=mock_llm_json):
            agent = IntentAgent()
            spec, context = agent.run("M2 is slow and J1 needs rushing")

            # Should fallback to BASELINE due to validation error
            assert spec.scenario_type == ScenarioType.BASELINE
            assert isinstance(context, str)

    def test_intent_agent_normalizes_rush_with_invalid_job_id(self):
        """Test that IntentAgent normalizes RUSH_ARRIVES with invalid job ID to BASELINE."""
        # LLM returns RUSH_ARRIVES with non-existent job ID
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.RUSH_ARRIVES
        expected_response.rush_job_id = "J99"  # Invalid job ID
        expected_response.slowdown_factor = None
        expected_response.constraint_summary = ""

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = IntentAgent()
            spec, context = agent.run("rush order for J99")

            # Should downgrade to BASELINE
            assert spec.scenario_type == ScenarioType.BASELINE
            assert spec.rush_job_id is None
            assert spec.slowdown_factor is None
            assert isinstance(context, str)


class TestFuturesAgentWithMockedLLM:
    """Test FuturesAgent with mocked call_llm_json."""

    def test_futures_agent_returns_three_scenarios(self):
        """Test that FuturesAgent returns multiple scenarios from mocked LLM."""
        expected_response = MagicMock()
        expected_response.scenarios = [
            ScenarioSpec(scenario_type=ScenarioType.BASELINE),
            ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J1",
                slowdown_factor=None,
            ),
            ScenarioSpec(
                scenario_type=ScenarioType.M2_SLOWDOWN,
                rush_job_id=None,
                slowdown_factor=2,
            ),
        ]
        expected_response.justification = "Testing three scenarios"

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            specs, context = agent.run(base_spec)

            assert len(specs) == 3
            assert specs[0].scenario_type == ScenarioType.BASELINE
            assert specs[1].scenario_type == ScenarioType.RUSH_ARRIVES
            assert specs[1].rush_job_id == "J1"
            assert specs[2].scenario_type == ScenarioType.M2_SLOWDOWN
            assert specs[2].slowdown_factor == 2
            assert isinstance(context, str)

    def test_futures_agent_returns_single_scenario(self):
        """Test that FuturesAgent handles a single scenario response."""
        expected_response = MagicMock()
        expected_response.scenarios = [
            ScenarioSpec(scenario_type=ScenarioType.BASELINE),
        ]
        expected_response.justification = "Single scenario test"

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            specs, context = agent.run(base_spec)

            assert len(specs) == 1
            assert specs[0].scenario_type == ScenarioType.BASELINE
            assert isinstance(context, str)

    def test_futures_agent_truncates_to_three_scenarios(self):
        """Test that FuturesAgent truncates if LLM returns more than 3 scenarios."""
        # LLM tries to return 5 scenarios
        expected_response = MagicMock()
        expected_response.scenarios = [
            ScenarioSpec(scenario_type=ScenarioType.BASELINE),
            ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J1",
                slowdown_factor=None,
            ),
            ScenarioSpec(
                scenario_type=ScenarioType.M2_SLOWDOWN,
                rush_job_id=None,
                slowdown_factor=2,
            ),
            ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J2",
                slowdown_factor=None,
            ),
            ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J3",
                slowdown_factor=None,
            ),
        ]
        expected_response.justification = "Too many scenarios"

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            specs, context = agent.run(base_spec)

            # Should be truncated to first 3
            assert len(specs) == 3
            assert isinstance(context, str)

    def test_futures_agent_fallback_on_llm_failure(self):
        """Test that FuturesAgent falls back to [spec] when LLM fails."""
        base_spec = ScenarioSpec(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id=None,
            slowdown_factor=2,
        )

        with patch("backend.agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = FuturesAgent()
            specs, context = agent.run(base_spec)

            # Should fallback to [base_spec]
            assert len(specs) == 1
            assert specs[0] == base_spec
            assert isinstance(context, str)

    def test_futures_agent_fallback_on_empty_response(self):
        """Test that FuturesAgent falls back to [spec] when LLM returns empty list."""
        expected_response = MagicMock()
        expected_response.scenarios = []
        expected_response.justification = ""

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            specs, context = agent.run(base_spec)

            # Should fallback to [base_spec]
            assert len(specs) == 1
            assert specs[0] == base_spec
            assert isinstance(context, str)


class TestBriefingAgentWithMockedLLM:
    """Test BriefingAgent with mocked call_llm_json."""

    def test_briefing_agent_returns_markdown(self):
        """Test that BriefingAgent returns markdown from mocked LLM."""
        expected_markdown = """# Morning Briefing

## Today at a Glance
M2 is the bottleneck in all scenarios. Baseline is feasible.

## Key Risks
- M2 utilization is high at 85%.
- No jobs are late in baseline scenario.

## Recommended Actions
- Monitor M2 throughout the day.
- Be prepared to prioritize jobs if M2 has issues.

## Limitations of This Model
This is a single-day deterministic model with no real disruptions."""

        expected_response = BriefingResponse(markdown=expected_markdown)

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()
            result = agent.run(metrics)

            assert "Morning Briefing" in result
            assert "M2 is the bottleneck" in result
            assert result == expected_markdown

    def test_briefing_agent_with_context(self):
        """Test that BriefingAgent receives context parameter."""
        expected_markdown = "# Brief\n\nWith context about other scenarios."
        expected_response = BriefingResponse(markdown=expected_markdown)

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        context = "Other scenarios: Rush scenario has J1 late by 3h."

        with patch("backend.agents.call_llm_json", return_value=expected_response) as mock_llm:
            agent = BriefingAgent()
            result = agent.run(metrics, context=context)

            # Verify call_llm_json was called
            assert mock_llm.called
            # Verify context was included in the prompt
            call_args = mock_llm.call_args
            prompt = call_args[0][0]  # First positional argument is the prompt
            assert "Other scenarios" in prompt or "context" in prompt.lower()

    def test_briefing_agent_fallback_on_llm_failure(self):
        """Test that BriefingAgent falls back to deterministic template on LLM failure."""
        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("backend.agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = BriefingAgent()
            result = agent.run(metrics)

            # Should fallback to deterministic template
            assert "# Morning Briefing" in result
            assert "M2" in result
            assert "0.85" in result or "85%" in result
            assert isinstance(result, str)
            assert len(result) > 0

    def test_briefing_agent_fallback_on_validation_error(self):
        """Test that BriefingAgent falls back when response validation fails."""
        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("backend.agents.call_llm_json", side_effect=ValueError("Invalid response")):
            agent = BriefingAgent()
            result = agent.run(metrics)

            # Should fallback to deterministic template
            assert "# Morning Briefing" in result
            assert "M2" in result
            assert isinstance(result, str)

    def test_briefing_agent_without_context(self):
        """Test that BriefingAgent works without context parameter."""
        expected_response = BriefingResponse(markdown="# Briefing\n\nNo context.")

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()
            result = agent.run(metrics)  # No context parameter

            assert "Briefing" in result


class TestAgentDeterminism:
    """Test that agents produce deterministic outputs under mocked LLM."""

    def test_intent_agent_determinism(self):
        """Test that IntentAgent produces same output for same input with same mocked LLM."""
        expected_response = MagicMock()
        expected_response.scenario_type = ScenarioType.RUSH_ARRIVES
        expected_response.rush_job_id = "J2"
        expected_response.slowdown_factor = None
        expected_response.constraint_summary = ""

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = IntentAgent()

            spec1, ctx1 = agent.run("rush order for J2")
            spec2, ctx2 = agent.run("rush order for J2")

            assert spec1 == spec2
            assert ctx1 == ctx2

    def test_futures_agent_determinism(self):
        """Test that FuturesAgent produces same output for same input with same mocked LLM."""
        expected_response = MagicMock()
        expected_response.scenarios = [
            ScenarioSpec(scenario_type=ScenarioType.BASELINE),
            ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J1",
                slowdown_factor=None,
            ),
        ]
        expected_response.justification = "Test justification"

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()

            specs1, ctx1 = agent.run(base_spec)
            specs2, ctx2 = agent.run(base_spec)

            assert specs1 == specs2
            assert ctx1 == ctx2
            assert len(specs1) == len(specs2) == 2

    def test_briefing_agent_determinism(self):
        """Test that BriefingAgent produces same output for same metrics with same mocked LLM."""
        expected_response = BriefingResponse(markdown="# Test\n\nDeterministic output.")

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("backend.agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()

            result1 = agent.run(metrics)
            result2 = agent.run(metrics)

            assert result1 == result2
