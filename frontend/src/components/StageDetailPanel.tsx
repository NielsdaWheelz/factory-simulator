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
    return <p className="summary-unavailable">summary unavailable for this stage type</p>;
  }

  switch (stageType) {
    case 'EXPLICIT_ID_EXTRACTION': {
      const machineIds = (summary.explicit_machine_ids as string[]) || [];
      const jobIds = (summary.explicit_job_ids as string[]) || [];
      const total = (summary.total_ids_detected as number) || 0;
      return (
        <>
          <div className="section-intro">detected explicit ids in the factory description text</div>
          <div className="summary-subsection">
            <h5>detected</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {machineIds.length > 0 ? machineIds.join(', ') : 'none'}</li>
              <li><strong>jobs:</strong> {jobIds.length > 0 ? jobIds.join(', ') : 'none'}</li>
              <li><strong>total:</strong> {total}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'COARSE_STRUCTURE': {
      const machines = (summary.coarse_machine_count as number) || 0;
      const jobs = (summary.coarse_job_count as number) || 0;
      return (
        <>
          <div className="section-intro">extracted high-level entity counts</div>
          <div className="summary-subsection">
            <h5>extracted</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {machines}</li>
              <li><strong>jobs:</strong> {jobs}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'FINE_EXTRACTION': {
      const machinesWithSteps = (summary.machines_with_steps as number) || 0;
      const jobsWithSteps = (summary.jobs_with_steps as number) || 0;
      const totalSteps = (summary.total_steps_extracted as number) || 0;
      return (
        <>
          <div className="section-intro">parsed detailed job steps and routing</div>
          <div className="summary-subsection">
            <h5>extracted</h5>
            <ul className="summary-list">
              <li><strong>machines with steps:</strong> {machinesWithSteps}</li>
              <li><strong>jobs with steps:</strong> {jobsWithSteps}</li>
              <li><strong>total steps:</strong> {totalSteps}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'NORMALIZATION': {
      const machines = (summary.normalized_machines as number) || 0;
      const jobs = (summary.normalized_jobs as number) || 0;
      return (
        <>
          <div className="section-intro">normalized and validated factory structure</div>
          <div className="summary-subsection">
            <h5>output</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {machines}</li>
              <li><strong>jobs:</strong> {jobs}</li>
            </ul>
          </div>
        </>
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
        <>
          <div className="section-intro">verified that parsed entities cover detected ids</div>
          
          <div className="summary-subsection">
            <h5>detected ids</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {detectedMachines.length > 0 ? detectedMachines.join(', ') : 'none'}</li>
              <li><strong>jobs:</strong> {detectedJobs.length > 0 ? detectedJobs.join(', ') : 'none'}</li>
            </ul>
          </div>

          <div className="summary-subsection">
            <h5>parsed entities</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {parsedMachines.length > 0 ? parsedMachines.join(', ') : 'none'}</li>
              <li><strong>jobs:</strong> {parsedJobs.length > 0 ? parsedJobs.join(', ') : 'none'}</li>
            </ul>
          </div>

          <div className="summary-subsection">
            <h5>coverage</h5>
            <ul className="summary-list">
              <li><strong>machines:</strong> {(machineCoverage * 100).toFixed(0)}%</li>
              <li><strong>jobs:</strong> {(jobCoverage * 100).toFixed(0)}%</li>
              <li><strong>100% coverage:</strong> {is100 ? 'yes' : 'no'}</li>
            </ul>
          </div>

          {(missingMachines.length > 0 || missingJobs.length > 0) && (
            <div className="summary-subsection summary-subsection--warning">
              <h5>missing</h5>
              <ul className="summary-list">
                {missingMachines.length > 0 && (
                  <li><strong>machines:</strong> {missingMachines.join(', ')}</li>
                )}
                {missingJobs.length > 0 && (
                  <li><strong>jobs:</strong> {missingJobs.join(', ')}</li>
                )}
              </ul>
            </div>
          )}

          {stage.status === 'FAILED' && (
            <div className="action-taken">
              <strong>action taken:</strong> system fell back to demo factory; decision pipeline ran using fallback config.
            </div>
          )}
        </>
      );
    }

    case 'INTENT_CLASSIFICATION': {
      const intent = (summary.intent_scenario_type as string) || 'unknown';
      const contextAvailable = summary.intent_context_available as boolean;
      return (
        <>
          <div className="section-intro">classified user intent from situation text</div>
          <div className="summary-subsection">
            <h5>result</h5>
            <ul className="summary-list">
              <li><strong>intent:</strong> {intent}</li>
              <li><strong>context available:</strong> {contextAvailable ? 'yes' : 'no'}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'FUTURES_EXPANSION': {
      const count = (summary.generated_scenario_count as number) || 0;
      const contextAvailable = summary.futures_context_available as boolean;
      return (
        <>
          <div className="section-intro">expanded intent into concrete scenarios</div>
          <div className="summary-subsection">
            <h5>output</h5>
            <ul className="summary-list">
              <li><strong>scenarios generated:</strong> {count}</li>
              <li><strong>context available:</strong> {contextAvailable ? 'yes' : 'no'}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'SIMULATION': {
      const count = (summary.scenarios_run as number) || 0;
      const allSucceeded = summary.all_succeeded as boolean;
      return (
        <>
          <div className="section-intro">ran discrete-event simulations for each scenario</div>
          <div className="summary-subsection">
            <h5>execution</h5>
            <ul className="summary-list">
              <li><strong>scenarios run:</strong> {count}</li>
              <li><strong>all succeeded:</strong> {allSucceeded ? 'yes' : 'no'}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'METRICS_COMPUTATION': {
      const count = (summary.metrics_computed as number) || 0;
      const allSucceeded = summary.all_succeeded as boolean;
      return (
        <>
          <div className="section-intro">computed metrics from simulation results</div>
          <div className="summary-subsection">
            <h5>output</h5>
            <ul className="summary-list">
              <li><strong>metrics computed:</strong> {count}</li>
              <li><strong>all succeeded:</strong> {allSucceeded ? 'yes' : 'no'}</li>
            </ul>
          </div>
        </>
      );
    }

    case 'BRIEFING_GENERATION': {
      const length = (summary.briefing_length_chars as number) || 0;
      const hasContent = summary.briefing_has_content as boolean;
      return (
        <>
          <div className="section-intro">generated decision briefing from metrics</div>
          <div className="summary-subsection">
            <h5>output</h5>
            <ul className="summary-list">
              <li><strong>length:</strong> {length} characters</li>
              <li><strong>has content:</strong> {hasContent ? 'yes' : 'no'}</li>
            </ul>
          </div>
        </>
      );
    }

    default:
      return (
        <p className="summary-unavailable">
          summary unavailable for stage type: {stageType}
        </p>
      );
  }
}

export function StageDetailPanel({ stage, onClose }: StageDetailPanelProps) {
  const agentDisplay = stage.agent_model || 'deterministic';
  const kindLabel = stage.kind.toLowerCase();

  return (
    <div className="stage-detail-panel">
      <div className="stage-detail-header">
        <div className="header-left">
          <span className={`stage-status-icon ${getStatusClass(stage.status)}`}>
            {getStatusIcon(stage.status)}
          </span>
          <div className="header-text">
            <h3 className="stage-title">
              [{getStatusIcon(stage.status)}] {stage.id}: {stage.name}
            </h3>
            <div className="stage-metadata">
              <span className="metadata-badge">{kindLabel}</span>
              <span className="metadata-separator">•</span>
              <span className="metadata-agent">{agentDisplay}</span>
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
          <h4>summary</h4>
          {renderSummaryContent(stage)}
        </div>

        {/* Errors Section */}
        {stage.errors && stage.errors.length > 0 && (
          <div className="stage-detail-section stage-detail-errors">
            <h4>errors ({stage.errors.length})</h4>
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
            <h4>payload preview</h4>
            <div className="payload-meta">
              <span>type: <strong>{stage.payload_preview.type}</strong></span>
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
