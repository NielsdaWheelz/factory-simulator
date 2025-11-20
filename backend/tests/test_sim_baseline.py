"""
Tests for baseline simulation.

Tests verify:
- Scheduling produces valid results (no overlaps, all integer hours)
- Job step ordering is preserved
- Makespan calculation is correct
- All invariants hold
"""

import pytest
from backend.world import build_toy_factory
from backend.sim import simulate_baseline


class TestBuildToyFactory:
    """Test toy factory construction."""

    def test_build_toy_factory_returns_config(self):
        """Verify toy factory returns a valid FactoryConfig."""
        factory = build_toy_factory()
        assert factory is not None
        assert len(factory.machines) == 3
        assert len(factory.jobs) == 3

    def test_machines_have_correct_ids(self):
        """Verify machines have expected IDs."""
        factory = build_toy_factory()
        machine_ids = {m.id for m in factory.machines}
        assert machine_ids == {"M1", "M2", "M3"}

    def test_jobs_have_correct_ids(self):
        """Verify jobs have expected IDs."""
        factory = build_toy_factory()
        job_ids = {j.id for j in factory.jobs}
        assert job_ids == {"J1", "J2", "J3"}

    def test_all_jobs_contend_for_m2(self):
        """Verify all three jobs have at least one step on M2."""
        factory = build_toy_factory()
        for job in factory.jobs:
            machine_ids = {s.machine_id for s in job.steps}
            assert "M2" in machine_ids, f"{job.id} should have a step on M2"

    def test_m2_is_bottleneck(self):
        """Verify M2 has the most contention (highest total duration across all jobs)."""
        factory = build_toy_factory()
        total_per_machine = {}
        for job in factory.jobs:
            for step in job.steps:
                total_per_machine[step.machine_id] = (
                    total_per_machine.get(step.machine_id, 0) + step.duration_hours
                )

        m2_total = total_per_machine.get("M2", 0)
        m1_total = total_per_machine.get("M1", 0)
        m3_total = total_per_machine.get("M3", 0)

        # M2 should have the highest total load
        assert m2_total > m1_total
        assert m2_total > m3_total

    def test_all_steps_have_integer_durations(self):
        """Verify all steps have integer durations."""
        factory = build_toy_factory()
        for job in factory.jobs:
            for step in job.steps:
                assert isinstance(step.duration_hours, int)
                assert step.duration_hours > 0

    def test_all_due_times_are_integers(self):
        """Verify all jobs have integer due times."""
        factory = build_toy_factory()
        for job in factory.jobs:
            assert isinstance(job.due_time_hour, int)


class TestSimulateBaseline:
    """Test baseline simulation."""

    def test_simulate_baseline_produces_result(self):
        """Verify simulate_baseline returns a valid SimulationResult."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        assert result is not None
        assert result.scheduled_steps
        assert result.job_completion_times
        assert result.makespan_hour > 0

    def test_scheduled_steps_are_not_empty(self):
        """Verify at least one step is scheduled."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        assert len(result.scheduled_steps) > 0

    def test_all_scheduled_steps_have_integer_hours(self):
        """Verify all scheduled step times are integers."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)
        for step in result.scheduled_steps:
            assert isinstance(step.start_hour, int)
            assert isinstance(step.end_hour, int)
            assert step.start_hour < step.end_hour

    def test_no_machine_overlaps(self):
        """Verify no two steps on the same machine overlap."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # Group steps by machine
        steps_by_machine = {}
        for step in result.scheduled_steps:
            if step.machine_id not in steps_by_machine:
                steps_by_machine[step.machine_id] = []
            steps_by_machine[step.machine_id].append(step)

        # For each machine, verify no overlaps
        for machine_id, steps in steps_by_machine.items():
            # Sort by start_hour
            sorted_steps = sorted(steps, key=lambda s: s.start_hour)
            for i in range(len(sorted_steps) - 1):
                current = sorted_steps[i]
                next_step = sorted_steps[i + 1]
                # Current step must end before or at next step start
                assert (
                    current.end_hour <= next_step.start_hour
                ), f"Overlap on {machine_id}: {current} overlaps {next_step}"

    def test_job_steps_preserve_order(self):
        """Verify job steps are scheduled in order (step_index increases)."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # Group steps by job
        steps_by_job = {}
        for step in result.scheduled_steps:
            if step.job_id not in steps_by_job:
                steps_by_job[step.job_id] = []
            steps_by_job[step.job_id].append(step)

        # For each job, verify steps are in order and don't overlap
        for job_id, steps in steps_by_job.items():
            sorted_steps = sorted(steps, key=lambda s: s.step_index)
            # Verify step indices are 0, 1, 2, ... with no gaps
            for i, step in enumerate(sorted_steps):
                assert step.step_index == i, f"{job_id} step indices are not contiguous"
            # Verify each step starts >= previous step ends
            for i in range(len(sorted_steps) - 1):
                current = sorted_steps[i]
                next_step = sorted_steps[i + 1]
                assert (
                    next_step.start_hour >= current.end_hour
                ), f"Job {job_id}: step {i+1} starts before step {i} ends"

    def test_job_completion_times_match_last_step(self):
        """Verify job completion times match the end_hour of last step."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        for job_id, completion_time in result.job_completion_times.items():
            # Find all steps for this job
            job_steps = [s for s in result.scheduled_steps if s.job_id == job_id]
            if job_steps:
                expected_completion = max(s.end_hour for s in job_steps)
                assert (
                    completion_time == expected_completion
                ), f"{job_id} completion time mismatch"

    def test_makespan_equals_max_completion_time(self):
        """Verify makespan equals the max job completion time."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        expected_makespan = max(result.job_completion_times.values())
        assert result.makespan_hour == expected_makespan

    def test_determinism(self):
        """Verify same input yields same output."""
        factory = build_toy_factory()
        result1 = simulate_baseline(factory)
        result2 = simulate_baseline(factory)

        # Compare all scheduled steps
        assert len(result1.scheduled_steps) == len(result2.scheduled_steps)
        for s1, s2 in zip(result1.scheduled_steps, result2.scheduled_steps):
            assert s1.job_id == s2.job_id
            assert s1.machine_id == s2.machine_id
            assert s1.step_index == s2.step_index
            assert s1.start_hour == s2.start_hour
            assert s1.end_hour == s2.end_hour

        # Compare makespan and job completion times
        assert result1.makespan_hour == result2.makespan_hour
        assert result1.job_completion_times == result2.job_completion_times

    def test_all_jobs_scheduled(self):
        """Verify all jobs from factory have completion times."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        job_ids = {j.id for j in factory.jobs}
        completion_job_ids = set(result.job_completion_times.keys())
        assert job_ids == completion_job_ids

    def test_baseline_completes_reasonably(self):
        """Verify baseline completes within a reasonable time (<=24 hours)."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        # All jobs should complete within 24 hours in baseline
        assert result.makespan_hour <= 24

    def test_scheduled_step_references_valid_jobs_and_machines(self):
        """Verify all scheduled steps reference real jobs and machines."""
        factory = build_toy_factory()
        result = simulate_baseline(factory)

        job_ids = {j.id for j in factory.jobs}
        machine_ids = {m.id for m in factory.machines}

        for step in result.scheduled_steps:
            assert step.job_id in job_ids
            assert step.machine_id in machine_ids
