"""
FastAPI HTTP server for the factory simulator.

Exposes:
- POST /api/simulate - Legacy pipeline endpoint
- POST /api/onboard - Factory parsing endpoint
- POST /api/agent - NEW: SOTA agent endpoint with trace

Handles JSON serialization of Pydantic models and enum types.
"""

import logging
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from .orchestrator import run_onboarded_pipeline, run_onboarding, is_toy_factory
from .serializer import serialize_simulation_result
from .models import OnboardingRequest, OnboardingResponse
from .agent_engine import run_agent
from .agent_types import AgentState, AgentStatus

# Configure logging to show INFO level messages in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
    force=True
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Factory Simulator API",
    description="REST API for factory simulation with onboarded factory configs",
    version="0.1.0",
)

# Configure CORS origins from environment variable or default to "*" for local dev
origins_env = os.getenv("BACKEND_CORS_ORIGINS")
if origins_env:
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    allow_origins = ["*"]

import logging

logger = logging.getLogger(__name__)
logger.info("CORS allow_origins = %r", allow_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SimulateRequest(BaseModel):
    """Request body for POST /api/simulate endpoint."""

    factory_description: str
    situation_text: str


class AgentRequest(BaseModel):
    """Request body for POST /api/agent endpoint."""
    
    user_request: str = Field(..., description="Natural language request for the agent")
    max_steps: int = Field(default=15, description="Maximum agent loop iterations")


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
    
    status: str = Field(..., description="Agent completion status: DONE, FAILED, MAX_STEPS")
    steps_taken: int
    final_answer: Optional[str] = None
    
    # Domain results (if available)
    factory: Optional[dict] = None
    scenarios_run: list[dict] = Field(default_factory=list)
    metrics_collected: list[dict] = Field(default_factory=list)
    
    # The execution trace (for debugging/observability)
    trace: list[AgentTraceStep] = Field(default_factory=list)
    scratchpad: list[str] = Field(default_factory=list)


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    """
    HTTP endpoint for running the onboarding + simulation pipeline.

    Wraps run_onboarded_pipeline(factory_text, situation_text) and returns
    a JSON-serializable response.

    Args:
        req: Request containing factory_description and situation_text

    Returns:
        A dict containing:
        - factory: Factory configuration (machines and jobs)
        - specs: List of scenario specifications
        - metrics: List of metrics for each scenario
        - briefing: Markdown briefing string
        - meta: Metadata (used_default_factory, onboarding_errors)

    Raises:
        RuntimeError: If pipeline encounters an error
    """
    logger.info("=" * 80)
    logger.info("🚀 POST /api/simulate endpoint called")
    logger.info(f"   Factory description length: {len(req.factory_description)} chars")
    logger.info(f"   Situation text length: {len(req.situation_text)} chars")
    logger.info("   Starting pipeline...")
    logger.info("=" * 80)

    result = run_onboarded_pipeline(
        factory_text=req.factory_description,
        situation_text=req.situation_text,
    )

    logger.info("=" * 80)
    logger.info("✅ Pipeline completed successfully")
    logger.info(f"   Factory: {len(result.factory.machines)} machines, {len(result.factory.jobs)} jobs")
    logger.info(f"   Scenarios: {len(result.specs)} generated")
    logger.info(f"   Metrics: {len(result.metrics)} computed")
    logger.info(f"   Briefing length: {len(result.briefing)} chars")
    if result.debug is not None:
        logger.info(f"   Debug payload: {len(result.debug.stages)} stages")
    logger.info("   Serializing response...")

    # PRF2: Convert PipelineRunResult to HTTP dict (including debug payload if available)
    api_response = result.to_http_dict()

    # Ensure result is JSON serializable
    serialized = serialize_simulation_result(api_response)

    logger.info("=" * 80)
    logger.info("✅ Response serialized and ready to send")
    logger.info(f"   Total response keys: {list(serialized.keys())}")
    logger.info("=" * 80)

    return serialized


@app.post("/api/onboard")
def onboard(req: OnboardingRequest) -> dict:
    """
    HTTP endpoint for onboarding a factory description.

    Wraps run_onboarding and returns factory + metadata (no simulation).

    Args:
        req: Request containing factory_description

    Returns:
        A dict containing:
        - factory: Factory configuration (machines and jobs)
        - meta: Metadata (used_default_factory, onboarding_errors)

    Raises:
        RuntimeError: If pipeline encounters an error
    """
    logger.info("=" * 80)
    logger.info("🚀 POST /api/onboard endpoint called")
    logger.info(f"   Factory description length: {len(req.factory_description)} chars")
    logger.info("   Starting onboarding pipeline...")
    logger.info("=" * 80)

    factory, meta, _stages = run_onboarding(req.factory_description)

    response = OnboardingResponse(factory=factory, meta=meta)

    logger.info("=" * 80)
    logger.info("✅ Onboarding completed successfully")
    logger.info(f"   Factory: {len(response.factory.machines)} machines, {len(response.factory.jobs)} jobs")
    logger.info(f"   Used default factory: {meta.used_default_factory}")
    logger.info(f"   Onboarding errors: {len(meta.onboarding_errors)}")
    logger.info("   Serializing response...")

    # Ensure result is JSON serializable
    serialized = serialize_simulation_result({
        "factory": response.factory,
        "meta": response.meta,
    })

    logger.info("=" * 80)
    logger.info("✅ Response serialized and ready to send")
    logger.info(f"   Total response keys: {list(serialized.keys())}")
    logger.info("=" * 80)

    return serialized


@app.post("/api/agent")
def agent_endpoint(req: AgentRequest) -> dict:
    """
    HTTP endpoint for the SOTA agent system.
    
    This endpoint runs the full agent loop, allowing the LLM to:
    - Decide which tools to call
    - Iterate until it has enough information
    - Generate a final answer
    
    Returns the final answer plus a full execution trace for observability.
    
    Args:
        req: Request containing user_request and optional max_steps
    
    Returns:
        AgentResponse with status, final_answer, domain results, and trace
    """
    logger.info("=" * 80)
    logger.info("🤖 POST /api/agent endpoint called")
    logger.info(f"   User request: {req.user_request[:100]}...")
    logger.info(f"   Max steps: {req.max_steps}")
    logger.info("=" * 80)
    
    # Run the agent
    state = run_agent(req.user_request, max_steps=req.max_steps)
    
    # Build trace from messages and scratchpad
    trace = _build_trace_from_state(state)
    
    # Build response
    response = AgentResponse(
        status=state.status.value,
        steps_taken=state.steps,
        final_answer=state.final_answer,
        factory=state.factory.model_dump() if state.factory else None,
        scenarios_run=[s.model_dump() for s in state.scenarios_run],
        metrics_collected=[m.model_dump() for m in state.metrics_collected],
        trace=trace,
        scratchpad=state.scratchpad,
    )
    
    logger.info("=" * 80)
    logger.info(f"🤖 Agent completed with status: {state.status.value}")
    logger.info(f"   Steps: {state.steps}")
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
                tool_args=None,  # We don't store args in messages currently
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
