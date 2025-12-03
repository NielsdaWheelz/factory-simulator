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
    
    # Plan information
    plan_summary: Optional[str] = None
    
    # The execution trace (for debugging/observability)
    trace: list[AgentTraceStep] = Field(default_factory=list)
    scratchpad: list[str] = Field(default_factory=list)


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
        trace=trace,
        scratchpad=state.scratchpad,
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
