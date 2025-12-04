import { useState } from 'react';
import { runAgent, type AgentResponse } from './api';
import { AgentTrace } from './components/AgentTrace';
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

function App() {
  const [factoryDescription, setFactoryDescription] = useState(DEFAULT_FACTORY_DESCRIPTION);
  const [situation, setSituation] = useState(DEFAULT_SITUATION);
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAgentTrace, setShowAgentTrace] = useState(false);

  const handleSimulate = async () => {
    setLoading(true);
    setError(null);
    setAgentResult(null);
    
    try {
      const userRequest = `Factory: ${factoryDescription}\n\nSituation: ${situation}`;
      const response = await runAgent(userRequest);
      setAgentResult(response);
      console.log('Agent complete:', response);
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
        <button
          className="btn btn-ghost debug-toggle"
          onClick={() => setShowAgentTrace(!showAgentTrace)}
        >
          {showAgentTrace ? 'Hide' : 'Show'} Debug Trace
        </button>
      </header>

      <main className="app-main">
        <div className="layout">
          {/* LEFT COLUMN: Inputs & Controls */}
          <section className="layout-column layout-column--left">
            <div className="panel">
              <h2 className="panel-title">Inputs</h2>
              
              <div className="form-group">
                <label htmlFor="factory-desc">Factory Description</label>
                <textarea
                  id="factory-desc"
                  className="textarea"
                  value={factoryDescription}
                  onChange={(e) => setFactoryDescription(e.target.value)}
                  placeholder="Describe your factory, machines, and jobs..."
                  rows={8}
                />
              </div>

              <div className="form-group">
                <label htmlFor="situation">Situation & Priorities</label>
                <textarea
                  id="situation"
                  className="textarea"
                  value={situation}
                  onChange={(e) => setSituation(e.target.value)}
                  placeholder="Describe current priorities, constraints, or special requests..."
                  rows={8}
                />
              </div>

              <button
                onClick={handleSimulate}
                disabled={loading}
                className="btn btn-primary"
                style={{ width: '100%' }}
              >
                {loading ? 'Running...' : 'Run Simulation'}
              </button>

              {error && (
                <div className="alert alert--error" style={{ marginTop: 'var(--space-4)' }}>
                  <strong>Error:</strong> {error}
                </div>
              )}
            </div>
          </section>

          {/* CENTER COLUMN: Data Flow Visualization */}
          <section className="layout-column layout-column--center">
            {agentResult && agentResult.data_flow && agentResult.data_flow.length > 0 ? (
              <DataFlowDiagram
                dataFlow={agentResult.data_flow}
                userRequest={`Factory: ${factoryDescription}\n\nSituation: ${situation}`}
                finalAnswer={agentResult.final_answer}
              />
            ) : (
              <div className="panel empty-state">
                <div className="empty-state-title">Ready to Simulate</div>
                <div className="empty-state-description">
                  Fill in the factory description and situation, then click "Run Simulation" to see the agent's analysis and data flow.
                </div>
              </div>
            )}
          </section>

          {/* RIGHT COLUMN: Analysis & Results */}
          <section className="layout-column layout-column--right">
            {agentResult && agentResult.factory && (
              <div className="panel factory-panel">
                <h2 className="panel-title">Inferred Factory</h2>
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
            )}

            {agentResult && agentResult.scenarios_run.length > 0 && (
              <div className="panel scenarios-panel">
                <h2 className="panel-title">Scenarios & Metrics</h2>
                <table className="table">
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
            )}

            {agentResult && agentResult.final_answer && (
              <div className="panel briefing-panel">
                <h2 className="panel-title">Agent Response</h2>
                <div className="briefing-content">
                  <div
                    className="briefing-text"
                    dangerouslySetInnerHTML={{
                      __html: markdownToHtml(agentResult.final_answer),
                    }}
                  />
                </div>
              </div>
            )}

            {agentResult && showAgentTrace && (
              <div className="panel panel--debug">
                <h2 className="panel-title">Debug Trace</h2>
                <AgentTrace response={agentResult} />
              </div>
            )}
          </section>
        </div>
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
