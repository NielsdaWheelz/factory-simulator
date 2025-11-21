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
from .models import FactoryConfig, ScenarioSpec, SimulationResult, ScenarioMetrics, OnboardingMeta, PipelineRunResult
from .onboarding import (
    normalize_factory,
    estimate_onboarding_coverage,
    extract_explicit_ids,
    enumerate_entities,
    compute_coverage,
    ExtractionError,
    extract_coarse_structure,
    extract_steps,
    validate_and_normalize,
    assess_coverage,
    CoarseStructure,
    RawFactoryConfig,
    CoverageReport,
)
from .debug_types import (
    PipelineDebugPayload,
    PipelineStageRecord,
    StageStatus,
    StageKind,
)
from .pipeline_instrumentation import (
    make_stage_wrapper,
    build_payload,
)

logger = logging.getLogger(__name__)


def _build_onboarding_stage_summaries(
    ids: "ExplicitIds | None" = None,
    coarse: "CoarseStructure | None" = None,
    raw: "RawFactoryConfig | None" = None,
    factory: "FactoryConfig | None" = None,
    coverage: "CoverageReport | None" = None,
) -> list[dict]:
    """
    Build minimal summaries for onboarding stages (O0-O4).

    Returns list of 5 dicts, one per stage, with minimal required fields.
    """
    summaries = []

    # O0: Extract Explicit IDs
    o0_summary = {"stage_type": "EXPLICIT_ID_EXTRACTION"}
    if ids:
        o0_summary.update({
            "explicit_machine_ids": sorted(list(ids.machine_ids)),
            "explicit_job_ids": sorted(list(ids.job_ids)),
            "total_ids_detected": len(ids.machine_ids) + len(ids.job_ids),
        })
    summaries.append(o0_summary)

    # O1: Extract Coarse Structure
    o1_summary = {"stage_type": "COARSE_STRUCTURE"}
    if coarse:
        o1_summary.update({
            "coarse_machine_count": len(coarse.machines),
            "coarse_job_count": len(coarse.jobs),
        })
    summaries.append(o1_summary)

    # O2: Extract Job Steps
    o2_summary = {"stage_type": "FINE_EXTRACTION"}
    if raw:
        machines_with_steps = set()
        total_steps = 0
        for job in raw.jobs:
            if job.steps:
                total_steps += len(job.steps)
                for step in job.steps:
                    machines_with_steps.add(step.machine_id)
        jobs_with_steps = sum(1 for job in raw.jobs if job.steps)
        o2_summary.update({
            "machines_with_steps": len(machines_with_steps),
            "jobs_with_steps": jobs_with_steps,
            "total_steps_extracted": total_steps,
        })
    summaries.append(o2_summary)

    # O3: Validate & Normalize
    o3_summary = {"stage_type": "NORMALIZATION"}
    if factory:
        o3_summary.update({
            "normalized_machines": len(factory.machines),
            "normalized_jobs": len(factory.jobs),
        })
    summaries.append(o3_summary)

    # O4: Coverage Assessment
    o4_summary = {"stage_type": "COVERAGE_ASSESSMENT"}
    if coverage:
        o4_summary.update({
            "detected_machines": sorted(list(coverage.detected_machines)),
            "detected_jobs": sorted(list(coverage.detected_jobs)),
            "parsed_machines": sorted(list(coverage.parsed_machines)),
            "parsed_jobs": sorted(list(coverage.parsed_jobs)),
            "machine_coverage_ratio": coverage.machine_coverage,
            "job_coverage_ratio": coverage.job_coverage,
            "missing_machines": sorted(list(coverage.missing_machines)),
            "missing_jobs": sorted(list(coverage.missing_jobs)),
            "is_100_percent_coverage": (coverage.machine_coverage == 1.0 and coverage.job_coverage == 1.0),
        })
    summaries.append(o4_summary)

    return summaries


def _build_decision_stage_summaries(
    intent_spec: "ScenarioSpec | None" = None,
    futures_specs: "list[ScenarioSpec] | None" = None,
    simulation_results: "list[SimulationResult] | None" = None,
    metrics_list: "list[ScenarioMetrics] | None" = None,
    briefing: "str | None" = None,
) -> list[dict]:
    """
    Build minimal summaries for decision stages (D1-D5).

    Returns list of 5 dicts, one per stage, with minimal required fields.
    """
    summaries = []

    # D1: Intent Agent
    d1_summary = {"stage_type": "INTENT_CLASSIFICATION"}
    if intent_spec:
        d1_summary.update({
            "intent_scenario_type": intent_spec.scenario_type.value,
            "intent_context_available": True,
        })
    summaries.append(d1_summary)

    # D2: Futures Agent
    d2_summary = {"stage_type": "FUTURES_EXPANSION"}
    if futures_specs:
        d2_summary.update({
            "generated_scenario_count": len(futures_specs),
            "futures_context_available": True,
        })
    summaries.append(d2_summary)

    # D3: Simulation
    d3_summary = {"stage_type": "SIMULATION"}
    if simulation_results is not None:
        d3_summary.update({
            "scenarios_run": len(simulation_results),
            "all_succeeded": True,  # If we got here, all succeeded
        })
    summaries.append(d3_summary)

    # D4: Metrics Computation
    d4_summary = {"stage_type": "METRICS_COMPUTATION"}
    if metrics_list is not None:
        d4_summary.update({
            "metrics_computed": len(metrics_list),
            "all_succeeded": True,  # If we got here, all succeeded
        })
    summaries.append(d4_summary)

    # D5: Briefing Generation
    d5_summary = {"stage_type": "BRIEFING_GENERATION"}
    if briefing is not None:
        d5_summary.update({
            "briefing_length_chars": len(briefing),
            "briefing_has_content": len(briefing) > 0,
        })
    summaries.append(d5_summary)

    return summaries


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


def run_onboarding(factory_text: str) -> tuple[FactoryConfig, OnboardingMeta, list[PipelineStageRecord]]:
    """Run onboarding pipeline: parse and normalize factory description with debug instrumentation.

    PRF1: Now constructs PipelineStageRecords for all 5 onboarding stages (O0-O4).

    Steps:
    1. Instantiate OnboardingAgent
    2. Call agent.run(factory_text) which orchestrates stages 0-4:
       - Stage 0: Extract explicit IDs (regex, deterministic)
       - Stage 1: Extract coarse structure (LLM)
       - Stage 2: Extract job steps (LLM)
       - Stage 3: Validate and normalize
       - Stage 4: Assess coverage (enforce 100%)
    3. Wrap each stage in instrumentation to build PipelineStageRecords
    4. On success: return factory, meta, and stage records with used_default_factory=False
    5. On ExtractionError: log warning, fallback to toy factory, return with used_default_factory=True

    Behavior:
    - Happy path: agent succeeds, all IDs covered → return onboarded factory, clean meta, success stages
    - Coverage mismatch: agent raises COVERAGE_MISMATCH → fallback to toy factory
    - LLM error: agent raises LLM_FAILURE → fallback to toy factory
    - Any error: log and fallback; no exception raised from this function

    Args:
        factory_text: Free-text factory description

    Returns:
        Tuple of (FactoryConfig, OnboardingMeta, list[PipelineStageRecord])
        - FactoryConfig is from agent (with 100% coverage) or toy factory (on fallback)
        - OnboardingMeta tracks whether fallback was used and error summary
        - List of 5 PipelineStageRecord for stages O0-O4

    Raises:
        Nothing; all failures are handled internally with fallback
    """
    logger.info(f"run_onboarding: factory_text len={len(factory_text)}")

    # Initialize stage records for O0-O4
    stage_records: list[PipelineStageRecord] = []

    # Tracking intermediate results for summaries
    ids = None
    coarse = None
    raw = None
    factory = None
    coverage = None

    try:
        agent = OnboardingAgent()

        # O0: Extract Explicit IDs (deterministic)
        try:
            ids = extract_explicit_ids(factory_text)
            o0_summary = {
                "stage_type": "EXPLICIT_ID_EXTRACTION",
                "explicit_machine_ids": sorted(list(ids.machine_ids)),
                "explicit_job_ids": sorted(list(ids.job_ids)),
                "total_ids_detected": len(ids.machine_ids) + len(ids.job_ids),
            }
            o0_record = PipelineStageRecord(
                id="O0",
                name="Extract Explicit IDs",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
                agent_model=None,
                summary=o0_summary,
                errors=[],
                payload_preview=None,
            )
            stage_records.append(o0_record)
        except Exception as e:
            logger.warning(f"O0 failed: {e}")
            o0_record = PipelineStageRecord(
                id="O0",
                name="Extract Explicit IDs",
                kind=StageKind.ONBOARDING,
                status=StageStatus.FAILED,
                agent_model=None,
                summary={"stage_type": "EXPLICIT_ID_EXTRACTION"},
                errors=[str(e)[:200]],
                payload_preview=None,
            )
            stage_records.append(o0_record)
            raise

        # O1: Extract Coarse Structure (LLM)
        try:
            coarse = extract_coarse_structure(factory_text, ids)
            o1_summary = {
                "stage_type": "COARSE_STRUCTURE",
                "coarse_machine_count": len(coarse.machines),
                "coarse_job_count": len(coarse.jobs),
            }
            o1_record = PipelineStageRecord(
                id="O1",
                name="Extract Coarse Structure",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
                agent_model="gpt-4.1",
                summary=o1_summary,
                errors=[],
                payload_preview=None,
            )
            stage_records.append(o1_record)
        except Exception as e:
            logger.warning(f"O1 failed: {e}")
            o1_record = PipelineStageRecord(
                id="O1",
                name="Extract Coarse Structure",
                kind=StageKind.ONBOARDING,
                status=StageStatus.FAILED,
                agent_model="gpt-4.1",
                summary={"stage_type": "COARSE_STRUCTURE"},
                errors=[str(e)[:200]],
                payload_preview=None,
            )
            stage_records.append(o1_record)
            raise

        # O2: Extract Steps (LLM)
        try:
            raw = extract_steps(factory_text, coarse)
            machines_with_steps = set()
            total_steps = 0
            for job in raw.jobs:
                if job.steps:
                    total_steps += len(job.steps)
                    for step in job.steps:
                        machines_with_steps.add(step.machine_id)
            jobs_with_steps = sum(1 for job in raw.jobs if job.steps)
            o2_summary = {
                "stage_type": "FINE_EXTRACTION",
                "machines_with_steps": len(machines_with_steps),
                "jobs_with_steps": jobs_with_steps,
                "total_steps_extracted": total_steps,
            }
            o2_record = PipelineStageRecord(
                id="O2",
                name="Extract Job Steps",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
                agent_model="gpt-4.1",
                summary=o2_summary,
                errors=[],
                payload_preview=None,
            )
            stage_records.append(o2_record)
        except Exception as e:
            logger.warning(f"O2 failed: {e}")
            o2_record = PipelineStageRecord(
                id="O2",
                name="Extract Job Steps",
                kind=StageKind.ONBOARDING,
                status=StageStatus.FAILED,
                agent_model="gpt-4.1",
                summary={"stage_type": "FINE_EXTRACTION"},
                errors=[str(e)[:200]],
                payload_preview=None,
            )
            stage_records.append(o2_record)
            raise

        # O3: Validate & Normalize
        try:
            factory = validate_and_normalize(raw)
            o3_summary = {
                "stage_type": "NORMALIZATION",
                "normalized_machines": len(factory.machines),
                "normalized_jobs": len(factory.jobs),
            }
            o3_record = PipelineStageRecord(
                id="O3",
                name="Validate & Normalize",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
                agent_model=None,
                summary=o3_summary,
                errors=[],
                payload_preview=None,
            )
            stage_records.append(o3_record)
        except Exception as e:
            logger.warning(f"O3 failed: {e}")
            o3_record = PipelineStageRecord(
                id="O3",
                name="Validate & Normalize",
                kind=StageKind.ONBOARDING,
                status=StageStatus.FAILED,
                agent_model=None,
                summary={"stage_type": "NORMALIZATION"},
                errors=[str(e)[:200]],
                payload_preview=None,
            )
            stage_records.append(o3_record)
            raise

        # O4: Assess Coverage
        try:
            coverage = assess_coverage(ids, factory)
            o4_summary = {
                "stage_type": "COVERAGE_ASSESSMENT",
                "detected_machines": sorted(list(coverage.detected_machines)),
                "detected_jobs": sorted(list(coverage.detected_jobs)),
                "parsed_machines": sorted(list(coverage.parsed_machines)),
                "parsed_jobs": sorted(list(coverage.parsed_jobs)),
                "machine_coverage_ratio": coverage.machine_coverage,
                "job_coverage_ratio": coverage.job_coverage,
                "missing_machines": sorted(list(coverage.missing_machines)),
                "missing_jobs": sorted(list(coverage.missing_jobs)),
                "is_100_percent_coverage": (coverage.machine_coverage == 1.0 and coverage.job_coverage == 1.0),
            }
            o4_record = PipelineStageRecord(
                id="O4",
                name="Assess Coverage",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
                agent_model=None,
                summary=o4_summary,
                errors=[],
                payload_preview=None,
            )
            stage_records.append(o4_record)

            # Check coverage enforcement
            if coverage.machine_coverage < 1.0 or coverage.job_coverage < 1.0:
                raise ExtractionError(
                    code="COVERAGE_MISMATCH",
                    message=f"coverage mismatch: missing machines {sorted(coverage.missing_machines)}, "
                            f"missing jobs {sorted(coverage.missing_jobs)}",
                    details={
                        "missing_machines": sorted(coverage.missing_machines),
                        "missing_jobs": sorted(coverage.missing_jobs),
                        "machine_coverage": coverage.machine_coverage,
                        "job_coverage": coverage.job_coverage,
                    },
                )
        except Exception as e:
            logger.warning(f"O4 failed: {e}")
            o4_record = PipelineStageRecord(
                id="O4",
                name="Assess Coverage",
                kind=StageKind.ONBOARDING,
                status=StageStatus.FAILED,
                agent_model=None,
                summary={"stage_type": "COVERAGE_ASSESSMENT"},
                errors=[str(e)[:200]],
                payload_preview=None,
            )
            stage_records.append(o4_record)
            raise

        # Success
        used_default_factory = False
        onboarding_errors: list[str] = []
        logger.info(
            f"run_onboarding: success - factory produced {len(factory.machines)} machines, "
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

    return factory, meta, stage_records


def run_decision_pipeline(
    factory: FactoryConfig,
    situation_text: str,
    meta: OnboardingMeta,
) -> tuple[dict, list[PipelineStageRecord]]:
    """Run decision + simulation pipeline with a given factory and onboarding metadata.

    PRF1: Now constructs PipelineStageRecords for all 5 decision stages (D1-D5).

    Steps:
    1. IntentAgent parses situation_text → ScenarioSpec (D1)
    2. FuturesAgent expands → list of ScenarioSpecs (1-3) (D2)
    3. For each scenario: simulate() + compute_metrics() (D3, D4)
    4. BriefingAgent generates markdown briefing (D5)
    5. Return dict with specs, metrics, briefing, meta, factory + stage records

    Args:
        factory: FactoryConfig to use for all scenarios
        situation_text: Free-text description of today's situation
        meta: OnboardingMeta from onboarding phase (threaded through)

    Returns:
        Tuple of (dict, list[PipelineStageRecord])
        - dict containing:
            - "factory": FactoryConfig (input factory)
            - "specs": list[ScenarioSpec] (scenarios from FuturesAgent)
            - "metrics": list[ScenarioMetrics] (one per scenario)
            - "briefing": str (markdown)
            - "meta": OnboardingMeta (input meta, threaded through)
        - list of 5 PipelineStageRecords for stages D1-D5

    Raises:
        RuntimeError: If FuturesAgent returns no scenarios
    """
    logger.debug(
        f"run_decision_pipeline: situation_text={situation_text[:100]}{'...' if len(situation_text) > 100 else ''}"
    )

    # Initialize stage records for D1-D5
    stage_records: list[PipelineStageRecord] = []

    # Initialize agents
    intent_agent = IntentAgent()
    futures_agent = FuturesAgent()
    briefing_agent = BriefingAgent()

    # D1: IntentAgent parses situation text
    logger.debug("   D1: IntentAgent parsing situation text...")
    try:
        base_spec, intent_context = intent_agent.run(situation_text, factory=factory)
        d1_summary = {
            "stage_type": "INTENT_CLASSIFICATION",
            "intent_scenario_type": base_spec.scenario_type.value,
            "intent_context_available": bool(intent_context),
        }
        d1_record = PipelineStageRecord(
            id="D1",
            name="Intent Classification",
            kind=StageKind.DECISION,
            status=StageStatus.SUCCESS,
            agent_model="gpt-4.1",
            summary=d1_summary,
            errors=[],
            payload_preview=None,
        )
        stage_records.append(d1_record)
        logger.debug(f"   D1: type={base_spec.scenario_type.value}")
    except Exception as e:
        logger.warning(f"D1 failed: {e}")
        d1_record = PipelineStageRecord(
            id="D1",
            name="Intent Classification",
            kind=StageKind.DECISION,
            status=StageStatus.FAILED,
            agent_model="gpt-4.1",
            summary={"stage_type": "INTENT_CLASSIFICATION"},
            errors=[str(e)[:200]],
            payload_preview=None,
        )
        stage_records.append(d1_record)
        raise

    # D2: FuturesAgent expands to candidate scenarios
    logger.debug("   D2: FuturesAgent expanding scenarios...")
    try:
        specs, futures_context = futures_agent.run(base_spec, factory=factory)
        if not specs:
            logger.error("FuturesAgent returned no scenarios!")
            raise RuntimeError("FuturesAgent returned no scenarios.")
        d2_summary = {
            "stage_type": "FUTURES_EXPANSION",
            "generated_scenario_count": len(specs),
            "futures_context_available": bool(futures_context),
        }
        d2_record = PipelineStageRecord(
            id="D2",
            name="Futures Expansion",
            kind=StageKind.DECISION,
            status=StageStatus.SUCCESS,
            agent_model="gpt-4.1",
            summary=d2_summary,
            errors=[],
            payload_preview=None,
        )
        stage_records.append(d2_record)
        logger.debug(f"   D2: {len(specs)} scenarios")
    except Exception as e:
        logger.warning(f"D2 failed: {e}")
        d2_record = PipelineStageRecord(
            id="D2",
            name="Futures Expansion",
            kind=StageKind.DECISION,
            status=StageStatus.FAILED,
            agent_model="gpt-4.1",
            summary={"stage_type": "FUTURES_EXPANSION"},
            errors=[str(e)[:200]],
            payload_preview=None,
        )
        stage_records.append(d2_record)
        raise

    # D3: Run simulation for each scenario
    logger.debug("   D3: Running simulations...")
    try:
        results: list[SimulationResult] = []
        for i, spec in enumerate(specs):
            result: SimulationResult = simulate(factory, spec)
            results.append(result)
            logger.debug(f"      [Scenario {i+1}/{len(specs)}] simulated")

        d3_summary = {
            "stage_type": "SIMULATION",
            "scenarios_run": len(results),
            "all_succeeded": True,
        }
        d3_record = PipelineStageRecord(
            id="D3",
            name="Simulation",
            kind=StageKind.SIMULATION,
            status=StageStatus.SUCCESS,
            agent_model=None,
            summary=d3_summary,
            errors=[],
            payload_preview=None,
        )
        stage_records.append(d3_record)
    except Exception as e:
        logger.warning(f"D3 failed: {e}")
        d3_record = PipelineStageRecord(
            id="D3",
            name="Simulation",
            kind=StageKind.SIMULATION,
            status=StageStatus.FAILED,
            agent_model=None,
            summary={"stage_type": "SIMULATION"},
            errors=[str(e)[:200]],
            payload_preview=None,
        )
        stage_records.append(d3_record)
        raise

    # D4: Compute metrics for each scenario
    logger.debug("   D4: Computing metrics...")
    try:
        metrics_list: list[ScenarioMetrics] = []
        for i, result in enumerate(results):
            metrics: ScenarioMetrics = compute_metrics(factory, result)
            metrics_list.append(metrics)
            logger.debug(f"      [Scenario {i+1}/{len(results)}] metrics computed")

        d4_summary = {
            "stage_type": "METRICS_COMPUTATION",
            "metrics_computed": len(metrics_list),
            "all_succeeded": True,
        }
        d4_record = PipelineStageRecord(
            id="D4",
            name="Metrics Computation",
            kind=StageKind.SIMULATION,
            status=StageStatus.SUCCESS,
            agent_model=None,
            summary=d4_summary,
            errors=[],
            payload_preview=None,
        )
        stage_records.append(d4_record)
    except Exception as e:
        logger.warning(f"D4 failed: {e}")
        d4_record = PipelineStageRecord(
            id="D4",
            name="Metrics Computation",
            kind=StageKind.SIMULATION,
            status=StageStatus.FAILED,
            agent_model=None,
            summary={"stage_type": "METRICS_COMPUTATION"},
            errors=[str(e)[:200]],
            payload_preview=None,
        )
        stage_records.append(d4_record)
        raise

    # D5: Generate briefing
    logger.debug("   D5: BriefingAgent generating briefing...")
    try:
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
        briefing: str = briefing_agent.run(
            primary_metrics,
            context=context,
            intent_context=intent_context,
            futures_context=futures_context,
        )

        d5_summary = {
            "stage_type": "BRIEFING_GENERATION",
            "briefing_length_chars": len(briefing),
            "briefing_has_content": len(briefing) > 0,
        }
        d5_record = PipelineStageRecord(
            id="D5",
            name="Briefing Generation",
            kind=StageKind.DECISION,
            status=StageStatus.SUCCESS,
            agent_model="gpt-4.1",
            summary=d5_summary,
            errors=[],
            payload_preview=None,
        )
        stage_records.append(d5_record)
        logger.debug(f"   D5: {len(briefing)} chars")
    except Exception as e:
        logger.warning(f"D5 failed: {e}")
        d5_record = PipelineStageRecord(
            id="D5",
            name="Briefing Generation",
            kind=StageKind.DECISION,
            status=StageStatus.FAILED,
            agent_model="gpt-4.1",
            summary={"stage_type": "BRIEFING_GENERATION"},
            errors=[str(e)[:200]],
            payload_preview=None,
        )
        stage_records.append(d5_record)
        raise

    logger.info(
        f"run_decision_pipeline complete: {len(specs)} scenarios, "
        f"{len(metrics_list)} metrics"
    )

    return (
        {
            "factory": factory,
            "specs": specs,
            "metrics": metrics_list,
            "briefing": briefing,
            "meta": meta,
        },
        stage_records,
    )


def run_onboarded_pipeline(factory_text: str, situation_text: str) -> PipelineRunResult:
    """Run complete pipeline: onboarding + decision + simulation with debug instrumentation.

    PRF1: This function now builds and returns a PipelineDebugPayload internally
    but does NOT expose it via HTTP (that is deferred to a future PR).

    This glues run_onboarding and run_decision_pipeline together:
    1. run_onboarding(factory_text) → (factory, meta, onboarding_stages)
    2. run_decision_pipeline(factory, situation_text, meta) → (result_dict, decision_stages)
    3. Assemble PipelineDebugPayload from all 10 stages
    4. Return PipelineRunResult with debug payload attached (not exposed via HTTP)

    Args:
        factory_text: Free-text factory description
        situation_text: Free-text situation description

    Returns:
        PipelineRunResult with fields:
            - factory: FactoryConfig
            - specs: list[ScenarioSpec]
            - metrics: list[ScenarioMetrics]
            - briefing: str (markdown)
            - meta: OnboardingMeta
            - debug: PipelineDebugPayload | None (populated in PRF1, not exposed via HTTP yet)

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
    factory, meta, onboarding_stages = run_onboarding(factory_text)
    logger.info(f"   ✓ Factory: {len(factory.machines)} machines, {len(factory.jobs)} jobs")
    logger.info(f"   ✓ Used default: {meta.used_default_factory}, errors: {len(meta.onboarding_errors)}")

    # Phase 2: Decision + Simulation
    logger.info("Phase 2️⃣ Decision pipeline (intent → futures → simulation → briefing)...")
    result_dict, decision_stages = run_decision_pipeline(factory, situation_text, meta)
    logger.info(f"   ✓ Scenarios: {len(result_dict['specs'])}")
    logger.info(f"   ✓ Briefing: {len(result_dict['briefing'])} chars")

    logger.info("=" * 80)
    logger.info("✅ run_onboarded_pipeline completed successfully!")
    logger.info(f"   Factory: {len(factory.machines)} machines, {len(factory.jobs)} jobs")
    logger.info(f"   Scenarios: {len(result_dict['specs'])}")
    logger.info(f"   Used default factory: {meta.used_default_factory}")
    logger.info("=" * 80)

    # PRF1: Assemble debug payload from all 10 stages
    all_stages = onboarding_stages + decision_stages
    debug_payload = build_payload(factory_text, situation_text, all_stages)

    logger.debug(f"PipelineDebugPayload assembled: {len(all_stages)} stages, overall_status={debug_payload.overall_status}")

    # Return PipelineRunResult with debug payload (not exposed via HTTP in PRF1)
    return PipelineRunResult(
        factory=result_dict["factory"],
        specs=result_dict["specs"],
        metrics=result_dict["metrics"],
        briefing=result_dict["briefing"],
        meta=result_dict["meta"],
        debug=debug_payload,
    )
