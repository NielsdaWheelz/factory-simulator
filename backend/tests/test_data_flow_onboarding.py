"""
Tests for PR5: Data Flow Integration with Onboarding Pipeline

Tests that the onboarding stages are correctly exposed in the data_flow
for AgentTrace visualization:
- Each onboarding stage creates a separate DataFlowStep
- Steps have correct IDs, types, and names
- Operations within steps have correct data previews
- Diagnostics summary step includes score and issue counts
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.agent_tools import ParseFactoryTool
from backend.agent_types import (
    AgentState,
    DataFlowStep,
    Operation,
    OperationType,
)
from backend.models import FactoryConfig, Machine, Job, Step
from backend.onboarding import (
    MultiPassResult,
    OnboardingPassResult,
    FactoryDiff,
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
        ],
        jobs=[
            Job(id="J1", name="Widget", steps=[
                Step(machine_id="M1", duration_hours=2),
                Step(machine_id="M2", duration_hours=3),
            ], due_time_hour=10),
        ],
    )


@pytest.fixture
def mock_multi_pass_success(sample_factory):
    """Return a successful MultiPassResult."""
    return MultiPassResult(
        primary_config=sample_factory,
        primary_mode="default",
        alt_configs=[],
        alt_modes=[],
        diffs=[],
        diff_summaries=[],
        all_pass_results=[
            OnboardingPassResult(
                mode="default",
                success=True,
                factory=sample_factory,
                normalization_warnings=[],
            ),
        ],
        alt_conflict_count=0,
    )


# =============================================================================
# Tests for DataFlowStep creation
# =============================================================================

class TestDataFlowOnboardingSteps:
    """Tests for onboarding DataFlowStep creation."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o0_explicit_id_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O0: Explicit ID Extraction step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O0 step
        o0_steps = [s for s in state.data_flow if s.step_id == -10]
        assert len(o0_steps) == 1
        
        o0 = o0_steps[0]
        assert o0.step_type == "onboarding_o0"
        assert "O0" in o0.step_name
        assert "Explicit ID" in o0.step_name
        assert o0.status == "done"
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o1_multi_pass_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O1: Multi-Pass Extraction step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O1 step
        o1_steps = [s for s in state.data_flow if s.step_id == -11]
        assert len(o1_steps) == 1
        
        o1 = o1_steps[0]
        assert o1.step_type == "onboarding_o1"
        assert "O1" in o1.step_name
        assert "Multi-Pass" in o1.step_name
        assert o1.status == "done"
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o2_validation_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O2: Validation & Normalization step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O2 step
        o2_steps = [s for s in state.data_flow if s.step_id == -12]
        assert len(o2_steps) == 1
        
        o2 = o2_steps[0]
        assert o2.step_type == "onboarding_o2"
        assert "O2" in o2.step_name
        assert "Validation" in o2.step_name
        assert o2.status == "done"
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o3_coverage_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O3: Coverage Assessment step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O3 step
        o3_steps = [s for s in state.data_flow if s.step_id == -13]
        assert len(o3_steps) == 1
        
        o3 = o3_steps[0]
        assert o3.step_type == "onboarding_o3"
        assert "O3" in o3.step_name
        assert "Coverage" in o3.step_name
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o4_consensus_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O4: Consensus & Alternatives step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O4 step
        o4_steps = [s for s in state.data_flow if s.step_id == -14]
        assert len(o4_steps) == 1
        
        o4 = o4_steps[0]
        assert o4.step_type == "onboarding_o4"
        assert "O4" in o4.step_name
        assert "Consensus" in o4.step_name
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_o5_diagnostics_step(self, mock_multi_pass, mock_multi_pass_success):
        """ParseFactoryTool should create O5: Diagnostics Summary step."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Find the O5 step
        o5_steps = [s for s in state.data_flow if s.step_id == -15]
        assert len(o5_steps) == 1
        
        o5 = o5_steps[0]
        assert o5.step_type == "onboarding_o5"
        assert "O5" in o5.step_name
        assert "Diagnostics" in o5.step_name
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_all_steps_created_in_order(self, mock_multi_pass, mock_multi_pass_success):
        """All onboarding steps should be created and in correct order."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        # Should have at least 6 steps (O0-O5)
        onboarding_steps = [s for s in state.data_flow if s.step_id <= -10]
        assert len(onboarding_steps) >= 6
        
        # Verify step IDs are in descending order (from -10 to -15)
        step_ids = [s.step_id for s in onboarding_steps]
        expected_ids = [-10, -11, -12, -13, -14, -15]
        assert step_ids == expected_ids


# =============================================================================
# Tests for Operations within steps
# =============================================================================

class TestDataFlowOperations:
    """Tests for operations within DataFlowSteps."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o0_has_extract_explicit_ids_operation(self, mock_multi_pass, mock_multi_pass_success):
        """O0 step should have extract_explicit_ids operation."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o0 = [s for s in state.data_flow if s.step_id == -10][0]
        
        # Should have at least one operation
        assert len(o0.operations) >= 1
        
        # First operation should be extract_explicit_ids
        op = o0.operations[0]
        assert op.name == "extract_explicit_ids"
        assert op.type == OperationType.FUNCTION
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o1_has_llm_operation(self, mock_multi_pass, mock_multi_pass_success):
        """O1 step should have LLM operation for multi-pass onboarding."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o1 = [s for s in state.data_flow if s.step_id == -11][0]
        
        # Should have at least one operation
        assert len(o1.operations) >= 1
        
        # Should have an LLM operation
        llm_ops = [op for op in o1.operations if op.type == OperationType.LLM]
        assert len(llm_ops) >= 1
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o3_has_coverage_operation(self, mock_multi_pass, mock_multi_pass_success):
        """O3 step should have assess_coverage operation."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o3 = [s for s in state.data_flow if s.step_id == -13][0]
        
        # Should have assess_coverage operation
        coverage_ops = [op for op in o3.operations if op.name == "assess_coverage"]
        assert len(coverage_ops) == 1
        assert coverage_ops[0].type == OperationType.VALIDATION
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o5_has_score_operation(self, mock_multi_pass, mock_multi_pass_success):
        """O5 step should have compute_onboarding_score operation."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o5 = [s for s in state.data_flow if s.step_id == -15][0]
        
        # Should have compute_onboarding_score operation
        score_ops = [op for op in o5.operations if op.name == "compute_onboarding_score"]
        assert len(score_ops) == 1


# =============================================================================
# Tests for scratchpad entries
# =============================================================================

class TestScratchpadOnboardingEntries:
    """Tests for onboarding stage markers in scratchpad."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_scratchpad_has_o0_entry(self, mock_multi_pass, mock_multi_pass_success):
        """Scratchpad should have O0 stage marker."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o0_entries = [e for e in state.scratchpad if "O0:" in e]
        assert len(o0_entries) >= 1
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_scratchpad_has_o1_entry(self, mock_multi_pass, mock_multi_pass_success):
        """Scratchpad should have O1 stage marker."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o1_entries = [e for e in state.scratchpad if "O1:" in e]
        assert len(o1_entries) >= 1
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_scratchpad_has_diagnostics_entry(self, mock_multi_pass, mock_multi_pass_success):
        """Scratchpad should have O5 diagnostics summary."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o5_entries = [e for e in state.scratchpad if "O5:" in e]
        assert len(o5_entries) >= 1
        
        # Should include score
        assert any("score=" in e for e in o5_entries)


# =============================================================================
# Tests for failure cases
# =============================================================================

class TestDataFlowOnFailure:
    """Tests for data flow when onboarding fails."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_creates_steps_on_extraction_failure(self, mock_multi_pass):
        """Should create data flow steps even when extraction fails."""
        # Mock all passes failing
        mock_multi_pass.return_value = MultiPassResult(
            primary_config=None,
            all_pass_results=[
                OnboardingPassResult(mode="default", success=False, error="LLM error"),
                OnboardingPassResult(mode="conservative", success=False, error="LLM error 2"),
            ],
        )
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "invalid"}, state)
        
        # Should still have O0 step
        o0_steps = [s for s in state.data_flow if s.step_id == -10]
        assert len(o0_steps) >= 1
        
        # Should still have O1 step (with failed status)
        o1_steps = [s for s in state.data_flow if s.step_id == -11]
        assert len(o1_steps) >= 1
        
        # O1 should be marked as failed
        assert o1_steps[0].status == "failed"
        
        # Should have diagnostics summary step
        o5_steps = [s for s in state.data_flow if s.step_id == -15]
        assert len(o5_steps) >= 1


# =============================================================================
# Tests for step outputs
# =============================================================================

class TestDataFlowStepOutputs:
    """Tests for DataFlowStep outputs."""
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o0_output_includes_ids_found(self, mock_multi_pass, mock_multi_pass_success):
        """O0 step output should include number of IDs found."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o0 = [s for s in state.data_flow if s.step_id == -10][0]
        
        # Step output should exist
        assert o0.step_output is not None
        assert "machine" in o0.step_output.preview.lower() or "job" in o0.step_output.preview.lower()
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o1_output_includes_factory_summary(self, mock_multi_pass, mock_multi_pass_success):
        """O1 step output should include factory summary."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o1 = [s for s in state.data_flow if s.step_id == -11][0]
        
        # Step output should include machine/job info
        assert o1.step_output is not None
        assert "machine" in o1.step_output.preview.lower() or "M1" in o1.step_output.preview
    
    @patch('backend.agent_tools.run_multi_pass_onboarding')
    def test_o5_output_includes_score(self, mock_multi_pass, mock_multi_pass_success):
        """O5 step output should include onboarding score."""
        mock_multi_pass.return_value = mock_multi_pass_success
        
        state = AgentState(user_request="test")
        tool = ParseFactoryTool()
        
        result = tool.execute({"description": "M1 assembly, M2 drill. J1 widget."}, state)
        
        o5 = [s for s in state.data_flow if s.step_id == -15][0]
        
        # Step output should include score
        assert o5.step_output is not None
        assert "score=" in o5.step_output.preview.lower()

