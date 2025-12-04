"""
Tests for the assemble_factory function.

Tests verify:
- Basic assembly: entities + routing + parameters -> FactoryConfig
- Missing routes: jobs with empty routing produce warnings
- Missing durations: defaults to 1 hour with warning
- Missing due times: defaults to 24 with warning
- Invalid durations: clamped to positive integers
- Unknown machine references: warning generated, step still created
- Determinism: same inputs produce same outputs
- Immutability/purity: function has no side effects
"""

import pytest
from backend.agent_types import FactoryEntities, FactoryRouting, FactoryParameters
from backend.onboarding import assemble_factory, AssemblyResult


class TestAssembleFactoryBasic:
    """Tests for basic assembly behavior."""

    def test_simple_factory_assembly(self):
        """Basic factory with complete data assembles correctly."""
        entities = FactoryEntities(
            machine_ids=["M1", "M2"],
            machine_names={"M1": "Assembly", "M2": "Drill"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2, "M2": 3}},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert isinstance(result, AssemblyResult)
        assert len(result.factory.machines) == 2
        assert len(result.factory.jobs) == 1
        assert result.factory.machines[0].id == "M1"
        assert result.factory.machines[0].name == "Assembly"
        assert result.factory.machines[1].id == "M2"
        assert result.factory.jobs[0].id == "J1"
        assert result.factory.jobs[0].name == "Widget"
        assert result.factory.jobs[0].due_time_hour == 10
        assert len(result.factory.jobs[0].steps) == 2
        assert result.factory.jobs[0].steps[0].machine_id == "M1"
        assert result.factory.jobs[0].steps[0].duration_hours == 2
        assert result.factory.jobs[0].steps[1].machine_id == "M2"
        assert result.factory.jobs[0].steps[1].duration_hours == 3
        assert len(result.warnings) == 0

    def test_multiple_jobs_assembly(self):
        """Factory with multiple jobs assembles all correctly."""
        entities = FactoryEntities(
            machine_ids=["M1", "M2", "M3"],
            machine_names={"M1": "Assembly", "M2": "Drill", "M3": "Pack"},
            job_ids=["J1", "J2"],
            job_names={"J1": "Widget", "J2": "Gadget"},
        )
        routing = FactoryRouting(
            job_routes={
                "J1": ["M1", "M2", "M3"],
                "J2": ["M2", "M3"],
            }
        )
        parameters = FactoryParameters(
            processing_times={
                "J1": {"M1": 1, "M2": 2, "M3": 1},
                "J2": {"M2": 3, "M3": 2},
            },
            due_times={"J1": 8, "J2": 12},
        )

        result = assemble_factory(entities, routing, parameters)

        assert len(result.factory.jobs) == 2
        j1 = next(j for j in result.factory.jobs if j.id == "J1")
        j2 = next(j for j in result.factory.jobs if j.id == "J2")
        assert len(j1.steps) == 3
        assert len(j2.steps) == 2
        assert j1.due_time_hour == 8
        assert j2.due_time_hour == 12

    def test_empty_entities(self):
        """Empty entities produce empty factory."""
        entities = FactoryEntities(
            machine_ids=[],
            machine_names={},
            job_ids=[],
            job_names={},
        )
        routing = FactoryRouting(job_routes={})
        parameters = FactoryParameters(processing_times={}, due_times={})

        result = assemble_factory(entities, routing, parameters)

        assert len(result.factory.machines) == 0
        assert len(result.factory.jobs) == 0
        assert len(result.warnings) == 0


class TestAssembleFactoryMissingNames:
    """Tests for handling missing names."""

    def test_missing_machine_name_uses_id(self):
        """Machine without name in machine_names uses id as name."""
        entities = FactoryEntities(
            machine_ids=["M1", "M2"],
            machine_names={"M1": "Assembly"},  # M2 missing
            job_ids=[],
            job_names={},
        )
        routing = FactoryRouting(job_routes={})
        parameters = FactoryParameters(processing_times={}, due_times={})

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.machines[0].name == "Assembly"
        assert result.factory.machines[1].name == "M2"  # Falls back to id

    def test_missing_job_name_uses_id(self):
        """Job without name in job_names uses id as name."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1", "J2"],
            job_names={"J1": "Widget"},  # J2 missing
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"], "J2": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 1}, "J2": {"M1": 1}},
            due_times={"J1": 10, "J2": 12},
        )

        result = assemble_factory(entities, routing, parameters)

        j1 = next(j for j in result.factory.jobs if j.id == "J1")
        j2 = next(j for j in result.factory.jobs if j.id == "J2")
        assert j1.name == "Widget"
        assert j2.name == "J2"  # Falls back to id


class TestAssembleFactoryMissingRouting:
    """Tests for handling missing routing."""

    def test_missing_routing_produces_warning(self):
        """Job with no routing in job_routes produces warning and empty steps."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={})  # No routing for J1
        parameters = FactoryParameters(
            processing_times={},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert len(result.factory.jobs) == 1
        assert len(result.factory.jobs[0].steps) == 0
        assert any("J1" in w and "no routing" in w.lower() for w in result.warnings)

    def test_empty_routing_list_produces_warning(self):
        """Job with empty routing list produces warning and empty steps."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": []})  # Empty routing
        parameters = FactoryParameters(
            processing_times={},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert len(result.factory.jobs[0].steps) == 0
        assert any("J1" in w and "no routing" in w.lower() for w in result.warnings)


class TestAssembleFactoryMissingDurations:
    """Tests for handling missing durations."""

    def test_missing_duration_defaults_to_one(self):
        """Step without duration defaults to 1 hour (silent default, no warning for missing)."""
        entities = FactoryEntities(
            machine_ids=["M1", "M2"],
            machine_names={"M1": "Assembly", "M2": "Drill"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2}},  # M2 duration missing
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].steps[0].duration_hours == 2
        assert result.factory.jobs[0].steps[1].duration_hours == 1  # Default

    def test_job_missing_from_processing_times(self):
        """Job missing from processing_times gets default durations (silent default)."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={},  # J1 entirely missing
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].steps[0].duration_hours == 1


class TestAssembleFactoryMissingDueTimes:
    """Tests for handling missing due times."""

    def test_missing_due_time_defaults_to_24(self):
        """Job without due time defaults to 24 (silent default)."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2}},
            due_times={},  # J1 missing
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].due_time_hour == 24

    def test_valid_due_time_preserved(self):
        """Job with valid due time has it preserved."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2}},
            due_times={"J1": 15},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].due_time_hour == 15
        assert len(result.warnings) == 0


class TestAssembleFactoryInvalidValues:
    """Tests for handling invalid values that need clamping."""

    def test_negative_duration_clamped_to_one(self):
        """Negative duration is clamped to 1 with warning."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": -5}},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].steps[0].duration_hours == 1
        assert any("invalid" in w.lower() and "clamped" in w.lower() for w in result.warnings)

    def test_zero_duration_clamped_to_one(self):
        """Zero duration is clamped to 1 with warning."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 0}},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].steps[0].duration_hours == 1
        assert any("invalid" in w.lower() and "clamped" in w.lower() for w in result.warnings)

    def test_negative_due_time_clamped_to_24(self):
        """Negative due time is clamped to 24 with warning."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2}},
            due_times={"J1": -5},
        )

        result = assemble_factory(entities, routing, parameters)

        assert result.factory.jobs[0].due_time_hour == 24
        assert any("invalid" in w.lower() and "clamping" in w.lower() for w in result.warnings)


class TestAssembleFactoryUnknownMachines:
    """Tests for handling unknown machine references in routing."""

    def test_unknown_machine_in_routing_produces_warning(self):
        """Step referencing unknown machine still created but warning generated."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})  # M2 not in entities
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2, "M2": 3}},
            due_times={"J1": 10},
        )

        result = assemble_factory(entities, routing, parameters)

        # Step is still created
        assert len(result.factory.jobs[0].steps) == 2
        assert result.factory.jobs[0].steps[1].machine_id == "M2"
        # But warning is generated
        assert any("unknown machine" in w.lower() and "M2" in w for w in result.warnings)


class TestAssembleFactoryDeterminism:
    """Tests for deterministic behavior."""

    def test_assembly_is_deterministic(self):
        """Multiple calls with same inputs produce identical results."""
        entities = FactoryEntities(
            machine_ids=["M1", "M2"],
            machine_names={"M1": "Assembly", "M2": "Drill"},
            job_ids=["J1", "J2"],
            job_names={"J1": "Widget", "J2": "Gadget"},
        )
        routing = FactoryRouting(
            job_routes={"J1": ["M1", "M2"], "J2": ["M2"]}
        )
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2, "M2": 3}, "J2": {"M2": 4}},
            due_times={"J1": 10, "J2": 12},
        )

        result1 = assemble_factory(entities, routing, parameters)
        result2 = assemble_factory(entities, routing, parameters)

        # Factories should be identical
        assert len(result1.factory.machines) == len(result2.factory.machines)
        assert len(result1.factory.jobs) == len(result2.factory.jobs)
        for m1, m2 in zip(result1.factory.machines, result2.factory.machines):
            assert m1.id == m2.id
            assert m1.name == m2.name
        for j1, j2 in zip(result1.factory.jobs, result2.factory.jobs):
            assert j1.id == j2.id
            assert j1.name == j2.name
            assert j1.due_time_hour == j2.due_time_hour
            assert len(j1.steps) == len(j2.steps)
        # Warnings should be identical
        assert result1.warnings == result2.warnings


class TestAssembleFactoryPurity:
    """Tests for pure function behavior (no side effects)."""

    def test_inputs_not_mutated(self):
        """Input objects should not be mutated by assembly."""
        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2}},
            due_times={"J1": 10},
        )

        # Store original values
        original_machine_ids = entities.machine_ids.copy()
        original_job_ids = entities.job_ids.copy()
        original_routes = {k: v.copy() for k, v in routing.job_routes.items()}
        original_times = {k: v.copy() for k, v in parameters.processing_times.items()}
        original_due = parameters.due_times.copy()

        # Call assemble_factory
        result = assemble_factory(entities, routing, parameters)

        # Verify inputs were not mutated
        assert entities.machine_ids == original_machine_ids
        assert entities.job_ids == original_job_ids
        assert routing.job_routes == original_routes
        assert parameters.processing_times == original_times
        assert parameters.due_times == original_due


class TestAssembleFactoryIntegrationWithNormalizeFactory:
    """Tests that assembled factories work correctly with normalize_factory."""

    def test_clean_assembly_passes_normalization(self):
        """Cleanly assembled factory should pass normalize_factory without changes."""
        from backend.onboarding import normalize_factory

        entities = FactoryEntities(
            machine_ids=["M1", "M2"],
            machine_names={"M1": "Assembly", "M2": "Drill"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2, "M2": 3}},
            due_times={"J1": 10},
        )

        assembly_result = assemble_factory(entities, routing, parameters)
        normalized, norm_warnings = normalize_factory(assembly_result.factory)

        # Should pass with no additional normalization needed
        assert len(normalized.machines) == 2
        assert len(normalized.jobs) == 1
        assert len(normalized.jobs[0].steps) == 2

    def test_assembly_with_unknown_machine_has_step_dropped(self):
        """Assembled factory with unknown machine reference should have step dropped by normalization."""
        from backend.onboarding import normalize_factory

        entities = FactoryEntities(
            machine_ids=["M1"],
            machine_names={"M1": "Assembly"},
            job_ids=["J1"],
            job_names={"J1": "Widget"},
        )
        routing = FactoryRouting(job_routes={"J1": ["M1", "M2"]})  # M2 unknown
        parameters = FactoryParameters(
            processing_times={"J1": {"M1": 2, "M2": 3}},
            due_times={"J1": 10},
        )

        assembly_result = assemble_factory(entities, routing, parameters)
        # Assembly creates the step with warning
        assert len(assembly_result.factory.jobs[0].steps) == 2
        assert any("unknown machine" in w.lower() for w in assembly_result.warnings)

        # Normalization drops the invalid step
        normalized, norm_warnings = normalize_factory(assembly_result.factory)
        assert len(normalized.jobs[0].steps) == 1  # M2 step dropped
        assert normalized.jobs[0].steps[0].machine_id == "M1"

