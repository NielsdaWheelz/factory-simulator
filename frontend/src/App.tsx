import { useState } from 'react';
import { simulate, runAgent, type SimulateResponse, type AgentResponse } from './api';
import type { PipelineDebugPayload } from './types/pipeline';
import { PipelineSummary } from './components/PipelineSummary';
import { StageList } from './components/StageList';
import { AgentTrace } from './components/AgentTrace';
import { PipelineFlow } from './components/PipelineFlow';
import { DataFlowDiagram } from './components/DataFlowDiagram';
import './App.css';

const DEFAULT_FACTORY_DESCRIPTION = `We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).`;

const DEFAULT_SITUATION = `Today is a normal production day. No rush orders or unexpected events.
We want to understand baseline performance and explore what-if scenarios.
Key interest: bottleneck identification and makespan optimization.`;

type Mode = 'pipeline' | 'agent';

function App() {
  const [mode, setMode] = useState<Mode>('agent'); // Default to new agent mode
  const [factoryDescription, setFactoryDescription] = useState(DEFAULT_FACTORY_DESCRIPTION);
  const [situation, setSituation] = useState(DEFAULT_SITUATION);
  
  // Pipeline mode state
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [pipelineDebug, setPipelineDebug] = useState<PipelineDebugPayload | null>(null);
  const [expandedStageId, setExpandedStageId] = useState<string | null>(null);
  
  // Agent mode state
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null);
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSimulate = async () => {
    setLoading(true);
    setError(null);
    
    // Reset both result sets
    setResult(null);
    setAgentResult(null);
    setPipelineDebug(null);
    setExpandedStageId(null);
    
    try {
      if (mode === 'agent') {
        // Agent mode: combine factory + situation into a single request
        const userRequest = `Factory: ${factoryDescription}\n\nSituation: ${situation}`;
        const response = await runAgent(userRequest);
        setAgentResult(response);
        console.log('Agent complete:', response);
      } else {
        // Pipeline mode: use legacy endpoint
        const response = await simulate(factoryDescription, situation);
        setResult(response);
        setPipelineDebug(response.debug ?? null);
        console.log('Simulation complete:', response);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not reach simulation server';
      setError(message);
      console.error('Simulation failed:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Factory Simulator</h1>
        <div className="mode-toggle">
          <button 
            className={`mode-btn ${mode === 'agent' ? 'active' : ''}`}
            onClick={() => setMode('agent')}
          >
            🤖 Agent Mode
          </button>
          <button 
            className={`mode-btn ${mode === 'pipeline' ? 'active' : ''}`}
            onClick={() => setMode('pipeline')}
          >
            📊 Pipeline Mode
          </button>
        </div>
      </header>

      <main className="app-main">
        {/* Instructions */}
        <p className="instructions">
          {mode === 'agent' 
            ? '🤖 Agent Mode: The AI agent will dynamically decide what to do based on your request.'
            : '📊 Pipeline Mode: Fixed 10-stage pipeline (legacy mode).'
          }
        </p>

        {/* Input Section */}
        <section className="input-section">
          <div className="textarea-group">
            <label htmlFor="factory-desc">Factory Description (machines, jobs, routing)</label>
            <textarea
              id="factory-desc"
              value={factoryDescription}
              onChange={(e) => setFactoryDescription(e.target.value)}
              placeholder="Describe your factory, machines, and jobs..."
              rows={6}
            />
          </div>

          <div className="textarea-group">
            <label htmlFor="situation">Today's Situation / Priorities (rush orders, slowdowns, constraints)</label>
            <textarea
              id="situation"
              value={situation}
              onChange={(e) => setSituation(e.target.value)}
              placeholder="Describe current priorities, constraints, or special requests..."
              rows={6}
            />
          </div>
        </section>

        {/* Simulate Button */}
        <section className="button-section">
          <button
            onClick={handleSimulate}
            disabled={loading}
            className="simulate-button"
          >
            {loading ? 'Simulating...' : 'Simulate'}
          </button>
        </section>

        {/* Error Banner */}
        {error && (
          <div className="error-banner">
            Error: {error}
          </div>
        )}

        {/* Output Panels - Agent Mode */}
        {mode === 'agent' && agentResult && (
          <div className="output-panels">
            {/* Data Flow Diagram - Main Visualization */}
            {agentResult.data_flow && agentResult.data_flow.length > 0 && (
              <section className="panel data-flow-panel">
                <DataFlowDiagram
                  dataFlow={agentResult.data_flow}
                  userRequest={`Factory: ${factoryDescription}\n\nSituation: ${situation}`}
                  finalAnswer={agentResult.final_answer}
                />
              </section>
            )}

            {/* Agent Trace Panel (collapsed by default, for debugging) */}
            <section className="panel agent-panel">
              <AgentTrace response={agentResult} />
            </section>
            
            {/* Factory Panel (if agent loaded one) */}
            {agentResult.factory && (
              <section className="panel factory-panel">
                <h2>Inferred Factory</h2>
                <div className="panel-content">
                  <div className="factory-subsection">
                    <h3>Machines</h3>
                    <ul className="machine-list">
                      {agentResult.factory.machines.map((machine) => (
                        <li key={machine.id}>
                          <strong>{machine.id}</strong> – {machine.name}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="factory-subsection">
                    <h3>Jobs</h3>
                    <ul className="job-list">
                      {agentResult.factory.jobs.map((job) => (
                        <li key={job.id}>
                          <strong>{job.id}</strong> ({job.name}) – Due: {job.due_time_hour}h
                          <ul className="steps-list">
                            {job.steps.map((step, idx) => (
                              <li key={idx}>
                                {step.machine_id}: {step.duration_hours}h
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </section>
            )}

            {/* Scenarios & Metrics (if agent ran simulations) */}
            {agentResult.scenarios_run.length > 0 && (
              <section className="panel scenarios-panel">
                <h2>Scenarios & Metrics</h2>
                <div className="panel-content">
                  <table className="metrics-table">
                    <thead>
                      <tr>
                        <th>Scenario</th>
                        <th>Makespan (h)</th>
                        <th>Late Jobs</th>
                        <th>Bottleneck Machine</th>
                        <th>Bottleneck Util.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agentResult.scenarios_run.map((spec, idx) => {
                        const metric = agentResult.metrics_collected[idx];
                        if (!metric) return null;
                        const lateJobs = Object.entries(metric.job_lateness)
                          .filter(([_, lateness]) => lateness > 0)
                          .map(([jobId]) => jobId);
                        return (
                          <tr key={idx}>
                            <td>{spec.scenario_type}</td>
                            <td>{metric.makespan_hour}</td>
                            <td>{lateJobs.length > 0 ? lateJobs.join(', ') : 'None'}</td>
                            <td>{metric.bottleneck_machine_id}</td>
                            <td>{(metric.bottleneck_utilization * 100).toFixed(0)}%</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* Final Answer (Briefing) */}
            {agentResult.final_answer && (
              <section className="panel briefing-panel">
                <h2>Agent Response</h2>
                <div className="briefing-content">
                  <div
                    className="briefing-text"
                    dangerouslySetInnerHTML={{
                      __html: markdownToHtml(agentResult.final_answer),
                    }}
                  />
                </div>
              </section>
            )}
          </div>
        )}

        {/* Output Panels - Pipeline Mode (Legacy) */}
        {mode === 'pipeline' && result && (
          <div className="output-panels">
            {/* Pipeline Panel */}
            <section className="panel pipeline-panel">
              <h2>Pipeline Status</h2>
              <PipelineSummary
                debug={pipelineDebug}
                usedDefaultFactory={result.meta?.used_default_factory ?? false}
              />
              {pipelineDebug && (
                <StageList
                  stages={pipelineDebug.stages}
                  selectedStageId={expandedStageId}
                  onSelectStage={setExpandedStageId}
                />
              )}
            </section>
            {/* Factory Panel */}
            <section className="panel factory-panel">
              <h2>Inferred Factory</h2>

              {/* Fallback Warning Banner */}
              {result.meta?.used_default_factory && (
                <div className="fallback-banner">
                  <div className="banner-header">
                    <strong>⚠️ using demo factory</strong>
                  </div>
                  <p className="banner-message">
                    we couldn&apos;t parse your factory description. the system is using a built-in demo factory instead. review the factory below to ensure it matches your intent.
                  </p>
                  {result.meta?.onboarding_errors && result.meta.onboarding_errors.length > 0 && (
                    <div className="errors-box">
                      <strong>issues encountered:</strong>
                      <ul className="errors-list">
                        {result.meta.onboarding_errors.map((error, idx) => (
                          <li key={idx}>{error}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {pipelineDebug && (() => {
                    // prefer o4 (coverage assessment) if it failed, otherwise first failed onboarding stage
                    const onboardingStages = pipelineDebug.stages.filter(s => s.kind === 'ONBOARDING');
                    const failedOnboarding = onboardingStages.filter(s => s.status === 'FAILED');
                    const coverageStage = failedOnboarding.find(s => s.id === 'o4');
                    const firstFailedStage = coverageStage || failedOnboarding[0];
                    
                    return firstFailedStage ? (
                      <button
                        className="view-details-button"
                        onClick={() => setExpandedStageId(firstFailedStage.id)}
                      >
                        view pipeline details
                      </button>
                    ) : null;
                  })()}
                </div>
              )}

              <div className="panel-content">
                <div className="factory-subsection">
                  <h3>Machines</h3>
                  <ul className="machine-list">
                    {result.factory.machines.map((machine) => (
                      <li key={machine.id}>
                        <strong>{machine.id}</strong> – {machine.name}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="factory-subsection">
                  <h3>Jobs</h3>
                  <ul className="job-list">
                    {result.factory.jobs.map((job) => (
                      <li key={job.id}>
                        <strong>{job.id}</strong> ({job.name}) – Due: {job.due_time_hour}h
                        <ul className="steps-list">
                          {job.steps.map((step, idx) => (
                            <li key={idx}>
                              {step.machine_id}: {step.duration_hours}h
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            {/* Scenarios & Metrics Panel */}
            <section className="panel scenarios-panel">
              <h2>Scenarios & Metrics</h2>

              {/* Fallback Notice for Simulate */}
              {result.meta?.used_default_factory && (
                <div className="fallback-notice">
                  <p>
                    <strong>Note:</strong> The scenarios and metrics below are based on the demo factory, not your original input.
                  </p>
                </div>
              )}

              <div className="panel-content">
                <table className="metrics-table">
                  <thead>
                    <tr>
                      <th>Scenario</th>
                      <th>Makespan (h)</th>
                      <th>Late Jobs</th>
                      <th>Bottleneck Machine</th>
                      <th>Bottleneck Util.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.specs.map((spec, idx) => {
                      const metric = result.metrics[idx];
                      const lateJobs = Object.entries(metric.job_lateness)
                        .filter(([_, lateness]) => lateness > 0)
                        .map(([jobId]) => jobId);
                      return (
                        <tr key={idx}>
                          <td>{spec.scenario_type}</td>
                          <td>{metric.makespan_hour.toFixed(2)}</td>
                          <td>{lateJobs.length > 0 ? lateJobs.join(', ') : 'None'}</td>
                          <td>{metric.bottleneck_machine_id}</td>
                          <td>{(metric.bottleneck_utilization * 100).toFixed(0)}%</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Briefing Panel */}
            <section className="panel briefing-panel">
              <h2>Decision Briefing</h2>
              <div className="briefing-content">
                <div
                  className="briefing-text"
                  dangerouslySetInnerHTML={{
                    __html: markdownToHtml(result.briefing),
                  }}
                />
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

// Simple markdown to HTML converter (basic formatting only)
function markdownToHtml(markdown: string): string {
  return markdown
    .split('\n')
    .map((line) => {
      // Headers
      if (line.startsWith('## ')) {
        return `<h3>${line.substring(3)}</h3>`;
      }
      if (line.startsWith('# ')) {
        return `<h2>${line.substring(2)}</h2>`;
      }
      // Bold
      if (line.includes('**')) {
        return `<p>${line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')}</p>`;
      }
      // Regular paragraph
      if (line.trim()) {
        return `<p>${line}</p>`;
      }
      return '';
    })
    .join('');
}

export default App;
