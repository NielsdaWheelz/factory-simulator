"""
Agentic Interpretation Layer

This module defines three stub agents that form the agentic boundaries:

1. IntentAgent: Maps free-form user text to a ScenarioSpec
   - Input: user text
   - Output: ScenarioSpec
   - Stub behavior: always returns BASELINE

2. FuturesAgent: Expands a ScenarioSpec into a list of candidate scenarios
   - Input: ScenarioSpec
   - Output: list[ScenarioSpec]
   - Stub behavior: returns single-element list containing input spec

3. BriefingAgent: Translates ScenarioMetrics to markdown summary
   - Input: ScenarioMetrics
   - Output: markdown string
   - Stub behavior: simple deterministic formatting

All agents are deterministic with no randomness or external dependencies.
Future PRs will replace these stubs with LLM-backed versions.
"""

from models import ScenarioSpec, ScenarioType, ScenarioMetrics


class IntentAgent:
    """Stub agent that maps raw user text to a ScenarioSpec.

    In this PR, it is a deterministic stub: it ignores the text and always returns BASELINE.
    Future PRs will replace this with LLM-backed logic.
    """

    def run(self, user_text: str) -> ScenarioSpec:
        """Return a ScenarioSpec based on user_text (stub: always BASELINE)."""
        return ScenarioSpec(scenario_type=ScenarioType.BASELINE)


class FuturesAgent:
    """Stub agent that expands a single ScenarioSpec into a list of candidate scenarios.

    In this PR, it is a deterministic stub: it returns [spec] unchanged.
    """

    def run(self, spec: ScenarioSpec) -> list[ScenarioSpec]:
        """Return a list of candidate ScenarioSpecs (stub: single-element list)."""
        return [spec]


class BriefingAgent:
    """Stub agent that turns ScenarioMetrics into a human-readable markdown summary.

    In this PR, it is a simple deterministic formatter.
    """

    def run(self, metrics: ScenarioMetrics) -> str:
        """Return a minimal markdown briefing describing the simulation metrics."""
        lines = [
            "# Simulation Summary",
            "",
            f"- Makespan: {metrics.makespan_hour} hours",
            f"- Bottleneck machine: {metrics.bottleneck_machine_id}",
            f"- Bottleneck utilization: {metrics.bottleneck_utilization:.3f}",
        ]
        return "\n".join(lines)
