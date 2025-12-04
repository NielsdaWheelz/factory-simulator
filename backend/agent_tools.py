"""
Agent Tools Module

Defines the Tool interface and implements the tools available to the agent.
Each tool wraps existing functionality (onboarding, simulation, metrics) and
exposes it to the LLM via a standard interface.

Tools are the agent's "hands" - discrete, well-defined actions it can choose from.
"""

import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Type
from pydantic import BaseModel, Field

from .agent_types import (
    AgentState, 
    ToolCall, 
    ToolResult,
    FactoryEntities,
    FactoryRouting,
    FactoryParameters,
    FactoryValidationReport,
    OperationType,
    DataPreview,
)
from .models import FactoryConfig, ScenarioSpec, ScenarioType, ScenarioMetrics, Machine, Job, Step
from .world import build_toy_factory
from .sim import simulate
from .metrics import compute_metrics
from .onboarding import (
    extract_explicit_ids,
    extract_coarse_structure,
    extract_steps,
    validate_and_normalize,
    validate_and_normalize_with_diagnostics,
    assess_coverage,
    assemble_factory,
    compute_onboarding_score,
    estimate_onboarding_coverage,
    run_multi_pass_onboarding,
    compute_factory_diff,
    generate_clarifying_questions,
    ExtractionError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL INTERFACE (Abstract Base Class)
# =============================================================================

class Tool(ABC):
    """
    Abstract base class for all tools.
    
    Each tool must define:
    - name: Unique identifier the LLM uses to call it
    - description: What the tool does (shown to LLM)
    - args_schema: Pydantic model defining required arguments
    - execute(): The actual implementation
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        pass
    
    @property
    @abstractmethod
    def args_schema(self) -> Type[BaseModel]:
        """Pydantic model defining the tool's arguments."""
        pass
    
    @abstractmethod
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        """
        Execute the tool with the given arguments.
        
        Args:
            args: Dictionary of arguments (validated against args_schema)
            state: Current agent state (for reading context, NOT for mutation)
        
        Returns:
            ToolResult with success/failure and output/error
        """
        pass
    
    def to_openai_schema(self) -> dict:
        """Convert tool definition to OpenAI function calling format."""
        schema = self.args_schema.model_json_schema()
        # Remove the title field that Pydantic adds
        schema.pop("title", None)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            }
        }


# =============================================================================
# TOOL ARGUMENT SCHEMAS
# =============================================================================

class ParseFactoryArgs(BaseModel):
    """Arguments for the parse_factory tool."""
    description: str = Field(
        ..., 
        description="Free-text description of the factory (machines, jobs, routing, due times)"
    )


class SimulateScenarioArgs(BaseModel):
    """Arguments for the simulate_scenario tool."""
    scenario_type: str = Field(
        ..., 
        description="Type of scenario: 'BASELINE', 'RUSH_ARRIVES', 'M2_SLOWDOWN', or 'MACHINE_SLOWDOWN'"
    )
    rush_job_id: str | None = Field(
        default=None,
        description="Job ID to rush (required for RUSH_ARRIVES)"
    )
    slowdown_factor: int | None = Field(
        default=None,
        description="Slowdown multiplier (required for M2_SLOWDOWN/MACHINE_SLOWDOWN, must be >= 2)"
    )
    slowdown_machine_id: str | None = Field(
        default=None,
        description="Machine ID to slow down (required for MACHINE_SLOWDOWN, ignored for M2_SLOWDOWN)"
    )


class GetFactoryInfoArgs(BaseModel):
    """Arguments for the get_factory_info tool (no args needed)."""
    pass


class FinalReportArgs(BaseModel):
    """Arguments for generating the final report."""
    summary: str = Field(
        ...,
        description="A brief summary of what was analyzed and key findings"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="List of actionable recommendations for the user"
    )
    risks: list[str] = Field(
        default_factory=list,
        description="List of identified risks or concerns"
    )


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

class ParseFactoryTool(Tool):
    """
    Parses a free-text factory description into a structured FactoryConfig.
    
    Uses the multi-stage onboarding pipeline:
    - Extract explicit IDs (regex)
    - Extract coarse structure (LLM)
    - Extract steps and timings (LLM)
    - Validate and normalize
    - Assess coverage
    """
    
    @property
    def name(self) -> str:
        return "parse_factory"
    
    @property
    def description(self) -> str:
        return (
            "Parse a free-text factory description into a structured configuration. "
            "Use this when you need to understand the factory's machines, jobs, and routing. "
            "Returns the parsed factory or an error if parsing fails."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ParseFactoryArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        factory_text = args["description"]
        
        # Track issues for scoring
        normalization_repair_count = 0
        coverage_issue_count = 0
        alt_conflict_count = 0
        
        # Close any existing data flow step from the main loop
        # We'll create our own sub-steps for each onboarding phase
        state.finish_data_flow_step(status="done")
        
        try:
            # =================================================================
            # O0: Explicit ID Extraction (regex-based, no LLM)
            # =================================================================
            state.start_data_flow_step(
                step_id=-10,
                step_type="onboarding_o0",
                step_name="🔍 O0: Explicit ID Extraction",
                step_input=DataPreview(
                    label="factory_text",
                    type_name="str",
                    preview=factory_text[:80] + ("..." if len(factory_text) > 80 else ""),
                    size=f"{len(factory_text)} chars",
                ),
            )
            state.add_thought("O0: Extracting explicit IDs from text (regex-based)")
            
            t0 = time.time()
            ids = extract_explicit_ids(factory_text)
            latency_ids = int((time.time() - t0) * 1000)
            logger.debug(f"Extracted IDs: {len(ids.machine_ids)} machines, {len(ids.job_ids)} jobs")
            
            state.add_operation(
                op_type=OperationType.FUNCTION,
                name="extract_explicit_ids",
                duration_ms=latency_ids,
                inputs=[DataPreview(label="factory_text", type_name="str", preview=factory_text[:60] + "...", size=f"{len(factory_text)} chars")],
                outputs=[DataPreview(
                    label="ids",
                    type_name="ExplicitIds",
                    preview=f"machines: {list(ids.machine_ids)}, jobs: {list(ids.job_ids)}",
                    size=f"{len(ids.machine_ids)} machines, {len(ids.job_ids)} jobs",
                )],
            )
            
            ids_found = len(ids.machine_ids) + len(ids.job_ids)
            state.finish_data_flow_step(
                status="done",
                step_output=DataPreview(
                    label="explicit_ids",
                    type_name="ExplicitIds",
                    preview=f"{len(ids.machine_ids)} machines, {len(ids.job_ids)} jobs" if ids_found > 0 else "none found (will rely on LLM)",
                    size=f"{ids_found} total IDs",
                ),
            )
            
            # =================================================================
            # O1: Multi-Pass Entity & Routing Extraction (LLM-based)
            # =================================================================
            state.start_data_flow_step(
                step_id=-11,
                step_type="onboarding_o1",
                step_name="🤖 O1: Multi-Pass Extraction",
                step_input=DataPreview(
                    label="factory_text",
                    type_name="str",
                    preview="...",
                    size=f"{len(factory_text)} chars",
                ),
            )
            state.add_thought("O1: Running multi-pass onboarding (entity extraction, routing, parameters)")
            
            t0 = time.time()
            multi_pass_result = run_multi_pass_onboarding(factory_text, num_passes=2)
            latency_multi_pass = int((time.time() - t0) * 1000)
            
            # Track the multi-pass operation
            state.add_operation(
                op_type=OperationType.LLM,
                name="run_multi_pass_onboarding",
                duration_ms=latency_multi_pass,
                inputs=[
                    DataPreview(label="factory_text", type_name="str", preview="...", size=f"{len(factory_text)} chars"),
                    DataPreview(label="num_passes", type_name="int", preview="2", size=None),
                ],
                outputs=[DataPreview(
                    label="multi_pass_result",
                    type_name="MultiPassResult",
                    preview=f"primary: {multi_pass_result.primary_mode}, alts: {len(multi_pass_result.alt_configs)}, conflicts: {multi_pass_result.alt_conflict_count}",
                    size=f"{len(multi_pass_result.all_pass_results)} passes",
                )],
                schema_name="MultiPassResult",
            )
            
            # Record LLM calls from passes (approximate: 2 calls per pass)
            for pass_result in multi_pass_result.all_pass_results:
                if pass_result.success:
                    state.record_llm_call(
                        schema_name="CoarseStructure",
                        latency_ms=latency_multi_pass // (2 * len(multi_pass_result.all_pass_results)),
                        purpose=f"Extract entities ({pass_result.mode} mode)",
                    )
                    state.record_llm_call(
                        schema_name="RawFactoryConfig",
                        latency_ms=latency_multi_pass // (2 * len(multi_pass_result.all_pass_results)),
                        purpose=f"Extract routing/timing ({pass_result.mode} mode)",
                    )
            
            # Check if we got a valid config
            if multi_pass_result.primary_config is None:
                # All passes failed - aggregate errors
                error_messages = [
                    f"{pr.mode}: {pr.error}" 
                    for pr in multi_pass_result.all_pass_results 
                    if pr.error
                ]
                combined_error = "; ".join(error_messages[:3])  # Limit to first 3
                
                state.finish_data_flow_step(
                    status="failed",
                    step_output=DataPreview(
                        label="error",
                        type_name="str",
                        preview=combined_error[:80],
                        size=None,
                    ),
                )
                
                # Create diagnostics summary step even on failure
                self._create_diagnostics_summary_step(
                    state=state,
                    score=0,
                    trust="LOW_TRUST",
                    coverage_issues=2,
                    normalization_repairs=0,
                    alt_conflicts=0,
                    factory=None,
                )
                
                # Compute score for failure case
                score, trust = compute_onboarding_score(
                    coverage_issues=2,
                    normalization_repairs=0,
                    alt_conflicts=0,
                )
                state.set_onboarding_score(score, trust)
                state.add_onboarding_issue(
                    issue_type="extraction_error",
                    severity="error",
                    message=f"All extraction passes failed: {combined_error}",
                    related_ids=None,
                )
                
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error=f"All extraction passes failed: {combined_error}"
                )
            
            factory = multi_pass_result.primary_config
            alt_conflict_count = multi_pass_result.alt_conflict_count
            
            # Aggregate normalization warnings from successful passes
            for pass_result in multi_pass_result.all_pass_results:
                if pass_result.success:
                    for warning in pass_result.normalization_warnings:
                        normalization_repair_count += 1
                        # Try to extract related IDs from the warning message
                        related_ids = []
                        for job in factory.jobs:
                            if job.id in warning:
                                related_ids.append(job.id)
                        for machine in factory.machines:
                            if machine.id in warning:
                                related_ids.append(machine.id)
                        
                        state.add_onboarding_issue(
                            issue_type="normalization_repair",
                            severity="warning",
                            message=warning,
                            related_ids=related_ids if related_ids else None,
                        )
                    # Only count from primary pass to avoid double-counting
                    break
            
            state.finish_data_flow_step(
                status="done",
                step_output=DataPreview(
                    label="factory",
                    type_name="FactoryConfig",
                    preview=f"machines: {[m.id for m in factory.machines]}, jobs: {[j.id for j in factory.jobs]}",
                    size=f"{len(factory.machines)} machines, {len(factory.jobs)} jobs",
                ),
            )
            
            # =================================================================
            # O2: Normalization & Validation
            # =================================================================
            state.start_data_flow_step(
                step_id=-12,
                step_type="onboarding_o2",
                step_name="✓ O2: Validation & Normalization",
                step_input=DataPreview(
                    label="raw_config",
                    type_name="RawFactoryConfig",
                    preview=f"{len(factory.machines)}M, {len(factory.jobs)}J",
                    size=None,
                ),
            )
            state.add_thought(f"O2: Validation complete - {normalization_repair_count} repairs applied")
            
            state.add_operation(
                op_type=OperationType.VALIDATION,
                name="validate_and_normalize",
                duration_ms=0,  # Already included in multi-pass
                inputs=[DataPreview(label="raw", type_name="RawFactoryConfig", preview="...", size=None)],
                outputs=[DataPreview(
                    label="factory",
                    type_name="FactoryConfig",
                    preview=f"machines: {[m.id for m in factory.machines]}, jobs: {[j.id for j in factory.jobs]}",
                    size=f"{len(factory.machines)} machines, {len(factory.jobs)} jobs",
                )],
            )
            
            # Add operation for each normalization repair if any
            if normalization_repair_count > 0:
                state.add_operation(
                    op_type=OperationType.VALIDATION,
                    name="normalization_repairs",
                    duration_ms=0,
                    inputs=[],
                    outputs=[DataPreview(
                        label="repairs",
                        type_name="list[str]",
                        preview=f"{normalization_repair_count} repairs applied",
                        size=None,
                    )],
                )
            
            state.finish_data_flow_step(
                status="done",
                step_output=DataPreview(
                    label="normalized_factory",
                    type_name="FactoryConfig",
                    preview=f"{normalization_repair_count} repairs" if normalization_repair_count > 0 else "no repairs needed",
                    size=f"{len(factory.machines)} machines, {len(factory.jobs)} jobs",
                ),
            )
            
            # =================================================================
            # O3: Coverage Assessment
            # =================================================================
            state.start_data_flow_step(
                step_id=-13,
                step_type="onboarding_o3",
                step_name="📊 O3: Coverage Assessment",
                step_input=DataPreview(
                    label="inputs",
                    type_name="tuple",
                    preview=f"explicit_ids + factory",
                    size=None,
                ),
            )
            state.add_thought("O3: Assessing coverage (comparing explicit IDs to parsed factory)")
            
            t0 = time.time()
            coverage = assess_coverage(ids, factory)
            latency_coverage = int((time.time() - t0) * 1000)
            
            # Create OnboardingIssues from coverage misses
            if coverage.missing_machines:
                coverage_issue_count += len(coverage.missing_machines)
                state.add_onboarding_issue(
                    issue_type="coverage_miss",
                    severity="warning",
                    message=f"Machines mentioned in text but not in parsed config: {sorted(coverage.missing_machines)}",
                    related_ids=sorted(coverage.missing_machines),
                )
            
            if coverage.missing_jobs:
                coverage_issue_count += len(coverage.missing_jobs)
                state.add_onboarding_issue(
                    issue_type="coverage_miss",
                    severity="warning",
                    message=f"Jobs mentioned in text but not in parsed config: {sorted(coverage.missing_jobs)}",
                    related_ids=sorted(coverage.missing_jobs),
                )
            
            state.add_operation(
                op_type=OperationType.VALIDATION,
                name="assess_coverage",
                duration_ms=latency_coverage,
                inputs=[
                    DataPreview(label="explicit_ids", type_name="ExplicitIds", preview=f"{len(ids.machine_ids)}M, {len(ids.job_ids)}J", size=None),
                    DataPreview(label="factory", type_name="FactoryConfig", preview=f"{len(factory.machines)}M, {len(factory.jobs)}J", size=None),
                ],
                outputs=[DataPreview(
                    label="coverage",
                    type_name="CoverageReport",
                    preview=f"machines: {coverage.machine_coverage:.0%}, jobs: {coverage.job_coverage:.0%}",
                    size=f"missing: {len(coverage.missing_machines)}M, {len(coverage.missing_jobs)}J" if coverage.missing_machines or coverage.missing_jobs else "complete",
                )],
            )
            
            coverage_status = "complete" if (coverage.machine_coverage == 1.0 and coverage.job_coverage == 1.0) else "incomplete"
            state.finish_data_flow_step(
                status="done" if coverage_status == "complete" else "warning",
                step_output=DataPreview(
                    label="coverage_report",
                    type_name="CoverageReport",
                    preview=f"machines: {coverage.machine_coverage:.0%}, jobs: {coverage.job_coverage:.0%}",
                    size=coverage_status,
                ),
            )
            
            # =================================================================
            # O4: Consensus & Alternatives
            # =================================================================
            state.start_data_flow_step(
                step_id=-14,
                step_type="onboarding_o4",
                step_name="🔄 O4: Consensus & Alternatives",
                step_input=DataPreview(
                    label="configs",
                    type_name="list[FactoryConfig]",
                    preview=f"primary + {len(multi_pass_result.alt_configs)} alternatives",
                    size=None,
                ),
            )
            state.add_thought(f"O4: Computing consensus across {len(multi_pass_result.all_pass_results)} extraction passes")
            
            # Create OnboardingIssues from alternative config conflicts
            if alt_conflict_count > 0:
                for i, (diff, summary) in enumerate(zip(multi_pass_result.diffs, multi_pass_result.diff_summaries)):
                    if not diff.is_identical:
                        # Extract related IDs from the diff
                        related_ids = []
                        related_ids.extend(diff.machines_added)
                        related_ids.extend(diff.machines_removed)
                        related_ids.extend(diff.jobs_added)
                        related_ids.extend(diff.jobs_removed)
                        related_ids.extend(diff.routing_differences.keys())
                        
                        state.add_onboarding_issue(
                            issue_type="alt_conflict",
                            severity="warning",
                            message=f"Alternative interpretation ({multi_pass_result.alt_modes[i]} mode) differs: {summary}",
                            related_ids=list(set(related_ids)) if related_ids else None,
                        )
            
            state.add_operation(
                op_type=OperationType.VALIDATION,
                name="multi_pass_consensus",
                duration_ms=0,
                inputs=[
                    DataPreview(label="primary_config", type_name="FactoryConfig", preview=f"{len(factory.machines)}M, {len(factory.jobs)}J", size=None),
                    DataPreview(label="alt_configs", type_name="list[FactoryConfig]", preview=f"{len(multi_pass_result.alt_configs)} alternatives", size=None),
                ],
                outputs=[DataPreview(
                    label="consensus",
                    type_name="str",
                    preview=f"conflicts: {alt_conflict_count}, identical: {alt_conflict_count == 0}",
                    size=f"{len(multi_pass_result.diff_summaries)} diffs",
                )],
            )
            
            consensus_status = "unanimous" if alt_conflict_count == 0 else f"{alt_conflict_count} conflicts"
            state.finish_data_flow_step(
                status="done" if alt_conflict_count == 0 else "warning",
                step_output=DataPreview(
                    label="consensus_result",
                    type_name="str",
                    preview=consensus_status,
                    size=f"primary: {multi_pass_result.primary_mode}",
                ),
            )
            
            # =================================================================
            # O5: Diagnostics Summary
            # =================================================================
            score, trust = compute_onboarding_score(
                coverage_issues=coverage_issue_count,
                normalization_repairs=normalization_repair_count,
                alt_conflicts=alt_conflict_count,
            )
            state.set_onboarding_score(score, trust)

            # Generate clarifying questions from diffs
            questions = generate_clarifying_questions(
                primary=factory,
                alternatives=multi_pass_result.alt_configs,
                diffs=multi_pass_result.diffs,
                modes=multi_pass_result.alt_modes,
            )

            # Store alternative factories + diffs + questions for frontend display (PR9)
            state.set_alternative_factories(
                alt_factories=multi_pass_result.alt_configs,
                alt_modes=multi_pass_result.alt_modes,
                diff_summaries=multi_pass_result.diff_summaries,
                diffs=multi_pass_result.diffs,
                questions=questions,
            )
            
            self._create_diagnostics_summary_step(
                state=state,
                score=score,
                trust=trust,
                coverage_issues=coverage_issue_count,
                normalization_repairs=normalization_repair_count,
                alt_conflicts=alt_conflict_count,
                factory=factory,
            )
            
            # Log diagnostics summary to scratchpad
            state.add_thought(
                f"O5: Diagnostics complete - score={score} ({trust}), "
                f"coverage_issues={coverage_issue_count}, "
                f"normalization_repairs={normalization_repair_count}, "
                f"alt_conflicts={alt_conflict_count}"
            )
            
            # Still fail if coverage is incomplete (but we've recorded the issues)
            if coverage.machine_coverage < 1.0 or coverage.job_coverage < 1.0:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error=(
                        f"Coverage mismatch: missing machines {sorted(coverage.missing_machines)}, "
                        f"missing jobs {sorted(coverage.missing_jobs)}. "
                        f"The description may be ambiguous. Try rephrasing or use the demo factory."
                    )
                )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "factory": factory.model_dump(),
                    "machine_count": len(factory.machines),
                    "job_count": len(factory.jobs),
                    "machines": [m.id for m in factory.machines],
                    "jobs": [j.id for j in factory.jobs],
                    "onboarding_score": score,
                    "onboarding_trust": trust,
                    "alt_configs_count": len(multi_pass_result.alt_configs),
                    "alt_conflicts_count": alt_conflict_count,
                    "diff_summaries": multi_pass_result.diff_summaries,
                }
            )
            
        except ExtractionError as e:
            # Still compute a score even on failure
            score, trust = compute_onboarding_score(
                coverage_issues=coverage_issue_count + 1,  # Count the failure as an issue
                normalization_repairs=normalization_repair_count,
                alt_conflicts=alt_conflict_count,
            )
            state.set_onboarding_score(score, trust)
            state.add_onboarding_issue(
                issue_type="extraction_error",
                severity="error",
                message=f"{e.code}: {e.message}",
                related_ids=None,
            )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Extraction failed ({e.code}): {e.message}"
            )
        except Exception as e:
            # Still compute a score even on unexpected failure
            score, trust = compute_onboarding_score(
                coverage_issues=coverage_issue_count + 2,  # Count unexpected failure as worse
                normalization_repairs=normalization_repair_count,
                alt_conflicts=alt_conflict_count,
            )
            state.set_onboarding_score(score, trust)
            state.add_onboarding_issue(
                issue_type="unexpected_error",
                severity="error",
                message=f"Unexpected error: {str(e)[:200]}",
                related_ids=None,
            )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Unexpected error: {str(e)[:200]}"
            )
    
    def _create_diagnostics_summary_step(
        self,
        state: AgentState,
        score: int,
        trust: str,
        coverage_issues: int,
        normalization_repairs: int,
        alt_conflicts: int,
        factory: FactoryConfig | None,
    ) -> None:
        """
        Create the O5: Diagnostics Summary data flow step.
        
        This step summarizes the overall onboarding quality including:
        - Onboarding score and trust level
        - Issue counts by category
        - Final factory configuration summary
        """
        state.start_data_flow_step(
            step_id=-15,
            step_type="onboarding_o5",
            step_name="📋 O5: Diagnostics Summary",
            step_input=DataPreview(
                label="diagnostics_input",
                type_name="tuple",
                preview=f"issues + score + factory",
                size=None,
            ),
        )
        
        # Add operation showing score computation
        state.add_operation(
            op_type=OperationType.VALIDATION,
            name="compute_onboarding_score",
            duration_ms=0,
            inputs=[
                DataPreview(label="coverage_issues", type_name="int", preview=str(coverage_issues), size=None),
                DataPreview(label="normalization_repairs", type_name="int", preview=str(normalization_repairs), size=None),
                DataPreview(label="alt_conflicts", type_name="int", preview=str(alt_conflicts), size=None),
            ],
            outputs=[
                DataPreview(label="score", type_name="int", preview=str(score), size=None),
                DataPreview(label="trust", type_name="str", preview=trust, size=None),
            ],
        )
        
        # Add operation showing issue summary
        total_issues = len(state.onboarding_issues)
        issue_summary = f"{total_issues} total issues"
        if total_issues > 0:
            by_severity = {}
            for issue in state.onboarding_issues:
                by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
            issue_summary += f" ({', '.join(f'{v} {k}' for k, v in by_severity.items())})"
        
        state.add_operation(
            op_type=OperationType.VALIDATION,
            name="aggregate_issues",
            duration_ms=0,
            inputs=[],
            outputs=[
                DataPreview(
                    label="issues",
                    type_name="list[OnboardingIssue]",
                    preview=issue_summary,
                    size=f"{total_issues} issues",
                ),
            ],
        )
        
        # Finish with the final summary
        factory_summary = f"{len(factory.machines)}M, {len(factory.jobs)}J" if factory else "no factory"
        state.finish_data_flow_step(
            status="done" if trust == "HIGH_TRUST" else ("warning" if trust == "MEDIUM_TRUST" else "failed"),
            step_output=DataPreview(
                label="onboarding_summary",
                type_name="dict",
                preview=f"score={score} ({trust}), {factory_summary}",
                size=issue_summary,
            ),
        )


class GetDemoFactoryTool(Tool):
    """
    Returns the built-in demo factory (3 machines, 3 jobs).
    
    Use this as a fallback when factory parsing fails, or for demonstration.
    """
    
    @property
    def name(self) -> str:
        return "get_demo_factory"
    
    @property
    def description(self) -> str:
        return (
            "Get the built-in demo factory with 3 machines (M1, M2, M3) and 3 jobs (J1, J2, J3). "
            "Use this as a fallback if parsing the user's factory description fails, "
            "or if the user just wants to see a demonstration."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return GetFactoryInfoArgs  # No args needed
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        factory = build_toy_factory()
        
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            output={
                "factory": factory.model_dump(),
                "machine_count": len(factory.machines),
                "job_count": len(factory.jobs),
                "machines": [m.id for m in factory.machines],
                "jobs": [j.id for j in factory.jobs],
                "note": "This is the demo factory. M2 is the bottleneck.",
            }
        )


class SimulateScenarioTool(Tool):
    """
    Runs a simulation scenario on the current factory.
    
    Requires a factory to be loaded in the agent state first.
    """
    
    @property
    def name(self) -> str:
        return "simulate_scenario"
    
    @property
    def description(self) -> str:
        return (
            "Run a simulation scenario on the current factory. "
            "Available scenarios:\n"
            "- baseline: Normal operations, no modifications\n"
            "- rush_order: Prioritize a job (requires rush_job_id)\n"
            "- machine_slowdown: Slow down any machine (requires slowdown_factor >= 2 and slowdown_machine_id)\n"
            "Returns makespan, job lateness, bottleneck machine, and utilization metrics. "
            "IMPORTANT: You must have a factory loaded first (use parse_factory or get_demo_factory)."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return SimulateScenarioArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        
        # Check if factory is loaded
        if state.factory is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="No factory loaded. Use parse_factory or get_demo_factory first."
            )
        
        # Parse scenario type
        try:
            scenario_type = ScenarioType(args["scenario_type"])
        except ValueError:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Invalid scenario_type '{args['scenario_type']}'. Must be baseline, rush_order, or machine_slowdown."
            )
        
        # Build scenario spec
        try:
            spec = ScenarioSpec(
                scenario_type=scenario_type,
                rush_job_id=args.get("rush_job_id"),
                slowdown_factor=args.get("slowdown_factor"),
                slowdown_machine_id=args.get("slowdown_machine_id"),
            )
        except ValueError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Invalid scenario specification: {str(e)}"
            )
        
        # Validate rush_job_id exists
        if spec.rush_job_id:
            valid_job_ids = {j.id for j in state.factory.jobs}
            if spec.rush_job_id not in valid_job_ids:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error=f"Job '{spec.rush_job_id}' not found. Available jobs: {sorted(valid_job_ids)}"
                )
        
        # Validate slowdown_machine_id exists for MACHINE_SLOWDOWN
        if scenario_type == ScenarioType.MACHINE_SLOWDOWN:
            if not spec.slowdown_machine_id:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error="MACHINE_SLOWDOWN requires slowdown_machine_id"
                )
            valid_machine_ids = {m.id for m in state.factory.machines}
            if spec.slowdown_machine_id not in valid_machine_ids:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error=f"Machine '{spec.slowdown_machine_id}' not found. Available: {sorted(valid_machine_ids)}"
                )
        
        # Run simulation
        try:
            t0 = time.time()
            result = simulate(state.factory, spec)
            latency_sim = int((time.time() - t0) * 1000)
            
            # Track simulate operation
            state.add_operation(
                op_type=OperationType.FUNCTION,
                name="simulate",
                duration_ms=latency_sim,
                inputs=[
                    DataPreview(label="factory", type_name="FactoryConfig", preview=f"{len(state.factory.machines)}M, {len(state.factory.jobs)}J", size=None),
                    DataPreview(label="spec", type_name="ScenarioSpec", preview=f"{spec.scenario_type.value}", size=None),
                ],
                outputs=[DataPreview(
                    label="result",
                    type_name="SimulationResult",
                    preview=f"makespan={result.makespan_hour}h, {len(result.scheduled_steps)} scheduled steps",
                    size=None,
                )],
            )
            
            t0 = time.time()
            metrics = compute_metrics(state.factory, result)
            latency_metrics = int((time.time() - t0) * 1000)
            
            # Track compute_metrics operation
            state.add_operation(
                op_type=OperationType.FUNCTION,
                name="compute_metrics",
                duration_ms=latency_metrics,
                inputs=[
                    DataPreview(label="factory", type_name="FactoryConfig", preview="...", size=None),
                    DataPreview(label="sim_result", type_name="SimulationResult", preview=f"makespan={result.makespan_hour}h", size=None),
                ],
                outputs=[DataPreview(
                    label="metrics",
                    type_name="ScenarioMetrics",
                    preview=f"makespan={metrics.makespan_hour}h, bottleneck={metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%})",
                    size=None,
                )],
            )
            
            # Format output
            late_jobs = {k: v for k, v in metrics.job_lateness.items() if v > 0}
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "scenario_type": spec.scenario_type.value,
                    "rush_job_id": spec.rush_job_id,
                    "slowdown_factor": spec.slowdown_factor,
                    "slowdown_machine_id": spec.slowdown_machine_id,
                    "makespan_hours": metrics.makespan_hour,
                    "bottleneck_machine": metrics.bottleneck_machine_id,
                    "bottleneck_utilization": f"{metrics.bottleneck_utilization:.0%}",
                    "late_jobs": late_jobs if late_jobs else "None",
                    "all_job_lateness": metrics.job_lateness,
                    "metrics": metrics.model_dump(),
                    "spec": spec.model_dump(),
                }
            )
            
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Simulation failed: {str(e)[:200]}"
            )


class GetCurrentFactoryTool(Tool):
    """
    Returns information about the currently loaded factory.
    """
    
    @property
    def name(self) -> str:
        return "get_current_factory"
    
    @property
    def description(self) -> str:
        return (
            "Get details about the currently loaded factory configuration. "
            "Shows machines, jobs, their routing, and due times. "
            "Returns an error if no factory is loaded yet."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return GetFactoryInfoArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        
        if state.factory is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="No factory loaded. Use parse_factory or get_demo_factory first."
            )
        
        factory = state.factory
        
        # Build readable summary
        machines_info = [{"id": m.id, "name": m.name} for m in factory.machines]
        jobs_info = []
        for job in factory.jobs:
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "due_time": job.due_time_hour,
                "steps": [{"machine": s.machine_id, "hours": s.duration_hours} for s in job.steps],
                "total_hours": sum(s.duration_hours for s in job.steps),
            })
        
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            output={
                "machines": machines_info,
                "jobs": jobs_info,
                "machine_count": len(factory.machines),
                "job_count": len(factory.jobs),
            }
        )


class ListPossibleScenariosTool(Tool):
    """
    Lists all valid scenarios the agent can run based on current factory.
    
    This helps the agent understand what options are available without guessing.
    """
    
    @property
    def name(self) -> str:
        return "list_possible_scenarios"
    
    @property
    def description(self) -> str:
        return (
            "List all valid simulation scenarios you can run based on the current factory. "
            "Shows which jobs can be rushed and what slowdown factors are available. "
            "Use this BEFORE simulating to understand your options. "
            "IMPORTANT: You must have a factory loaded first."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return GetFactoryInfoArgs  # No args needed
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        
        if state.factory is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="No factory loaded. Use parse_factory or get_demo_factory first."
            )
        
        factory = state.factory
        job_ids = [j.id for j in factory.jobs]
        machine_ids = [m.id for m in factory.machines]
        
        # Check if M2 exists for slowdown scenarios
        has_m2 = "M2" in machine_ids
        
        scenarios = [
            {
                "scenario_type": "BASELINE",
                "description": "Normal operations, no modifications",
                "required_args": {},
                "always_available": True,
            },
        ]
        
        # Rush scenarios (one per job)
        for job_id in job_ids:
            job = next(j for j in factory.jobs if j.id == job_id)
            scenarios.append({
                "scenario_type": "RUSH_ARRIVES",
                "description": f"Rush order for {job_id} ({job.name})",
                "required_args": {"rush_job_id": job_id},
                "job_due_time": job.due_time_hour,
            })
        
        # M2 slowdown scenarios (legacy)
        if has_m2:
            for factor in [2, 3]:
                scenarios.append({
                    "scenario_type": "M2_SLOWDOWN",
                    "description": f"Machine M2 runs at {factor}x slower speed (legacy)",
                    "required_args": {"slowdown_factor": factor},
                })
        
        # Machine slowdown scenarios (new - any machine)
        for machine_id in machine_ids:
            for factor in [2, 3]:
                scenarios.append({
                    "scenario_type": "MACHINE_SLOWDOWN",
                    "description": f"Machine {machine_id} runs at {factor}x slower speed",
                    "required_args": {"slowdown_factor": factor, "slowdown_machine_id": machine_id},
                })
        
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            output={
                "available_scenarios": scenarios,
                "job_ids": job_ids,
                "machine_ids": machine_ids,
                "has_m2": has_m2,
                "hint": "Run BASELINE first to establish a reference point, then compare with other scenarios.",
            }
        )


class GenerateBriefingArgs(BaseModel):
    """Arguments for generating a briefing."""
    include_recommendations: bool = Field(
        default=True,
        description="Whether to include actionable recommendations"
    )
    focus_area: str | None = Field(
        default=None,
        description="Optional focus area: 'bottlenecks', 'lateness', 'rush_impact', or None for general"
    )


class GenerateBriefingTool(Tool):
    """
    Generates a structured markdown briefing from collected simulation data.
    
    Uses the existing BriefingAgent to produce professional reports.
    Enhanced for PR6: Now includes onboarding diagnostics and clarifying questions.
    """
    
    @property
    def name(self) -> str:
        return "generate_briefing"
    
    @property
    def description(self) -> str:
        return (
            "Generate a professional markdown briefing summarizing simulation results. "
            "Synthesizes all metrics collected so far into a cohesive report with "
            "risks, recommendations, and key findings. "
            "If onboarding issues were detected, also generates clarifying questions. "
            "IMPORTANT: Run at least one simulation first to have data to report on."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return GenerateBriefingArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        
        # Check preconditions
        if state.factory is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="No factory loaded. Parse a factory first."
            )
        
        if not state.metrics_collected:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="No simulations run yet. Run at least one simulation first."
            )
        
        try:
            # Import here to avoid circular dependency
            from .agents import BriefingAgent
            
            # Build context from all scenarios
            context_lines = [f"Original request: {state.user_request}", ""]
            context_lines.append("Scenarios analyzed:")
            
            for i, (spec, metrics) in enumerate(zip(state.scenarios_run, state.metrics_collected), 1):
                scenario_desc = f"\n{i}) {spec.scenario_type.value}"
                if spec.rush_job_id:
                    scenario_desc += f" (Rush: {spec.rush_job_id})"
                if spec.slowdown_factor:
                    scenario_desc += f" (Slowdown: {spec.slowdown_factor}x)"
                scenario_desc += f"\n   - Makespan: {metrics.makespan_hour}h"
                late_jobs = [k for k, v in metrics.job_lateness.items() if v > 0]
                scenario_desc += f"\n   - Late jobs: {late_jobs if late_jobs else 'none'}"
                scenario_desc += f"\n   - Bottleneck: {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%})"
                context_lines.append(scenario_desc)
            
            context = "\n".join(context_lines)
            
            # Add focus area if specified
            focus = args.get("focus_area")
            if focus:
                context += f"\n\nFocus area requested: {focus}"
            
            # Build onboarding context from state diagnostics (PR6)
            onboarding_context = self._build_onboarding_context(state)
            
            # Use BriefingAgent to generate the report (includes LLM call)
            agent = BriefingAgent()
            primary_metrics = state.metrics_collected[0]  # Use first scenario as primary
            
            t0 = time.time()
            briefing = agent.run(
                primary_metrics,
                context=context,
                intent_context=f"User request: {state.user_request}",
                futures_context=f"Analyzed {len(state.scenarios_run)} scenarios",
                onboarding_context=onboarding_context,
                factory=state.factory,
            )
            latency_briefing = int((time.time() - t0) * 1000)
            state.record_llm_call(
                schema_name="BriefingResponse",
                latency_ms=latency_briefing,
                purpose="Generate executive briefing with recommendations and clarifying questions",
            )
            
            # Track LLM operation
            inputs = [
                DataPreview(label="metrics", type_name="ScenarioMetrics", preview=f"{len(state.metrics_collected)} scenarios", size=None),
                DataPreview(label="context", type_name="str", preview=context[:60] + "...", size=f"{len(context)} chars"),
            ]
            if onboarding_context:
                inputs.append(DataPreview(
                    label="onboarding_context",
                    type_name="str",
                    preview=onboarding_context[:60] + "..." if len(onboarding_context) > 60 else onboarding_context,
                    size=f"{len(state.onboarding_issues)} issues",
                ))
            
            state.add_operation(
                op_type=OperationType.LLM,
                name="generate_briefing",
                duration_ms=latency_briefing,
                inputs=inputs,
                outputs=[DataPreview(
                    label="briefing",
                    type_name="str",
                    preview=briefing[:80] + "..." if len(briefing) > 80 else briefing,
                    size=f"{len(briefing)} chars",
                )],
                schema_name="BriefingResponse",
            )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "briefing": briefing,
                    "scenarios_included": len(state.scenarios_run),
                    "primary_scenario": state.scenarios_run[0].scenario_type.value,
                    "briefing_length": len(briefing),
                    "onboarding_issues_count": len(state.onboarding_issues),
                    "onboarding_score": state.onboarding_score,
                    "onboarding_trust": state.onboarding_trust,
                }
            )
            
        except Exception as e:
            logger.exception("Briefing generation failed")
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Briefing generation failed: {str(e)[:200]}"
            )
    
    def _build_onboarding_context(self, state: AgentState) -> str | None:
        """
        Build onboarding context string from state diagnostics for BriefingAgent.
        
        Returns None if no onboarding issues or score are present.
        """
        if not state.onboarding_issues and state.onboarding_score is None:
            return None
        
        lines = []
        
        # Add score and trust level
        if state.onboarding_score is not None:
            trust_label = state.onboarding_trust or "UNKNOWN"
            lines.append(f"Onboarding Quality Score: {state.onboarding_score}/100 ({trust_label})")
            lines.append("")
        
        # Add issues grouped by severity
        if state.onboarding_issues:
            # Group by severity
            by_severity: dict[str, list] = {"error": [], "warning": [], "info": []}
            for issue in state.onboarding_issues:
                severity = issue.severity.lower()
                if severity in by_severity:
                    by_severity[severity].append(issue)
                else:
                    by_severity["info"].append(issue)
            
            lines.append("Issues detected during factory parsing:")
            lines.append("")
            
            # Show errors first, then warnings, then info
            for severity in ["error", "warning", "info"]:
                issues = by_severity[severity]
                if issues:
                    severity_label = severity.upper()
                    for issue in issues:
                        related = ""
                        if issue.related_ids:
                            related = f" (related: {', '.join(issue.related_ids)})"
                        lines.append(f"- [{severity_label}] {issue.message}{related}")
            
            lines.append("")
            
            # Add summary for LLM context
            error_count = len(by_severity["error"])
            warning_count = len(by_severity["warning"])
            info_count = len(by_severity["info"])
            lines.append(f"Summary: {error_count} errors, {warning_count} warnings, {info_count} info")
        
        return "\n".join(lines) if lines else None


# =============================================================================
# PHASE 2: ATOMIC PARSING TOOLS
# =============================================================================

class ExtractEntitiesArgs(BaseModel):
    """Arguments for entity extraction."""
    description: str = Field(..., description="Factory description text")


class ExtractFactoryEntitiesTool(Tool):
    """
    Extract machine and job entities from factory description.
    
    First stage of decomposed factory parsing:
    - Extracts machine IDs and names
    - Extracts job IDs and names
    - Does NOT extract routing or parameters
    
    Stores intermediate results (coarse structure) in state for reuse by
    subsequent tools (ExtractRoutingTool, ExtractParametersTool).
    """
    
    @property
    def name(self) -> str:
        return "extract_factory_entities"
    
    @property
    def description(self) -> str:
        return (
            "Extract machine and job entities from a factory description. "
            "Returns IDs and names only - use extract_routing for job sequences, "
            "and extract_parameters for timings."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ExtractEntitiesArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        description = args["description"]
        
        try:
            # Stage 0: Extract explicit IDs (regex, no LLM)
            ids = extract_explicit_ids(description)
            
            # Stage 1: Extract coarse structure (LLM call)
            coarse = extract_coarse_structure(description, ids)
            
            # Store coarse structure for reuse by subsequent tools
            state._coarse_structure = coarse
            
            # Build entity result from coarse structure (authoritative source)
            # Use coarse.machines/jobs as source of truth, not regex IDs
            machine_ids = [m.id for m in coarse.machines]
            machine_names = {m.id: m.name for m in coarse.machines}
            job_ids = [j.id for j in coarse.jobs]
            job_names = {j.id: j.name for j in coarse.jobs}
            
            # Store in state for subsequent tools
            from .agent_types import FactoryEntities
            state.factory_entities = FactoryEntities(
                machine_ids=sorted(machine_ids),
                machine_names=machine_names,
                job_ids=sorted(job_ids),
                job_names=job_names,
            )
            
            # Also store factory text for later use
            state.factory_text = description
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "machine_ids": sorted(machine_ids),
                    "machine_names": machine_names,
                    "job_ids": sorted(job_ids),
                    "job_names": job_names,
                    "total_machines": len(machine_ids),
                    "total_jobs": len(job_ids),
                    "explicit_ids_found": {
                        "machines": sorted(ids.machine_ids),
                        "jobs": sorted(ids.job_ids),
                    },
                }
            )
        except ExtractionError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Entity extraction failed ({e.code}): {e.message}"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Entity extraction failed: {str(e)[:200]}"
            )


class ExtractRoutingArgs(BaseModel):
    """Arguments for routing extraction."""
    description: str = Field(..., description="Factory description text")


class ExtractRoutingTool(Tool):
    """
    Extract job routing (machine sequences) from factory description.
    
    Requires entities to be extracted first (uses cached coarse structure).
    Stores the full RawFactoryConfig for reuse by ExtractParametersTool.
    """
    
    @property
    def name(self) -> str:
        return "extract_routing"
    
    @property
    def description(self) -> str:
        return (
            "Extract job routing information (which machines each job uses, in order). "
            "IMPORTANT: Run extract_factory_entities first to identify machines and jobs."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ExtractRoutingArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        description = args["description"]
        
        # Check precondition
        if state.factory_entities is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="Must run extract_factory_entities first"
            )
        
        try:
            # Reuse coarse structure from entity extraction (avoid redundant LLM call)
            coarse = state._coarse_structure
            if coarse is None:
                # Fallback: re-extract if not cached (shouldn't happen in normal flow)
                ids = extract_explicit_ids(description)
                coarse = extract_coarse_structure(description, ids)
                state._coarse_structure = coarse
            
            # Stage 2: Extract steps and timings (LLM call)
            raw = extract_steps(description, coarse)
            
            # Store raw factory config for reuse by ExtractParametersTool
            state._raw_factory_config = raw
            
            # Extract routing info from raw config
            job_routes = {}
            for job in raw.jobs:
                if job.steps:
                    job_routes[job.id] = [step.machine_id for step in job.steps]
            
            # Store in state
            from .agent_types import FactoryRouting
            state.factory_routing = FactoryRouting(job_routes=job_routes)
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "job_routes": job_routes,
                    "jobs_with_routes": len(job_routes),
                }
            )
        except ExtractionError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Routing extraction failed ({e.code}): {e.message}"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Routing extraction failed: {str(e)[:200]}"
            )


class ExtractParametersArgs(BaseModel):
    """Arguments for parameter extraction."""
    description: str = Field(..., description="Factory description text")


class ExtractParametersTool(Tool):
    """
    Extract processing times and due dates from factory description.
    
    Requires entities and routing to be extracted first.
    Reuses the RawFactoryConfig cached by ExtractRoutingTool (NO additional LLM call).
    """
    
    @property
    def name(self) -> str:
        return "extract_parameters"
    
    @property
    def description(self) -> str:
        return (
            "Extract processing times and due dates from factory description. "
            "IMPORTANT: Run extract_factory_entities and extract_routing first."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ExtractParametersArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        description = args["description"]
        
        # Check preconditions
        if state.factory_entities is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="Must run extract_factory_entities first"
            )
        if state.factory_routing is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="Must run extract_routing first"
            )
        
        try:
            # Reuse raw factory config from routing extraction (NO LLM call needed!)
            raw = state._raw_factory_config
            if raw is None:
                # Fallback: re-extract if not cached (shouldn't happen in normal flow)
                coarse = state._coarse_structure
                if coarse is None:
                    ids = extract_explicit_ids(description)
                    coarse = extract_coarse_structure(description, ids)
                    state._coarse_structure = coarse
                raw = extract_steps(description, coarse)
                state._raw_factory_config = raw
            
            # Extract processing times and due dates from cached raw config
            processing_times = {}
            due_times = {}
            
            for job in raw.jobs:
                job_times = {}
                for step in job.steps:
                    # Convert to int for consistency with FactoryParameters type
                    job_times[step.machine_id] = int(step.duration_hours)
                processing_times[job.id] = job_times
                # Handle None due_time_hour
                due_times[job.id] = int(job.due_time_hour) if job.due_time_hour is not None else 24
            
            # Store in state
            from .agent_types import FactoryParameters
            state.factory_parameters = FactoryParameters(
                processing_times=processing_times,
                due_times=due_times,
            )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "processing_times": processing_times,
                    "due_times": due_times,
                }
            )
        except ExtractionError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Parameter extraction failed ({e.code}): {e.message}"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Parameter extraction failed: {str(e)[:200]}"
            )


class ValidateFactoryArgs(BaseModel):
    """Arguments for factory validation (no args needed)."""
    pass


class ValidateFactoryTool(Tool):
    """
    Validate factory data and assemble into FactoryConfig.
    
    Uses the same validate_and_normalize function as ParseFactoryTool to ensure
    consistent behavior between monolithic and atomic extraction pipelines.
    
    Pure consistency checks + coverage validation. No LLM calls.
    """
    
    @property
    def name(self) -> str:
        return "validate_factory"
    
    @property
    def description(self) -> str:
        return (
            "Validate extracted factory data and assemble into final FactoryConfig. "
            "Checks consistency, coverage, and produces validation report. "
            "IMPORTANT: Run extract_factory_entities, extract_routing, and extract_parameters first."
        )
    
    @property
    def args_schema(self) -> Type[BaseModel]:
        return ValidateFactoryArgs
    
    def execute(self, args: dict[str, Any], state: AgentState) -> ToolResult:
        tool_call_id = str(uuid.uuid4())[:8]
        
        # Check all preconditions
        errors = []
        warnings = []
        
        if state.factory_entities is None:
            errors.append("Missing entities - run extract_factory_entities first")
        if state.factory_routing is None:
            errors.append("Missing routing - run extract_routing first")
        if state.factory_parameters is None:
            errors.append("Missing parameters - run extract_parameters first")
        
        if errors:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error="; ".join(errors)
            )
        
        try:
            # Prefer using cached RawFactoryConfig if available (same path as ParseFactoryTool)
            raw = getattr(state, '_raw_factory_config', None)
            
            if raw is not None:
                # Use validate_and_normalize for consistency with ParseFactoryTool
                factory = validate_and_normalize(raw)
                
                # Assess coverage using explicit IDs from factory text
                if state.factory_text:
                    coverage = assess_coverage(extract_explicit_ids(state.factory_text), factory)
                    machine_coverage = coverage.machine_coverage
                    job_coverage = coverage.job_coverage
                    
                    if coverage.missing_machines:
                        warnings.append(f"Missing machines from text: {sorted(coverage.missing_machines)}")
                    if coverage.missing_jobs:
                        warnings.append(f"Missing jobs from text: {sorted(coverage.missing_jobs)}")
                else:
                    machine_coverage = 1.0
                    job_coverage = 1.0
            else:
                # Use the deterministic assembler (PR2) to build factory from intermediate state
                # This ensures consistent assembly logic across all code paths
                assembly_result = assemble_factory(
                    entities=state.factory_entities,
                    routing=state.factory_routing,
                    parameters=state.factory_parameters,
                )
                
                # Collect assembly warnings
                warnings.extend(assembly_result.warnings)
                factory = assembly_result.factory
                
                # Check for fatal issues: jobs with steps referencing unknown machines
                machine_ids_set = {m.id for m in factory.machines}
                for job in factory.jobs:
                    for step in job.steps:
                        if step.machine_id not in machine_ids_set:
                            errors.append(f"Job {job.id} references unknown machine {step.machine_id}")
                
                if errors:
                    return ToolResult(
                        tool_call_id=tool_call_id,
                        tool_name=self.name,
                        success=False,
                        error=f"Validation failed: {'; '.join(errors)}"
                    )
                
                # Compute coverage based on entity counts
                machine_coverage = len(factory.machines) / max(1, len(state.factory_entities.machine_ids))
                job_coverage = len(factory.jobs) / max(1, len(state.factory_entities.job_ids))
            
            # Store the validated factory in state
            state.factory = factory
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "factory": factory.model_dump(),
                    "machine_count": len(factory.machines),
                    "job_count": len(factory.jobs),
                    "machines": [m.id for m in factory.machines],
                    "jobs": [j.id for j in factory.jobs],
                    "warnings": warnings,
                    "coverage": {"machines": machine_coverage, "jobs": job_coverage}
                }
            )
            
        except ExtractionError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Validation failed ({e.code}): {e.message}"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Validation failed: {str(e)[:200]}"
            )


# =============================================================================
# TOOL REGISTRY
# =============================================================================

class ToolRegistry:
    """
    Registry of all available tools.
    
    Provides lookup by name and generates the OpenAI function schema for all tools.
    """
    
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """Register a tool by name."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())
    
    def get_openai_schemas(self) -> list[dict]:
        """Get OpenAI function calling schemas for all tools."""
        return [tool.to_openai_schema() for tool in self._tools.values()]
    
    def get_tools_description(self) -> str:
        """Get a human-readable description of all tools for the system prompt."""
        lines = ["Available tools:"]
        for tool in self._tools.values():
            lines.append(f"\n- {tool.name}: {tool.description}")
        return "\n".join(lines)


def create_default_registry() -> ToolRegistry:
    """Create and populate the default tool registry."""
    registry = ToolRegistry()
    
    # Core tools (legacy all-in-one)
    registry.register(ParseFactoryTool())
    registry.register(GetDemoFactoryTool())
    registry.register(SimulateScenarioTool())
    
    # Phase 2: Atomic parsing tools
    registry.register(ExtractFactoryEntitiesTool())
    registry.register(ExtractRoutingTool())
    registry.register(ExtractParametersTool())
    registry.register(ValidateFactoryTool())
    
    # Inspection tools
    registry.register(GetCurrentFactoryTool())
    registry.register(ListPossibleScenariosTool())
    
    # Reporting tools
    registry.register(GenerateBriefingTool())
    
    return registry

