import { useState } from 'react';
import type { AgentResponse } from '../api';
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
    case 'BUDGET_EXCEEDED':
      return { text: '⚠ Budget Exceeded', className: 'status-max-steps' };
    case 'RUNNING':
      return { text: '⟳ Running', className: 'status-running' };
    default:
      return { text: status, className: '' };
  }
}

export function AgentTrace({ response }: AgentTraceProps) {
  const [showScratchpad, setShowScratchpad] = useState(true);
  
  const statusBadge = getStatusBadge(response.status);
  
  return (
    <div className="agent-trace">
      <div className="trace-header">
        <h3>Agent Thinking Log</h3>
        <div className="trace-header-controls">
          <span className={`status-badge ${statusBadge.className}`}>
            {statusBadge.text}
          </span>
          <span className="steps-count">
            {response.steps_taken} step{response.steps_taken !== 1 ? 's' : ''}
          </span>
          {response.scratchpad.length > 0 && (
            <button 
              className="expand-btn" 
              onClick={() => setShowScratchpad(!showScratchpad)}
            >
              {showScratchpad ? 'Hide' : 'Show'} Scratchpad
            </button>
          )}
        </div>
      </div>
      
      {showScratchpad && response.scratchpad.length > 0 && (
        <div className="scratchpad-section">
          <div className="scratchpad-list">
            {response.scratchpad.map((thought, idx) => {
              // Parse step number from "[Step X]" prefix
              const match = thought.match(/^\[Step (\d+)\] (.+)$/);
              const stepNum = match ? match[1] : null;
              const content = match ? match[2] : thought;
              
              // Determine thought type for styling
              const isError = content.toLowerCase().includes('error');
              const isPlan = content.toLowerCase().startsWith('plan:');
              const isExecuting = content.toLowerCase().startsWith('executing:');
              
              return (
                <div 
                  key={idx} 
                  className={`scratchpad-item ${isError ? 'error' : ''} ${isPlan ? 'plan' : ''} ${isExecuting ? 'executing' : ''}`}
                >
                  {stepNum && <span className="step-badge">Step {stepNum}</span>}
                  <span className="thought-content">{content}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      
      {response.scratchpad.length === 0 && (
        <div className="no-trace">No thinking log available.</div>
      )}
    </div>
  );
}

