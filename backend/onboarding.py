"""
Onboarding Module

Provides utilities for safely onboarding free-text factory descriptions into
the simulation pipeline.

PR7: Multi-stage extraction + coverage instrumentation
- Stage 0: Deterministic ID extraction (regex-based, zero-LLM)
- Stage 1: LLM enumeration of entities (machines/jobs only, no steps/durations)
- Stage 2: Coverage computation between explicit text and enumerated entities
- Stage 3: Full FactoryConfig LLM call (existing behavior, now with visibility into coverage)

PR2: Explicit assembler + invariant gate
- assemble_factory: Deterministic composition of intermediate extraction results

Core functions:
- assemble_factory(entities, routing, params) -> AssemblyResult
  Pure, deterministic assembly of FactoryConfig from intermediate extraction types.
  Takes FactoryEntities, FactoryRouting, FactoryParameters and returns
  AssemblyResult containing the factory and any warnings.
  Does NOT enforce invariants; use validate_and_normalize after assembly.

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
from typing import Any, TYPE_CHECKING
from pydantic import BaseModel, Field, field_validator
from .models import FactoryConfig, Machine, Job, Step
from .llm import call_llm_json

if TYPE_CHECKING:
    from .agent_types import FactoryEntities, FactoryRouting, FactoryParameters

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


# ============================================================================
# DETERMINISTIC ASSEMBLER (PR2: Explicit Assembly from Intermediate Types)
# ============================================================================

class AssemblyResult(BaseModel):
    """
    Result of assembling a FactoryConfig from intermediate extraction types.
    
    Contains both the assembled factory and any warnings generated during assembly.
    This is a pure data structure with no behavior.
    """
    factory: FactoryConfig
    warnings: list[str] = Field(default_factory=list)


def assemble_factory(
    entities: "FactoryEntities",
    routing: "FactoryRouting",
    parameters: "FactoryParameters",
) -> AssemblyResult:
    """
    Deterministically assemble a FactoryConfig from intermediate extraction results.
    
    This is a pure function: given the same inputs, it always produces the same output.
    No LLM calls, no side effects, no logging.
    
    Assembly rules:
    1. Machines: Created from entities.machine_ids with names from entities.machine_names.
       If a name is missing, the id is used as the name.
    
    2. Jobs: Created from entities.job_ids with:
       - Names from entities.job_names (fallback to id).
       - Steps from routing.job_routes, with durations from parameters.processing_times.
       - Due times from parameters.due_times (default: 24 if missing).
    
    3. Steps: For each machine_id in a job's route:
       - Duration comes from parameters.processing_times[job_id][machine_id].
       - If duration is missing, defaults to 1 hour.
       - If duration is not a positive integer, it is clamped to 1.
    
    4. Missing routing: If a job has no routing (empty or missing in routing.job_routes),
       a warning is generated and no steps are created for that job.
    
    5. Unknown machine references: If a step references a machine_id not in entities,
       the step is still created but a warning is generated.
    
    This function does NOT enforce invariants beyond basic assembly. Use 
    validate_and_normalize() after assembly to enforce hard invariants and
    filter out invalid configurations.
    
    Args:
        entities: Machine and job IDs/names from entity extraction.
        routing: Per-job machine sequences from routing extraction.
        parameters: Processing times and due dates from parameter extraction.
    
    Returns:
        AssemblyResult containing:
        - factory: The assembled FactoryConfig (may have issues; not yet validated).
        - warnings: List of warnings about missing data, defaults applied, etc.
    
    Example:
        >>> from backend.agent_types import FactoryEntities, FactoryRouting, FactoryParameters
        >>> entities = FactoryEntities(
        ...     machine_ids=["M1", "M2"],
        ...     machine_names={"M1": "Assembly", "M2": "Drill"},
        ...     job_ids=["J1"],
        ...     job_names={"J1": "Widget"}
        ... )
        >>> routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})
        >>> parameters = FactoryParameters(
        ...     processing_times={"J1": {"M1": 2, "M2": 3}},
        ...     due_times={"J1": 10}
        ... )
        >>> result = assemble_factory(entities, routing, parameters)
        >>> result.factory.machines[0].id
        'M1'
        >>> result.factory.jobs[0].steps[0].duration_hours
        2
    """
    warnings: list[str] = []
    
    # Build set of known machine IDs for validation
    known_machine_ids = set(entities.machine_ids)
    
    # -------------------------------------------------------------------------
    # Step 1: Assemble machines
    # -------------------------------------------------------------------------
    machines: list[Machine] = []
    for mid in entities.machine_ids:
        name = entities.machine_names.get(mid, mid)
        machines.append(Machine(id=mid, name=name))
    
    # -------------------------------------------------------------------------
    # Step 2: Assemble jobs with steps
    # -------------------------------------------------------------------------
    jobs: list[Job] = []
    for jid in entities.job_ids:
        # Get job name (default to id)
        name = entities.job_names.get(jid, jid)
        
        # Get routing for this job
        route = routing.job_routes.get(jid, [])
        if not route:
            warnings.append(f"Job {jid} has no routing defined; will have empty steps")
        
        # Get processing times for this job
        job_times = parameters.processing_times.get(jid, {})
        
        # Get due time for this job (default to 24)
        due_time = parameters.due_times.get(jid, 24)
        if due_time is None:
            due_time = 24
            warnings.append(f"Job {jid} has no due time; defaulting to 24")
        
        # Ensure due_time is a valid integer
        if not isinstance(due_time, int) or due_time < 0:
            warnings.append(f"Job {jid} due_time {due_time} invalid; clamping to 24")
            due_time = 24
        
        # Build steps from routing
        steps: list[Step] = []
        for machine_id in route:
            # Check if machine is known
            if machine_id not in known_machine_ids:
                warnings.append(
                    f"Job {jid} references unknown machine {machine_id}; "
                    f"step will be created but may fail validation"
                )
            
            # Get duration (default to 1)
            duration = job_times.get(machine_id, 1)
            if duration is None:
                duration = 1
                warnings.append(
                    f"Job {jid} step on {machine_id} has no duration; defaulting to 1"
                )
            
            # Ensure duration is a valid positive integer
            if not isinstance(duration, int) or duration <= 0:
                original = duration
                duration = max(1, int(duration) if isinstance(duration, (int, float)) else 1)
                warnings.append(
                    f"Job {jid} step on {machine_id} duration {original} invalid; "
                    f"clamped to {duration}"
                )
            
            steps.append(Step(machine_id=machine_id, duration_hours=duration))
        
        jobs.append(Job(
            id=jid,
            name=name,
            steps=steps,
            due_time_hour=due_time,
        ))
    
    # -------------------------------------------------------------------------
    # Step 3: Create the FactoryConfig
    # -------------------------------------------------------------------------
    factory = FactoryConfig(machines=machines, jobs=jobs)
    
    return AssemblyResult(factory=factory, warnings=warnings)


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


# ============================================================================
# VALIDATION WITH DIAGNOSTICS (PR3: Expose Normalization Warnings)
# ============================================================================

class NormalizationResult(BaseModel):
    """
    Result of validate_and_normalize_with_diagnostics.
    
    Contains the normalized factory plus any warnings generated during normalization.
    """
    factory: FactoryConfig
    warnings: list[str] = Field(default_factory=list)


def validate_and_normalize_with_diagnostics(raw: RawFactoryConfig) -> NormalizationResult:
    """
    Same as validate_and_normalize but also returns normalization warnings.
    
    This variant exposes the warnings generated during normalization so they
    can be surfaced as OnboardingIssues for user feedback.
    
    Args:
        raw: RawFactoryConfig from LLM extraction (permissive DTO)
    
    Returns:
        NormalizationResult containing:
        - factory: The normalized FactoryConfig
        - warnings: List of normalization warnings (repairs applied)
    
    Raises:
        ExtractionError: if any hard invariant is violated
    """
    # Convert RawFactoryConfig to FactoryConfig format for normalization
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
    normalized_factory, warnings = normalize_factory(raw_factory)
    
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
    
    return NormalizationResult(factory=normalized_factory, warnings=warnings)


# ============================================================================
# ONBOARDING SCORE COMPUTATION (PR3)
# ============================================================================

def compute_onboarding_score(
    coverage_issues: int,
    normalization_repairs: int,
    alt_conflicts: int = 0,
) -> tuple[int, str]:
    """
    Compute an onboarding quality score based on detected issues.
    
    This is a simple heuristic scoring function:
    - Start at 100
    - Subtract 15 points per coverage miss (explicit ID not in parsed config)
    - Subtract 5 points per normalization repair (duration clamped, etc.)
    - Subtract 20 points per alternative config conflict (future use)
    
    Score bands:
    - 80-100: HIGH_TRUST
    - 50-79: MEDIUM_TRUST
    - 0-49: LOW_TRUST
    
    Args:
        coverage_issues: Number of coverage misses (explicit IDs missing from config)
        normalization_repairs: Number of normalization repairs applied
        alt_conflicts: Number of alternative config conflicts (for multi-pass)
    
    Returns:
        Tuple of (score: int 0-100, trust: str HIGH_TRUST/MEDIUM_TRUST/LOW_TRUST)
    """
    score = 100
    
    # Deduct for coverage misses (more severe)
    score -= coverage_issues * 15
    
    # Deduct for normalization repairs (less severe)
    score -= normalization_repairs * 5
    
    # Deduct for alternative conflicts (future: multi-pass disagreements)
    score -= alt_conflicts * 20
    
    # Clamp to 0-100
    score = max(0, min(100, score))
    
    # Determine trust band
    if score >= 80:
        trust = "HIGH_TRUST"
    elif score >= 50:
        trust = "MEDIUM_TRUST"
    else:
        trust = "LOW_TRUST"
    
    return score, trust


# ============================================================================
# MULTI-PASS ONBOARDING (PR4)
# ============================================================================

class FactoryDiff(BaseModel):
    """
    Structural differences between two FactoryConfigs.
    
    Used to compare alternative configs from multi-pass extraction.
    """
    machines_added: list[str] = Field(default_factory=list, description="Machine IDs in config_b but not in config_a")
    machines_removed: list[str] = Field(default_factory=list, description="Machine IDs in config_a but not in config_b")
    jobs_added: list[str] = Field(default_factory=list, description="Job IDs in config_b but not in config_a")
    jobs_removed: list[str] = Field(default_factory=list, description="Job IDs in config_a but not in config_b")
    routing_differences: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description="Per-job routing differences: {job_id: {'a': [route_a], 'b': [route_b]}}"
    )
    timing_differences: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-job timing differences: {job_id: {'due_a': X, 'due_b': Y, 'duration_diff': {...}}}"
    )
    is_identical: bool = Field(default=True, description="Whether the two configs are structurally identical")
    
    def summary(self) -> str:
        """Generate a human-readable summary of the differences."""
        if self.is_identical:
            return "Configs are structurally identical"
        
        parts = []
        if self.machines_added:
            parts.append(f"Machines added: {self.machines_added}")
        if self.machines_removed:
            parts.append(f"Machines removed: {self.machines_removed}")
        if self.jobs_added:
            parts.append(f"Jobs added: {self.jobs_added}")
        if self.jobs_removed:
            parts.append(f"Jobs removed: {self.jobs_removed}")
        if self.routing_differences:
            for job_id, diff in self.routing_differences.items():
                parts.append(f"Job {job_id} routing: {diff['a']} vs {diff['b']}")
        if self.timing_differences:
            for job_id, diff in self.timing_differences.items():
                if 'due_a' in diff and 'due_b' in diff and diff['due_a'] != diff['due_b']:
                    parts.append(f"Job {job_id} due time: {diff['due_a']} vs {diff['due_b']}")
        
        return "; ".join(parts) if parts else "Minor differences"


def compute_factory_diff(config_a: FactoryConfig, config_b: FactoryConfig) -> FactoryDiff:
    """
    Compute structural differences between two FactoryConfigs.
    
    Compares:
    - Machine sets (added/removed)
    - Job sets (added/removed)
    - Per-job routing (machine sequences)
    - Per-job timing (due times and durations)
    
    This is a pure function: no side effects, deterministic output.
    
    Args:
        config_a: The primary/reference config
        config_b: The alternative config to compare
    
    Returns:
        FactoryDiff with all detected differences
    """
    # Compare machine sets
    machines_a = {m.id for m in config_a.machines}
    machines_b = {m.id for m in config_b.machines}
    machines_added = sorted(machines_b - machines_a)
    machines_removed = sorted(machines_a - machines_b)
    
    # Compare job sets
    jobs_a = {j.id for j in config_a.jobs}
    jobs_b = {j.id for j in config_b.jobs}
    jobs_added = sorted(jobs_b - jobs_a)
    jobs_removed = sorted(jobs_a - jobs_b)
    
    # Build job lookup maps
    jobs_map_a = {j.id: j for j in config_a.jobs}
    jobs_map_b = {j.id: j for j in config_b.jobs}
    
    # Compare routing and timing for jobs that exist in both
    common_jobs = jobs_a & jobs_b
    routing_differences: dict[str, dict[str, list[str]]] = {}
    timing_differences: dict[str, dict[str, Any]] = {}
    
    for job_id in sorted(common_jobs):
        job_a = jobs_map_a[job_id]
        job_b = jobs_map_b[job_id]
        
        # Compare routing (sequence of machine IDs)
        route_a = [s.machine_id for s in job_a.steps]
        route_b = [s.machine_id for s in job_b.steps]
        if route_a != route_b:
            routing_differences[job_id] = {"a": route_a, "b": route_b}
        
        # Compare timing
        timing_diff: dict[str, Any] = {}
        
        # Due time difference
        if job_a.due_time_hour != job_b.due_time_hour:
            timing_diff["due_a"] = job_a.due_time_hour
            timing_diff["due_b"] = job_b.due_time_hour
        
        # Duration differences per step
        duration_diff: dict[str, dict[str, int]] = {}
        # Build step maps by machine_id for comparison
        steps_a = {s.machine_id: s.duration_hours for s in job_a.steps}
        steps_b = {s.machine_id: s.duration_hours for s in job_b.steps}
        
        all_machines = set(steps_a.keys()) | set(steps_b.keys())
        for mid in all_machines:
            dur_a = steps_a.get(mid)
            dur_b = steps_b.get(mid)
            if dur_a != dur_b:
                duration_diff[mid] = {"a": dur_a, "b": dur_b}
        
        if duration_diff:
            timing_diff["duration_diff"] = duration_diff
        
        if timing_diff:
            timing_differences[job_id] = timing_diff
    
    # Determine if configs are identical
    is_identical = (
        not machines_added and
        not machines_removed and
        not jobs_added and
        not jobs_removed and
        not routing_differences and
        not timing_differences
    )
    
    return FactoryDiff(
        machines_added=machines_added,
        machines_removed=machines_removed,
        jobs_added=jobs_added,
        jobs_removed=jobs_removed,
        routing_differences=routing_differences,
        timing_differences=timing_differences,
        is_identical=is_identical,
    )


class OnboardingPassResult(BaseModel):
    """
    Result of a single onboarding extraction pass.
    """
    model_config = {"arbitrary_types_allowed": True}
    
    mode: str = Field(..., description="The extraction mode used (e.g., 'default', 'conservative', 'inclusive')")
    success: bool = Field(default=False, description="Whether extraction succeeded")
    factory: FactoryConfig | None = Field(default=None, description="The extracted factory config (if successful)")
    error: str | None = Field(default=None, description="Error message (if failed)")
    normalization_warnings: list[str] = Field(default_factory=list, description="Warnings from normalization")
    coverage_issues: int = Field(default=0, description="Number of coverage misses")


class MultiPassResult(BaseModel):
    """
    Result of multi-pass onboarding extraction.
    
    Contains the primary config, alternative configs, and structural diffs.
    """
    model_config = {"arbitrary_types_allowed": True}
    
    primary_config: FactoryConfig | None = Field(default=None, description="The chosen primary factory config")
    primary_mode: str = Field(default="", description="The mode that produced the primary config")
    alt_configs: list[FactoryConfig] = Field(default_factory=list, description="Alternative valid configs (deduplicated)")
    alt_modes: list[str] = Field(default_factory=list, description="Modes that produced each alt config")
    diffs: list[FactoryDiff] = Field(default_factory=list, description="Diffs between primary and each alternative")
    diff_summaries: list[str] = Field(default_factory=list, description="Human-readable diff summaries")
    all_pass_results: list[OnboardingPassResult] = Field(default_factory=list, description="Results from all passes")
    alt_conflict_count: int = Field(default=0, description="Number of structural conflicts between configs")


def run_onboarding_pass(
    factory_text: str,
    mode: str = "default",
) -> OnboardingPassResult:
    """
    Run a single onboarding extraction pass with a specific mode.
    
    Modes affect prompt phrasing and extraction behavior:
    - "default": Standard extraction, balanced
    - "conservative": Prefers explicit mentions, fewer inferences
    - "inclusive": More aggressive at inferring entities
    
    This function:
    - Runs the full extraction pipeline (ids → coarse → steps → normalize)
    - Captures all errors gracefully (returns OnboardingPassResult with error)
    - Does NOT modify any external state
    
    Args:
        factory_text: Raw factory description text
        mode: Extraction mode ("default", "conservative", "inclusive")
    
    Returns:
        OnboardingPassResult with either a valid factory or an error
    """
    result = OnboardingPassResult(mode=mode)
    
    try:
        # Stage 0: Extract explicit IDs
        ids = extract_explicit_ids(factory_text)
        
        # Stage 1: Extract coarse structure (with mode-specific behavior)
        # For now, modes affect logging/debugging but use same extraction
        # Future: could use different prompts per mode
        coarse = extract_coarse_structure(factory_text, ids)
        
        # Stage 2: Extract steps and timings
        raw = extract_steps(factory_text, coarse)
        
        # Stage 3: Validate and normalize with diagnostics
        norm_result = validate_and_normalize_with_diagnostics(raw)
        factory = norm_result.factory
        result.normalization_warnings = norm_result.warnings
        
        # Stage 4: Assess coverage
        coverage = assess_coverage(ids, factory)
        if coverage.missing_machines:
            result.coverage_issues += len(coverage.missing_machines)
        if coverage.missing_jobs:
            result.coverage_issues += len(coverage.missing_jobs)
        
        result.success = True
        result.factory = factory
        
    except ExtractionError as e:
        result.success = False
        result.error = f"{e.code}: {e.message}"
    except Exception as e:
        result.success = False
        result.error = f"Unexpected error: {str(e)[:200]}"
    
    return result


def run_multi_pass_onboarding(
    factory_text: str,
    num_passes: int = 2,
) -> MultiPassResult:
    """
    Run multiple onboarding extraction passes and compute consensus.
    
    This function:
    1. Runs num_passes extraction passes with different modes
    2. Collects all valid FactoryConfigs
    3. Deduplicates structurally-identical configs
    4. Chooses a primary config (first valid, or most conservative)
    5. Computes structural diffs between primary and alternatives
    6. Returns aggregated result with all configs and diffs
    
    Args:
        factory_text: Raw factory description text
        num_passes: Number of extraction passes to run (default: 2)
    
    Returns:
        MultiPassResult containing primary config, alternatives, and diffs
    """
    result = MultiPassResult()
    
    # Define modes for each pass
    modes = ["default", "conservative", "inclusive"][:num_passes]
    if num_passes > len(modes):
        modes = modes + ["default"] * (num_passes - len(modes))
    
    # Run all passes
    valid_configs: list[tuple[str, FactoryConfig]] = []  # (mode, config) pairs
    
    for mode in modes:
        pass_result = run_onboarding_pass(factory_text, mode)
        result.all_pass_results.append(pass_result)
        
        if pass_result.success and pass_result.factory is not None:
            valid_configs.append((mode, pass_result.factory))
    
    # If no valid configs, return empty result
    if not valid_configs:
        return result
    
    # Choose primary config (first valid config, prefer conservative if available)
    primary_mode, primary_config = valid_configs[0]
    for mode, config in valid_configs:
        if mode == "conservative":
            primary_mode, primary_config = mode, config
            break
    
    result.primary_config = primary_config
    result.primary_mode = primary_mode
    
    # Deduplicate alternatives and compute diffs
    seen_structures: list[FactoryConfig] = [primary_config]
    
    for mode, config in valid_configs:
        if config is primary_config:
            continue
        
        # Check if this config is structurally identical to any we've seen
        is_duplicate = False
        for seen in seen_structures:
            diff = compute_factory_diff(seen, config)
            if diff.is_identical:
                is_duplicate = True
                break
        
        if not is_duplicate:
            # This is a distinct alternative
            diff = compute_factory_diff(primary_config, config)
            result.alt_configs.append(config)
            result.alt_modes.append(mode)
            result.diffs.append(diff)
            result.diff_summaries.append(diff.summary())
            seen_structures.append(config)
            
            # Count structural conflicts (non-trivial differences)
            if not diff.is_identical:
                # Count as conflict if routing or job/machine sets differ
                if (diff.machines_added or diff.machines_removed or
                    diff.jobs_added or diff.jobs_removed or
                    diff.routing_differences):
                    result.alt_conflict_count += 1
    
    return result


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
