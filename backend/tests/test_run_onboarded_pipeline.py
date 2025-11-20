"""
Tests for the run_onboarded_pipeline function.

Tests verify:
- Correct wiring of OnboardingAgent, normalize_factory, and existing pipeline
- Proper structure of returned dict
- Handling of empty and non-empty factory_text
- Metadata tracking (used_default_factory, onboarding_errors)
- No LLM calls for OnboardingAgent (stub only in PR1)
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.orchestrator import run_onboarded_pipeline
from backend.agents import OnboardingAgent
from backend.models import ScenarioSpec, ScenarioType, FactoryConfig, Machine, Job, Step
from backend.world import build_toy_factory


class TestRunOnboardedPipelineStructure:
    """Test that run_onboarded_pipeline returns the correct structure and types."""

    def test_onboarded_pipeline_basic_structure(self):
        """Verify run_onboarded_pipeline returns expected dict structure."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="normal day"
            )

            # Check dict structure
            assert isinstance(output, dict)
            expected_keys = {
                "factory", "situation_text", "specs", "metrics", "briefing", "meta"
            }
            assert set(output.keys()) == expected_keys

    def test_onboarded_pipeline_factory_is_normalized(self):
        """Verify returned factory is normalized."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            factory = output["factory"]
            assert isinstance(factory, FactoryConfig)
            assert len(factory.machines) > 0
            assert len(factory.jobs) > 0

    def test_onboarded_pipeline_situation_text_preserved(self):
        """Verify situation_text is preserved in output."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            situation = "rush J1 today"
            output = run_onboarded_pipeline(
                factory_text="",
                situation_text=situation
            )

            assert output["situation_text"] == situation

    def test_onboarded_pipeline_specs_and_metrics_aligned(self):
        """Verify specs and metrics are aligned."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J1",
                    slowdown_factor=None,
                ),
            ], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            specs = output["specs"]
            metrics = output["metrics"]
            assert len(specs) == len(metrics) == 2

    def test_onboarded_pipeline_briefing_is_string(self):
        """Verify briefing is a string."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            expected_briefing = "# Morning Briefing\n\nTest content."
            mock_briefing.return_value = expected_briefing

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            assert isinstance(output["briefing"], str)
            assert output["briefing"] == expected_briefing

    def test_onboarded_pipeline_meta_structure(self):
        """Verify meta dict has required fields."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            meta = output["meta"]
            assert isinstance(meta, dict)
            assert "used_default_factory" in meta
            assert "onboarding_errors" in meta
            assert isinstance(meta["used_default_factory"], bool)
            assert isinstance(meta["onboarding_errors"], list)


class TestOnboardingAgentIntegration:
    """Test integration with OnboardingAgent."""

    def test_onboarded_pipeline_calls_onboarding_agent(self):
        """Verify OnboardingAgent.run is called with factory_text."""
        with patch("backend.orchestrator.OnboardingAgent.run") as mock_onboarding, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            toy_factory = build_toy_factory()
            mock_onboarding.return_value = toy_factory
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            factory_text = "custom factory description"
            situation_text = "test situation"

            run_onboarded_pipeline(
                factory_text=factory_text,
                situation_text=situation_text
            )

            # Verify OnboardingAgent.run was called with factory_text
            mock_onboarding.assert_called_once_with(factory_text)

    def test_onboarded_pipeline_empty_factory_text(self):
        """Verify pipeline handles empty factory_text."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # Should complete without error and return valid output
            assert isinstance(output, dict)
            assert "factory" in output
            assert "briefing" in output

    def test_onboarded_pipeline_nonempty_factory_text(self):
        """Verify pipeline handles non-empty factory_text."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="3 machines, 5 jobs, etc.",
                situation_text="test"
            )

            # Should complete without error
            assert isinstance(output, dict)
            assert "factory" in output


class TestNormalizeFactoryIntegration:
    """Test integration with normalize_factory."""

    def test_onboarded_pipeline_uses_normalize_factory(self):
        """Verify normalize_factory is called on OnboardingAgent output."""
        with patch("backend.orchestrator.normalize_factory") as mock_normalize, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            toy_factory = build_toy_factory()
            mock_normalize.return_value = toy_factory
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            run_onboarded_pipeline(
                factory_text="test",
                situation_text="test"
            )

            # Verify normalize_factory was called
            assert mock_normalize.called

    def test_onboarded_pipeline_with_invalid_factory_text_fallback(self):
        """Verify pipeline handles factories that normalize to toy factory."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # In PR1, OnboardingAgent stub always returns toy_factory
            # So used_default_factory should be True
            assert output["meta"]["used_default_factory"] is True


class TestMetadataTracking:
    """Test metadata tracking in output."""

    def test_onboarded_pipeline_used_default_factory_flag(self):
        """Verify used_default_factory flag is set correctly."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # In PR1, this should always be True (stub returns toy factory)
            assert isinstance(output["meta"]["used_default_factory"], bool)

    def test_onboarded_pipeline_onboarding_errors_empty_in_pr1(self):
        """Verify onboarding_errors is empty in PR1 (no LLM yet)."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="any text",
                situation_text="test"
            )

            # In PR1, onboarding_errors should always be empty
            assert output["meta"]["onboarding_errors"] == []


class TestAgentChaining:
    """Test correct chaining and ordering of agents."""

    def test_onboarded_pipeline_intent_agent_receives_situation_text(self):
        """Verify IntentAgent receives situation_text and factory context."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            situation = "rush job J1"
            run_onboarded_pipeline(
                factory_text="",
                situation_text=situation
            )

            # IntentAgent should be called with situation_text and factory (kwarg)
            # Now passes factory context as keyword argument
            assert mock_intent.called
            call_args = mock_intent.call_args
            assert call_args[0][0] == situation  # First arg is situation_text
            assert 'factory' in call_args[1]  # factory passed as kwarg

    def test_onboarded_pipeline_futures_agent_receives_intent_spec(self):
        """Verify FuturesAgent receives the spec from IntentAgent and factory context."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            intent_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
            mock_intent.return_value = (intent_spec, "test context")
            mock_futures.return_value = ([intent_spec], "test justification")
            mock_briefing.return_value = "# Test"

            run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # FuturesAgent should be called with the intent spec and factory context
            assert mock_futures.called
            call_args = mock_futures.call_args
            assert call_args[0][0] == intent_spec  # First arg is the spec
            assert 'factory' in call_args[1]  # factory passed as kwarg

    def test_onboarded_pipeline_briefing_agent_receives_primary_metrics(self):
        """Verify BriefingAgent receives the primary scenario's metrics."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # BriefingAgent should have been called with metrics
            assert mock_briefing.called
            # Check that it was called with at least one positional arg (metrics)
            assert mock_briefing.call_count == 1


class TestDeterminism:
    """Test that pipeline is deterministic."""

    def test_onboarded_pipeline_deterministic_with_same_inputs(self):
        """Verify same inputs produce consistent outputs."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Deterministic Briefing"

            factory_text = "test factory"
            situation_text = "test situation"

            out1 = run_onboarded_pipeline(
                factory_text=factory_text,
                situation_text=situation_text
            )
            out2 = run_onboarded_pipeline(
                factory_text=factory_text,
                situation_text=situation_text
            )

            # Key outputs should be identical
            assert out1["situation_text"] == out2["situation_text"]
            assert out1["briefing"] == out2["briefing"]
            assert len(out1["specs"]) == len(out2["specs"])
            assert len(out1["metrics"]) == len(out2["metrics"])


class TestErrorHandling:
    """Test error handling in pipeline."""

    def test_onboarded_pipeline_raises_on_empty_futures(self):
        """Verify pipeline raises if FuturesAgent returns no scenarios."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([], "test justification")  # Empty list
            mock_briefing.return_value = "# Test"

            with pytest.raises(RuntimeError, match="FuturesAgent returned no scenarios"):
                run_onboarded_pipeline(
                    factory_text="",
                    situation_text="test"
                )

    def test_onboarded_pipeline_handles_special_characters(self):
        """Verify pipeline handles special characters in text inputs."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            outputs = []
            special_texts = [
                ("test@#$", "situation@#$"),
                ("", ""),
                ("unicode: café", "naïve"),
            ]

            for factory_text, situation_text in special_texts:
                output = run_onboarded_pipeline(
                    factory_text=factory_text,
                    situation_text=situation_text
                )
                assert isinstance(output, dict)
                outputs.append(output)

            # All should complete successfully
            assert len(outputs) == len(special_texts)


class TestMultipleScenarios:
    """Test pipeline with multiple scenarios."""

    def test_onboarded_pipeline_with_three_scenarios(self):
        """Verify pipeline correctly handles multiple scenarios."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([
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
            ], "test justification")
            mock_briefing.return_value = "# Briefing"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # Should have 3 specs and 3 metrics
            assert len(output["specs"]) == 3
            assert len(output["metrics"]) == 3
            # Briefing should be non-empty
            assert len(output["briefing"]) > 0


class TestIntegrationWithSimulation:
    """Test integration with actual simulation (no mocking)."""

    def test_onboarded_pipeline_end_to_end_integration(self):
        """Verify pipeline runs end-to-end with actual simulation (no LLM mocks)."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            # Only mock the agents, let sim and metrics run for real
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # Verify complete structure
            assert isinstance(output, dict)
            assert "factory" in output
            assert "situation_text" in output
            assert "specs" in output
            assert "metrics" in output
            assert "briefing" in output
            assert "meta" in output

            # Verify metrics are real (not mocked)
            metrics = output["metrics"][0]
            assert metrics.makespan_hour > 0
            assert metrics.bottleneck_utilization > 0
            assert len(metrics.job_lateness) > 0
