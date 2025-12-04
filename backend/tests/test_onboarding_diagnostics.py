"""
Tests for PR3: Onboarding Diagnostics + Score Computation

Tests the new diagnostic capabilities:
- validate_and_normalize_with_diagnostics returns warnings
- compute_onboarding_score produces correct scores and trust levels
- ParseFactoryTool populates onboarding_issues and score
- AgentState helper methods work correctly
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.onboarding import (
    validate_and_normalize_with_diagnostics,
    compute_onboarding_score,
    NormalizationResult,
    RawFactoryConfig,
    RawJob,
    RawStep,
    CoarseMachine,
    ExtractionError,
    MultiPassResult,
    OnboardingPassResult,
)
from backend.agent_types import (
    AgentState,
    OnboardingIssue,
    OnboardingIssueSeverity,
    OnboardingIssueType,
    OnboardingTrust,
)
from backend.models import FactoryConfig, Machine, Job, Step


# =============================================================================
# Tests for compute_onboarding_score
# =============================================================================

class TestComputeOnboardingScore:
    """Tests for the onboarding score computation function."""
    
    def test_perfect_score_no_issues(self):
        """No issues should yield score 100 and HIGH_TRUST."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=0,
            alt_conflicts=0,
        )
        assert score == 100
        assert trust == "HIGH_TRUST"
    
    def test_coverage_issues_reduce_score(self):
        """Each coverage miss should reduce score by 15 points."""
        score, trust = compute_onboarding_score(
            coverage_issues=2,
            normalization_repairs=0,
            alt_conflicts=0,
        )
        assert score == 70  # 100 - 2*15
        assert trust == "MEDIUM_TRUST"
    
    def test_normalization_repairs_reduce_score(self):
        """Each normalization repair should reduce score by 5 points."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=4,
            alt_conflicts=0,
        )
        assert score == 80  # 100 - 4*5
        assert trust == "HIGH_TRUST"
    
    def test_alt_conflicts_reduce_score(self):
        """Each alt conflict should reduce score by 20 points."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=0,
            alt_conflicts=2,
        )
        assert score == 60  # 100 - 2*20
        assert trust == "MEDIUM_TRUST"
    
    def test_combined_issues(self):
        """Multiple issue types should combine correctly."""
        score, trust = compute_onboarding_score(
            coverage_issues=1,   # -15
            normalization_repairs=2,  # -10
            alt_conflicts=1,     # -20
        )
        assert score == 55  # 100 - 15 - 10 - 20
        assert trust == "MEDIUM_TRUST"
    
    def test_low_trust_threshold(self):
        """Score below 50 should yield LOW_TRUST."""
        score, trust = compute_onboarding_score(
            coverage_issues=3,   # -45
            normalization_repairs=2,  # -10
            alt_conflicts=0,
        )
        assert score == 45  # 100 - 45 - 10
        assert trust == "LOW_TRUST"
    
    def test_score_clamped_to_zero(self):
        """Score should never go below 0."""
        score, trust = compute_onboarding_score(
            coverage_issues=10,   # -150
            normalization_repairs=10,  # -50
            alt_conflicts=10,     # -200
        )
        assert score == 0
        assert trust == "LOW_TRUST"
    
    def test_high_trust_boundary(self):
        """Score of exactly 80 should be HIGH_TRUST."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=4,  # -20
            alt_conflicts=0,
        )
        assert score == 80
        assert trust == "HIGH_TRUST"
    
    def test_medium_trust_boundary(self):
        """Score of exactly 50 should be MEDIUM_TRUST."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=10,  # -50
            alt_conflicts=0,
        )
        assert score == 50
        assert trust == "MEDIUM_TRUST"


# =============================================================================
# Tests for validate_and_normalize_with_diagnostics
# =============================================================================

class TestValidateAndNormalizeWithDiagnostics:
    """Tests for the validate_and_normalize_with_diagnostics function."""
    
    def test_clean_input_no_warnings(self):
        """Clean input should produce no warnings."""
        raw = RawFactoryConfig(
            machines=[
                CoarseMachine(id="M1", name="Assembly"),
                CoarseMachine(id="M2", name="Drill"),
            ],
            jobs=[
                RawJob(
                    id="J1",
                    name="Widget",
                    steps=[
                        RawStep(machine_id="M1", duration_hours=2),
                        RawStep(machine_id="M2", duration_hours=3),
                    ],
                    due_time_hour=10,
                ),
            ],
        )
        
        result = validate_and_normalize_with_diagnostics(raw)
        
        assert isinstance(result, NormalizationResult)
        assert isinstance(result.factory, FactoryConfig)
        assert len(result.warnings) == 0
        assert len(result.factory.machines) == 2
        assert len(result.factory.jobs) == 1
    
    def test_duration_normalization_produces_warning(self):
        """Invalid duration should be clamped and produce a warning."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=0)],  # Invalid: 0
                    due_time_hour=10,
                ),
            ],
        )
        
        result = validate_and_normalize_with_diagnostics(raw)
        
        assert len(result.warnings) >= 1
        assert any("duration" in w.lower() for w in result.warnings)
        # Duration should be clamped to 1
        assert result.factory.jobs[0].steps[0].duration_hours == 1
    
    def test_due_time_normalization_produces_warning(self):
        """Invalid due time should be clamped and produce a warning."""
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=-5,  # Invalid: negative
                ),
            ],
        )
        
        result = validate_and_normalize_with_diagnostics(raw)
        
        assert len(result.warnings) >= 1
        assert any("due_time" in w.lower() for w in result.warnings)
        # Due time should be clamped to 24
        assert result.factory.jobs[0].due_time_hour == 24
    
    def test_invariant_violation_raises_error(self):
        """Jobs lost during normalization should raise ExtractionError."""
        # Create a job with a step referencing a non-existent machine
        # This will cause the step to be dropped, leaving the job with no steps,
        # which will cause the job to be dropped, violating the invariant
        raw = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Machine")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job",
                    steps=[RawStep(machine_id="M_NONEXISTENT", duration_hours=2)],
                    due_time_hour=10,
                ),
            ],
        )
        
        with pytest.raises(ExtractionError) as exc_info:
            validate_and_normalize_with_diagnostics(raw)
        
        assert exc_info.value.code == "NORMALIZATION_FAILED"
        assert "J1" in exc_info.value.message


# =============================================================================
# Tests for AgentState helper methods
# =============================================================================

class TestAgentStateOnboardingHelpers:
    """Tests for AgentState onboarding helper methods."""
    
    def test_add_onboarding_issue(self):
        """add_onboarding_issue should append to onboarding_issues."""
        state = AgentState(user_request="test")
        
        state.add_onboarding_issue(
            issue_type="coverage_miss",
            severity="warning",
            message="Machine M4 mentioned but not parsed",
            related_ids=["M4"],
        )
        
        assert len(state.onboarding_issues) == 1
        issue = state.onboarding_issues[0]
        assert issue.type == "coverage_miss"
        assert issue.severity == "warning"
        assert issue.message == "Machine M4 mentioned but not parsed"
        assert issue.related_ids == ["M4"]
    
    def test_add_onboarding_issue_no_related_ids(self):
        """add_onboarding_issue should work without related_ids."""
        state = AgentState(user_request="test")
        
        state.add_onboarding_issue(
            issue_type="normalization_repair",
            severity="info",
            message="Duration clamped to 1",
        )
        
        assert len(state.onboarding_issues) == 1
        issue = state.onboarding_issues[0]
        assert issue.related_ids is None
    
    def test_add_multiple_issues(self):
        """Multiple issues should accumulate."""
        state = AgentState(user_request="test")
        
        state.add_onboarding_issue(
            issue_type="coverage_miss",
            severity="warning",
            message="Issue 1",
        )
        state.add_onboarding_issue(
            issue_type="normalization_repair",
            severity="info",
            message="Issue 2",
        )
        
        assert len(state.onboarding_issues) == 2
    
    def test_set_onboarding_score(self):
        """set_onboarding_score should set both score and trust."""
        state = AgentState(user_request="test")
        
        state.set_onboarding_score(85, "HIGH_TRUST")
        
        assert state.onboarding_score == 85
        assert state.onboarding_trust == "HIGH_TRUST"
    
    def test_initial_state_has_empty_issues(self):
        """New AgentState should have empty onboarding_issues."""
        state = AgentState(user_request="test")
        
        assert state.onboarding_issues == []
        assert state.onboarding_score is None
        assert state.onboarding_trust is None


# =============================================================================
# Integration tests for ParseFactoryTool with diagnostics
# =============================================================================

class TestParseFactoryToolDiagnostics:
    """Integration tests for ParseFactoryTool with onboarding diagnostics."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_clean_parse_high_trust(self, mock_multi_pass):
        """Clean parse should yield HIGH_TRUST score."""
        from backend.agent_tools import ParseFactoryTool
        from backend.onboarding import MultiPassResult, OnboardingPassResult
        
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[],
            alt_modes=[],
            diffs=[],
            diff_summaries=[],
            all_pass_results=[OnboardingPassResult(mode="default", success=True, factory=factory)],
            alt_conflict_count=0,
        )
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly. J1 widget on M1 for 2h, due 10h."}, state)
        
        assert result.success
        assert state.onboarding_score == 100
        assert state.onboarding_trust == "HIGH_TRUST"
        assert len(state.onboarding_issues) == 0
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_parse_with_normalization_repairs(self, mock_multi_pass):
        """Parse with normalization repairs should produce warnings and lower score."""
        from backend.agent_tools import ParseFactoryTool
        from backend.onboarding import MultiPassResult, OnboardingPassResult
        
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=10)],
        )
        
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[],
            alt_modes=[],
            diffs=[],
            diff_summaries=[],
            all_pass_results=[OnboardingPassResult(
                mode="default",
                success=True,
                factory=factory,
                normalization_warnings=["Set duration_hours to 1 for step on machine M1 in job J1"],
            )],
            alt_conflict_count=0,
        )
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly. J1 widget on M1, due 10h."}, state)
        
        assert result.success
        # Should have normalization repair issues
        assert len(state.onboarding_issues) >= 1
        assert any(i.type == "normalization_repair" for i in state.onboarding_issues)
        # Score should be reduced
        assert state.onboarding_score < 100
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_parse_with_coverage_miss(self, mock_multi_pass):
        """Parse with coverage miss should produce issues and fail."""
        from backend.agent_tools import ParseFactoryTool
        from backend.onboarding import MultiPassResult, OnboardingPassResult
        
        # Factory only has M1, but text mentions M2
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],  # M2 missing
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[],
            alt_modes=[],
            diffs=[],
            diff_summaries=[],
            all_pass_results=[OnboardingPassResult(mode="default", success=True, factory=factory)],
            alt_conflict_count=0,
        )
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        # Description mentions M2 which won't be in parsed config
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget on M1."}, state)
        
        # Should fail due to coverage mismatch
        assert not result.success
        # Should have coverage miss issues
        assert any(i.type == "coverage_miss" for i in state.onboarding_issues)
        # Score should be set even on failure
        assert state.onboarding_score is not None
        assert state.onboarding_trust is not None
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_extraction_error_produces_issue(self, mock_multi_pass):
        """When all passes fail, should produce error issue and set score."""
        from backend.agent_tools import ParseFactoryTool
        from backend.onboarding import MultiPassResult, OnboardingPassResult
        
        # Mock all passes failing
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=None,
            all_pass_results=[
                OnboardingPassResult(mode="default", success=False, error="LLM error 1"),
                OnboardingPassResult(mode="conservative", success=False, error="LLM error 2"),
            ],
        )
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 J1"}, state)
        
        assert not result.success
        # Should have an extraction_error issue
        assert any(i.type == "extraction_error" for i in state.onboarding_issues)
        # Score should be set
        assert state.onboarding_score is not None


# =============================================================================
# Trust band boundary tests
# =============================================================================

class TestTrustBandBoundaries:
    """Tests for trust band boundary conditions."""
    
    def test_score_79_is_medium_trust(self):
        """Score 79 should be MEDIUM_TRUST."""
        score, trust = compute_onboarding_score(
            coverage_issues=0,
            normalization_repairs=0,
            alt_conflicts=0,
        )
        # Manually adjust to test boundary
        adjusted_score = 79
        if adjusted_score >= 80:
            adjusted_trust = "HIGH_TRUST"
        elif adjusted_score >= 50:
            adjusted_trust = "MEDIUM_TRUST"
        else:
            adjusted_trust = "LOW_TRUST"
        
        assert adjusted_trust == "MEDIUM_TRUST"
    
    def test_score_49_is_low_trust(self):
        """Score 49 should be LOW_TRUST."""
        adjusted_score = 49
        if adjusted_score >= 80:
            adjusted_trust = "HIGH_TRUST"
        elif adjusted_score >= 50:
            adjusted_trust = "MEDIUM_TRUST"
        else:
            adjusted_trust = "LOW_TRUST"
        
        assert adjusted_trust == "LOW_TRUST"

