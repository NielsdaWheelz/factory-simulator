"""
Tests for orchestrator.py - End-to-end pipeline verification.

Ensures:
- Pipeline runs end-to-end
- Correct types are returned
- Behavior is deterministic
- No randomness or nondeterminism
"""

import pytest
from orchestrator import run_pipeline
from models import ScenarioSpec, ScenarioType, SimulationResult, ScenarioMetrics, FactoryConfig


class TestRunPipelineStructure:
    """Test that run_pipeline returns the correct structure and types."""

    def test_run_pipeline_baseline_structure(self):
        """Verify pipeline returns expected dict structure with correct types."""
        output = run_pipeline("any free-text description")

        # Check dict structure
        assert isinstance(output, dict)
        assert set(output.keys()) == {"factory", "spec", "result", "metrics", "briefing"}

        # Extract and check types
        factory = output["factory"]
        spec = output["spec"]
        result = output["result"]
        metrics = output["metrics"]
        briefing = output["briefing"]

        assert isinstance(factory, FactoryConfig)
        assert isinstance(spec, ScenarioSpec)
        assert isinstance(result, SimulationResult)
        assert isinstance(metrics, ScenarioMetrics)
        assert isinstance(briefing, str)

    def test_run_pipeline_spec_is_baseline(self):
        """Verify that stub IntentAgent always produces BASELINE."""
        output = run_pipeline("any text at all")

        spec = output["spec"]
        assert spec.scenario_type == ScenarioType.BASELINE

    def test_run_pipeline_briefing_contains_key_sections(self):
        """Verify briefing markdown contains expected sections."""
        output = run_pipeline("test input")

        briefing = output["briefing"]
        assert isinstance(briefing, str)
        assert "Simulation Summary" in briefing
        assert "Makespan" in briefing
        assert "Bottleneck machine" in briefing
        assert "Bottleneck utilization" in briefing

    def test_run_pipeline_result_is_valid(self):
        """Verify SimulationResult is valid and contains expected data."""
        output = run_pipeline("test")

        result = output["result"]
        assert isinstance(result.scheduled_steps, list)
        assert len(result.scheduled_steps) > 0
        assert isinstance(result.job_completion_times, dict)
        assert isinstance(result.makespan_hour, int)
        assert result.makespan_hour > 0

    def test_run_pipeline_metrics_are_valid(self):
        """Verify ScenarioMetrics has valid values."""
        output = run_pipeline("test")

        metrics = output["metrics"]
        assert isinstance(metrics.makespan_hour, int)
        assert metrics.makespan_hour > 0
        assert isinstance(metrics.job_lateness, dict)
        assert isinstance(metrics.bottleneck_machine_id, str)
        assert isinstance(metrics.bottleneck_utilization, float)
        assert 0.0 <= metrics.bottleneck_utilization <= 1.0

    def test_run_pipeline_factory_has_expected_config(self):
        """Verify factory has machines and jobs from toy factory."""
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
        """Verify same input produces identical outputs across multiple runs."""
        out1 = run_pipeline("rush this order please")
        out2 = run_pipeline("rush this order please")

        # Check that key outputs are identical
        assert out1["spec"] == out2["spec"]
        assert out1["metrics"] == out2["metrics"]
        assert out1["briefing"] == out2["briefing"]

        # Verify simulation results are identical
        assert out1["result"].makespan_hour == out2["result"].makespan_hour
        assert out1["result"].job_completion_times == out2["result"].job_completion_times

    def test_run_pipeline_deterministic_multiple_calls(self):
        """Verify determinism over many consecutive calls."""
        text = "some random request"
        outputs = [run_pipeline(text) for _ in range(5)]

        # All outputs should have identical metrics
        first_metrics = outputs[0]["metrics"]
        for output in outputs[1:]:
            assert output["metrics"] == first_metrics

        # All outputs should have identical briefing
        first_briefing = outputs[0]["briefing"]
        for output in outputs[1:]:
            assert output["briefing"] == first_briefing

    def test_run_pipeline_ignores_text_in_stub(self):
        """Verify that stub IntentAgent ignores text content (always BASELINE)."""
        out1 = run_pipeline("make everything fast")
        out2 = run_pipeline("completely different text")
        out3 = run_pipeline("")
        out4 = run_pipeline("slow everything down")

        # All should produce BASELINE specs
        assert out1["spec"].scenario_type == ScenarioType.BASELINE
        assert out2["spec"].scenario_type == ScenarioType.BASELINE
        assert out3["spec"].scenario_type == ScenarioType.BASELINE
        assert out4["spec"].scenario_type == ScenarioType.BASELINE

        # All should have identical metrics
        assert out1["metrics"] == out2["metrics"]
        assert out2["metrics"] == out3["metrics"]
        assert out3["metrics"] == out4["metrics"]


class TestPipelineIntegration:
    """Test end-to-end integration of all components."""

    def test_run_pipeline_end_to_end_with_empty_text(self):
        """Verify pipeline works even with empty user text."""
        output = run_pipeline("")
        assert isinstance(output, dict)
        assert "briefing" in output
        assert len(output["briefing"]) > 0

    def test_run_pipeline_end_to_end_with_long_text(self):
        """Verify pipeline works with longer user input."""
        long_text = "This is a much longer piece of text that describes " \
                    "a complex scenario with many requirements and constraints. " \
                    "The factory should optimize for throughput while minimizing " \
                    "lateness and bottleneck utilization. All jobs should complete " \
                    "as quickly as possible without violating machine constraints."
        output = run_pipeline(long_text)
        assert isinstance(output, dict)
        assert output["spec"].scenario_type == ScenarioType.BASELINE
        assert isinstance(output["briefing"], str)

    def test_run_pipeline_metrics_match_result(self):
        """Verify metrics are computed correctly from the result."""
        output = run_pipeline("test")

        result = output["result"]
        metrics = output["metrics"]

        # Makespan should match result
        assert metrics.makespan_hour == result.makespan_hour

        # All jobs from result should have lateness entries
        for job_id in result.job_completion_times:
            assert job_id in metrics.job_lateness

        # Bottleneck machine should be real and in factory
        factory = output["factory"]
        machine_ids = {m.id for m in factory.machines}
        assert metrics.bottleneck_machine_id in machine_ids

    def test_run_pipeline_briefing_formatting(self):
        """Verify briefing is properly formatted markdown."""
        output = run_pipeline("test")

        briefing = output["briefing"]
        lines = briefing.split("\n")

        # Should have header line
        assert any("Simulation Summary" in line for line in lines)

        # Should have metrics lines
        assert any("Makespan" in line for line in lines)
        assert any("Bottleneck machine" in line for line in lines)
        assert any("Bottleneck utilization" in line for line in lines)

        # Should contain numeric values
        assert any(str(d) in briefing for d in range(10))  # At least one digit

    def test_run_pipeline_factory_never_mutated(self):
        """Verify that run_pipeline doesn't mutate the toy factory definition."""
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
        out1 = run_pipeline("test")
        briefing1_before = out1["briefing"]

        # Modify the output (should not affect next call)
        out1["briefing"] = "MODIFIED"

        out2 = run_pipeline("test")
        briefing2 = out2["briefing"]

        # Briefing should still be the original
        assert briefing2 == briefing1_before
        assert briefing2 != "MODIFIED"
