"""
Tests for BriefingAgent and GenerateBriefingTool with onboarding context (PR6).

Tests cover:
- BriefingAgent with onboarding_context parameter
- Onboarding sections in generated briefings (Issues, Clarifying Questions)
- Deterministic fallback with onboarding issues
- GenerateBriefingTool._build_onboarding_context helper
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.agents import BriefingAgent, BriefingResponse
from backend.agent_tools import GenerateBriefingTool
from backend.agent_types import (
    AgentState,
    OnboardingIssue,
)
from backend.models import (
    FactoryConfig,
    Machine,
    Job,
    Step,
    ScenarioSpec,
    ScenarioType,
    ScenarioMetrics,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_factory():
    """Return a sample FactoryConfig for testing."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
            Machine(id="M3", name="Pack"),
        ],
        jobs=[
            Job(id="J1", name="Widget A", steps=[
                Step(machine_id="M1", duration_hours=1),
                Step(machine_id="M2", duration_hours=3),
                Step(machine_id="M3", duration_hours=1),
            ], due_time_hour=12),
            Job(id="J2", name="Gadget B", steps=[
                Step(machine_id="M1", duration_hours=1),
                Step(machine_id="M2", duration_hours=2),
                Step(machine_id="M3", duration_hours=1),
            ], due_time_hour=14),
        ],
    )


@pytest.fixture
def baseline_metrics():
    """Return sample baseline metrics."""
    return ScenarioMetrics(
        makespan_hour=11,
        job_lateness={"J1": 0, "J2": 0},
        bottleneck_machine_id="M2",
        bottleneck_utilization=0.95,
    )


@pytest.fixture
def sample_onboarding_issues():
    """Return sample onboarding issues for testing."""
    return [
        OnboardingIssue(
            type="coverage_miss",
            severity="warning",
            message="Machine M4 mentioned in description but not in parsed config",
            related_ids=["M4"],
        ),
        OnboardingIssue(
            type="normalization_repair",
            severity="info",
            message="Duration for J1 step on M2 clamped from 3.5 to 4 hours",
            related_ids=["J1", "M2"],
        ),
        OnboardingIssue(
            type="alt_conflict",
            severity="error",
            message="Alternative config differs in J2 routing: M1->M3 vs M1->M2->M3",
            related_ids=["J2"],
        ),
    ]


@pytest.fixture
def state_with_onboarding_issues(sample_factory, baseline_metrics, sample_onboarding_issues):
    """Return an AgentState with factory, metrics, and onboarding issues."""
    state = AgentState(user_request="Analyze my factory with M1, M2, M3, M4")
    state.factory = sample_factory
    state.scenarios_run = [ScenarioSpec(scenario_type=ScenarioType.BASELINE)]
    state.metrics_collected = [baseline_metrics]
    state.onboarding_issues = sample_onboarding_issues
    state.onboarding_score = 65
    state.onboarding_trust = "MEDIUM_TRUST"
    return state


@pytest.fixture
def state_without_onboarding_issues(sample_factory, baseline_metrics):
    """Return an AgentState with factory and metrics but no onboarding issues."""
    state = AgentState(user_request="Analyze my factory")
    state.factory = sample_factory
    state.scenarios_run = [ScenarioSpec(scenario_type=ScenarioType.BASELINE)]
    state.metrics_collected = [baseline_metrics]
    # No onboarding issues set
    return state


# =============================================================================
# BRIEFING AGENT TESTS
# =============================================================================

class TestBriefingAgentOnboardingContext:
    """Tests for BriefingAgent with onboarding context."""

    def test_run_with_onboarding_context_calls_llm(self, baseline_metrics, sample_factory):
        """Test that BriefingAgent.run includes onboarding context in LLM call."""
        mock_response = BriefingResponse(
            markdown="# Factory Analysis Report\n\n## Onboarding Issues\nTest issues\n\n## Clarifying Questions\n1. Test question?"
        )
        
        with patch("backend.agents.call_llm_json", return_value=mock_response) as mock_llm:
            agent = BriefingAgent()
            onboarding_ctx = "Onboarding Quality Score: 65/100 (MEDIUM_TRUST)\n\n- [WARNING] Test issue"
            
            result = agent.run(
                baseline_metrics,
                onboarding_context=onboarding_ctx,
                factory=sample_factory,
            )
            
            # Verify LLM was called
            mock_llm.assert_called_once()
            
            # Check prompt contains onboarding context
            call_args = mock_llm.call_args
            prompt = call_args[0][0]  # First positional argument
            assert "Onboarding Diagnostics" in prompt
            assert "65/100" in prompt
            assert "MEDIUM_TRUST" in prompt

    def test_run_without_onboarding_context(self, baseline_metrics, sample_factory):
        """Test that BriefingAgent.run works without onboarding context."""
        mock_response = BriefingResponse(
            markdown="# Factory Analysis Report\n\n## Key Risks\nStandard briefing"
        )
        
        with patch("backend.agents.call_llm_json", return_value=mock_response) as mock_llm:
            agent = BriefingAgent()
            
            result = agent.run(
                baseline_metrics,
                onboarding_context=None,
                factory=sample_factory,
            )
            
            mock_llm.assert_called_once()
            
            # Check prompt does NOT contain onboarding instructions
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            assert "Onboarding Diagnostics" not in prompt

    def test_run_with_onboarding_requires_clarifying_questions_in_schema(self, baseline_metrics, sample_factory):
        """Test that schema includes Clarifying Questions when onboarding context present."""
        mock_response = BriefingResponse(markdown="# Report")
        
        with patch("backend.agents.call_llm_json", return_value=mock_response) as mock_llm:
            agent = BriefingAgent()
            
            agent.run(
                baseline_metrics,
                onboarding_context="Issues detected",
                factory=sample_factory,
            )
            
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            
            # Schema should include both Onboarding Issues and Clarifying Questions
            assert "Onboarding Issues" in prompt
            assert "Clarifying Questions" in prompt

    def test_fallback_includes_onboarding_sections(self, baseline_metrics):
        """Test that deterministic fallback includes onboarding sections when context provided."""
        agent = BriefingAgent()
        
        # Force fallback by raising exception
        with patch("backend.agents.call_llm_json", side_effect=Exception("LLM error")):
            result = agent.run(
                baseline_metrics,
                onboarding_context="Score: 50/100\n- [ERROR] Missing machine M4",
            )
        
        # Check fallback contains onboarding sections
        assert "## Onboarding Issues" in result
        assert "## Clarifying Questions" in result
        assert "Missing machine M4" in result
        assert "Update your factory description" in result

    def test_fallback_without_onboarding_skips_sections(self, baseline_metrics):
        """Test that fallback skips onboarding sections when no context provided."""
        agent = BriefingAgent()
        
        with patch("backend.agents.call_llm_json", side_effect=Exception("LLM error")):
            result = agent.run(baseline_metrics, onboarding_context=None)
        
        # Fallback should NOT have onboarding sections
        assert "## Onboarding Issues" not in result
        assert "## Clarifying Questions" not in result

    def test_uses_provided_factory_for_context(self, baseline_metrics, sample_factory):
        """Test that BriefingAgent uses provided factory for job/machine summary."""
        mock_response = BriefingResponse(markdown="# Report")
        
        with patch("backend.agents.call_llm_json", return_value=mock_response) as mock_llm:
            agent = BriefingAgent()
            
            agent.run(baseline_metrics, factory=sample_factory)
            
            call_args = mock_llm.call_args
            prompt = call_args[0][0]
            
            # Should use provided factory's jobs/machines
            assert "M1" in prompt
            assert "M2" in prompt
            assert "J1" in prompt
            assert "Widget A" in prompt


# =============================================================================
# GENERATE BRIEFING TOOL TESTS
# =============================================================================

class TestGenerateBriefingToolOnboardingContext:
    """Tests for GenerateBriefingTool._build_onboarding_context helper."""

    def test_build_onboarding_context_with_issues(self, state_with_onboarding_issues):
        """Test building onboarding context when issues are present."""
        tool = GenerateBriefingTool()
        
        context = tool._build_onboarding_context(state_with_onboarding_issues)
        
        assert context is not None
        assert "65/100" in context
        assert "MEDIUM_TRUST" in context
        assert "[ERROR]" in context
        assert "[WARNING]" in context
        assert "[INFO]" in context
        assert "coverage_miss" in context or "M4" in context
        assert "1 errors, 1 warnings, 1 info" in context

    def test_build_onboarding_context_without_issues(self, state_without_onboarding_issues):
        """Test building onboarding context when no issues are present."""
        tool = GenerateBriefingTool()
        
        context = tool._build_onboarding_context(state_without_onboarding_issues)
        
        # Should return None when no issues and no score
        assert context is None

    def test_build_onboarding_context_with_score_only(self, state_without_onboarding_issues):
        """Test building onboarding context when only score is present."""
        state_without_onboarding_issues.onboarding_score = 95
        state_without_onboarding_issues.onboarding_trust = "HIGH_TRUST"
        
        tool = GenerateBriefingTool()
        context = tool._build_onboarding_context(state_without_onboarding_issues)
        
        assert context is not None
        assert "95/100" in context
        assert "HIGH_TRUST" in context

    def test_build_onboarding_context_groups_by_severity(self, state_with_onboarding_issues):
        """Test that issues are grouped by severity (errors first, then warnings, then info)."""
        tool = GenerateBriefingTool()
        
        context = tool._build_onboarding_context(state_with_onboarding_issues)
        
        # Find positions of each severity
        error_pos = context.find("[ERROR]")
        warning_pos = context.find("[WARNING]")
        info_pos = context.find("[INFO]")
        
        # Errors should appear first, then warnings, then info
        assert error_pos < warning_pos
        assert warning_pos < info_pos

    def test_build_onboarding_context_includes_related_ids(self, state_with_onboarding_issues):
        """Test that related IDs are included in context."""
        tool = GenerateBriefingTool()
        
        context = tool._build_onboarding_context(state_with_onboarding_issues)
        
        # Check that related IDs appear in the context
        assert "M4" in context
        assert "J1" in context or "M2" in context
        assert "J2" in context


class TestGenerateBriefingToolExecution:
    """Tests for GenerateBriefingTool.execute with onboarding context."""

    def test_execute_passes_onboarding_context_to_agent(self, state_with_onboarding_issues):
        """Test that execute passes onboarding context to BriefingAgent."""
        mock_briefing = "# Factory Analysis Report\n\n## Onboarding Issues\nTest"
        
        # Patch at the source module where BriefingAgent is defined
        with patch("backend.agents.BriefingAgent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_briefing
            MockAgent.return_value = mock_instance
            
            tool = GenerateBriefingTool()
            result = tool.execute({}, state_with_onboarding_issues)
            
            assert result.success
            
            # Verify agent.run was called with onboarding_context
            call_kwargs = mock_instance.run.call_args.kwargs
            assert "onboarding_context" in call_kwargs
            assert call_kwargs["onboarding_context"] is not None
            assert "65/100" in call_kwargs["onboarding_context"]

    def test_execute_without_onboarding_issues(self, state_without_onboarding_issues):
        """Test that execute works without onboarding issues."""
        mock_briefing = "# Factory Analysis Report\n\n## Key Risks\nStandard"
        
        with patch("backend.agents.BriefingAgent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_briefing
            MockAgent.return_value = mock_instance
            
            tool = GenerateBriefingTool()
            result = tool.execute({}, state_without_onboarding_issues)
            
            assert result.success
            
            # onboarding_context should be None
            call_kwargs = mock_instance.run.call_args.kwargs
            assert call_kwargs.get("onboarding_context") is None

    def test_execute_output_includes_onboarding_stats(self, state_with_onboarding_issues):
        """Test that execute output includes onboarding statistics."""
        mock_briefing = "# Report"
        
        with patch("backend.agents.BriefingAgent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_briefing
            MockAgent.return_value = mock_instance
            
            tool = GenerateBriefingTool()
            result = tool.execute({}, state_with_onboarding_issues)
            
            assert result.success
            assert result.output["onboarding_issues_count"] == 3
            assert result.output["onboarding_score"] == 65
            assert result.output["onboarding_trust"] == "MEDIUM_TRUST"

    def test_execute_adds_onboarding_input_to_operation(self, state_with_onboarding_issues):
        """Test that execute adds onboarding context as input in data flow operation."""
        mock_briefing = "# Report"
        
        # Start a data flow step so add_operation works
        state_with_onboarding_issues.start_data_flow_step(
            step_id=0, step_type="generate_briefing", step_name="Test"
        )
        
        with patch("backend.agents.BriefingAgent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_briefing
            MockAgent.return_value = mock_instance
            
            tool = GenerateBriefingTool()
            tool.execute({}, state_with_onboarding_issues)
        
        # Check that the operation was added with onboarding_context input
        step = state_with_onboarding_issues._current_data_flow_step
        if step:
            ops = step.operations
            if ops:
                last_op = ops[-1]
                input_labels = [inp.label for inp in last_op.inputs]
                assert "onboarding_context" in input_labels


# =============================================================================
# ONBOARDING ISSUE MODEL TESTS
# =============================================================================

class TestOnboardingIssueModel:
    """Tests for OnboardingIssue model."""

    def test_create_onboarding_issue(self):
        """Test creating an OnboardingIssue."""
        issue = OnboardingIssue(
            type="coverage_miss",
            severity="warning",
            message="Machine M4 not found",
            related_ids=["M4"],
        )
        
        assert issue.type == "coverage_miss"
        assert issue.severity == "warning"
        assert issue.message == "Machine M4 not found"
        assert issue.related_ids == ["M4"]

    def test_onboarding_issue_without_related_ids(self):
        """Test creating OnboardingIssue without related_ids."""
        issue = OnboardingIssue(
            type="llm_disagreement",
            severity="info",
            message="Multiple passes produced different results",
        )
        
        assert issue.related_ids is None

    def test_agent_state_add_onboarding_issue_helper(self):
        """Test AgentState.add_onboarding_issue helper method."""
        state = AgentState(user_request="test")
        
        state.add_onboarding_issue(
            issue_type="coverage_miss",
            severity="warning",
            message="Test issue",
            related_ids=["M1"],
        )
        
        assert len(state.onboarding_issues) == 1
        assert state.onboarding_issues[0].type == "coverage_miss"
        assert state.onboarding_issues[0].severity == "warning"

    def test_agent_state_set_onboarding_score_helper(self):
        """Test AgentState.set_onboarding_score helper method."""
        state = AgentState(user_request="test")
        
        state.set_onboarding_score(85, "HIGH_TRUST")
        
        assert state.onboarding_score == 85
        assert state.onboarding_trust == "HIGH_TRUST"

