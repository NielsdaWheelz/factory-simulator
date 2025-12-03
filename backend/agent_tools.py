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
    assess_coverage,
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
        
        try:
            # Stage 0: Extract explicit IDs (no LLM)
            t0 = time.time()
            ids = extract_explicit_ids(factory_text)
            latency_ids = int((time.time() - t0) * 1000)
            logger.debug(f"Extracted IDs: {len(ids.machine_ids)} machines, {len(ids.job_ids)} jobs")
            
            # Track operation
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
            
            # Stage 1: Extract coarse structure (LLM call)
            t0 = time.time()
            coarse = extract_coarse_structure(factory_text, ids)
            latency_coarse = int((time.time() - t0) * 1000)
            state.record_llm_call(
                schema_name="CoarseStructure",
                latency_ms=latency_coarse,
                purpose="Extract machines and jobs from description",
            )
            
            # Track LLM operation
            state.add_operation(
                op_type=OperationType.LLM,
                name="extract_coarse_structure",
                duration_ms=latency_coarse,
                inputs=[
                    DataPreview(label="factory_text", type_name="str", preview="...", size=f"{len(factory_text)} chars"),
                    DataPreview(label="explicit_ids", type_name="ExplicitIds", preview=f"{len(ids.machine_ids)}M, {len(ids.job_ids)}J", size=None),
                ],
                outputs=[DataPreview(
                    label="coarse",
                    type_name="CoarseStructure",
                    preview=f"machines: {[m.id for m in coarse.machines]}, jobs: {[j.id for j in coarse.jobs]}",
                    size=f"{len(coarse.machines)} machines, {len(coarse.jobs)} jobs",
                )],
                schema_name="CoarseStructure",
            )
            
            # Stage 2: Extract steps and timings (LLM call)
            t0 = time.time()
            raw = extract_steps(factory_text, coarse)
            latency_steps = int((time.time() - t0) * 1000)
            state.record_llm_call(
                schema_name="RawFactoryConfig",
                latency_ms=latency_steps,
                purpose="Extract job routing and processing times",
            )
            
            # Track LLM operation
            state.add_operation(
                op_type=OperationType.LLM,
                name="extract_steps",
                duration_ms=latency_steps,
                inputs=[
                    DataPreview(label="factory_text", type_name="str", preview="...", size=f"{len(factory_text)} chars"),
                    DataPreview(label="coarse", type_name="CoarseStructure", preview=f"{len(coarse.machines)}M, {len(coarse.jobs)}J", size=None),
                ],
                outputs=[DataPreview(
                    label="raw",
                    type_name="RawFactoryConfig",
                    preview=f"jobs with steps: {[j.id for j in raw.jobs]}",
                    size=f"{sum(len(j.steps) for j in raw.jobs)} total steps",
                )],
                schema_name="RawFactoryConfig",
            )
            
            # Stage 3: Validate and normalize (no LLM)
            t0 = time.time()
            factory = validate_and_normalize(raw)
            latency_validate = int((time.time() - t0) * 1000)
            
            state.add_operation(
                op_type=OperationType.VALIDATION,
                name="validate_and_normalize",
                duration_ms=latency_validate,
                inputs=[DataPreview(label="raw", type_name="RawFactoryConfig", preview="...", size=None)],
                outputs=[DataPreview(
                    label="factory",
                    type_name="FactoryConfig",
                    preview=f"machines: {[m.id for m in factory.machines]}, jobs: {[j.id for j in factory.jobs]}",
                    size=f"{len(factory.machines)} machines, {len(factory.jobs)} jobs",
                )],
            )
            
            # Stage 4: Assess coverage (no LLM)
            t0 = time.time()
            coverage = assess_coverage(ids, factory)
            latency_coverage = int((time.time() - t0) * 1000)
            
            state.add_operation(
                op_type=OperationType.VALIDATION,
                name="assess_coverage",
                duration_ms=latency_coverage,
                inputs=[
                    DataPreview(label="explicit_ids", type_name="ExplicitIds", preview="...", size=None),
                    DataPreview(label="factory", type_name="FactoryConfig", preview="...", size=None),
                ],
                outputs=[DataPreview(
                    label="coverage",
                    type_name="CoverageReport",
                    preview=f"machines: {coverage.machine_coverage:.0%}, jobs: {coverage.job_coverage:.0%}",
                    size=f"missing: {len(coverage.missing_machines)}M, {len(coverage.missing_jobs)}J" if coverage.missing_machines or coverage.missing_jobs else "complete",
                )],
            )
            
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
                }
            )
            
        except ExtractionError as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Extraction failed ({e.code}): {e.message}"
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=False,
                error=f"Unexpected error: {str(e)[:200]}"
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
            
            # Use BriefingAgent to generate the report (includes LLM call)
            agent = BriefingAgent()
            primary_metrics = state.metrics_collected[0]  # Use first scenario as primary
            
            t0 = time.time()
            briefing = agent.run(
                primary_metrics,
                context=context,
                intent_context=f"User request: {state.user_request}",
                futures_context=f"Analyzed {len(state.scenarios_run)} scenarios",
            )
            latency_briefing = int((time.time() - t0) * 1000)
            state.record_llm_call(
                schema_name="BriefingResponse",
                latency_ms=latency_briefing,
                purpose="Generate executive briefing with recommendations",
            )
            
            # Track LLM operation
            state.add_operation(
                op_type=OperationType.LLM,
                name="generate_briefing",
                duration_ms=latency_briefing,
                inputs=[
                    DataPreview(label="metrics", type_name="ScenarioMetrics", preview=f"{len(state.metrics_collected)} scenarios", size=None),
                    DataPreview(label="context", type_name="str", preview=context[:60] + "...", size=f"{len(context)} chars"),
                ],
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
            # Use regex-based extraction from onboarding module
            ids = extract_explicit_ids(description)
            
            # Extract coarse structure (machines and jobs only)
            coarse = extract_coarse_structure(description, ids)
            
            # Build entity result
            machine_names = {m.id: m.name for m in coarse.machines}
            job_names = {j.id: j.name for j in coarse.jobs}
            
            # Store in state for subsequent tools
            from .agent_types import FactoryEntities
            state.factory_entities = FactoryEntities(
                machine_ids=sorted(ids.machine_ids),
                machine_names=machine_names,
                job_ids=sorted(ids.job_ids),
                job_names=job_names,
            )
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "machine_ids": sorted(ids.machine_ids),
                    "machine_names": machine_names,
                    "job_ids": sorted(ids.job_ids),
                    "job_names": job_names,
                    "total_machines": len(ids.machine_ids),
                    "total_jobs": len(ids.job_ids),
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
    
    Requires entities to be extracted first.
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
            # Get IDs from state
            ids = extract_explicit_ids(description)
            coarse = extract_coarse_structure(description, ids)
            
            # Extract full config with routing
            raw = extract_steps(description, coarse)
            
            # Extract just the routing info
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
            ids = extract_explicit_ids(description)
            coarse = extract_coarse_structure(description, ids)
            raw = extract_steps(description, coarse)
            
            # Extract processing times and due dates
            processing_times = {}
            due_times = {}
            
            for job in raw.jobs:
                job_times = {}
                for step in job.steps:
                    job_times[step.machine_id] = step.duration_hours
                processing_times[job.id] = job_times
                due_times[job.id] = job.due_time_hour
            
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
    
    Pure consistency checks + coverage validation.
    No LLM calls - just validates extracted data.
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
            # Assemble FactoryConfig from extracted data
            entities = state.factory_entities
            routing = state.factory_routing
            params = state.factory_parameters
            
            # Build machines
            machines = []
            for mid in entities.machine_ids:
                machines.append(Machine(
                    id=mid,
                    name=entities.machine_names.get(mid, mid)
                ))
            
            # Build jobs
            jobs = []
            for jid in entities.job_ids:
                steps = []
                route = routing.job_routes.get(jid, [])
                times = params.processing_times.get(jid, {})
                
                for machine_id in route:
                    duration = times.get(machine_id, 1)  # Default 1 hour
                    steps.append(Step(machine_id=machine_id, duration_hours=duration))
                
                if not steps:
                    warnings.append(f"Job {jid} has no steps - using default")
                    # Use first machine as fallback
                    if machines:
                        steps.append(Step(machine_id=machines[0].id, duration_hours=1))
                
                jobs.append(Job(
                    id=jid,
                    name=entities.job_names.get(jid, jid),
                    steps=steps,
                    due_time_hour=params.due_times.get(jid, 24)
                ))
            
            # Validate coverage
            machine_coverage = len(machines) / max(1, len(entities.machine_ids))
            job_coverage = len(jobs) / max(1, len(entities.job_ids))
            
            if machine_coverage < 1.0:
                warnings.append(f"Machine coverage: {machine_coverage:.0%}")
            if job_coverage < 1.0:
                warnings.append(f"Job coverage: {job_coverage:.0%}")
            
            # Check for missing machine references in steps
            machine_ids_set = {m.id for m in machines}
            for job in jobs:
                for step in job.steps:
                    if step.machine_id not in machine_ids_set:
                        errors.append(f"Job {job.id} references unknown machine {step.machine_id}")
            
            if errors:
                from .agent_types import FactoryValidationReport
                report = FactoryValidationReport(
                    valid=False,
                    errors=errors,
                    warnings=warnings,
                    coverage={"machines": machine_coverage, "jobs": job_coverage}
                )
                return ToolResult(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    success=False,
                    error=f"Validation failed: {'; '.join(errors)}"
                )
            
            # Success - create FactoryConfig
            factory = FactoryConfig(machines=machines, jobs=jobs)
            state.factory = factory
            
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                success=True,
                output={
                    "factory": factory.model_dump(),
                    "machine_count": len(machines),
                    "job_count": len(jobs),
                    "machines": [m.id for m in machines],
                    "jobs": [j.id for j in jobs],
                    "warnings": warnings,
                    "coverage": {"machines": machine_coverage, "jobs": job_coverage}
                }
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

