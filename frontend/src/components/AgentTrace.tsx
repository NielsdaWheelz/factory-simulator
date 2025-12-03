import { useState } from 'react';
import type { AgentTraceStep, AgentResponse } from '../api';
import './AgentTrace.css';

export interface AgentTraceProps {
  response: AgentResponse;
}

function getStatusBadge(status: string): { text: string; className: string } {
  switch (status) {
    case 'DONE':
      return { text: '✓ Complete', className: 'status-done' };
    case 'FAILED':
      return { text: '✗ Failed', className: 'status-failed' };
    case 'MAX_STEPS':
      return { text: '⚠ Step Limit', className: 'status-max-steps' };
    case 'RUNNING':
      return { text: '⟳ Running', className: 'status-running' };
    default:
      return { text: status, className: '' };
  }
}

function getActionIcon(actionType: string, success?: boolean | null): string {
  if (actionType === 'final_answer') {
    return '💬';
  }
  if (success === true) {
    return '✓';
  }
  if (success === false) {
    return '✗';
  }
  return '⚙';
}

function TraceStep({ step, isExpanded, onToggle }: { 
  step: AgentTraceStep; 
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const actionIcon = getActionIcon(step.action_type, step.tool_success);
  const isToolCall = step.action_type === 'tool_call';
  const isFailed = step.tool_success === false;
  
  return (
    <div className={`trace-step ${isFailed ? 'trace-step--failed' : ''}`}>
      <div 
        className="trace-step-header"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <span className="step-number">Step {step.step_number}</span>
        <span className={`step-action-icon ${isFailed ? 'icon-failed' : 'icon-success'}`}>
          {actionIcon}
        </span>
        <span className="step-action-type">
          {isToolCall ? step.tool_name : 'final_answer'}
        </span>
        <span className="step-thought-preview">
          {step.thought.length > 80 ? step.thought.substring(0, 80) + '...' : step.thought}
        </span>
        <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
      </div>
      
      {isExpanded && (
        <div className="trace-step-details">
          <div className="detail-section">
            <div className="detail-label">Thought</div>
            <div className="detail-content thought-content">{step.thought}</div>
          </div>
          
          {isToolCall && (
            <>
              <div className="detail-section">
                <div className="detail-label">Tool Called</div>
                <div className="detail-content tool-name">{step.tool_name}</div>
              </div>
              
              {step.tool_args && (
                <div className="detail-section">
                  <div className="detail-label">Arguments</div>
                  <pre className="detail-content code-block">
                    {JSON.stringify(step.tool_args, null, 2)}
                  </pre>
                </div>
              )}
              
              {step.tool_success && step.tool_output && (
                <div className="detail-section">
                  <div className="detail-label">Output</div>
                  <pre className="detail-content code-block output-block">
                    {step.tool_output}
                  </pre>
                </div>
              )}
              
              {step.tool_error && (
                <div className="detail-section">
                  <div className="detail-label">Error</div>
                  <div className="detail-content error-content">{step.tool_error}</div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function AgentTrace({ response }: AgentTraceProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());
  
  const toggleStep = (stepNumber: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(stepNumber)) {
        next.delete(stepNumber);
      } else {
        next.add(stepNumber);
      }
      return next;
    });
  };
  
  const expandAll = () => {
    setExpandedSteps(new Set(response.trace.map(s => s.step_number)));
  };
  
  const collapseAll = () => {
    setExpandedSteps(new Set());
  };
  
  const statusBadge = getStatusBadge(response.status);
  
  return (
    <div className="agent-trace">
      <div className="trace-header">
        <h3>Agent Execution Trace</h3>
        <div className="trace-header-controls">
          <span className={`status-badge ${statusBadge.className}`}>
            {statusBadge.text}
          </span>
          <span className="steps-count">
            {response.steps_taken} step{response.steps_taken !== 1 ? 's' : ''}
          </span>
          <button className="expand-btn" onClick={expandAll}>Expand All</button>
          <button className="expand-btn" onClick={collapseAll}>Collapse All</button>
        </div>
      </div>
      
      {response.trace.length === 0 ? (
        <div className="no-trace">No execution trace available.</div>
      ) : (
        <div className="trace-steps">
          {response.trace.map((step) => (
            <TraceStep
              key={step.step_number}
              step={step}
              isExpanded={expandedSteps.has(step.step_number)}
              onToggle={() => toggleStep(step.step_number)}
            />
          ))}
        </div>
      )}
      
      {response.scratchpad.length > 0 && (
        <div className="scratchpad-section">
          <h4>Agent Scratchpad</h4>
          <ul className="scratchpad-list">
            {response.scratchpad.map((thought, idx) => (
              <li key={idx} className="scratchpad-item">{thought}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

