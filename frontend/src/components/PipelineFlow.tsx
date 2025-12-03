import type { PlanStepInfo, LLMCallInfo } from '../api';
import './PipelineFlow.css';

export interface PipelineFlowProps {
  planSteps: PlanStepInfo[];
  llmCalls: LLMCallInfo[];
  llmCallsUsed: number;
}

function getStepIcon(type: string): string {
  switch (type) {
    case 'ensure_factory':
      return '📦';
    case 'simulate_baseline':
      return '🔄';
    case 'simulate_rush':
      return '🚀';
    case 'simulate_slowdown':
      return '🐢';
    case 'generate_briefing':
      return '📝';
    case 'diagnostic':
      return '🔍';
    default:
      return '⚙';
  }
}

function getStepLabel(type: string): string {
  switch (type) {
    case 'ensure_factory':
      return 'Parse Factory';
    case 'simulate_baseline':
      return 'Simulate';
    case 'simulate_rush':
      return 'Rush Scenario';
    case 'simulate_slowdown':
      return 'Slowdown';
    case 'generate_briefing':
      return 'Briefing';
    case 'diagnostic':
      return 'Diagnostic';
    default:
      return type;
  }
}

function getStatusClass(status: string): string {
  switch (status) {
    case 'done':
      return 'step-done';
    case 'failed':
      return 'step-failed';
    case 'running':
      return 'step-running';
    case 'skipped':
      return 'step-skipped';
    default:
      return 'step-pending';
  }
}

function getStatusIndicator(status: string): string {
  switch (status) {
    case 'done':
      return '✓';
    case 'failed':
      return '✗';
    case 'running':
      return '▶';
    case 'skipped':
      return '−';
    default:
      return '○';
  }
}

function formatLatency(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

export function PipelineFlow({ planSteps, llmCalls, llmCallsUsed }: PipelineFlowProps) {
  // Group LLM calls by step_id
  const llmCallsByStep: Record<number, LLMCallInfo[]> = {};
  llmCalls.forEach(call => {
    const stepId = call.step_id ?? -1;
    if (!llmCallsByStep[stepId]) {
      llmCallsByStep[stepId] = [];
    }
    llmCallsByStep[stepId].push(call);
  });

  const totalLatency = llmCalls.reduce((sum, c) => sum + c.latency_ms, 0);

  return (
    <div className="pipeline-flow">
      {/* Header with summary stats */}
      <div className="pipeline-header">
        <h3>Execution Pipeline</h3>
        <div className="pipeline-stats">
          <span className="stat">
            <span className="stat-value">{llmCallsUsed}</span>
            <span className="stat-label">LLM calls</span>
          </span>
          <span className="stat">
            <span className="stat-value">{formatLatency(totalLatency)}</span>
            <span className="stat-label">LLM time</span>
          </span>
        </div>
      </div>

      {/* Pipeline visualization */}
      <div className="pipeline-steps">
        {planSteps.map((step, idx) => (
          <div key={step.id} className="pipeline-step-wrapper">
            {/* Step node */}
            <div className={`pipeline-step ${getStatusClass(step.status)}`}>
              <div className="step-icon">{getStepIcon(step.type)}</div>
              <div className="step-content">
                <div className="step-label">{getStepLabel(step.type)}</div>
                <div className="step-status">
                  <span className="status-indicator">{getStatusIndicator(step.status)}</span>
                  {step.status}
                </div>
              </div>
              {step.error_message && (
                <div className="step-error" title={step.error_message}>
                  ⚠
                </div>
              )}
            </div>

            {/* LLM calls for this step */}
            {llmCallsByStep[step.id] && llmCallsByStep[step.id].length > 0 && (
              <div className="step-llm-calls">
                {llmCallsByStep[step.id].map(call => (
                  <div key={call.call_id} className="llm-call-badge">
                    <span className="llm-icon">🤖</span>
                    <span className="llm-schema">{call.schema_name}</span>
                    <span className="llm-latency">{formatLatency(call.latency_ms)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Connector arrow */}
            {idx < planSteps.length - 1 && (
              <div className="pipeline-connector">
                <div className="connector-line" />
                <div className="connector-arrow">→</div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* LLM calls without a step (planning phase) */}
      {llmCallsByStep[-1] && llmCallsByStep[-1].length > 0 && (
        <div className="planning-llm-calls">
          <div className="planning-label">Planning Phase:</div>
          {llmCallsByStep[-1].map(call => (
            <div key={call.call_id} className="llm-call-badge planning">
              <span className="llm-icon">🎯</span>
              <span className="llm-schema">{call.purpose || call.schema_name}</span>
              <span className="llm-latency">{formatLatency(call.latency_ms)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Detailed LLM call list */}
      {llmCalls.length > 0 && (
        <div className="llm-calls-detail">
          <h4>LLM Calls ({llmCalls.length})</h4>
          <div className="llm-calls-list">
            {llmCalls.map(call => (
              <div key={call.call_id} className="llm-call-row">
                <span className="call-number">#{call.call_id}</span>
                <span className="call-schema">{call.schema_name}</span>
                <span className="call-purpose">{call.purpose}</span>
                <span className="call-latency">{formatLatency(call.latency_ms)}</span>
                {call.input_tokens && call.output_tokens && (
                  <span className="call-tokens">
                    {call.input_tokens}→{call.output_tokens} tokens
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

