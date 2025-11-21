"""
Smoke tests for debug_types module.

PRF0: Types-only contract tests. These verify that the types are correctly
defined and instantiable, but do NOT test any runtime behavior or integration.

This test file:
- Imports all debug types
- Constructs minimal valid instances in memory
- Verifies field names and type structure
- Does NOT call any pipeline code or modify any behavior
"""

import pytest
from backend.debug_types import (
    StageStatus,
    StageKind,
    DebugInputs,
    PayloadPreview,
    PipelineStageRecord,
    PipelineDebugPayload,
)


class TestDebugTypesImport:
    """Verify all debug types import successfully."""

    def test_stage_status_enum_values(self):
        """StageStatus should have exactly three values."""
        assert StageStatus.SUCCESS.value == "SUCCESS"
        assert StageStatus.FAILED.value == "FAILED"
        assert StageStatus.SKIPPED.value == "SKIPPED"

    def test_stage_kind_enum_values(self):
        """StageKind should have exactly three values."""
        assert StageKind.ONBOARDING.value == "ONBOARDING"
        assert StageKind.DECISION.value == "DECISION"
        assert StageKind.SIMULATION.value == "SIMULATION"


class TestDebugInputsStructure:
    """Verify DebugInputs model structure."""

    def test_minimal_debug_inputs(self):
        """Should construct minimal DebugInputs."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1, M2, J1, J2",
            situation_text_chars=50,
            situation_text_preview="Rush job arrives",
        )
        assert inputs.factory_text_chars == 100
        assert inputs.factory_text_preview == "M1, M2, J1, J2"
        assert inputs.situation_text_chars == 50
        assert inputs.situation_text_preview == "Rush job arrives"

    def test_debug_inputs_field_names(self):
        """DebugInputs should have exact field names."""
        inputs = DebugInputs(
            factory_text_chars=0,
            factory_text_preview="",
            situation_text_chars=0,
            situation_text_preview="",
        )
        assert hasattr(inputs, "factory_text_chars")
        assert hasattr(inputs, "factory_text_preview")
        assert hasattr(inputs, "situation_text_chars")
        assert hasattr(inputs, "situation_text_preview")


class TestPayloadPreviewStructure:
    """Verify PayloadPreview model structure."""

    def test_minimal_payload_preview_json(self):
        """Should construct PayloadPreview with json type."""
        preview = PayloadPreview(
            type="json",
            content='{"status": "ok"}',
            truncated=False,
        )
        assert preview.type == "json"
        assert preview.content == '{"status": "ok"}'
        assert preview.truncated is False

    def test_minimal_payload_preview_text(self):
        """Should construct PayloadPreview with text type."""
        preview = PayloadPreview(
            type="text",
            content="some text output",
            truncated=True,
        )
        assert preview.type == "text"
        assert preview.truncated is True

    def test_minimal_payload_preview_summary(self):
        """Should construct PayloadPreview with summary type."""
        preview = PayloadPreview(
            type="summary",
            content="brief summary",
            truncated=False,
        )
        assert preview.type == "summary"


class TestPipelineStageRecordStructure:
    """Verify PipelineStageRecord model structure."""

    def test_minimal_stage_record(self):
        """Should construct minimal PipelineStageRecord."""
        record = PipelineStageRecord(
            id="O0",
            name="Extract Explicit IDs",
            kind=StageKind.ONBOARDING,
            status=StageStatus.SUCCESS,
        )
        assert record.id == "O0"
        assert record.name == "Extract Explicit IDs"
        assert record.kind == StageKind.ONBOARDING
        assert record.status == StageStatus.SUCCESS
        assert record.agent_model is None
        assert record.summary == {}
        assert record.errors == []
        assert record.payload_preview is None

    def test_stage_record_with_all_fields(self):
        """Should construct PipelineStageRecord with all fields."""
        preview = PayloadPreview(
            type="json",
            content='{"extracted": ["M1", "M2"]}',
            truncated=False,
        )
        record = PipelineStageRecord(
            id="D1",
            name="Generate Intent Scenario",
            kind=StageKind.DECISION,
            status=StageStatus.SUCCESS,
            agent_model="claude-opus",
            summary={"scenario_type": "RUSH_ARRIVES", "job_id": "J1"},
            errors=[],
            payload_preview=preview,
        )
        assert record.id == "D1"
        assert record.agent_model == "claude-opus"
        assert record.summary["scenario_type"] == "RUSH_ARRIVES"
        assert record.payload_preview is not None
        assert record.payload_preview.type == "json"

    def test_stage_record_with_errors(self):
        """Should construct PipelineStageRecord with error list."""
        record = PipelineStageRecord(
            id="D2",
            name="Some stage",
            kind=StageKind.DECISION,
            status=StageStatus.FAILED,
            errors=["LLM timeout", "Validation failed"],
        )
        assert record.status == StageStatus.FAILED
        assert len(record.errors) == 2
        assert "LLM timeout" in record.errors


class TestPipelineDebugPayloadStructure:
    """Verify PipelineDebugPayload model structure."""

    def test_minimal_debug_payload(self):
        """Should construct minimal PipelineDebugPayload."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1, M2",
            situation_text_chars=50,
            situation_text_preview="Rush",
        )
        payload = PipelineDebugPayload(
            inputs=inputs,
            overall_status="SUCCESS",
        )
        assert payload.inputs.factory_text_chars == 100
        assert payload.overall_status == "SUCCESS"
        assert len(payload.stages) == 0

    def test_debug_payload_with_stages(self):
        """Should construct PipelineDebugPayload with multiple stages."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1, M2",
            situation_text_chars=50,
            situation_text_preview="Rush",
        )
        stages = [
            PipelineStageRecord(
                id="O0",
                name="Stage 1",
                kind=StageKind.ONBOARDING,
                status=StageStatus.SUCCESS,
            ),
            PipelineStageRecord(
                id="D1",
                name="Stage 2",
                kind=StageKind.DECISION,
                status=StageStatus.SUCCESS,
            ),
        ]
        payload = PipelineDebugPayload(
            inputs=inputs,
            overall_status="SUCCESS",
            stages=stages,
        )
        assert len(payload.stages) == 2
        assert payload.stages[0].id == "O0"
        assert payload.stages[1].id == "D1"

    def test_overall_status_partial(self):
        """Should accept PARTIAL overall_status."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1",
            situation_text_chars=50,
            situation_text_preview="Test",
        )
        payload = PipelineDebugPayload(
            inputs=inputs,
            overall_status="PARTIAL",
        )
        assert payload.overall_status == "PARTIAL"

    def test_overall_status_failed(self):
        """Should accept FAILED overall_status."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1",
            situation_text_chars=50,
            situation_text_preview="Test",
        )
        payload = PipelineDebugPayload(
            inputs=inputs,
            overall_status="FAILED",
        )
        assert payload.overall_status == "FAILED"

    def test_debug_payload_serializable(self):
        """PipelineDebugPayload should be JSON-serializable via .model_dump()."""
        inputs = DebugInputs(
            factory_text_chars=100,
            factory_text_preview="M1, M2",
            situation_text_chars=50,
            situation_text_preview="Rush",
        )
        payload = PipelineDebugPayload(
            inputs=inputs,
            overall_status="SUCCESS",
        )
        # Verify it can be converted to dict for JSON serialization
        dumped = payload.model_dump()
        assert isinstance(dumped, dict)
        assert "inputs" in dumped
        assert "overall_status" in dumped
        assert "stages" in dumped
