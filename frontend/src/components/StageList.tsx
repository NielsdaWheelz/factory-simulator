import type { PipelineStageRecord } from '../types/pipeline';
import { StageDetailPanel } from './StageDetailPanel';
import './StageList.css';

export interface StageListProps {
  stages: PipelineStageRecord[];
  selectedStageId: string | null;
  onSelectStage: (id: string | null) => void;
}

interface StageGroup {
  title: string;
  subtitle: string;
  stages: PipelineStageRecord[];
}

function getStatusIcon(status: string): string {
  switch (status) {
    case 'SUCCESS':
      return '✓';
    case 'FAILED':
      return '✗';
    case 'SKIPPED':
      return '○';
    default:
      return '?';
  }
}

function getStatusClass(status: string): string {
  switch (status) {
    case 'SUCCESS':
      return 'status-success';
    case 'FAILED':
      return 'status-failed';
    case 'SKIPPED':
      return 'status-skipped';
    default:
      return '';
  }
}

function getStatusTitle(status: string): string {
  switch (status) {
    case 'SUCCESS':
      return 'success';
    case 'FAILED':
      return 'failed';
    case 'SKIPPED':
      return 'skipped';
    default:
      return 'unknown';
  }
}

function getStageSummaryText(stage: PipelineStageRecord): string {
  const summary = stage.summary as Record<string, unknown>;

  // onboarding stages
  if (summary.stage_type === 'EXPLICIT_ID_EXTRACTION') {
    const machineIds = (summary.explicit_machine_ids as string[]) || [];
    const jobIds = (summary.explicit_job_ids as string[]) || [];
    const total = machineIds.length + jobIds.length;
    return `${total} ids detected (${machineIds.length} machines, ${jobIds.length} jobs)`;
  }

  if (summary.stage_type === 'COARSE_STRUCTURE') {
    const machines = (summary.coarse_machine_count as number) || 0;
    const jobs = (summary.coarse_job_count as number) || 0;
    return `${machines} machines, ${jobs} jobs extracted`;
  }

  if (summary.stage_type === 'FINE_EXTRACTION') {
    const totalSteps = (summary.total_steps_extracted as number) || 0;
    return `${totalSteps} steps extracted`;
  }

  if (summary.stage_type === 'NORMALIZATION') {
    const machines = (summary.normalized_machines as number) || 0;
    const jobs = (summary.normalized_jobs as number) || 0;
    return `normalized: ${machines} machines, ${jobs} jobs`;
  }

  if (summary.stage_type === 'COVERAGE_ASSESSMENT') {
    const machineCoverage = (summary.machine_coverage_ratio as number) || 0;
    const jobCoverage = (summary.job_coverage_ratio as number) || 0;
    const is100 = summary.is_100_percent_coverage as boolean;
    if (is100) {
      return 'coverage 100%';
    }
    const missingMachines = (summary.missing_machines as string[]) || [];
    const missingJobs = (summary.missing_jobs as string[]) || [];
    const missing = [...missingMachines, ...missingJobs];
    const avgCoverage = ((machineCoverage + jobCoverage) / 2 * 100).toFixed(0);
    return missing.length > 0 
      ? `coverage ${avgCoverage}% (missing: ${missing.join(', ')})`
      : `coverage ${avgCoverage}%`;
  }

  // decision stages
  if (summary.stage_type === 'INTENT_CLASSIFICATION') {
    const intent = (summary.intent_scenario_type as string) || 'unknown';
    return `intent: ${intent}`;
  }

  if (summary.stage_type === 'FUTURES_EXPANSION') {
    const count = (summary.generated_scenario_count as number) || 0;
    return `${count} scenarios`;
  }

  if (summary.stage_type === 'SIMULATION') {
    const count = (summary.scenarios_run as number) || 0;
    return `${count} sims run`;
  }

  if (summary.stage_type === 'METRICS_COMPUTATION') {
    const count = (summary.metrics_computed as number) || 0;
    return `${count} metrics computed`;
  }

  if (summary.stage_type === 'BRIEFING_GENERATION') {
    const length = (summary.briefing_length_chars as number) || 0;
    return `briefing ${length} chars`;
  }

  // generic fallback
  if (Object.keys(summary).length > 0) {
    return 'stage completed';
  }

  return 'no summary available';
}

function groupStages(stages: PipelineStageRecord[]): StageGroup[] {
  const onboardingStages = stages.filter(s => s.kind === 'ONBOARDING');
  const decisionStages = stages.filter(s => s.kind === 'DECISION' || s.kind === 'SIMULATION');

  const groups: StageGroup[] = [];

  if (onboardingStages.length > 0) {
    groups.push({
      title: 'onboarding pipeline',
      subtitle: 'structuring the factory',
      stages: onboardingStages,
    });
  }

  if (decisionStages.length > 0) {
    groups.push({
      title: 'decision pipeline',
      subtitle: 'intent → futures → sim → briefing',
      stages: decisionStages,
    });
  }

  return groups;
}

export function StageList({ stages, selectedStageId, onSelectStage }: StageListProps) {
  if (!stages || stages.length === 0) {
    return (
      <div className="stage-list">
        <p className="no-stages-message">no pipeline stages recorded for this run.</p>
      </div>
    );
  }

  const handleRowClick = (stageId: string) => {
    if (selectedStageId === stageId) {
      onSelectStage(null); // Toggle off if already selected
    } else {
      onSelectStage(stageId);
    }
  };

  const groups = groupStages(stages);

  return (
    <div className="stage-list">
      <div className="stages-container">
        {groups.map((group, groupIdx) => (
          <div key={groupIdx} className="stage-group">
            <div className="stage-group-header">
              <div className="stage-group-title">{group.title}</div>
              <div className="stage-group-subtitle">{group.subtitle}</div>
            </div>
            <div className="stage-group-stages">
              {group.stages.map((stage, idx) => {
                const isSelected = selectedStageId === stage.id;
                const rowClassName = `stage-row ${isSelected ? 'stage-row--selected' : ''}`;
                const statusTitle = `${getStatusTitle(stage.status)}${stage.errors.length > 0 ? ': ' + stage.errors.join('; ') : ''}`;

                return (
                  <div key={idx} className="stage-row-wrapper">
                    <div
                      className={rowClassName}
                      onClick={() => handleRowClick(stage.id)}
                      role="button"
                      tabIndex={0}
                      title={statusTitle}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleRowClick(stage.id);
                        }
                      }}
                    >
                      <span className={`stage-status-icon ${getStatusClass(stage.status)}`}>
                        {getStatusIcon(stage.status)}
                      </span>
                      <span className="stage-id">{stage.id}:</span>
                      <span className="stage-name">{stage.name}</span>
                      <span className="stage-summary">{getStageSummaryText(stage)}</span>
                    </div>
                    {isSelected && (
                      <div className="stage-detail-inline-wrapper">
                        <StageDetailPanel
                          stage={stage}
                          onClose={() => onSelectStage(null)}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
