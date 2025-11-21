"""
Onboarding Module

Provides utilities for safely onboarding free-text factory descriptions into
the simulation pipeline.

PR7: Multi-stage extraction + coverage instrumentation
- Stage 0: Deterministic ID extraction (regex-based, zero-LLM)
- Stage 1: LLM enumeration of entities (machines/jobs only, no steps/durations)
- Stage 2: Coverage computation between explicit text and enumerated entities
- Stage 3: Full FactoryConfig LLM call (existing behavior, now with visibility into coverage)

Core functions:
- normalize_factory(factory: FactoryConfig) -> tuple[FactoryConfig, list[str]]
  Cleans up and validates a FactoryConfig, fixing bad durations, invalid references.
  Returns both the normalized factory (may be empty) and a list of repair messages.
  Does not handle fallback; that is the caller's responsibility.

- estimate_onboarding_coverage(factory_text: str, factory: FactoryConfig) -> list[str]
  Inspects raw text for explicit machine/job IDs and compares to parsed factory.
  Returns human-readable warnings if mentioned entities are missing from the parsed output.
  Pure, deterministic helper; no logging. Used for transparency/observability.

- extract_explicit_ids(factory_text: str) -> ExplicitIds
  Pure regex-based extraction of machine/job IDs from text.
  No LLM, no inferences; only what's explicitly mentioned.

- compute_coverage(explicit_ids: ExplicitIds, entities: FactoryEntities) -> CoverageReport
  Compares detected IDs with enumerated entities.
  Returns coverage metrics and missing ID sets.
"""

import logging
import re
from pydantic import BaseModel, field_validator
from .models import FactoryConfig, Machine, Job, Step
from .llm import call_llm_json

logger = logging.getLogger(__name__)


# ============================================================================
# ID GRAMMAR HELPERS (Canonical Source of Truth)
# ============================================================================

def is_machine_id(s: str) -> bool:
    """
    Check if a string matches the machine ID grammar.

    Machine IDs must be "M" followed by:
    - One digit and zero or more alphanumeric/underscore chars, OR
    - An underscore followed by one or more letters/underscores (NOT digits alone)

    Valid examples: M1, M2, M10, M1_ASSEMBLY, M3_PACK, M_WIDGET
    Invalid examples: M_1, MACHINE1, M, 1M, M-1

    Args:
        s: String to validate

    Returns:
        True if s matches the machine ID pattern, False otherwise
    """
    # Pattern: M followed by (digit + optional alnum/underscore) OR (underscore + non-digit chars)
    pattern = r'^M(?:[0-9][0-9A-Za-z_]*|_[A-Za-z_][A-Za-z0-9_]*)$'
    return re.match(pattern, s) is not None


def is_job_id(s: str) -> bool:
    """
    Check if a string matches the job ID grammar.

    Job IDs must be "J" followed by:
    - One digit and zero or more alphanumeric/underscore chars, OR
    - An underscore followed by one or more letters/underscores (NOT digits alone)

    Valid examples: J1, J2, J10, J2_A, J3_WIDGET, J_ORDER
    Invalid examples: JOB1, J_1, 1J, J-1

    Args:
        s: String to validate

    Returns:
        True if s matches the job ID pattern, False otherwise
    """
    # Pattern: J followed by (digit + optional alnum/underscore) OR (underscore + non-digit chars)
    pattern = r'^J(?:[0-9][0-9A-Za-z_]*|_[A-Za-z_][A-Za-z0-9_]*)$'
    return re.match(pattern, s) is not None


# ============================================================================
# STAGE 0: Deterministic ID Extraction Models & Functions
# ============================================================================

class ExplicitIds(BaseModel):
    """Result of stage-0 explicit ID extraction from raw text."""
    machine_ids: set[str]
    job_ids: set[str]


def extract_explicit_ids(factory_text: str) -> ExplicitIds:
    """
    Extract explicit machine and job IDs from factory text using regex.

    Pure function: no LLM, no inferences. Only matches what's explicitly present.

    Algorithm:
    1. Find all word-boundary-delimited substrings that look like IDs
    2. Validate each against is_machine_id() and is_job_id()
    3. Return deduplicated sets

    Args:
        factory_text: Raw factory description text

    Returns:
        ExplicitIds with sets of detected machine_ids and job_ids
    """
    # Pattern: M or J followed by at least one digit or underscore and optional alnum/underscore
    # Use word boundaries to avoid false matches like "EM1" or "JOB"
    id_pattern = r'\b[MJ][0-9][0-9A-Za-z_]*\b|\b[MJ]_[0-9A-Za-z_]+\b'
    candidate_ids = re.findall(id_pattern, factory_text)

    machine_ids = {cid for cid in candidate_ids if is_machine_id(cid)}
    job_ids = {cid for cid in candidate_ids if is_job_id(cid)}

    return ExplicitIds(machine_ids=machine_ids, job_ids=job_ids)


# ============================================================================
# STAGE 1: Entity Enumeration Models (LLM-backed)
# ============================================================================

class CoarseMachine(BaseModel):
    """A machine identified by ID and name (no steps or other details)."""
    id: str
    name: str

    @field_validator("id", "name")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        """Ensure id and name are non-empty strings."""
        if not v or not isinstance(v, str) or len(v.strip()) == 0:
            raise ValueError("id and name must be non-empty strings")
        return v


class CoarseJob(BaseModel):
    """A job identified by ID and name (no steps or routing details)."""
    id: str
    name: str

    @field_validator("id", "name")
    @classmethod
    def validate_nonempty(cls, v: str) -> str:
        """Ensure id and name are non-empty strings."""
        if not v or not isinstance(v, str) or len(v.strip()) == 0:
            raise ValueError("id and name must be non-empty strings")
        return v


class CoarseStructure(BaseModel):
    """Coarse skeleton of factory: machines and jobs (no steps/durations/routing)."""
    machines: list[CoarseMachine]
    jobs: list[CoarseJob]


class FactoryEntity(BaseModel):
    """A factory entity (machine or job) identified by ID and name."""
    id: str
    name: str


class FactoryEntities(BaseModel):
    """Collection of enumerated machines and jobs (no steps/durations)."""
    machines: list[FactoryEntity]
    jobs: list[FactoryEntity]


def extract_coarse_structure(
    factory_text: str,
    ids: ExplicitIds,
) -> CoarseStructure:
    """
    Extract a coarse structure (machines + jobs skeleton) from factory text.

    This is a focused, single-responsibility function:
    - Takes raw factory text and pre-extracted explicit IDs from stage-0
    - Builds a surgical prompt for the LLM to enumerate machines and jobs only
    - Calls call_llm_json with the prompt and CoarseStructure schema
    - Returns the parsed CoarseStructure (machines and jobs, no steps/durations/routing)

    The LLM is instructed to:
    - Include ALL IDs from ids.machine_ids and ids.job_ids in output (if they appear in text)
    - NOT invent IDs that don't appear in the text
    - Extract descriptive names where available, fall back to "M1"/"J1" style names
    - Focus only on machines and jobs, not steps, durations, or routing

    This function:
    - Does NOT enforce coverage, normalize, log, or catch exceptions
    - Does NOT call any fallback logic
    - Lets exceptions from call_llm_json propagate up (higher layers decide error handling)

    Args:
        factory_text: Raw factory description text
        ids: ExplicitIds containing machine_ids and job_ids explicitly detected in text

    Returns:
        CoarseStructure with machines and jobs (may be empty lists)

    Raises:
        RuntimeError: If LLM call fails (from call_llm_json)
        ValidationError: If LLM response doesn't match CoarseStructure schema
    """
    prompt = _build_coarse_extraction_prompt(factory_text, ids)
    structure = call_llm_json(prompt, CoarseStructure)
    return structure


def _build_coarse_extraction_prompt(
    factory_text: str,
    ids: ExplicitIds,
) -> str:
    """
    Build a focused prompt for extracting coarse structure (machines + jobs only).

    Args:
        factory_text: Raw factory description
        ids: ExplicitIds with machine_ids and job_ids to include

    Returns:
        Prompt string for the LLM
    """
    machines_str = ", ".join(sorted(ids.machine_ids)) if ids.machine_ids else "(none detected)"
    jobs_str = ", ".join(sorted(ids.job_ids)) if ids.job_ids else "(none detected)"

    prompt = f"""You are a factory structure extraction assistant. Your task is to extract machines and jobs from the factory description.

CRITICAL REQUIREMENTS:
1. You MUST include every machine ID in this list: {machines_str}
2. You MUST include every job ID in this list: {jobs_str}
3. You MUST NOT invent IDs that don't appear in the factory description.
4. For each machine/job, extract a descriptive name from the text if available.
5. If no descriptive text is available, use a simple fallback name like "Machine M1" or "Job J1".
6. DO NOT extract steps, durations, routing, or due times in this response.

OUTPUT SCHEMA (JSON ONLY):
{{
  "machines": [
    {{"id": "M1", "name": "assembly"}},
    {{"id": "M2", "name": "drill"}}
  ],
  "jobs": [
    {{"id": "J1", "name": "widget assembly"}},
    {{"id": "J2", "name": "gadget packing"}}
  ]
}}

FACTORY DESCRIPTION:
{factory_text}

OUTPUT (JSON ONLY):
"""
    return prompt


# ============================================================================
# STAGE 2: Coverage Computation Models & Functions
# ============================================================================

class CoverageReport(BaseModel):
    """Coverage metrics comparing explicit text IDs to enumerated entities."""
    detected_machine_ids: set[str]
    detected_job_ids: set[str]
    enumerated_machine_ids: set[str]
    enumerated_job_ids: set[str]
    missing_machines: set[str]
    missing_jobs: set[str]
    machine_coverage: float  # 0.0 to 1.0
    job_coverage: float      # 0.0 to 1.0


def compute_coverage(explicit_ids: ExplicitIds, entities: FactoryEntities) -> CoverageReport:
    """
    Compute coverage between explicitly detected IDs and enumerated entities.

    Coverage ratio calculation:
    - If no detected IDs of a type, coverage = 1.0 (nothing to cover)
    - Else: coverage = |enumerated ∩ detected| / |detected|

    Args:
        explicit_ids: Result from stage-0 explicit ID extraction
        entities: Result from stage-1 LLM enumeration

    Returns:
        CoverageReport with detected/enumerated/missing IDs and coverage ratios
    """
    # Get enumerated IDs
    enumerated_machine_ids = {m.id for m in entities.machines}
    enumerated_job_ids = {j.id for j in entities.jobs}

    # Compute missing IDs
    missing_machines = explicit_ids.machine_ids - enumerated_machine_ids
    missing_jobs = explicit_ids.job_ids - enumerated_job_ids

    # Compute coverage ratios
    if explicit_ids.machine_ids:
        machine_coverage = len(enumerated_machine_ids & explicit_ids.machine_ids) / len(explicit_ids.machine_ids)
    else:
        machine_coverage = 1.0  # Nothing to cover

    if explicit_ids.job_ids:
        job_coverage = len(enumerated_job_ids & explicit_ids.job_ids) / len(explicit_ids.job_ids)
    else:
        job_coverage = 1.0  # Nothing to cover

    return CoverageReport(
        detected_machine_ids=explicit_ids.machine_ids,
        detected_job_ids=explicit_ids.job_ids,
        enumerated_machine_ids=enumerated_machine_ids,
        enumerated_job_ids=enumerated_job_ids,
        missing_machines=missing_machines,
        missing_jobs=missing_jobs,
        machine_coverage=machine_coverage,
        job_coverage=job_coverage,
    )


def enumerate_entities(
    factory_text: str,
    required_machine_ids: set[str],
    required_job_ids: set[str],
) -> FactoryEntities:
    """
    LLM-backed enumeration of machines and jobs from factory text.

    Stage-1 call: separated from full FactoryConfig call to focus on entity enumeration.
    This call does NOT produce:
    - Job steps
    - Step durations
    - Due times
    - Full routing information

    The LLM is explicitly instructed to:
    - Include ALL IDs in the required_*_ids sets
    - May infer additional entities if reasonable
    - Extract names from the text if available, else use fallback defaults

    Args:
        factory_text: Raw factory description text
        required_machine_ids: Machine IDs explicitly detected in text (stage-0)
        required_job_ids: Job IDs explicitly detected in text (stage-0)

    Returns:
        FactoryEntities with enumerated machines and jobs (no steps/durations)

    Raises:
        Exception: On LLM communication failure (caller should handle gracefully)
    """
    prompt = _build_enumeration_prompt(factory_text, required_machine_ids, required_job_ids)
    logger.debug(
        f"enumerate_entities: calling LLM to enumerate {len(required_machine_ids)} machines, "
        f"{len(required_job_ids)} jobs"
    )
    entities = call_llm_json(prompt, FactoryEntities)
    logger.debug(
        f"enumerate_entities: LLM returned {len(entities.machines)} machines, "
        f"{len(entities.jobs)} jobs"
    )
    return entities


def _build_enumeration_prompt(
    factory_text: str,
    required_machine_ids: set[str],
    required_job_ids: set[str],
) -> str:
    """
    Build prompt for stage-1 LLM enumeration (machines and jobs only).

    This prompt is narrower than the full FactoryConfig prompt.
    Focus: extract machine and job IDs and names only.
    Exclude: steps, durations, routing details, due times.

    Args:
        factory_text: Raw factory description
        required_machine_ids: Machine IDs to include
        required_job_ids: Job IDs to include

    Returns:
        Prompt string
    """
    required_machines_str = ", ".join(sorted(required_machine_ids)) if required_machine_ids else "(none detected)"
    required_jobs_str = ", ".join(sorted(required_job_ids)) if required_job_ids else "(none detected)"

    prompt = f"""You are a factory entity enumeration assistant. Your task is to enumerate (list) all machines and jobs mentioned in the factory description. Do not extract steps, durations, or routing details.

CRITICAL REQUIREMENTS:
1. You MUST include every machine ID in this list: {required_machines_str}
2. You MUST include every job ID in this list: {required_jobs_str}
3. You MAY infer additional machines or jobs if explicitly mentioned and reasonable.
4. For each machine/job, extract a name/description from the text if available.
5. If no description is available, use a generic name like "Machine M1" or "Job J1".

OUTPUT SCHEMA:
{{
  "machines": [
    {{"id": "M1", "name": "assembly"}},
    {{"id": "M2", "name": "drill"}}
  ],
  "jobs": [
    {{"id": "J1", "name": "Job 1"}},
    {{"id": "J2", "name": "Job 2"}}
  ]
}}

FACTORY DESCRIPTION:
{factory_text}

OUTPUT (JSON ONLY):
"""
    return prompt


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

    Uses extract_explicit_ids() internally to identify mentions, then compares
    against the parsed factory. Generates warnings only if explicit mentions
    exist but are missing from parsed config.

    Args:
        factory_text: Raw factory description (user input)
        factory: Parsed FactoryConfig

    Returns:
        list[str]: Human-readable warnings (empty if no coverage issues detected)
    """
    warnings = []

    # Extract explicit IDs from text using canonical helpers
    explicit_ids = extract_explicit_ids(factory_text)
    mentioned_machine_ids = explicit_ids.machine_ids
    mentioned_job_ids = explicit_ids.job_ids

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
