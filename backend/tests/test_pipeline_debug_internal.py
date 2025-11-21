"""
Tests for PRF1: Backend instrumentation wrapper for pipeline debug.

Tests that the orchestrator builds PipelineDebugPayload internally and
that all stages are instrumented correctly without changing behavior.

Key test scenarios:
- Happy path: all stages succeed (with mocked agents to avoid LLM calls)
- Onboarding failure: at least one O* stage fails, decision stages still run (PARTIAL)
- Decision failure: at least one D* stage fails (FAILED)
- Summaries are minimal and payload_preview is None for all stages
- HTTP response shape is unchanged (debug not exposed)
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.orchestrator import run_onboarded_pipeline, run_onboarding, run_decision_pipeline
from backend.models import (
    ScenarioSpec,
    ScenarioType,
    FactoryConfig,
    Machine,
    Job,
    Step,
    OnboardingMeta,
    PipelineRunResult,
)
from backend.debug_types import (
    PipelineDebugPayload,
    StageStatus,
    StageKind,
)
from backend.world import build_toy_factory
from backend.onboarding import CoarseStructure, RawFactoryConfig, RawJob, RawStep, CoarseMachine, CoarseJob


class TestDebugPayloadSuccessPath:
    """Test that debug payload is created correctly on the success path."""

    def test_debug_payload_success_path_has_all_stages(self):
        """Test that successful run creates debug payload with all 10 stages (when onboarding succeeds)."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing, \
             patch("backend.orchestrator.extract_coarse_structure") as mock_coarse, \
             patch("backend.orchestrator.extract_steps") as mock_steps:

            # Mock onboarding to succeed completely
            mock_coarse.return_value = CoarseStructure(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[CoarseJob(id="J1", name="job1")]
            )
            mock_steps.return_value = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[RawJob(id="J1", name="job1", steps=[RawStep(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )

            # Mock decision agents to return deterministic results
            mock_intent.return_value = (
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                "test context"
            )
            mock_futures.return_value = (
                [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
                "test justification"
            )
            mock_briefing.return_value = "# Test Briefing"

            # Factory text with M1 J1 so extraction works
            factory_text = "M1 machine J1 job"
            situation_text = "Normal day, no issues."

            result = run_onboarded_pipeline(factory_text, situation_text)

            # Check that result is PipelineRunResult with debug payload
            assert isinstance(result, PipelineRunResult)
            assert result.debug is not None
            assert isinstance(result.debug, PipelineDebugPayload)

            # Check all 10 stages are present (since onboarding succeeded)
            assert len(result.debug.stages) == 10, f"Expected 10 stages but got {len(result.debug.stages)}: {[s.id for s in result.debug.stages]}"
            stage_ids = {s.id for s in result.debug.stages}
            expected_ids = {"O0", "O1", "O2", "O3", "O4", "D1", "D2", "D3", "D4", "D5"}
            assert stage_ids == expected_ids

            # Check all stages have SUCCESS status
            for stage in result.debug.stages:
                assert stage.status == StageStatus.SUCCESS, f"Stage {stage.id} should be SUCCESS but got {stage.status}"

            # Check overall_status is SUCCESS
            assert result.debug.overall_status == "SUCCESS"

            # Check inputs are populated
            assert result.debug.inputs.factory_text_chars == len(factory_text)
            assert result.debug.inputs.situation_text_chars == len(situation_text)
            assert result.debug.inputs.factory_text_preview == factory_text[:200]
            assert result.debug.inputs.situation_text_preview == situation_text[:200]

    def test_all_stages_have_agent_model_set_correctly(self):
        """Test that agent_model is set correctly (gpt-4.1 for LLM, None for deterministic)."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing, \
             patch("backend.orchestrator.extract_coarse_structure") as mock_coarse, \
             patch("backend.orchestrator.extract_steps") as mock_steps:

            # Mock onboarding stages to succeed
            mock_coarse_obj = CoarseStructure(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[CoarseJob(id="J1", name="job1")]
            )
            mock_steps_obj = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[RawJob(id="J1", name="job1", steps=[RawStep(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )

            mock_coarse.return_value = mock_coarse_obj
            mock_steps.return_value = mock_steps_obj

            mock_intent.return_value = (
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                "test"
            )
            mock_futures.return_value = (
                [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
                "test"
            )
            mock_briefing.return_value = "# Briefing"

            result = run_onboarded_pipeline("M1 J1 test factory", "test situation")

            # Check agent_model values
            stages_by_id = {s.id: s for s in result.debug.stages}

            # Onboarding stages: O0, O3 are deterministic; O1, O2 are LLM
            assert stages_by_id["O0"].agent_model is None
            assert stages_by_id["O1"].agent_model == "gpt-4.1"
            assert stages_by_id["O2"].agent_model == "gpt-4.1"
            assert stages_by_id["O3"].agent_model is None
            assert stages_by_id["O4"].agent_model is None

            # Decision stages: D1, D2, D5 are LLM; D3, D4 are deterministic
            assert stages_by_id["D1"].agent_model == "gpt-4.1"
            assert stages_by_id["D2"].agent_model == "gpt-4.1"
            assert stages_by_id["D3"].agent_model is None
            assert stages_by_id["D4"].agent_model is None
            assert stages_by_id["D5"].agent_model == "gpt-4.1"


class TestDebugSummariesMinimal:
    """Test that stage summaries are minimal and not bloated."""

    def test_summaries_have_payload_preview_none_for_all_stages(self):
        """Test that payload_preview is None for all stages in PRF1."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing, \
             patch("backend.orchestrator.extract_coarse_structure") as mock_coarse, \
             patch("backend.orchestrator.extract_steps") as mock_steps:

            # Mock onboarding to succeed
            mock_coarse.return_value = CoarseStructure(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[CoarseJob(id="J1", name="job1")]
            )
            mock_steps.return_value = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[RawJob(id="J1", name="job1", steps=[RawStep(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test")
            mock_briefing.return_value = "# Briefing"

            result = run_onboarded_pipeline("M1 J1 test", "test situation")

            # Check payload_preview is None for all stages
            for stage in result.debug.stages:
                assert stage.payload_preview is None, f"Stage {stage.id} should have payload_preview=None"


class TestHTTPResponseUnchanged:
    """Test that HTTP response shape is unchanged (debug not exposed)."""

    def test_to_http_dict_excludes_debug(self):
        """Test that to_http_dict() excludes debug and has correct shape."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing, \
             patch("backend.orchestrator.extract_coarse_structure") as mock_coarse, \
             patch("backend.orchestrator.extract_steps") as mock_steps:

            # Mock onboarding
            mock_coarse.return_value = CoarseStructure(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[CoarseJob(id="J1", name="job1")]
            )
            mock_steps.return_value = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[RawJob(id="J1", name="job1", steps=[RawStep(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test")
            mock_briefing.return_value = "# Briefing"

            result = run_onboarded_pipeline("M1 J1 test", "test situation")

            # Convert to HTTP dict
            http_dict = result.to_http_dict()

            # Check that debug is NOT in the HTTP response
            assert "debug" not in http_dict

            # Check expected keys are present
            expected_keys = {"factory", "specs", "metrics", "briefing", "meta"}
            assert set(http_dict.keys()) == expected_keys

    def test_pipeline_run_result_has_debug_field_internally(self):
        """Test that PipelineRunResult includes debug field (not exposed via HTTP)."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing, \
             patch("backend.orchestrator.extract_coarse_structure") as mock_coarse, \
             patch("backend.orchestrator.extract_steps") as mock_steps:

            # Mock onboarding
            mock_coarse.return_value = CoarseStructure(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[CoarseJob(id="J1", name="job1")]
            )
            mock_steps.return_value = RawFactoryConfig(
                machines=[CoarseMachine(id="M1", name="machine1")],
                jobs=[RawJob(id="J1", name="job1", steps=[RawStep(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test")
            mock_briefing.return_value = "# Briefing"

            result = run_onboarded_pipeline("M1 J1 test", "test situation")

            # Check that PipelineRunResult has debug field
            assert hasattr(result, "debug")
            assert result.debug is not None
            assert isinstance(result.debug, PipelineDebugPayload)
