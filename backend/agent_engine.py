"""
Agent Engine Module

The core execution engine that drives the agent:
- Planning phase: LLM generates a structured plan at step 0
- Execution phase: Deterministic graph execution of plan steps
- Error handling: Typed errors with different retry/recovery policies

This is the "spine" of the agent - the control logic that orchestrates
planning vs acting, enforces budgets, and handles errors.
"""

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from .agent_types import (
    AgentState,
    AgentStatus,
    AgentDecision,
    ToolCall,
    ToolResult,
    Message,
    PlanStep,
    PlanStepType,
    PlanResponse,
    ErrorType,
    ErrorInfo,
)
from .agent_tools import ToolRegistry, create_default_registry
from .models import FactoryConfig, ScenarioSpec, ScenarioType, ScenarioMetrics
from .llm import call_llm_json
from .config import OPENAI_MODEL

logger = logging.getLogger(__name__)


# =============================================================================
# SYSTEM PROMPT FRAGMENTS
# =============================================================================

SYSTEM_PROMPT_CORE = """You are an expert factory operations analyst. Your job is to help users understand their factory's performance by parsing factory descriptions, running simulations, and providing actionable insights.

KEY CONSTRAINTS:
- NEVER make up factory data. Parse from user input or fail explicitly.
- NEVER silently fall back to a demo factory. Be explicit about failures.
- ALWAYS explain your reasoning before taking action.
- STOP when you have sufficient data to answer the user's question.
"""

PLANNING_PROMPT = """Given the user's request, generate an execution plan.

Available step types:
- ensure_factory: Parse/load the factory configuration
- simulate_baseline: Run baseline simulation
- simulate_rush: Run rush order scenario (params: job_id)
- simulate_slowdown: Run machine slowdown scenario (params: machine_id, factor)
- generate_briefing: Generate final markdown report
- diagnostic: Error recovery / explanation step

Standard pipeline for "analyze my factory":
1. ensure_factory
2. simulate_baseline
3. (optional) simulate_rush or simulate_slowdown based on user request
4. generate_briefing

Output JSON with this schema:
{
  "plan": [
    {"type": "ensure_factory", "params": {}},
    {"type": "simulate_baseline", "params": {}},
    {"type": "generate_briefing", "params": {}}
  ],
  "reasoning": "Brief explanation of why this plan was chosen"
}

IMPORTANT: 
- Only use the step types listed above
- Keep plans short (3-5 steps typical)
- Include ensure_factory first if user provided a factory description
- Include simulate_baseline before any comparison scenarios
"""


# =============================================================================
# PLANNING PHASE
# =============================================================================

def _build_planning_observation(state: AgentState, registry: ToolRegistry) -> str:
    """Build the observation for the planning LLM call."""
    parts = [
        "## User Request",
        state.user_request,
        "",
        "## Available Capabilities",
        "- Parse factory descriptions into structured configs",
        "- Run baseline simulations",
        "- Run what-if scenarios (rush orders, machine slowdowns)",
        "- Generate markdown briefings with insights and recommendations",
        "",
        "## Constraints",
        f"- LLM call budget: {state.llm_call_budget - state.llm_calls_used} remaining",
        f"- Max steps: {state.max_steps}",
    ]
    
    if state.factory_text:
        parts.append("")
        parts.append("## Factory Description Provided")
        parts.append(f"User provided a factory description ({len(state.factory_text)} chars)")
    
    return "\n".join(parts)


def _generate_plan(state: AgentState, registry: ToolRegistry) -> list[PlanStep]:
    """
    Generate execution plan using LLM at step 0.
    
    This is the PLANNING phase - the LLM decides what steps to take,
    but doesn't execute them. Execution is deterministic graph traversal.
    """
    logger.info("🎯 Planning phase: generating execution plan")
    
    observation = _build_planning_observation(state, registry)
    
    prompt = f"""{SYSTEM_PROMPT_CORE}

{PLANNING_PROMPT}

---

{observation}

---

Generate a plan for this request. Output ONLY valid JSON.
"""
    
    # Track LLM call
    if not state.increment_llm_calls():
        logger.warning("LLM budget exceeded during planning")
        return [
            PlanStep(id=0, type=PlanStepType.DIAGNOSTIC, params={"reason": "budget_exceeded"})
        ]
    
    try:
        response = call_llm_json(prompt, PlanResponse)
        logger.info(f"Planning LLM returned {len(response.plan)} steps")
        logger.debug(f"Planning reasoning: {response.reasoning}")
        
        # Convert to PlanStep objects, validating types
        plan_steps = []
        for i, step_dict in enumerate(response.plan):
            step_type_str = step_dict.get("type", "")
            
            try:
                step_type = PlanStepType(step_type_str)
            except ValueError:
                logger.warning(f"Invalid step type '{step_type_str}', skipping")
                continue
            
            plan_steps.append(PlanStep(
                id=i,
                type=step_type,
                params=step_dict.get("params", {}),
                status="pending",
            ))
        
        if not plan_steps:
            logger.warning("LLM returned empty plan, using canonical fallback")
            plan_steps = _get_canonical_plan(state)
        
        return plan_steps
        
    except Exception as e:
        logger.error(f"Planning LLM call failed: {e}")
        return _get_canonical_plan(state)


def _get_canonical_plan(state: AgentState) -> list[PlanStep]:
    """
    Return the canonical 4-step plan for factory analysis.
    Used as fallback when LLM planning fails.
    """
    plan = [
        PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, params={}),
        PlanStep(id=1, type=PlanStepType.SIMULATE_BASELINE, params={}),
    ]
    
    user_lower = state.user_request.lower()
    if any(word in user_lower for word in ["rush", "priority", "urgent", "expedite"]):
        plan.append(PlanStep(id=2, type=PlanStepType.SIMULATE_RUSH, params={}))
    
    plan.append(PlanStep(id=len(plan), type=PlanStepType.GENERATE_BRIEFING, params={}))
    
    return plan


# =============================================================================
# STEP EXECUTION (Tiny Graph)
# =============================================================================

def _execute_ensure_factory(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute ENSURE_FACTORY step."""
    logger.info("📦 Executing ENSURE_FACTORY")
    
    if state.factory is not None:
        logger.info("Factory already loaded, skipping")
        return None
    
    if not state.factory_text:
        state.factory_text = state.user_request
    
    tool = registry.get("parse_factory")
    if tool is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="parse_factory tool not found", recoverable=False)
    
    result = tool.execute({"description": state.factory_text}, state)
    
    if result.success:
        if result.output and "factory" in result.output:
            state.factory = FactoryConfig.model_validate(result.output["factory"])
            state.add_thought(f"Factory parsed: {len(state.factory.machines)} machines, {len(state.factory.jobs)} jobs")
            logger.info(f"Factory loaded: {len(state.factory.machines)} machines, {len(state.factory.jobs)} jobs")
        return None
    else:
        return ErrorInfo(
            type=ErrorType.TASK_UNSAT,
            message=result.error or "Factory parsing failed",
            context={"factory_text_length": len(state.factory_text)},
            recoverable=False
        )


def _execute_simulate_baseline(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute SIMULATE_BASELINE step."""
    logger.info("🔄 Executing SIMULATE_BASELINE")
    
    if state.factory is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="Cannot simulate: no factory loaded", recoverable=False)
    
    tool = registry.get("simulate_scenario")
    if tool is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="simulate_scenario tool not found")
    
    result = tool.execute({"scenario_type": "baseline"}, state)
    
    if result.success:
        # Persist results to state for downstream steps
        spec = ScenarioSpec.model_validate(result.output["spec"])
        metrics = ScenarioMetrics.model_validate(result.output["metrics"])
        state.scenarios_run.append(spec)
        state.metrics_collected.append(metrics)
        state.add_thought(f"Baseline simulation complete: makespan={metrics.makespan_hour}h")
        return None
    else:
        return ErrorInfo(
            type=ErrorType.TOOL_TRANSIENT if "timeout" in (result.error or "").lower() else ErrorType.TOOL_FATAL,
            message=result.error or "Simulation failed"
        )


def _execute_simulate_rush(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute SIMULATE_RUSH step."""
    logger.info("🚀 Executing SIMULATE_RUSH")
    
    if state.factory is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="Cannot simulate: no factory loaded")
    
    job_id = step.params.get("job_id")
    if not job_id and state.factory.jobs:
        job_id = state.factory.jobs[0].id
        logger.info(f"No job_id specified, using first job: {job_id}")
    
    if not job_id:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="No job_id for rush scenario")
    
    tool = registry.get("simulate_scenario")
    result = tool.execute({"scenario_type": "rush_order", "rush_job_id": job_id}, state)
    
    if result.success:
        # Persist results to state for downstream steps
        spec = ScenarioSpec.model_validate(result.output["spec"])
        metrics = ScenarioMetrics.model_validate(result.output["metrics"])
        state.scenarios_run.append(spec)
        state.metrics_collected.append(metrics)
        state.add_thought(f"Rush simulation ({job_id}) complete: makespan={metrics.makespan_hour}h")
        return None
    else:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message=result.error or "Rush simulation failed")


def _execute_simulate_slowdown(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute SIMULATE_SLOWDOWN step."""
    logger.info("🐢 Executing SIMULATE_SLOWDOWN")
    
    if state.factory is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="Cannot simulate: no factory loaded")
    
    machine_id = step.params.get("machine_id", "M2")
    factor = step.params.get("factor", 2)
    
    machine_ids = {m.id for m in state.factory.machines}
    if machine_id not in machine_ids:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message=f"Machine '{machine_id}' not found. Available: {sorted(machine_ids)}")
    
    tool = registry.get("simulate_scenario")
    
    result = tool.execute({"scenario_type": "machine_slowdown", "slowdown_factor": factor, "slowdown_machine_id": machine_id}, state)
    
    if result.success:
        # Persist results to state for downstream steps
        spec = ScenarioSpec.model_validate(result.output["spec"])
        metrics = ScenarioMetrics.model_validate(result.output["metrics"])
        state.scenarios_run.append(spec)
        state.metrics_collected.append(metrics)
        state.add_thought(f"Slowdown simulation ({machine_id} {factor}x) complete: makespan={metrics.makespan_hour}h")
        return None
    else:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message=result.error or "Slowdown simulation failed")


def _execute_generate_briefing(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute GENERATE_BRIEFING step."""
    logger.info("📝 Executing GENERATE_BRIEFING")
    
    if not state.metrics_collected:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message="Cannot generate briefing: no simulations run")
    
    tool = registry.get("generate_briefing")
    result = tool.execute({"include_recommendations": True, "focus_area": step.params.get("focus_area")}, state)
    
    if result.success and result.output:
        briefing = result.output.get("briefing", "")
        state.complete(briefing)
        return None
    else:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message=result.error or "Briefing generation failed")


def _execute_diagnostic(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute DIAGNOSTIC step - error recovery / explanation."""
    logger.info("🔍 Executing DIAGNOSTIC step")
    
    reason = step.params.get("reason", "unknown")
    
    parts = ["# Diagnostic Report\n"]
    parts.append(f"The analysis could not be completed fully. Reason: {reason}\n")
    
    if state.errors_encountered:
        parts.append("\n## Errors Encountered\n")
        for err in state.errors_encountered[-3:]:
            parts.append(f"- [{err.type.value}] {err.message}\n")
    
    if state.factory:
        parts.append("\n## Factory Status\n")
        parts.append(f"- Machines: {[m.id for m in state.factory.machines]}\n")
        parts.append(f"- Jobs: {[j.id for j in state.factory.jobs]}\n")
    else:
        parts.append("\n## Factory Status\n")
        parts.append("- Factory could not be parsed from the description.\n")
        if state.factory_text:
            parts.append(f"- Input length: {len(state.factory_text)} chars\n")
    
    if state.metrics_collected:
        parts.append("\n## Available Results\n")
        for spec, metrics in zip(state.scenarios_run, state.metrics_collected):
            parts.append(f"- {spec.scenario_type.value}: makespan {metrics.makespan_hour}h\n")
    
    state.complete("".join(parts))
    return None


def _execute_plan_step(state: AgentState, step: PlanStep, registry: ToolRegistry) -> Optional[ErrorInfo]:
    """Execute a single plan step based on its type."""
    executors = {
        PlanStepType.ENSURE_FACTORY: _execute_ensure_factory,
        PlanStepType.SIMULATE_BASELINE: _execute_simulate_baseline,
        PlanStepType.SIMULATE_RUSH: _execute_simulate_rush,
        PlanStepType.SIMULATE_SLOWDOWN: _execute_simulate_slowdown,
        PlanStepType.GENERATE_BRIEFING: _execute_generate_briefing,
        PlanStepType.DIAGNOSTIC: _execute_diagnostic,
    }
    
    executor = executors.get(step.type)
    if executor is None:
        return ErrorInfo(type=ErrorType.TOOL_FATAL, message=f"Unknown step type: {step.type}")
    
    return executor(state, step, registry)


# =============================================================================
# ERROR HANDLING POLICIES
# =============================================================================

def _handle_error(state: AgentState, step: PlanStep, error: ErrorInfo) -> None:
    """
    Handle an error based on its type.
    
    - TOOL_TRANSIENT: Could retry (handled by caller)
    - TOOL_FATAL: Mark step failed, add DIAGNOSTIC step
    - TASK_UNSAT: Stop execution, produce diagnostic
    """
    logger.warning(f"Error in step {step.id} ({step.type.value}): {error.type.value} - {error.message}")
    
    state.errors_encountered.append(error)
    state.mark_plan_step_failed(step.id, error)
    
    if error.type == ErrorType.TASK_UNSAT:
        state.status = AgentStatus.DIAGNOSTIC_PENDING
        diag_step = PlanStep(id=len(state.plan), type=PlanStepType.DIAGNOSTIC, params={"reason": error.message})
        state.plan.append(diag_step)
    
    elif error.type == ErrorType.TOOL_FATAL:
        if not any(s.type == PlanStepType.DIAGNOSTIC for s in state.plan if s.status == "pending"):
            diag_step = PlanStep(id=len(state.plan), type=PlanStepType.DIAGNOSTIC, params={"reason": f"Step {step.type.value} failed: {error.message}"})
            state.plan.append(diag_step)
    
    state.record_error(error.message, error)


# =============================================================================
# GRACEFUL DEGRADATION
# =============================================================================

def _synthesize_partial_answer(state: AgentState) -> str:
    """Synthesize a useful partial answer when budget/steps exceeded."""
    parts = ["# Partial Analysis\n"]
    
    if state.status == AgentStatus.BUDGET_EXCEEDED:
        parts.append(f"LLM call budget ({state.llm_call_budget}) exceeded.\n")
    elif state.status == AgentStatus.MAX_STEPS:
        parts.append(f"Step limit ({state.max_steps}) reached.\n")
    
    parts.append("Here's what I was able to determine:\n\n")
    
    if state.plan:
        parts.append("## Plan Progress\n")
        parts.append(state.get_plan_summary() + "\n\n")
    
    if state.factory:
        parts.append("## Factory Configuration\n")
        parts.append(f"- Machines: {', '.join([f'{m.id} ({m.name})' for m in state.factory.machines])}\n")
        parts.append(f"- Jobs: {', '.join([f'{j.id} ({j.name})' for j in state.factory.jobs])}\n\n")
    else:
        parts.append("## Factory Configuration\n")
        parts.append("*Factory was not successfully loaded.*\n\n")
    
    if state.scenarios_run and state.metrics_collected:
        parts.append("## Simulation Results\n")
        for spec, metrics in zip(state.scenarios_run, state.metrics_collected):
            label = spec.scenario_type.value
            if spec.rush_job_id:
                label += f" (Rush: {spec.rush_job_id})"
            if spec.slowdown_factor:
                label += f" ({spec.slowdown_factor}x slowdown)"
            
            late_jobs = [k for k, v in metrics.job_lateness.items() if v > 0]
            parts.append(f"### {label}\n")
            parts.append(f"- Makespan: {metrics.makespan_hour} hours\n")
            parts.append(f"- Bottleneck: {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%})\n")
            parts.append(f"- Late jobs: {late_jobs if late_jobs else 'none'}\n\n")
    
    return "".join(parts)


# =============================================================================
# THE MAIN LOOP
# =============================================================================

def run_agent(user_request: str, max_steps: int = 15, llm_budget: int = 10) -> AgentState:
    """
    Run the agent loop until completion or failure.
    
    Architecture:
    1. Step 0: Generate plan using LLM (planning phase)
    2. Steps 1+: Execute plan deterministically (execution phase)
    3. Error handling: Typed errors with different policies
    4. Budget enforcement: Stop gracefully when budget exceeded
    """
    logger.info("=" * 60)
    logger.info("🤖 Agent starting")
    logger.info(f"   Request: {user_request[:100]}...")
    logger.info("=" * 60)
    
    state = AgentState(
        user_request=user_request,
        max_steps=max_steps,
        llm_call_budget=llm_budget,
    )
    
    state.add_message("user", user_request)
    registry = create_default_registry()
    
    # === PLANNING PHASE ===
    if not state.plan:
        state.plan = _generate_plan(state, registry)
        state.add_thought(f"PLAN: {state.get_plan_summary()}")
        logger.info(f"Plan generated: {state.get_plan_summary()}")
    
    # === EXECUTION PHASE ===
    while state.is_running():
        logger.info(f"\n--- Step {state.steps + 1}/{state.max_steps} ---")
        
        step = state.get_next_pending_step()
        
        if step is None:
            if state.final_answer is None:
                logger.info("All plan steps complete, synthesizing answer")
                state.final_answer = _synthesize_partial_answer(state)
            state.status = AgentStatus.DONE
            break
        
        state.mark_plan_step_running(step.id)
        state.add_thought(f"Executing: {step.type.value}")
        logger.info(f"Executing step {step.id}: {step.type.value}")
        
        error = _execute_plan_step(state, step, registry)
        
        if error is None:
            state.mark_plan_step_done(step.id)
            state.record_success()
            logger.info(f"Step {step.id} completed successfully")
        else:
            _handle_error(state, step, error)
            if state.status != AgentStatus.RUNNING:
                break
        
        state.increment_step()
        
        if state.status == AgentStatus.BUDGET_EXCEEDED:
            logger.warning("LLM budget exceeded")
            break
    
    # === POST-LOOP ===
    if state.status in (AgentStatus.MAX_STEPS, AgentStatus.BUDGET_EXCEEDED):
        state.final_answer = _synthesize_partial_answer(state)
    
    if state.status == AgentStatus.DIAGNOSTIC_PENDING:
        for step in state.plan:
            if step.type == PlanStepType.DIAGNOSTIC and step.status == "pending":
                _execute_diagnostic(state, step, registry)
                state.mark_plan_step_done(step.id)
    
    logger.info("=" * 60)
    logger.info(f"🤖 Agent finished with status: {state.status.value}")
    logger.info(f"   Steps: {state.steps}")
    logger.info(f"   LLM calls: {state.llm_calls_used}/{state.llm_call_budget}")
    logger.info(f"   Plan: {state.get_plan_summary()}")
    logger.info(f"   Final answer length: {len(state.final_answer or '')}")
    logger.info("=" * 60)
    
    return state


def run_agent_and_get_answer(user_request: str) -> str:
    """Run the agent and return just the final answer string."""
    state = run_agent(user_request)
    return state.final_answer or "Agent did not produce an answer."
