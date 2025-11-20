"""
Simulation Engine Module

Implements the baseline scheduler using Earliest Due Date (EDD) heuristic
with greedy machine allocation to produce SimulationResult objects.

All times are in integer hours; no fractional scheduling.
"""

from models import FactoryConfig, SimulationResult, ScheduledStep


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
