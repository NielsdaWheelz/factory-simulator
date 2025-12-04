import { useState } from 'react';
import type { AgentResponse, OnboardingIssueInfo, OnboardingTrust } from '../api';
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

function getTrustBadge(trust: OnboardingTrust | null): { text: string; className: string } | null {
  if (!trust) return null;
  switch (trust) {
    case 'HIGH_TRUST':
      return { text: '● High Trust', className: 'trust-high' };
    case 'MEDIUM_TRUST':
      return { text: '◐ Medium Trust', className: 'trust-medium' };
    case 'LOW_TRUST':
      return { text: '○ Low Trust', className: 'trust-low' };
    default:
      return null;
  }
}

// Onboarding stage detection patterns
const ONBOARDING_STAGE_PATTERNS: { pattern: RegExp; stage: string; icon: string }[] = [
  { pattern: /^O0[:\s]|explicit.?id|regex/i, stage: 'O0', icon: '🔍' },
  { pattern: /^O1[:\s]|entity|entities|extract.*(machine|job)/i, stage: 'O1', icon: '📦' },
  { pattern: /^O2[:\s]|routing|route/i, stage: 'O2', icon: '🔀' },
  { pattern: /^O3[:\s]|parameter|timing|duration/i, stage: 'O3', icon: '⏱️' },
  { pattern: /^O4[:\s]|assembl|normaliz|invariant/i, stage: 'O4', icon: '🔧' },
  { pattern: /^O5[:\s]|coverage|consensus|multi.?pass|alternative/i, stage: 'O5', icon: '📊' },
  { pattern: /^O6[:\s]|score|trust|diagnostic/i, stage: 'O6', icon: '✅' },
];

// Issue type detection patterns
const ISSUE_PATTERNS: { pattern: RegExp; type: string; severity: 'error' | 'warning' | 'info' }[] = [
  { pattern: /coverage.?miss|missing.*(machine|job)/i, type: 'coverage', severity: 'warning' },
  { pattern: /normalization|repair|clamp|drop/i, type: 'normalization', severity: 'warning' },
  { pattern: /alt.?conflict|alternative|differ|disagreement/i, type: 'alt_conflict', severity: 'info' },
  { pattern: /error|fail|invalid/i, type: 'error', severity: 'error' },
  { pattern: /warning|warn/i, type: 'warning', severity: 'warning' },
];

interface ParsedThought {
  stepNum: string | null;
  content: string;
  itemType: 'plan' | 'executing' | 'onboarding' | 'issue' | 'error' | 'default';
  onboardingStage: string | null;
  onboardingIcon: string | null;
  issueType: string | null;
  issueSeverity: 'error' | 'warning' | 'info' | null;
}

function parseThought(thought: string): ParsedThought {
  // Parse step number from "[Step X]" prefix
  const stepMatch = thought.match(/^\[Step (\d+)\] (.+)$/);
  const stepNum = stepMatch ? stepMatch[1] : null;
  const content = stepMatch ? stepMatch[2] : thought;

  // Detect onboarding stage
  let onboardingStage: string | null = null;
  let onboardingIcon: string | null = null;
  for (const { pattern, stage, icon } of ONBOARDING_STAGE_PATTERNS) {
    if (pattern.test(content)) {
      onboardingStage = stage;
      onboardingIcon = icon;
      break;
    }
  }

  // Detect issue type
  let issueType: string | null = null;
  let issueSeverity: 'error' | 'warning' | 'info' | null = null;
  for (const { pattern, type, severity } of ISSUE_PATTERNS) {
    if (pattern.test(content)) {
      issueType = type;
      issueSeverity = severity;
      break;
    }
  }

  // Determine overall item type
  let itemType: ParsedThought['itemType'] = 'default';
  
  if (issueType === 'error' || content.toLowerCase().includes('error')) {
    itemType = 'error';
  } else if (issueType) {
    itemType = 'issue';
  } else if (onboardingStage) {
    itemType = 'onboarding';
  } else if (content.toLowerCase().startsWith('plan:')) {
    itemType = 'plan';
  } else if (content.toLowerCase().startsWith('executing:')) {
    itemType = 'executing';
  }

  return {
    stepNum,
    content,
    itemType,
    onboardingStage,
    onboardingIcon,
    issueType,
    issueSeverity,
  };
}

function OnboardingScoreBadge({ score, trust }: { score: number | null; trust: OnboardingTrust | null }) {
  if (score === null) return null;
  
  const trustBadge = getTrustBadge(trust);
  
  return (
    <div className="onboarding-score-badge">
      <span className="score-value">{score}</span>
      <span className="score-label">/ 100</span>
      {trustBadge && (
        <span className={`trust-indicator ${trustBadge.className}`}>
          {trustBadge.text}
        </span>
      )}
    </div>
  );
}

function OnboardingIssuesList({ issues }: { issues: OnboardingIssueInfo[] }) {
  if (issues.length === 0) return null;

  const groupedIssues = issues.reduce((acc, issue) => {
    const severity = issue.severity || 'info';
    if (!acc[severity]) acc[severity] = [];
    acc[severity].push(issue);
    return acc;
  }, {} as Record<string, OnboardingIssueInfo[]>);

  const severityOrder = ['error', 'warning', 'info'];

  return (
    <div className="onboarding-issues-section">
      <div className="issues-header">
        <span className="issues-icon">⚠️</span>
        <span className="issues-title">Onboarding Issues ({issues.length})</span>
      </div>
      <div className="issues-list">
        {severityOrder.map(severity => {
          const severityIssues = groupedIssues[severity];
          if (!severityIssues || severityIssues.length === 0) return null;
          return severityIssues.map((issue, idx) => (
            <div key={`${severity}-${idx}`} className={`issue-item issue-${issue.severity}`}>
              <span className="issue-type-badge">{issue.type}</span>
              <span className="issue-message">{issue.message}</span>
              {issue.related_ids && issue.related_ids.length > 0 && (
                <span className="issue-related-ids">
                  [{issue.related_ids.join(', ')}]
                </span>
              )}
            </div>
          ));
        })}
      </div>
    </div>
  );
}

function ScratchpadItem({ thought }: { thought: string }) {
  const parsed = parseThought(thought);

  const classNames = [
    'scratchpad-item',
    parsed.itemType,
    parsed.issueSeverity ? `severity-${parsed.issueSeverity}` : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={classNames}>
      <div className="item-badges">
        {parsed.stepNum && <span className="step-badge">Step {parsed.stepNum}</span>}
        {parsed.onboardingStage && (
          <span className="onboarding-stage-badge">
            {parsed.onboardingIcon} {parsed.onboardingStage}
          </span>
        )}
        {parsed.issueType && parsed.issueType !== 'error' && (
          <span className={`issue-type-indicator ${parsed.issueSeverity}`}>
            {parsed.issueType}
          </span>
        )}
      </div>
      <span className="thought-content">{parsed.content}</span>
    </div>
  );
}

export function AgentTrace({ response }: AgentTraceProps) {
  const [showScratchpad, setShowScratchpad] = useState(true);
  const [showIssues, setShowIssues] = useState(true);
  
  const statusBadge = getStatusBadge(response.status);
  const hasOnboardingData = response.onboarding_score !== null || response.onboarding_issues.length > 0;
  
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

      {/* Onboarding Score Banner */}
      {hasOnboardingData && (
        <div className="onboarding-banner">
          <div className="onboarding-banner-header">
            <span className="onboarding-banner-title">📋 Onboarding Quality</span>
            <OnboardingScoreBadge 
              score={response.onboarding_score} 
              trust={response.onboarding_trust} 
            />
          </div>
          {response.onboarding_issues.length > 0 && (
            <button 
              className="expand-btn issues-toggle"
              onClick={() => setShowIssues(!showIssues)}
            >
              {showIssues ? 'Hide' : 'Show'} Issues ({response.onboarding_issues.length})
            </button>
          )}
        </div>
      )}

      {/* Onboarding Issues */}
      {showIssues && response.onboarding_issues.length > 0 && (
        <OnboardingIssuesList issues={response.onboarding_issues} />
      )}

      {/* Pipeline Legend */}
      {hasOnboardingData && showScratchpad && (
        <div className="pipeline-legend">
          <span className="legend-title">Pipeline Stages:</span>
          <div className="legend-items">
            <span className="legend-item"><span className="legend-icon">🔍</span> O0: IDs</span>
            <span className="legend-item"><span className="legend-icon">📦</span> O1: Entities</span>
            <span className="legend-item"><span className="legend-icon">🔀</span> O2: Routing</span>
            <span className="legend-item"><span className="legend-icon">⏱️</span> O3: Params</span>
            <span className="legend-item"><span className="legend-icon">🔧</span> O4: Assemble</span>
            <span className="legend-item"><span className="legend-icon">📊</span> O5: Consensus</span>
            <span className="legend-item"><span className="legend-icon">✅</span> O6: Score</span>
          </div>
        </div>
      )}
      
      {showScratchpad && response.scratchpad.length > 0 && (
        <div className="scratchpad-section">
          <div className="scratchpad-list">
            {response.scratchpad.map((thought, idx) => (
              <ScratchpadItem key={idx} thought={thought} />
            ))}
          </div>
        </div>
      )}
      
      {response.scratchpad.length === 0 && (
        <div className="no-trace">No thinking log available.</div>
      )}
    </div>
  );
}
