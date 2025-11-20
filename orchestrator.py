"""
Orchestration & Pipeline Module

Defines the main orchestration pipeline that wires together:
1. Factory configuration
2. Intent Agent (user text -> ScenarioSpec)
3. Futures Agent (ScenarioSpec -> list of candidates)
4. Simulation engine
5. Metrics computation
6. Briefing Agent (metrics -> markdown)

The run_pipeline function is a thin coordinator that ensures
deterministic, end-to-end execution with proper type flow.
"""

from world import build_toy_factory
from sim import simulate
from metrics import compute_metrics
from agents import IntentAgent, FuturesAgent, BriefingAgent
from models import FactoryConfig, ScenarioSpec, SimulationResult, ScenarioMetrics


def run_pipeline(user_text: str) -> dict:
    """Run the full simulation pipeline for a given free-text user description.

    Steps:
    1. Build the baseline factory config.
    2. Use IntentAgent to turn user_text into a ScenarioSpec.
    3. Use FuturesAgent to expand that into a list of ScenarioSpecs.
    4. Take the first ScenarioSpec.
    5. Run the simulation for that scenario.
    6. Compute metrics for the result.
    7. Use BriefingAgent to produce a markdown summary.

    Args:
        user_text: Free-text description of desired simulation scenario.

    Returns:
        dict containing:
            - "factory": FactoryConfig
            - "spec": ScenarioSpec
            - "result": SimulationResult
            - "metrics": ScenarioMetrics
            - "briefing": str (markdown)

    Raises:
        RuntimeError: If FuturesAgent returns no scenarios.
    """
    # Step 1: Build the baseline factory config
    factory: FactoryConfig = build_toy_factory()

    # Initialize agents
    intent_agent = IntentAgent()
    futures_agent = FuturesAgent()
    briefing_agent = BriefingAgent()

    # Step 2: Use IntentAgent to parse user text into a ScenarioSpec
    spec: ScenarioSpec = intent_agent.run(user_text)

    # Step 3: Use FuturesAgent to expand into candidate scenarios
    specs = futures_agent.run(spec)
    if not specs:
        # This should not happen with the stub, but guard anyway.
        raise RuntimeError("FuturesAgent returned no scenarios.")

    # Step 4: Take the first (and only, in stub) scenario
    chosen_spec = specs[0]

    # Step 5: Run the simulation
    result: SimulationResult = simulate(factory, chosen_spec)

    # Step 6: Compute metrics
    metrics: ScenarioMetrics = compute_metrics(factory, result)

    # Step 7: Generate briefing
    briefing: str = briefing_agent.run(metrics)

    # Return all outputs
    return {
        "factory": factory,
        "spec": chosen_spec,
        "result": result,
        "metrics": metrics,
        "briefing": briefing,
    }
