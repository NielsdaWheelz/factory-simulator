"""
Tests for the SOTA agent engine with plan-based execution.

Tests cover:
- Planning phase: Plan generation and validation
- Execution phase: Step execution and state updates
- Error handling: Error taxonomy and recovery
- Budget enforcement: LLM call and step limits
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.agent_engine import (
    run_agent,
    _generate_plan,
    _get_canonical_plan,
    _execute_plan_step,
    _synthesize_partial_answer,
)
from backend.agent_types import (
    AgentState,
    AgentStatus,
    PlanStep,
    PlanStepType,
    ErrorType,
    ErrorInfo,
)
from backend.agent_tools import create_default_registry
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
def registry():
    """Return default tool registry."""
    return create_default_registry()


# =============================================================================
# PLANNING TESTS
# =============================================================================

class TestPlanning:
    """Tests for the planning phase."""

    def test_canonical_plan_has_expected_steps(self):
        """Test that canonical plan includes ensure_factory, baseline, and briefing."""
        state = AgentState(user_request="Analyze my factory")
        plan = _get_canonical_plan(state)
        
        step_types = [s.type for s in plan]
        assert PlanStepType.ENSURE_FACTORY in step_types
        assert PlanStepType.SIMULATE_BASELINE in step_types
        assert PlanStepType.GENERATE_BRIEFING in step_types

    def test_canonical_plan_adds_rush_for_rush_request(self):
        """Test that canonical plan adds rush step for rush-related requests."""
        state = AgentState(user_request="Rush J1 and analyze")
        plan = _get_canonical_plan(state)
        
        step_types = [s.type for s in plan]
        assert PlanStepType.SIMULATE_RUSH in step_types

    def test_canonical_plan_no_rush_for_normal_request(self):
        """Test that canonical plan doesn't add rush for normal requests."""
        state = AgentState(user_request="Analyze my factory baseline")
        plan = _get_canonical_plan(state)
        
        step_types = [s.type for s in plan]
        assert PlanStepType.SIMULATE_RUSH not in step_types

    def test_plan_steps_have_sequential_ids(self):
        """Test that plan steps have sequential IDs starting from 0."""
        state = AgentState(user_request="test")
        plan = _get_canonical_plan(state)
        
        ids = [s.id for s in plan]
        assert ids == list(range(len(plan)))

    def test_plan_steps_start_as_pending(self):
        """Test that all plan steps start with pending status."""
        state = AgentState(user_request="test")
        plan = _get_canonical_plan(state)
        
        for step in plan:
            assert step.status == "pending"


# =============================================================================
# STATE MANAGEMENT TESTS
# =============================================================================

class TestStateManagement:
    """Tests for AgentState plan management."""

    def test_get_next_pending_step_returns_first_pending(self):
        """Test that get_next_pending_step returns the first pending step."""
        state = AgentState(user_request="test")
        state.plan = [
            PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="done"),
            PlanStep(id=1, type=PlanStepType.SIMULATE_BASELINE, status="pending"),
            PlanStep(id=2, type=PlanStepType.GENERATE_BRIEFING, status="pending"),
        ]
        
        next_step = state.get_next_pending_step()
        assert next_step.id == 1
        assert next_step.type == PlanStepType.SIMULATE_BASELINE

    def test_get_next_pending_step_returns_none_when_all_done(self):
        """Test that get_next_pending_step returns None when all steps are done."""
        state = AgentState(user_request="test")
        state.plan = [
            PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="done"),
            PlanStep(id=1, type=PlanStepType.GENERATE_BRIEFING, status="done"),
        ]
        
        next_step = state.get_next_pending_step()
        assert next_step is None

    def test_mark_plan_step_running(self):
        """Test marking a step as running."""
        state = AgentState(user_request="test")
        state.plan = [PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="pending")]
        
        state.mark_plan_step_running(0)
        
        assert state.plan[0].status == "running"
        assert state.active_step_index == 0

    def test_mark_plan_step_done(self):
        """Test marking a step as done."""
        state = AgentState(user_request="test")
        state.plan = [PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="running")]
        
        state.mark_plan_step_done(0)
        
        assert state.plan[0].status == "done"

    def test_mark_plan_step_failed(self):
        """Test marking a step as failed with error info."""
        state = AgentState(user_request="test")
        state.plan = [PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="running")]
        error = ErrorInfo(type=ErrorType.TOOL_FATAL, message="Test error")
        
        state.mark_plan_step_failed(0, error)
        
        assert state.plan[0].status == "failed"
        assert state.plan[0].error == error

    def test_get_plan_summary(self):
        """Test plan summary formatting."""
        state = AgentState(user_request="test")
        state.plan = [
            PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="done"),
            PlanStep(id=1, type=PlanStepType.SIMULATE_BASELINE, status="running"),
            PlanStep(id=2, type=PlanStepType.GENERATE_BRIEFING, status="pending"),
        ]
        
        summary = state.get_plan_summary()
        
        assert "ensure_factory" in summary
        assert "simulate_baseline" in summary
        assert "generate_briefing" in summary


# =============================================================================
# BUDGET TESTS
# =============================================================================

class TestBudgetEnforcement:
    """Tests for LLM call budget enforcement."""

    def test_increment_llm_calls_under_budget(self):
        """Test that increment_llm_calls returns True when under budget."""
        state = AgentState(user_request="test", llm_call_budget=10)
        state.llm_calls_used = 5
        
        result = state.increment_llm_calls()
        
        assert result is True
        assert state.llm_calls_used == 6
        assert state.status == AgentStatus.RUNNING

    def test_increment_llm_calls_exceeds_budget(self):
        """Test that increment_llm_calls returns False when budget exceeded."""
        state = AgentState(user_request="test", llm_call_budget=5)
        state.llm_calls_used = 5
        
        result = state.increment_llm_calls()
        
        assert result is False
        assert state.llm_calls_used == 6
        assert state.status == AgentStatus.BUDGET_EXCEEDED


# =============================================================================
# PARTIAL ANSWER SYNTHESIS TESTS
# =============================================================================

class TestPartialAnswerSynthesis:
    """Tests for graceful degradation with partial answer synthesis."""

    def test_synthesize_shows_budget_exceeded(self):
        """Test that synthesis mentions budget exceeded."""
        state = AgentState(user_request="test", llm_call_budget=5)
        state.status = AgentStatus.BUDGET_EXCEEDED
        
        answer = _synthesize_partial_answer(state)
        
        assert "budget" in answer.lower()
        assert "5" in answer

    def test_synthesize_shows_step_limit(self):
        """Test that synthesis mentions step limit."""
        state = AgentState(user_request="test", max_steps=10)
        state.status = AgentStatus.MAX_STEPS
        
        answer = _synthesize_partial_answer(state)
        
        assert "step limit" in answer.lower() or "10" in answer

    def test_synthesize_includes_factory_info(self, sample_factory):
        """Test that synthesis includes factory information."""
        state = AgentState(user_request="test")
        state.factory = sample_factory
        state.status = AgentStatus.MAX_STEPS
        
        answer = _synthesize_partial_answer(state)
        
        assert "M1" in answer
        assert "M2" in answer
        assert "Factory Configuration" in answer

    def test_synthesize_handles_no_factory(self):
        """Test that synthesis handles missing factory gracefully."""
        state = AgentState(user_request="test")
        state.factory = None
        state.status = AgentStatus.MAX_STEPS
        
        answer = _synthesize_partial_answer(state)
        
        assert "not successfully loaded" in answer.lower() or "no factory" in answer.lower()

    def test_synthesize_includes_simulation_results(self, sample_factory, baseline_metrics):
        """Test that synthesis includes simulation results."""
        state = AgentState(user_request="test")
        state.factory = sample_factory
        state.scenarios_run.append(ScenarioSpec(scenario_type=ScenarioType.BASELINE))
        state.metrics_collected.append(baseline_metrics)
        state.status = AgentStatus.MAX_STEPS
        
        answer = _synthesize_partial_answer(state)
        
        assert "baseline" in answer
        assert "11" in answer  # makespan

    def test_synthesize_includes_plan_progress(self):
        """Test that synthesis includes plan progress."""
        state = AgentState(user_request="test")
        state.plan = [
            PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="done"),
            PlanStep(id=1, type=PlanStepType.SIMULATE_BASELINE, status="failed"),
        ]
        state.status = AgentStatus.MAX_STEPS
        
        answer = _synthesize_partial_answer(state)
        
        assert "Plan Progress" in answer


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error taxonomy and handling."""

    def test_error_info_creation(self):
        """Test creating ErrorInfo with all fields."""
        error = ErrorInfo(
            type=ErrorType.TOOL_FATAL,
            message="Test error",
            context={"key": "value"},
            recoverable=False
        )
        
        assert error.type == ErrorType.TOOL_FATAL
        assert error.message == "Test error"
        assert error.context == {"key": "value"}
        assert error.recoverable is False

    def test_task_unsat_sets_diagnostic_pending(self):
        """Test that TASK_UNSAT error sets DIAGNOSTIC_PENDING status."""
        state = AgentState(user_request="test")
        state.plan = [PlanStep(id=0, type=PlanStepType.ENSURE_FACTORY, status="running")]
        
        from backend.agent_engine import _handle_error
        error = ErrorInfo(type=ErrorType.TASK_UNSAT, message="Cannot parse factory")
        
        _handle_error(state, state.plan[0], error)
        
        assert state.status == AgentStatus.DIAGNOSTIC_PENDING
        # Should have added a diagnostic step
        assert any(s.type == PlanStepType.DIAGNOSTIC for s in state.plan)

    def test_tool_fatal_adds_diagnostic_step(self):
        """Test that TOOL_FATAL error adds a diagnostic step."""
        state = AgentState(user_request="test")
        state.plan = [PlanStep(id=0, type=PlanStepType.SIMULATE_BASELINE, status="running")]
        
        from backend.agent_engine import _handle_error
        error = ErrorInfo(type=ErrorType.TOOL_FATAL, message="Simulation failed")
        
        _handle_error(state, state.plan[0], error)
        
        assert any(s.type == PlanStepType.DIAGNOSTIC for s in state.plan)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestAgentIntegration:
    """Integration tests for the full agent loop."""

    def test_agent_generates_plan_and_executes(self):
        """Test that agent generates plan and attempts execution."""
        from backend.agent_types import PlanResponse
        
        mock_plan_response = PlanResponse(
            plan=[
                {"type": "diagnostic", "params": {"reason": "test"}},
            ],
            reasoning="Test plan"
        )
        
        with patch("backend.agent_engine.call_llm_json", return_value=mock_plan_response):
            state = run_agent("test", max_steps=5, llm_budget=5)
            
            # Agent should have a plan
            assert state.plan is not None
            assert len(state.plan) >= 1
            # Diagnostic step should complete
            assert state.status == AgentStatus.DONE
            assert state.final_answer is not None

    def test_agent_respects_max_steps(self):
        """Test that agent stops at max_steps."""
        from backend.agent_types import PlanResponse
        
        # Create a plan with many baseline simulation steps
        # These will all fail because no factory is loaded, but agent should still respect max_steps
        mock_plan = PlanResponse(
            plan=[{"type": "simulate_baseline", "params": {}} for _ in range(10)],
            reasoning="Many simulations"
        )
        
        with patch("backend.agent_engine.call_llm_json", return_value=mock_plan):
            state = run_agent("test", max_steps=3, llm_budget=10)
            
            # Should stop at or before max_steps
            assert state.steps <= 3
    
    def test_agent_handles_empty_plan_gracefully(self):
        """Test that agent handles empty/invalid plan by using canonical fallback."""
        from backend.agent_types import PlanResponse
        
        mock_plan = PlanResponse(plan=[], reasoning="Empty")
        
        with patch("backend.agent_engine.call_llm_json", return_value=mock_plan):
            state = run_agent("test", max_steps=5, llm_budget=5)
            
            # Should have fallen back to canonical plan
            assert len(state.plan) > 0
            assert any(s.type == PlanStepType.ENSURE_FACTORY for s in state.plan)

