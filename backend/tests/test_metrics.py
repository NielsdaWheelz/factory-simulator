"""
Tests for metrics computation.

Tests verify:
- Makespan passes through from result to metrics
- Job lateness is computed correctly (never negative)
- Bottleneck machine is identified correctly (M2 in toy factory)
- Bottleneck utilization is in valid range (0.0, 1.0]
- Metrics are consistent across different simulation entrypoints
- Type sanity (correct types for all metric fields)
"""

import pytest
from copy import deepcopy

from backend.world import build_toy_factory
from backend.sim import simulate_baseline, simulate
from backend.models import ScenarioSpec, ScenarioType, ScenarioMetrics
from backend.metrics import compute_metrics


class TestMakespanPassthrough:
    """Test that makespan passes through correctly."""

    def test_makespan_matches_result(self):
        """Verify metrics.makespan_hour == result.makespan_hour."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert metrics.makespan_hour == result.makespan_hour
        assert isinstance(metrics.makespan_hour, int)

    def test_makespan_is_non_negative(self):
        """Verify makespan is non-negative integer."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert metrics.makespan_hour >= 0
        assert isinstance(metrics.makespan_hour, int)


class TestLatenessSemantics:
    """Test that job lateness is computed correctly."""

    def test_lateness_never_negative(self):
        """Verify lateness is always >= 0, even for early jobs."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        for job_id, lateness in metrics.job_lateness.items():
            assert lateness >= 0, f"Job {job_id} has negative lateness: {lateness}"

    def test_lateness_is_int(self):
        """Verify all lateness values are integers."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        for job_id, lateness in metrics.job_lateness.items():
            assert isinstance(lateness, int), f"Job {job_id} lateness is not int: {type(lateness)}"

    def test_lateness_on_time_job(self):
        """Verify job with due_time >= completion_time has lateness 0."""
        factory = build_toy_factory()
        # In baseline, all jobs complete well before due times
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        # Check that on-time jobs have lateness 0
        for job in factory.jobs:
            completion_time = result.job_completion_times[job.id]
            if completion_time <= job.due_time_hour:
                assert metrics.job_lateness[job.id] == 0, \
                    f"Job {job.id} is on-time but has non-zero lateness"

    def test_lateness_with_tight_due_time(self):
        """Verify lateness is computed correctly with tight due time."""
        factory = build_toy_factory()
        factory_tight = deepcopy(factory)

        # Make J1's due time very tight
        job_j1 = next(j for j in factory_tight.jobs if j.id == "J1")
        job_j1.due_time_hour = 0

        result = simulate_baseline(factory_tight)
        metrics = compute_metrics(factory_tight, result)

        # J1 completion time is its lateness since due_time = 0
        j1_lateness = metrics.job_lateness["J1"]
        j1_completion = result.job_completion_times["J1"]
        assert j1_lateness == j1_completion, \
            f"J1 lateness {j1_lateness} should equal completion time {j1_completion} when due_time=0"

    def test_lateness_with_generous_due_time(self):
        """Verify lateness is 0 when due_time >> completion_time."""
        factory = build_toy_factory()
        factory_generous = deepcopy(factory)

        # Give all jobs very generous due times
        for job in factory_generous.jobs:
            job.due_time_hour = 100

        result = simulate_baseline(factory_generous)
        metrics = compute_metrics(factory_generous, result)

        # All jobs should have 0 lateness
        for job_id, lateness in metrics.job_lateness.items():
            assert lateness == 0, f"Job {job_id} should have 0 lateness with generous due time"


class TestBottleneckIdentification:
    """Test that bottleneck machine is identified correctly."""

    def test_baseline_bottleneck_is_m2(self):
        """Verify bottleneck for baseline is M2 (known from design)."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert metrics.bottleneck_machine_id == "M2", \
            f"Expected M2 as bottleneck, got {metrics.bottleneck_machine_id}"

    def test_bottleneck_is_valid_machine_id(self):
        """Verify bottleneck machine ID is a real machine in factory."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        machine_ids = {m.id for m in factory.machines}
        assert metrics.bottleneck_machine_id in machine_ids, \
            f"Bottleneck {metrics.bottleneck_machine_id} not in factory machines"

    def test_bottleneck_utilization_in_valid_range(self):
        """Verify bottleneck utilization is between 0.0 and 1.0."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert 0.0 < metrics.bottleneck_utilization <= 1.0, \
            f"Bottleneck utilization {metrics.bottleneck_utilization} not in (0.0, 1.0]"

    def test_bottleneck_utilization_is_float(self):
        """Verify bottleneck utilization is a float."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert isinstance(metrics.bottleneck_utilization, float), \
            f"Bottleneck utilization is not float: {type(metrics.bottleneck_utilization)}"

    def test_bottleneck_utilization_matches_calculation(self):
        """Verify bottleneck utilization = bottleneck_busy_hours / makespan."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        # Recompute utilization manually
        machine_busy = {}
        for step in result.scheduled_steps:
            machine_id = step.machine_id
            duration = step.end_hour - step.start_hour
            machine_busy[machine_id] = machine_busy.get(machine_id, 0) + duration

        expected_utilization = machine_busy[metrics.bottleneck_machine_id] / metrics.makespan_hour

        # Allow for floating point rounding
        assert abs(metrics.bottleneck_utilization - expected_utilization) < 1e-9, \
            f"Utilization mismatch: {metrics.bottleneck_utilization} vs {expected_utilization}"


class TestConsistencyAcrossEntrypoints:
    """Test that metrics are consistent across different simulation entrypoints."""

    def test_metrics_same_for_baseline_and_simulate(self):
        """Verify metrics are identical for simulate_baseline vs simulate(BASELINE)."""
        factory = build_toy_factory()

        # Via simulate_baseline
        result1 = simulate_baseline(factory)
        metrics1 = compute_metrics(factory, result1)

        # Via simulate with BASELINE spec
        baseline_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        result2 = simulate(factory, baseline_spec)
        metrics2 = compute_metrics(factory, result2)

        # Both should produce identical metrics
        assert metrics1 == metrics2, \
            f"Metrics differ between entrypoints:\n{metrics1}\nvs\n{metrics2}"

    def test_metrics_differ_across_scenarios(self):
        """Verify metrics differ between BASELINE and other scenarios."""
        factory = build_toy_factory()

        baseline_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        slowdown_spec = ScenarioSpec(scenario_type=ScenarioType.M2_SLOWDOWN, slowdown_factor=2)

        result_baseline = simulate(factory, baseline_spec)
        result_slowdown = simulate(factory, slowdown_spec)

        metrics_baseline = compute_metrics(factory, result_baseline)
        metrics_slowdown = compute_metrics(factory, result_slowdown)

        # Makespan should differ (slowdown increases it)
        assert metrics_slowdown.makespan_hour >= metrics_baseline.makespan_hour, \
            "Slowdown should increase makespan"


class TestTypeSanity:
    """Test type correctness of all metric fields."""

    def test_job_lateness_keys_are_job_ids(self):
        """Verify job_lateness dict keys are exactly the job IDs in factory."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        factory_job_ids = {j.id for j in factory.jobs}
        metrics_job_ids = set(metrics.job_lateness.keys())

        assert metrics_job_ids == factory_job_ids, \
            f"Job IDs mismatch: {metrics_job_ids} vs {factory_job_ids}"

    def test_job_lateness_values_are_non_negative_ints(self):
        """Verify all job_lateness values are non-negative integers."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        for job_id, lateness in metrics.job_lateness.items():
            assert isinstance(lateness, int), f"Job {job_id} lateness is not int"
            assert lateness >= 0, f"Job {job_id} lateness is negative"

    def test_metrics_model_valid(self):
        """Verify metrics is a valid ScenarioMetrics instance."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert isinstance(metrics, ScenarioMetrics)

    def test_all_fields_present(self):
        """Verify metrics has all required fields."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert hasattr(metrics, "makespan_hour")
        assert hasattr(metrics, "job_lateness")
        assert hasattr(metrics, "bottleneck_machine_id")
        assert hasattr(metrics, "bottleneck_utilization")

    def test_makespan_hour_is_int(self):
        """Verify makespan_hour is an integer."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert isinstance(metrics.makespan_hour, int)

    def test_bottleneck_machine_id_is_str(self):
        """Verify bottleneck_machine_id is a string."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        assert isinstance(metrics.bottleneck_machine_id, str)


class TestPurity:
    """Test that compute_metrics is pure (no mutations, no I/O)."""

    def test_compute_metrics_does_not_mutate_factory(self):
        """Verify compute_metrics does not mutate the factory."""
        factory = build_toy_factory()
        factory_copy = deepcopy(factory)

        result = simulate_baseline(factory)
        compute_metrics(factory, result)

        # Factory should be unchanged
        assert factory.model_dump() == factory_copy.model_dump()

    def test_compute_metrics_does_not_mutate_result(self):
        """Verify compute_metrics does not mutate the result."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        result_copy = deepcopy(result)

        compute_metrics(factory, result)

        # Result should be unchanged
        assert result.model_dump() == result_copy.model_dump()

    def test_compute_metrics_deterministic(self):
        """Verify compute_metrics is deterministic."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        metrics1 = compute_metrics(factory, result)
        metrics2 = compute_metrics(factory, result)

        assert metrics1 == metrics2, \
            "compute_metrics should be deterministic"


class TestErrorHandling:
    """Test error handling in compute_metrics."""

    def test_error_on_missing_job_completion_time(self):
        """Verify error if result is missing completion time for a job."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # Remove a job from completion times
        del result.job_completion_times[factory.jobs[0].id]

        with pytest.raises(ValueError, match="missing from result"):
            compute_metrics(factory, result)

    def test_error_on_empty_scheduled_steps(self):
        """Verify error if result has no scheduled steps."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # Clear scheduled steps
        result.scheduled_steps = []

        with pytest.raises(ValueError, match="No scheduled steps"):
            compute_metrics(factory, result)

    def test_error_on_negative_makespan(self):
        """Verify error if makespan is negative (shouldn't happen in practice)."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # Artificially set negative makespan
        result.makespan_hour = -1

        with pytest.raises(ValueError, match="must be positive"):
            compute_metrics(factory, result)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_all_jobs_complete_on_time_in_baseline(self):
        """Verify baseline toy factory has no late jobs."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        metrics = compute_metrics(factory, result)

        # In baseline, all jobs should be on time
        for job_id, lateness in metrics.job_lateness.items():
            assert lateness == 0, f"Job {job_id} is late in baseline: {lateness}h"

    def test_metrics_with_rush_scenario(self):
        """Verify metrics computation works with RUSH_ARRIVES scenario."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ARRIVES, rush_job_id="J2")
        result = simulate(factory, spec)
        metrics = compute_metrics(factory, result)

        # Just verify it computes without error and has valid structure
        assert metrics.makespan_hour > 0
        assert len(metrics.job_lateness) == len(factory.jobs)
        assert metrics.bottleneck_machine_id in {m.id for m in factory.machines}

    def test_metrics_with_slowdown_scenario(self):
        """Verify metrics computation works with M2_SLOWDOWN scenario."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.M2_SLOWDOWN, slowdown_factor=2)
        result = simulate(factory, spec)
        metrics = compute_metrics(factory, result)

        # Just verify it computes without error and has valid structure
        assert metrics.makespan_hour > 0
        assert len(metrics.job_lateness) == len(factory.jobs)
        assert metrics.bottleneck_machine_id in {m.id for m in factory.machines}

    def test_utilization_increases_with_slowdown(self):
        """Verify bottleneck utilization generally increases with slowdown (on M2)."""
        factory = build_toy_factory()

        baseline_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        slowdown_spec = ScenarioSpec(scenario_type=ScenarioType.M2_SLOWDOWN, slowdown_factor=2)

        result_baseline = simulate(factory, baseline_spec)
        result_slowdown = simulate(factory, slowdown_spec)

        metrics_baseline = compute_metrics(factory, result_baseline)
        metrics_slowdown = compute_metrics(factory, result_slowdown)

        # If slowdown is on M2 and M2 is bottleneck in both, utilization should increase or stay same
        # (may increase if makespan increases slower than M2 busy hours)
        assert metrics_slowdown.bottleneck_machine_id == "M2"
        assert metrics_baseline.bottleneck_machine_id == "M2"
        assert metrics_slowdown.bottleneck_utilization >= metrics_baseline.bottleneck_utilization, \
            "Slowdown on bottleneck should not decrease utilization"
