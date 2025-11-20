"""
FastAPI HTTP server for the factory simulator.

Exposes a single POST /api/simulate endpoint that wraps run_onboarded_pipeline.
Handles JSON serialization of Pydantic models and enum types.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import run_onboarded_pipeline
from serializer import serialize_simulation_result

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Factory Simulator API",
    description="REST API for factory simulation with onboarded factory configs",
    version="0.1.0",
)

# Allow local development from frontend vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for demo; can be tightened later
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulateRequest(BaseModel):
    """Request body for POST /api/simulate endpoint."""

    factory_description: str
    situation_text: str


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
    logger.info(
        "POST /api/simulate factory_desc_len=%d situation_text_len=%d",
        len(req.factory_description),
        len(req.situation_text),
    )

    result = run_onboarded_pipeline(
        factory_text=req.factory_description,
        situation_text=req.situation_text,
    )

    # Ensure result is JSON serializable
    serialized = serialize_simulation_result(result)

    logger.info(
        "simulate endpoint returning result with %d scenarios",
        len(serialized.get("specs", [])),
    )

    return serialized
