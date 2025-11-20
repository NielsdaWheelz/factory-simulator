"""
Onboarding Module

Provides utilities for safely onboarding free-text factory descriptions into
the simulation pipeline without requiring LLM calls yet.

Core functions:
- normalize_factory(factory: FactoryConfig) -> FactoryConfig
  Cleans up and validates a FactoryConfig, fixing bad durations, invalid references,
  and falling back to the toy factory if normalization results in an empty config.
"""

import logging
from models import FactoryConfig, Machine, Job, Step
from world import build_toy_factory

logger = logging.getLogger(__name__)


def normalize_factory(factory: FactoryConfig) -> FactoryConfig:
    """
    Normalize a FactoryConfig to ensure it is safe for simulation.

    Performs the following repairs:
    1. For each Step.duration_hours:
       - If missing, not an int, or <= 0, set to 1.
    2. For each Job.due_time_hour:
       - If missing, not an int, or < 0, set to 24.
    3. Clean invalid references:
       - Compute the set of valid machine IDs from factory.machines.
       - Drop any steps whose machine_id is not in that set.
       - Drop any jobs that end up with zero steps.
    4. Fallback behavior:
       - If after normalization factory.machines is empty or factory.jobs is empty,
         log a warning and fall back to build_toy_factory().

    Args:
        factory: FactoryConfig to normalize. Will not be mutated in-place.

    Returns:
        A new normalized FactoryConfig, either the cleaned input or the toy factory fallback.
    """
    # Machines don't need normalization, but compute valid IDs
    valid_machine_ids = {m.id for m in factory.machines}

    # Normalize jobs: fix durations, due times, and invalid machine references
    normalized_jobs = []
    for job in factory.jobs:
        # Normalize job due_time_hour
        normalized_due_time = job.due_time_hour
        if not isinstance(normalized_due_time, int) or normalized_due_time < 0:
            normalized_due_time = 24

        # Normalize and filter steps
        normalized_steps = []
        for step in job.steps:
            # Skip steps with invalid machine_id
            if step.machine_id not in valid_machine_ids:
                logger.debug(
                    "Dropping step with invalid machine_id=%r for job %s",
                    step.machine_id,
                    job.id,
                )
                continue

            # Normalize duration_hours
            normalized_duration = step.duration_hours
            if not isinstance(normalized_duration, int) or normalized_duration <= 0:
                normalized_duration = 1

            normalized_steps.append(
                Step(machine_id=step.machine_id, duration_hours=normalized_duration)
            )

        # Only add the job if it has at least one valid step
        if normalized_steps:
            normalized_jobs.append(
                Job(
                    id=job.id,
                    name=job.name,
                    steps=normalized_steps,
                    due_time_hour=normalized_due_time,
                )
            )
        else:
            logger.debug(
                "Dropping job %s because it has no valid steps after normalization",
                job.id,
            )

    # Fallback: if no machines or no jobs remain, use toy factory
    if not factory.machines or not normalized_jobs:
        logger.warning(
            "Normalization resulted in empty factory (machines=%d, jobs=%d); "
            "falling back to toy factory",
            len(factory.machines),
            len(normalized_jobs),
        )
        return build_toy_factory()

    # Return normalized factory
    return FactoryConfig(machines=factory.machines, jobs=normalized_jobs)
