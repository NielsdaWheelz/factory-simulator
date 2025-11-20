"""
Tests for server.py - FastAPI endpoint for /api/onboard.

Verifies:
- Endpoint accepts correct request shape (OnboardingRequest)
- Endpoint returns JSON-serializable response (OnboardingResponse)
- Response includes all required fields with correct types
- Normalization is wired correctly through the endpoint
- Fallback behavior works exactly per spec
- No simulation/agent logic is triggered (IntentAgent, FuturesAgent, etc.)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.server import app
from backend.models import (
    FactoryConfig,
    Machine,
    Job,
    Step,
    OnboardingMeta,
    OnboardingRequest,
)
from backend.world import build_toy_factory


@pytest.fixture
def client():
    """Return a FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture
def valid_factory_config():
    """Return a valid FactoryConfig."""
    return FactoryConfig(
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
            Job(
                id="J2",
                name="Job 2",
                steps=[Step(machine_id="M2", duration_hours=3)],
                due_time_hour=20,
            ),
        ],
    )


class TestOnboardEndpoint:
    """Test the POST /api/onboard endpoint."""

    def test_onboard_endpoint_smoke(self, client, valid_factory_config, monkeypatch):
        """Smoke test: endpoint accepts request and returns 200 with JSON response."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "3 machines, 2 jobs"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all required top-level keys present
        assert "factory" in data
        assert "meta" in data

    def test_onboard_endpoint_response_shape(self, client, valid_factory_config, monkeypatch):
        """Verify response structure matches OnboardingResponse schema."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test factory"},
        )

        assert response.status_code == 200
        data = response.json()

        # Check factory structure
        assert isinstance(data["factory"], dict)
        assert "machines" in data["factory"]
        assert "jobs" in data["factory"]
        assert isinstance(data["factory"]["machines"], list)
        assert isinstance(data["factory"]["jobs"], list)

        # Check machines and jobs
        machines = data["factory"]["machines"]
        assert len(machines) > 0
        assert "id" in machines[0]
        assert "name" in machines[0]

        jobs = data["factory"]["jobs"]
        assert len(jobs) > 0
        assert "id" in jobs[0]
        assert "name" in jobs[0]
        assert "steps" in jobs[0]
        assert "due_time_hour" in jobs[0]

        # Check steps
        steps = jobs[0]["steps"]
        assert len(steps) > 0
        assert "machine_id" in steps[0]
        assert "duration_hours" in steps[0]

        # Check meta
        assert isinstance(data["meta"], dict)
        assert "used_default_factory" in data["meta"]
        assert "onboarding_errors" in data["meta"]
        assert "inferred_assumptions" in data["meta"]

    def test_onboard_meta_contract(self, client, valid_factory_config, monkeypatch):
        """Verify OnboardingMeta has correct field types."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Check meta field types
        assert isinstance(meta["used_default_factory"], bool)
        assert isinstance(meta["onboarding_errors"], list)
        assert isinstance(meta["inferred_assumptions"], list)
        assert all(isinstance(e, str) for e in meta["onboarding_errors"])
        assert all(isinstance(e, str) for e in meta["inferred_assumptions"])

    def test_onboard_request_validation(self, client):
        """Verify that endpoint validates request shape."""
        # Missing factory_description
        response = client.post(
            "/api/onboard",
            json={},
        )
        assert response.status_code == 422  # Unprocessable entity

    def test_onboard_with_normalization_warnings(self, client, monkeypatch):
        """Test that normalization warnings are included in onboarding_errors."""
        # Create a factory with bad durations and invalid machine refs
        bad_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
                Machine(id="M2", name="Drill"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[
                        Step(machine_id="M1", duration_hours=0),  # Bad duration
                        Step(machine_id="M999", duration_hours=2),  # Invalid machine ref
                    ],
                    due_time_hour=24,
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return bad_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "bad factory"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify normalization warnings are in onboarding_errors
        meta = data["meta"]
        assert isinstance(meta["onboarding_errors"], list)
        assert len(meta["onboarding_errors"]) > 0

        # Check that specific warning about bad duration is present
        error_messages = "\n".join(meta["onboarding_errors"])
        assert "duration_hours" in error_messages.lower() or "dropped" in error_messages.lower()

        # Factory should not be fallback (still has valid job with one valid step)
        assert meta["used_default_factory"] is False

    def test_onboard_fallback_on_empty_machines(self, client, monkeypatch):
        """Test fallback when normalization results in zero machines."""
        # Factory with no machines
        empty_machines_factory = FactoryConfig(
            machines=[],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return empty_machines_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "factory with no machines"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Verify fallback was triggered
        assert meta["used_default_factory"] is True
        # After fallback, we get the toy factory (3 machines, 3 jobs)
        factory = data["factory"]
        assert len(factory["machines"]) == 3
        assert len(factory["jobs"]) == 3

    def test_onboard_fallback_on_empty_jobs(self, client, monkeypatch):
        """Test fallback when normalization results in zero jobs."""
        # Factory with valid machines but jobs with only invalid machine refs
        empty_jobs_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
                Machine(id="M2", name="Drill"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M999", duration_hours=2)],  # Invalid ref
                    due_time_hour=24,
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return empty_jobs_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "factory with invalid job refs"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Verify fallback was triggered
        assert meta["used_default_factory"] is True
        # After fallback, we get the toy factory (3 machines, 3 jobs)
        factory = data["factory"]
        assert len(factory["machines"]) == 3
        assert len(factory["jobs"]) == 3

    def test_onboard_no_simulation_logic(self, client, valid_factory_config, monkeypatch):
        """Verify that calling /api/onboard does not trigger IntentAgent, FuturesAgent, or simulation."""
        mock_intent_agent = MagicMock()
        mock_futures_agent = MagicMock()
        mock_briefing_agent = MagicMock()
        mock_simulate = MagicMock()
        mock_compute_metrics = MagicMock()

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )
        monkeypatch.setattr(
            "backend.orchestrator.IntentAgent",
            mock_intent_agent,
        )
        monkeypatch.setattr(
            "backend.orchestrator.FuturesAgent",
            mock_futures_agent,
        )
        monkeypatch.setattr(
            "backend.orchestrator.BriefingAgent",
            mock_briefing_agent,
        )
        monkeypatch.setattr(
            "backend.orchestrator.simulate",
            mock_simulate,
        )
        monkeypatch.setattr(
            "backend.orchestrator.compute_metrics",
            mock_compute_metrics,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test"},
        )

        assert response.status_code == 200

        # Verify no agents or simulation were called
        assert not mock_intent_agent.called
        assert not mock_futures_agent.called
        assert not mock_briefing_agent.called
        assert not mock_simulate.called
        assert not mock_compute_metrics.called

    def test_onboard_preserves_valid_factory(self, client, valid_factory_config, monkeypatch):
        """Test that a valid factory is preserved without fallback."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "valid factory"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]
        factory = data["factory"]

        # Verify no fallback
        assert meta["used_default_factory"] is False
        assert len(meta["onboarding_errors"]) == 0

        # Verify original factory is returned (not toy factory)
        assert len(factory["machines"]) == 3
        assert len(factory["jobs"]) == 2
        assert factory["machines"][0]["id"] == "M1"
        assert factory["jobs"][0]["id"] == "J1"

    def test_onboard_all_types_json_serializable(
        self, client, valid_factory_config, monkeypatch
    ):
        """Verify entire response can be JSON-serialized without errors."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test"},
        )

        assert response.status_code == 200
        # If we got here, response.json() worked, so it's JSON-serializable
        data = response.json()
        assert data is not None
        assert "factory" in data
        assert "meta" in data

    def test_onboard_with_negative_due_time(self, client, monkeypatch):
        """Test that negative due times are normalized and warnings generated."""
        bad_due_time_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
            ],
            jobs=[
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=2)],
                    due_time_hour=-5,  # Negative due time
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return bad_due_time_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "negative due time"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Should have a warning about due_time_hour
        assert meta["used_default_factory"] is False
        assert len(meta["onboarding_errors"]) > 0
        error_msg = "\n".join(meta["onboarding_errors"])
        assert "due_time_hour" in error_msg.lower() or "clamped" in error_msg.lower()

    def test_onboard_inferred_assumptions_empty(self, client, valid_factory_config, monkeypatch):
        """Verify inferred_assumptions is empty in PR1 (stub version)."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # In PR1, inferred_assumptions should always be empty
        assert meta["inferred_assumptions"] == []

    def test_onboard_factory_config_schema_compliance(self, client, valid_factory_config, monkeypatch):
        """Verify returned factory matches FactoryConfig schema."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "test"},
        )

        assert response.status_code == 200
        data = response.json()
        factory = data["factory"]

        # Check that we can reconstruct FactoryConfig from response
        reconstructed = FactoryConfig(**factory)
        assert reconstructed is not None
        assert len(reconstructed.machines) > 0
        assert len(reconstructed.jobs) > 0

    def test_onboard_empty_description(self, client, valid_factory_config, monkeypatch):
        """Test endpoint with empty factory description."""

        def mock_onboarding_agent_run(self, factory_text):
            # OnboardingAgent stub returns toy factory for empty text
            return valid_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": ""},
        )

        assert response.status_code == 200
        data = response.json()
        assert "factory" in data
        assert "meta" in data

    def test_onboard_mixed_valid_and_invalid_jobs(self, client, monkeypatch):
        """Test with mixed valid and invalid jobs."""
        mixed_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
                Machine(id="M2", name="Drill"),
            ],
            jobs=[
                # Valid job
                Job(
                    id="J1",
                    name="Good Job",
                    steps=[Step(machine_id="M1", duration_hours=2)],
                    due_time_hour=24,
                ),
                # Job with invalid machine ref (will be dropped)
                Job(
                    id="J2",
                    name="Bad Job",
                    steps=[Step(machine_id="M999", duration_hours=2)],
                    due_time_hour=24,
                ),
                # Job with bad duration (will be normalized)
                Job(
                    id="J3",
                    name="Bad Duration Job",
                    steps=[Step(machine_id="M2", duration_hours=0)],
                    due_time_hour=24,
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return mixed_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "mixed"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]
        factory = data["factory"]

        # Should not use fallback (has valid jobs)
        assert meta["used_default_factory"] is False

        # Should have warnings about dropped and normalized jobs
        assert len(meta["onboarding_errors"]) > 0

        # Should have at least J1 and J3 (J2 dropped due to invalid refs)
        job_ids = {job["id"] for job in factory["jobs"]}
        assert "J1" in job_ids
        assert "J3" in job_ids
        # J2 should be dropped
        assert "J2" not in job_ids


class TestOnboardEndpointWithLLMAgent:
    """Test /api/onboard endpoint with LLM-backed OnboardingAgent."""

    @pytest.fixture
    def client(self):
        """Return a FastAPI TestClient for the app."""
        return TestClient(app)

    @pytest.fixture
    def custom_factory_config(self):
        """Return a custom FactoryConfig different from the default."""
        return FactoryConfig(
            machines=[
                Machine(id="ASSEM", name="Assembly Station"),
                Machine(id="DRILL", name="Drill Machine"),
            ],
            jobs=[
                Job(
                    id="JOB_A",
                    name="Product A",
                    steps=[
                        Step(machine_id="ASSEM", duration_hours=2),
                        Step(machine_id="DRILL", duration_hours=1),
                    ],
                    due_time_hour=10,
                ),
                Job(
                    id="JOB_B",
                    name="Product B",
                    steps=[
                        Step(machine_id="DRILL", duration_hours=2),
                    ],
                    due_time_hour=15,
                ),
            ],
        )

    def test_onboard_uses_llm_factory_when_available(self, client, custom_factory_config, monkeypatch):
        """Test that /api/onboard uses OnboardingAgent-produced factory (not toy factory)."""

        def mock_onboarding_agent_run(self, factory_text):
            return custom_factory_config

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "Custom factory description"},
        )

        assert response.status_code == 200
        data = response.json()
        factory = data["factory"]
        meta = data["meta"]

        # Should NOT use fallback (factory is valid)
        assert meta["used_default_factory"] is False

        # Verify it's the custom factory, not the toy factory
        assert len(factory["machines"]) == 2
        assert len(factory["jobs"]) == 2
        assert factory["machines"][0]["id"] == "ASSEM"
        assert factory["jobs"][0]["id"] == "JOB_A"
        assert factory["jobs"][0]["due_time_hour"] == 10

    def test_onboard_falls_back_if_onboarding_agent_returns_empty_factory(self, client, monkeypatch):
        """Test that /api/onboard falls back if OnboardingAgent returns empty factory."""
        empty_factory = FactoryConfig(machines=[], jobs=[])

        def mock_onboarding_agent_run(self, factory_text):
            return empty_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "This results in empty factory"},
        )

        assert response.status_code == 200
        data = response.json()
        factory = data["factory"]
        meta = data["meta"]

        # Should use fallback
        assert meta["used_default_factory"] is True

        # Should have fallback warning
        assert len(meta["onboarding_errors"]) > 0

        # Factory should be the toy factory
        assert len(factory["machines"]) == 3
        assert len(factory["jobs"]) == 3
        toy = build_toy_factory()
        assert factory["machines"][0]["id"] == toy.machines[0].id

    def test_onboard_llm_agent_with_partially_valid_factory(self, client, monkeypatch):
        """Test /api/onboard when OnboardingAgent returns factory with some invalid data."""
        partially_valid_factory = FactoryConfig(
            machines=[
                Machine(id="M1", name="Machine 1"),
                Machine(id="M2", name="Machine 2"),
            ],
            jobs=[
                # Valid job
                Job(
                    id="J1",
                    name="Job 1",
                    steps=[Step(machine_id="M1", duration_hours=3)],
                    due_time_hour=12,
                ),
                # Job with invalid machine reference
                Job(
                    id="J2",
                    name="Job 2",
                    steps=[Step(machine_id="M999", duration_hours=2)],
                    due_time_hour=15,
                ),
                # Job with bad duration
                Job(
                    id="J3",
                    name="Job 3",
                    steps=[Step(machine_id="M2", duration_hours=0)],
                    due_time_hour=20,
                ),
            ],
        )

        def mock_onboarding_agent_run(self, factory_text):
            return partially_valid_factory

        monkeypatch.setattr(
            "backend.server.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "Factory with some issues"},
        )

        assert response.status_code == 200
        data = response.json()
        factory = data["factory"]
        meta = data["meta"]

        # Should NOT use fallback (has valid jobs after repair)
        assert meta["used_default_factory"] is False

        # Should have errors for normalization
        assert len(meta["onboarding_errors"]) > 0

        # Jobs should be filtered/normalized
        job_ids = {job["id"] for job in factory["jobs"]}
        assert "J1" in job_ids  # Valid job preserved
        assert "J2" not in job_ids  # Job with invalid machine ref dropped
        assert "J3" in job_ids  # Job with bad duration normalized (not dropped)

        # Check that J3's duration was normalized to 1
        j3 = next((j for j in factory["jobs"] if j["id"] == "J3"), None)
        assert j3 is not None
        assert j3["steps"][0]["duration_hours"] == 1  # Normalized from 0
