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

export type AgentStatus = 'RUNNING' | 'DONE' | 'FAILED' | 'MAX_STEPS';

export interface AgentResponse {
  status: AgentStatus;
  steps_taken: number;
  final_answer: string | null;
  
  // Domain results
  factory: FactoryConfig | null;
  scenarios_run: ScenarioSpec[];
  metrics_collected: ScenarioMetrics[];
  
  // Execution trace
  trace: AgentTraceStep[];
  scratchpad: string[];
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
