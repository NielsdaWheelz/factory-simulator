"""
Tests for server.py - FastAPI endpoint for /api/simulate.

Verifies:
- Endpoint accepts correct request shape
- Endpoint returns JSON-serializable response
- Response includes all required fields
- Serialization handles Pydantic models and enums
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.server import app
from backend.models import (
    FactoryConfig,
    Machine,
    Job,
    Step,
    ScenarioSpec,
    ScenarioType,
    ScenarioMetrics,
)


@pytest.fixture
def client():
    """Return a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def mock_pipeline_result():
    """Return a realistic mock result from run_onboarded_pipeline."""
    factory = FactoryConfig(
        machines=[
            Machine(id="M1", name="Assembly"),
            Machine(id="M2", name="Drill"),
            Machine(id="M3", name="Package"),
        ],
        jobs=[
            Job(
                id="J1",
                name="Job 1",
                steps=[Step(machine_id="M1", duration_hours=2)],
                due_time_hour=24,
            ),
        ],
    )

    specs = [
        ScenarioSpec(scenario_type=ScenarioType.BASELINE),
        ScenarioSpec(scenario_type=ScenarioType.RUSH_ARRIVES, rush_job_id="J1"),
    ]

    metrics = [
        ScenarioMetrics(
            makespan_hour=5,
            job_lateness={"J1": 0},
            bottleneck_machine_id="M1",
            bottleneck_utilization=0.5,
        ),
        ScenarioMetrics(
            makespan_hour=6,
            job_lateness={"J1": 0},
            bottleneck_machine_id="M1",
            bottleneck_utilization=0.6,
        ),
    ]

    return {
        "factory": factory,
        "situation_text": "normal day",
        "specs": specs,
        "metrics": metrics,
        "briefing": "# Test Briefing\n\nThis is a test briefing.",
        "meta": {
            "used_default_factory": False,
            "onboarding_errors": [],
        },
    }


class TestSimulateEndpoint:
    """Test the POST /api/simulate endpoint."""

    def test_simulate_endpoint_smoke(self, client, mock_pipeline_result, monkeypatch):
        """Smoke test: endpoint accepts request and returns 200 with JSON response."""
        # Patch run_onboarded_pipeline to return a deterministic result
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "3 machines, 3 jobs",
                "situation_text": "normal day",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all required top-level keys present
        assert "factory" in data
        assert "specs" in data
        assert "metrics" in data
        assert "briefing" in data
        assert "meta" in data

    def test_simulate_endpoint_response_shape(
        self, client, mock_pipeline_result, monkeypatch
    ):
        """Verify response structure matches expected schema."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "test factory",
                "situation_text": "test situation",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Check factory structure
        assert isinstance(data["factory"], dict)
        assert "machines" in data["factory"]
        assert "jobs" in data["factory"]
        assert isinstance(data["factory"]["machines"], list)
        assert isinstance(data["factory"]["jobs"], list)

        # Check specs structure
        assert isinstance(data["specs"], list)
        assert len(data["specs"]) > 0
        spec = data["specs"][0]
        assert "scenario_type" in spec

        # Check metrics structure
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0
        metrics = data["metrics"][0]
        assert "makespan_hour" in metrics
        assert "bottleneck_machine_id" in metrics
        assert "bottleneck_utilization" in metrics
        assert "job_lateness" in metrics

        # Check briefing
        assert isinstance(data["briefing"], str)

        # Check meta
        assert isinstance(data["meta"], dict)
        assert "used_default_factory" in data["meta"]
        assert "onboarding_errors" in data["meta"]

    def test_simulate_endpoint_enum_serialization(
        self, client, mock_pipeline_result, monkeypatch
    ):
        """Verify that ScenarioType enums are serialized as strings."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "test",
                "situation_text": "test",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify scenario_type is a string (enum serialized)
        assert isinstance(data["specs"][0]["scenario_type"], str)
        assert data["specs"][0]["scenario_type"] == "BASELINE"
        assert data["specs"][1]["scenario_type"] == "RUSH_ARRIVES"

    def test_simulate_endpoint_request_validation(self, client):
        """Verify that endpoint validates request shape."""
        # Missing factory_description
        response = client.post(
            "/api/simulate",
            json={"situation_text": "test"},
        )
        assert response.status_code == 422  # Unprocessable entity

        # Missing situation_text
        response = client.post(
            "/api/simulate",
            json={"factory_description": "test"},
        )
        assert response.status_code == 422

    def test_simulate_endpoint_all_types_json_serializable(
        self, client, mock_pipeline_result, monkeypatch
    ):
        """Verify entire response can be JSON-serialized without errors."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "test",
                "situation_text": "test",
            },
        )

        assert response.status_code == 200
        # If we got here, response.json() worked, so it's JSON-serializable
        data = response.json()
        assert data is not None


class TestSimulateEndpointOnboardingIntegration:
    """Test that /api/simulate uses onboarding (not toy factory shortcut)."""

    def test_simulate_uses_onboarded_factory_custom_factory(self, client, monkeypatch):
        """Test that /api/simulate uses run_onboarded_pipeline with custom factory."""
        # Create a custom factory to verify it's used
        custom_factory = FactoryConfig(
            machines=[Machine(id="M_CUSTOM", name="CustomMachine")],
            jobs=[Job(
                id="J_CUSTOM",
                name="CustomJob",
                steps=[Step(machine_id="M_CUSTOM", duration_hours=3)],
                due_time_hour=16
            )],
        )

        custom_pipeline_result = {
            "factory": custom_factory,
            "specs": [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
            "metrics": [
                ScenarioMetrics(
                    makespan_hour=3,
                    job_lateness={"J_CUSTOM": 0},
                    bottleneck_machine_id="M_CUSTOM",
                    bottleneck_utilization=0.5,
                ),
            ],
            "briefing": "# Custom Factory Briefing",
            "meta": {
                "used_default_factory": False,
                "onboarding_errors": [],
            },
        }

        def mock_run_onboarded_pipeline(factory_text, situation_text):
            # Verify we're called with the right inputs
            assert factory_text == "custom factory description"
            assert situation_text == "test situation"
            return custom_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "custom factory description",
                "situation_text": "test situation",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify custom factory is returned (not toy factory)
        assert len(data["factory"]["machines"]) == 1
        assert data["factory"]["machines"][0]["id"] == "M_CUSTOM"
        assert len(data["factory"]["jobs"]) == 1
        assert data["factory"]["jobs"][0]["id"] == "J_CUSTOM"

    def test_simulate_endpoint_calls_run_onboarded_pipeline(self, client, monkeypatch):
        """Test that endpoint calls run_onboarded_pipeline."""
        mock_onboarded_pipeline = None

        def mock_run_onboarded_pipeline(factory_text, situation_text):
            nonlocal mock_onboarded_pipeline
            mock_onboarded_pipeline = (factory_text, situation_text)
            return {
                "factory": FactoryConfig(
                    machines=[Machine(id="M1", name="M1")],
                    jobs=[Job(
                        id="J1",
                        name="J1",
                        steps=[Step(machine_id="M1", duration_hours=1)],
                        due_time_hour=24
                    )],
                ),
                "specs": [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
                "metrics": [
                    ScenarioMetrics(
                        makespan_hour=1,
                        job_lateness={"J1": 0},
                        bottleneck_machine_id="M1",
                        bottleneck_utilization=0.5,
                    ),
                ],
                "briefing": "# Test",
                "meta": {
                    "used_default_factory": False,
                    "onboarding_errors": [],
                },
            }

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        factory_desc = "factory description"
        situation = "test situation"

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": factory_desc,
                "situation_text": situation,
            },
        )

        assert response.status_code == 200
        # Verify run_onboarded_pipeline was called with the right arguments
        assert mock_onboarded_pipeline is not None
        assert mock_onboarded_pipeline[0] == factory_desc
        assert mock_onboarded_pipeline[1] == situation

    def test_simulate_endpoint_fallback_sets_meta_correctly(self, client, monkeypatch):
        """Test that fallback factory sets used_default_factory in meta."""
        from backend.models import OnboardingMeta
        from backend.world import build_toy_factory

        # Simulate a fallback to toy factory
        toy_factory = build_toy_factory()

        fallback_result = {
            "factory": toy_factory,
            "specs": [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
            "metrics": [
                ScenarioMetrics(
                    makespan_hour=5,
                    job_lateness={"J1": 0, "J2": 0, "J3": 0},
                    bottleneck_machine_id="M2",
                    bottleneck_utilization=0.7,
                ),
            ],
            "briefing": "# Fallback Briefing",
            "meta": OnboardingMeta(
                used_default_factory=True,
                onboarding_errors=["Normalization resulted in empty factory; falling back to toy factory"],
                inferred_assumptions=[],
            ),
        }

        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return fallback_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "bad factory",
                "situation_text": "test",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify fallback was detected
        assert data["meta"]["used_default_factory"] is True
        assert len(data["meta"]["onboarding_errors"]) > 0
        assert "falling back to toy factory" in data["meta"]["onboarding_errors"][0]

        # Verify toy factory is returned
        assert len(data["factory"]["machines"]) == 3
        assert len(data["factory"]["jobs"]) == 3

    def test_simulate_endpoint_includes_meta_in_response(self, client, monkeypatch):
        """Test that /api/simulate response includes meta field."""
        from backend.models import OnboardingMeta

        meta = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=["warning 1"],
            inferred_assumptions=["assumption 1"],
        )

        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return {
                "factory": FactoryConfig(
                    machines=[Machine(id="M1", name="M1")],
                    jobs=[Job(
                        id="J1",
                        name="J1",
                        steps=[Step(machine_id="M1", duration_hours=1)],
                        due_time_hour=24
                    )],
                ),
                "specs": [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
                "metrics": [
                    ScenarioMetrics(
                        makespan_hour=1,
                        job_lateness={"J1": 0},
                        bottleneck_machine_id="M1",
                        bottleneck_utilization=0.5,
                    ),
                ],
                "briefing": "# Test",
                "meta": meta,
            }

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "test",
                "situation_text": "test",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify meta is in response
        assert "meta" in data
        assert isinstance(data["meta"], dict)
        assert data["meta"]["used_default_factory"] is False
        assert data["meta"]["onboarding_errors"] == ["warning 1"]

    def test_simulate_endpoint_always_does_onboarding(self, client, monkeypatch):
        """Test that /api/simulate ALWAYS does onboarding (no toy shortcut)."""
        called_with = []

        def mock_run_onboarded_pipeline(factory_text, situation_text):
            called_with.append((factory_text, situation_text))
            # Simulate custom onboarded factory
            return {
                "factory": FactoryConfig(
                    machines=[Machine(id="M_ONBOARD", name="OnboardedMachine")],
                    jobs=[Job(
                        id="J_ONBOARD",
                        name="OnboardedJob",
                        steps=[Step(machine_id="M_ONBOARD", duration_hours=2)],
                        due_time_hour=18
                    )],
                ),
                "specs": [ScenarioSpec(scenario_type=ScenarioType.BASELINE)],
                "metrics": [
                    ScenarioMetrics(
                        makespan_hour=2,
                        job_lateness={"J_ONBOARD": 0},
                        bottleneck_machine_id="M_ONBOARD",
                        bottleneck_utilization=0.6,
                    ),
                ],
                "briefing": "# Onboarded Briefing",
                "meta": {
                    "used_default_factory": False,
                    "onboarding_errors": [],
                },
            }

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        # Call /api/simulate with specific factory description
        response = client.post(
            "/api/simulate",
            json={
                "factory_description": "specific onboarding input",
                "situation_text": "test",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify run_onboarded_pipeline was called (proving onboarding happened)
        assert len(called_with) == 1
        assert called_with[0][0] == "specific onboarding input"

        # Verify the response contains the onboarded factory (not toy)
        assert data["factory"]["machines"][0]["id"] == "M_ONBOARD"
        assert data["factory"]["jobs"][0]["id"] == "J_ONBOARD"
