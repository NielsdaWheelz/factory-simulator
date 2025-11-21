import type { PipelineDebugPayload } from '../types/pipeline';
import './PipelineSummary.css';

export interface PipelineSummaryProps {
  debug: PipelineDebugPayload | null;
  usedDefaultFactory: boolean;
}

export function PipelineSummary({ debug, usedDefaultFactory }: PipelineSummaryProps) {
  if (!debug) {
    return (
      <div className="pipeline-summary">
        <p className="no-debug-message">Pipeline details not available for this run.</p>
      </div>
    );
  }

  const totalStages = debug.stages.length;
  const failedStages = debug.stages.filter(s => s.status === 'FAILED').length;
  const overallStatus = debug.overall_status;

  let statusColor = 'status-success';
  let statusText = '';

  if (overallStatus === 'SUCCESS') {
    statusColor = 'status-success';
    statusText = `Pipeline: all ${totalStages} stages succeeded.`;
  } else if (overallStatus === 'PARTIAL') {
    statusColor = 'status-partial';
    statusText = 'Pipeline: onboarding fell back to demo factory; decision pipeline succeeded.';
  } else if (overallStatus === 'FAILED') {
    statusColor = 'status-failed';
    if (failedStages > 0) {
      statusText = `Pipeline: at least one decision stage failed (${failedStages} failed).`;
    } else {
      statusText = 'Pipeline: execution failed.';
    }
  }

  return (
    <div className="pipeline-summary">
      <div className={`status-badge ${statusColor}`}>
        <strong>{statusText}</strong>
      </div>
      {usedDefaultFactory && (
        <p className="fallback-note">Using demo factory (onboarding failed).</p>
      )}
    </div>
  );
}
