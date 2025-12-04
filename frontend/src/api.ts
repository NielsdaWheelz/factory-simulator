/**
 * TypeScript interfaces mirroring backend API contracts.
 * These must remain in sync with backend/models.py and backend/API_CONTRACTS.md.
 * Any changes to these interfaces require coordinated updates to:
 * - backend/API_CONTRACTS.md
 * - backend/models.py
 * - backend/tests/test_api_contracts.py (update EXPECTED_*_KEYS)
 */

import type { PipelineDebugPayload } from './types/pipeline';

export interface Machine {
  id: string;
  name: string;
}

export interface Step {
  machine_id: string;
  duration_hours: number;
}

export interface Job {
  id: string;
  name: string;
  steps: Step[];
  due_time_hour: number;
}

export interface FactoryConfig {
  machines: Machine[];
  jobs: Job[];
}

export type ScenarioType = "BASELINE" | "RUSH_ARRIVES" | "M2_SLOWDOWN";

export interface ScenarioSpec {
  scenario_type: ScenarioType;
  rush_job_id: string | null;
  slowdown_factor: number | null;
}

export interface ScenarioMetrics {
  makespan_hour: number;
  job_lateness: Record<string, number>;
  bottleneck_machine_id: string;
  bottleneck_utilization: number;
}

export interface OnboardingMeta {
  used_default_factory: boolean;
  onboarding_errors: string[];
  inferred_assumptions: string[];
}

export interface OnboardingResponse {
  factory: FactoryConfig;
  meta: OnboardingMeta;
}

export interface SimulateResponse {
  factory: FactoryConfig;
  specs: ScenarioSpec[];
  metrics: ScenarioMetrics[];
  briefing: string;
  meta: OnboardingMeta;
  debug?: PipelineDebugPayload | null; // PRF2: Optional debug payload with pipeline stage records
}

// =============================================================================
// AGENT TYPES (SOTA Agent System)
// =============================================================================

export interface AgentTraceStep {
  step_number: number;
  thought: string;
  action_type: 'tool_call' | 'final_answer';
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_success?: boolean | null;
  tool_output?: string | null;
  tool_error?: string | null;
}

export interface LLMCallInfo {
  call_id: number;
  schema_name: string;
  purpose: string;
  latency_ms: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  step_id?: number | null;
}

export interface PlanStepInfo {
  id: number;
  type: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  params: Record<string, unknown>;
  error_message?: string | null;
}

export interface DataPreviewInfo {
  label: string;
  type_name: string;
  preview: string;
  size?: string | null;
}

export interface OperationInfo {
  id: string;
  type: 'function' | 'llm' | 'validation';
  name: string;
  duration_ms: number;
  inputs: DataPreviewInfo[];
  outputs: DataPreviewInfo[];
  schema_name?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  error?: string | null;
}

export interface DataFlowStepInfo {
  step_id: number;
  step_type: string;
  step_name: string;
  status: string;
  total_duration_ms: number;
  operations: OperationInfo[];
  step_input?: DataPreviewInfo | null;
  step_output?: DataPreviewInfo | null;
}

export type AgentStatus = 'RUNNING' | 'DONE' | 'FAILED' | 'MAX_STEPS' | 'BUDGET_EXCEEDED';

export interface OnboardingIssueInfo {
  type: string;
  severity: string;
  message: string;
  related_ids?: string[] | null;
}

export type OnboardingTrust = 'HIGH_TRUST' | 'MEDIUM_TRUST' | 'LOW_TRUST';

// Alternative factory interpretation (PR9)
export interface AltFactoryInfo {
  machines: string[];  // Just machine IDs
  jobs: string[];  // Just job IDs
  mode: string;  // Extraction mode that produced this config
}

// Diff summary between primary and alternative config (PR9)
export interface DiffSummaryInfo {
  alt_index: number;  // Index of the alternative (0-based)
  mode: string;  // Extraction mode that produced the alternative
  summary: string;  // Human-readable summary of differences
}

// Detailed structural diff between primary and alternative config (PR10)
export interface DiffDetailInfo {
  machines_added: string[];
  machines_removed: string[];
  jobs_added: string[];
  jobs_removed: string[];
  routing_differences: Record<string, { a: string[]; b: string[] }>;
  timing_differences: Record<string, Record<string, any>>;
  is_identical: boolean;
}

export interface AgentResponse {
  status: AgentStatus;
  steps_taken: number;
  llm_calls_used: number;
  final_answer: string | null;

  // Domain results
  factory: FactoryConfig | null;
  scenarios_run: ScenarioSpec[];
  metrics_collected: ScenarioMetrics[];

  // Plan information
  plan_summary: string | null;
  plan_steps: PlanStepInfo[];

  // LLM call tracking
  llm_calls: LLMCallInfo[];

  // Data flow visualization
  data_flow: DataFlowStepInfo[];

  // Execution trace
  trace: AgentTraceStep[];
  scratchpad: string[];

  // Onboarding diagnostics
  onboarding_issues: OnboardingIssueInfo[];
  onboarding_score: number | null;
  onboarding_trust: OnboardingTrust | null;

  // Alternative factory interpretations (PR9)
  alt_factories: AltFactoryInfo[];
  diff_summaries: DiffSummaryInfo[];

  // Structured diffs and clarifying questions (PR10)
  alt_factory_diffs: DiffDetailInfo[];
  clarifying_questions: string[];
}

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

export async function onboardFactory(
  factoryDescription: string
): Promise<OnboardingResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/onboard`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      factory_description: factoryDescription,
    }),
  });

  if (!resp.ok) {
    throw new Error(`onboard failed with status ${resp.status}`);
  }

  const data = await resp.json();
  return data as OnboardingResponse;
}

export async function simulate(
  factoryDescription: string,
  situationText: string
): Promise<SimulateResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      factory_description: factoryDescription,
      situation_text: situationText,
    }),
  });

  if (!resp.ok) {
    throw new Error(`simulate failed with status ${resp.status}`);
  }

  const data = await resp.json();
  return data as SimulateResponse;
}

/**
 * Call the SOTA agent endpoint.
 * 
 * The agent runs a control loop, dynamically choosing which tools to call
 * and when to stop. Returns the final answer plus the full execution trace.
 * 
 * Note: Agent requests can take 1-3 minutes due to multiple LLM calls.
 * We use a 5 minute timeout to handle slow OpenAI responses.
 */
export async function runAgent(
  userRequest: string,
  maxSteps: number = 15
): Promise<AgentResponse> {
  // Create an AbortController for timeout handling
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5 * 60 * 1000); // 5 minute timeout

  try {
    const resp = await fetch(`${API_BASE_URL}/api/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_request: userRequest,
        max_steps: maxSteps,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!resp.ok) {
      throw new Error(`Agent request failed with status ${resp.status}`);
    }

    const data = await resp.json();
    return data as AgentResponse;
  } catch (error) {
    clearTimeout(timeoutId);
    
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        throw new Error('Agent request timed out after 5 minutes. The server may still be processing - check the backend logs.');
      }
      // Re-throw with more context
      throw new Error(`Agent request failed: ${error.message}`);
    }
    throw error;
  }
}
