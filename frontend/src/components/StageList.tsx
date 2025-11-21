import type { PipelineStageRecord } from '../types/pipeline';
import './StageList.css';

export interface StageListProps {
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

function getStageSummaryText(stage: PipelineStageRecord): string {
  const summary = stage.summary as Record<string, unknown>;

  // Handle different stage types based on stage_type in summary
  if (summary.stage_type === 'COVERAGE_ASSESSMENT') {
    const machinesCoverage = (summary.machines_coverage as number) || 0;
    const jobsCoverage = (summary.jobs_coverage as number) || 0;
    return `coverage: machines ${(machinesCoverage * 100).toFixed(0)}%, jobs ${(jobsCoverage * 100).toFixed(0)}%`;
  }

  if (summary.stage_type === 'EXPLICIT_ID_EXTRACTION') {
    const machineIds = (summary.explicit_machine_ids as string[]) || [];
    const jobIds = (summary.explicit_job_ids as string[]) || [];
    return `detected ${machineIds.length} machines, ${jobIds.length} jobs`;
  }

  if (summary.stage_type === 'INTENT_CLASSIFICATION') {
    const intent = (summary.intent_scenario_type as string) || 'unknown';
    return `intent: ${intent}`;
  }

  if (summary.stage_type === 'COARSE_STRUCTURE') {
    const machines = (summary.machines as number) || 0;
    const jobs = (summary.jobs as number) || 0;
    return `extracted: ${machines} machines, ${jobs} jobs`;
  }

  if (summary.stage_type === 'JOB_STEPS_EXTRACTION') {
    const steps = (summary.total_steps as number) || 0;
    return `extracted ${steps} steps`;
  }

  // Generic fallback
  if (Object.keys(summary).length > 0) {
    return 'stage completed';
  }

  return 'no summary available';
}

export function StageList({ stages }: StageListProps) {
  if (!stages || stages.length === 0) {
    return (
      <div className="stage-list">
        <p className="no-stages-message">No stages recorded for this run.</p>
      </div>
    );
  }

  return (
    <div className="stage-list">
      <div className="stages-container">
        {stages.map((stage, idx) => (
          <div key={idx} className="stage-row">
            <span className={`stage-status-icon ${getStatusClass(stage.status)}`}>
              {getStatusIcon(stage.status)}
            </span>
            <span className="stage-id">{stage.id}</span>
            <span className="stage-name">{stage.name}</span>
            <span className="stage-summary">{getStageSummaryText(stage)}</span>
            {stage.errors && stage.errors.length > 0 && (
              <span className="stage-errors" title={stage.errors.join(', ')}>
                ({stage.errors.length} error{stage.errors.length !== 1 ? 's' : ''})
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
