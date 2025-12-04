import { useState } from 'react';
import { runAgent, type AgentResponse, type OnboardingIssueInfo, type OnboardingTrust, type AltFactoryInfo, type DiffSummaryInfo } from './api';
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
  const [clarifications, setClarifications] = useState('');
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAgentTrace, setShowAgentTrace] = useState(false);

  const handleSimulate = async () => {
    setLoading(true);
    setError(null);
    setAgentResult(null);
    
    try {
      // Build user request with optional clarifications section
      let userRequest = `Factory:\n${factoryDescription}`;
      if (clarifications.trim()) {
        userRequest += `\n\nClarifications:\n${clarifications}`;
      }
      userRequest += `\n\nSituation:\n${situation}`;
      
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
                  rows={6}
                />
              </div>

              <div className="form-group">
                <label htmlFor="clarifications">
                  Clarifications for Next Run
                  <span className="label-hint"> (answer questions from previous run)</span>
                </label>
                <textarea
                  id="clarifications"
                  className="textarea textarea--clarifications"
                  value={clarifications}
                  onChange={(e) => setClarifications(e.target.value)}
                  placeholder="If the agent asked clarifying questions, answer them here and rerun..."
                  rows={4}
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
                userRequest={`Factory:\n${factoryDescription}${clarifications.trim() ? `\n\nClarifications:\n${clarifications}` : ''}\n\nSituation:\n${situation}`}
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
            {/* Onboarding Summary Panel */}
            {agentResult && agentResult.onboarding_score !== null && (
              <OnboardingSummary
                score={agentResult.onboarding_score}
                trust={agentResult.onboarding_trust}
                issues={agentResult.onboarding_issues}
              />
            )}

            {/* Alternative Interpretations Panel (PR9) */}
            {agentResult && agentResult.diff_summaries && agentResult.diff_summaries.length > 0 && (
              <AlternativeInterpretations
                altFactories={agentResult.alt_factories}
                diffSummaries={agentResult.diff_summaries}
                primaryFactory={agentResult.factory}
              />
            )}

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

// Onboarding Summary Component
interface OnboardingSummaryProps {
  score: number;
  trust: OnboardingTrust | null;
  issues: OnboardingIssueInfo[];
}

function OnboardingSummary({ score, trust, issues }: OnboardingSummaryProps) {
  const getTrustColor = (trust: OnboardingTrust | null): string => {
    switch (trust) {
      case 'HIGH_TRUST':
        return 'var(--status-success)';
      case 'MEDIUM_TRUST':
        return 'var(--status-warning)';
      case 'LOW_TRUST':
        return 'var(--status-error)';
      default:
        return 'var(--text-muted)';
    }
  };

  const getTrustLabel = (trust: OnboardingTrust | null): string => {
    switch (trust) {
      case 'HIGH_TRUST':
        return 'High Trust';
      case 'MEDIUM_TRUST':
        return 'Medium Trust';
      case 'LOW_TRUST':
        return 'Low Trust';
      default:
        return 'Unknown';
    }
  };

  const getSeverityIcon = (severity: string): string => {
    switch (severity.toLowerCase()) {
      case 'error':
        return '✗';
      case 'warning':
        return '⚠';
      case 'info':
        return 'ℹ';
      default:
        return '•';
    }
  };

  const getSeverityClass = (severity: string): string => {
    switch (severity.toLowerCase()) {
      case 'error':
        return 'issue--error';
      case 'warning':
        return 'issue--warning';
      case 'info':
        return 'issue--info';
      default:
        return '';
    }
  };

  // Group issues by severity
  const errorIssues = issues.filter((i) => i.severity.toLowerCase() === 'error');
  const warningIssues = issues.filter((i) => i.severity.toLowerCase() === 'warning');
  const infoIssues = issues.filter((i) => i.severity.toLowerCase() === 'info');

  return (
    <div className="panel onboarding-summary-panel">
      <h2 className="panel-title">Onboarding Quality</h2>

      {/* Score and Trust Badge */}
      <div className="onboarding-score-section">
        <div className="onboarding-score">
          <span className="score-value">{score}</span>
          <span className="score-max">/100</span>
        </div>
        <div
          className="trust-badge"
          style={{ backgroundColor: getTrustColor(trust) }}
        >
          {getTrustLabel(trust)}
        </div>
      </div>

      {/* Issues List */}
      {issues.length > 0 ? (
        <div className="onboarding-issues">
          <h3 className="issues-header">
            Issues ({issues.length})
          </h3>
          <ul className="issues-list">
            {errorIssues.map((issue, idx) => (
              <li key={`error-${idx}`} className={`issue-item ${getSeverityClass(issue.severity)}`}>
                <span className="issue-icon">{getSeverityIcon(issue.severity)}</span>
                <span className="issue-message">{issue.message}</span>
                {issue.related_ids && issue.related_ids.length > 0 && (
                  <span className="issue-ids">[{issue.related_ids.join(', ')}]</span>
                )}
              </li>
            ))}
            {warningIssues.map((issue, idx) => (
              <li key={`warning-${idx}`} className={`issue-item ${getSeverityClass(issue.severity)}`}>
                <span className="issue-icon">{getSeverityIcon(issue.severity)}</span>
                <span className="issue-message">{issue.message}</span>
                {issue.related_ids && issue.related_ids.length > 0 && (
                  <span className="issue-ids">[{issue.related_ids.join(', ')}]</span>
                )}
              </li>
            ))}
            {infoIssues.map((issue, idx) => (
              <li key={`info-${idx}`} className={`issue-item ${getSeverityClass(issue.severity)}`}>
                <span className="issue-icon">{getSeverityIcon(issue.severity)}</span>
                <span className="issue-message">{issue.message}</span>
                {issue.related_ids && issue.related_ids.length > 0 && (
                  <span className="issue-ids">[{issue.related_ids.join(', ')}]</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="no-issues">
          <span className="no-issues-icon">✓</span>
          <span>No issues detected</span>
        </div>
      )}

      {/* Hint for correction loop */}
      {issues.length > 0 && (
        <p className="correction-hint">
          Answer the clarifying questions in the Agent Response below, then add your answers to the "Clarifications" box and rerun.
        </p>
      )}
    </div>
  );
}

// Alternative Interpretations Component (PR9)
interface AlternativeInterpretationsProps {
  altFactories: AltFactoryInfo[];
  diffSummaries: DiffSummaryInfo[];
  primaryFactory: { machines: { id: string; name: string }[]; jobs: { id: string; name: string }[] } | null;
}

function AlternativeInterpretations({ altFactories, diffSummaries, primaryFactory }: AlternativeInterpretationsProps) {
  if (diffSummaries.length === 0) {
    return null;
  }

  const getModeLabel = (mode: string): string => {
    switch (mode.toLowerCase()) {
      case 'conservative':
        return 'Conservative';
      case 'inclusive':
        return 'Inclusive';
      case 'default':
        return 'Default';
      default:
        return mode;
    }
  };

  const getModeDescription = (mode: string): string => {
    switch (mode.toLowerCase()) {
      case 'conservative':
        return 'Prefers explicit mentions, fewer inferences';
      case 'inclusive':
        return 'More aggressive at inferring entities';
      case 'default':
        return 'Balanced extraction';
      default:
        return '';
    }
  };

  return (
    <div className="panel alt-interpretations-panel">
      <h2 className="panel-title">
        Alternative Interpretations
        <span className="alt-count-badge">{diffSummaries.length}</span>
      </h2>

      <p className="alt-intro">
        Multiple plausible factories were extracted. The differences below show how alternative interpretations diverge from the primary.
      </p>

      {/* Primary factory summary */}
      {primaryFactory && (
        <div className="primary-summary">
          <h3 className="primary-label">Primary (selected)</h3>
          <div className="primary-entities">
            <span className="entity-count">
              <strong>{primaryFactory.machines.length}</strong> machines
            </span>
            <span className="entity-separator">•</span>
            <span className="entity-count">
              <strong>{primaryFactory.jobs.length}</strong> jobs
            </span>
          </div>
        </div>
      )}

      {/* Alternative diffs */}
      <ul className="alt-list">
        {diffSummaries.map((diffInfo, idx) => {
          const altFactory = altFactories[idx];
          return (
            <li key={idx} className="alt-item">
              <div className="alt-header">
                <span className="alt-label">Alt {idx + 1}</span>
                <span className="alt-mode" title={getModeDescription(diffInfo.mode)}>
                  {getModeLabel(diffInfo.mode)}
                </span>
              </div>
              {altFactory && (
                <div className="alt-entities">
                  <span className="entity-count">
                    {altFactory.machines.length} machines: {altFactory.machines.join(', ')}
                  </span>
                  <span className="entity-count">
                    {altFactory.jobs.length} jobs: {altFactory.jobs.join(', ')}
                  </span>
                </div>
              )}
              <div className="alt-diff">
                <span className="diff-icon">Δ</span>
                <span className="diff-summary">{diffInfo.summary}</span>
              </div>
            </li>
          );
        })}
      </ul>

      <p className="alt-hint">
        If an alternative looks more accurate, update your factory description to clarify and rerun.
      </p>
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
