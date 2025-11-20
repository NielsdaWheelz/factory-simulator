"""
FastAPI HTTP server for the factory simulator.

Exposes a single POST /api/simulate endpoint that wraps run_onboarded_pipeline.
Handles JSON serialization of Pydantic models and enum types.
"""

import logging
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .orchestrator import run_onboarded_pipeline
from .serializer import serialize_simulation_result

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
    logger.info(f"   Factory: {len(result['factory'].machines)} machines, {len(result['factory'].jobs)} jobs")
    logger.info(f"   Scenarios: {len(result['specs'])} generated")
    logger.info(f"   Metrics: {len(result['metrics'])} computed")
    logger.info(f"   Briefing length: {len(result['briefing'])} chars")
    logger.info("   Serializing response...")

    # Filter result to only include API contract keys: factory, specs, metrics, briefing, meta
    api_response = {
        "factory": result["factory"],
        "specs": result["specs"],
        "metrics": result["metrics"],
        "briefing": result["briefing"],
        "meta": result["meta"],
    }

    # Ensure result is JSON serializable
    serialized = serialize_simulation_result(api_response)

    logger.info("=" * 80)
    logger.info("✅ Response serialized and ready to send")
    logger.info(f"   Total response keys: {list(serialized.keys())}")
    logger.info("=" * 80)

    return serialized
