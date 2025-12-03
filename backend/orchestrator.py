"""
Orchestrator module - thin wrapper around the new agent system.

The new architecture uses the agent_engine.run_agent() function directly.
This module is kept for any orchestration logic that might be needed
outside of the agent loop.
"""

import logging

from .agent_engine import run_agent, run_agent_and_get_answer

logger = logging.getLogger(__name__)


def analyze_factory(factory_description: str) -> str:
    """
    High-level entrypoint for factory analysis.
    
    Runs the agent system to parse the factory, simulate scenarios,
    and generate a briefing.
    
    Args:
        factory_description: Free-text description of the factory
        
    Returns:
        Markdown briefing with analysis results
    """
    return run_agent_and_get_answer(
        f"Analyze this factory and give me a briefing: {factory_description}"
    )
