"""
Metrics Computation Module

Computes aggregate performance metrics from simulation results.

- ScenarioMetrics: aggregated metrics for a single simulation run
- compute_metrics(factory, result) -> ScenarioMetrics: pure function to compute metrics

Metrics computed:
- makespan_hour: total time to complete all jobs
- job_lateness: per-job lateness (max(0, completion_time - due_time))
- bottleneck_machine_id: machine with highest total busy time
- bottleneck_utilization: bottleneck busy hours / makespan
"""

import logging
from collections import defaultdict
from .models import FactoryConfig, SimulationResult, ScenarioMetrics

logger = logging.getLogger(__name__)


def compute_metrics(factory: FactoryConfig, result: SimulationResult) -> ScenarioMetrics:
    """
    Compute aggregate metrics for a single simulation result.

    Pure function: does not mutate inputs, no I/O.

    Args:
        factory: FactoryConfig with machines and jobs
        result: SimulationResult from simulate_baseline or simulate

    Returns:
        ScenarioMetrics with aggregated performance data

    Raises:
        ValueError: if result is missing completion times for a job, or if no steps scheduled
    """
    # 1. Makespan (directly from result)
    makespan_hour = result.makespan_hour

    # 2. Job lateness: max(0, completion_time - due_time) per job
    job_lateness: dict[str, int] = {}
    for job in factory.jobs:
        if job.id not in result.job_completion_times:
            raise ValueError(f"Job '{job.id}' missing from result.job_completion_times")

        completion_time = result.job_completion_times[job.id]
        lateness = max(0, completion_time - job.due_time_hour)
        job_lateness[job.id] = lateness

    # 3. Bottleneck machine: compute total busy hours per machine
    if not result.scheduled_steps:
        raise ValueError("No scheduled steps in result; cannot identify bottleneck")

    machine_busy: dict[str, int] = defaultdict(int)
    for step in result.scheduled_steps:
        duration = step.end_hour - step.start_hour
        machine_busy[step.machine_id] += duration

    # Find bottleneck as machine with maximum busy time
    bottleneck_machine_id = max(machine_busy, key=machine_busy.get)
    bottleneck_busy_hours = machine_busy[bottleneck_machine_id]

    # 4. Bottleneck utilization: bottleneck_busy_hours / makespan
    if makespan_hour <= 0:
        raise ValueError("makespan_hour must be positive for utilization calculation")

    bottleneck_utilization = bottleneck_busy_hours / makespan_hour

    # Create and return metrics
    metrics = ScenarioMetrics(
        makespan_hour=makespan_hour,
        job_lateness=job_lateness,
        bottleneck_machine_id=bottleneck_machine_id,
        bottleneck_utilization=bottleneck_utilization,
    )

    logger.debug(
        "compute_metrics: makespan=%d bottleneck=%s util=%.3f",
        metrics.makespan_hour,
        metrics.bottleneck_machine_id,
        metrics.bottleneck_utilization,
    )

    return metrics
