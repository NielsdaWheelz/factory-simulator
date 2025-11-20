"""
Tests for API contracts - ensures /api/simulate response shape is frozen and locked.

This test suite verifies that the HTTP response schema for /api/simulate
matches the frozen contract defined in backend/API_CONTRACTS.md.

These tests will fail if:
- Response is missing required keys (factory, specs, metrics, briefing, meta)
- Response has unexpected keys
- Types of response values don't match contract
- meta structure is incorrect or missing required fields
"""

import pytest
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
    OnboardingMeta,
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
    ]

    metrics = [
        ScenarioMetrics(
            makespan_hour=5,
            job_lateness={"J1": 0},
            bottleneck_machine_id="M1",
            bottleneck_utilization=0.5,
        ),
    ]

    meta = OnboardingMeta(
        used_default_factory=False,
        onboarding_errors=[],
        inferred_assumptions=[],
    )

    return {
        "factory": factory,
        "situation_text": "normal day",
        "specs": specs,
        "metrics": metrics,
        "briefing": "# Test Briefing\n\nThis is a test briefing.",
        "meta": meta,
    }


class TestSimulateResponseContract:
    """Test that /api/simulate response adheres to frozen contract."""

    def test_response_has_exactly_required_keys(self, client, mock_pipeline_result, monkeypatch):
        """Response must have exactly: factory, specs, metrics, briefing, meta."""
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

        # Verify exactly these keys, no more, no less
        expected_keys = {"factory", "specs", "metrics", "briefing", "meta"}
        actual_keys = set(data.keys())
        assert actual_keys == expected_keys, f"Expected keys {expected_keys}, got {actual_keys}"

    def test_factory_has_correct_structure(self, client, mock_pipeline_result, monkeypatch):
        """factory must have machines and jobs lists."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        factory = data["factory"]

        assert isinstance(factory, dict)
        assert "machines" in factory
        assert "jobs" in factory
        assert isinstance(factory["machines"], list)
        assert isinstance(factory["jobs"], list)
        assert len(factory["machines"]) > 0
        assert len(factory["jobs"]) > 0

        # Verify machine structure
        machine = factory["machines"][0]
        assert "id" in machine
        assert "name" in machine
        assert isinstance(machine["id"], str)
        assert isinstance(machine["name"], str)

        # Verify job structure
        job = factory["jobs"][0]
        assert "id" in job
        assert "name" in job
        assert "steps" in job
        assert "due_time_hour" in job
        assert isinstance(job["steps"], list)
        assert isinstance(job["due_time_hour"], int)

    def test_specs_is_non_empty_list(self, client, mock_pipeline_result, monkeypatch):
        """specs must be a non-empty list of scenario specs."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data["specs"], list)
        assert len(data["specs"]) > 0

        spec = data["specs"][0]
        assert "scenario_type" in spec
        assert isinstance(spec["scenario_type"], str)

    def test_metrics_length_matches_specs(self, client, mock_pipeline_result, monkeypatch):
        """metrics must have same length as specs and same order."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["metrics"]) == len(data["specs"])

        # Verify metrics structure
        metrics = data["metrics"][0]
        assert "makespan_hour" in metrics
        assert "job_lateness" in metrics
        assert "bottleneck_machine_id" in metrics
        assert "bottleneck_utilization" in metrics
        assert isinstance(metrics["makespan_hour"], int)
        assert isinstance(metrics["job_lateness"], dict)
        assert isinstance(metrics["bottleneck_machine_id"], str)
        assert isinstance(metrics["bottleneck_utilization"], (int, float))

    def test_briefing_is_string(self, client, mock_pipeline_result, monkeypatch):
        """briefing must be a string (markdown)."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data["briefing"], str)
        assert len(data["briefing"]) > 0

    def test_meta_has_all_required_fields(self, client, mock_pipeline_result, monkeypatch):
        """meta must have exactly: used_default_factory, onboarding_errors, inferred_assumptions."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Verify exactly these keys
        expected_meta_keys = {
            "used_default_factory",
            "onboarding_errors",
            "inferred_assumptions",
        }
        actual_meta_keys = set(meta.keys())
        assert actual_meta_keys == expected_meta_keys, (
            f"Expected meta keys {expected_meta_keys}, got {actual_meta_keys}"
        )

    def test_meta_field_types(self, client, mock_pipeline_result, monkeypatch):
        """meta fields must have correct types."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Verify field types
        assert isinstance(meta["used_default_factory"], bool)
        assert isinstance(meta["onboarding_errors"], list)
        assert isinstance(meta["inferred_assumptions"], list)

        # Verify list contents are strings
        for error in meta["onboarding_errors"]:
            assert isinstance(error, str)
        for assumption in meta["inferred_assumptions"]:
            assert isinstance(assumption, str)

    def test_meta_lists_default_to_empty(self, client, mock_pipeline_result, monkeypatch):
        """meta lists should default to empty [] not None."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Lists must be lists, not null/None
        assert meta["onboarding_errors"] is not None
        assert meta["inferred_assumptions"] is not None
        assert isinstance(meta["onboarding_errors"], list)
        assert isinstance(meta["inferred_assumptions"], list)

    def test_full_response_is_json_serializable(self, client, mock_pipeline_result, monkeypatch):
        """Entire response must be JSON-serializable without errors."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        # If we can call response.json(), the response is JSON-serializable
        data = response.json()
        assert data is not None
        assert isinstance(data, dict)

    def test_scenario_type_serialized_as_string(self, client, mock_pipeline_result, monkeypatch):
        """ScenarioType enums must be serialized as strings (e.g., 'BASELINE')."""
        def mock_run_onboarded_pipeline(factory_text, situation_text):
            return mock_pipeline_result

        monkeypatch.setattr(
            "backend.server.run_onboarded_pipeline", mock_run_onboarded_pipeline
        )

        response = client.post(
            "/api/simulate",
            json={"factory_description": "test", "situation_text": "test"},
        )

        assert response.status_code == 200
        data = response.json()

        for spec in data["specs"]:
            assert isinstance(spec["scenario_type"], str)
            assert spec["scenario_type"] in ["BASELINE", "RUSH_ARRIVES", "M2_SLOWDOWN"]
