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
        Build a simplified, focused prompt for LLM parsing of factory descriptions.

        This prompt prioritizes:
        1. Clear extraction rules (COVERAGE FIRST)
        2. Fractional duration handling (round, never drop)
        3. A concrete worked example at the END (recency bias)
        4. Minimal verbosity to avoid confusion

        Args:
            factory_text: Free-form factory description from user

        Returns:
            Full prompt ready for LLM
        """
        prompt = """You are a factory description parser. Output ONLY valid JSON.

================================================================================
CRITICAL RULES (Apply These Always)
================================================================================

1. COVERAGE FIRST: Extract ALL explicitly mentioned machines and jobs.
   - If text says "M1, M2, M3", include all three.
   - If text names "J1, J2, J3, J4", include all four.
   - NEVER drop a job or machine.

2. FRACTIONAL DURATIONS: Always round, never drop.
   - 1.5h → 2, 0.5h → 1, 2.25h → 2, 3.7h → 4
   - Output MUST be integer >= 1
   - Never drop a job because its duration is fractional.

3. FILL GAPS: Use defaults when underspecified.
   - Missing duration → 1 hour
   - Missing due time → 24 (end of day)
   - Missing machine in step → drop that step only, keep job

================================================================================
SCHEMA
================================================================================

{
  "machines": [
    {"id": "M1", "name": "string from text"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "string from text",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2}
      ],
      "due_time_hour": 24
    }
  ]
}

================================================================================
TIME INTERPRETATION (when needed)
================================================================================

Due times: "10am" → 10, "noon" → 12, "3pm" → 15, "EOD" → 24
Durations: "5h" → 5, "3-4h" → 3, "quick" → 1, "lengthy" → 3

================================================================================
FINAL WORKED EXAMPLE (Read This Carefully!)
================================================================================

INPUT TEXT:
We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h).

YOUR OUTPUT MUST BE:
{
  "machines": [
    {"id": "M1", "name": "assembly"},
    {"id": "M2", "name": "drill"},
    {"id": "M3", "name": "pack"}
  ],
  "jobs": [
    {
      "id": "J1",
      "name": "Job 1",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2},
        {"machine_id": "M2", "duration_hours": 3},
        {"machine_id": "M3", "duration_hours": 1}
      ],
      "due_time_hour": 24
    },
    {
      "id": "J2",
      "name": "Job 2",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2},
        {"machine_id": "M2", "duration_hours": 2},
        {"machine_id": "M3", "duration_hours": 2}
      ],
      "due_time_hour": 24
    },
    {
      "id": "J3",
      "name": "Job 3",
      "steps": [
        {"machine_id": "M1", "duration_hours": 3},
        {"machine_id": "M2", "duration_hours": 1},
        {"machine_id": "M3", "duration_hours": 2}
      ],
      "due_time_hour": 24
    },
    {
      "id": "J4",
      "name": "Job 4",
      "steps": [
        {"machine_id": "M1", "duration_hours": 2},
        {"machine_id": "M2", "duration_hours": 2},
        {"machine_id": "M3", "duration_hours": 4}
      ],
      "due_time_hour": 24
    }
  ]
}

KEY POINTS SHOWN IN THIS EXAMPLE:
- All 3 machines (M1, M2, M3) included (NEVER drop).
- All 4 jobs (J1, J2, J3, J4) included (NEVER drop).
- Fractional 1.5h rounded to 2 in J2 steps (NEVER drop due to fractional).
- Default due_time 24 used (no due time given).

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
