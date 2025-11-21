"""
Type definitions for pipeline debug payloads.

This module defines the shape of debug data that will be attached to simulation responses.
It is intentionally types-only; no code populates these structures in PRF0.

Future PRs will:
- Instrument the onboarding and decision pipeline stages to capture debug info
- Populate PipelineDebugPayload instances
- Attach them to simulation responses

For now, these types serve as a stable contract for the frontend and backend
to agree on the structure of debug metadata.
"""

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    """Status of a single pipeline stage execution.

    - SUCCESS: Stage completed without errors
    - FAILED: Stage encountered an error and did not complete
    - SKIPPED: Stage was skipped (e.g., due to prior failure or conditional logic)
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StageKind(str, Enum):
    """Kind/category of a pipeline stage.

    - ONBOARDING: Factory description parsing and normalization
    - DECISION: LLM-based decision making (scenario generation, briefing, etc.)
    - SIMULATION: Factory simulation / metric computation
    """

    ONBOARDING = "ONBOARDING"
    DECISION = "DECISION"
    SIMULATION = "SIMULATION"


class DebugInputs(BaseModel):
    """Summary of inputs to the pipeline.

    Captures:
    - Length and preview of the factory description text
    - Length and preview of the situation text

    These previews help with debugging without storing massive amounts of text.
    """

    factory_text_chars: int = Field(
        ..., description="Total character count of the factory description"
    )
    factory_text_preview: str = Field(
        ..., description="First ~200 chars of factory description for visibility"
    )
    situation_text_chars: int = Field(
        ..., description="Total character count of the situation text"
    )
    situation_text_preview: str = Field(
        ..., description="First ~200 chars of situation text for visibility"
    )


class PayloadPreview(BaseModel):
    """Preview of a structured payload (e.g., LLM response, parsed JSON).

    Allows attaching a preview of data that was processed during a stage,
    without storing the full payload (which may be large).
    """

    type: Literal["json", "text", "summary"] = Field(
        ..., description="Type of preview: raw JSON, plain text, or summary"
    )
    content: str = Field(
        ..., description="Preview content (may be truncated)"
    )
    truncated: bool = Field(
        ..., description="True if content was truncated due to size limits"
    )


# Alias for generic stage summary; will be refined in future PRs
StageSummary = dict[str, Any]


class PipelineStageRecord(BaseModel):
    """Record of a single stage in the pipeline execution.

    Captures:
    - Metadata (id, name, kind, status)
    - Which model was used (if any)
    - A generic summary dict (structure TBD in future PRs)
    - Any errors that occurred
    - Optional preview of the stage's output
    """

    id: str = Field(
        ..., description="Stage identifier, e.g. 'O0', 'O1', 'D1', etc."
    )
    name: str = Field(
        ..., description="Human-readable stage name, e.g. 'Extract Explicit IDs'"
    )
    kind: StageKind = Field(
        ..., description="Kind of stage: ONBOARDING, DECISION, or SIMULATION"
    )
    status: StageStatus = Field(
        ..., description="Execution status: SUCCESS, FAILED, or SKIPPED"
    )
    agent_model: Optional[str] = Field(
        default=None, description="Model used by agent in this stage (e.g. 'claude-opus')"
    )
    summary: StageSummary = Field(
        default_factory=dict, description="Generic summary dict; structure refined in future PRs"
    )
    errors: list[str] = Field(
        default_factory=list, description="List of error messages, if any"
    )
    payload_preview: Optional[PayloadPreview] = Field(
        default=None, description="Optional preview of stage output (e.g., LLM response, parsed JSON)"
    )


class PipelineDebugPayload(BaseModel):
    """Shape of the optional debug payload for simulation responses.

    PRF0: This is a types-only contract. No code populates this yet.
    Future PRs will:
    - Instrument onboarding and decision pipeline stages to populate this
    - Attach it to the /api/simulate response (as an optional field)

    Semantics of overall_status:
    - SUCCESS: All stages completed successfully, coverage > threshold
    - PARTIAL: Onboarding fell back to toy factory, but decision pipeline ran
    - FAILED: Decision pipeline failed or unrecoverable error occurred
    """

    inputs: DebugInputs = Field(
        ..., description="Summary of pipeline inputs"
    )
    overall_status: Literal["SUCCESS", "PARTIAL", "FAILED"] = Field(
        ..., description="Overall pipeline execution status"
    )
    stages: list[PipelineStageRecord] = Field(
        default_factory=list, description="Ordered list of stage execution records"
    )
