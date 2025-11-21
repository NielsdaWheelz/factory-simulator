import type { PipelineStageRecord } from '../types/pipeline';
import './StageDetailPanel.css';

export interface StageDetailPanelProps {
  stage: PipelineStageRecord;
  onClose: () => void;
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

function renderSummaryContent(stage: PipelineStageRecord): JSX.Element {
  const summary = stage.summary as Record<string, unknown>;
  const stageType = summary.stage_type as string | undefined;

  if (!stageType) {
    return <p className="summary-unavailable">Summary unavailable for this stage.</p>;
  }

  switch (stageType) {
    case 'EXPLICIT_ID_EXTRACTION': {
      const machineIds = (summary.explicit_machine_ids as string[]) || [];
      const jobIds = (summary.explicit_job_ids as string[]) || [];
      const total = (summary.total_ids_detected as number) || 0;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Machines:</strong> {machineIds.length > 0 ? machineIds.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Jobs:</strong> {jobIds.length > 0 ? jobIds.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Total IDs detected:</strong> {total}
          </div>
        </div>
      );
    }

    case 'COARSE_STRUCTURE': {
      const machines = (summary.coarse_machine_count as number) || 0;
      const jobs = (summary.coarse_job_count as number) || 0;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Coarse machine count:</strong> {machines}
          </div>
          <div className="summary-field">
            <strong>Coarse job count:</strong> {jobs}
          </div>
        </div>
      );
    }

    case 'FINE_EXTRACTION': {
      const machinesWithSteps = (summary.machines_with_steps as number) || 0;
      const jobsWithSteps = (summary.jobs_with_steps as number) || 0;
      const totalSteps = (summary.total_steps_extracted as number) || 0;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Machines with steps:</strong> {machinesWithSteps}
          </div>
          <div className="summary-field">
            <strong>Jobs with steps:</strong> {jobsWithSteps}
          </div>
          <div className="summary-field">
            <strong>Total steps extracted:</strong> {totalSteps}
          </div>
        </div>
      );
    }

    case 'NORMALIZATION': {
      const machines = (summary.normalized_machines as number) || 0;
      const jobs = (summary.normalized_jobs as number) || 0;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Normalized machines:</strong> {machines}
          </div>
          <div className="summary-field">
            <strong>Normalized jobs:</strong> {jobs}
          </div>
        </div>
      );
    }

    case 'COVERAGE_ASSESSMENT': {
      const detectedMachines = (summary.detected_machines as string[]) || [];
      const detectedJobs = (summary.detected_jobs as string[]) || [];
      const parsedMachines = (summary.parsed_machines as string[]) || [];
      const parsedJobs = (summary.parsed_jobs as string[]) || [];
      const machineCoverage = (summary.machine_coverage_ratio as number) || 0;
      const jobCoverage = (summary.job_coverage_ratio as number) || 0;
      const missingMachines = (summary.missing_machines as string[]) || [];
      const missingJobs = (summary.missing_jobs as string[]) || [];
      const is100 = summary.is_100_percent_coverage as boolean;

      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Detected machines:</strong> {detectedMachines.length > 0 ? detectedMachines.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Detected jobs:</strong> {detectedJobs.length > 0 ? detectedJobs.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Parsed machines:</strong> {parsedMachines.length > 0 ? parsedMachines.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Parsed jobs:</strong> {parsedJobs.length > 0 ? parsedJobs.join(', ') : 'none'}
          </div>
          <div className="summary-field">
            <strong>Machine coverage:</strong> {(machineCoverage * 100).toFixed(0)}%
          </div>
          <div className="summary-field">
            <strong>Job coverage:</strong> {(jobCoverage * 100).toFixed(0)}%
          </div>
          {missingMachines.length > 0 && (
            <div className="summary-field">
              <strong>Missing machines:</strong> {missingMachines.join(', ')}
            </div>
          )}
          {missingJobs.length > 0 && (
            <div className="summary-field">
              <strong>Missing jobs:</strong> {missingJobs.join(', ')}
            </div>
          )}
          <div className="summary-field">
            <strong>100% coverage:</strong> {is100 ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    case 'INTENT_CLASSIFICATION': {
      const intent = (summary.intent_scenario_type as string) || 'unknown';
      const contextAvailable = summary.intent_context_available as boolean;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Intent scenario type:</strong> {intent}
          </div>
          <div className="summary-field">
            <strong>Context available:</strong> {contextAvailable ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    case 'FUTURES_EXPANSION': {
      const count = (summary.generated_scenario_count as number) || 0;
      const contextAvailable = summary.futures_context_available as boolean;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Generated scenario count:</strong> {count}
          </div>
          <div className="summary-field">
            <strong>Context available:</strong> {contextAvailable ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    case 'SIMULATION': {
      const count = (summary.scenarios_run as number) || 0;
      const allSucceeded = summary.all_succeeded as boolean;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Scenarios run:</strong> {count}
          </div>
          <div className="summary-field">
            <strong>All succeeded:</strong> {allSucceeded ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    case 'METRICS_COMPUTATION': {
      const count = (summary.metrics_computed as number) || 0;
      const allSucceeded = summary.all_succeeded as boolean;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Metrics computed:</strong> {count}
          </div>
          <div className="summary-field">
            <strong>All succeeded:</strong> {allSucceeded ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    case 'BRIEFING_GENERATION': {
      const length = (summary.briefing_length_chars as number) || 0;
      const hasContent = summary.briefing_has_content as boolean;
      return (
        <div className="summary-fields">
          <div className="summary-field">
            <strong>Briefing length:</strong> {length} characters
          </div>
          <div className="summary-field">
            <strong>Has content:</strong> {hasContent ? 'yes' : 'no'}
          </div>
        </div>
      );
    }

    default:
      return (
        <p className="summary-unavailable">
          Summary unavailable for stage type: {stageType}
        </p>
      );
  }
}

export function StageDetailPanel({ stage, onClose }: StageDetailPanelProps) {
  const agentDisplay = stage.agent_model || 'deterministic';

  return (
    <div className="stage-detail-panel">
      <div className="stage-detail-header">
        <div className="header-left">
          <span className={`stage-status-icon ${getStatusClass(stage.status)}`}>
            {getStatusIcon(stage.status)}
          </span>
          <div className="header-text">
            <h3 className="stage-title">
              [{stage.id}] {stage.name}
            </h3>
            <div className="stage-metadata">
              <span className="metadata-item">
                <strong>Status:</strong> {stage.status}
              </span>
              <span className="metadata-item">
                <strong>Kind:</strong> {stage.kind}
              </span>
              <span className="metadata-item">
                <strong>Agent:</strong> {agentDisplay}
              </span>
            </div>
          </div>
        </div>
        <button className="close-button" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>

      <div className="stage-detail-content">
        {/* Summary Section */}
        <div className="stage-detail-section">
          <h4>Summary</h4>
          {renderSummaryContent(stage)}
        </div>

        {/* Errors Section */}
        {stage.errors && stage.errors.length > 0 && (
          <div className="stage-detail-section stage-detail-errors">
            <h4>Errors ({stage.errors.length})</h4>
            <ul className="errors-list">
              {stage.errors.map((error, idx) => (
                <li key={idx}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Payload Preview Section */}
        {stage.payload_preview && (
          <div className="stage-detail-section stage-detail-payload">
            <h4>Payload Preview</h4>
            <div className="payload-meta">
              <span>Type: <strong>{stage.payload_preview.type}</strong></span>
              {stage.payload_preview.truncated && (
                <span className="truncated-badge">truncated</span>
              )}
            </div>
            <pre className="payload-content">{stage.payload_preview.content}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
