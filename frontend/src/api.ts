/**
 * TypeScript interfaces mirroring backend API contracts.
 * These must remain in sync with backend/models.py and backend/API_CONTRACTS.md.
 * Any changes to these interfaces require coordinated updates to:
 * - backend/API_CONTRACTS.md
 * - backend/models.py
 * - backend/tests/test_api_contracts.py (update EXPECTED_*_KEYS)
 */

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
