"""
Tests for orchestrator.py - End-to-end pipeline verification.

Ensures:
- Pipeline runs end-to-end with multiple scenarios
- Correct types are returned
- Behavior is deterministic
- No randomness or nondeterminism
"""

import pytest
from unittest.mock import patch

from backend.orchestrator import run_pipeline
from backend.models import ScenarioSpec, ScenarioType, SimulationResult, ScenarioMetrics, FactoryConfig
from backend.agents import FuturesResponse, BriefingResponse


class TestRunPipelineStructure:
    """Test that run_pipeline returns the correct structure and types."""

    def test_run_pipeline_baseline_structure(self):
        """Verify pipeline returns expected dict structure with correct types."""
        # Mock LLM to return deterministic scenarios
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            # Return single BASELINE scenario
            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing\n\nTest output."

            output = run_pipeline("any free-text description")

            # Check dict structure
            assert isinstance(output, dict)
            assert set(output.keys()) == {
                "factory", "base_spec", "specs", "results", "metrics", "briefing"
            }

            # Extract and check types
            factory = output["factory"]
            base_spec = output["base_spec"]
            specs = output["specs"]
            results = output["results"]
            metrics_list = output["metrics"]
            briefing = output["briefing"]

            assert isinstance(factory, FactoryConfig)
            assert isinstance(base_spec, ScenarioSpec)
            assert isinstance(specs, list)
            assert len(specs) >= 1
            assert all(isinstance(s, ScenarioSpec) for s in specs)
            assert isinstance(results, list)
            assert len(results) == len(specs)
            assert all(isinstance(r, SimulationResult) for r in results)
            assert isinstance(metrics_list, list)
            assert len(metrics_list) == len(specs)
            assert all(isinstance(m, ScenarioMetrics) for m in metrics_list)
            assert isinstance(briefing, str)

    def test_run_pipeline_multiple_scenarios(self):
        """Verify pipeline handles multiple scenarios correctly."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            # Return 3 scenarios
            mock_futures.return_value = ([
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J2",
                    slowdown_factor=None,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.M2_SLOWDOWN,
                    rush_job_id=None,
                    slowdown_factor=2,
                ),
            ], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            output = run_pipeline("test with multiple scenarios")

            # Verify we got 3 scenarios
            assert len(output["specs"]) == 3
            assert len(output["results"]) == 3
            assert len(output["metrics"]) == 3

    def test_run_pipeline_results_and_metrics_aligned(self):
        """Verify that results and metrics are aligned with specs."""
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

            output = run_pipeline("test")

            # Verify alignment: results and metrics count should match specs
            assert len(output["specs"]) == len(output["results"])
            assert len(output["specs"]) == len(output["metrics"])

            # Verify each result corresponds to the spec
            for result, metrics in zip(output["results"], output["metrics"]):
                assert isinstance(result.makespan_hour, int)
                assert isinstance(metrics.makespan_hour, int)
                assert result.makespan_hour == metrics.makespan_hour

    def test_run_pipeline_briefing_contains_key_sections(self):
        """Verify briefing markdown contains expected sections."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Morning Briefing\n\n## Today at a Glance\nTest\n\n## Key Risks\n- Risk"

            output = run_pipeline("test input")

            briefing = output["briefing"]
            assert isinstance(briefing, str)
            assert len(briefing) > 0
            assert "Briefing" in briefing

    def test_run_pipeline_factory_has_expected_config(self):
        """Verify factory has machines and jobs from toy factory."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            output = run_pipeline("test")

            factory = output["factory"]
            assert len(factory.machines) == 3
            assert len(factory.jobs) == 3

            machine_ids = {m.id for m in factory.machines}
            assert machine_ids == {"M1", "M2", "M3"}

            job_ids = {j.id for j in factory.jobs}
            assert job_ids == {"J1", "J2", "J3"}


class TestDeterminism:
    """Test that pipeline is deterministic and produces same results for same inputs."""

    def test_run_pipeline_deterministic_basic(self):
        """Verify same input produces identical outputs with mocked agents."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            out1 = run_pipeline("rush this order please")
            out2 = run_pipeline("rush this order please")

            # Check that key outputs are identical
            assert out1["base_spec"] == out2["base_spec"]
            assert out1["metrics"] == out2["metrics"]
            assert out1["briefing"] == out2["briefing"]

            # Verify simulation results are identical
            assert out1["results"][0].makespan_hour == out2["results"][0].makespan_hour
            assert (out1["results"][0].job_completion_times ==
                    out2["results"][0].job_completion_times)

    def test_run_pipeline_deterministic_multiple_scenarios(self):
        """Verify determinism with multiple scenarios."""
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
            mock_briefing.return_value = "# Briefing"

            out1 = run_pipeline("test")
            out2 = run_pipeline("test")

            # Both should have same scenario structure
            assert len(out1["specs"]) == len(out2["specs"]) == 2
            assert len(out1["metrics"]) == len(out2["metrics"]) == 2

            # Metrics should be identical across runs
            for m1, m2 in zip(out1["metrics"], out2["metrics"]):
                assert m1 == m2

    def test_run_pipeline_deterministic_briefing(self):
        """Verify briefing is deterministic with mocked agents."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            expected_briefing = "# Deterministic Briefing\n\nSame output every time."

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = expected_briefing

            out1 = run_pipeline("test")
            out2 = run_pipeline("test")
            out3 = run_pipeline("test")

            # All should have identical briefing
            assert out1["briefing"] == out2["briefing"] == out3["briefing"]
            assert out1["briefing"] == expected_briefing


class TestPipelineIntegration:
    """Test end-to-end integration of all components."""

    def test_run_pipeline_end_to_end_with_mocked_agents(self):
        """Verify pipeline works end-to-end with mocked agents."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test Briefing"

            output = run_pipeline("")
            assert isinstance(output, dict)
            assert "briefing" in output
            assert len(output["briefing"]) > 0

    def test_run_pipeline_end_to_end_with_multiple_scenarios(self):
        """Verify pipeline works with multiple scenarios."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J2",
                    slowdown_factor=None,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.M2_SLOWDOWN,
                    rush_job_id=None,
                    slowdown_factor=3,
                ),
            ], "test justification")
            mock_briefing.return_value = "# Briefing with context"

            output = run_pipeline("test with multiple scenarios")

            # All arrays should be aligned
            assert len(output["specs"]) == 3
            assert len(output["results"]) == 3
            assert len(output["metrics"]) == 3
            assert isinstance(output["briefing"], str)

    def test_run_pipeline_metrics_match_results(self):
        """Verify metrics are computed correctly from each result."""
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

            output = run_pipeline("test")

            # For each result, metrics should match
            for result, metrics in zip(output["results"], output["metrics"]):
                assert metrics.makespan_hour == result.makespan_hour
                for job_id in result.job_completion_times:
                    assert job_id in metrics.job_lateness

            # Bottleneck machines should be real
            factory = output["factory"]
            machine_ids = {m.id for m in factory.machines}
            for metrics in output["metrics"]:
                assert metrics.bottleneck_machine_id in machine_ids

    def test_run_pipeline_factory_never_mutated(self):
        """Verify that run_pipeline doesn't mutate the toy factory definition."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            out1 = run_pipeline("first run")
            out2 = run_pipeline("second run")

            # Factories should be equal (both freshly built)
            factory1 = out1["factory"]
            factory2 = out2["factory"]

            # Same structure
            assert len(factory1.machines) == len(factory2.machines)
            assert len(factory1.jobs) == len(factory2.jobs)

            # Same machines
            machines1 = {m.id: m.name for m in factory1.machines}
            machines2 = {m.id: m.name for m in factory2.machines}
            assert machines1 == machines2

            # Same jobs and their properties
            jobs1 = {j.id: (j.name, j.due_time_hour) for j in factory1.jobs}
            jobs2 = {j.id: (j.name, j.due_time_hour) for j in factory2.jobs}
            assert jobs1 == jobs2


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_run_pipeline_with_special_characters(self):
        """Verify pipeline handles special characters in text."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Test"

            special_texts = [
                "test with @#$%^&*()",
                "unicode: café, naïve, 中文",
                "newlines\nin\ntext",
                "tabs\t\tin\t\ttext",
            ]
            for text in special_texts:
                output = run_pipeline(text)
                assert isinstance(output, dict)
                assert "briefing" in output

    def test_run_pipeline_output_immutability(self):
        """Verify output structure doesn't affect subsequent calls."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            mock_intent.return_value = (ScenarioSpec(scenario_type=ScenarioType.BASELINE), "test context")
            mock_futures.return_value = ([ScenarioSpec(scenario_type=ScenarioType.BASELINE)], "test justification")
            mock_briefing.return_value = "# Original Briefing"

            out1 = run_pipeline("test")
            briefing1_before = out1["briefing"]

            # Modify the output (should not affect next call)
            out1["briefing"] = "MODIFIED"

            out2 = run_pipeline("test")
            briefing2 = out2["briefing"]

            # Briefing should still be the original
            assert briefing2 == briefing1_before
            assert briefing2 != "MODIFIED"

    def test_run_pipeline_with_fallback_scenarios(self):
        """Verify pipeline handles fallback when FuturesAgent fails."""
        with patch("backend.orchestrator.IntentAgent.run") as mock_intent, \
             patch("backend.orchestrator.FuturesAgent.run") as mock_futures, \
             patch("backend.orchestrator.BriefingAgent.run") as mock_briefing:

            base_spec = ScenarioSpec(
                scenario_type=ScenarioType.RUSH_ARRIVES,
                rush_job_id="J1",
                slowdown_factor=None,
            )
            mock_intent.return_value = (base_spec, "test context")
            # Simulate FuturesAgent fallback: returns [base_spec] on error
            mock_futures.return_value = ([base_spec], "fallback justification")
            mock_briefing.return_value = "# Fallback Briefing"

            output = run_pipeline("test")

            # Should still have at least one scenario
            assert len(output["specs"]) >= 1
            assert len(output["results"]) >= 1
            assert len(output["metrics"]) >= 1
