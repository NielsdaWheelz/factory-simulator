"""
Tests for the atomic extraction pipeline (PR1).

Tests verify that:
1. The atomic pipeline (ExtractFactoryEntitiesTool → ExtractRoutingTool → 
   ExtractParametersTool → ValidateFactoryTool) produces equivalent results 
   to the monolithic ParseFactoryTool.
2. Intermediate state is properly shared between tools (no redundant LLM calls).
3. Edge cases are handled consistently.

All LLM calls are mocked; no real network interaction.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from copy import deepcopy

from backend.agent_types import AgentState
from backend.agent_tools import (
    ParseFactoryTool,
    ExtractFactoryEntitiesTool,
    ExtractRoutingTool,
    ExtractParametersTool,
    ValidateFactoryTool,
)
from backend.onboarding import (
    ExplicitIds,
    CoarseStructure,
    CoarseMachine,
    CoarseJob,
    RawFactoryConfig,
    RawJob,
    RawStep,
)
from backend.models import FactoryConfig


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_factory_text():
    """Sample factory description for testing."""
    return """
    We run 3 machines: M1 (assembly), M2 (drill), M3 (pack).
    Jobs J1, J2, J3 each pass through those machines in sequence.
    J1 takes 2h on M1, 3h on M2, 1h on M3 (due at hour 12).
    J2 takes 1h on M1, 2h on M2, 1h on M3 (due at hour 14).
    J3 takes 3h on M1, 1h on M2, 2h on M3 (due at hour 16).
    """


@pytest.fixture
def sample_coarse_structure():
    """Sample CoarseStructure for mocking."""
    return CoarseStructure(
        machines=[
            CoarseMachine(id="M1", name="assembly"),
            CoarseMachine(id="M2", name="drill"),
            CoarseMachine(id="M3", name="pack"),
        ],
        jobs=[
            CoarseJob(id="J1", name="Job 1"),
            CoarseJob(id="J2", name="Job 2"),
            CoarseJob(id="J3", name="Job 3"),
        ],
    )


@pytest.fixture
def sample_raw_factory():
    """Sample RawFactoryConfig for mocking."""
    return RawFactoryConfig(
        machines=[
            CoarseMachine(id="M1", name="assembly"),
            CoarseMachine(id="M2", name="drill"),
            CoarseMachine(id="M3", name="pack"),
        ],
        jobs=[
            RawJob(
                id="J1",
                name="Job 1",
                steps=[
                    RawStep(machine_id="M1", duration_hours=2),
                    RawStep(machine_id="M2", duration_hours=3),
                    RawStep(machine_id="M3", duration_hours=1),
                ],
                due_time_hour=12,
            ),
            RawJob(
                id="J2",
                name="Job 2",
                steps=[
                    RawStep(machine_id="M1", duration_hours=1),
                    RawStep(machine_id="M2", duration_hours=2),
                    RawStep(machine_id="M3", duration_hours=1),
                ],
                due_time_hour=14,
            ),
            RawJob(
                id="J3",
                name="Job 3",
                steps=[
                    RawStep(machine_id="M1", duration_hours=3),
                    RawStep(machine_id="M2", duration_hours=1),
                    RawStep(machine_id="M3", duration_hours=2),
                ],
                due_time_hour=16,
            ),
        ],
    )


@pytest.fixture
def fresh_state(sample_factory_text):
    """Fresh AgentState for each test."""
    return AgentState(user_request=sample_factory_text)


# =============================================================================
# ATOMIC PIPELINE VS MONOLITHIC TOOL COMPARISON
# =============================================================================

class TestAtomicPipelineEquivalence:
    """Test that atomic pipeline produces equivalent results to ParseFactoryTool."""

    def test_atomic_pipeline_produces_same_factory_as_monolithic(
        self, 
        sample_factory_text,
        sample_coarse_structure, 
        sample_raw_factory,
    ):
        """
        The 4-step atomic pipeline should produce the same FactoryConfig as
        the monolithic ParseFactoryTool, given the same mocked LLM responses.
        """
        # Run monolithic ParseFactoryTool
        monolithic_state = AgentState(user_request=sample_factory_text)
        parse_tool = ParseFactoryTool()
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure), \
             patch("backend.agent_tools.extract_steps", return_value=sample_raw_factory):
            monolithic_result = parse_tool.execute({"description": sample_factory_text}, monolithic_state)
        
        assert monolithic_result.success, f"ParseFactoryTool failed: {monolithic_result.error}"
        monolithic_factory = FactoryConfig.model_validate(monolithic_result.output["factory"])
        
        # Run atomic pipeline
        atomic_state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure), \
             patch("backend.agent_tools.extract_steps", return_value=sample_raw_factory):
            
            # Step 1: Extract entities
            entities_tool = ExtractFactoryEntitiesTool()
            entities_result = entities_tool.execute({"description": sample_factory_text}, atomic_state)
            assert entities_result.success, f"ExtractFactoryEntitiesTool failed: {entities_result.error}"
            
            # Step 2: Extract routing
            routing_tool = ExtractRoutingTool()
            routing_result = routing_tool.execute({"description": sample_factory_text}, atomic_state)
            assert routing_result.success, f"ExtractRoutingTool failed: {routing_result.error}"
            
            # Step 3: Extract parameters
            params_tool = ExtractParametersTool()
            params_result = params_tool.execute({"description": sample_factory_text}, atomic_state)
            assert params_result.success, f"ExtractParametersTool failed: {params_result.error}"
            
            # Step 4: Validate and assemble
            validate_tool = ValidateFactoryTool()
            validate_result = validate_tool.execute({}, atomic_state)
            assert validate_result.success, f"ValidateFactoryTool failed: {validate_result.error}"
        
        atomic_factory = atomic_state.factory
        
        # Compare results
        assert atomic_factory is not None
        assert len(atomic_factory.machines) == len(monolithic_factory.machines)
        assert len(atomic_factory.jobs) == len(monolithic_factory.jobs)
        
        # Compare machine IDs
        monolithic_machine_ids = {m.id for m in monolithic_factory.machines}
        atomic_machine_ids = {m.id for m in atomic_factory.machines}
        assert monolithic_machine_ids == atomic_machine_ids
        
        # Compare job IDs
        monolithic_job_ids = {j.id for j in monolithic_factory.jobs}
        atomic_job_ids = {j.id for j in atomic_factory.jobs}
        assert monolithic_job_ids == atomic_job_ids
        
        # Compare job routing (step machine sequences)
        for m_job in monolithic_factory.jobs:
            a_job = next(j for j in atomic_factory.jobs if j.id == m_job.id)
            m_route = [s.machine_id for s in m_job.steps]
            a_route = [s.machine_id for s in a_job.steps]
            assert m_route == a_route, f"Routing mismatch for {m_job.id}: {m_route} vs {a_route}"
            
            # Compare durations
            m_durations = [s.duration_hours for s in m_job.steps]
            a_durations = [s.duration_hours for s in a_job.steps]
            assert m_durations == a_durations, f"Duration mismatch for {m_job.id}: {m_durations} vs {a_durations}"
            
            # Compare due times
            assert m_job.due_time_hour == a_job.due_time_hour


# =============================================================================
# INTERMEDIATE STATE SHARING TESTS
# =============================================================================

class TestIntermediateStateSharing:
    """Test that intermediate state is properly shared between tools."""

    def test_coarse_structure_is_cached_and_reused(
        self, 
        sample_factory_text, 
        sample_coarse_structure, 
        sample_raw_factory,
    ):
        """
        ExtractRoutingTool should reuse the CoarseStructure cached by 
        ExtractFactoryEntitiesTool, not re-call extract_coarse_structure.
        """
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure) as mock_coarse, \
             patch("backend.agent_tools.extract_steps", return_value=sample_raw_factory) as mock_steps:
            
            # Step 1: Extract entities (should call extract_coarse_structure)
            entities_tool = ExtractFactoryEntitiesTool()
            entities_tool.execute({"description": sample_factory_text}, state)
            
            # Verify coarse structure was called once and cached
            assert mock_coarse.call_count == 1
            assert state._coarse_structure is not None
            
            # Step 2: Extract routing (should NOT call extract_coarse_structure again)
            routing_tool = ExtractRoutingTool()
            routing_tool.execute({"description": sample_factory_text}, state)
            
            # Should still be 1 call (reused from cache)
            assert mock_coarse.call_count == 1
            # extract_steps should be called once
            assert mock_steps.call_count == 1

    def test_raw_factory_config_is_cached_and_reused(
        self, 
        sample_factory_text, 
        sample_coarse_structure, 
        sample_raw_factory,
    ):
        """
        ExtractParametersTool should reuse the RawFactoryConfig cached by 
        ExtractRoutingTool, not re-call extract_steps.
        """
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure), \
             patch("backend.agent_tools.extract_steps", return_value=sample_raw_factory) as mock_steps:
            
            # Step 1: Extract entities
            entities_tool = ExtractFactoryEntitiesTool()
            entities_tool.execute({"description": sample_factory_text}, state)
            
            # Step 2: Extract routing (should call extract_steps)
            routing_tool = ExtractRoutingTool()
            routing_tool.execute({"description": sample_factory_text}, state)
            
            assert mock_steps.call_count == 1
            assert state._raw_factory_config is not None
            
            # Step 3: Extract parameters (should NOT call extract_steps again)
            params_tool = ExtractParametersTool()
            params_tool.execute({"description": sample_factory_text}, state)
            
            # Should still be 1 call (reused from cache)
            assert mock_steps.call_count == 1

    def test_atomic_pipeline_makes_exactly_2_llm_calls(
        self, 
        sample_factory_text, 
        sample_coarse_structure, 
        sample_raw_factory,
    ):
        """
        The full atomic pipeline should make exactly 2 LLM calls:
        1. extract_coarse_structure (in ExtractFactoryEntitiesTool)
        2. extract_steps (in ExtractRoutingTool)
        
        ExtractParametersTool and ValidateFactoryTool should not make LLM calls.
        """
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure) as mock_coarse, \
             patch("backend.agent_tools.extract_steps", return_value=sample_raw_factory) as mock_steps:
            
            # Run full pipeline
            ExtractFactoryEntitiesTool().execute({"description": sample_factory_text}, state)
            ExtractRoutingTool().execute({"description": sample_factory_text}, state)
            ExtractParametersTool().execute({"description": sample_factory_text}, state)
            ValidateFactoryTool().execute({}, state)
            
            # Verify exactly 2 LLM-backed calls
            assert mock_coarse.call_count == 1
            assert mock_steps.call_count == 1


# =============================================================================
# PRECONDITION TESTS
# =============================================================================

class TestPreconditions:
    """Test that tools enforce their preconditions."""

    def test_routing_tool_requires_entities(self, sample_factory_text):
        """ExtractRoutingTool fails if entities not extracted first."""
        state = AgentState(user_request=sample_factory_text)
        
        routing_tool = ExtractRoutingTool()
        result = routing_tool.execute({"description": sample_factory_text}, state)
        
        assert not result.success
        assert "extract_factory_entities" in result.error.lower()

    def test_parameters_tool_requires_entities(self, sample_factory_text):
        """ExtractParametersTool fails if entities not extracted first."""
        state = AgentState(user_request=sample_factory_text)
        
        params_tool = ExtractParametersTool()
        result = params_tool.execute({"description": sample_factory_text}, state)
        
        assert not result.success
        assert "extract_factory_entities" in result.error.lower()

    def test_parameters_tool_requires_routing(
        self, 
        sample_factory_text, 
        sample_coarse_structure,
    ):
        """ExtractParametersTool fails if routing not extracted first."""
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure):
            # Run entities but skip routing
            ExtractFactoryEntitiesTool().execute({"description": sample_factory_text}, state)
        
        params_tool = ExtractParametersTool()
        result = params_tool.execute({"description": sample_factory_text}, state)
        
        assert not result.success
        assert "extract_routing" in result.error.lower()

    def test_validate_tool_requires_all_preconditions(self, sample_factory_text):
        """ValidateFactoryTool fails if any precondition is missing."""
        state = AgentState(user_request=sample_factory_text)
        
        validate_tool = ValidateFactoryTool()
        result = validate_tool.execute({}, state)
        
        assert not result.success
        assert "entities" in result.error.lower() or "routing" in result.error.lower()


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_missing_durations_with_defaults(
        self, 
        sample_factory_text, 
        sample_coarse_structure,
    ):
        """
        Pipeline should handle jobs with missing duration info by using defaults.
        """
        # Create raw factory with a job missing duration info
        raw_factory_missing_duration = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=0)],  # Invalid duration
                    due_time_hour=12,
                ),
            ],
        )
        
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )), \
             patch("backend.agent_tools.extract_steps", return_value=raw_factory_missing_duration):
            
            # Run full pipeline
            ExtractFactoryEntitiesTool().execute({"description": sample_factory_text}, state)
            ExtractRoutingTool().execute({"description": sample_factory_text}, state)
            ExtractParametersTool().execute({"description": sample_factory_text}, state)
            result = ValidateFactoryTool().execute({}, state)
            
            # Should succeed (normalization fixes invalid durations)
            assert result.success
            assert state.factory is not None
            # Duration should be normalized to 1 (minimum valid)
            assert state.factory.jobs[0].steps[0].duration_hours == 1

    def test_handles_none_due_time_with_default(
        self, 
        sample_factory_text,
    ):
        """Pipeline should handle None due_time_hour by defaulting to 24."""
        raw_factory_none_due = RawFactoryConfig(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[
                RawJob(
                    id="J1",
                    name="Job 1",
                    steps=[RawStep(machine_id="M1", duration_hours=2)],
                    due_time_hour=None,  # Missing due time
                ),
            ],
        )
        
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=CoarseStructure(
            machines=[CoarseMachine(id="M1", name="assembly")],
            jobs=[CoarseJob(id="J1", name="Job 1")],
        )), \
             patch("backend.agent_tools.extract_steps", return_value=raw_factory_none_due):
            
            ExtractFactoryEntitiesTool().execute({"description": sample_factory_text}, state)
            ExtractRoutingTool().execute({"description": sample_factory_text}, state)
            ExtractParametersTool().execute({"description": sample_factory_text}, state)
            result = ValidateFactoryTool().execute({}, state)
            
            assert result.success
            assert state.factory.jobs[0].due_time_hour == 24

    def test_factory_text_is_stored_in_state(
        self, 
        sample_factory_text, 
        sample_coarse_structure,
    ):
        """ExtractFactoryEntitiesTool should store factory_text in state."""
        state = AgentState(user_request=sample_factory_text)
        
        with patch("backend.agent_tools.extract_coarse_structure", return_value=sample_coarse_structure):
            entities_tool = ExtractFactoryEntitiesTool()
            entities_tool.execute({"description": sample_factory_text}, state)
        
        assert state.factory_text == sample_factory_text

