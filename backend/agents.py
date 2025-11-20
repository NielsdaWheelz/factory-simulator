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
from typing import Iterable
from pydantic import BaseModel

from .models import ScenarioSpec, ScenarioType, ScenarioMetrics, FactoryConfig
from .world import build_toy_factory
from .llm import call_llm_json

logger = logging.getLogger(__name__)


class OnboardingAgent:
    """Stub onboarding agent for factory description parsing.

    In PR1 this does NOT call any LLM. It will be upgraded later to interpret
    free-text factory descriptions and return a FactoryConfig. For now, it
    simply returns the toy factory.
    """

    def run(self, factory_text: str) -> FactoryConfig:
        """
        Parse factory text into a FactoryConfig (stub version, no LLM).

        In PR1:
        - If factory_text is empty, return build_toy_factory()
        - If factory_text is non-empty, log and return build_toy_factory()

        Args:
            factory_text: Free-form factory description (ignored in stub)

        Returns:
            FactoryConfig (currently always the toy factory)
        """
        if not factory_text.strip():
            logger.info("OnboardingAgent: empty factory_text; returning toy factory")
            return build_toy_factory()

        logger.info(
            "OnboardingAgent stub used; ignoring custom factory_text for now. "
            "Will be upgraded with LLM parsing in a future PR."
        )
        return build_toy_factory()


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
    """LLM-backed agent that maps raw user text to a ScenarioSpec."""

    def run(self, user_text: str) -> ScenarioSpec:
        """
        Parse user text into a ScenarioSpec using an LLM.

        Falls back to BASELINE if LLM call fails.

        Args:
            user_text: Free-form user description

        Returns:
            ScenarioSpec for the scenario to simulate
        """
        try:
            # Build a minimal factory summary for context
            factory = build_toy_factory()

            job_summary = ", ".join([f"{j.id} ({j.name})" for j in factory.jobs])
            machine_summary = ", ".join([f"{m.id} ({m.name})" for m in factory.machines])

            prompt = f"""You are a factory operations interpreter. Your job is to read a planner's
text description of their priorities for today and extract a scenario specification.

You will output ONLY valid JSON matching the schema below. Do not add explanation or prose.

# Mapping Rules
- Mentions of "rush", "expedite", "priority" + a job ID → RUSH_ARRIVES with that job ID
- Mentions of "M2 slow", "M2 half-speed", "M2 maintenance" → M2_SLOWDOWN with slowdown_factor 2 or 3
- Explicit "normal day", "no rush", "no issues" → BASELINE
- If multiple patterns match, choose the scenario type that best reflects the main risk
- Do not invent combined types or unknown jobs (e.g., J99, J0)
- Ignore unknown job IDs and treat as no rush

# Schema
{{
  "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
  "rush_job_id": null or a valid job ID,
  "slowdown_factor": null or an integer >= 2
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

            spec = call_llm_json(prompt, ScenarioSpec)
            logger.info(
                "IntentAgent raw ScenarioSpec from LLM: type=%s rush_job_id=%s slowdown_factor=%s",
                spec.scenario_type,
                spec.rush_job_id,
                spec.slowdown_factor,
            )

            # Normalize the spec
            norm_spec = normalize_scenario_spec(spec, factory)
            logger.info(
                "IntentAgent normalized ScenarioSpec: type=%s rush_job_id=%s slowdown_factor=%s",
                norm_spec.scenario_type,
                norm_spec.rush_job_id,
                norm_spec.slowdown_factor,
            )

            return norm_spec

        except Exception as e:
            # Fallback to BASELINE on any error (LLM unavailable, parsing failure, etc.)
            logger.warning("IntentAgent LLM call failed; falling back to BASELINE: %s", e)
            return ScenarioSpec(scenario_type=ScenarioType.BASELINE)


class FuturesAgent:
    """LLM-backed agent that expands a ScenarioSpec into candidate scenarios."""

    def run(self, spec: ScenarioSpec) -> list[ScenarioSpec]:
        """
        Expand a scenario into 1-3 candidate scenarios using an LLM.

        Falls back to [spec] if LLM call fails.

        Args:
            spec: Base ScenarioSpec to expand

        Returns:
            List of 1-3 ScenarioSpec objects (≤ 3)
        """
        try:
            # Build factory summary for context
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
- One scenario should reflect the interpreted intent from the base scenario
- Others can be more conservative or more aggressive variants of the same type
- All rush_job_id values must be real job IDs from available jobs
- All slowdown_factor values must be integers >= 2
- Do NOT create mixed types (e.g., rush AND slowdown in same scenario)

# Schema (return exactly this structure)
{{
  "scenarios": [
    {{
      "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
      "rush_job_id": null or valid job ID,
      "slowdown_factor": null or integer >= 2
    }},
    ...
  ]
}}

# Available Jobs
{job_summary}

# Available Machines
{machine_summary}

# Current Scenario
{spec_summary}

Generate 1-3 reasonable scenario variants, all valid per the rules above.

# Respond with ONLY the JSON object with "scenarios" array."""

            response = call_llm_json(prompt, FuturesResponse)
            scenarios = response.scenarios

            logger.info("FuturesAgent returned %d scenarios from LLM", len(scenarios))

            # Safety: ensure we have at most 3 scenarios
            if len(scenarios) > 3:
                scenarios = scenarios[:3]
                logger.info("FuturesAgent truncated to 3 scenarios")

            # Safety: if empty, return original spec
            if not scenarios:
                scenarios = [spec]
                logger.info("FuturesAgent empty response; returning [spec]")

            return scenarios

        except Exception as e:
            # Fallback to [spec] on any error
            logger.warning("FuturesAgent LLM call failed; falling back to [spec]: %s", e)
            return [spec]


class BriefingAgent:
    """LLM-backed agent that converts metrics to a markdown briefing."""

    def run(self, metrics: ScenarioMetrics, context: str | None = None) -> str:
        """
        Generate a markdown briefing from metrics using an LLM.

        Falls back to a deterministic template if LLM call fails.

        Args:
            metrics: ScenarioMetrics for the primary scenario
            context: Optional summary of other scenarios and their metrics (includes user_text)

        Returns:
            Markdown string briefing
        """
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

            prompt = f"""You are a factory operations briefing writer. Your job is to translate
simulation metrics into a clear, actionable morning briefing for a plant manager.

Use ONLY the data provided. Do not invent jobs, machines, or scenarios.
You will output ONLY valid JSON matching the schema below. Do not add explanation or prose.

# Important: Constraint Analysis
When reviewing the scenarios and metrics, compare user constraints (if any) against the actual metrics:
- If user requested impossible targets (e.g., makespan ≤ 6h but all scenarios are ≥ 9h, or "no late jobs" but every scenario has lateness):
  * Explicitly state that no scenario meets all constraints
  * Explain the tradeoff and which scenario is the "least bad"
  * Do not assume constraints are always satisfiable
- If some scenarios meet constraints better than others, highlight the best option
- Always be honest about what the metrics show, even if it conflicts with user expectations

# FactoryConfig Summary
Jobs: {job_summary}
Machines: {machine_summary}

# Primary Scenario Metrics
{metrics_summary}{context_str}

# Schema
{{
  "markdown": "# Morning Briefing\n\n## Today at a Glance\n[1-2 sentences summarizing the main risk or recommendation]\n\n## Key Risks\n[3-5 bullet points on lateness, bottlenecks, utilization]\n\n## Recommended Actions\n[2-4 bullet points with concrete, actionable steps]\n\n## Limitations of This Model\n[2-3 sentences on scope and limitations of this deterministic model]"
}}

# Respond with ONLY the JSON object, no explanation."""

            logger.info("BriefingAgent generating briefing via LLM")
            response = call_llm_json(prompt, BriefingResponse)
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
            ]
            return "\n".join(lines)
