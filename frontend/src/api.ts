export interface Machine {
  id: string;
  name: string;
}

export interface JobStep {
  machine_id: string;
  duration_hours: number;
}

export interface Job {
  id: string;
  name: string;
  due_time_hour: number;
  steps: JobStep[];
}

export interface Factory {
  machines: Machine[];
  jobs: Job[];
}

export interface ScenarioSpec {
  scenario_type: string;
  rush_job_id: string | null;
  slowdown_factor: number | null;
}

export interface ScenarioMetrics {
  makespan_hour: number;
  job_lateness: { [jobId: string]: number };
  bottleneck_machine_id: string;
  bottleneck_utilization: number;
}

export interface SimulateResponse {
  factory: Factory;
  specs: ScenarioSpec[];
  metrics: ScenarioMetrics[];
  briefing: string;
  situation_text: string;
  meta: {
    used_default_factory: boolean;
    onboarding_errors: string[];
  };
}

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

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
