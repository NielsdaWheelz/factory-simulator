"""
FastAPI HTTP server for the factory simulator.

Exposes:
- POST /api/agent - Main agent endpoint for factory analysis

The agent system handles:
- Factory parsing from natural language
- Simulation of scenarios
- Briefing generation
"""

import logging
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from .agent_engine import run_agent
from .agent_types import AgentState, AgentStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
    force=True
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Factory Simulator API",
    description="REST API for factory simulation powered by an AI agent",
    version="2.0.0",
)

# Configure CORS
origins_env = os.getenv("BACKEND_CORS_ORIGINS")
if origins_env:
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    allow_origins = ["*"]

logger.info("CORS allow_origins = %r", allow_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class AgentRequest(BaseModel):
    """Request body for POST /api/agent endpoint."""
    
    user_request: str = Field(..., description="Natural language request for the agent")
    max_steps: int = Field(default=15, description="Maximum agent loop iterations")
    llm_budget: int = Field(default=10, description="Maximum LLM calls allowed")


class AgentTraceStep(BaseModel):
    """A single step in the agent's execution trace."""
    
    step_number: int
    thought: str
    action_type: str  # "tool_call" or "final_answer"
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_success: Optional[bool] = None
    tool_output: Optional[str] = None
    tool_error: Optional[str] = None


class LLMCallInfo(BaseModel):
    """Info about an LLM call for frontend display."""
    call_id: int
    schema_name: str
    purpose: str
    latency_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    step_id: Optional[int] = None


class PlanStepInfo(BaseModel):
    """Info about a plan step for frontend display."""
    id: int
    type: str
    status: str  # "pending", "running", "done", "failed"
    params: dict = {}
    error_message: Optional[str] = None


class DataPreviewInfo(BaseModel):
    """Preview of data flowing through the system."""
    label: str
    type_name: str
    preview: str
    size: Optional[str] = None


class OperationInfo(BaseModel):
    """A single operation in the data flow."""
    id: str
    type: str  # "function", "llm", "validation"
    name: str
    duration_ms: int = 0
    inputs: list[DataPreviewInfo] = Field(default_factory=list)
    outputs: list[DataPreviewInfo] = Field(default_factory=list)
    schema_name: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None


class DataFlowStepInfo(BaseModel):
    """A step in the data flow for visualization."""
    step_id: int
    step_type: str
    step_name: str
    status: str
    total_duration_ms: int = 0
    operations: list[OperationInfo] = Field(default_factory=list)
    step_input: Optional[DataPreviewInfo] = None
    step_output: Optional[DataPreviewInfo] = None


class OnboardingIssueInfo(BaseModel):
    """Info about an onboarding issue for frontend display."""
    type: str
    severity: str
    message: str
    related_ids: Optional[list[str]] = None


class AltFactoryInfo(BaseModel):
    """Reduced representation of an alternative factory config for frontend display."""
    machines: list[str]  # Just machine IDs
    jobs: list[str]  # Just job IDs
    mode: str  # Extraction mode that produced this config


class DiffSummaryInfo(BaseModel):
    """Summary of differences between primary and an alternative config."""
    alt_index: int  # Index of the alternative (0-based)
    mode: str  # Extraction mode that produced the alternative
    summary: str  # Human-readable summary of differences


class AgentResponse(BaseModel):
    """Response from the agent endpoint."""
    
    status: str = Field(..., description="Agent completion status: DONE, FAILED, MAX_STEPS, BUDGET_EXCEEDED")
    steps_taken: int
    llm_calls_used: int
    final_answer: Optional[str] = None
    
    # Domain results (if available)
    factory: Optional[dict] = None
    scenarios_run: list[dict] = Field(default_factory=list)
    metrics_collected: list[dict] = Field(default_factory=list)
    
    # Plan information (structured for visualization)
    plan_summary: Optional[str] = None
    plan_steps: list[PlanStepInfo] = Field(default_factory=list)
    
    # LLM call tracking (for observability)
    llm_calls: list[LLMCallInfo] = Field(default_factory=list)
    
    # Data flow visualization
    data_flow: list[DataFlowStepInfo] = Field(default_factory=list)
    
    # The execution trace (for debugging/observability)
    trace: list[AgentTraceStep] = Field(default_factory=list)
    scratchpad: list[str] = Field(default_factory=list)
    
    # Onboarding diagnostics (for robust onboarding)
    onboarding_issues: list[OnboardingIssueInfo] = Field(default_factory=list)
    onboarding_score: Optional[int] = None
    onboarding_trust: Optional[str] = None
    
    # Alternative factory interpretations (PR9)
    alt_factories: list[AltFactoryInfo] = Field(default_factory=list)
    diff_summaries: list[DiffSummaryInfo] = Field(default_factory=list)


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.post("/api/agent")
def agent_endpoint(req: AgentRequest) -> dict:
    """
    Main endpoint for factory analysis using the AI agent.
    
    The agent will:
    1. Generate a plan based on the user's request
    2. Execute the plan (parse factory, run simulations, etc.)
    3. Generate a final answer with insights and recommendations
    
    Args:
        req: Request containing user_request, max_steps, and llm_budget
    
    Returns:
        AgentResponse with status, final_answer, domain results, and trace
    """
    logger.info("=" * 80)
    logger.info("🤖 POST /api/agent endpoint called")
    logger.info(f"   User request: {req.user_request[:100]}...")
    logger.info(f"   Max steps: {req.max_steps}")
    logger.info(f"   LLM budget: {req.llm_budget}")
    logger.info("=" * 80)
    
    # Run the agent
    state = run_agent(req.user_request, max_steps=req.max_steps, llm_budget=req.llm_budget)
    
    # Build trace from messages and scratchpad
    trace = _build_trace_from_state(state)
    
    # Build structured plan steps
    plan_steps = [
        PlanStepInfo(
            id=step.id,
            type=step.type.value,
            status=step.status,
            params=step.params,
            error_message=step.error.message if step.error else None,
        )
        for step in state.plan
    ]
    
    # Build LLM call info
    llm_calls = [
        LLMCallInfo(
            call_id=call.call_id,
            schema_name=call.schema_name,
            purpose=call.purpose,
            latency_ms=call.latency_ms,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            step_id=call.step_id,
        )
        for call in state.llm_calls
    ]
    
    # Build data flow info
    data_flow = []
    for df_step in state.data_flow:
        operations = []
        for op in df_step.operations:
            operations.append(OperationInfo(
                id=op.id,
                type=op.type.value,
                name=op.name,
                duration_ms=op.duration_ms,
                inputs=[DataPreviewInfo(
                    label=inp.label,
                    type_name=inp.type_name,
                    preview=inp.preview,
                    size=inp.size,
                ) for inp in op.inputs],
                outputs=[DataPreviewInfo(
                    label=out.label,
                    type_name=out.type_name,
                    preview=out.preview,
                    size=out.size,
                ) for out in op.outputs],
                schema_name=op.schema_name,
                input_tokens=op.input_tokens,
                output_tokens=op.output_tokens,
                error=op.error,
            ))
        
        data_flow.append(DataFlowStepInfo(
            step_id=df_step.step_id,
            step_type=df_step.step_type,
            step_name=df_step.step_name,
            status=df_step.status,
            total_duration_ms=df_step.total_duration_ms,
            operations=operations,
            step_input=DataPreviewInfo(
                label=df_step.step_input.label,
                type_name=df_step.step_input.type_name,
                preview=df_step.step_input.preview,
                size=df_step.step_input.size,
            ) if df_step.step_input else None,
            step_output=DataPreviewInfo(
                label=df_step.step_output.label,
                type_name=df_step.step_output.type_name,
                preview=df_step.step_output.preview,
                size=df_step.step_output.size,
            ) if df_step.step_output else None,
        ))
    
    # Build onboarding issues info
    onboarding_issues = [
        OnboardingIssueInfo(
            type=issue.type,
            severity=issue.severity,
            message=issue.message,
            related_ids=issue.related_ids,
        )
        for issue in state.onboarding_issues
    ]
    
    # Build alternative factories info (PR9)
    alt_factories = [
        AltFactoryInfo(
            machines=[m.id for m in alt_factory.machines],
            jobs=[j.id for j in alt_factory.jobs],
            mode=state.alt_factory_modes[i] if i < len(state.alt_factory_modes) else "unknown",
        )
        for i, alt_factory in enumerate(state.alt_factories)
    ]
    
    # Build diff summaries info (PR9)
    diff_summaries_info = [
        DiffSummaryInfo(
            alt_index=i,
            mode=state.alt_factory_modes[i] if i < len(state.alt_factory_modes) else "unknown",
            summary=summary,
        )
        for i, summary in enumerate(state.diff_summaries)
    ]
    
    # Build response
    response = AgentResponse(
        status=state.status.value,
        steps_taken=state.steps,
        llm_calls_used=state.llm_calls_used,
        final_answer=state.final_answer,
        factory=state.factory.model_dump() if state.factory else None,
        scenarios_run=[s.model_dump() for s in state.scenarios_run],
        metrics_collected=[m.model_dump() for m in state.metrics_collected],
        plan_summary=state.get_plan_summary() if state.plan else None,
        plan_steps=plan_steps,
        llm_calls=llm_calls,
        data_flow=data_flow,
        trace=trace,
        scratchpad=state.scratchpad,
        onboarding_issues=onboarding_issues,
        onboarding_score=state.onboarding_score,
        onboarding_trust=state.onboarding_trust,
        alt_factories=alt_factories,
        diff_summaries=diff_summaries_info,
    )
    
    logger.info("=" * 80)
    logger.info(f"🤖 Agent completed with status: {state.status.value}")
    logger.info(f"   Steps: {state.steps}")
    logger.info(f"   LLM calls: {state.llm_calls_used}/{req.llm_budget}")
    logger.info(f"   Scenarios run: {len(state.scenarios_run)}")
    logger.info(f"   Final answer length: {len(state.final_answer or '')}")
    logger.info("=" * 80)
    
    return response.model_dump()


def _build_trace_from_state(state: AgentState) -> list[AgentTraceStep]:
    """
    Build execution trace from the agent state.
    
    Extracts tool calls and results from the message history
    and pairs them with thoughts from the scratchpad.
    """
    trace = []
    step_num = 0
    
    # Parse through messages to reconstruct trace
    i = 0
    messages = state.messages
    
    while i < len(messages):
        msg = messages[i]
        
        # Look for tool messages (these come after tool calls)
        if msg.role == "tool":
            step_num += 1
            
            # Get the thought from scratchpad if available
            thought = ""
            if step_num - 1 < len(state.scratchpad):
                thought = state.scratchpad[step_num - 1]
                # Remove the "[Step X]" prefix if present
                if thought.startswith("[Step"):
                    thought = thought.split("] ", 1)[-1] if "] " in thought else thought
            
            # Parse tool output
            import json
            try:
                output_data = json.loads(msg.content) if msg.content else {}
            except json.JSONDecodeError:
                output_data = {"raw": msg.content}
            
            tool_success = "error" not in output_data
            tool_output = msg.content[:500] if tool_success else None
            tool_error = output_data.get("error") if not tool_success else None
            
            trace.append(AgentTraceStep(
                step_number=step_num,
                thought=thought,
                action_type="tool_call",
                tool_name=msg.name,
                tool_args=None,
                tool_success=tool_success,
                tool_output=tool_output,
                tool_error=tool_error,
            ))
        
        i += 1
    
    # Add final answer step if present
    if state.final_answer:
        step_num += 1
        thought = state.scratchpad[-1] if state.scratchpad else "Delivering final answer"
        if thought.startswith("[Step"):
            thought = thought.split("] ", 1)[-1] if "] " in thought else thought
        
        trace.append(AgentTraceStep(
            step_number=step_num,
            thought=thought,
            action_type="final_answer",
        ))
    
    return trace


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}
