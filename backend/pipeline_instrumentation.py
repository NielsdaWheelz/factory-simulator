"""
PRF1: Pipeline instrumentation wrapper for debug payload construction.

This module provides wrappers around individual pipeline stages to collect
structured debug information. It builds PipelineStageRecords for each stage
and assembles them into a PipelineDebugPayload.

The instrumentation is additive and does not change the control flow or
error handling semantics of the underlying pipeline.

See debug_types.py for the PipelineDebugPayload and PipelineStageRecord schemas.
"""

import logging
from typing import Any, Callable, TypeVar, Tuple
from .debug_types import (
    PipelineDebugPayload,
    PipelineStageRecord,
    StageStatus,
    StageKind,
    DebugInputs,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _build_stage_record(
    stage_id: str,
    stage_name: str,
    stage_kind: StageKind,
    agent_model: str | None = None,
) -> PipelineStageRecord:
    """Create a new PipelineStageRecord with default values."""
    return PipelineStageRecord(
        id=stage_id,
        name=stage_name,
        kind=stage_kind,
        status=StageStatus.SUCCESS,
        agent_model=agent_model,
        summary={},
        errors=[],
        payload_preview=None,
    )


def instrument_stage(
    stage_id: str,
    stage_name: str,
    stage_kind: StageKind,
    agent_model: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., Tuple[T, PipelineStageRecord]]]:
    """
    Decorator to wrap a stage function and collect debug information.

    Wraps the function to:
    - Create a PipelineStageRecord
    - Execute the function in a try/except block
    - On success: set status=SUCCESS, return (result, record)
    - On exception: set status=FAILED, append error message, re-raise

    Args:
        stage_id: Stage identifier (e.g., "O0", "D1")
        stage_name: Human-readable name (e.g., "Extract Explicit IDs")
        stage_kind: StageKind enum (ONBOARDING, DECISION, or SIMULATION)
        agent_model: LLM model name (e.g., "gpt-4.1") or None for deterministic stages

    Returns:
        Decorator that wraps a function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., Tuple[T, PipelineStageRecord]]:
        def wrapper(*args, **kwargs) -> Tuple[T, PipelineStageRecord]:
            record = _build_stage_record(stage_id, stage_name, stage_kind, agent_model)
            try:
                result = func(*args, **kwargs)
                record.status = StageStatus.SUCCESS
                return result, record
            except Exception as e:
                record.status = StageStatus.FAILED
                record.errors.append(str(e)[:200])
                raise

        return wrapper

    return decorator


def make_stage_wrapper(
    stage_id: str,
    stage_name: str,
    stage_kind: StageKind,
    agent_model: str | None = None,
) -> Callable[[T], Tuple[T, PipelineStageRecord]]:
    """
    Create a function that wraps a stage execution and returns (result, record).

    This is a functional alternative to the decorator for inline use.

    Usage:
        wrapper = make_stage_wrapper("O0", "Extract Explicit IDs", StageKind.ONBOARDING)
        result, record = wrapper(lambda: my_stage_function())

    Args:
        stage_id: Stage identifier
        stage_name: Human-readable name
        stage_kind: StageKind enum
        agent_model: LLM model name or None

    Returns:
        Function that takes a callable and returns (result, record) tuple
    """

    def execute_with_instrumentation(func: Callable[[], T]) -> Tuple[T, PipelineStageRecord]:
        record = _build_stage_record(stage_id, stage_name, stage_kind, agent_model)
        try:
            result = func()
            record.status = StageStatus.SUCCESS
            return result, record
        except Exception as e:
            record.status = StageStatus.FAILED
            record.errors.append(str(e)[:200])
            raise

    return execute_with_instrumentation


def build_debug_inputs(factory_text: str, situation_text: str) -> DebugInputs:
    """Build DebugInputs from raw text inputs."""
    return DebugInputs(
        factory_text_chars=len(factory_text),
        factory_text_preview=factory_text[:200],
        situation_text_chars=len(situation_text),
        situation_text_preview=situation_text[:200],
    )


def compute_overall_status(stages: list[PipelineStageRecord]) -> str:
    """
    Compute overall_status from stage records.

    Logic:
    - SUCCESS: all stages have status==SUCCESS
    - FAILED: any DECISION or SIMULATION stage has status==FAILED
    - PARTIAL: onboarding stage(s) failed, but decision stages are present

    Args:
        stages: List of PipelineStageRecord

    Returns:
        String: "SUCCESS", "FAILED", or "PARTIAL"
    """
    all_success = all(s.status == StageStatus.SUCCESS for s in stages)
    if all_success:
        return "SUCCESS"

    # Check for decision/simulation failures
    decision_sim_failed = any(
        s.kind in (StageKind.DECISION, StageKind.SIMULATION)
        and s.status == StageStatus.FAILED
        for s in stages
    )
    if decision_sim_failed:
        return "FAILED"

    # Onboarding failed but decision stages are present
    return "PARTIAL"


def build_payload(
    factory_text: str,
    situation_text: str,
    stages: list[PipelineStageRecord],
) -> PipelineDebugPayload:
    """Build a complete PipelineDebugPayload from components."""
    return PipelineDebugPayload(
        inputs=build_debug_inputs(factory_text, situation_text),
        overall_status=compute_overall_status(stages),
        stages=stages,
    )
