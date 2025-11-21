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
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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

    def test_onboard_with_coverage_mismatch_falls_back(self, client, monkeypatch):
        """Test that OnboardingAgent raising COVERAGE_MISMATCH triggers fallback."""
        from backend.onboarding import ExtractionError

        # Agent raises coverage mismatch error
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="COVERAGE_MISMATCH",
                message="coverage mismatch: missing machines ['M2'], missing jobs []",
                details={
                    "missing_machines": ["M2"],
                    "missing_jobs": [],
                    "machine_coverage": 0.5,
                    "job_coverage": 1.0,
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "factory with M1, M2"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify fallback and error message
        meta = data["meta"]
        assert meta["used_default_factory"] is True
        assert len(meta["onboarding_errors"]) > 0
        assert "COVERAGE_MISMATCH" in meta["onboarding_errors"][0]

        # Should have fallback factory
        factory = data["factory"]
        assert len(factory["machines"]) == 3  # toy factory

    def test_onboard_fallback_on_normalization_error(self, client, monkeypatch):
        """Test fallback when agent raises NORMALIZATION_FAILED."""
        from backend.onboarding import ExtractionError

        # Agent raises normalization error
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="NORMALIZATION_FAILED",
                message="Jobs were lost during normalization: ['J1']",
                details={
                    "raw_job_ids": ["J1"],
                    "normalized_job_ids": [],
                    "missing_job_ids": ["J1"],
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "factory with bad jobs"},
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

    def test_onboard_fallback_on_invalid_structure(self, client, monkeypatch):
        """Test fallback when agent raises INVALID_STRUCTURE."""
        from backend.onboarding import ExtractionError

        # Agent raises structure error (during normalization)
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message="Step in job J1 references non-existent machine M999",
                details={
                    "job_id": "J1",
                    "step_machine_id": "M999",
                    "available_machines": ["M1", "M2"],
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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

    def test_onboard_with_invalid_due_time_fallback(self, client, monkeypatch):
        """Test that agent raises error for invalid due_time_hour and triggers fallback."""
        from backend.onboarding import ExtractionError

        # Agent raises validation error for negative due_time_hour
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message="Job J1 has invalid due_time_hour: -5",
                details={
                    "job_id": "J1",
                    "due_time_hour": -5,
                    "valid_range": "0-24",
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "negative due time"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Should have fallback due to validation error
        assert meta["used_default_factory"] is True
        assert len(meta["onboarding_errors"]) > 0
        error_msg = "\n".join(meta["onboarding_errors"])
        assert "INVALID_STRUCTURE" in error_msg

    def test_onboard_inferred_assumptions_empty(self, client, valid_factory_config, monkeypatch):
        """Verify inferred_assumptions is empty in PR1 (stub version)."""

        def mock_onboarding_agent_run(self, factory_text):
            return valid_factory_config

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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
            "backend.agents.OnboardingAgent.run",
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
        """Test that agent raises error when LLM produces jobs with invalid refs."""
        from backend.onboarding import ExtractionError

        # Agent raises error because LLM created jobs with invalid machine refs
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message="Step in job J2 references non-existent machine M999",
                details={
                    "job_id": "J2",
                    "step_machine_id": "M999",
                    "available_machines": ["M1", "M2"],
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "mixed"},
        )

        assert response.status_code == 200
        data = response.json()
        meta = data["meta"]

        # Should fallback due to invalid structure
        assert meta["used_default_factory"] is True
        assert len(meta["onboarding_errors"]) > 0

        # Should return toy factory
        factory = data["factory"]
        assert len(factory["machines"]) == 3  # toy factory
        assert len(factory["jobs"]) == 3


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
            "backend.agents.OnboardingAgent.run",
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

    def test_onboard_raises_on_empty_detected_ids(self, client, monkeypatch):
        """Test that agent raises error when no IDs are detected in text."""
        from backend.onboarding import ExtractionError

        # Agent raises error because no machine/job IDs detected in text
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="COVERAGE_MISMATCH",
                message="coverage mismatch: no IDs detected in text",
                details={
                    "missing_machines": [],
                    "missing_jobs": [],
                    "machine_coverage": 1.0,
                    "job_coverage": 1.0,
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
            mock_onboarding_agent_run,
        )

        response = client.post(
            "/api/onboard",
            json={"factory_description": "This has no machine or job IDs"},
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

    def test_onboard_llm_agent_detects_invalid_data_and_falls_back(self, client, monkeypatch):
        """Test that agent detects invalid data in LLM response and raises error."""
        from backend.onboarding import ExtractionError

        # Agent detected that LLM produced jobs with invalid machine refs
        def mock_onboarding_agent_run(self, factory_text):
            raise ExtractionError(
                code="INVALID_STRUCTURE",
                message="Step in job J2 references non-existent machine M999",
                details={
                    "job_id": "J2",
                    "step_machine_id": "M999",
                    "available_machines": ["M1", "M2"],
                },
            )

        monkeypatch.setattr(
            "backend.agents.OnboardingAgent.run",
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

        # Should use fallback due to invalid structure
        assert meta["used_default_factory"] is True

        # Should have errors
        assert len(meta["onboarding_errors"]) > 0

        # Should be toy factory
        assert len(factory["machines"]) == 3
        assert len(factory["jobs"]) == 3
