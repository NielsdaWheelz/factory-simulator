"""
Agent Engine Module

The core OODA loop that drives the agent:
- Observe: Build the observation (state → prompt)
- Orient: (Implicit in the LLM's reasoning)
- Decide: Call LLM to get next action
- Act: Execute the selected tool

This is the "heartbeat" of the agent - the while loop that keeps it thinking.
"""

import json
import logging
from typing import Any

from pydantic import BaseModel

from .agent_types import (
    AgentState,
    AgentStatus,
    AgentDecision,
    ToolCall,
    ToolResult,
    Message,
)
from .agent_tools import ToolRegistry, create_default_registry
from .models import FactoryConfig
from .llm import call_llm_json
from .config import OPENAI_MODEL

logger = logging.getLogger(__name__)


# =============================================================================
# SYSTEM PROMPT (The Agent's "Personality")
# =============================================================================

SYSTEM_PROMPT = """You are an expert factory operations analyst. Your job is to help users understand their factory's performance by parsing factory descriptions, running simulations, and providing actionable insights.

## Available Tools

1. `parse_factory` - Parse a free-text factory description into structured config
2. `get_demo_factory` - Get the built-in demo factory (fallback if parsing fails)
3. `get_current_factory` - View the currently loaded factory details
4. `list_possible_scenarios` - See all valid scenarios you can run
5. `simulate_scenario` - Run a simulation and get metrics
6. `generate_briefing` - Generate a professional markdown report from simulation data

## Your Goal

Help the user understand their factory's performance. You decide which tools to use and in what order based on what information you need.

## Principles

- Load a factory before you can simulate (parse_factory or get_demo_factory)
- Discover valid scenarios with list_possible_scenarios before guessing job IDs
- Run BASELINE first to establish a reference point
- Stop when you have enough data to answer the user's question
- NEVER guess job IDs or machine IDs - use tools to discover them

## When to Stop (CRITICAL)

You should choose `final_answer` when ALL of these are true:
1. Factory is loaded (parse_factory or get_demo_factory succeeded)
2. BASELINE simulation has been run
3. At least one comparison scenario has been run (if user asked for comparison)
4. You have enough data to answer the user's actual question

DO NOT keep running simulations after you have sufficient data.
If you've run BASELINE + 1-2 relevant scenarios, STOP and generate your answer.

## Anti-patterns (AVOID)

- Calling the same tool twice with the same arguments (check Action History)
- Running more than 3 simulations unless the user explicitly asks for more
- Hitting the step limit when you already have enough data to answer
- Calling list_possible_scenarios after you've already called it successfully

## Output Format

At each step, respond with JSON:
```json
{
    "thought": "Your reasoning (1-3 sentences)",
    "action_type": "tool_call" or "final_answer",
    "tool_calls": [{"id": "unique_id", "name": "tool_name", "arguments": {...}}],
    "final_answer": "Your markdown response to the user"
}
```
"""


# =============================================================================
# OBSERVATION BUILDER
# =============================================================================

def _build_action_history(state: AgentState) -> list[str]:
    """
    Build the Action History section showing what tools have been called.
    
    This is the REFLECTION mechanism - it prevents redundant tool calls
    by showing the agent what it has already done.
    """
    # Track tool calls and their outcomes
    tool_history: dict[str, list[dict]] = {}
    
    for msg in state.messages:
        if msg.role == "tool" and msg.name:
            if msg.name not in tool_history:
                tool_history[msg.name] = []
            
            # Parse the result to determine success/failure
            try:
                content = json.loads(msg.content) if msg.content else {}
                success = "error" not in content
                # Extract key info based on tool type
                if msg.name == "simulate_scenario" and success:
                    scenario_type = content.get("scenario_type", "?")
                    rush_job = content.get("rush_job_id")
                    slowdown = content.get("slowdown_factor")
                    label = scenario_type
                    if rush_job:
                        label += f"({rush_job})"
                    if slowdown:
                        label += f"({slowdown}x)"
                    tool_history[msg.name].append({"success": True, "label": label})
                else:
                    tool_history[msg.name].append({
                        "success": success,
                        "error": content.get("error", "")[:50] if not success else None
                    })
            except (json.JSONDecodeError, TypeError):
                tool_history[msg.name].append({"success": False, "error": "parse error"})
    
    if not tool_history:
        return []
    
    lines = ["## Action History (DO NOT REPEAT SUCCESSFUL CALLS)"]
    for tool_name, calls in tool_history.items():
        if tool_name == "simulate_scenario":
            # Special handling for simulations - show which scenarios were run
            successful = [c["label"] for c in calls if c.get("success") and c.get("label")]
            failed = [c for c in calls if not c.get("success")]
            if successful:
                lines.append(f"- {tool_name}: ✓ ran {', '.join(successful)}")
            if failed:
                lines.append(f"- {tool_name}: ✗ {len(failed)} failed attempt(s)")
        else:
            # Generic tool history
            successes = sum(1 for c in calls if c.get("success"))
            failures = sum(1 for c in calls if not c.get("success"))
            status_parts = []
            if successes:
                status_parts.append(f"✓ {successes} success")
            if failures:
                status_parts.append(f"✗ {failures} failed")
            lines.append(f"- {tool_name}: {', '.join(status_parts)}")
    
    return lines


def _build_data_sufficiency_check(state: AgentState) -> list[str]:
    """
    Build the Data Sufficiency Check section.
    
    This nudges the agent to stop when it has enough information.
    """
    lines = ["## Data Sufficiency Check"]
    
    # Check each criterion
    factory_loaded = state.factory is not None
    baseline_run = any(
        spec.scenario_type.value == "BASELINE" 
        for spec in state.scenarios_run
    )
    comparison_scenarios = sum(
        1 for spec in state.scenarios_run 
        if spec.scenario_type.value != "BASELINE"
    )
    
    lines.append(f"- Factory loaded: {'✓' if factory_loaded else '✗'}")
    lines.append(f"- BASELINE run: {'✓' if baseline_run else '✗'}")
    lines.append(f"- Comparison scenarios: {comparison_scenarios}")
    
    # Recommendation
    if factory_loaded and baseline_run and comparison_scenarios >= 1:
        lines.append("→ RECOMMENDATION: You have enough data. Consider providing final_answer.")
    elif factory_loaded and baseline_run:
        lines.append("→ You have baseline data. Run 1 comparison scenario OR provide final_answer if user only asked for baseline.")
    elif factory_loaded:
        lines.append("→ Factory loaded. Run BASELINE simulation next.")
    else:
        lines.append("→ Load a factory first (parse_factory or get_demo_factory).")
    
    return lines


def _build_investigation_summary(state: AgentState) -> list[str]:
    """
    Build a compact investigation summary for later steps (context pruning).
    
    After step 5, we switch from raw tool outputs to a condensed summary
    to avoid context bloat.
    """
    lines = ["## Investigation Summary"]
    
    # Factory summary
    if state.factory:
        machines = ", ".join([f"{m.id} ({m.name})" for m in state.factory.machines])
        jobs = ", ".join([f"{j.id}" for j in state.factory.jobs])
        lines.append(f"- Factory: {machines}")
        lines.append(f"- Jobs: {jobs}")
    
    # Simulation results summary (compact)
    if state.scenarios_run and state.metrics_collected:
        for spec, metrics in zip(state.scenarios_run, state.metrics_collected):
            scenario_label = spec.scenario_type.value
            if spec.rush_job_id:
                scenario_label += f"({spec.rush_job_id})"
            if spec.slowdown_factor:
                scenario_label += f"({spec.slowdown_factor}x)"
            
            late_jobs = [k for k, v in metrics.job_lateness.items() if v > 0]
            late_str = f", late: {late_jobs}" if late_jobs else ", no late jobs"
            
            lines.append(
                f"- {scenario_label}: makespan {metrics.makespan_hour}h, "
                f"bottleneck {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%}){late_str}"
            )
    
    return lines


def build_observation(state: AgentState, registry: ToolRegistry) -> str:
    """
    Build the observation string that the LLM sees.
    
    This is the "window into the world" - we curate what the LLM sees
    to keep it focused and within context limits.
    
    SOTA Features:
    - Action History: Shows what tools have been called (prevents redundant calls)
    - Data Sufficiency Check: Nudges agent to stop when it has enough data
    - Context Pruning: After step 5, uses compact summaries instead of raw outputs
    """
    parts = []
    
    # Current state summary
    parts.append("## Current State")
    parts.append(f"- Steps taken: {state.steps}/{state.max_steps}")
    parts.append(f"- Factory loaded: {'Yes' if state.factory else 'No'}")
    if state.factory:
        parts.append(f"  - Machines: {[m.id for m in state.factory.machines]}")
        parts.append(f"  - Jobs: {[j.id for j in state.factory.jobs]}")
    parts.append(f"- Simulations run: {len(state.scenarios_run)}")
    
    # === PHASE 1: Action History (Reflection) ===
    action_history = _build_action_history(state)
    if action_history:
        parts.append("")
        parts.extend(action_history)
    
    # === PHASE 2: Data Sufficiency Check ===
    parts.append("")
    parts.extend(_build_data_sufficiency_check(state))
    
    # === PHASE 3: Context Pruning ===
    # After step 5, switch to compact investigation summary
    if state.steps >= 5:
        parts.append("")
        parts.extend(_build_investigation_summary(state))
        
        # Show only the LAST tool result for freshness
        tool_messages = [m for m in state.messages if m.role == "tool"]
        if tool_messages:
            last_msg = tool_messages[-1]
            content_preview = last_msg.content[:300] + "..." if len(last_msg.content) > 300 else last_msg.content
            parts.append(f"\n## Last Tool Result")
            parts.append(f"[{last_msg.name}]: {content_preview}")
    else:
        # Early steps: show simulation results summary
        if state.scenarios_run and state.metrics_collected:
            parts.append("\n## Simulation Results Summary")
            for i, (spec, metrics) in enumerate(zip(state.scenarios_run, state.metrics_collected)):
                scenario_label = spec.scenario_type.value
                if spec.rush_job_id:
                    scenario_label += f" (rush {spec.rush_job_id})"
                if spec.slowdown_factor:
                    scenario_label += f" ({spec.slowdown_factor}x slow)"
                
                late_jobs = [f"{k}: +{v}h" for k, v in metrics.job_lateness.items() if v > 0]
                late_str = ", ".join(late_jobs) if late_jobs else "none"
                
                parts.append(f"  {i+1}. {scenario_label}")
                parts.append(f"     - Makespan: {metrics.makespan_hour}h")
                parts.append(f"     - Bottleneck: {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%})")
                parts.append(f"     - Late jobs: {late_str}")
        
        # Recent tool results (last 3 messages)
        tool_messages = [m for m in state.messages if m.role == "tool"]
        if tool_messages:
            parts.append("\n## Recent Tool Results")
            for msg in tool_messages[-3:]:
                content_preview = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
                parts.append(f"\n[{msg.name}]: {content_preview}")
    
    # User request (always visible)
    parts.append(f"\n## Original User Request")
    parts.append(state.user_request)
    
    # Available tools with signatures (shows exact argument names)
    parts.append("\n## Available Tools (use EXACT argument names)")
    for tool in registry.list_tools():
        if tool.name in state.blocked_tools:
            continue
        # Build signature from schema
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        required = schema.get("required", [])
        
        args_parts = []
        for arg_name, arg_info in props.items():
            arg_type = arg_info.get("type", "any")
            if arg_name in required:
                args_parts.append(f"{arg_name}: {arg_type}")
            else:
                args_parts.append(f"{arg_name}?: {arg_type}")
        
        sig = f"{tool.name}({', '.join(args_parts)})" if args_parts else f"{tool.name}()"
        parts.append(f"- {sig}")
    
    if state.blocked_tools:
        parts.append(f"\n## BLOCKED Tools (do not use): {list(state.blocked_tools)}")
    
    return "\n".join(parts)


# =============================================================================
# LLM DECISION CALLER
# =============================================================================

def call_llm_for_decision(
    observation: str,
    system_prompt: str,
    registry: ToolRegistry,
) -> AgentDecision:
    """
    Call the LLM to get the next decision.
    
    Uses structured output (JSON mode) to enforce the AgentDecision schema.
    """
    
    # Build the full prompt
    full_prompt = f"""{system_prompt}

---

{observation}

---

Based on the current state and the user's request, decide what to do next.

Respond with a JSON object matching this schema:
{{
    "thought": "Your reasoning about what to do next...",
    "action_type": "tool_call" or "final_answer",
    "tool_calls": [  // Only if action_type is "tool_call"
        {{
            "id": "unique_id",
            "name": "tool_name",
            "arguments": {{...}}
        }}
    ],
    "final_answer": "..."  // Only if action_type is "final_answer"
}}

IMPORTANT: Use EXACT argument names from the tool signatures shown in the observation.
"""
    
    decision = call_llm_json(full_prompt, AgentDecision)
    return decision


# =============================================================================
# TOOL EXECUTOR
# =============================================================================

def _validate_tool_args(tool, args: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Validate tool arguments against the tool's schema BEFORE execution.
    
    Returns (is_valid, error_message).
    This prevents cryptic KeyError/TypeError and gives actionable feedback.
    """
    schema = tool.args_schema.model_json_schema()
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    # Check for missing required arguments
    missing = [arg for arg in required if arg not in args]
    if missing:
        # Build helpful error message showing expected signature
        expected_parts = []
        for arg_name, arg_info in properties.items():
            arg_type = arg_info.get("type", "any")
            if arg_name in required:
                expected_parts.append(f"{arg_name}: {arg_type} (required)")
            else:
                expected_parts.append(f"{arg_name}: {arg_type} (optional)")
        
        return False, (
            f"Missing required argument(s): {missing}. "
            f"Expected arguments for {tool.name}: {', '.join(expected_parts)}"
        )
    
    # Check for unknown arguments (likely typos)
    unknown = [arg for arg in args if arg not in properties]
    if unknown:
        valid_args = list(properties.keys())
        return False, (
            f"Unknown argument(s): {unknown}. "
            f"Valid arguments for {tool.name}: {valid_args}"
        )
    
    # Basic type validation for common cases
    for arg_name, arg_value in args.items():
        if arg_value is None:
            continue  # None is OK for optional args
            
        expected_type = properties.get(arg_name, {}).get("type")
        if expected_type == "string" and not isinstance(arg_value, str):
            return False, (
                f"Argument '{arg_name}' should be a string, got {type(arg_value).__name__}"
            )
        if expected_type == "integer" and not isinstance(arg_value, int):
            return False, (
                f"Argument '{arg_name}' should be an integer, got {type(arg_value).__name__}"
            )
    
    return True, None


def execute_tool_calls(
    tool_calls: list[ToolCall],
    state: AgentState,
    registry: ToolRegistry,
) -> list[ToolResult]:
    """
    Execute a list of tool calls and return results.
    
    Each tool is executed in sequence. Results are collected for
    feeding back into the observation.
    
    SOTA Features:
    - Pre-execution argument validation (prevents cryptic errors)
    - Helpful error messages showing expected arguments
    """
    results = []
    
    for call in tool_calls:
        # Check if tool is blocked due to repeated failures
        if state.is_tool_blocked(call.name):
            results.append(ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                success=False,
                error=f"Tool '{call.name}' is blocked after 3 consecutive failures. Try a different approach."
            ))
            continue
        
        tool = registry.get(call.name)
        
        if tool is None:
            # Suggest similar tool names
            all_tools = [t.name for t in registry.list_tools()]
            results.append(ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                success=False,
                error=f"Unknown tool: '{call.name}'. Available tools: {all_tools}"
            ))
            continue
        
        # === FIX 1 & 2: Validate arguments BEFORE execution ===
        is_valid, validation_error = _validate_tool_args(tool, call.arguments)
        if not is_valid:
            logger.warning(f"Tool {call.name} argument validation failed: {validation_error}")
            results.append(ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                success=False,
                error=validation_error
            ))
            continue
        
        logger.info(f"Executing tool: {call.name} with args: {call.arguments}")
        
        try:
            result = tool.execute(call.arguments, state)
            results.append(result)
            
            # Update state based on tool results
            if result.success:
                _update_state_from_result(state, call.name, result)
            
        except Exception as e:
            logger.exception(f"Tool {call.name} raised exception")
            results.append(ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                success=False,
                error=f"Tool execution error: {str(e)[:200]}"
            ))
    
    return results


def _update_state_from_result(state: AgentState, tool_name: str, result: ToolResult) -> None:
    """
    Update agent state based on successful tool results.
    
    This is where we persist learned information (factory config, metrics, etc.)
    """
    if tool_name in ("parse_factory", "get_demo_factory") and result.output:
        # Store the factory config
        factory_data = result.output.get("factory")
        if factory_data:
            state.factory = FactoryConfig.model_validate(factory_data)
            logger.info(f"Factory loaded: {len(state.factory.machines)} machines, {len(state.factory.jobs)} jobs")
    
    elif tool_name == "simulate_scenario" and result.output:
        # Store simulation results
        from .models import ScenarioSpec, ScenarioMetrics
        
        spec_data = result.output.get("spec")
        metrics_data = result.output.get("metrics")
        
        if spec_data:
            spec = ScenarioSpec.model_validate(spec_data)
            state.scenarios_run.append(spec)
        
        if metrics_data:
            metrics = ScenarioMetrics.model_validate(metrics_data)
            state.metrics_collected.append(metrics)
        
        logger.info(f"Simulation complete: {result.output.get('scenario_type')}")


# =============================================================================
# GRACEFUL DEGRADATION (Partial Answer Synthesis)
# =============================================================================

def _synthesize_partial_answer(state: AgentState) -> str:
    """
    Synthesize a useful partial answer when the agent hits MAX_STEPS.
    
    Instead of just saying "ran out of steps", we analyze what data
    was collected and provide a meaningful summary.
    """
    parts = ["# Partial Analysis (Step Limit Reached)\n"]
    parts.append(f"I reached the step limit ({state.max_steps}) before completing the full analysis, ")
    parts.append("but here's what I was able to determine:\n\n")
    
    # Factory information
    if state.factory:
        parts.append("## Factory Configuration\n")
        parts.append(f"- **Machines**: {', '.join([f'{m.id} ({m.name})' for m in state.factory.machines])}\n")
        parts.append(f"- **Jobs**: {', '.join([f'{j.id} ({j.name})' for j in state.factory.jobs])}\n\n")
    else:
        parts.append("## Factory Configuration\n")
        parts.append("*Factory was not successfully loaded.*\n\n")
    
    # Simulation results
    if state.scenarios_run and state.metrics_collected:
        parts.append("## Simulation Results\n\n")
        
        for spec, metrics in zip(state.scenarios_run, state.metrics_collected):
            scenario_label = spec.scenario_type.value
            if spec.rush_job_id:
                scenario_label += f" (Rush: {spec.rush_job_id})"
            if spec.slowdown_factor:
                scenario_label += f" ({spec.slowdown_factor}x slowdown)"
            
            parts.append(f"### {scenario_label}\n")
            parts.append(f"- **Makespan**: {metrics.makespan_hour} hours\n")
            parts.append(f"- **Bottleneck**: {metrics.bottleneck_machine_id} ({metrics.bottleneck_utilization:.0%} utilization)\n")
            
            late_jobs = [f"{k}: +{v}h" for k, v in metrics.job_lateness.items() if v > 0]
            if late_jobs:
                parts.append(f"- **Late Jobs**: {', '.join(late_jobs)}\n")
            else:
                parts.append("- **Late Jobs**: None\n")
            parts.append("\n")
        
        # Add basic analysis if we have baseline
        baseline_metrics = None
        for spec, metrics in zip(state.scenarios_run, state.metrics_collected):
            if spec.scenario_type.value == "BASELINE":
                baseline_metrics = metrics
                break
        
        if baseline_metrics:
            parts.append("## Key Findings\n")
            parts.append(f"- The bottleneck machine is **{baseline_metrics.bottleneck_machine_id}** ")
            parts.append(f"with {baseline_metrics.bottleneck_utilization:.0%} utilization.\n")
            parts.append(f"- Baseline makespan is **{baseline_metrics.makespan_hour} hours**.\n")
            
            all_on_time = all(v == 0 for v in baseline_metrics.job_lateness.values())
            if all_on_time:
                parts.append("- All jobs complete on time in the baseline scenario.\n")
    else:
        parts.append("## Simulation Results\n")
        parts.append("*No simulations were completed.*\n\n")
    
    # What was the agent trying to do?
    if state.scratchpad:
        parts.append("\n## Investigation Progress\n")
        # Show last few thoughts
        recent_thoughts = state.scratchpad[-3:]
        for thought in recent_thoughts:
            # Clean up the thought format
            clean_thought = thought.replace("[Step ", "- Step ").replace("]", ":")
            parts.append(f"{clean_thought}\n")
    
    parts.append("\n---\n*Analysis was incomplete due to step limit. ")
    parts.append("Try a more specific question or increase the step limit.*")
    
    return "".join(parts)


# =============================================================================
# THE MAIN LOOP (The "Heartbeat")
# =============================================================================

def run_agent(user_request: str, max_steps: int = 15) -> AgentState:
    """
    Run the agent loop until completion or failure.
    
    This is the main entry point for the agent system.
    
    Args:
        user_request: The user's natural language query
        max_steps: Maximum number of loop iterations
    
    Returns:
        Final AgentState with results (check state.final_answer for output)
    """
    logger.info("=" * 60)
    logger.info("🤖 Agent starting")
    logger.info(f"   Request: {user_request[:100]}...")
    logger.info("=" * 60)
    
    # Initialize state
    state = AgentState(
        user_request=user_request,
        max_steps=max_steps,
    )
    
    # Add initial user message
    state.add_message("user", user_request)
    
    # Initialize tool registry
    registry = create_default_registry()
    
    # === THE LOOP ===
    while state.is_running():
        logger.info(f"\n--- Step {state.steps + 1}/{state.max_steps} ---")
        
        # 1. OBSERVE: Build the observation
        observation = build_observation(state, registry)
        logger.debug(f"Observation:\n{observation[:500]}...")
        
        # 2. DECIDE: Call LLM for next action
        try:
            decision = call_llm_for_decision(observation, SYSTEM_PROMPT, registry)
            logger.info(f"Decision: {decision.action_type}")
            logger.info(f"Thought: {decision.thought[:200]}...")
            
            # Record the thought
            state.add_thought(decision.thought)
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            state.record_error(f"LLM call failed: {str(e)[:100]}")
            state.increment_step()
            continue
        
        # 3. ACT: Execute the decision
        if decision.action_type == "final_answer":
            # Agent is done
            logger.info("Agent providing final answer")
            state.complete(decision.final_answer or "No answer provided")
            
        elif decision.action_type == "tool_call":
            if not decision.tool_calls:
                logger.warning("tool_call action but no tools specified")
                state.record_error("Decided to call tools but didn't specify any")
                state.increment_step()
                continue
            
            # Execute tools
            results = execute_tool_calls(decision.tool_calls, state, registry)
            
            # Add tool results to conversation history
            for result in results:
                result_summary = json.dumps(result.output if result.success else {"error": result.error}, indent=2)
                state.add_message(
                    role="tool",
                    content=result_summary[:2000],  # Truncate to avoid context blowup
                    tool_call_id=result.tool_call_id,
                    name=result.tool_name,
                )
                
                if result.success:
                    state.record_success(result.tool_name)
                    logger.info(f"Tool {result.tool_name} succeeded")
                else:
                    # Track per-tool failures (blocks tool after 3 consecutive failures)
                    was_blocked = state.record_tool_failure(result.tool_name, result.error or "Unknown error")
                    if was_blocked:
                        logger.warning(f"Tool {result.tool_name} is now BLOCKED after repeated failures")
                    state.record_error(result.error or "Unknown error")
                    logger.warning(f"Tool {result.tool_name} failed: {result.error}")
        
        # 4. INCREMENT: Advance step counter
        state.increment_step()
    
    # === LOOP ENDED ===
    
    # === FIX 3: Graceful MAX_STEPS handling ===
    # Instead of just saying "ran out of steps", synthesize a useful partial answer
    if state.status == AgentStatus.MAX_STEPS:
        logger.warning("Agent hit step limit - synthesizing partial answer")
        state.final_answer = _synthesize_partial_answer(state)
    
    logger.info("=" * 60)
    logger.info(f"🤖 Agent finished with status: {state.status.value}")
    logger.info(f"   Steps: {state.steps}")
    logger.info(f"   Final answer length: {len(state.final_answer or '')}")
    logger.info("=" * 60)
    
    return state


# =============================================================================
# CONVENIENCE WRAPPER
# =============================================================================

def run_agent_and_get_answer(user_request: str) -> str:
    """
    Run the agent and return just the final answer string.
    
    Convenience wrapper for simple use cases.
    """
    state = run_agent(user_request)
    return state.final_answer or "Agent did not produce an answer."

