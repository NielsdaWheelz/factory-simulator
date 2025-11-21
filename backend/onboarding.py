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
from typing import Any
from pydantic import BaseModel, field_validator
from .models import FactoryConfig, Machine, Job, Step
from .llm import call_llm_json

logger = logging.getLogger(__name__)


# ============================================================================
# STAGE 3: Normalization & Invariant Enforcement
# ============================================================================

class ExtractionError(Exception):
    """
    Exception raised when normalization or validation fails.

    Carries structured error information for observability:
    - code: error category (e.g., 'NORMALIZATION_FAILED', 'INVALID_STRUCTURE')
    - message: human-readable error description
    - details: optional dict with debug information
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


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
# STAGE 2: Fine Extraction Models & Functions (Steps & Timings)
# ============================================================================

class RawStep(BaseModel):
    """Raw (permissive) representation of a job step extracted by LLM."""
    machine_id: str
    duration_hours: float | int  # Allow fractional and junk; stage 3 will normalize


class RawJob(BaseModel):
    """Raw (permissive) representation of a job extracted by LLM."""
    id: str
    name: str
    steps: list[RawStep]
    due_time_hour: int | float | None  # Allow None / fractional; to be normalized later


class RawFactoryConfig(BaseModel):
    """Raw (permissive) factory configuration extracted by LLM."""
    machines: list[CoarseMachine]  # Reuse coarse DTOs
    jobs: list[RawJob]


def extract_steps(factory_text: str, coarse: CoarseStructure) -> RawFactoryConfig:
    """
    Extract job steps and timings from factory text using LLM.

    This is stage 2 of the multi-stage extraction pipeline:
    - Input: factory_text + coarse structure (machines + jobs from stage 1)
    - Output: RawFactoryConfig with steps and durations for each job
    - No normalization, no coverage enforcement, no orchestration changes

    The LLM is instructed to:
    - Only use machine_ids from coarse.machines (no invention)
    - Only use job_ids from coarse.jobs (no invention)
    - Infer steps and due times from the text
    - Output permissive data (fractional durations allowed)

    This function:
    - Does NOT normalize or validate durations/due times
    - Does NOT catch or transform exceptions
    - Lets LLM errors and validation errors propagate to the caller

    Args:
        factory_text: Raw factory description text
        coarse: CoarseStructure with machines and jobs (from stage 1)

    Returns:
        RawFactoryConfig with permissive step/timing data

    Raises:
        RuntimeError: If LLM call fails (from call_llm_json)
        ValidationError: If LLM response doesn't match RawFactoryConfig schema
        ValueError: If LLM invents machine/job IDs not in coarse
    """
    prompt = _build_fine_extraction_prompt(factory_text, coarse)
    raw = call_llm_json(prompt, RawFactoryConfig)

    # Validate ID consistency: LLM must not invent or drop entities
    coarse_machine_ids = {m.id for m in coarse.machines}
    raw_machine_ids = {m.id for m in raw.machines}
    if coarse_machine_ids != raw_machine_ids:
        missing = coarse_machine_ids - raw_machine_ids
        extra = raw_machine_ids - coarse_machine_ids
        msg_parts = []
        if missing:
            msg_parts.append(f"missing machine ids {sorted(missing)}")
        if extra:
            msg_parts.append(f"extra machine ids {sorted(extra)}")
        raise ValueError(f"LLM returned inconsistent machine ids: {', '.join(msg_parts)}")

    coarse_job_ids = {j.id for j in coarse.jobs}
    raw_job_ids = {j.id for j in raw.jobs}
    if coarse_job_ids != raw_job_ids:
        missing = coarse_job_ids - raw_job_ids
        extra = raw_job_ids - coarse_job_ids
        msg_parts = []
        if missing:
            msg_parts.append(f"missing job ids {sorted(missing)}")
        if extra:
            msg_parts.append(f"extra job ids {sorted(extra)}")
        raise ValueError(f"LLM returned inconsistent job ids: {', '.join(msg_parts)}")

    return raw


def _build_fine_extraction_prompt(factory_text: str, coarse: CoarseStructure) -> str:
    """
    Build a focused prompt for extracting job steps and timings (stage 2).

    Args:
        factory_text: Raw factory description text
        coarse: CoarseStructure with machines and jobs

    Returns:
        Prompt string for the LLM
    """
    # Build machine list with IDs and names
    machines_list = "\n".join(
        f"  - {m.id}: {m.name}" for m in coarse.machines
    ) if coarse.machines else "  (none)"

    # Build job list with IDs and names
    jobs_list = "\n".join(
        f"  - {j.id}: {j.name}" for j in coarse.jobs
    ) if coarse.jobs else "  (none)"

    # Get all valid machine IDs for reference in prompt
    machine_ids_str = ", ".join(m.id for m in coarse.machines) if coarse.machines else "(none)"
    job_ids_str = ", ".join(j.id for j in coarse.jobs) if coarse.jobs else "(none)"

    prompt = f"""You are a factory fine-extraction assistant. Your task is to extract job steps, timings, and due times from the factory description.

CRITICAL REQUIREMENTS:
1. You MUST preserve exactly the machines: {machine_ids_str}
2. You MUST preserve exactly the jobs: {job_ids_str}
3. You MUST NOT invent machine IDs or job IDs not listed above.
4. You MUST NOT drop or rename any machines or jobs from the lists above.
5. For each job, infer:
   - steps: ordered list of {{machine_id, duration_hours}} from the description
   - due_time_hour: when the job is due (can be None if not specified)
6. Duration values can be fractional (e.g., 2.5 hours); normalization happens downstream.
7. Do not add extra machines or jobs; the structure is fixed.

AVAILABLE MACHINES:
{machines_list}

AVAILABLE JOBS:
{jobs_list}

OUTPUT SCHEMA (JSON ONLY):
{{
  "machines": [
    {{"id": "M1", "name": "assembly"}},
    {{"id": "M2", "name": "drill"}}
  ],
  "jobs": [
    {{
      "id": "J1",
      "name": "widget assembly",
      "steps": [
        {{"machine_id": "M1", "duration_hours": 2.5}},
        {{"machine_id": "M2", "duration_hours": 1}}
      ],
      "due_time_hour": 8
    }},
    {{
      "id": "J2",
      "name": "gadget packing",
      "steps": [
        {{"machine_id": "M2", "duration_hours": 3}}
      ],
      "due_time_hour": null
    }}
  ]
}}

FACTORY DESCRIPTION:
{factory_text}

OUTPUT (JSON ONLY):
"""
    return prompt


# ============================================================================
# STAGE 3: Coverage Computation Models & Functions
# ============================================================================

class CoverageReport(BaseModel):
    """Coverage metrics comparing explicit text IDs to parsed factory entities."""
    detected_machines: set[str]
    detected_jobs: set[str]
    parsed_machines: set[str]
    parsed_jobs: set[str]
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
        detected_machines=explicit_ids.machine_ids,
        detected_jobs=explicit_ids.job_ids,
        parsed_machines=enumerated_machine_ids,
        parsed_jobs=enumerated_job_ids,
        missing_machines=missing_machines,
        missing_jobs=missing_jobs,
        machine_coverage=machine_coverage,
        job_coverage=job_coverage,
    )


def assess_coverage(ids: ExplicitIds, factory: FactoryConfig) -> CoverageReport:
    """
    Assess coverage of explicit IDs against a parsed FactoryConfig.

    Pure function: no logging, no LLM calls, deterministic.

    Coverage ratio calculation:
    - If no detected IDs of a type, coverage = 1.0 (nothing to cover)
    - Else: coverage = |parsed ∩ detected| / |detected|

    Args:
        ids: ExplicitIds from stage-0 extraction (detected from text)
        factory: FactoryConfig from stage-3 normalization (parsed entities)

    Returns:
        CoverageReport with detected/parsed/missing IDs and coverage ratios
    """
    # Get parsed machine and job IDs from factory
    parsed_machines = {m.id for m in factory.machines}
    parsed_jobs = {j.id for j in factory.jobs}

    # Compute missing IDs
    missing_machines = ids.machine_ids - parsed_machines
    missing_jobs = ids.job_ids - parsed_jobs

    # Compute coverage ratios
    if ids.machine_ids:
        machine_coverage = len(parsed_machines & ids.machine_ids) / len(ids.machine_ids)
    else:
        machine_coverage = 1.0  # Nothing to cover

    if ids.job_ids:
        job_coverage = len(parsed_jobs & ids.job_ids) / len(ids.job_ids)
    else:
        job_coverage = 1.0  # Nothing to cover

    return CoverageReport(
        detected_machines=ids.machine_ids,
        detected_jobs=ids.job_ids,
        parsed_machines=parsed_machines,
        parsed_jobs=parsed_jobs,
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


def validate_and_normalize(raw: RawFactoryConfig) -> FactoryConfig:
    """
    Normalize RawFactoryConfig to a strict FactoryConfig and enforce invariants.

    This is the normalization gate that bridges permissive LLM output (RawFactoryConfig)
    to the strict canonical structure (FactoryConfig). It performs:
    1. Calls normalize_factory() to repair durations, due times, and references
    2. Enforces: no jobs silently dropped during normalization
    3. Enforces: every job has at least one step
    4. Enforces: every step references an existing machine
    5. Enforces: durations and due times are in valid ranges
    6. Enforces: no duplicate IDs in output

    All invariant violations raise ExtractionError. No partial output or fallbacks.

    Args:
        raw: RawFactoryConfig from LLM extraction (permissive DTO)

    Returns:
        FactoryConfig: normalized, structurally sound factory configuration

    Raises:
        ExtractionError: if any invariant is violated (hard fail, no partial output)
    """
    # Convert RawFactoryConfig to FactoryConfig format for normalization
    # Map raw steps/jobs to canonical Step/Job/Machine types
    raw_machines = [Machine(id=m.id, name=m.name) for m in raw.machines]
    raw_jobs = [
        Job(
            id=j.id,
            name=j.name,
            steps=[Step(machine_id=s.machine_id, duration_hours=int(s.duration_hours)) for s in j.steps],
            due_time_hour=int(j.due_time_hour) if j.due_time_hour is not None else 24,
        )
        for j in raw.jobs
    ]
    raw_factory = FactoryConfig(machines=raw_machines, jobs=raw_jobs)

    # Store raw job IDs before normalization
    raw_job_ids = {j.id for j in raw.jobs}

    # Call normalize_factory to repair durations, due times, and invalid references
    normalized_factory, _warnings = normalize_factory(raw_factory)

    # Get normalized job IDs
    normalized_job_ids = {j.id for j in normalized_factory.jobs}
    normalized_machine_ids = {m.id for m in normalized_factory.machines}

    # ========== INVARIANT 1: No jobs silently dropped ==========
    if normalized_job_ids != raw_job_ids:
        missing_jobs = raw_job_ids - normalized_job_ids
        raise ExtractionError(
            code="NORMALIZATION_FAILED",
            message=f"Jobs were lost during normalization: {sorted(missing_jobs)}",
            details={
                "raw_job_ids": sorted(raw_job_ids),
                "normalized_job_ids": sorted(normalized_job_ids),
                "missing_job_ids": sorted(missing_jobs),
            },
        )

    # ========== INVARIANT 2: Every job has at least one step ==========
    for job in normalized_factory.jobs:
        if len(job.steps) == 0:
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message=f"Job {job.id} has no steps",
                details={"job_id": job.id, "steps_count": 0},
            )

    # ========== INVARIANT 3: Every step references an existing machine ==========
    for job in normalized_factory.jobs:
        for step in job.steps:
            if step.machine_id not in normalized_machine_ids:
                raise ExtractionError(
                    code="INVALID_STRUCTURE",
                    message=f"Step in job {job.id} references non-existent machine {step.machine_id}",
                    details={
                        "job_id": job.id,
                        "step_machine_id": step.machine_id,
                        "available_machines": sorted(normalized_machine_ids),
                    },
                )

    # ========== INVARIANT 4: Durations and due times are in valid ranges ==========
    for job in normalized_factory.jobs:
        # Check job due_time_hour
        if not isinstance(job.due_time_hour, int) or job.due_time_hour < 0 or job.due_time_hour > 24:
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message=f"Job {job.id} has invalid due_time_hour: {job.due_time_hour}",
                details={
                    "job_id": job.id,
                    "due_time_hour": job.due_time_hour,
                    "valid_range": "0-24",
                },
            )

        # Check step durations
        for i, step in enumerate(job.steps):
            if not isinstance(step.duration_hours, int) or step.duration_hours < 1:
                raise ExtractionError(
                    code="INVALID_STRUCTURE",
                    message=f"Step {i} in job {job.id} has invalid duration_hours: {step.duration_hours}",
                    details={
                        "job_id": job.id,
                        "step_index": i,
                        "duration_hours": step.duration_hours,
                        "valid_range": ">= 1",
                    },
                )

    # ========== INVARIANT 5: No duplicate IDs ==========
    machine_ids_list = [m.id for m in normalized_factory.machines]
    if len(machine_ids_list) != len(set(machine_ids_list)):
        duplicates = [mid for mid in set(machine_ids_list) if machine_ids_list.count(mid) > 1]
        raise ExtractionError(
            code="INVALID_STRUCTURE",
            message=f"Duplicate machine IDs: {duplicates}",
            details={"duplicate_machine_ids": duplicates},
        )

    job_ids_list = [j.id for j in normalized_factory.jobs]
    if len(job_ids_list) != len(set(job_ids_list)):
        duplicates = [jid for jid in set(job_ids_list) if job_ids_list.count(jid) > 1]
        raise ExtractionError(
            code="INVALID_STRUCTURE",
            message=f"Duplicate job IDs: {duplicates}",
            details={"duplicate_job_ids": duplicates},
        )

    # All invariants passed, return normalized factory
    return normalized_factory


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
