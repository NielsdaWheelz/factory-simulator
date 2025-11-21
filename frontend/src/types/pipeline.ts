/**
 * Type definitions for pipeline debug payloads.
 *
 * These interfaces mirror the backend types defined in backend/debug_types.py.
 * They form the contract for the optional debug payload that may be attached to
 * simulation responses.
 *
 * PRF0: Types-only. No code populates or uses these yet.
 * Future PRs will wire these into debug visualization UI.
 */

/**
 * Status of a single pipeline stage execution.
 * - SUCCESS: Stage completed without errors
 * - FAILED: Stage encountered an error and did not complete
 * - SKIPPED: Stage was skipped (e.g., due to prior failure or conditional logic)
 */
export type StageStatus = "SUCCESS" | "FAILED" | "SKIPPED";

/**
 * Kind/category of a pipeline stage.
 * - ONBOARDING: Factory description parsing and normalization
 * - DECISION: LLM-based decision making (scenario generation, briefing, etc.)
 * - SIMULATION: Factory simulation / metric computation
 */
export type StageKind = "ONBOARDING" | "DECISION" | "SIMULATION";

/**
 * Overall status of the entire pipeline execution.
 * - SUCCESS: All stages completed successfully, coverage > threshold
 * - PARTIAL: Onboarding fell back to toy factory, but decision pipeline ran
 * - FAILED: Decision pipeline failed or unrecoverable error occurred
 */
export type OverallStatus = "SUCCESS" | "PARTIAL" | "FAILED";

/**
 * Summary of inputs to the pipeline.
 *
 * Captures length and preview of factory description and situation text.
 * Previews help with debugging without storing massive amounts of text.
 */
export interface DebugInputs {
  factory_text_chars: number;
  factory_text_preview: string;
  situation_text_chars: number;
  situation_text_preview: string;
}

/**
 * Preview of a structured payload (e.g., LLM response, parsed JSON).
 *
 * Allows attaching a preview of data that was processed during a stage,
 * without storing the full payload.
 */
export interface PayloadPreview {
  type: "json" | "text" | "summary";
  content: string;
  truncated: boolean;
}

/**
 * Generic summary of a pipeline stage.
 * Structure will be refined in future PRs.
 */
export type StageSummary = Record<string, unknown>;

/**
 * Record of a single stage in the pipeline execution.
 *
 * Captures metadata, status, model used, summary, errors, and optional
 * output preview.
 */
export interface PipelineStageRecord {
  id: string;
  name: string;
  kind: StageKind;
  status: StageStatus;
  agent_model: string | null;
  summary: StageSummary;
  errors: string[];
  payload_preview?: PayloadPreview | null;
}

/**
 * Shape of the optional debug payload attached to /api/simulate responses.
 *
 * PRF0: Types-only contract. No code populates this yet.
 * Future PRs will construct this from onboarding + decision pipeline stages
 * and wire it into debug visualization UI.
 */
export interface PipelineDebugPayload {
  inputs: DebugInputs;
  overall_status: OverallStatus;
  stages: PipelineStageRecord[];
}
