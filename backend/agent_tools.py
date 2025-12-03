"""
Agent Tools Module

Defines the Tool interface and implements the tools available to the agent.
Each tool wraps existing functionality (onboarding, simulation, metrics) and
exposes it to the LLM via a standard interface.

Tools are the agent's "hands" - discrete, well-defined actions it can choose from.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Type
from pydantic import BaseModel, Field

from .agent_types import AgentState, ToolCall, ToolResult
from .models import FactoryConfig, ScenarioSpec, ScenarioType, ScenarioMetrics
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
        description="Type of scenario: 'BASELINE', 'RUSH_ARRIVES', or 'M2_SLOWDOWN'"
    )
    rush_job_id: str | None = Field(
        default=None,
        description="Job ID to rush (required for RUSH_ARRIVES)"
    )
    slowdown_factor: int | None = Field(
        default=None,
        description="Slowdown multiplier for M2 (required for M2_SLOWDOWN, must be >= 2)"
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
            # Stage 0: Extract explicit IDs
            ids = extract_explicit_ids(factory_text)
            logger.debug(f"Extracted IDs: {len(ids.machine_ids)} machines, {len(ids.job_ids)} jobs")
            
            # Stage 1: Extract coarse structure
            coarse = extract_coarse_structure(factory_text, ids)
            
            # Stage 2: Extract steps and timings
            raw = extract_steps(factory_text, coarse)
            
            # Stage 3: Validate and normalize
            factory = validate_and_normalize(raw)
            
            # Stage 4: Assess coverage
            coverage = assess_coverage(ids, factory)
            
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
            "- BASELINE: Normal operations, no modifications\n"
            "- RUSH_ARRIVES: Prioritize a job (requires rush_job_id)\n"
            "- M2_SLOWDOWN: Slow down machine M2 (requires slowdown_factor >= 2)\n"
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
                error=f"Invalid scenario_type '{args['scenario_type']}'. Must be BASELINE, RUSH_ARRIVES, or M2_SLOWDOWN."
            )
        
        # Build scenario spec
        try:
            spec = ScenarioSpec(
                scenario_type=scenario_type,
                rush_job_id=args.get("rush_job_id"),
                slowdown_factor=args.get("slowdown_factor"),
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
        
        # Run simulation
        try:
            result = simulate(state.factory, spec)
            metrics = compute_metrics(state.factory, result)
            
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
        
        # M2 slowdown scenarios
        if has_m2:
            for factor in [2, 3]:
                scenarios.append({
                    "scenario_type": "M2_SLOWDOWN",
                    "description": f"Machine M2 runs at {factor}x slower speed",
                    "required_args": {"slowdown_factor": factor},
                })
        else:
            scenarios.append({
                "scenario_type": "M2_SLOWDOWN",
                "description": "NOT AVAILABLE - no machine M2 in this factory",
                "available": False,
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
            
            # Use BriefingAgent to generate the report
            agent = BriefingAgent()
            primary_metrics = state.metrics_collected[0]  # Use first scenario as primary
            
            briefing = agent.run(
                primary_metrics,
                context=context,
                intent_context=f"User request: {state.user_request}",
                futures_context=f"Analyzed {len(state.scenarios_run)} scenarios",
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
    
    # Core tools
    registry.register(ParseFactoryTool())
    registry.register(GetDemoFactoryTool())
    registry.register(SimulateScenarioTool())
    
    # Inspection tools
    registry.register(GetCurrentFactoryTool())
    registry.register(ListPossibleScenariosTool())
    
    # Reporting tools
    registry.register(GenerateBriefingTool())
    
    return registry

