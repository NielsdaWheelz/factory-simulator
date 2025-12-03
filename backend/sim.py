"""
Simulation Engine Module

Implements the baseline scheduler using Earliest Due Date (EDD) heuristic
with greedy machine allocation to produce SimulationResult objects.

All times are in integer hours; no fractional scheduling.
"""

import logging
from copy import deepcopy
from .models import FactoryConfig, SimulationResult, ScheduledStep, ScenarioSpec, ScenarioType, Job, Step

logger = logging.getLogger(__name__)


def simulate_baseline(factory: FactoryConfig) -> SimulationResult:
    """
    Run baseline simulation using EDD (Earliest Due Date) scheduler.

    Scheduling algorithm:
    1. Sort jobs by due_time_hour (earliest first)
    2. For each job, schedule steps in order
    3. For each step, find earliest available slot on the machine
       that respects both machine availability and job step dependencies
    4. Record all scheduled steps and compute completion times

    Args:
        factory: FactoryConfig with machines and jobs

    Returns:
        SimulationResult with scheduled steps and completion times
    """
    # Track when each machine becomes available
    machine_available_at: dict[str, int] = {m.id: 0 for m in factory.machines}

    # Track when each job is ready for its next step
    job_available_at: dict[str, int] = {j.id: 0 for j in factory.jobs}

    # Collect all scheduled steps
    scheduled_steps: list[ScheduledStep] = []

    # Sort jobs by due time (deterministic order)
    sorted_jobs = sorted(factory.jobs, key=lambda j: (j.due_time_hour, j.id))

    # Schedule each job's steps
    for job in sorted_jobs:
        for step_index, step in enumerate(job.steps):
            # Earliest start is the later of:
            # - When the machine is available
            # - When the previous step completes
            earliest_start = max(
                machine_available_at[step.machine_id],
                job_available_at[job.id],
            )

            start_hour = earliest_start
            end_hour = start_hour + step.duration_hours

            # Record this scheduled step
            scheduled_step = ScheduledStep(
                job_id=job.id,
                machine_id=step.machine_id,
                step_index=step_index,
                start_hour=start_hour,
                end_hour=end_hour,
            )
            scheduled_steps.append(scheduled_step)

            # Update availability tracking
            machine_available_at[step.machine_id] = end_hour
            job_available_at[job.id] = end_hour

    # Compute job completion times (last step's end_hour for each job)
    job_completion_times: dict[str, int] = {}
    for job in factory.jobs:
        # Find all scheduled steps for this job
        job_steps = [s for s in scheduled_steps if s.job_id == job.id]
        if job_steps:
            # Completion time is the max end_hour among all steps
            job_completion_times[job.id] = max(s.end_hour for s in job_steps)
        else:
            job_completion_times[job.id] = 0

    # Compute makespan (max completion time across all jobs)
    makespan_hour = max(job_completion_times.values()) if job_completion_times else 0

    return SimulationResult(
        scheduled_steps=scheduled_steps,
        job_completion_times=job_completion_times,
        makespan_hour=makespan_hour,
    )


def apply_scenario(factory: FactoryConfig, spec: ScenarioSpec) -> FactoryConfig:
    """
    Return a modified FactoryConfig according to the given ScenarioSpec.

    - baseline: return a deep copy of the original factory (for safety).
    - rush_order: prioritize an existing job by tightening its due_time_hour.
    - machine_slowdown: slow a specified machine by slowdown_factor.

    Args:
        factory: Original FactoryConfig (never mutated)
        spec: ScenarioSpec defining the scenario to apply

    Returns:
        Modified FactoryConfig (a deep copy of the input)

    Raises:
        ValueError: If rush_order references a non-existent job
        ValueError: If machine_slowdown references a non-existent machine
    """
    # Always start with a deep copy to avoid mutating the original
    factory_copy = deepcopy(factory)

    if spec.scenario_type == ScenarioType.BASELINE:
        # No changes, just return the copy
        return factory_copy

    elif spec.scenario_type == ScenarioType.RUSH_ORDER:
        # Find the job by ID and tighten its due time
        assert spec.rush_job_id is not None, "rush_order requires rush_job_id"

        rush_job = None
        for job in factory_copy.jobs:
            if job.id == spec.rush_job_id:
                rush_job = job
                break

        if rush_job is None:
            raise ValueError(f"Job '{spec.rush_job_id}' not found in factory")

        # Compute the minimum existing due_time_hour across all jobs
        earliest_due = min(job.due_time_hour for job in factory_copy.jobs)

        # Tighten the rush job's due time to be earlier than the current minimum
        rush_job.due_time_hour = max(0, earliest_due - 1)

        return factory_copy

    elif spec.scenario_type == ScenarioType.MACHINE_SLOWDOWN:
        assert spec.slowdown_factor is not None and spec.slowdown_factor >= 2, \
            "machine_slowdown requires slowdown_factor >= 2"
        assert spec.slowdown_machine_id is not None, \
            "machine_slowdown requires slowdown_machine_id"

        machine_id = spec.slowdown_machine_id
        
        # Validate machine exists in factory
        machine_ids = {m.id for m in factory_copy.machines}
        if machine_id not in machine_ids:
            raise ValueError(f"Machine '{machine_id}' not found in factory. Available: {sorted(machine_ids)}")

        # Apply slowdown to all steps on this machine
        for job in factory_copy.jobs:
            for step in job.steps:
                if step.machine_id == machine_id:
                    step.duration_hours = step.duration_hours * spec.slowdown_factor

        return factory_copy

    else:
        raise ValueError(f"Unknown scenario type: {spec.scenario_type}")


def simulate(factory: FactoryConfig, spec: ScenarioSpec) -> SimulationResult:
    """
    High-level simulation entrypoint.

    Applies the given ScenarioSpec to the baseline factory config,
    then runs the baseline scheduler on the modified config.

    Args:
        factory: Original FactoryConfig
        spec: ScenarioSpec defining the scenario to apply

    Returns:
        SimulationResult from running the scheduler on the modified factory
    """
    logger.debug("simulate called for scenario_type=%s", spec.scenario_type)
    modified_factory = apply_scenario(factory, spec)
    return simulate_baseline(modified_factory)
