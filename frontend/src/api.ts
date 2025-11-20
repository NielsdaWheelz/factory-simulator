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

export interface Scenario {
  label: string;
  scenario_type: string;
}

export interface ScenarioMetrics {
  scenario_name: string;
  scenario_type: string;
  makespan_hour: number;
  total_lateness_hours: number;
  bottleneck_machine_id: string;
  bottleneck_utilization: number;
}

export interface SimulateResponse {
  factory: Factory;
  scenarios: Scenario[];
  metrics: ScenarioMetrics[];
  briefing: string;
  meta: {
    used_default_factory: boolean;
    onboarding_errors: string[];
  };
}

const MOCK_RESPONSE: SimulateResponse = {
  factory: {
    machines: [
      { id: 'M1', name: 'Assembly Machine' },
      { id: 'M2', name: 'Drill Press' },
      { id: 'M3', name: 'Packaging Station' },
    ],
    jobs: [
      {
        id: 'J1',
        name: 'Job 1',
        due_time_hour: 24,
        steps: [
          { machine_id: 'M1', duration_hours: 2 },
          { machine_id: 'M2', duration_hours: 3 },
          { machine_id: 'M3', duration_hours: 1 },
        ],
      },
      {
        id: 'J2',
        name: 'Job 2',
        due_time_hour: 20,
        steps: [
          { machine_id: 'M1', duration_hours: 1.5 },
          { machine_id: 'M2', duration_hours: 2 },
          { machine_id: 'M3', duration_hours: 1.5 },
        ],
      },
      {
        id: 'J3',
        name: 'Job 3',
        due_time_hour: 32,
        steps: [
          { machine_id: 'M1', duration_hours: 3 },
          { machine_id: 'M2', duration_hours: 1 },
          { machine_id: 'M3', duration_hours: 2 },
        ],
      },
    ],
  },
  scenarios: [
    { label: 'Baseline', scenario_type: 'baseline' },
    { label: 'Rush J2', scenario_type: 'rush_j2' },
    { label: 'M2 Slowdown', scenario_type: 'm2_slowdown' },
  ],
  metrics: [
    {
      scenario_name: 'Baseline',
      scenario_type: 'baseline',
      makespan_hour: 7.5,
      total_lateness_hours: 0,
      bottleneck_machine_id: 'M2',
      bottleneck_utilization: 0.72,
    },
    {
      scenario_name: 'Rush J2',
      scenario_type: 'rush_j2',
      makespan_hour: 8.2,
      total_lateness_hours: 2.1,
      bottleneck_machine_id: 'M1',
      bottleneck_utilization: 0.85,
    },
    {
      scenario_name: 'M2 Slowdown',
      scenario_type: 'm2_slowdown',
      makespan_hour: 9.8,
      total_lateness_hours: 5.3,
      bottleneck_machine_id: 'M2',
      bottleneck_utilization: 1.0,
    },
  ],
  briefing: `## Analysis Summary

Based on the factory description and current situation, here are the key insights:

**Baseline Performance:**
- All jobs complete on time with a makespan of 7.5 hours
- M2 (Drill Press) is the primary bottleneck at 72% utilization
- Recommended action: Standard execution following job sequence

**Rush J2 Scenario:**
- Prioritizing J2 creates a bottleneck at M1 (Assembly)
- Total lateness increases to 2.1 hours across other jobs
- M1 reaches 85% utilization
- Trade-off: J2 finishes faster but delays other jobs

**M2 Slowdown Scenario:**
- If M2 operates at reduced capacity, makespan extends to 9.8 hours
- Total lateness reaches 5.3 hours
- M2 becomes fully utilized (100%)
- Recommendation: Prioritize maintenance or acquire backup equipment

Consider the business impact of each scenario before deciding on production strategy.`,
  meta: {
    used_default_factory: false,
    onboarding_errors: [],
  },
};

export async function simulate(
  factoryDescription: string,
  situation: string
): Promise<SimulateResponse> {
  console.log('Simulating with inputs:', {
    factoryDescription,
    situation,
  });

  // Return mock response as a resolved promise
  return Promise.resolve(MOCK_RESPONSE);
}
