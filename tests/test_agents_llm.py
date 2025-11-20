"""
Tests for LLM-backed agents with mocked call_llm_json.

These tests verify agent behavior when the LLM returns expected responses,
and also verify fallback behavior when the LLM fails.
All network calls are mocked; no real OpenAI API key is required.
"""

import pytest
from unittest.mock import patch, MagicMock

from models import ScenarioSpec, ScenarioType, ScenarioMetrics
from agents import IntentAgent, FuturesAgent, BriefingAgent, FuturesResponse, BriefingResponse, normalize_scenario_spec
from world import build_toy_factory


class TestNormalizeScenarioSpec:
    """Test normalize_scenario_spec function."""

    def test_m2_slowdown_clears_rush_job_id(self):
        """Test that M2_SLOWDOWN with rush_job_id set gets rush_job_id cleared."""
        factory = build_toy_factory()

        # LLM incorrectly produced M2_SLOWDOWN with rush_job_id set
        # Use model_construct to bypass validation (simulating LLM returning invalid JSON)
        spec = ScenarioSpec.model_construct(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id="J1",  # This shouldn't be here
            slowdown_factor=2,
        )

        # Normalize should clear the rush_job_id
        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.M2_SLOWDOWN
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor == 2

    def test_rush_arrives_with_valid_job_id_unchanged(self):
        """Test that RUSH_ARRIVES with valid rush_job_id is unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J1",
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.RUSH_ARRIVES
        assert normalized.rush_job_id == "J1"
        assert normalized.slowdown_factor is None

    def test_rush_arrives_with_invalid_job_id_downgrades_to_baseline(self):
        """Test that RUSH_ARRIVES with invalid rush_job_id downgrades to BASELINE."""
        factory = build_toy_factory()

        # J99 doesn't exist in the factory
        spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J99",
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_rush_arrives_with_none_rush_job_id_downgrades_to_baseline(self):
        """Test that RUSH_ARRIVES with None rush_job_id downgrades to BASELINE."""
        factory = build_toy_factory()

        # Use model_construct to bypass validation (simulating invalid LLM JSON)
        spec = ScenarioSpec.model_construct(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id=None,
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_baseline_unchanged(self):
        """Test that BASELINE specs are unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.BASELINE,
            rush_job_id=None,
            slowdown_factor=None,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.BASELINE
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor is None

    def test_m2_slowdown_with_none_rush_job_id_unchanged(self):
        """Test that M2_SLOWDOWN with None rush_job_id is unchanged."""
        factory = build_toy_factory()

        spec = ScenarioSpec(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id=None,
            slowdown_factor=3,
        )

        normalized = normalize_scenario_spec(spec, factory)

        assert normalized.scenario_type == ScenarioType.M2_SLOWDOWN
        assert normalized.rush_job_id is None
        assert normalized.slowdown_factor == 3


class TestIntentAgentWithMockedLLM:
    """Test IntentAgent with mocked call_llm_json."""

    def test_intent_agent_returns_rush_scenario(self):
        """Test that IntentAgent returns a RUSH_ARRIVES spec when mocked LLM does."""
        expected_spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J2",
            slowdown_factor=None,
        )

        with patch("agents.call_llm_json", return_value=expected_spec):
            agent = IntentAgent()
            result = agent.run("we have a rush order for J2")

            assert result.scenario_type == ScenarioType.RUSH_ARRIVES
            assert result.rush_job_id == "J2"
            assert result.slowdown_factor is None

    def test_intent_agent_returns_m2_slowdown_scenario(self):
        """Test that IntentAgent returns M2_SLOWDOWN spec when mocked LLM does."""
        expected_spec = ScenarioSpec(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id=None,
            slowdown_factor=3,
        )

        with patch("agents.call_llm_json", return_value=expected_spec):
            agent = IntentAgent()
            result = agent.run("machine M2 is having issues")

            assert result.scenario_type == ScenarioType.M2_SLOWDOWN
            assert result.slowdown_factor == 3
            assert result.rush_job_id is None

    def test_intent_agent_returns_baseline_scenario(self):
        """Test that IntentAgent returns BASELINE spec when mocked LLM does."""
        expected_spec = ScenarioSpec(
            scenario_type=ScenarioType.BASELINE,
            rush_job_id=None,
            slowdown_factor=None,
        )

        with patch("agents.call_llm_json", return_value=expected_spec):
            agent = IntentAgent()
            result = agent.run("just a normal day")

            assert result.scenario_type == ScenarioType.BASELINE
            assert result.rush_job_id is None
            assert result.slowdown_factor is None

    def test_intent_agent_fallback_on_llm_failure(self):
        """Test that IntentAgent falls back to BASELINE when LLM call fails."""
        with patch("agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = IntentAgent()
            result = agent.run("some text")

            # Should fallback to BASELINE
            assert result.scenario_type == ScenarioType.BASELINE
            assert result.rush_job_id is None
            assert result.slowdown_factor is None

    def test_intent_agent_fallback_on_validation_error(self):
        """Test that IntentAgent falls back when LLM response validation fails."""
        # Raise a validation error during model_validate
        with patch("agents.call_llm_json", side_effect=ValueError("Invalid scenario")):
            agent = IntentAgent()
            result = agent.run("some text")

            # Should fallback to BASELINE
            assert result.scenario_type == ScenarioType.BASELINE

    def test_intent_agent_normalizes_m2_slowdown_with_rush_job_id(self):
        """Test that IntentAgent normalizes M2_SLOWDOWN with rush_job_id to valid spec."""
        # LLM returns M2_SLOWDOWN with rush_job_id set (invalid combo)
        # Use model_construct to bypass validation (simulating LLM returning invalid JSON)
        invalid_spec = ScenarioSpec.model_construct(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id="J1",  # Invalid with M2_SLOWDOWN
            slowdown_factor=2,
        )

        with patch("agents.call_llm_json", return_value=invalid_spec):
            agent = IntentAgent()
            result = agent.run("M2 is slow and J1 needs rushing")

            # Should be normalized to valid M2_SLOWDOWN (no rush_job_id)
            assert result.scenario_type == ScenarioType.M2_SLOWDOWN
            assert result.rush_job_id is None
            assert result.slowdown_factor == 2

    def test_intent_agent_normalizes_rush_with_invalid_job_id(self):
        """Test that IntentAgent normalizes RUSH_ARRIVES with invalid job ID to BASELINE."""
        # LLM returns RUSH_ARRIVES with non-existent job ID
        invalid_spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J99",  # Invalid job ID
            slowdown_factor=None,
        )

        with patch("agents.call_llm_json", return_value=invalid_spec):
            agent = IntentAgent()
            result = agent.run("rush order for J99")

            # Should downgrade to BASELINE
            assert result.scenario_type == ScenarioType.BASELINE
            assert result.rush_job_id is None
            assert result.slowdown_factor is None


class TestFuturesAgentWithMockedLLM:
    """Test FuturesAgent with mocked call_llm_json."""

    def test_futures_agent_returns_three_scenarios(self):
        """Test that FuturesAgent returns multiple scenarios from mocked LLM."""
        expected_response = FuturesResponse(
            scenarios=[
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J1",
                    slowdown_factor=None,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.M2_SLOWDOWN,
                    rush_job_id=None,
                    slowdown_factor=2,
                ),
            ]
        )

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            result = agent.run(base_spec)

            assert len(result) == 3
            assert result[0].scenario_type == ScenarioType.BASELINE
            assert result[1].scenario_type == ScenarioType.RUSH_ARRIVES
            assert result[1].rush_job_id == "J1"
            assert result[2].scenario_type == ScenarioType.M2_SLOWDOWN
            assert result[2].slowdown_factor == 2

    def test_futures_agent_returns_single_scenario(self):
        """Test that FuturesAgent handles a single scenario response."""
        expected_response = FuturesResponse(
            scenarios=[
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
            ]
        )

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            result = agent.run(base_spec)

            assert len(result) == 1
            assert result[0].scenario_type == ScenarioType.BASELINE

    def test_futures_agent_truncates_to_three_scenarios(self):
        """Test that FuturesAgent truncates if LLM returns more than 3 scenarios."""
        # LLM tries to return 5 scenarios
        expected_response = FuturesResponse(
            scenarios=[
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J1",
                    slowdown_factor=None,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.M2_SLOWDOWN,
                    rush_job_id=None,
                    slowdown_factor=2,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J2",
                    slowdown_factor=None,
                ),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J3",
                    slowdown_factor=None,
                ),
            ]
        )

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            result = agent.run(base_spec)

            # Should be truncated to first 3
            assert len(result) == 3

    def test_futures_agent_fallback_on_llm_failure(self):
        """Test that FuturesAgent falls back to [spec] when LLM fails."""
        base_spec = ScenarioSpec(
            scenario_type=ScenarioType.M2_SLOWDOWN,
            rush_job_id=None,
            slowdown_factor=2,
        )

        with patch("agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = FuturesAgent()
            result = agent.run(base_spec)

            # Should fallback to [base_spec]
            assert len(result) == 1
            assert result[0] == base_spec

    def test_futures_agent_fallback_on_empty_response(self):
        """Test that FuturesAgent falls back to [spec] when LLM returns empty list."""
        expected_response = FuturesResponse(scenarios=[])

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()
            result = agent.run(base_spec)

            # Should fallback to [base_spec]
            assert len(result) == 1
            assert result[0] == base_spec


class TestBriefingAgentWithMockedLLM:
    """Test BriefingAgent with mocked call_llm_json."""

    def test_briefing_agent_returns_markdown(self):
        """Test that BriefingAgent returns markdown from mocked LLM."""
        expected_markdown = """# Morning Briefing

## Today at a Glance
M2 is the bottleneck in all scenarios. Baseline is feasible.

## Key Risks
- M2 utilization is high at 85%.
- No jobs are late in baseline scenario.

## Recommended Actions
- Monitor M2 throughout the day.
- Be prepared to prioritize jobs if M2 has issues.

## Limitations of This Model
This is a single-day deterministic model with no real disruptions."""

        expected_response = BriefingResponse(markdown=expected_markdown)

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()
            result = agent.run(metrics)

            assert "Morning Briefing" in result
            assert "M2 is the bottleneck" in result
            assert result == expected_markdown

    def test_briefing_agent_with_context(self):
        """Test that BriefingAgent receives context parameter."""
        expected_markdown = "# Brief\n\nWith context about other scenarios."
        expected_response = BriefingResponse(markdown=expected_markdown)

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        context = "Other scenarios: Rush scenario has J1 late by 3h."

        with patch("agents.call_llm_json", return_value=expected_response) as mock_llm:
            agent = BriefingAgent()
            result = agent.run(metrics, context=context)

            # Verify call_llm_json was called
            assert mock_llm.called
            # Verify context was included in the prompt
            call_args = mock_llm.call_args
            prompt = call_args[0][0]  # First positional argument is the prompt
            assert "Other scenarios" in prompt or "context" in prompt.lower()

    def test_briefing_agent_fallback_on_llm_failure(self):
        """Test that BriefingAgent falls back to deterministic template on LLM failure."""
        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("agents.call_llm_json", side_effect=RuntimeError("API error")):
            agent = BriefingAgent()
            result = agent.run(metrics)

            # Should fallback to deterministic template
            assert "# Morning Briefing" in result
            assert "M2" in result
            assert "0.85" in result or "85%" in result
            assert isinstance(result, str)
            assert len(result) > 0

    def test_briefing_agent_fallback_on_validation_error(self):
        """Test that BriefingAgent falls back when response validation fails."""
        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("agents.call_llm_json", side_effect=ValueError("Invalid response")):
            agent = BriefingAgent()
            result = agent.run(metrics)

            # Should fallback to deterministic template
            assert "# Morning Briefing" in result
            assert "M2" in result
            assert isinstance(result, str)

    def test_briefing_agent_without_context(self):
        """Test that BriefingAgent works without context parameter."""
        expected_response = BriefingResponse(markdown="# Briefing\n\nNo context.")

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()
            result = agent.run(metrics)  # No context parameter

            assert "Briefing" in result


class TestAgentDeterminism:
    """Test that agents produce deterministic outputs under mocked LLM."""

    def test_intent_agent_determinism(self):
        """Test that IntentAgent produces same output for same input with same mocked LLM."""
        expected_spec = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J2",
            slowdown_factor=None,
        )

        with patch("agents.call_llm_json", return_value=expected_spec):
            agent = IntentAgent()

            result1 = agent.run("rush order for J2")
            result2 = agent.run("rush order for J2")

            assert result1 == result2

    def test_futures_agent_determinism(self):
        """Test that FuturesAgent produces same output for same input with same mocked LLM."""
        expected_response = FuturesResponse(
            scenarios=[
                ScenarioSpec(scenario_type=ScenarioType.BASELINE),
                ScenarioSpec(
                    scenario_type=ScenarioType.RUSH_ARRIVES,
                    rush_job_id="J1",
                    slowdown_factor=None,
                ),
            ]
        )

        base_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = FuturesAgent()

            result1 = agent.run(base_spec)
            result2 = agent.run(base_spec)

            assert result1 == result2
            assert len(result1) == len(result2) == 2

    def test_briefing_agent_determinism(self):
        """Test that BriefingAgent produces same output for same metrics with same mocked LLM."""
        expected_response = BriefingResponse(markdown="# Test\n\nDeterministic output.")

        metrics = ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0, "J2": 0, "J3": 0},
            bottleneck_machine_id="M2",
            bottleneck_utilization=0.85,
        )

        with patch("agents.call_llm_json", return_value=expected_response):
            agent = BriefingAgent()

            result1 = agent.run(metrics)
            result2 = agent.run(metrics)

            assert result1 == result2
