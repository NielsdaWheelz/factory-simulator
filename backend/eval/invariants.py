"""
Invariant validation helpers for adversarial evaluation harness.

These functions check properties of factories and metrics without raising exceptions,
returning a list of human-readable violation messages instead.
"""

from backend.models import FactoryConfig, ScenarioSpec, ScenarioMetrics


def check_factory_invariants(factory: FactoryConfig) -> list[str]:
    """
    Validate a FactoryConfig against structural invariants.

    Args:
        factory: The factory to validate.

    Returns:
        List of violation messages. Empty list means all invariants passed.
    """
    violations = []

    # Invariant 1: All steps reference valid machines
    machine_ids = {m.id for m in factory.machines}
    for job in factory.jobs:
        for step_idx, step in enumerate(job.steps):
            if step.machine_id not in machine_ids:
                violations.append(
                    f"Job {job.id} step {step_idx}: machine_id '{step.machine_id}' "
                    f"not in factory machines {sorted(machine_ids)}"
                )

    # Invariant 2: All step durations >= 1 hour
    for job in factory.jobs:
        for step_idx, step in enumerate(job.steps):
            if step.duration_hours < 1:
                violations.append(
                    f"Job {job.id} step {step_idx}: duration_hours={step.duration_hours} "
                    f"is less than minimum of 1 hour"
                )

    # Invariant 3: Every job has at least 1 step
    for job in factory.jobs:
        if not job.steps or len(job.steps) == 0:
            violations.append(f"Job {job.id}: has no steps (empty job)")

    # Invariant 4: Demo capacity caps
    if len(factory.machines) > 10:
        violations.append(
            f"Factory has {len(factory.machines)} machines (demo cap is 10)"
        )

    if len(factory.jobs) > 15:
        violations.append(
            f"Factory has {len(factory.jobs)} jobs (demo cap is 15)"
        )

    for job in factory.jobs:
        if len(job.steps) > 10:
            violations.append(
                f"Job {job.id} has {len(job.steps)} steps (demo cap is 10 per job)"
            )

    # Invariant 5: All due times >= 0
    for job in factory.jobs:
        if job.due_time_hour < 0:
            violations.append(
                f"Job {job.id}: due_time_hour={job.due_time_hour} is negative"
            )

    return violations


def check_metrics_invariants(
    factory: FactoryConfig,
    specs: list[ScenarioSpec],
    metrics: list[ScenarioMetrics],
) -> list[str]:
    """
    Validate metrics against structural and logical invariants.

    Args:
        factory: The factory used for simulation.
        specs: The scenario specs that were simulated.
        metrics: The resulting metrics from simulation.

    Returns:
        List of violation messages. Empty list means all invariants passed.
    """
    violations = []

    # Invariant 1: len(metrics) == len(specs)
    if len(metrics) != len(specs):
        violations.append(
            f"Metrics count mismatch: {len(metrics)} metrics but {len(specs)} specs"
        )

    # Build set of valid job IDs for cross-checks
    job_ids = {job.id for job in factory.jobs}
    machine_ids = {m.id for m in factory.machines}

    # Invariant 2-5: Per-metric checks
    for idx, metric in enumerate(metrics):
        # 2a: makespan_hour >= 0
        if metric.makespan_hour < 0:
            violations.append(
                f"Metrics[{idx}]: makespan_hour={metric.makespan_hour} is negative"
            )

        # 2b: bottleneck_machine_id is valid
        if metric.bottleneck_machine_id not in machine_ids:
            violations.append(
                f"Metrics[{idx}]: bottleneck_machine_id '{metric.bottleneck_machine_id}' "
                f"not in factory machines {sorted(machine_ids)}"
            )

        # 2c: bottleneck_utilization in [0.0, 1.0]
        if not (0.0 <= metric.bottleneck_utilization <= 1.0):
            violations.append(
                f"Metrics[{idx}]: bottleneck_utilization={metric.bottleneck_utilization} "
                f"not in range [0.0, 1.0]"
            )

        # 2d: job_lateness keys are valid job IDs
        for job_id, lateness in metric.job_lateness.items():
            if job_id not in job_ids:
                violations.append(
                    f"Metrics[{idx}]: job_lateness has unknown job_id '{job_id}'"
                )

        # 2e: all lateness values >= 0
        for job_id, lateness in metric.job_lateness.items():
            if lateness < 0:
                violations.append(
                    f"Metrics[{idx}]: job_lateness[{job_id}]={lateness} is negative"
                )

    return violations
