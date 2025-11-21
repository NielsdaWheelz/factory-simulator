import type { PipelineDebugPayload } from '../types/pipeline';
import './PipelineSummary.css';

export interface PipelineSummaryProps {
  debug: PipelineDebugPayload | null;
  usedDefaultFactory: boolean;
}

export function PipelineSummary({ debug }: PipelineSummaryProps) {
  if (!debug) {
    return (
      <div className="pipeline-summary">
        <p className="no-debug-message">pipeline details not available for this run.</p>
      </div>
    );
  }

  const onboardingStages = debug.stages.filter(s => s.kind === 'ONBOARDING');
  const decisionStages = debug.stages.filter(s => s.kind === 'DECISION' || s.kind === 'SIMULATION');
  const failedOnboarding = onboardingStages.filter(s => s.status === 'FAILED');
  const failedDecision = decisionStages.filter(s => s.status === 'FAILED');

  const overallStatus = debug.overall_status;
  let statusColor = 'status-success';
  let statusText = '';

  if (overallStatus === 'SUCCESS') {
    statusColor = 'status-success';
    statusText = `all stages succeeded (${onboardingStages.length} onboarding, ${decisionStages.length} decision)`;
  } else if (overallStatus === 'PARTIAL') {
    statusColor = 'status-partial';
    if (failedOnboarding.length > 0) {
      const firstFailed = failedOnboarding[0];
      statusText = `onboarding failed at ${firstFailed.id} → using demo factory; decision pipeline succeeded`;
    } else {
      statusText = 'onboarding fell back to demo factory; decision pipeline succeeded';
    }
  } else if (overallStatus === 'FAILED') {
    statusColor = 'status-failed';
    if (failedDecision.length > 0) {
      const firstFailed = failedDecision[0];
      statusText = `decision pipeline failed at ${firstFailed.id}`;
    } else {
      statusText = 'pipeline execution failed';
    }
  }

  return (
    <div className="pipeline-summary">
      <div className={`status-badge ${statusColor}`}>
        {statusText}
      </div>
    </div>
  );
}
