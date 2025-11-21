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
from .onboarding import (
    normalize_factory,
    estimate_onboarding_coverage,
    extract_explicit_ids,
    enumerate_entities,
    compute_coverage,
    ExtractionError,
)

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


def run_onboarding(factory_text: str) -> tuple[FactoryConfig, OnboardingMeta]:
    """Run onboarding pipeline: parse and normalize factory description.

    PR4: Simplified orchestration using new OnboardingAgent.run with fallback strategy.

    Steps:
    1. Instantiate OnboardingAgent
    2. Call agent.run(factory_text) which orchestrates stages 0-4:
       - Stage 0: Extract explicit IDs (regex, deterministic)
       - Stage 1: Extract coarse structure (LLM)
       - Stage 2: Extract job steps (LLM)
       - Stage 3: Validate and normalize
       - Stage 4: Assess coverage (enforce 100%)
    3. On success: return factory and meta with used_default_factory=False
    4. On ExtractionError: log warning, fallback to toy factory, return with used_default_factory=True

    Behavior:
    - Happy path: agent succeeds, all IDs covered → return onboarded factory, clean meta
    - Coverage mismatch: agent raises COVERAGE_MISMATCH → fallback to toy factory
    - LLM error: agent raises LLM_FAILURE → fallback to toy factory
    - Any error: log and fallback; no exception raised from this function

    Args:
        factory_text: Free-text factory description

    Returns:
        Tuple of (FactoryConfig, OnboardingMeta)
        - FactoryConfig is from agent (with 100% coverage) or toy factory (on fallback)
        - OnboardingMeta tracks whether fallback was used and error summary

    Raises:
        Nothing; all failures are handled internally with fallback
    """
    logger.info(f"run_onboarding: factory_text len={len(factory_text)}")

    agent = OnboardingAgent()

    try:
        # Call the agent; it will run all stages 0-4 and enforce coverage
        factory = agent.run(factory_text)
        used_default_factory = False
        onboarding_errors: list[str] = []
        logger.info(
            f"run_onboarding: success - agent produced {len(factory.machines)} machines, "
            f"{len(factory.jobs)} jobs with 100% coverage"
        )

    except ExtractionError as e:
        # Log the error and fallback to toy factory
        logger.warning(
            f"run_onboarding: onboarding failed, falling back to toy factory: {e.code} - {e.message}"
        )
        factory = build_toy_factory()
        used_default_factory = True

        # Build user-facing error summary
        onboarding_errors: list[str] = [f"onboarding failed: {e.code}"]

        # Add details about coverage mismatch if applicable
        if e.code == "COVERAGE_MISMATCH" and isinstance(e.details, dict):
            missing_m = e.details.get("missing_machines") or []
            missing_j = e.details.get("missing_jobs") or []
            if missing_m or missing_j:
                details_msg = f"(missing machines={sorted(list(missing_m))}, missing jobs={sorted(list(missing_j))})"
                onboarding_errors[0] += f" {details_msg}"

    logger.info(
        f"run_onboarding complete: {len(factory.machines)} machines, {len(factory.jobs)} jobs, "
        f"used_default={used_default_factory}"
    )

    # Build OnboardingMeta
    meta = OnboardingMeta(
        used_default_factory=used_default_factory,
        onboarding_errors=onboarding_errors,
        inferred_assumptions=[],
    )

    return factory, meta


def run_decision_pipeline(
    factory: FactoryConfig,
    situation_text: str,
    meta: OnboardingMeta,
) -> dict:
    """Run decision + simulation pipeline with a given factory and onboarding metadata.

    Steps:
    1. IntentAgent parses situation_text → ScenarioSpec
    2. FuturesAgent expands → list of ScenarioSpecs (1-3)
    3. For each scenario: simulate() + compute_metrics()
    4. BriefingAgent generates markdown briefing
    5. Return dict with specs, metrics, briefing, meta, factory

    Args:
        factory: FactoryConfig to use for all scenarios
        situation_text: Free-text description of today's situation
        meta: OnboardingMeta from onboarding phase (threaded through)

    Returns:
        dict containing:
            - "factory": FactoryConfig (input factory)
            - "specs": list[ScenarioSpec] (scenarios from FuturesAgent)
            - "metrics": list[ScenarioMetrics] (one per scenario)
            - "briefing": str (markdown)
            - "meta": OnboardingMeta (input meta, threaded through)

    Raises:
        RuntimeError: If FuturesAgent returns no scenarios
    """
    logger.debug(
        f"run_decision_pipeline: situation_text={situation_text[:100]}{'...' if len(situation_text) > 100 else ''}"
    )

    # Initialize agents
    intent_agent = IntentAgent()
    futures_agent = FuturesAgent()
    briefing_agent = BriefingAgent()

    # Step 1: IntentAgent parses situation text
    logger.debug("   IntentAgent: parsing situation text...")
    base_spec, intent_context = intent_agent.run(situation_text, factory=factory)
    logger.debug(f"   IntentAgent: type={base_spec.scenario_type.value}")

    # Step 2: FuturesAgent expands to candidate scenarios
    logger.debug("   FuturesAgent: expanding scenarios...")
    specs, futures_context = futures_agent.run(base_spec, factory=factory)
    if not specs:
        logger.error("FuturesAgent returned no scenarios!")
        raise RuntimeError("FuturesAgent returned no scenarios.")
    logger.debug(f"   FuturesAgent: {len(specs)} scenarios")

    # Step 3: Run simulation and metrics for each scenario
    logger.debug("   Running simulations...")
    results: list[SimulationResult] = []
    metrics_list: list[ScenarioMetrics] = []

    for i, spec in enumerate(specs):
        result: SimulationResult = simulate(factory, spec)
        results.append(result)
        metrics: ScenarioMetrics = compute_metrics(factory, result)
        metrics_list.append(metrics)
        late_jobs = sum(1 for v in metrics.job_lateness.values() if v > 0)
        logger.debug(
            f"   [Scenario {i+1}/{len(specs)}] type={spec.scenario_type.value} "
            f"makespan={metrics.makespan_hour}h late_jobs={late_jobs}"
        )

    # Step 4: Generate briefing
    primary_metrics = metrics_list[0]
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
    logger.debug(f"   BriefingAgent: generating briefing...")
    briefing: str = briefing_agent.run(
        primary_metrics,
        context=context,
        intent_context=intent_context,
        futures_context=futures_context,
    )
    logger.debug(f"   BriefingAgent: {len(briefing)} chars")

    logger.info(
        f"run_decision_pipeline complete: {len(specs)} scenarios, "
        f"{len(metrics_list)} metrics"
    )

    return {
        "factory": factory,
        "specs": specs,
        "metrics": metrics_list,
        "briefing": briefing,
        "meta": meta,
    }


def run_onboarded_pipeline(factory_text: str, situation_text: str) -> dict:
    """Run complete pipeline: onboarding + decision + simulation.

    This glues run_onboarding and run_decision_pipeline together:
    1. run_onboarding(factory_text) → (factory, meta)
    2. run_decision_pipeline(factory, situation_text, meta) → full result

    Args:
        factory_text: Free-text factory description
        situation_text: Free-text situation description

    Returns:
        dict containing:
            - "factory": FactoryConfig
            - "specs": list[ScenarioSpec]
            - "metrics": list[ScenarioMetrics]
            - "briefing": str (markdown)
            - "meta": OnboardingMeta

    Raises:
        RuntimeError: If pipeline encounters unrecoverable error
    """
    logger.info("=" * 80)
    logger.info("🔧 run_onboarded_pipeline started")
    logger.info(f"   Factory text: {factory_text[:80]}{'...' if len(factory_text) > 80 else ''}")
    logger.info(f"   Situation text: {situation_text[:100]}{'...' if len(situation_text) > 100 else ''}")
    logger.info("=" * 80)

    # Phase 1: Onboarding
    logger.info("Phase 1️⃣ Onboarding (parsing and normalizing factory)...")
    factory, meta = run_onboarding(factory_text)
    logger.info(f"   ✓ Factory: {len(factory.machines)} machines, {len(factory.jobs)} jobs")
    logger.info(f"   ✓ Used default: {meta.used_default_factory}, errors: {len(meta.onboarding_errors)}")

    # Phase 2: Decision + Simulation
    logger.info("Phase 2️⃣ Decision pipeline (intent → futures → simulation → briefing)...")
    result = run_decision_pipeline(factory, situation_text, meta)
    logger.info(f"   ✓ Scenarios: {len(result['specs'])}")
    logger.info(f"   ✓ Briefing: {len(result['briefing'])} chars")

    logger.info("=" * 80)
    logger.info("✅ run_onboarded_pipeline completed successfully!")
    logger.info(f"   Factory: {len(factory.machines)} machines, {len(factory.jobs)} jobs")
    logger.info(f"   Scenarios: {len(result['specs'])}")
    logger.info(f"   Used default factory: {meta.used_default_factory}")
    logger.info("=" * 80)

    return result
