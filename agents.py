"""
Agentic Interpretation Layer

This module defines three LLM-backed agents that form the agentic boundaries:

1. IntentAgent: Maps free-form user text to a ScenarioSpec
   - Input: user text
   - Output: ScenarioSpec
   - Uses LLM with fallback to BASELINE on error

2. FuturesAgent: Expands a ScenarioSpec into a list of candidate scenarios
   - Input: ScenarioSpec
   - Output: list[ScenarioSpec]
   - Uses LLM with fallback to [spec] on error

3. BriefingAgent: Translates ScenarioMetrics to markdown summary
   - Input: ScenarioMetrics, optional context string
   - Output: markdown string
   - Uses LLM with fallback to deterministic template on error

All agents call llm.call_llm_json for LLM communication.
Tests will monkeypatch call_llm_json to avoid real network calls.
"""

import logging
from pydantic import BaseModel

from models import ScenarioSpec, ScenarioType, ScenarioMetrics
from world import build_toy_factory
from llm import call_llm_json

logger = logging.getLogger(__name__)


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

# Schema
{{
  "scenario_type": "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN",
  "rush_job_id": null or a valid job ID,
  "slowdown_factor": null or an integer >= 2
}}

# Definitions
- BASELINE: Run the day as planned with no special modifications.
- RUSH_ARRIVES: An existing job is prioritized as a rush order (rush_job_id must be a real job ID).
- M2_SLOWDOWN: Machine M2 is slowed by a factor (slowdown_factor >= 2).

# Available Jobs
{job_summary}

# Available Machines
{machine_summary}

# Planner Input
{user_text}

# Respond with ONLY the JSON object, no explanation."""

            spec = call_llm_json(prompt, ScenarioSpec)
            return spec

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

You will output ONLY valid JSON. Do not add explanation.

# Scenario Types (Closed Set)
1. BASELINE: No modifications.
2. RUSH_ARRIVES: An existing job is injected as a rush instance (must specify valid rush_job_id).
3. M2_SLOWDOWN: Machine M2 is slowed (must specify slowdown_factor >= 2).

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

Generate 1-3 reasonable scenario variants. All rush_job_id values must be real job IDs.
All slowdown_factor values must be >= 2.

# Respond with ONLY the JSON object with "scenarios" array."""

            response = call_llm_json(prompt, FuturesResponse)
            scenarios = response.scenarios

            # Safety: ensure we have at most 3 scenarios
            if len(scenarios) > 3:
                scenarios = scenarios[:3]

            # Safety: if empty, return original spec
            if not scenarios:
                scenarios = [spec]

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
            context: Optional summary of other scenarios and their metrics

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

            response = call_llm_json(prompt, BriefingResponse)
            return response.markdown

        except Exception as e:
            # Fallback to deterministic template on error
            logger.warning("BriefingAgent LLM call failed; using deterministic template: %s", e)
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
