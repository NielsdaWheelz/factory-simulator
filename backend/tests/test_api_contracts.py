"""
Tests for API contracts - ensures /api/simulate and /api/onboard response shapes are frozen and locked.

This test suite verifies that the HTTP response schemas match the frozen contracts defined in backend/API_CONTRACTS.md.

These tests enforce:
- Exact key sets (no additions, no removals) via snapshot assertions
- Correct types for all values
- Proper serialization of enums and nested structures
- meta field presence and structure
- len(specs) == len(metrics) invariant

These tests will FAIL loudly if:
- Response is missing required keys
- Response has unexpected keys
- Types of response values don't match contract
- meta structure is incorrect or missing required fields
- Enum values are not serialized as strings
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

# === CONTRACT SNAPSHOTS (FROZEN KEY SETS) ===
# These constants define the exact allowed keys for each endpoint/structure.
# Any deviation (addition, removal, rename) must update both this file AND frontend/src/types.ts

EXPECTED_SIMULATE_KEYS = {"factory", "specs", "metrics", "briefing", "meta"}
EXPECTED_ONBOARD_KEYS = {"factory", "meta"}
EXPECTED_META_KEYS = {"used_default_factory", "onboarding_errors", "inferred_assumptions"}
EXPECTED_FACTORY_KEYS = {"machines", "jobs"}
EXPECTED_MACHINE_KEYS = {"id", "name"}
EXPECTED_JOB_KEYS = {"id", "name", "steps", "due_time_hour"}
EXPECTED_STEP_KEYS = {"machine_id", "duration_hours"}
EXPECTED_SCENARIO_SPEC_KEYS = {"scenario_type", "rush_job_id", "slowdown_factor"}
EXPECTED_SCENARIO_METRICS_KEYS = {"makespan_hour", "job_lateness", "bottleneck_machine_id", "bottleneck_utilization"}


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


class TestSimulateResponseContractSnapshot:
    """Snapshot tests for /api/simulate - verify exact key sets are frozen."""

    def test_simulate_response_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: /api/simulate response must have exactly these top-level keys, no more, no less."""
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
        actual_keys = set(data.keys())

        assert actual_keys == EXPECTED_SIMULATE_KEYS, (
            f"Simulate response keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_SIMULATE_KEYS)}, Got: {sorted(actual_keys)}"
        )

    def test_simulate_meta_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: meta field must have exactly these keys, no more, no less."""
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
        meta_keys = set(data["meta"].keys())

        assert meta_keys == EXPECTED_META_KEYS, (
            f"Meta field keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_META_KEYS)}, Got: {sorted(meta_keys)}"
        )

    def test_simulate_factory_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: factory field must have exactly machines and jobs keys."""
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
        factory_keys = set(data["factory"].keys())

        assert factory_keys == EXPECTED_FACTORY_KEYS, (
            f"Factory keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_FACTORY_KEYS)}, Got: {sorted(factory_keys)}"
        )

    def test_simulate_machine_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: each machine object must have exactly id and name."""
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
        for machine in data["factory"]["machines"]:
            machine_keys = set(machine.keys())
            assert machine_keys == EXPECTED_MACHINE_KEYS, (
                f"Machine {machine.get('id')} keys do not match. "
                f"Expected: {sorted(EXPECTED_MACHINE_KEYS)}, Got: {sorted(machine_keys)}"
            )

    def test_simulate_job_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: each job object must have exactly id, name, steps, due_time_hour."""
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
        for job in data["factory"]["jobs"]:
            job_keys = set(job.keys())
            assert job_keys == EXPECTED_JOB_KEYS, (
                f"Job {job.get('id')} keys do not match. "
                f"Expected: {sorted(EXPECTED_JOB_KEYS)}, Got: {sorted(job_keys)}"
            )

    def test_simulate_step_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: each step object must have exactly machine_id and duration_hours."""
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
        for job in data["factory"]["jobs"]:
            for step in job["steps"]:
                step_keys = set(step.keys())
                assert step_keys == EXPECTED_STEP_KEYS, (
                    f"Step in job {job.get('id')} has wrong keys. "
                    f"Expected: {sorted(EXPECTED_STEP_KEYS)}, Got: {sorted(step_keys)}"
                )

    def test_simulate_spec_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: each scenario spec must have exactly scenario_type, rush_job_id, slowdown_factor."""
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
        for idx, spec in enumerate(data["specs"]):
            spec_keys = set(spec.keys())
            assert spec_keys == EXPECTED_SCENARIO_SPEC_KEYS, (
                f"Spec {idx} keys do not match. "
                f"Expected: {sorted(EXPECTED_SCENARIO_SPEC_KEYS)}, Got: {sorted(spec_keys)}"
            )

    def test_simulate_metrics_has_exactly_frozen_keys(self, client, mock_pipeline_result, monkeypatch):
        """CRITICAL: each metrics object must have exactly makespan_hour, job_lateness, bottleneck_machine_id, bottleneck_utilization."""
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
        for idx, metric in enumerate(data["metrics"]):
            metric_keys = set(metric.keys())
            assert metric_keys == EXPECTED_SCENARIO_METRICS_KEYS, (
                f"Metrics {idx} keys do not match. "
                f"Expected: {sorted(EXPECTED_SCENARIO_METRICS_KEYS)}, Got: {sorted(metric_keys)}"
            )


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


class TestOnboardResponseContractSnapshot:
    """Snapshot tests for /api/onboard - verify exact key sets are frozen."""

    @pytest.fixture
    def client(self):
        """Return a FastAPI TestClient for the app."""
        return TestClient(app)

    @pytest.fixture
    def valid_factory_config(self):
        """Return a valid FactoryConfig."""
        return FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly"),
                Machine(id="M2", name="Drill"),
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

    def test_onboard_response_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: /api/onboard response must have exactly these top-level keys, no more, no less."""
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
        actual_keys = set(data.keys())

        assert actual_keys == EXPECTED_ONBOARD_KEYS, (
            f"Onboard response keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_ONBOARD_KEYS)}, Got: {sorted(actual_keys)}"
        )

    def test_onboard_meta_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: meta field must have exactly these keys, no more, no less."""
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
        meta_keys = set(data["meta"].keys())

        assert meta_keys == EXPECTED_META_KEYS, (
            f"Meta field keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_META_KEYS)}, Got: {sorted(meta_keys)}"
        )

    def test_onboard_factory_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: factory field must have exactly machines and jobs keys."""
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
        factory_keys = set(data["factory"].keys())

        assert factory_keys == EXPECTED_FACTORY_KEYS, (
            f"Factory keys do not match frozen contract. "
            f"Expected: {sorted(EXPECTED_FACTORY_KEYS)}, Got: {sorted(factory_keys)}"
        )

    def test_onboard_machine_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: each machine object must have exactly id and name."""
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
        for machine in data["factory"]["machines"]:
            machine_keys = set(machine.keys())
            assert machine_keys == EXPECTED_MACHINE_KEYS, (
                f"Machine {machine.get('id')} keys do not match. "
                f"Expected: {sorted(EXPECTED_MACHINE_KEYS)}, Got: {sorted(machine_keys)}"
            )

    def test_onboard_job_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: each job object must have exactly id, name, steps, due_time_hour."""
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
        for job in data["factory"]["jobs"]:
            job_keys = set(job.keys())
            assert job_keys == EXPECTED_JOB_KEYS, (
                f"Job {job.get('id')} keys do not match. "
                f"Expected: {sorted(EXPECTED_JOB_KEYS)}, Got: {sorted(job_keys)}"
            )

    def test_onboard_step_has_exactly_frozen_keys(self, client, valid_factory_config, monkeypatch):
        """CRITICAL: each step object must have exactly machine_id and duration_hours."""
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
        for job in data["factory"]["jobs"]:
            for step in job["steps"]:
                step_keys = set(step.keys())
                assert step_keys == EXPECTED_STEP_KEYS, (
                    f"Step in job {job.get('id')} has wrong keys. "
                    f"Expected: {sorted(EXPECTED_STEP_KEYS)}, Got: {sorted(step_keys)}"
                )
