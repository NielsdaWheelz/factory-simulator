"""
Onboarding Module

Provides utilities for safely onboarding free-text factory descriptions into
the simulation pipeline.

Core functions:
- normalize_factory(factory: FactoryConfig) -> tuple[FactoryConfig, list[str]]
  Cleans up and validates a FactoryConfig, fixing bad durations, invalid references.
  Returns both the normalized factory (may be empty) and a list of repair messages.
  Does not handle fallback; that is the caller's responsibility.

- estimate_onboarding_coverage(factory_text: str, factory: FactoryConfig) -> list[str]
  Inspects raw text for explicit machine/job IDs and compares to parsed factory.
  Returns human-readable warnings if mentioned entities are missing from the parsed output.
  Pure, deterministic helper; no logging. Used for transparency/observability.
"""

import logging
import re
from .models import FactoryConfig, Machine, Job, Step

logger = logging.getLogger(__name__)


def normalize_factory(factory: FactoryConfig) -> tuple[FactoryConfig, list[str]]:
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

    This function performs repairs only and never decides fallback or uses default factories.
    Fallback logic is handled at the orchestration layer (orchestrator.py or HTTP endpoints).

    Args:
        factory: FactoryConfig to normalize. Will not be mutated in-place.

    Returns:
        Tuple of (normalized_factory, warnings):
        - normalized_factory: A new FactoryConfig with repairs applied (may be empty)
        - warnings: List of human-readable repair messages (empty if no repairs needed)

    Guarantee:
        - Never raises an exception
        - Never mutates input factory
        - Never calls build_toy_factory() or any default factory
        - Never signals fallback via warning messages
        - Every repair is documented in the warnings list
    """
    warnings = []

    # Machines don't need normalization, but compute valid IDs
    valid_machine_ids = {m.id for m in factory.machines}

    # Normalize jobs: fix durations, due times, and invalid machine references
    normalized_jobs = []
    for job in factory.jobs:
        # Normalize job due_time_hour
        normalized_due_time = job.due_time_hour
        if not isinstance(normalized_due_time, int) or normalized_due_time < 0:
            normalized_due_time = 24
            warnings.append(f"Clamped due_time_hour for job {job.id} to 24")

        # Normalize and filter steps
        normalized_steps = []
        for step in job.steps:
            # Skip steps with invalid machine_id
            if step.machine_id not in valid_machine_ids:
                warnings.append(
                    f"Dropped step with invalid machine_id {step.machine_id} for job {job.id}"
                )
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
                warnings.append(
                    f"Set duration_hours to 1 for step on machine {step.machine_id} in job {job.id}"
                )

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
            warnings.append(
                f"Dropped job {job.id} because it has no valid steps after normalization"
            )
            logger.debug(
                "Dropping job %s because it has no valid steps after normalization",
                job.id,
            )

    # Return normalized factory (may be empty) and warnings list
    # Fallback logic is handled by the caller (orchestrator or endpoint)
    return FactoryConfig(machines=factory.machines, jobs=normalized_jobs), warnings


def estimate_onboarding_coverage(factory_text: str, factory: FactoryConfig) -> list[str]:
    """
    Inspect raw factory text for explicit machine/job IDs and compare to parsed factory.

    Returns a list of human-readable warnings if explicitly mentioned entities
    are missing from the parsed FactoryConfig. This is a pure helper for observability
    and transparency; it does not change behavior or trigger fallback.

    Heuristics:
    - Machine IDs: Regex \bM[0-9A-Za-z_]+\b (e.g., M1, M2, M_ASSEMBLY)
    - Job IDs: Regex \bJ[0-9A-Za-z_]+\b (e.g., J1, J2, J_WIDGET_A)
    - Generate warnings only if explicit mentions exist but are missing from parsed config.

    Args:
        factory_text: Raw factory description (user input)
        factory: Parsed FactoryConfig

    Returns:
        list[str]: Human-readable warnings (empty if no coverage issues detected)
    """
    warnings = []

    # Extract candidate machine IDs from text
    # Pattern: M followed by at least one digit, underscore, or letter (e.g., M1, M_ASSEMBLY, M01)
    # Requires at least one digit or underscore to avoid false positives like "My"
    machine_id_pattern = r'\bM[0-9][0-9A-Za-z_]*\b|\bM_[0-9A-Za-z_]+\b'
    mentioned_machine_ids = set(re.findall(machine_id_pattern, factory_text))

    # Extract candidate job IDs from text
    # Pattern: J followed by at least one digit, underscore, or letter (e.g., J1, J_WIDGET, J01)
    # Requires at least one digit or underscore to avoid false positives like "Job", "Jobs"
    job_id_pattern = r'\bJ[0-9][0-9A-Za-z_]*\b|\bJ_[0-9A-Za-z_]+\b'
    mentioned_job_ids = set(re.findall(job_id_pattern, factory_text))

    # Get parsed IDs from factory
    parsed_machine_ids = {m.id for m in factory.machines}
    parsed_job_ids = {j.id for j in factory.jobs}

    # Detect missing machines
    missing_machines = mentioned_machine_ids - parsed_machine_ids
    if missing_machines:
        missing_list = sorted(list(missing_machines))
        warnings.append(
            f"Onboarding coverage warning: machines {missing_list} were mentioned in the description "
            f"but did not appear in the parsed factory."
        )

    # Detect missing jobs
    missing_jobs = mentioned_job_ids - parsed_job_ids
    if missing_jobs:
        missing_list = sorted(list(missing_jobs))
        warnings.append(
            f"Onboarding coverage warning: jobs {missing_list} were mentioned in the description "
            f"but did not appear in the parsed factory."
        )

    return warnings
