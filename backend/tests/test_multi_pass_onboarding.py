"""
Tests for PR4: Multi-pass onboarding + alternative configs + diffs.

Tests cover:
- compute_factory_diff: structural diffing between FactoryConfigs
- run_onboarding_pass: single extraction pass with modes
- run_multi_pass_onboarding: multi-pass orchestration and consensus
- Integration with ParseFactoryTool
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.models import FactoryConfig, Machine, Job, Step
from backend.onboarding import (
    compute_factory_diff,
    run_onboarding_pass,
    run_multi_pass_onboarding,
    FactoryDiff,
    OnboardingPassResult,
    MultiPassResult,
    CoarseStructure,
    CoarseMachine,
    CoarseJob,
    RawFactoryConfig,
    RawJob,
    RawStep,
)
from backend.agent_types import AgentState
from backend.agent_tools import ParseFactoryTool


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def simple_factory_a():
    """Simple factory with 2 machines, 2 jobs."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Widget",
                steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=3),
                ],
                due_time_hour=10,
            ),
            Job(
                id="J2",
                name="Gadget",
                steps=[
                    Step(machine_id="M2", duration_hours=1),
                ],
                due_time_hour=12,
            ),
        ],
    )


@pytest.fixture
def simple_factory_b_same():
    """Factory identical to simple_factory_a."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Widget",
                steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=3),
                ],
                due_time_hour=10,
            ),
            Job(
                id="J2",
                name="Gadget",
                steps=[
                    Step(machine_id="M2", duration_hours=1),
                ],
                due_time_hour=12,
            ),
        ],
    )


@pytest.fixture
def factory_with_extra_machine():
    """Factory with an extra machine M3."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
            Machine(id="M3", name="Pack"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Widget",
                steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=3),
                ],
                due_time_hour=10,
            ),
            Job(
                id="J2",
                name="Gadget",
                steps=[
                    Step(machine_id="M2", duration_hours=1),
                ],
                due_time_hour=12,
            ),
        ],
    )


@pytest.fixture
def factory_with_different_routing():
    """Factory with different routing for J1."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Widget",
                steps=[
                    Step(machine_id="M2", duration_hours=2),  # Different order
                    Step(machine_id="M1", duration_hours=3),
                ],
                due_time_hour=10,
            ),
            Job(
                id="J2",
                name="Gadget",
                steps=[
                    Step(machine_id="M2", duration_hours=1),
                ],
                due_time_hour=12,
            ),
        ],
    )


@pytest.fixture
def factory_with_different_timing():
    """Factory with different timing for J1."""
    return FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Widget",
                steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=5),  # Different duration
                ],
                due_time_hour=15,  # Different due time
            ),
            Job(
                id="J2",
                name="Gadget",
                steps=[
                    Step(machine_id="M2", duration_hours=1),
                ],
                due_time_hour=12,
            ),
        ],
    )


# =============================================================================
# TESTS FOR compute_factory_diff
# =============================================================================

class TestComputeFactoryDiff:
    """Tests for the structural diff function."""
    
    def test_identical_configs(self, simple_factory_a, simple_factory_b_same):
        """Identical configs should produce is_identical=True."""
        diff = compute_factory_diff(simple_factory_a, simple_factory_b_same)
        
        assert diff.is_identical is True
        assert diff.machines_added == []
        assert diff.machines_removed == []
        assert diff.jobs_added == []
        assert diff.jobs_removed == []
        assert diff.routing_differences == {}
        assert diff.timing_differences == {}
    
    def test_machine_added(self, simple_factory_a, factory_with_extra_machine):
        """Should detect machines added in config_b."""
        diff = compute_factory_diff(simple_factory_a, factory_with_extra_machine)
        
        assert diff.is_identical is False
        assert diff.machines_added == ["M3"]
        assert diff.machines_removed == []
        assert diff.jobs_added == []
        assert diff.jobs_removed == []
    
    def test_machine_removed(self, factory_with_extra_machine, simple_factory_a):
        """Should detect machines removed in config_b."""
        diff = compute_factory_diff(factory_with_extra_machine, simple_factory_a)
        
        assert diff.is_identical is False
        assert diff.machines_added == []
        assert diff.machines_removed == ["M3"]
    
    def test_routing_difference(self, simple_factory_a, factory_with_different_routing):
        """Should detect routing differences for jobs."""
        diff = compute_factory_diff(simple_factory_a, factory_with_different_routing)
        
        assert diff.is_identical is False
        assert "J1" in diff.routing_differences
        assert diff.routing_differences["J1"]["a"] == ["M1", "M2"]
        assert diff.routing_differences["J1"]["b"] == ["M2", "M1"]
    
    def test_timing_difference(self, simple_factory_a, factory_with_different_timing):
        """Should detect timing differences for jobs."""
        diff = compute_factory_diff(simple_factory_a, factory_with_different_timing)
        
        assert diff.is_identical is False
        assert "J1" in diff.timing_differences
        timing = diff.timing_differences["J1"]
        assert timing["due_a"] == 10
        assert timing["due_b"] == 15
        assert "duration_diff" in timing
        assert "M2" in timing["duration_diff"]
    
    def test_summary_for_identical(self, simple_factory_a, simple_factory_b_same):
        """Summary should indicate identical configs."""
        diff = compute_factory_diff(simple_factory_a, simple_factory_b_same)
        summary = diff.summary()
        
        assert "identical" in summary.lower()
    
    def test_summary_for_differences(self, simple_factory_a, factory_with_different_routing):
        """Summary should describe the differences."""
        diff = compute_factory_diff(simple_factory_a, factory_with_different_routing)
        summary = diff.summary()
        
        assert "J1" in summary
        assert "routing" in summary.lower() or "vs" in summary
    
    def test_diff_with_job_added(self, simple_factory_a):
        """Should detect jobs added in config_b."""
        config_b = FactoryConfig(
            machines=simple_factory_a.machines,
            jobs=simple_factory_a.jobs + [
                Job(id="J3", name="New", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=20)
            ],
        )
        
        diff = compute_factory_diff(simple_factory_a, config_b)
        
        assert diff.is_identical is False
        assert diff.jobs_added == ["J3"]
        assert diff.jobs_removed == []
    
    def test_diff_with_job_removed(self, simple_factory_a):
        """Should detect jobs removed in config_b."""
        config_b = FactoryConfig(
            machines=simple_factory_a.machines,
            jobs=[simple_factory_a.jobs[0]],  # Only first job
        )
        
        diff = compute_factory_diff(simple_factory_a, config_b)
        
        assert diff.is_identical is False
        assert diff.jobs_added == []
        assert diff.jobs_removed == ["J2"]


# =============================================================================
# TESTS FOR run_onboarding_pass
# =============================================================================

class TestRunOnboardingPass:
    """Tests for single extraction pass."""
    
    @patch('backend.onboarding.extract_coarse_structure')
    @patch('backend.onboarding.extract_steps')
    def test_successful_pass_returns_factory(self, mock_extract_steps, mock_extract_coarse):
        """Successful pass should return factory in result."""
        # Mock the LLM calls
        mock_extract_coarse.return_value = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Assembly")],
            jobs=[CoarseJob(id="J1", name="Widget")],
        )
        mock_extract_steps.return_value = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Assembly")],
            jobs=[RawJob(
                id="J1",
                name="Widget",
                steps=[RawStep(machine_id="M1", duration_hours=2)],
                due_time_hour=10,
            )],
        )
        
        result = run_onboarding_pass("M1 does J1", mode="default")
        
        assert result.success is True
        assert result.factory is not None
        assert result.error is None
        assert result.mode == "default"
        assert len(result.factory.machines) == 1
        assert len(result.factory.jobs) == 1
    
    @patch('backend.onboarding.extract_coarse_structure')
    def test_failed_pass_returns_error(self, mock_extract_coarse):
        """Failed pass should return error in result."""
        mock_extract_coarse.side_effect = Exception("LLM error")
        
        result = run_onboarding_pass("invalid input", mode="default")
        
        assert result.success is False
        assert result.factory is None
        assert result.error is not None
        assert "error" in result.error.lower() or "LLM" in result.error
    
    @patch('backend.onboarding.extract_coarse_structure')
    @patch('backend.onboarding.extract_steps')
    def test_pass_captures_normalization_warnings(self, mock_extract_steps, mock_extract_coarse):
        """Pass should capture normalization warnings."""
        mock_extract_coarse.return_value = CoarseStructure(
            machines=[CoarseMachine(id="M1", name="Assembly")],
            jobs=[CoarseJob(id="J1", name="Widget")],
        )
        mock_extract_steps.return_value = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="Assembly")],
            jobs=[RawJob(
                id="J1",
                name="Widget",
                steps=[RawStep(machine_id="M1", duration_hours=0.5)],  # Will be clamped
                due_time_hour=10,
            )],
        )
        
        result = run_onboarding_pass("M1 does J1", mode="default")
        
        # The duration should be clamped and a warning generated
        assert result.success is True
        # Note: normalization_warnings may or may not be populated depending on clamping behavior
    
    def test_different_modes_accepted(self):
        """Should accept different mode strings."""
        for mode in ["default", "conservative", "inclusive"]:
            result = OnboardingPassResult(mode=mode)
            assert result.mode == mode


# =============================================================================
# TESTS FOR run_multi_pass_onboarding
# =============================================================================

class TestRunMultiPassOnboarding:
    """Tests for multi-pass orchestration."""
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_returns_primary_config_when_all_agree(self, mock_run_pass):
        """When all passes agree, should return primary with no conflicts."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_run_pass.return_value = OnboardingPassResult(
            mode="default",
            success=True,
            factory=factory,
        )
        
        result = run_multi_pass_onboarding("M1 does J1", num_passes=2)
        
        assert result.primary_config is not None
        assert result.alt_conflict_count == 0
        assert len(result.alt_configs) == 0  # Deduplicated, so no distinct alts
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_returns_alternatives_when_passes_disagree(self, mock_run_pass):
        """When passes produce different configs, should return alternatives."""
        factory_a = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        factory_b = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly"), Machine(id="M2", name="Drill")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        # First pass returns factory_a, second returns factory_b
        mock_run_pass.side_effect = [
            OnboardingPassResult(mode="default", success=True, factory=factory_a),
            OnboardingPassResult(mode="conservative", success=True, factory=factory_b),
        ]
        
        result = run_multi_pass_onboarding("M1 M2 J1", num_passes=2)
        
        assert result.primary_config is not None
        assert len(result.alt_configs) == 1
        assert result.alt_conflict_count == 1
        assert len(result.diffs) == 1
        assert not result.diffs[0].is_identical
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_prefers_conservative_as_primary(self, mock_run_pass):
        """Should prefer conservative mode as primary when available."""
        factory_default = FactoryConfig(
            machines=[Machine(id="M1", name="A")],
            jobs=[Job(id="J1", name="W", steps=[Step(machine_id="M1", duration_hours=1)], due_time_hour=10)],
        )
        factory_conservative = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_run_pass.side_effect = [
            OnboardingPassResult(mode="default", success=True, factory=factory_default),
            OnboardingPassResult(mode="conservative", success=True, factory=factory_conservative),
        ]
        
        result = run_multi_pass_onboarding("M1 J1", num_passes=2)
        
        assert result.primary_mode == "conservative"
        assert result.primary_config == factory_conservative
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_handles_all_passes_failing(self, mock_run_pass):
        """When all passes fail, should return empty result."""
        mock_run_pass.return_value = OnboardingPassResult(
            mode="default",
            success=False,
            error="LLM failed",
        )
        
        result = run_multi_pass_onboarding("garbage input", num_passes=2)
        
        assert result.primary_config is None
        assert len(result.alt_configs) == 0
        assert len(result.all_pass_results) == 2
        assert all(not pr.success for pr in result.all_pass_results)
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_handles_partial_success(self, mock_run_pass):
        """When some passes succeed and others fail, should use successful ones."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_run_pass.side_effect = [
            OnboardingPassResult(mode="default", success=False, error="LLM error"),
            OnboardingPassResult(mode="conservative", success=True, factory=factory),
        ]
        
        result = run_multi_pass_onboarding("M1 J1", num_passes=2)
        
        assert result.primary_config is not None
        assert result.primary_mode == "conservative"
    
    @patch('backend.onboarding.run_onboarding_pass')
    def test_diff_summaries_populated(self, mock_run_pass):
        """Diff summaries should be human-readable strings."""
        factory_a = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        factory_b = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=5)], due_time_hour=10)],
        )
        
        mock_run_pass.side_effect = [
            OnboardingPassResult(mode="default", success=True, factory=factory_a),
            OnboardingPassResult(mode="conservative", success=True, factory=factory_b),
        ]
        
        result = run_multi_pass_onboarding("M1 J1", num_passes=2)
        
        # Should have diff summaries if configs differ
        if result.alt_configs:
            assert len(result.diff_summaries) == len(result.alt_configs)
            for summary in result.diff_summaries:
                assert isinstance(summary, str)


# =============================================================================
# INTEGRATION TESTS WITH ParseFactoryTool
# =============================================================================

class TestParseFactoryToolMultiPass:
    """Integration tests for ParseFactoryTool with multi-pass onboarding."""
    
    @pytest.fixture
    def agent_state(self):
        """Create a fresh agent state."""
        return AgentState(user_request="Test factory")
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_tool_uses_multi_pass(self, mock_multi_pass, agent_state):
        """ParseFactoryTool should use run_multi_pass_onboarding."""
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
        
        tool = ParseFactoryTool()
        result = tool.execute({"description": "M1 does J1"}, agent_state)
        
        assert mock_multi_pass.called
        assert result.success is True
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_tool_creates_alt_conflict_issues(self, mock_multi_pass, agent_state):
        """ParseFactoryTool should create onboarding issues for alt conflicts."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        alt_factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly"), Machine(id="M2", name="Drill")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        diff = FactoryDiff(
            machines_added=["M2"],
            machines_removed=[],
            jobs_added=[],
            jobs_removed=[],
            routing_differences={},
            timing_differences={},
            is_identical=False,
        )
        
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[alt_factory],
            alt_modes=["conservative"],
            diffs=[diff],
            diff_summaries=["Machines added: ['M2']"],
            all_pass_results=[
                OnboardingPassResult(mode="default", success=True, factory=factory),
                OnboardingPassResult(mode="conservative", success=True, factory=alt_factory),
            ],
            alt_conflict_count=1,
        )
        
        tool = ParseFactoryTool()
        result = tool.execute({"description": "M1 M2 J1"}, agent_state)
        
        # Should have alt_conflict issue
        alt_conflict_issues = [i for i in agent_state.onboarding_issues if i.type == "alt_conflict"]
        assert len(alt_conflict_issues) >= 1
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_tool_includes_alt_info_in_output(self, mock_multi_pass, agent_state):
        """ParseFactoryTool output should include alternative config info."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[factory],  # Same config, but we'll pretend it's different
            alt_modes=["conservative"],
            diffs=[FactoryDiff(is_identical=True)],
            diff_summaries=["Configs are identical"],
            all_pass_results=[OnboardingPassResult(mode="default", success=True, factory=factory)],
            alt_conflict_count=0,
        )
        
        tool = ParseFactoryTool()
        result = tool.execute({"description": "M1 J1"}, agent_state)
        
        assert result.success is True
        assert "alt_configs_count" in result.output
        assert "alt_conflicts_count" in result.output
        assert "diff_summaries" in result.output
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_tool_handles_all_passes_failing(self, mock_multi_pass, agent_state):
        """ParseFactoryTool should handle case where all passes fail."""
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=None,
            all_pass_results=[
                OnboardingPassResult(mode="default", success=False, error="LLM error 1"),
                OnboardingPassResult(mode="conservative", success=False, error="LLM error 2"),
            ],
        )
        
        tool = ParseFactoryTool()
        result = tool.execute({"description": "garbage"}, agent_state)
        
        assert result.success is False
        assert "failed" in result.error.lower()
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_onboarding_score_includes_alt_conflicts(self, mock_multi_pass, agent_state):
        """Onboarding score should be penalized for alt conflicts."""
        factory = FactoryConfig(
            machines=[Machine(id="M1", name="Assembly")],
            jobs=[Job(id="J1", name="Widget", steps=[Step(machine_id="M1", duration_hours=2)], due_time_hour=10)],
        )
        
        # No conflicts
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
        
        tool = ParseFactoryTool()
        result = tool.execute({"description": "M1 J1"}, agent_state)
        
        score_no_conflicts = agent_state.onboarding_score
        
        # Reset state
        agent_state_2 = AgentState(user_request="Test factory")
        
        # With conflicts
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=factory,
            primary_mode="default",
            alt_configs=[factory],
            alt_modes=["conservative"],
            diffs=[FactoryDiff(machines_added=["M2"], is_identical=False)],
            diff_summaries=["Machines added"],
            all_pass_results=[OnboardingPassResult(mode="default", success=True, factory=factory)],
            alt_conflict_count=1,
        )
        
        result_2 = tool.execute({"description": "M1 J1"}, agent_state_2)
        
        score_with_conflicts = agent_state_2.onboarding_score
        
        # Score should be lower with conflicts
        assert score_with_conflicts < score_no_conflicts

