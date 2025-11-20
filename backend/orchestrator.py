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

The run_onboarded_pipeline function extends this pipeline to support:
- OnboardingAgent for factory description parsing (no LLM in PR1)
- normalize_factory for safe config cleanup
- Returns a structured dict with factory, specs, metrics, briefing, and metadata
"""

import logging
from .world import build_toy_factory
from .sim import simulate
from .metrics import compute_metrics
from .agents import IntentAgent, FuturesAgent, BriefingAgent, OnboardingAgent
from .models import FactoryConfig, ScenarioSpec, SimulationResult, ScenarioMetrics, OnboardingMeta
from .onboarding import normalize_factory

logger = logging.getLogger(__name__)


def is_toy_factory(factory: FactoryConfig) -> bool:
    """
    Detect if a factory is the toy factory (default) based on structure.

    The toy factory has:
    - 3 machines with IDs M1, M2, M3
    - 3 jobs with IDs J1, J2, J3

    This structural check is used to determine if normalization or the onboarding agent
    returned the default toy factory (indicating fallback or stub behavior).

    Args:
        factory: FactoryConfig to check

    Returns:
        True if this is the toy factory, False otherwise
    """
    if len(factory.machines) != 3 or len(factory.jobs) != 3:
        return False

    machine_ids = {m.id for m in factory.machines}
    job_ids = {j.id for j in factory.jobs}

    return machine_ids == {"M1", "M2", "M3"} and job_ids == {"J1", "J2", "J3"}


def run_pipeline(user_text: str) -> dict:
    """Run the full simulation pipeline for a given free-text user description.

    Enhanced for PR5: Now captures and passes context from agents through the pipeline.

    Steps:
    1. Build the baseline factory config.
    2. Use IntentAgent to turn user_text into a base ScenarioSpec (plus constraint context).
    3. Use FuturesAgent to expand that into a list of ScenarioSpecs (1-3) (plus scenario reasoning).
    4. For each ScenarioSpec:
       - Run simulate(factory, spec)
       - Run compute_metrics(factory, result)
    5. Choose primary scenario (first in list).
    6. Build context summary describing all scenarios + metrics.
    7. Use BriefingAgent to produce a markdown summary with intent, futures, and scenario context.

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
    # Log incoming user text (truncated for safety)
    logger.info("=" * 80)
    logger.info("📋 run_pipeline started")
    logger.info(f"   User text: {user_text[:100]}{'...' if len(user_text) > 100 else ''}")
    logger.info("=" * 80)

    # Step 1: Build the baseline factory config
    logger.info("Step 1️⃣ Building baseline factory config...")
    factory: FactoryConfig = build_toy_factory()
    logger.info(f"   ✓ Factory built: {len(factory.machines)} machines, {len(factory.jobs)} jobs")

    # Initialize agents
    logger.info("Step 2️⃣ Initializing agents...")
    intent_agent = IntentAgent()
    futures_agent = FuturesAgent()
    briefing_agent = BriefingAgent()
    logger.info("   ✓ Agents initialized")

    # Step 2: Use IntentAgent to parse user text into a base ScenarioSpec
    logger.info("Step 3️⃣ Running IntentAgent (parsing user text → scenario intent)...")
    base_spec, intent_context = intent_agent.run(user_text, factory=factory)
    logger.info(f"   ✓ IntentAgent result: {base_spec.scenario_type.value}")
    logger.debug(f"   Intent context: {intent_context}")

    # Step 3: Use FuturesAgent to expand into candidate scenarios
    logger.info("Step 4️⃣ Running FuturesAgent (expanding to candidate scenarios)...")
    specs, futures_context = futures_agent.run(base_spec, factory=factory)
    logger.info(f"   ✓ FuturesAgent generated {len(specs)} scenarios")
    logger.debug(f"   Futures context: {futures_context}")
    if not specs:
        # Guard against empty list (though fallback in FuturesAgent should prevent this)
        logger.error("❌ FuturesAgent returned no scenarios!")
        raise RuntimeError("FuturesAgent returned no scenarios.")

    # Step 4: For each scenario, run simulation and compute metrics
    logger.info("Step 5️⃣ Running simulations for each scenario...")
    results: list[SimulationResult] = []
    metrics_list: list[ScenarioMetrics] = []

    for i, spec in enumerate(specs):
        logger.debug(f"   [Scenario {i+1}/{len(specs)}] Running simulation...")
        # Run simulation
        result: SimulationResult = simulate(factory, spec)
        results.append(result)

        # Compute metrics
        logger.debug(f"   [Scenario {i+1}/{len(specs)}] Computing metrics...")
        metrics: ScenarioMetrics = compute_metrics(factory, result)
        metrics_list.append(metrics)

        # Log scenario metrics
        late_jobs = sum(1 for v in metrics.job_lateness.values() if v > 0)
        logger.info(
            f"   [Scenario {i+1}/{len(specs)}] ✓ Complete: "
            f"type={spec.scenario_type.value} "
            f"makespan={metrics.makespan_hour}h "
            f"late_jobs={late_jobs} "
            f"bottleneck={metrics.bottleneck_machine_id} "
            f"util={metrics.bottleneck_utilization:.1%}"
        )

    # Step 5: Choose primary scenario (first in list)
    logger.info("Step 6️⃣ Selecting primary scenario...")
    primary_spec = specs[0]
    primary_metrics = metrics_list[0]
    logger.info(f"   ✓ Primary scenario: {primary_spec.scenario_type.value}")

    # Step 6: Build context summary for BriefingAgent with user_text and scenarios
    logger.info("Step 7️⃣ Building context summary for briefing...")
    context_lines = [f"User Request: {user_text}", ""]
    context_lines.append("You evaluated the following scenarios:")
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
    logger.info(f"   ✓ Context built ({len(context)} chars)")

    # Step 7: Generate briefing with primary metrics and context
    logger.info("Step 8️⃣ Running BriefingAgent (generating markdown summary)...")
    briefing: str = briefing_agent.run(
        primary_metrics,
        context=context,
        intent_context=intent_context,
        futures_context=futures_context,
    )
    logger.info(f"   ✓ Briefing generated ({len(briefing)} chars)")

    logger.info("=" * 80)
    logger.info("✅ run_pipeline completed successfully!")
    logger.info("=" * 80)

    # Return all outputs
    return {
        "factory": factory,
        "base_spec": base_spec,
        "specs": specs,
        "results": results,
        "metrics": metrics_list,
        "briefing": briefing,
    }


def run_onboarded_pipeline(factory_text: str, situation_text: str) -> dict:
    """Run the full simulation pipeline with onboarded factory config.

    This is an extension of run_pipeline that:
    1. Uses OnboardingAgent to parse factory_text into a FactoryConfig
    2. Normalizes the factory using normalize_factory
    3. Runs the multi-agent + simulation pipeline using the normalized factory
    4. Returns a structured dict with factory, specs, metrics, briefing, and metadata

    Steps:
    1. Instantiate OnboardingAgent and call its run(factory_text) to get a FactoryConfig
    2. Normalize the config with normalize_factory()
    3. Run IntentAgent to parse situation_text into a base ScenarioSpec
    4. Use FuturesAgent to expand into candidate scenarios
    5. For each ScenarioSpec:
       - Run simulate(factory, spec)
       - Run compute_metrics(factory, result)
    6. Use BriefingAgent to produce markdown briefing
    7. Return structured dict with factory, specs, metrics, briefing, and metadata

    Args:
        factory_text: Free-text description of factory (passed to OnboardingAgent)
        situation_text: Free-text description of today's situation

    Returns:
        dict containing:
            - "factory": FactoryConfig (normalized)
            - "situation_text": str (the input situation_text)
            - "specs": list[ScenarioSpec] (all scenarios from FuturesAgent)
            - "metrics": list[ScenarioMetrics] (one per scenario, same order as specs)
            - "briefing": str (markdown)
            - "meta": dict with:
                - "used_default_factory": bool (True if we fell back to toy factory)
                - "onboarding_errors": list[str] (empty in PR1)

    Raises:
        RuntimeError: If FuturesAgent returns no scenarios.
    """
    # Log incoming text (truncated for safety)
    logger.info("=" * 80)
    logger.info("🔧 run_onboarded_pipeline started")
    logger.info(f"   Factory text: {factory_text[:80]}{'...' if len(factory_text) > 80 else ''}")
    logger.info(f"   Situation text: {situation_text[:100]}{'...' if len(situation_text) > 100 else ''}")
    logger.info("=" * 80)

    # Step 1: Instantiate OnboardingAgent and get initial factory config
    logger.info("Step 1️⃣ Running OnboardingAgent (parsing factory description)...")
    onboarding_agent = OnboardingAgent()
    raw_factory = onboarding_agent.run(factory_text)
    logger.info(
        f"   ✓ OnboardingAgent returned factory: {len(raw_factory.machines)} machines, {len(raw_factory.jobs)} jobs"
    )

    # Step 2: Normalize the factory
    logger.info("Step 2️⃣ Normalizing factory configuration...")
    normalized_factory, normalization_warnings = normalize_factory(raw_factory)
    logger.debug(
        f"   After normalization: {len(normalized_factory.machines)} machines, {len(normalized_factory.jobs)} jobs"
    )

    # Step 3: Determine fallback level
    # Fallback is needed if the normalized factory is empty (no machines or no jobs)
    if not normalized_factory.machines or not normalized_factory.jobs:
        logger.debug("Fallback triggered: normalized factory is empty")
        final_factory = build_toy_factory()
        used_default_factory = True
    else:
        final_factory = normalized_factory
        # Check if the normalized factory is structurally the toy factory
        used_default_factory = is_toy_factory(final_factory)

    logger.info(
        f"   ✓ Factory prepared: {len(final_factory.machines)} machines, {len(final_factory.jobs)} jobs "
        f"(used_default={used_default_factory})"
    )

    # Log normalization warnings if any
    if normalization_warnings:
        logger.info(f"   Normalization repairs: {len(normalization_warnings)} issue(s)")
        for warning in normalization_warnings:
            logger.debug(f"     - {warning}")

    # Step 3: Initialize agents (except OnboardingAgent which we already used)
    logger.info("Step 3️⃣ Initializing agents...")
    intent_agent = IntentAgent()
    futures_agent = FuturesAgent()
    briefing_agent = BriefingAgent()
    logger.info("   ✓ Agents initialized")

    # Step 4: Use IntentAgent to parse situation text into a base ScenarioSpec
    logger.info("Step 4️⃣ Running IntentAgent (parsing situation text → scenario intent)...")
    base_spec, intent_context = intent_agent.run(situation_text, factory=final_factory)
    logger.info(
        f"   ✓ IntentAgent result: type={base_spec.scenario_type.value}"
    )
    logger.debug(f"   Intent context: {intent_context}")

    # Step 5: Use FuturesAgent to expand into candidate scenarios
    logger.info("Step 5️⃣ Running FuturesAgent (expanding to candidate scenarios)...")
    specs, futures_context = futures_agent.run(base_spec, factory=final_factory)
    if not specs:
        logger.error("❌ FuturesAgent returned no scenarios!")
        raise RuntimeError("FuturesAgent returned no scenarios.")

    logger.info(f"   ✓ FuturesAgent generated {len(specs)} scenarios")
    logger.debug(f"   Futures context: {futures_context}")

    # Step 6: For each scenario, run simulation and compute metrics
    logger.info("Step 6️⃣ Running simulations for each scenario...")
    results: list[SimulationResult] = []
    metrics_list: list[ScenarioMetrics] = []

    for i, spec in enumerate(specs):
        logger.debug(f"   [Scenario {i+1}/{len(specs)}] Running simulation...")
        # Run simulation
        result: SimulationResult = simulate(final_factory, spec)
        results.append(result)

        # Compute metrics
        logger.debug(f"   [Scenario {i+1}/{len(specs)}] Computing metrics...")
        metrics: ScenarioMetrics = compute_metrics(final_factory, result)
        metrics_list.append(metrics)

        # Log scenario metrics
        late_jobs = sum(1 for v in metrics.job_lateness.values() if v > 0)
        logger.info(
            f"   [Scenario {i+1}/{len(specs)}] ✓ Complete: "
            f"type={spec.scenario_type.value} "
            f"makespan={metrics.makespan_hour}h "
            f"late_jobs={late_jobs} "
            f"bottleneck={metrics.bottleneck_machine_id} "
            f"util={metrics.bottleneck_utilization:.1%}"
        )

    # Step 7: Choose primary scenario (first in list) and generate briefing
    logger.info("Step 7️⃣ Selecting primary scenario and generating briefing...")
    primary_spec = specs[0]
    primary_metrics = metrics_list[0]
    logger.info(f"   ✓ Primary scenario: {primary_spec.scenario_type.value}")

    # Build context summary for BriefingAgent
    logger.info("   Building context summary...")
    context_lines = [f"User Request: {situation_text}", ""]
    context_lines.append("You evaluated the following scenarios:")
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
    logger.info(f"   ✓ Context built ({len(context)} chars)")

    # Generate briefing with full context
    logger.info("Step 8️⃣ Running BriefingAgent (generating markdown summary)...")
    briefing: str = briefing_agent.run(
        primary_metrics,
        context=context,
        intent_context=intent_context,
        futures_context=futures_context,
    )
    logger.info(f"   ✓ Briefing generated ({len(briefing)} chars)")

    logger.info("=" * 80)
    logger.info("✅ run_onboarded_pipeline completed successfully!")
    logger.info(f"   Factory: {len(final_factory.machines)} machines, {len(final_factory.jobs)} jobs")
    logger.info(f"   Scenarios: {len(specs)}")
    logger.info(f"   Used default factory: {used_default_factory}")
    logger.info("=" * 80)

    # Create OnboardingMeta with all required fields
    # onboarding_errors comes from normalization warnings
    meta = OnboardingMeta(
        used_default_factory=used_default_factory,
        onboarding_errors=normalization_warnings,
        inferred_assumptions=[],
    )

    # Return all outputs in the structured format
    return {
        "factory": final_factory,
        "situation_text": situation_text,
        "specs": specs,
        "metrics": metrics_list,
        "briefing": briefing,
        "meta": meta,
    }
