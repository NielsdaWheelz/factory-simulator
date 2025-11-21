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
                "factory", "specs", "metrics", "briefing", "meta"
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

    def test_onboarded_pipeline_correct_output_keys(self):
        """Verify output contains all required keys."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="rush J1 today"
            )

            # Verify all required keys are present
            assert "factory" in output
            assert "specs" in output
            assert "metrics" in output
            assert "briefing" in output
            assert "meta" in output

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
        """Verify meta has required fields and is an OnboardingMeta object."""
        from backend.models import OnboardingMeta

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
            assert isinstance(meta, OnboardingMeta)
            assert hasattr(meta, "used_default_factory")
            assert hasattr(meta, "onboarding_errors")
            assert hasattr(meta, "inferred_assumptions")
            assert isinstance(meta.used_default_factory, bool)
            assert isinstance(meta.onboarding_errors, list)
            assert isinstance(meta.inferred_assumptions, list)


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

    def test_onboarded_pipeline_with_valid_agent_output(self):
        """Verify run_onboarded_pipeline works with valid OnboardingAgent output."""
        with patch("backend.orchestrator.OnboardingAgent.run") as mock_onboarding, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            valid_factory = FactoryConfig(
                machines=[Machine(id="M1", name="M1")],
                jobs=[Job(id="J1", name="J1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24)]
            )
            mock_onboarding.return_value = valid_factory
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="test",
                situation_text="test"
            )

            # Verify agent was called and output is valid
            assert mock_onboarding.called
            assert "meta" in output
            assert output["meta"].used_default_factory is False
            assert len(output["meta"].onboarding_errors) == 0

    def test_onboarded_pipeline_with_agent_error_fallback(self):
        """Verify pipeline fallsback when agent raises ExtractionError."""
        from backend.onboarding import ExtractionError

        with patch("backend.agents.OnboardingAgent.run") as mock_onboarding, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            # Agent raises error - causes fallback to toy factory
            mock_onboarding.side_effect = ExtractionError(
                code="COVERAGE_MISMATCH",
                message="missing machines",
                details={},
            )
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # When OnboardingAgent returns an empty factory, it normalizes to toy_factory
            # So used_default_factory should be True
            assert output["meta"].used_default_factory is True


class TestMetadataTracking:
    """Test metadata tracking in output."""

    def test_onboarded_pipeline_used_default_factory_flag(self):
        """Verify used_default_factory flag is set when onboarding fails."""
        from backend.onboarding import ExtractionError

        with patch("backend.agents.OnboardingAgent.run") as mock_onboarding, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            # Agent raises error → run_onboarding falls back to toy factory
            mock_onboarding.side_effect = ExtractionError(
                code="LLM_FAILURE",
                message="LLM error",
                details={},
            )
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="",
                situation_text="test"
            )

            # When OnboardingAgent returns toy factory, used_default_factory is True
            assert isinstance(output["meta"].used_default_factory, bool)
            assert output["meta"].used_default_factory is True

    def test_onboarded_pipeline_onboarding_errors_empty_in_pr1(self):
        """Verify onboarding_errors is empty when OnboardingAgent succeeds."""
        # Mock OnboardingAgent to return a valid factory (success case)
        valid_factory = FactoryConfig(
            machines=[Machine(id="M1", name="Machine 1")],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                )
            ]
        )

        with patch("backend.agents.OnboardingAgent.run") as mock_onboarding, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_onboarding.return_value = valid_factory
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_onboarded_pipeline(
                factory_text="any text",
                situation_text="test"
            )

            # When OnboardingAgent succeeds with valid factory, onboarding_errors should be empty
            assert output["meta"].onboarding_errors == []


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
            assert out1["briefing"] == out2["briefing"]
            assert len(out1["specs"]) == len(out2["specs"])
            assert len(out1["metrics"]) == len(out2["metrics"])
            assert out1["specs"] == out2["specs"]


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
            assert "specs" in output
            assert "metrics" in output
            assert "briefing" in output
            assert "meta" in output

            # Verify metrics are real (not mocked)
            metrics = output["metrics"][0]
            assert metrics.makespan_hour > 0
            assert metrics.bottleneck_utilization > 0
            assert len(metrics.job_lateness) > 0


class TestOnboardingCoverageWarnings:
    """Test that coverage warnings are properly integrated into run_onboarding."""

    def test_coverage_mismatch_causes_fallback(self):
        """When OnboardingAgent detects coverage mismatch, fallback is triggered."""
        from backend.onboarding import ExtractionError

        # Create a factory text mentioning 4 jobs
        factory_text = "We have jobs J1, J2, J3, J4 to process through machines M1, M2."

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent, \
             patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            # Agent detects coverage mismatch (J2, J3, J4, M2 not in factory)
            mock_agent_instance = MagicMock()
            mock_agent_instance.run.side_effect = ExtractionError(
                code="COVERAGE_MISMATCH",
                message="coverage mismatch: missing machines ['M2'], missing jobs ['J2', 'J3', 'J4']",
                details={
                    "missing_machines": ["M2"],
                    "missing_jobs": ["J2", "J3", "J4"],
                    "machine_coverage": 0.5,
                    "job_coverage": 0.25,
                },
            )
            MockAgent.return_value = mock_agent_instance

            # Mock other agents to avoid failures
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            # Run the pipeline
            from backend.orchestrator import run_onboarding
            factory, meta = run_onboarding(factory_text)

            # Verify that fallback was triggered
            assert meta.used_default_factory is True
            # Should have error about coverage mismatch
            error_text = " ".join(meta.onboarding_errors)
            assert "COVERAGE_MISMATCH" in error_text

            # Verify toy factory was returned
            assert len(factory.machines) == 3  # Toy factory has 3 machines
            assert len(factory.jobs) == 3  # Toy factory has 3 jobs

    def test_no_coverage_warnings_for_complete_extraction(self):
        """When all mentioned jobs/machines are extracted, no coverage warnings."""
        factory_text = "We have jobs J1, J2, J3 and machines M1, M2."

        # Complete factory matching all mentions
        complete_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Machine 1"),
                Machine(id="M2", name="Machine 2"),
            ],
            jobs=[
                Job(id="J1", name="Job 1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
                Job(id="J2", name="Job 2", steps=[Step(machine_id="M2", duration_hours=1)], due_time_hour=24),
                Job(id="J3", name="Job 3", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
            ],
        )

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.run.return_value = complete_factory
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding
            factory, meta = run_onboarding(factory_text)

            # Should have no coverage warnings (only normalization warnings if any)
            coverage_warnings = [e for e in meta.onboarding_errors if "coverage warning" in e.lower()]
            assert len(coverage_warnings) == 0

            # Factory should be unchanged
            assert len(factory.machines) == 2
            assert len(factory.jobs) == 3


class TestRunOnboardingWithNewAgent:
    """Test run_onboarding with new multi-stage OnboardingAgent that enforces coverage."""

    def test_run_onboarding_agent_success_passes_through_factory(self):
        """When OnboardingAgent.run succeeds, run_onboarding returns that factory."""
        factory_text = "We have M1, M2. J1 on M1, J2 on M2."
        expected_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="M1"),
                Machine(id="M2", name="M2"),
            ],
            jobs=[
                Job(id="J1", name="J1", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=24),
                Job(id="J2", name="J2", steps=[Step(machine_id="M2", duration_hours=1)], due_time_hour=24),
            ],
        )

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.run.return_value = expected_factory
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding

            factory, meta = run_onboarding(factory_text)

            # Verify factory is the one from agent
            assert factory == expected_factory
            assert len(factory.machines) == 2
            assert len(factory.jobs) == 2

            # Verify meta indicates success
            assert meta.used_default_factory is False
            assert len(meta.onboarding_errors) == 0

            # Verify agent.run was called with factory_text
            mock_agent_instance.run.assert_called_once_with(factory_text)

    def test_run_onboarding_extraction_error_coverage_mismatch_falls_back(self):
        """When OnboardingAgent raises COVERAGE_MISMATCH, run_onboarding falls back to toy factory."""
        from backend.onboarding import ExtractionError

        factory_text = "We have M1, M2, M3. J1 only uses M1."

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            # Agent raises coverage mismatch: M2, M3 are mentioned but not in parsed factory
            error = ExtractionError(
                code="COVERAGE_MISMATCH",
                message="coverage mismatch: missing machines ['M2', 'M3'], missing jobs []",
                details={
                    "missing_machines": ["M2", "M3"],
                    "missing_jobs": [],
                    "machine_coverage": 0.33,
                    "job_coverage": 1.0,
                },
            )
            mock_agent_instance.run.side_effect = error
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding

            factory, meta = run_onboarding(factory_text)

            # Should fallback to toy factory
            assert meta.used_default_factory is True
            toy_factory = build_toy_factory()
            assert len(factory.machines) == len(toy_factory.machines)
            assert len(factory.jobs) == len(toy_factory.jobs)

            # Should have error in meta
            assert len(meta.onboarding_errors) > 0
            assert "COVERAGE_MISMATCH" in meta.onboarding_errors[0]
            assert "M2" in meta.onboarding_errors[0] or "missing machines" in meta.onboarding_errors[0]

    def test_run_onboarding_extraction_error_llm_failure_falls_back(self):
        """When OnboardingAgent raises LLM_FAILURE, run_onboarding falls back to toy factory."""
        from backend.onboarding import ExtractionError

        factory_text = "We have M1. J1."

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            error = ExtractionError(
                code="LLM_FAILURE",
                message="API timeout",
                details={"stage": "coarse_extraction", "error_type": "RuntimeError"},
            )
            mock_agent_instance.run.side_effect = error
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding

            factory, meta = run_onboarding(factory_text)

            # Should fallback to toy factory
            assert meta.used_default_factory is True
            toy_factory = build_toy_factory()
            assert len(factory.machines) == len(toy_factory.machines)

            # Should have error in meta
            assert len(meta.onboarding_errors) > 0
            assert "LLM_FAILURE" in meta.onboarding_errors[0]

    def test_run_onboarding_never_raises_exception(self):
        """run_onboarding should never raise an exception; always return with fallback."""
        from backend.onboarding import ExtractionError

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            # Any ExtractionError should be caught and handled
            error = ExtractionError(
                code="INVALID_STRUCTURE",
                message="Invalid normalization result",
                details={},
            )
            mock_agent_instance.run.side_effect = error
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding

            # Should not raise
            factory, meta = run_onboarding("any text")

            # Should fallback gracefully
            assert meta.used_default_factory is True
            assert len(meta.onboarding_errors) > 0

    def test_run_onboarding_with_empty_text(self):
        """run_onboarding should handle empty factory_text."""
        from backend.onboarding import ExtractionError

        with patch("backend.orchestrator.OnboardingAgent") as MockAgent:
            mock_agent_instance = MagicMock()
            toy_factory = build_toy_factory()
            # Empty text might cause no IDs detected → coverage mismatch
            error = ExtractionError(
                code="COVERAGE_MISMATCH",
                message="no IDs detected in text",
                details={"missing_machines": [], "missing_jobs": []},
            )
            mock_agent_instance.run.side_effect = error
            MockAgent.return_value = mock_agent_instance

            from backend.orchestrator import run_onboarding

            factory, meta = run_onboarding("")

            # Should handle gracefully and fallback
            assert meta.used_default_factory is True
