"""
Tests for SOTA agent engine improvements.

Tests cover:
- Phase 1: Action History (Reflection) - prevents redundant tool calls
- Phase 2: Data Sufficiency Check - nudges agent to stop when it has enough data
- Phase 3: Context Pruning - compact summaries after step 5
- Phase 4: Goal-oriented SYSTEM_PROMPT

These tests use mocked LLM calls and verify the observation builder output.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from backend.agent_engine import (
    build_observation,
    _build_action_history,
    _build_data_sufficiency_check,
    _build_investigation_summary,
    SYSTEM_PROMPT,
    run_agent,
)
from backend.agent_types import AgentState, AgentStatus, Message
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
            Job(
                id="J1",
                name="Widget A",
                steps=[
                    Step(machine_id="M1", duration_hours=1),
                    Step(machine_id="M2", duration_hours=3),
                    Step(machine_id="M3", duration_hours=1),
                ],
                due_time_hour=12,
            ),
            Job(
                id="J2",
                name="Gadget B",
                steps=[
                    Step(machine_id="M1", duration_hours=1),
                    Step(machine_id="M2", duration_hours=2),
                    Step(machine_id="M3", duration_hours=1),
                ],
                due_time_hour=14,
            ),
            Job(
                id="J3",
                name="Gizmo C",
                steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=2),
                    Step(machine_id="M3", duration_hours=2),
                ],
                due_time_hour=16,
            ),
        ],
    )


@pytest.fixture
def baseline_metrics():
    """Return sample baseline metrics."""
    return ScenarioMetrics(
        makespan_hour=11,
        job_lateness={"J1": 0, "J2": 0, "J3": 0},
        bottleneck_machine_id="M2",
        bottleneck_utilization=0.95,
    )


@pytest.fixture
def rush_metrics():
    """Return sample RUSH_ARRIVES metrics."""
    return ScenarioMetrics(
        makespan_hour=12,
        job_lateness={"J1": 0, "J2": 0, "J3": 2},
        bottleneck_machine_id="M2",
        bottleneck_utilization=0.98,
    )


@pytest.fixture
def registry():
    """Return default tool registry."""
    return create_default_registry()


# =============================================================================
# PHASE 1: ACTION HISTORY (REFLECTION) TESTS
# =============================================================================

class TestActionHistory:
    """Tests for the Action History section (prevents redundant tool calls)."""

    def test_empty_state_has_no_action_history(self):
        """Test that a fresh state produces no action history."""
        state = AgentState(user_request="test request")
        history = _build_action_history(state)
        assert history == []

    def test_single_successful_tool_call_appears_in_history(self):
        """Test that a successful tool call appears in the action history."""
        state = AgentState(user_request="test request")
        state.add_message(
            "tool",
            json.dumps({"factory": {}, "machine_count": 3, "job_count": 3}),
            tool_call_id="1",
            name="get_demo_factory",
        )
        
        history = _build_action_history(state)
        
        assert len(history) > 0
        assert "Action History" in history[0]
        history_text = "\n".join(history)
        assert "get_demo_factory" in history_text
        assert "✓" in history_text  # Success marker

    def test_failed_tool_call_appears_in_history(self):
        """Test that a failed tool call appears in the action history."""
        state = AgentState(user_request="test request")
        state.add_message(
            "tool",
            json.dumps({"error": "No factory loaded"}),
            tool_call_id="1",
            name="simulate_scenario",
        )
        
        history = _build_action_history(state)
        
        history_text = "\n".join(history)
        assert "simulate_scenario" in history_text
        assert "✗" in history_text  # Failure marker

    def test_simulate_scenario_shows_scenario_types(self):
        """Test that simulate_scenario history shows which scenarios were run."""
        state = AgentState(user_request="test request")
        
        # Add successful BASELINE simulation
        state.add_message(
            "tool",
            json.dumps({
                "scenario_type": "BASELINE",
                "rush_job_id": None,
                "makespan_hours": 11,
            }),
            tool_call_id="1",
            name="simulate_scenario",
        )
        
        # Add successful RUSH_ARRIVES simulation
        state.add_message(
            "tool",
            json.dumps({
                "scenario_type": "RUSH_ARRIVES",
                "rush_job_id": "J1",
                "makespan_hours": 12,
            }),
            tool_call_id="2",
            name="simulate_scenario",
        )
        
        history = _build_action_history(state)
        history_text = "\n".join(history)
        
        assert "BASELINE" in history_text
        assert "RUSH_ARRIVES(J1)" in history_text

    def test_multiple_tools_all_appear_in_history(self):
        """Test that multiple different tools all appear in history."""
        state = AgentState(user_request="test request")
        
        state.add_message(
            "tool",
            json.dumps({"factory": {}, "machine_count": 3}),
            tool_call_id="1",
            name="get_demo_factory",
        )
        state.add_message(
            "tool",
            json.dumps({"available_scenarios": []}),
            tool_call_id="2",
            name="list_possible_scenarios",
        )
        state.add_message(
            "tool",
            json.dumps({"scenario_type": "BASELINE", "makespan_hours": 11}),
            tool_call_id="3",
            name="simulate_scenario",
        )
        
        history = _build_action_history(state)
        history_text = "\n".join(history)
        
        assert "get_demo_factory" in history_text
        assert "list_possible_scenarios" in history_text
        assert "simulate_scenario" in history_text


# =============================================================================
# PHASE 2: DATA SUFFICIENCY CHECK TESTS
# =============================================================================

class TestDataSufficiencyCheck:
    """Tests for the Data Sufficiency Check section."""

    def test_empty_state_shows_factory_not_loaded(self):
        """Test that a fresh state shows factory not loaded."""
        state = AgentState(user_request="test request")
        check = _build_data_sufficiency_check(state)
        
        check_text = "\n".join(check)
        assert "Factory loaded: ✗" in check_text
        assert "BASELINE run: ✗" in check_text
        assert "Comparison scenarios: 0" in check_text

    def test_factory_loaded_shows_checkmark(self, sample_factory):
        """Test that loaded factory shows checkmark."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        
        check = _build_data_sufficiency_check(state)
        check_text = "\n".join(check)
        
        assert "Factory loaded: ✓" in check_text

    def test_baseline_run_shows_checkmark(self, sample_factory, baseline_metrics):
        """Test that running BASELINE shows checkmark."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        check = _build_data_sufficiency_check(state)
        check_text = "\n".join(check)
        
        assert "BASELINE run: ✓" in check_text

    def test_comparison_scenarios_counted(self, sample_factory, baseline_metrics, rush_metrics):
        """Test that comparison scenarios are counted correctly."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        
        # Add BASELINE
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        # Add RUSH_ARRIVES
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ARRIVES, rush_job_id="J1")
        )
        state.metrics_collected.append(rush_metrics)
        
        check = _build_data_sufficiency_check(state)
        check_text = "\n".join(check)
        
        assert "Comparison scenarios: 1" in check_text

    def test_sufficient_data_shows_recommendation(self, sample_factory, baseline_metrics, rush_metrics):
        """Test that sufficient data triggers RECOMMENDATION to stop."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        
        # Add BASELINE and one comparison scenario
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.RUSH_ARRIVES, rush_job_id="J1")
        )
        state.metrics_collected.append(rush_metrics)
        
        check = _build_data_sufficiency_check(state)
        check_text = "\n".join(check)
        
        assert "RECOMMENDATION" in check_text
        assert "final_answer" in check_text

    def test_no_baseline_no_recommendation(self, sample_factory):
        """Test that without baseline, no recommendation to stop is given."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        # No simulations run
        
        check = _build_data_sufficiency_check(state)
        check_text = "\n".join(check)
        
        assert "RECOMMENDATION" not in check_text
        assert "Run BASELINE" in check_text


# =============================================================================
# PHASE 3: CONTEXT PRUNING TESTS
# =============================================================================

class TestContextPruning:
    """Tests for context pruning (compact summaries after step 5)."""

    def test_early_steps_show_recent_tool_results(self, sample_factory, registry):
        """Test that early steps (< 5) show Recent Tool Results section."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        state.steps = 2  # Early step
        
        # Add a tool message
        state.add_message(
            "tool",
            json.dumps({"factory": {}, "machine_count": 3}),
            tool_call_id="1",
            name="get_demo_factory",
        )
        
        observation = build_observation(state, registry)
        
        assert "Recent Tool Results" in observation

    def test_later_steps_show_investigation_summary(self, sample_factory, baseline_metrics, registry):
        """Test that later steps (>= 5) show Investigation Summary."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        state.steps = 5  # Pruning threshold
        
        # Add simulation results
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        # Add a tool message
        state.add_message(
            "tool",
            json.dumps({"scenario_type": "BASELINE"}),
            tool_call_id="1",
            name="simulate_scenario",
        )
        
        observation = build_observation(state, registry)
        
        assert "Investigation Summary" in observation
        # Should show only "Last Tool Result", not "Recent Tool Results"
        assert "Last Tool Result" in observation

    def test_investigation_summary_shows_compact_metrics(self, sample_factory, baseline_metrics, registry):
        """Test that Investigation Summary shows compact metrics format."""
        state = AgentState(user_request="test request")
        state.factory = sample_factory
        state.steps = 6
        
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        summary = _build_investigation_summary(state)
        summary_text = "\n".join(summary)
        
        # Should contain compact format
        assert "makespan 11h" in summary_text
        assert "M2" in summary_text


# =============================================================================
# PHASE 4: SYSTEM PROMPT TESTS
# =============================================================================

class TestSystemPrompt:
    """Tests for the goal-oriented SYSTEM_PROMPT."""

    def test_system_prompt_contains_when_to_stop_section(self):
        """Test that SYSTEM_PROMPT has the When to Stop section."""
        assert "When to Stop" in SYSTEM_PROMPT
        assert "CRITICAL" in SYSTEM_PROMPT

    def test_system_prompt_contains_anti_patterns(self):
        """Test that SYSTEM_PROMPT warns against anti-patterns."""
        assert "Anti-patterns" in SYSTEM_PROMPT
        assert "same tool twice" in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_action_history(self):
        """Test that SYSTEM_PROMPT tells agent to check Action History."""
        assert "Action History" in SYSTEM_PROMPT

    def test_system_prompt_no_rigid_workflow(self):
        """Test that SYSTEM_PROMPT doesn't have rigid Step 1-6 workflow."""
        # Old prompt had "## Example Workflow" with fixed steps
        # New prompt should be more flexible
        assert "Example Workflow" not in SYSTEM_PROMPT
        # But should have goal-oriented language
        assert "Goal" in SYSTEM_PROMPT or "goal" in SYSTEM_PROMPT

    def test_system_prompt_defines_sufficient_data(self):
        """Test that SYSTEM_PROMPT defines what 'sufficient data' means."""
        # Should mention BASELINE + comparison scenario
        assert "BASELINE" in SYSTEM_PROMPT
        # Should mention when to stop
        assert "final_answer" in SYSTEM_PROMPT


# =============================================================================
# INTEGRATION: FULL OBSERVATION TESTS
# =============================================================================

class TestBuildObservationIntegration:
    """Integration tests for the full build_observation function."""

    def test_full_observation_structure(self, sample_factory, baseline_metrics, registry):
        """Test that observation has all expected sections."""
        state = AgentState(user_request="Analyze my factory")
        state.factory = sample_factory
        state.scenarios_run.append(
            ScenarioSpec(scenario_type=ScenarioType.BASELINE)
        )
        state.metrics_collected.append(baseline_metrics)
        
        # Add a tool message
        state.add_message(
            "tool",
            json.dumps({"scenario_type": "BASELINE"}),
            tool_call_id="1",
            name="simulate_scenario",
        )
        
        observation = build_observation(state, registry)
        
        # Should have these sections
        assert "## Current State" in observation
        assert "## Action History" in observation
        assert "## Data Sufficiency Check" in observation
        assert "## Original User Request" in observation
        assert "## Available Tools" in observation

    def test_observation_contains_user_request(self, registry):
        """Test that observation always contains the user request."""
        state = AgentState(user_request="Please analyze the bottlenecks")
        
        observation = build_observation(state, registry)
        
        assert "Please analyze the bottlenecks" in observation

    def test_observation_shows_blocked_tools(self, registry):
        """Test that observation shows blocked tools separately."""
        state = AgentState(user_request="test")
        state.blocked_tools.add("parse_factory")
        
        observation = build_observation(state, registry)
        
        assert "BLOCKED" in observation
        assert "parse_factory" in observation

    def test_observation_shows_tool_signatures_with_argument_names(self, registry):
        """Test that observation shows tool signatures with exact argument names."""
        state = AgentState(user_request="test")
        
        observation = build_observation(state, registry)
        
        # Should show tool signatures, not just names
        assert "simulate_scenario(scenario_type:" in observation
        assert "parse_factory(description:" in observation
        # Should indicate exact argument names are required
        assert "EXACT argument names" in observation


# =============================================================================
# AGENT LOOP BEHAVIOR TESTS (with mocked LLM)
# =============================================================================

class TestAgentLoopBehavior:
    """Tests for the agent loop behavior with SOTA improvements."""

    def test_agent_completes_when_providing_final_answer(self):
        """Test that agent completes when LLM returns final_answer."""
        from backend.agent_types import AgentDecision
        
        mock_decision = AgentDecision(
            thought="I have all the data I need.",
            action_type="final_answer",
            tool_calls=[],
            final_answer="Here is your analysis..."
        )
        
        with patch("backend.agent_engine.call_llm_for_decision", return_value=mock_decision):
            state = run_agent("Analyze my factory", max_steps=10)
            
            assert state.status == AgentStatus.DONE
            assert state.final_answer == "Here is your analysis..."
            assert state.steps == 1  # Should stop after one step

    def test_agent_respects_max_steps(self):
        """Test that agent stops at max_steps if it never finishes."""
        from backend.agent_types import AgentDecision, ToolCall
        
        # Always return a tool call (never finish)
        mock_decision = AgentDecision(
            thought="I need more data.",
            action_type="tool_call",
            tool_calls=[
                ToolCall(id="1", name="list_possible_scenarios", arguments={})
            ],
            final_answer=None
        )
        
        with patch("backend.agent_engine.call_llm_for_decision", return_value=mock_decision):
            state = run_agent("Analyze my factory", max_steps=3)
            
            assert state.status == AgentStatus.MAX_STEPS
            assert state.steps == 3

    def test_observation_includes_action_history_after_tool_call(self):
        """Test that observation includes action history after a tool call."""
        from backend.agent_types import AgentDecision, ToolCall
        
        call_count = 0
        observations_seen = []
        
        def mock_llm_for_decision(observation, system_prompt, registry):
            nonlocal call_count
            observations_seen.append(observation)
            call_count += 1
            
            if call_count == 1:
                # First call: load factory
                return AgentDecision(
                    thought="Loading demo factory",
                    action_type="tool_call",
                    tool_calls=[ToolCall(id="1", name="get_demo_factory", arguments={})],
                    final_answer=None
                )
            else:
                # Second call: should see action history
                return AgentDecision(
                    thought="I have enough data.",
                    action_type="final_answer",
                    tool_calls=[],
                    final_answer="Done."
                )
        
        with patch("backend.agent_engine.call_llm_for_decision", side_effect=mock_llm_for_decision):
            state = run_agent("test", max_steps=5)
        
        # Second observation should have action history
        assert len(observations_seen) >= 2
        assert "Action History" in observations_seen[1]
        assert "get_demo_factory" in observations_seen[1]


# =============================================================================
# FIX 1 & 2: ARGUMENT VALIDATION TESTS
# =============================================================================

class TestArgumentValidation:
    """Tests for pre-execution argument validation."""

    def test_missing_required_argument_gives_helpful_error(self, registry):
        """Test that missing required args give clear error messages."""
        from backend.agent_engine import _validate_tool_args
        
        tool = registry.get("simulate_scenario")
        
        # Missing scenario_type (required)
        is_valid, error = _validate_tool_args(tool, {})
        
        assert not is_valid
        assert "Missing required argument" in error
        assert "scenario_type" in error
        assert "required" in error.lower()

    def test_unknown_argument_gives_helpful_error(self, registry):
        """Test that unknown/typo args are caught with suggestions."""
        from backend.agent_engine import _validate_tool_args
        
        tool = registry.get("simulate_scenario")
        
        # Provide all required args PLUS an unknown arg
        is_valid, error = _validate_tool_args(tool, {
            "scenario_type": "BASELINE",
            "scenario_id": "extra"  # Unknown/typo arg
        })
        
        assert not is_valid
        assert "Unknown argument" in error
        assert "scenario_id" in error
        assert "scenario_type" in error  # Should list valid args

    def test_valid_arguments_pass_validation(self, registry):
        """Test that valid arguments pass validation."""
        from backend.agent_engine import _validate_tool_args
        
        tool = registry.get("simulate_scenario")
        
        # Valid args
        is_valid, error = _validate_tool_args(tool, {"scenario_type": "BASELINE"})
        
        assert is_valid
        assert error is None

    def test_optional_arguments_can_be_omitted(self, registry):
        """Test that optional arguments can be left out."""
        from backend.agent_engine import _validate_tool_args
        
        tool = registry.get("simulate_scenario")
        
        # Only required arg, no optional args
        is_valid, error = _validate_tool_args(tool, {"scenario_type": "RUSH_ARRIVES"})
        
        assert is_valid
        assert error is None

    def test_tool_with_no_required_args(self, registry):
        """Test that tools with no required args accept empty dict."""
        from backend.agent_engine import _validate_tool_args
        
        tool = registry.get("get_demo_factory")
        
        is_valid, error = _validate_tool_args(tool, {})
        
        assert is_valid
        assert error is None

    def test_execute_tool_calls_validates_before_execution(self):
        """Test that execute_tool_calls validates args and doesn't call execute on invalid args."""
        from backend.agent_engine import execute_tool_calls
        from backend.agent_types import ToolCall
        
        state = AgentState(user_request="test")
        registry = create_default_registry()
        
        # Tool call with wrong argument name (missing required arg)
        tool_calls = [
            ToolCall(id="1", name="simulate_scenario", arguments={"scenario_id": "BASELINE"})
        ]
        
        results = execute_tool_calls(tool_calls, state, registry)
        
        assert len(results) == 1
        assert not results[0].success
        # Should report the missing required arg and show expected args
        assert "Missing required argument" in results[0].error
        assert "scenario_type" in results[0].error
        # Should also show expected arguments
        assert "Expected arguments" in results[0].error


# =============================================================================
# FIX 3: GRACEFUL MAX_STEPS TESTS
# =============================================================================

class TestGracefulMaxSteps:
    """Tests for graceful MAX_STEPS handling with partial answer synthesis."""

    def test_max_steps_synthesizes_partial_answer(self, sample_factory, baseline_metrics):
        """Test that hitting MAX_STEPS produces a useful partial answer."""
        from backend.agent_engine import _synthesize_partial_answer
        
        state = AgentState(user_request="Analyze bottlenecks")
        state.factory = sample_factory
        state.scenarios_run.append(ScenarioSpec(scenario_type=ScenarioType.BASELINE))
        state.metrics_collected.append(baseline_metrics)
        state.scratchpad.append("[Step 1] Loading factory configuration")
        state.scratchpad.append("[Step 2] Running baseline simulation")
        
        partial_answer = _synthesize_partial_answer(state)
        
        # Should have structured sections
        assert "# Partial Analysis" in partial_answer
        assert "## Factory Configuration" in partial_answer
        assert "## Simulation Results" in partial_answer
        
        # Should include factory info
        assert "M1" in partial_answer
        assert "M2" in partial_answer
        
        # Should include simulation results
        assert "BASELINE" in partial_answer
        assert "11 hours" in partial_answer or "11h" in partial_answer
        
        # Should include key findings
        assert "bottleneck" in partial_answer.lower()

    def test_max_steps_handles_no_factory(self):
        """Test that partial answer handles case where factory wasn't loaded."""
        from backend.agent_engine import _synthesize_partial_answer
        
        state = AgentState(user_request="test")
        state.factory = None  # No factory loaded
        
        partial_answer = _synthesize_partial_answer(state)
        
        assert "not successfully loaded" in partial_answer.lower() or "no factory" in partial_answer.lower()

    def test_max_steps_handles_no_simulations(self, sample_factory):
        """Test that partial answer handles case where no simulations ran."""
        from backend.agent_engine import _synthesize_partial_answer
        
        state = AgentState(user_request="test")
        state.factory = sample_factory
        # No simulations
        
        partial_answer = _synthesize_partial_answer(state)
        
        assert "Factory Configuration" in partial_answer
        assert "No simulations" in partial_answer or "not completed" in partial_answer.lower()

    def test_max_steps_includes_investigation_progress(self, sample_factory, baseline_metrics):
        """Test that partial answer shows what the agent was working on."""
        from backend.agent_engine import _synthesize_partial_answer
        
        state = AgentState(user_request="test")
        state.factory = sample_factory
        state.scenarios_run.append(ScenarioSpec(scenario_type=ScenarioType.BASELINE))
        state.metrics_collected.append(baseline_metrics)
        state.scratchpad.append("[Step 1] Parsing factory description")
        state.scratchpad.append("[Step 2] Running baseline simulation")
        state.scratchpad.append("[Step 3] About to run rush scenario")
        
        partial_answer = _synthesize_partial_answer(state)
        
        assert "Investigation Progress" in partial_answer
        # Should show recent thoughts
        assert "baseline" in partial_answer.lower()

    def test_agent_uses_partial_synthesis_on_max_steps(self):
        """Integration test: agent produces synthesized answer on MAX_STEPS."""
        from backend.agent_types import AgentDecision, ToolCall
        
        call_count = 0
        
        def mock_llm(observation, system_prompt, registry):
            nonlocal call_count
            call_count += 1
            # Always call a tool (never finish)
            return AgentDecision(
                thought="I need to run more simulations",
                action_type="tool_call",
                tool_calls=[ToolCall(id=str(call_count), name="get_demo_factory", arguments={})],
                final_answer=None
            )
        
        with patch("backend.agent_engine.call_llm_for_decision", side_effect=mock_llm):
            state = run_agent("Analyze factory", max_steps=3)
        
        assert state.status == AgentStatus.MAX_STEPS
        # Should have a synthesized partial answer, not just "ran out of steps"
        assert state.final_answer is not None
        assert "Partial Analysis" in state.final_answer
        assert "step limit" in state.final_answer.lower()

