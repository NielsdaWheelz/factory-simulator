"""
Tests for scenario simulation.

Tests verify:
- BASELINE scenario produces identical results to simulate_baseline
- RUSH_ORDER scenario prioritizes the rush job
- MACHINE_SLOWDOWN scenario increases makespan and completion times
- apply_scenario does not mutate the original factory
"""

import pytest
from copy import deepcopy
from backend.world import build_toy_factory
from backend.sim import simulate_baseline, simulate, apply_scenario
from backend.models import ScenarioSpec, ScenarioType


class TestApplyScenarioBaseline:
    """Test BASELINE scenario application."""

    def test_baseline_returns_factory_copy(self):
        """Verify BASELINE scenario returns a deep copy of the factory."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        modified = apply_scenario(factory, spec)

        # Should be equal in content
        assert modified.model_dump() == factory.model_dump()
        # But a different object
        assert modified is not factory

    def test_baseline_does_not_mutate_original(self):
        """Verify BASELINE scenario does not mutate the original factory."""
        factory = build_toy_factory()
        original_copy = deepcopy(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        apply_scenario(factory, spec)

        # Original should be unchanged
        assert factory.model_dump() == original_copy.model_dump()


class TestSimulateBaseline:
    """Test BASELINE scenario simulation."""

    def test_baseline_simulation_matches_simulate_baseline(self):
        """Verify simulate with BASELINE spec produces identical results to simulate_baseline."""
        factory = build_toy_factory()
        baseline_result = simulate_baseline(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        scenario_result = simulate(factory, spec)

        # Makespans should match
        assert scenario_result.makespan_hour == baseline_result.makespan_hour

        # Job completion times should match
        assert scenario_result.job_completion_times == baseline_result.job_completion_times

        # Scheduled steps should match (compare as sorted tuples for determinism)
        baseline_steps = sorted(
            [(s.job_id, s.machine_id, s.step_index, s.start_hour, s.end_hour)
             for s in baseline_result.scheduled_steps]
        )
        scenario_steps = sorted(
            [(s.job_id, s.machine_id, s.step_index, s.start_hour, s.end_hour)
             for s in scenario_result.scheduled_steps]
        )
        assert baseline_steps == scenario_steps


class TestApplyScenarioRush:
    """Test RUSH_ORDER scenario application."""

    def test_rush_tightens_due_time(self):
        """Verify RUSH_ORDER tightens the due time of the rush job."""
        factory = build_toy_factory()
        original_j2_due = next(j.due_time_hour for j in factory.jobs if j.id == "J2")

        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")
        modified = apply_scenario(factory, spec)

        modified_j2_due = next(j.due_time_hour for j in modified.jobs if j.id == "J2")

        # J2 due time should be tightened (less than original)
        assert modified_j2_due < original_j2_due

    def test_rush_does_not_mutate_original(self):
        """Verify RUSH_ORDER does not mutate the original factory."""
        factory = build_toy_factory()
        original_copy = deepcopy(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")

        apply_scenario(factory, spec)

        # Original should be unchanged
        assert factory.model_dump() == original_copy.model_dump()

    def test_rush_raises_for_nonexistent_job(self):
        """Verify RUSH_ORDER raises ValueError for non-existent job."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J999")

        with pytest.raises(ValueError, match="not found"):
            apply_scenario(factory, spec)

    def test_rush_preserves_other_jobs(self):
        """Verify RUSH_ORDER preserves other jobs unchanged."""
        factory = build_toy_factory()
        j1_original = next(j.due_time_hour for j in factory.jobs if j.id == "J1")
        j3_original = next(j.due_time_hour for j in factory.jobs if j.id == "J3")

        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")
        modified = apply_scenario(factory, spec)

        j1_modified = next(j.due_time_hour for j in modified.jobs if j.id == "J1")
        j3_modified = next(j.due_time_hour for j in modified.jobs if j.id == "J3")

        # Other jobs should be unchanged
        assert j1_modified == j1_original
        assert j3_modified == j3_original

    def test_rush_preserves_job_steps(self):
        """Verify RUSH_ORDER does not change job steps."""
        factory = build_toy_factory()
        original_j2 = next(j for j in factory.jobs if j.id == "J2")
        original_steps = [(s.machine_id, s.duration_hours) for s in original_j2.steps]

        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")
        modified = apply_scenario(factory, spec)

        modified_j2 = next(j for j in modified.jobs if j.id == "J2")
        modified_steps = [(s.machine_id, s.duration_hours) for s in modified_j2.steps]

        assert modified_steps == original_steps


class TestSimulateRush:
    """Test RUSH_ORDER scenario simulation."""

    def test_rush_completes_job_earlier_or_same(self):
        """Verify RUSH_ORDER job completes no later than baseline."""
        factory = build_toy_factory()
        baseline_result = simulate_baseline(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")
        rush_result = simulate(factory, spec)

        # Rush job should complete no later than baseline
        assert rush_result.job_completion_times["J2"] <= baseline_result.job_completion_times["J2"]

    def test_rush_no_machine_overlaps(self):
        """Verify RUSH_ORDER result has no machine overlaps."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J2")
        result = simulate(factory, spec)

        # Group steps by machine
        steps_by_machine = {}
        for step in result.scheduled_steps:
            if step.machine_id not in steps_by_machine:
                steps_by_machine[step.machine_id] = []
            steps_by_machine[step.machine_id].append(step)

        # Verify no overlaps on any machine
        for machine_id, steps in steps_by_machine.items():
            sorted_steps = sorted(steps, key=lambda s: s.start_hour)
            for i in range(len(sorted_steps) - 1):
                current = sorted_steps[i]
                next_step = sorted_steps[i + 1]
                assert current.end_hour <= next_step.start_hour, \
                    f"Overlap on {machine_id}: {current} overlaps {next_step}"

    def test_rush_affects_other_jobs(self):
        """Verify RUSH_ORDER may affect other jobs' completion times."""
        factory = build_toy_factory()
        baseline_result = simulate_baseline(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J1")
        rush_result = simulate(factory, spec)

        # At least one other job should be affected (not faster due to rush)
        other_jobs = [j for j in ["J2", "J3"] if j != "J1"]
        at_least_one_affected = any(
            rush_result.job_completion_times[jid] >= baseline_result.job_completion_times[jid]
            for jid in other_jobs
        )
        # This test just verifies that rushing one job can affect others
        # (due to M2 contention), so at least one should not improve
        assert at_least_one_affected


class TestApplyScenarioSlowdown:
    """Test MACHINE_SLOWDOWN scenario application."""

    def test_slowdown_increases_m2_durations(self):
        """Verify MACHINE_SLOWDOWN multiplies M2 step durations."""
        factory = build_toy_factory()
        slowdown_factor = 2
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=slowdown_factor)
        modified = apply_scenario(factory, spec)

        # Check that all M2 steps are multiplied
        for original_job, modified_job in zip(factory.jobs, modified.jobs):
            for orig_step, mod_step in zip(original_job.steps, modified_job.steps):
                if orig_step.machine_id == "M2":
                    assert mod_step.duration_hours == orig_step.duration_hours * slowdown_factor
                else:
                    assert mod_step.duration_hours == orig_step.duration_hours

    def test_slowdown_does_not_mutate_original(self):
        """Verify MACHINE_SLOWDOWN does not mutate the original factory."""
        factory = build_toy_factory()
        original_copy = deepcopy(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)

        apply_scenario(factory, spec)

        # Original should be unchanged
        assert factory.model_dump() == original_copy.model_dump()

    def test_slowdown_preserves_non_m2_steps(self):
        """Verify MACHINE_SLOWDOWN does not affect non-M2 steps."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=3)
        modified = apply_scenario(factory, spec)

        for original_job, modified_job in zip(factory.jobs, modified.jobs):
            for orig_step, mod_step in zip(original_job.steps, modified_job.steps):
                if orig_step.machine_id != "M2":
                    assert mod_step.duration_hours == orig_step.duration_hours


class TestSimulateSlowdown:
    """Test MACHINE_SLOWDOWN scenario simulation."""

    def test_slowdown_increases_makespan(self):
        """Verify MACHINE_SLOWDOWN increases makespan."""
        factory = build_toy_factory()
        baseline_result = simulate_baseline(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)
        slow_result = simulate(factory, spec)

        # Makespan should increase with slowdown
        assert slow_result.makespan_hour >= baseline_result.makespan_hour

    def test_slowdown_increases_job_completion_times(self):
        """Verify MACHINE_SLOWDOWN increases all job completion times."""
        factory = build_toy_factory()
        baseline_result = simulate_baseline(factory)
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)
        slow_result = simulate(factory, spec)

        for job_id in baseline_result.job_completion_times:
            assert slow_result.job_completion_times[job_id] >= baseline_result.job_completion_times[job_id], \
                f"Job {job_id} completion time should not decrease with M2 slowdown"

    def test_slowdown_no_machine_overlaps(self):
        """Verify MACHINE_SLOWDOWN result has no machine overlaps."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)
        result = simulate(factory, spec)

        # Group steps by machine
        steps_by_machine = {}
        for step in result.scheduled_steps:
            if step.machine_id not in steps_by_machine:
                steps_by_machine[step.machine_id] = []
            steps_by_machine[step.machine_id].append(step)

        # Verify no overlaps on any machine
        for machine_id, steps in steps_by_machine.items():
            sorted_steps = sorted(steps, key=lambda s: s.start_hour)
            for i in range(len(sorted_steps) - 1):
                current = sorted_steps[i]
                next_step = sorted_steps[i + 1]
                assert current.end_hour <= next_step.start_hour, \
                    f"Overlap on {machine_id}: {current} overlaps {next_step}"

    def test_slowdown_preserves_integer_times(self):
        """Verify MACHINE_SLOWDOWN result uses only integer times."""
        factory = build_toy_factory()
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)
        result = simulate(factory, spec)

        for step in result.scheduled_steps:
            assert isinstance(step.start_hour, int)
            assert isinstance(step.end_hour, int)

        for completion_time in result.job_completion_times.values():
            assert isinstance(completion_time, int)

        assert isinstance(result.makespan_hour, int)


class TestPurityAndValidation:
    """Test apply_scenario purity and field validation."""

    def test_apply_scenario_does_not_mutate_any_scenario(self):
        """Verify apply_scenario never mutates the original factory."""
        factory = build_toy_factory()
        original_copy = deepcopy(factory)

        # Test all three scenario types
        specs = [
            ScenarioSpec(scenario_type=ScenarioType.BASELINE),
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J1"),
            ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2),
        ]

        for spec in specs:
            factory_test = deepcopy(original_copy)
            apply_scenario(factory_test, spec)
            assert factory_test.model_dump() == original_copy.model_dump(), \
                f"apply_scenario mutated factory for {spec.scenario_type}"

    def test_scenario_spec_validation_baseline(self):
        """Verify ScenarioSpec validates BASELINE scenario."""
        # Valid
        spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        assert spec.rush_job_id is None
        assert spec.slowdown_factor is None

        # Invalid: BASELINE with rush_job_id
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.BASELINE, rush_job_id="J1")

        # Invalid: BASELINE with slowdown_factor
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.BASELINE, slowdown_factor=2)

    def test_scenario_spec_validation_rush(self):
        """Verify ScenarioSpec validates RUSH_ORDER scenario."""
        # Valid
        spec = ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J1")
        assert spec.rush_job_id == "J1"

        # Invalid: RUSH_ORDER without rush_job_id
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER)

        # Invalid: RUSH_ORDER with empty rush_job_id
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="")

        # Invalid: RUSH_ORDER with slowdown_factor
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ORDER, rush_job_id="J1", slowdown_factor=2)

    def test_scenario_spec_validation_slowdown(self):
        """Verify ScenarioSpec validates MACHINE_SLOWDOWN scenario."""
        # Valid
        spec = ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2)
        assert spec.slowdown_factor == 2

        # Invalid: MACHINE_SLOWDOWN without slowdown_factor
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN)

        # Invalid: MACHINE_SLOWDOWN with slowdown_factor < 2
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=1)

        # Invalid: MACHINE_SLOWDOWN with slowdown_factor == 0
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=0)

        # Invalid: MACHINE_SLOWDOWN with rush_job_id
        with pytest.raises(ValueError):
            ScenarioSpec(scenario_type=ScenarioType.MACHINE_SLOWDOWN, slowdown_machine_id="M2", slowdown_factor=2, rush_job_id="J1")

    def test_simulate_all_jobs_present(self):
        """Verify simulate results include all jobs."""
        factory = build_toy_factory()
        job_ids = {j.id for j in factory.jobs}

        for scenario_type in [ScenarioType.BASELINE, ScenarioType.RUSH_ORDER, ScenarioType.MACHINE_SLOWDOWN]:
            if scenario_type == ScenarioType.RUSH_ORDER:
                spec = ScenarioSpec(scenario_type=scenario_type, rush_job_id="J1")
            elif scenario_type == ScenarioType.MACHINE_SLOWDOWN:
                spec = ScenarioSpec(scenario_type=scenario_type, slowdown_machine_id="M2", slowdown_factor=2)
            else:
                spec = ScenarioSpec(scenario_type=scenario_type)

            result = simulate(factory, spec)
            result_job_ids = set(result.job_completion_times.keys())
            assert result_job_ids == job_ids, \
                f"Missing jobs in result for {scenario_type}"
