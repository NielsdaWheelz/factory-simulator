"""
Agentic Interpretation Layer

This module defines LLM-backed and stub agents that form the agentic boundaries:

1. OnboardingAgent: Maps free-text factory description to a FactoryConfig
   - Input: factory_text (free-form user description)
   - Output: FactoryConfig
   - In PR1: stub that returns build_toy_factory() (no LLM yet)

2. IntentAgent: Maps free-form user text to a ScenarioSpec
   - Input: user text
   - Output: ScenarioSpec
   - Uses LLM with fallback to BASELINE on error

3. FuturesAgent: Expands a ScenarioSpec into a list of candidate scenarios
   - Input: ScenarioSpec
   - Output: list[ScenarioSpec]
   - Uses LLM with fallback to [spec] on error

4. BriefingAgent: Translates ScenarioMetrics to markdown summary
   - Input: ScenarioMetrics, optional context string
   - Output: markdown string
   - Uses LLM with fallback to deterministic template on error

All agents except OnboardingAgent call llm.call_llm_json for LLM communication.
Tests will monkeypatch call_llm_json to avoid real network calls.
"""

import logging
from typing import Iterable, Optional
from pydantic import BaseModel

from .models import ScenarioSpec, ScenarioType, ScenarioMetrics, FactoryConfig
from .world import build_toy_factory
from .llm import call_llm_json

logger = logging.getLogger(__name__)


class OnboardingAgent:
    """LLM-backed agent for factory description parsing.

    Takes a free-text factory description and interprets it into a FactoryConfig
    using an LLM. Falls back gracefully to toy factory on any error.

    Prompt includes:
    - Time interpretation rules (by 10am → 10, etc.)
    - Inference envelope (what's allowed/forbidden)
    - Schema definition and example
    - Explicit instructions for JSON output

    Error handling: Never throws. Catches all exceptions and returns toy factory.
    """

    def run(self, factory_text: str) -> FactoryConfig:
        """
        Parse factory text into a FactoryConfig using LLM.

        Happy path:
        - Calls call_llm_json with a carefully designed prompt
        - Returns the LLM-produced FactoryConfig

        On any error:
        - Logs the error with truncated factory_text and error details
        - Returns build_toy_factory() as fallback
        - Does not raise

        Args:
            factory_text: Free-form factory description

        Returns:
            FactoryConfig (from LLM on success, toy factory on error)
        """
        # Log input
        preview = factory_text[:200] if factory_text else "(empty)"
        logger.debug(f"OnboardingAgent: received factory_text len={len(factory_text)}, preview={preview}...")

        try:
            # Build prompt
            prompt = self._build_prompt(factory_text)

            # Call LLM
            cfg = call_llm_json(prompt, FactoryConfig)

            # Log success
            total_steps = sum(len(job.steps) for job in cfg.jobs)
            logger.debug(
                f"OnboardingAgent: produced factory with {len(cfg.machines)} machines, "
                f"{len(cfg.jobs)} jobs, {total_steps} total steps"
            )

            return cfg

        except Exception as e:
            # Log error and return fallback
            logger.warning(
                f"OnboardingAgent: LLM call failed, falling back to toy factory: {type(e).__name__}: {str(e)[:100]}"
            )
            return build_toy_factory()

    def _build_prompt(self, factory_text: str) -> str:
        """
        Build a robust, comprehensive prompt for the LLM to produce stable FactoryConfig objects.

        Structure:
        1. Role and guardrails
        2. Hard schema definition with field descriptions
        3. Comprehensive time/duration interpretation rules with examples
        4. Size limits and demo constraints
        5. Inference envelope (allowed vs forbidden)
        6. ID generation rules for consistency
        7. Step ordering and sequencing rules
        8. Four worked examples (clean, messy, contradiction, forbidden features)
        9. Explicit output rules and validation
        10. Final constraint summary

        Args:
            factory_text: Free-form factory description from user

        Returns:
            Full prompt ready for LLM
        """
        prompt = """You are a factory description parser. Your job is to interpret free-text descriptions
of factories and extract a structured FactoryConfig.

You will output ONLY valid JSON. No markdown, no prose, no explanation, no comments.

================================================================================
# ROLE & GUARDRAILS
================================================================================

You are conservative and deterministic. When uncertain, you:
1. Pick the simplest interpretation that fits the schema
2. Use defaults rather than guess missing values
3. Drop incomplete or ambiguous constructs
4. Prefer under-modeling to over-modeling

================================================================================
# SCHEMA DEFINITION (Required Output Structure)
================================================================================

You MUST output this exact structure:

{
  "machines": [
    {
      "id": "string (e.g., 'M1', 'M2', or descriptive: 'M_ASSEMBLY', 'M_DRILL')",
      "name": "string (human-readable name from text)"
    }
  ],
  "jobs": [
    {
      "id": "string (e.g., 'J1', 'J2', or descriptive: 'J_WIDGET_A')",
      "name": "string (human-readable name from text)",
      "steps": [
        {
          "machine_id": "string (MUST match some machine.id exactly)",
          "duration_hours": "integer >= 1 (hours)"
        }
      ],
      "due_time_hour": "integer (hour 0-24, or slightly beyond if explicit)"
    }
  ]
}

Notes on schema:
- machines.id: Must be unique. Use M1, M2, M3... or descriptive IDs like M_ASSEMBLY.
- machines.name: Human-readable name from the text.
- jobs.id: Must be unique. Use J1, J2, J3... or descriptive IDs like J_WIDGET_A.
- jobs.name: Human-readable name from the text.
- steps: Ordered list. Each step references a machine.id that exists.
- duration_hours: Must be >= 1 (integer). Never 0 or negative.
- due_time_hour: Integer representing hour of day. 24 = end of day. Default = 24.

================================================================================
# TIME INTERPRETATION RULES (MANDATORY - Apply Deterministically)
================================================================================

When you see time expressions, apply these rules EXACTLY:

### DUE TIMES (must be integers)
"by 10am" or "10am" or "due 10am"              → 10
"by noon" or "noon" or "12pm" or "midday"      → 12
"by 3pm" or "3pm"                              → 15
"by 4:30pm" or "4:30pm"                        → 4 (round down, conservative)
"end of day" or "EOD" or "close" or "by close" → 24
"by tomorrow" or "next day"                    → Ignore (multi-day forbidden; use 24)
"ASAP" or "urgent" with no time                → 24 (unless explicitly earlier time given)
Missing due time (no deadline mentioned)       → 24 (default: end of day)
Negative due time (e.g., "-5")                 → 0 or 24 (per context; default 24)
"by 30 hours"                                  → 30 (if hours are explicit, use as-is)

### DURATIONS (must be integers >= 1)
"5 hours" or "5h" or "5 hrs"           → 5
"about 3 hours" or "~3h" or "roughly 3" → 3 (round down; conservative)
"3-4 hours" or "3 to 4 hours" or "3–4h" → 3 (take lower bound; conservative)
"quick" or "fast" or "short"           → 1 (minimum viable duration)
"lengthy" or "long" or "slow"          → 3 (context-dependent; infer conservatively)
"a couple hours"                       → 2
"half hour" or "0.5h"                  → 1 (round up; no sub-hour durations)
Missing duration                       → 1 (default: minimum viable)
Zero or negative duration              → 1 (clamp upward)

RULE: Always round durations DOWN or UP to integers >= 1. Never output 0 or fractional durations.

================================================================================
# SIZE LIMITS (Demo Constraints)
================================================================================

Enforce these hard caps:
- Machines: 1-10 maximum (typical: 3-5)
- Jobs: 1-15 maximum (typical: 3-5)
- Steps per job: 1-8 maximum (typical: 2-4)
- Duration per step: 1-24 hours (typical: 1-6)
- Due time: 1-30 hours (typical: 8-24)

If the description implies more machines or jobs, IGNORE the excess and model only
the first 10 machines and first 15 jobs mentioned. Prioritize clarity and consistency.

================================================================================
# INFERENCE ENVELOPE (Allowed vs Forbidden)
================================================================================

### ALLOWED (infer freely within these bounds)
✓ Infer machine IDs from names (e.g., "Assembly line" → M1 or M_ASSEMBLY)
✓ Infer job IDs from names or references (e.g., "Widget A" → J1 or J_WIDGET_A)
✓ Infer step durations using the rules above (missing → default 1)
✓ Infer due times using the rules above (missing → default 24)
✓ Infer job routing (step sequence) from text order
✓ Map the same machine name to the same ID consistently
✓ Fill missing fields with defaults
✓ Interpret vague durations conservatively (e.g., "quick" → 1)

### FORBIDDEN (DO NOT infer; ignore these constructs completely)
✗ Parallel steps or branching within a job (e.g., "then do A or B")
✗ Multi-day schedules or rolling horizons (e.g., "Monday, then Tuesday")
✗ Quantities, batch sizes, material flow (e.g., "100 units")
✗ Costs, labor, resource pools (e.g., "2 operators")
✗ Setup times or machine reconfiguration (e.g., "30min setup")
✗ Machine parallelism or duplicate instances (e.g., "two Drill machines")
✗ Job dependencies beyond sequential steps (e.g., "Job B starts after Job A ends")
✗ External constraints (e.g., "power cuts at 6pm")
✗ Batching, queueing, or variability (e.g., "batch sizes vary")

If the text contains forbidden constructs, IGNORE them completely. Model only what fits.

================================================================================
# ID GENERATION RULES
================================================================================

Machine IDs:
- Prefer simple numeric IDs: M1, M2, M3, ... (simplest, clearest)
- OR descriptive: M_ASSEMBLY, M_DRILL, M_PACK (if text strongly supports)
- MUST be unique per factory
- DO NOT invent machine IDs not grounded in the text

Job IDs:
- Prefer simple numeric IDs: J1, J2, J3, ... (simplest, clearest)
- OR descriptive: J_WIDGET_A, J_GADGET_B (if text strongly supports)
- MUST be unique per factory
- DO NOT invent job IDs not grounded in the text

Consistency: If you assign M1 to "Assembly" the first time, use M1 for Assembly every time.
Same for jobs. Map names → IDs deterministically.

================================================================================
# STEP ORDERING & SEQUENCING RULES
================================================================================

1. Steps are ordered (first step listed is first to execute).
2. No branching. No "Job A can do Step 1 OR Step 2". Always pick ONE sequence.
3. No parallel steps. "Assembly → Drill AND Pack" is forbidden. Use "Assembly → Drill → Pack".
4. No job dependencies. Each job's steps are independent of other jobs.
5. All step.machine_id values MUST reference existing machines.
6. Drop incomplete steps (machine_id not found) entirely; warn user.
7. Never reorder steps unless the text explicitly shows the order.

================================================================================
# EXAMPLE A: Clean Factory Description
================================================================================

Input:
"We operate 3 machines: Assembly (A), Drill (D), and Pack (P).
Two jobs: Widget-A requires A(2h) → D(3h) → P(1h), due by noon.
Gadget-B requires A(1h) → D(2h), due at 3pm."

Output:
{
  "machines": [
    {"id": "M1", "name": "Assembly"},
    {"id": "M2", "name": "Drill"},
    {"id": "M3", "name": "Pack"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Widget-A",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2},
        {"machine_id": "M2", "duration_hours": 3},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 12
    },
    {
      "id": "J2",
      "name": "Gadget-B",
      "steps": [
        {"machine_id": "M1", "duration_hours": 1},
        {"machine_id": "M2", "duration_hours": 2}
      ],
      "due_time_hour": 15
    }
  ]
}

Why this works:
- All machine names and job names extracted cleanly.
- All durations explicit and integer.
- All due times interpreted from clock times.
- Schema compliance.

================================================================================
# EXAMPLE B: Messy SOP (Standard Operating Procedure)
================================================================================

Input:
"SOP v3.2 (outdated): We have Assem (old ~1-2 hrs), Drill/Mill bottleneck (quick 2h or more like 4h, depends),
Packing (fast or slow, 1-3h really). Three orders: Widget goes Assem→Drill→Pack by noon (approx).
Gadget goes Assem→Drill by 2-3pm (or maybe 4). Part? Unknown route, maybe Drill→Pack, due EOD.
Note: This procedure is from 2023, some machines offline next week (ignore this)."

Output (conservative & deterministic):
{
  "machines": [
    {"id": "M1", "name": "Assem"},
    {"id": "M2", "name": "Drill/Mill"},
    {"id": "M3", "name": "Packing"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Widget",
      "steps": [
        {"machine_id": "M1", "duration_hours": 1},
        {"machine_id": "M2", "duration_hours": 2},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 12
    },
    {
      "id": "J2",
      "name": "Gadget",
      "steps": [
        {"machine_id": "M1", "duration_hours": 1},
        {"machine_id": "M2", "duration_hours": 2}
      ],
      "due_time_hour": 14
    },
    {
      "id": "J3",
      "name": "Part",
      "steps": [
        {"machine_id": "M2", "duration_hours": 1},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 24
    }
  ]
}

Why this is conservative:
- "~1-2h" Assem → 1 (lower bound)
- "2h or 4h" Drill → 2 (lower bound; conservative)
- "fast or slow, 1-3h" Pack → 1 (lower bound)
- "2-3pm or maybe 4" Gadget → 14 (lower bound; 2pm = 14)
- "unknown route" Part → infer Drill→Pack (only path matching schema)
- "machines offline next week" → ignored (multi-day forbidden)
- All vague language resolved conservatively

================================================================================
# EXAMPLE C: Contradiction → Conservative Resolution
================================================================================

Input:
"Machine Drill can process parts in 2 hours. But it's slow, takes 6 hours usually.
Widget goes Assembly(quick) → Drill(fast) → Pack, due 'around noon, maybe 1pm'.
Gadget goes Assembly → Drill, due 'definitely not past 10am, or maybe 2pm?'"

Output (picking simplest consistent interpretation):
{
  "machines": [
    {"id": "M1", "name": "Assembly"},
    {"id": "M2", "name": "Drill"},
    {"id": "M3", "name": "Pack"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Widget",
      "steps": [
        {"machine_id": "M1", "duration_hours": 1},
        {"machine_id": "M2", "duration_hours": 2},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 12
    },
    {
      "id": "J2",
      "name": "Gadget",
      "steps": [
        {"machine_id": "M1", "duration_hours": 1},
        {"machine_id": "M2", "duration_hours": 2}
      ],
      "due_time_hour": 10
    }
  ]
}

Resolution rules applied:
- Drill duration: "2 hours" (explicit) is preferred over vague "usually 6h". Use 2.
- "quick" Assembly → 1 (default for vague)
- "fast" Drill → 1, but then we see "2 hours" → use 2 (explicit wins)
- Widget due time: "around noon, maybe 1pm" → 12 (12pm/noon, lower bound)
- Gadget due time: "definitely not past 10am" wins over "maybe 2pm" (explicit constraint → 10)
- Pack duration: missing → 1 (default)

================================================================================
# EXAMPLE D: Forbidden Features → Ignore
================================================================================

Input:
"We make Widgets in two parallel paths:
Path A: Assembly (2h) → Drill (3h) → Pack (1h)
Path B: Assembly (2h) → Hardening (2h) → Pack (1h)
Gadgets go one of: Drill OR Hardening, then Pack (2h), due 4pm.
We process batches of 10 units each. On Mondays we double-speed all machines.
Setup times are typically 30min per job. Machine downtime is Wednesdays."

Output (ignoring all forbidden constructs):
{
  "machines": [
    {"id": "M1", "name": "Assembly"},
    {"id": "M2", "name": "Drill"},
    {"id": "M3", "name": "Pack"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Widget",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2},
        {"machine_id": "M2", "duration_hours": 3},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 24
    },
    {
      "id": "J2",
      "name": "Gadget",
      "steps": [
        {"machine_id": "M2", "duration_hours": 1},
        {"machine_id": "M3", "duration_hours": 2}
      ],
      "due_time_hour": 16
    }
  ]
}

Ignored constructs:
- Parallel paths (Path A / Path B): Forbidden. Picked Path A (first mentioned).
- Branching ("one of: Drill OR Hardening"): Forbidden. Picked Drill (first option).
- "Hardening" machine: Not in Path A, so not included. (Path A has Assembly, Drill, Pack.)
- Batch sizes (10 units): Forbidden. Ignored.
- Multi-day rules ("Mondays", "double-speed", "Wednesdays"): Forbidden. Ignored.
- Setup times (30min): Forbidden. Ignored.
- "Gadget due 4pm": 16. Gadgets lack explicit due time in description, so 24 default used
  (or if we extract "4pm" from context, that's 16).

Key point: We modeled only what fits the sequential, deterministic schema.

================================================================================
# HARD CONSTRAINTS (Final Checklist)
================================================================================

Before outputting JSON, ensure:

1. All machines have unique IDs
2. All jobs have unique IDs
3. All job steps reference existing machine IDs
4. No machines have duplicate names
5. No jobs have duplicate names
6. All durations are integers >= 1
7. All due times are integers (typically 1-30)
8. No branching in job steps (single linear sequence per job)
9. No parallelism (no "and" in step routing; use →)
10. No forbidden constructs (parallel ops, multi-day, batching, setup, resources, etc.)
11. Machine count: 1-10
12. Job count: 1-15
13. Steps per job: 1-8
14. JSON is valid and matches schema exactly
15. If unclear, use defaults: duration=1, due_time=24

If a constraint is violated, fix it by:
- Dropping the offending job/step entirely
- Filling missing values with defaults
- Picking the simplest interpretation

================================================================================
# OUTPUT INSTRUCTION
================================================================================

Respond with ONLY the JSON object. No markdown, no backticks, no prose, no comments.

Valid output example:
{"machines": [...], "jobs": [...]}

INVALID output examples (do NOT use these):
- json\n{...}\n```
- "// This is a comment" (no comments in JSON)
- "machines": [...] // TODO (no comments)
- Explanation before the JSON
- Multiple JSON objects

Output raw, valid JSON only.

================================================================================
# USER FACTORY DESCRIPTION
================================================================================

{factory_text}

================================================================================
# OUTPUT (JSON ONLY)
================================================================================
"""
        return prompt


def normalize_scenario_spec(spec: ScenarioSpec, factory: FactoryConfig) -> ScenarioSpec:
    """
    Apply small, conservative corrections to an LLM-produced ScenarioSpec.

    Rules:
    - If scenario_type == M2_SLOWDOWN:
        - force rush_job_id = None
    - If scenario_type == RUSH_ARRIVES:
        - if rush_job_id is not one of the known job IDs in factory.jobs,
          fall back to BASELINE with rush_job_id=None and slowdown_factor=None.

    Returns a new ScenarioSpec (does not mutate the input if it's immutable).
    """
    if spec.scenario_type == ScenarioType.M2_SLOWDOWN:
        # If M2_SLOWDOWN has rush_job_id set, clear it
        if spec.rush_job_id is not None:
            return ScenarioSpec(
                scenario_type=ScenarioType.M2_SLOWDOWN,
                rush_job_id=None,
                slowdown_factor=spec.slowdown_factor,
            )
        return spec

    elif spec.scenario_type == ScenarioType.RUSH_ARRIVES:
        # Check if rush_job_id is valid
        valid_job_ids = {job.id for job in factory.jobs}
        if spec.rush_job_id is None or spec.rush_job_id not in valid_job_ids:
            # Fall back to BASELINE
            return ScenarioSpec(
                scenario_type=ScenarioType.BASELINE,
                rush_job_id=None,
                slowdown_factor=None,
            )
        return spec

    else:
        # BASELINE or any other scenario type: return as-is
        return spec


# Internal DTOs for multi-object LLM responses
class FuturesResponse(BaseModel):
    """Container for FuturesAgent LLM response."""
    scenarios: list[ScenarioSpec]


class BriefingResponse(BaseModel):
    """Container for BriefingAgent LLM response."""
    markdown: str


class IntentAgent:
    """LLM-backed agent that maps raw user text to a ScenarioSpec.

    Enhanced for PR5: Now extracts user constraints and generates explanation context
    for downstream agents.
    """

    def run(self, user_text: str, factory: FactoryConfig | None = None) -> tuple[ScenarioSpec, str]:
        """
        Parse user text into a ScenarioSpec using an LLM.

        Falls back to BASELINE if LLM call fails.

        Args:
            user_text: Free-form user description
            factory: Optional FactoryConfig for context (defaults to toy factory)

        Returns:
            Tuple of (ScenarioSpec for the scenario to simulate, explanation string for context)
            The explanation string is NOT part of the spec; it's for the orchestrator to pass to BriefingAgent.
        """
        logger.debug(f"IntentAgent.run: Received user text: {user_text[:100]}...")

        try:
            # Build factory context
            if factory is None:
                factory = build_toy_factory()

            job_summary = ", ".join([f"{j.id} ({j.name})" for j in factory.jobs])
            machine_summary = ", ".join([f"{m.id} ({m.name})" for m in factory.machines])

            prompt = f"""You are a factory operations interpreter. Your job is to read a planner's
text description of their priorities for today and extract a scenario specification.
Additionally, extract any explicit user constraints or goals mentioned (e.g., "no lateness", "rush J2", "finish by 6pm").

You will output ONLY valid JSON matching the schema below. Do not add explanation or prose.

# Mapping Rules
- Mentions of "rush", "expedite", "priority" + a job ID → RUSH_ARRIVES with that job ID
- Mentions of "M2 slow", "M2 half-speed", "M2 maintenance" → M2_SLOWDOWN with slowdown_factor 2 or 3
- Explicit "normal day", "no rush", "no issues" → BASELINE
- If multiple patterns match, choose the scenario type that best reflects the main risk
- Do not invent combined types or unknown jobs (e.g., J99, J0)
- Ignore unknown job IDs and treat as no rush

# Constraint Extraction
Extract any explicit constraints or goals the user mentions, such as:
- "no lateness on J1"
- "must finish by 6pm"
- "zero late jobs"
- "J2 is critical"
- "makespan must be <= 8 hours"
Include these verbatim in the constraint_summary field.

# Schema
{{
  "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
  "rush_job_id": null or a valid job ID,
  "slowdown_factor": null or an integer >= 2,
  "constraint_summary": "string summarizing any explicit constraints or goals mentioned by user"
}}

# Scenario Types (Closed Set)
- BASELINE: Run the day as planned with no special modifications. rush_job_id and slowdown_factor must be null.
- RUSH_ARRIVES: An existing job is prioritized as a rush order. rush_job_id MUST be a real job ID from available jobs, slowdown_factor must be null.
- M2_SLOWDOWN: Machine M2 is slowed by a factor. slowdown_factor must be >= 2 and rush_job_id must be null.

# Available Jobs
{job_summary}

# Available Machines
{machine_summary}

# Planner Input
{user_text}

# Respond with ONLY the JSON object, no explanation."""

            # Parse with extended schema that includes constraint_summary
            class IntentResponse(BaseModel):
                scenario_type: ScenarioType
                rush_job_id: Optional[str] = None
                slowdown_factor: Optional[int] = None
                constraint_summary: str = ""

            response = call_llm_json(prompt, IntentResponse)
            spec = ScenarioSpec(
                scenario_type=response.scenario_type,
                rush_job_id=response.rush_job_id,
                slowdown_factor=response.slowdown_factor,
            )
            constraint_summary = response.constraint_summary

            logger.debug(
                "IntentAgent raw ScenarioSpec from LLM: type=%s rush_job_id=%s slowdown_factor=%s",
                spec.scenario_type,
                spec.rush_job_id,
                spec.slowdown_factor,
            )
            logger.debug(f"IntentAgent extracted constraints: {constraint_summary}")

            # Normalize the spec
            norm_spec = normalize_scenario_spec(spec, factory)
            logger.debug(
                "IntentAgent normalized ScenarioSpec: type=%s rush_job_id=%s slowdown_factor=%s",
                norm_spec.scenario_type,
                norm_spec.rush_job_id,
                norm_spec.slowdown_factor,
            )

            # Build explanation for downstream agents
            explanation = f"User intent: {norm_spec.scenario_type.value}"
            if norm_spec.rush_job_id:
                explanation += f" (rush job: {norm_spec.rush_job_id})"
            if norm_spec.slowdown_factor:
                explanation += f" (slowdown: {norm_spec.slowdown_factor}x)"
            if constraint_summary:
                explanation += f"\nUser constraints: {constraint_summary}"

            logger.info(f"IntentAgent explanation: {explanation}")

            return norm_spec, explanation

        except Exception as e:
            # Fallback to BASELINE on any error (LLM unavailable, parsing failure, etc.)
            logger.warning("IntentAgent LLM call failed; falling back to BASELINE: %s", e)
            return ScenarioSpec(scenario_type=ScenarioType.BASELINE), "Fallback to baseline due to parsing error"


class FuturesAgent:
    """LLM-backed agent that expands a ScenarioSpec into candidate scenarios.

    Enhanced for PR5: Now provides scenario selection reasoning for downstream context.
    """

    def run(self, spec: ScenarioSpec, factory: FactoryConfig | None = None) -> tuple[list[ScenarioSpec], str]:
        """
        Expand a scenario into 1-3 candidate scenarios using an LLM.

        Falls back to [spec] if LLM call fails.

        Args:
            spec: Base ScenarioSpec to expand
            factory: Optional FactoryConfig for context (defaults to toy factory)

        Returns:
            Tuple of (list of 1-3 ScenarioSpec objects, justification string for context)
            The justification string explains why these scenarios were chosen.
        """
        logger.debug(f"FuturesAgent.run: Received spec type={spec.scenario_type.value}")

        try:
            # Build factory summary for context
            if factory is None:
                factory = build_toy_factory()

            job_summary = ", ".join([f"{j.id} ({j.name})" for j in factory.jobs])
            machine_summary = ", ".join([f"{m.id} ({m.name})" for m in factory.machines])

            # Format current spec for context
            spec_summary = f"Type: {spec.scenario_type.value}"
            if spec.rush_job_id:
                spec_summary += f", Rush Job: {spec.rush_job_id}"
            if spec.slowdown_factor:
                spec_summary += f", Slowdown Factor: {spec.slowdown_factor}"

            prompt = f"""You are a factory scenario planner. Your job is to take a scenario
and generate 1-3 concrete scenario variations that explore the day's possibilities.
All scenarios must be valid ScenarioSpec objects.

You will output ONLY valid JSON. Do not add explanation.

# Valid Scenario Combinations
1. BASELINE: rush_job_id=null, slowdown_factor=null (no modifications)
2. RUSH_ARRIVES: rush_job_id=<valid job ID>, slowdown_factor=null
3. M2_SLOWDOWN: rush_job_id=null, slowdown_factor>=2

# Scenario Planning Rules
- Produce at most 3 scenarios
- If the primary scenario is BASELINE: include baseline, and optionally one other scenario for context
- If the primary scenario is RUSH_ARRIVES: include the primary rush scenario, and optionally baseline and/or a more aggressive rush
- If the primary scenario is M2_SLOWDOWN: include the primary slowdown, and optionally baseline and/or more severe slowdown
- All rush_job_id values must be real job IDs from available jobs
- All slowdown_factor values must be integers >= 2
- Do NOT create mixed types (e.g., rush AND slowdown in same scenario)
- Avoid irrelevant expansions; keep scenarios focused on the primary scenario type
- When in doubt, include BASELINE as a reference point

# Schema (return exactly this structure)
{{
  "scenarios": [
    {{
      "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
      "rush_job_id": null or valid job ID,
      "slowdown_factor": null or integer >= 2
    }},
    ...
  ],
  "justification": "1-2 sentence summary of why these scenarios were chosen"
}}

# Available Jobs
{job_summary}

# Available Machines
{machine_summary}

# Current Scenario
{spec_summary}

Generate 1-3 reasonable scenario variants, all valid per the rules above.

# Respond with ONLY the JSON object with "scenarios" array and "justification" string."""

            class FuturesResponseWithJustification(BaseModel):
                scenarios: list[ScenarioSpec]
                justification: str = ""

            response = call_llm_json(prompt, FuturesResponseWithJustification)
            scenarios = response.scenarios
            justification = response.justification

            logger.debug(f"FuturesAgent returned {len(scenarios)} scenarios from LLM")
            logger.debug(f"FuturesAgent justification: {justification}")

            # Safety: ensure we have at most 3 scenarios
            if len(scenarios) > 3:
                scenarios = scenarios[:3]
                logger.debug("FuturesAgent truncated to 3 scenarios")

            # Safety: if empty, return original spec
            if not scenarios:
                scenarios = [spec]
                justification = f"Fallback: returning primary scenario only ({spec.scenario_type.value})"
                logger.debug("FuturesAgent empty response; returning [spec]")

            logger.info(f"FuturesAgent scenario selection: {len(scenarios)} scenarios chosen for {spec.scenario_type.value}")

            return scenarios, justification

        except Exception as e:
            # Fallback to [spec] on any error
            logger.warning("FuturesAgent LLM call failed; falling back to [spec]: %s", e)
            return [spec], f"Fallback due to error: {str(e)}"


class BriefingAgent:
    """LLM-backed agent that converts metrics to a markdown briefing.

    Enhanced for PR5: Now includes feasibility assessment against user constraints
    and explicit conflict detection.
    """

    def run(
        self,
        metrics: ScenarioMetrics,
        context: str | None = None,
        intent_context: str | None = None,
        futures_context: str | None = None,
    ) -> str:
        """
        Generate a markdown briefing from metrics using an LLM.

        Falls back to a deterministic template if LLM call fails.

        Args:
            metrics: ScenarioMetrics for the primary scenario
            context: Optional summary of other scenarios and their metrics
            intent_context: Optional explanation from IntentAgent (includes user constraints)
            futures_context: Optional justification from FuturesAgent (why these scenarios were chosen)

        Returns:
            Markdown string briefing
        """
        logger.debug(f"BriefingAgent.run: Received metrics for briefing (makespan={metrics.makespan_hour}h)")

        try:
            # Build factory summary
            factory = build_toy_factory()

            job_summary = ", ".join([f"{j.id} ({j.name})" for j in factory.jobs])
            machine_summary = ", ".join([f"{m.id} ({m.name})" for m in factory.machines])

            # Format metrics for context
            metrics_summary = f"""Makespan: {metrics.makespan_hour} hours
Bottleneck Machine: {metrics.bottleneck_machine_id}
Bottleneck Utilization: {metrics.bottleneck_utilization:.2%}
Job Lateness: {dict(metrics.job_lateness)}"""

            context_str = ""
            if context:
                context_str = f"\n# Scenarios Context\n{context}"

            intent_str = ""
            if intent_context:
                intent_str = f"\n# User Intent & Constraints\n{intent_context}"

            futures_str = ""
            if futures_context:
                futures_str = f"\n# Scenario Selection Reasoning\n{futures_context}"

            prompt = f"""You are a factory operations briefing writer. Your job is to translate
simulation metrics into a clear, actionable morning briefing for a plant manager.

Use ONLY the data provided. Do not invent jobs, machines, or scenarios.
You will output ONLY valid JSON matching the schema below. Do not add explanation or prose.

# Critical Instructions: Constraint & Feasibility Analysis
When reviewing the scenarios and metrics, explicitly:
1. Identify any user constraints mentioned (e.g., "no lateness", "must finish by 6pm", "rush J2")
2. Compare these constraints against the actual metrics:
   - If user requested impossible targets (e.g., makespan ≤ 6h but all scenarios are ≥ 9h, or "no late jobs" but scenario shows lateness):
     * Clearly state that the constraint cannot be met
     * Explain why (e.g., "M2 is a bottleneck; all three jobs need 6h of M2 time, but M2 is only available 24h/day")
     * Show the "best achievable" alternative
   - If some scenarios meet constraints better than others, highlight which is closest
   - Always be honest about what the metrics show, even if it conflicts with user expectations
3. Structure your response with a dedicated "Feasibility Assessment" section that addresses constraints explicitly
4. If there are NO constraints mentioned, still provide the standard briefing structure

# FactoryConfig Summary
Jobs: {job_summary}
Machines: {machine_summary}

# Primary Scenario Metrics
{metrics_summary}{intent_str}{futures_str}{context_str}

# Schema
{{
  "markdown": "# Morning Briefing\n\n## Today at a Glance\n[1-2 sentences summarizing the main risk, constraint feasibility, or recommendation]\n\n## Feasibility Assessment\n[If constraints were mentioned by user, state whether they can be met. If impossible, explain why and what is best achievable. If no constraints, you may skip this section or note 'No explicit constraints mentioned.']\n\n## Key Risks\n[3-5 bullet points on lateness, bottlenecks, utilization, and any constraint violations]\n\n## Recommended Actions\n[2-4 bullet points with concrete, actionable steps]\n\n## Limitations of This Model\n[2-3 sentences on scope and limitations of this deterministic model]"
}}

# Respond with ONLY the JSON object, no explanation."""

            logger.debug(f"BriefingAgent: Calling LLM with intent_context={bool(intent_context)}, futures_context={bool(futures_context)}")
            response = call_llm_json(prompt, BriefingResponse)
            logger.info(f"BriefingAgent: Generated briefing ({len(response.markdown)} chars)")
            return response.markdown

        except Exception as e:
            # Fallback to deterministic template on error
            logger.warning("BriefingAgent LLM failed; using deterministic fallback: %s", e)
            lines = [
                "# Morning Briefing",
                "",
                "## Today at a Glance",
                f"Makespan: {metrics.makespan_hour} hours. Bottleneck: {metrics.bottleneck_machine_id}.",
                "",
            ]

            # Add user intent if available
            if intent_context:
                lines.extend([
                    "## Feasibility Assessment",
                    f"{intent_context}",
                    "",
                ])

            lines.extend([
                "## Key Risks",
                f"- {metrics.bottleneck_machine_id} is bottleneck at {metrics.bottleneck_utilization:.0%} utilization",
                f"- Late jobs: {[k for k, v in metrics.job_lateness.items() if v > 0] or 'none'}",
                "",
                "## Recommended Actions",
                "- Monitor bottleneck machine closely.",
                "- Review job scheduling priorities.",
                "",
                "## Limitations of This Model",
                "This is a deterministic simulation of a single day. It does not account for real-world variability, "
                "material delays, equipment breakdowns, or other disruptions.",
            ])
            return "\n".join(lines)
