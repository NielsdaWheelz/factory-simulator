"""
Orchestration & Pipeline Module

Defines the main orchestration pipeline that wires together:
1. Factory configuration
2. Intent Agent (user text -> ScenarioSpec)
3. Futures Agent (ScenarioSpec -> list of candidates)
4. Simulation engine for each scenario
5. Metrics computation for each scenario
6. Briefing Agent (primary metrics + context -> markdown)

The run_pipeline function is a coordinator that runs multiple scenarios,
builds a context summary, and produces a comprehensive briefing.
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
    2. Use IntentAgent to turn user_text into a base ScenarioSpec.
    3. Use FuturesAgent to expand that into a list of ScenarioSpecs (1-3).
    4. For each ScenarioSpec:
       - Run simulate(factory, spec)
       - Run compute_metrics(factory, result)
    5. Choose primary scenario (first in list).
    6. Build context summary describing all scenarios + metrics.
    7. Use BriefingAgent to produce a markdown summary with context.

    Args:
        user_text: Free-text description of desired simulation scenario.

    Returns:
        dict containing:
            - "factory": FactoryConfig
            - "base_spec": ScenarioSpec (first spec from IntentAgent)
            - "specs": list[ScenarioSpec] (all scenarios from FuturesAgent)
            - "results": list[SimulationResult] (one per scenario, same order as specs)
            - "metrics": list[ScenarioMetrics] (one per scenario, same order as specs)
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

    # Step 2: Use IntentAgent to parse user text into a base ScenarioSpec
    base_spec: ScenarioSpec = intent_agent.run(user_text)

    # Step 3: Use FuturesAgent to expand into candidate scenarios
    specs = futures_agent.run(base_spec)
    if not specs:
        # Guard against empty list (though fallback in FuturesAgent should prevent this)
        raise RuntimeError("FuturesAgent returned no scenarios.")

    # Step 4: For each scenario, run simulation and compute metrics
    results: list[SimulationResult] = []
    metrics_list: list[ScenarioMetrics] = []

    for spec in specs:
        # Run simulation
        result: SimulationResult = simulate(factory, spec)
        results.append(result)

        # Compute metrics
        metrics: ScenarioMetrics = compute_metrics(factory, result)
        metrics_list.append(metrics)

    # Step 5: Choose primary scenario (first in list)
    primary_spec = specs[0]
    primary_metrics = metrics_list[0]

    # Step 6: Build context summary for BriefingAgent
    context_lines = ["You evaluated the following scenarios:"]
    for i, (spec, metrics) in enumerate(zip(specs, metrics_list), start=1):
        scenario_desc = f"\n{i}) {spec.scenario_type.value}"
        if spec.rush_job_id:
            scenario_desc += f" (Job: {spec.rush_job_id})"
        if spec.slowdown_factor:
            scenario_desc += f" (Factor: {spec.slowdown_factor})"
        scenario_desc += f"\n   - Makespan: {metrics.makespan_hour}h"
        scenario_desc += f"\n   - Late jobs: {[k for k, v in metrics.job_lateness.items() if v > 0] or 'none'}"
        scenario_desc += f"\n   - Bottleneck: {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%})"
        context_lines.append(scenario_desc)

    context = "\n".join(context_lines)

    # Step 7: Generate briefing with primary metrics and context
    briefing: str = briefing_agent.run(primary_metrics, context=context)

    # Return all outputs
    return {
        "factory": factory,
        "base_spec": base_spec,
        "specs": specs,
        "results": results,
        "metrics": metrics_list,
        "briefing": briefing,
    }
