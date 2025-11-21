"""
Adversarial Evaluation Harness CLI

Runs a curated set of adversarial/messy inputs through the onboarding and
simulation pipelines, checks invariants, and generates structured JSON reports.

Usage:
    python -m backend.eval.run_adversarial [OPTIONS]

Options:
    --http              Exercise FastAPI endpoints (default: False)
    --use-llm           Call the real LLM (default: True)
    --case-id ID        Run only specific case(s); may be repeated
    --out-dir DIR       Output directory for reports (default: backend/eval/reports)
    --help              Show this message and exit

Examples:
    # Run all cases with LLM, no HTTP
    python -m backend.eval.run_adversarial --use-llm

    # Run specific case with HTTP
    python -m backend.eval.run_adversarial --use-llm --http --case-id messy_sop

    # Run all cases, write reports to custom directory
    python -m backend.eval.run_adversarial --use-llm --out-dir /tmp/reports
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi.testclient import TestClient

from backend.agents import (
    BriefingAgent,
    FuturesAgent,
    IntentAgent,
    OnboardingAgent,
)
from backend.eval.invariants import (
    check_factory_invariants,
    check_metrics_invariants,
)
from backend.metrics import compute_metrics
from backend.models import FactoryConfig, OnboardingMeta, ScenarioMetrics, ScenarioSpec
from backend.onboarding import extract_explicit_ids, enumerate_entities, compute_coverage
from backend.orchestrator import (
    is_toy_factory,
    run_decision_pipeline,
    run_onboarding,
)
from backend.server import app
from backend.sim import simulate


def load_cases(yaml_path: str) -> list[dict[str, Any]]:
    """Load adversarial cases from YAML file."""
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


def run_onboarding_phase(
    factory_description: str, use_llm: bool = True
) -> tuple[FactoryConfig, OnboardingMeta, dict[str, Any]]:
    """
    Run the onboarding phase and capture intermediate outputs.

    Returns:
        (final_factory, meta, debug_info)
    """
    debug_info = {}

    # Run the orchestrator function
    factory, meta = run_onboarding(factory_description)

    # For debugging, optionally capture if we used the default factory
    debug_info["used_default_factory"] = meta.used_default_factory

    return factory, meta, debug_info


def run_decision_phase(
    factory: FactoryConfig,
    situation_text: str,
    meta: OnboardingMeta,
    use_llm: bool = True,
) -> dict[str, Any]:
    """
    Run the decision pipeline (intent → futures → simulation → briefing).

    Returns:
        Dict with: specs, metrics, briefing, agents (intent_spec, intent_context, etc.)
    """
    agents_info = {}

    # Run decision pipeline
    result = run_decision_pipeline(factory, situation_text, meta)

    # Extract agent-level outputs for reporting
    # Note: these are computed inline within run_decision_pipeline
    # For now, we'll capture what's available via the result dict
    agents_info["intent_spec"] = None  # Not directly exposed, but in result
    agents_info["intent_context"] = None  # Would need to refactor to expose
    agents_info["futures_specs"] = None
    agents_info["futures_context"] = None

    return {
        "specs": result.get("specs", []),
        "metrics": result.get("metrics", []),
        "briefing": result.get("briefing", ""),
        "agents": agents_info,
    }


def run_http_phase(
    case: dict[str, Any], use_llm: bool = True
) -> dict[str, Any]:
    """
    Run HTTP endpoints via FastAPI TestClient.

    Returns:
        Dict with: onboard_response, simulate_response
    """
    client = TestClient(app)
    http_info = {
        "onboard_response": None,
        "simulate_response": None,
    }

    # POST /api/onboard
    try:
        onboard_req = {"factory_description": case["factory_description"]}
        onboard_resp = client.post("/api/onboard", json=onboard_req)
        if onboard_resp.status_code == 200:
            http_info["onboard_response"] = onboard_resp.json()
    except Exception as e:
        http_info["onboard_response"] = {"error": str(e)}

    # POST /api/simulate (if kind == "simulate")
    if case["kind"] == "simulate":
        try:
            simulate_req = {
                "factory_description": case["factory_description"],
                "situation_text": case.get("situation_text", ""),
            }
            simulate_resp = client.post("/api/simulate", json=simulate_req)
            if simulate_resp.status_code == 200:
                http_info["simulate_response"] = simulate_resp.json()
        except Exception as e:
            http_info["simulate_response"] = {"error": str(e)}

    return http_info


def serialize_for_json(obj: Any) -> Any:
    """
    Convert Pydantic models and enums to JSON-serializable types.
    """
    if hasattr(obj, "model_dump"):
        # Pydantic BaseModel
        return obj.model_dump()
    elif hasattr(obj, "value"):
        # Enum
        return obj.value
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    else:
        return obj


def build_report(
    case: dict[str, Any],
    factory: FactoryConfig,
    meta: OnboardingMeta,
    decision_result: Optional[dict[str, Any]],
    http_result: Optional[dict[str, Any]],
    debug_info: dict[str, Any],
) -> dict[str, Any]:
    """Build the structured JSON report for a single case."""
    report = {
        "case": case,
        "onboarding": {
            "factory": serialize_for_json(factory),
            "meta": serialize_for_json(meta),
            "debug": debug_info,
        },
        "agents": {},
        "simulation": None,
        "http": http_result or {},
        "invariants": {
            "factory_invariants_ok": True,
            "metrics_invariants_ok": True,
            "errors": [],
        },
        "coverage": None,  # PR7: coverage metrics
    }

    # PR7: Compute coverage metrics
    try:
        factory_text = case.get("factory_description", "")
        explicit_ids = extract_explicit_ids(factory_text)

        # Attempt to enumerate entities if text contains explicit IDs
        if explicit_ids.machine_ids or explicit_ids.job_ids:
            try:
                entities = enumerate_entities(factory_text, explicit_ids.machine_ids, explicit_ids.job_ids)
                coverage_report = compute_coverage(explicit_ids, entities)
                report["coverage"] = {
                    "detected_machine_ids": sorted(list(coverage_report.detected_machine_ids)),
                    "detected_job_ids": sorted(list(coverage_report.detected_job_ids)),
                    "enumerated_machine_ids": sorted(list(coverage_report.enumerated_machine_ids)),
                    "enumerated_job_ids": sorted(list(coverage_report.enumerated_job_ids)),
                    "missing_machines": sorted(list(coverage_report.missing_machines)),
                    "missing_jobs": sorted(list(coverage_report.missing_jobs)),
                    "machine_coverage": coverage_report.machine_coverage,
                    "job_coverage": coverage_report.job_coverage,
                }
            except Exception as e:
                # Enumeration failed; record the error but don't fail the report
                report["coverage"] = {
                    "error": f"Enumeration failed: {type(e).__name__}: {str(e)[:100]}",
                    "detected_machine_ids": sorted(list(explicit_ids.machine_ids)),
                    "detected_job_ids": sorted(list(explicit_ids.job_ids)),
                }
    except Exception as e:
        # Even extraction failed; record it
        report["coverage"] = {"error": f"Coverage computation failed: {str(e)[:100]}"}

    # Add decision phase results if applicable
    if decision_result:
        report["agents"] = decision_result.get("agents", {})
        report["simulation"] = {
            "specs": serialize_for_json(decision_result.get("specs", [])),
            "metrics": serialize_for_json(decision_result.get("metrics", [])),
            "briefing": decision_result.get("briefing", ""),
        }

    # Check invariants
    factory_violations = check_factory_invariants(factory)
    if factory_violations:
        report["invariants"]["factory_invariants_ok"] = False
        report["invariants"]["errors"].extend(factory_violations)

    if decision_result and decision_result.get("metrics"):
        metrics_violations = check_metrics_invariants(
            factory,
            decision_result.get("specs", []),
            decision_result.get("metrics", []),
        )
        if metrics_violations:
            report["invariants"]["metrics_invariants_ok"] = False
            report["invariants"]["errors"].extend(metrics_violations)

    return report


def determine_onboarding_status(meta: OnboardingMeta) -> str:
    """
    Summarize onboarding status as OK, DEGRADED, or FALLBACK.
    """
    if meta.used_default_factory:
        return "FALLBACK"
    elif meta.onboarding_errors:
        return "DEGRADED"
    else:
        return "OK"


def run_case(
    case: dict[str, Any],
    use_llm: bool = True,
    use_http: bool = False,
) -> tuple[dict[str, Any], str]:
    """
    Run a single adversarial case.

    Returns:
        (report_dict, status_line)
    """
    case_id = case["id"]
    kind = case["kind"]

    try:
        # Phase 1: Onboarding
        factory, meta, debug_info = run_onboarding_phase(
            case["factory_description"], use_llm=use_llm
        )

        decision_result = None
        http_result = None

        # Phase 2: Decision pipeline (if kind == "simulate")
        if kind == "simulate":
            decision_result = run_decision_phase(
                factory,
                case.get("situation_text", ""),
                meta,
                use_llm=use_llm,
            )

        # Phase 3: HTTP (if requested)
        if use_http:
            http_result = run_http_phase(case, use_llm=use_llm)

        # Build report
        report = build_report(
            case, factory, meta, decision_result, http_result, debug_info
        )

        # Determine status for summary line
        onboarding_status = determine_onboarding_status(meta)
        used_default = "true" if meta.used_default_factory else "false"
        invariants_ok = report["invariants"]["factory_invariants_ok"] and (
            report["invariants"]["metrics_invariants_ok"]
            if decision_result
            else True
        )
        invariants_status = "OK" if invariants_ok else "FAILED"

        # PR7: Add coverage to status line
        coverage_info = ""
        if report.get("coverage"):
            if "error" in report["coverage"]:
                coverage_info = " coverage=ERROR"
            else:
                machine_cov = report["coverage"].get("machine_coverage", 1.0)
                job_cov = report["coverage"].get("job_coverage", 1.0)
                coverage_info = f" coverage=machines:{machine_cov:.0%}/jobs:{job_cov:.0%}"

        if not invariants_ok:
            error_count = len(report["invariants"]["errors"])
            status_line = (
                f"[{case_id}] kind={kind} onboarding={onboarding_status} "
                f"used_default_factory={used_default} invariants={invariants_status} "
                f"({error_count} violations){coverage_info}"
            )
        else:
            status_line = (
                f"[{case_id}] kind={kind} onboarding={onboarding_status} "
                f"used_default_factory={used_default} invariants={invariants_status}{coverage_info}"
            )

        return report, status_line

    except Exception as e:
        # Error running case
        status_line = f"[{case_id}] ERROR: {str(e)}"
        error_report = {
            "case": case,
            "error": str(e),
            "onboarding": None,
            "agents": None,
            "simulation": None,
            "http": None,
            "invariants": {"errors": [str(e)]},
        }
        return error_report, status_line


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Adversarial Evaluation Harness for factory-simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--http",
        action="store_true",
        default=False,
        help="Exercise FastAPI endpoints via TestClient",
    )

    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=True,
        help="Call the real LLM (default: True)",
    )

    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="Run only specific case(s); may be repeated",
    )

    parser.add_argument(
        "--out-dir",
        default="backend/eval/reports",
        help="Output directory for JSON reports (default: backend/eval/reports)",
    )

    args = parser.parse_args()

    # Resolve paths
    harness_dir = Path(__file__).parent
    cases_yaml = harness_dir / "adversarial_cases.yaml"
    out_dir = Path(args.out_dir)

    if not cases_yaml.exists():
        print(f"ERROR: Cases file not found: {cases_yaml}", file=sys.stderr)
        sys.exit(1)

    # Create timestamped report directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = out_dir / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    # Load cases
    all_cases = load_cases(str(cases_yaml))
    print(f"Loaded {len(all_cases)} cases from {cases_yaml}")

    # Filter by case IDs if specified
    if args.case_ids:
        case_ids_set = set(args.case_ids)
        selected_cases = [c for c in all_cases if c["id"] in case_ids_set]
        if not selected_cases:
            print(
                f"WARNING: No cases matched specified IDs: {args.case_ids}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        selected_cases = all_cases

    print(f"Running {len(selected_cases)} case(s)...\n")

    # Run cases
    reports = []
    status_lines = []
    for case in selected_cases:
        report, status_line = run_case(
            case,
            use_llm=args.use_llm,
            use_http=args.http,
        )
        reports.append(report)
        status_lines.append(status_line)
        print(status_line)

    # Write reports
    for report in reports:
        case_id = report["case"]["id"]
        report_path = report_dir / f"{case_id}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

    # Print summary
    print()
    ok_count = sum(
        1
        for r in reports
        if r.get("invariants", {}).get("factory_invariants_ok", False)
        and (
            r.get("simulation") is None
            or r.get("invariants", {}).get("metrics_invariants_ok", False)
        )
    )
    error_count = len(reports) - ok_count

    print(f"ran {len(reports)} cases: {ok_count} OK, {error_count} with violations")
    print(f"reports written to {report_dir}")


if __name__ == "__main__":
    main()
