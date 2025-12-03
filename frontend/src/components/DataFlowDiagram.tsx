import { useState } from 'react';
import type { DataFlowStepInfo, OperationInfo, DataPreviewInfo } from '../api';
import './DataFlowDiagram.css';

export interface DataFlowDiagramProps {
  dataFlow: DataFlowStepInfo[];
  userRequest: string;
  finalAnswer: string | null;
}

function formatDuration(ms: number): string {
  if (ms < 1) return '<1ms';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getOperationIcon(type: string): string {
  switch (type) {
    case 'llm': return '🤖';
    case 'function': return '🔧';
    case 'validation': return '✓';
    default: return '⚙';
  }
}

function getStatusClass(status: string): string {
  switch (status) {
    case 'done': return 'status-done';
    case 'failed': return 'status-failed';
    case 'running': return 'status-running';
    default: return 'status-pending';
  }
}

function DataPreview({ data, compact = false }: { data: DataPreviewInfo; compact?: boolean }) {
  return (
    <div className={`data-preview ${compact ? 'compact' : ''}`}>
      <span className="data-label">{data.label}</span>
      <span className="data-type">{data.type_name}</span>
      {!compact && <span className="data-value">{data.preview}</span>}
      {data.size && <span className="data-size">{data.size}</span>}
    </div>
  );
}

function Operation({ op, isExpanded, onToggle }: { 
  op: OperationInfo; 
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const icon = getOperationIcon(op.type);
  const isLLM = op.type === 'llm';
  
  return (
    <div className={`operation ${op.type} ${op.error ? 'error' : ''}`}>
      <div className="operation-header" onClick={onToggle}>
        <span className="op-icon">{icon}</span>
        <span className="op-name">{op.name}</span>
        {isLLM && op.schema_name && (
          <span className="op-schema">{op.schema_name}</span>
        )}
        <span className="op-duration">{formatDuration(op.duration_ms)}</span>
        {isLLM && op.input_tokens && op.output_tokens && (
          <span className="op-tokens">{op.input_tokens}→{op.output_tokens}</span>
        )}
        <span className="expand-indicator">{isExpanded ? '▼' : '▶'}</span>
      </div>
      
      {isExpanded && (
        <div className="operation-details">
          {op.inputs.length > 0 && (
            <div className="io-section">
              <div className="io-label">INPUTS</div>
              <div className="io-items">
                {op.inputs.map((inp, i) => (
                  <DataPreview key={i} data={inp} />
                ))}
              </div>
            </div>
          )}
          
          <div className="op-arrow">↓</div>
          
          {op.outputs.length > 0 && (
            <div className="io-section">
              <div className="io-label">OUTPUTS</div>
              <div className="io-items">
                {op.outputs.map((out, i) => (
                  <DataPreview key={i} data={out} />
                ))}
              </div>
            </div>
          )}
          
          {op.error && (
            <div className="op-error">
              <span className="error-label">ERROR:</span> {op.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FlowStep({ step, isExpanded, onToggle }: {
  step: DataFlowStepInfo;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [expandedOps, setExpandedOps] = useState<Set<string>>(new Set());
  
  const toggleOp = (opId: string) => {
    setExpandedOps(prev => {
      const next = new Set(prev);
      if (next.has(opId)) {
        next.delete(opId);
      } else {
        next.add(opId);
      }
      return next;
    });
  };
  
  const expandAllOps = () => {
    setExpandedOps(new Set(step.operations.map(op => op.id)));
  };
  
  const llmCount = step.operations.filter(op => op.type === 'llm').length;
  const totalLLMTime = step.operations
    .filter(op => op.type === 'llm')
    .reduce((sum, op) => sum + op.duration_ms, 0);
  
  return (
    <div className={`flow-step ${getStatusClass(step.status)}`}>
      <div className="step-header" onClick={onToggle}>
        <div className="step-title">
          <span className="step-name">{step.step_name}</span>
          <span className={`step-status-badge ${getStatusClass(step.status)}`}>
            {step.status}
          </span>
        </div>
        <div className="step-meta">
          <span className="step-duration">{formatDuration(step.total_duration_ms)}</span>
          {llmCount > 0 && (
            <span className="step-llm-count">
              🤖 {llmCount} LLM call{llmCount > 1 ? 's' : ''} ({formatDuration(totalLLMTime)})
            </span>
          )}
          <span className="step-expand">{isExpanded ? '▼' : '▶'}</span>
        </div>
      </div>
      
      {isExpanded && (
        <div className="step-body">
          {/* Step input */}
          {step.step_input && (
            <div className="step-io step-input-section">
              <div className="step-io-label">INPUT</div>
              <DataPreview data={step.step_input} />
            </div>
          )}
          
          {/* Operations */}
          <div className="operations-section">
            <div className="operations-header">
              <span className="operations-title">Operations ({step.operations.length})</span>
              <button className="expand-all-btn" onClick={(e) => { e.stopPropagation(); expandAllOps(); }}>
                Expand All
              </button>
            </div>
            <div className="operations-list">
              {step.operations.map(op => (
                <Operation
                  key={op.id}
                  op={op}
                  isExpanded={expandedOps.has(op.id)}
                  onToggle={() => toggleOp(op.id)}
                />
              ))}
            </div>
          </div>
          
          {/* Step output */}
          {step.step_output && (
            <div className="step-io step-output-section">
              <div className="step-io-label">OUTPUT</div>
              <DataPreview data={step.step_output} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function DataFlowDiagram({ dataFlow, userRequest, finalAnswer }: DataFlowDiagramProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(() => {
    // Expand all steps by default
    return new Set(dataFlow.map(s => s.step_id));
  });
  
  const toggleStep = (stepId: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(stepId)) {
        next.delete(stepId);
      } else {
        next.add(stepId);
      }
      return next;
    });
  };
  
  const expandAll = () => setExpandedSteps(new Set(dataFlow.map(s => s.step_id)));
  const collapseAll = () => setExpandedSteps(new Set());
  
  const totalLLMCalls = dataFlow.reduce(
    (sum, step) => sum + step.operations.filter(op => op.type === 'llm').length,
    0
  );
  const totalLLMTime = dataFlow.reduce(
    (sum, step) => sum + step.operations.filter(op => op.type === 'llm').reduce((s, op) => s + op.duration_ms, 0),
    0
  );
  const totalTime = dataFlow.reduce((sum, step) => sum + step.total_duration_ms, 0);
  
  return (
    <div className="data-flow-diagram">
      <div className="diagram-header">
        <h2>Data Flow Visualization</h2>
        <div className="diagram-controls">
          <div className="diagram-stats">
            <span className="stat">
              <span className="stat-value">{dataFlow.length}</span> steps
            </span>
            <span className="stat">
              <span className="stat-value">{totalLLMCalls}</span> LLM calls
            </span>
            <span className="stat">
              <span className="stat-value">{formatDuration(totalLLMTime)}</span> LLM time
            </span>
            <span className="stat">
              <span className="stat-value">{formatDuration(totalTime)}</span> total
            </span>
          </div>
          <div className="diagram-buttons">
            <button onClick={expandAll}>Expand All</button>
            <button onClick={collapseAll}>Collapse All</button>
          </div>
        </div>
      </div>
      
      <div className="flow-container">
        {/* User input node */}
        <div className="flow-node input-node">
          <div className="node-header">USER INPUT</div>
          <div className="node-content">
            <span className="node-preview">
              {userRequest.length > 120 ? userRequest.substring(0, 120) + '...' : userRequest}
            </span>
            <span className="node-size">{userRequest.length} chars</span>
          </div>
        </div>
        
        <div className="flow-connector">
          <div className="connector-line" />
          <div className="connector-arrow">▼</div>
        </div>
        
        {/* Data flow steps */}
        {dataFlow.map((step, idx) => (
          <div key={step.step_id} className="flow-step-container">
            <FlowStep
              step={step}
              isExpanded={expandedSteps.has(step.step_id)}
              onToggle={() => toggleStep(step.step_id)}
            />
            
            {idx < dataFlow.length - 1 && (
              <div className="flow-connector">
                <div className="connector-line" />
                <div className="connector-arrow">▼</div>
              </div>
            )}
          </div>
        ))}
        
        {/* Final output node */}
        {finalAnswer && (
          <>
            <div className="flow-connector">
              <div className="connector-line" />
              <div className="connector-arrow">▼</div>
            </div>
            
            <div className="flow-node output-node">
              <div className="node-header">FINAL OUTPUT</div>
              <div className="node-content">
                <span className="node-preview">
                  {finalAnswer.length > 120 ? finalAnswer.substring(0, 120) + '...' : finalAnswer}
                </span>
                <span className="node-size">{finalAnswer.length} chars</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

