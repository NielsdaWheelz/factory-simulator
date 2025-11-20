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
