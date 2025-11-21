"""
Tests for stage-0 explicit ID extraction and stage-2 coverage computation.

These tests are deterministic and require no LLM calls.
"""

import pytest
from backend.onboarding import extract_explicit_ids, compute_coverage, FactoryEntities, FactoryEntity


class TestExtractExplicitIds:
    """Tests for extract_explicit_ids function."""

    def test_simple_structured_text(self):
        """Extract IDs from simple structured factory description."""
        factory_text = """We run 3 machines (M1 assembly, M2 drill, M3 pack).
Jobs J1, J2, J3, J4 each pass through those machines in sequence.
J1 takes 2h on M1, 3h on M2, 1h on M3 (total 6h).
J2 takes 1.5h on M1, 2h on M2, 1.5h on M3 (total 5h).
J3 takes 3h on M1, 1h on M2, 2h on M3 (total 6h).
J4 takes 2h on M1, 2h on M2, 4h on M3 (total 8h)."""

        result = extract_explicit_ids(factory_text)

        assert result.machine_ids == {"M1", "M2", "M3"}
        assert result.job_ids == {"J1", "J2", "J3", "J4"}

    def test_descriptive_machine_ids(self):
        """Extract descriptive machine IDs like M_ASSEMBLY."""
        factory_text = "We have 4 machines: M1 (saw), M2 (drill), M_ASSEMBLY (pack), M_WRAP (wrap)."

        result = extract_explicit_ids(factory_text)

        # M_ASSEMBLY and M_WRAP should be detected
        assert "M1" in result.machine_ids
        assert "M2" in result.machine_ids
        assert "M_ASSEMBLY" in result.machine_ids
        assert "M_WRAP" in result.machine_ids

    def test_descriptive_job_ids(self):
        """Extract descriptive job IDs like J_WIDGET_A."""
        factory_text = "Jobs: J_WIDGET_A, J_WIDGET_B, J_GADGET_C are processed."

        result = extract_explicit_ids(factory_text)

        assert result.job_ids == {"J_WIDGET_A", "J_WIDGET_B", "J_GADGET_C"}

    def test_mixed_ids(self):
        """Extract mixed numeric and descriptive IDs."""
        factory_text = """
We have 4 machines: M1, M2, M3, M4.
Jobs: J1, J2, J_SPECIAL, J_RUSH all need processing.
        """

        result = extract_explicit_ids(factory_text)

        assert result.machine_ids == {"M1", "M2", "M3", "M4"}
        assert result.job_ids == {"J1", "J2", "J_SPECIAL", "J_RUSH"}

    def test_word_boundary_respected(self):
        """Word boundaries prevent false matches."""
        factory_text = "Emma's machine (EM1) is broken, but M1 works. Job J1 is important, not J."

        result = extract_explicit_ids(factory_text)

        # EM1 should not match (no word boundary)
        # J should not match (no digit or underscore)
        assert result.machine_ids == {"M1"}
        assert result.job_ids == {"J1"}

    def test_case_sensitive(self):
        """Machine/job IDs are case-sensitive."""
        factory_text = "We have M1 (uppercase) and m1 (lowercase). Jobs J1 and j1."

        result = extract_explicit_ids(factory_text)

        # Only uppercase M1, J1 should be detected
        assert result.machine_ids == {"M1"}
        assert result.job_ids == {"J1"}

    def test_no_ids(self):
        """No IDs in text returns empty sets."""
        factory_text = "We operate some machines and process some jobs."

        result = extract_explicit_ids(factory_text)

        assert result.machine_ids == set()
        assert result.job_ids == set()

    def test_non_uniform_job_paths(self):
        """Extract IDs from non-uniform job routing description."""
        factory_text = """We run 4 machines (M1 assembly, M2 drill, M3 pack, M4 wrap).
Jobs J1, J2, J3 each pass through those machines.
J1 takes 2h on M1, 3h on M2, 1h on M4 (total 6h).
J2 takes 1h on M1, 2h on M2, 1h on M3 (total 4h).
J3 takes 3h on M1, 1h on M2, 2h on M4 (total 6h)."""

        result = extract_explicit_ids(factory_text)

        assert result.machine_ids == {"M1", "M2", "M3", "M4"}
        assert result.job_ids == {"J1", "J2", "J3"}


class TestComputeCoverage:
    """Tests for compute_coverage function."""

    def test_perfect_coverage(self):
        """All detected IDs are enumerated."""
        from backend.onboarding import ExplicitIds

        explicit = ExplicitIds(
            machine_ids={"M1", "M2", "M3"},
            job_ids={"J1", "J2", "J3"},
        )

        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
                FactoryEntity(id="M3", name="pack"),
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),
                FactoryEntity(id="J3", name="Job 3"),
            ],
        )

        coverage = compute_coverage(explicit, entities)

        assert coverage.machine_coverage == 1.0
        assert coverage.job_coverage == 1.0
        assert coverage.missing_machines == set()
        assert coverage.missing_jobs == set()

    def test_missing_one_machine(self):
        """One machine mentioned but not enumerated."""
        from backend.onboarding import ExplicitIds

        explicit = ExplicitIds(
            machine_ids={"M1", "M2", "M3"},
            job_ids={"J1", "J2"},
        )

        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),
            ],
        )

        coverage = compute_coverage(explicit, entities)

        assert coverage.machine_coverage == pytest.approx(2.0 / 3.0)
        assert coverage.job_coverage == 1.0
        assert coverage.missing_machines == {"M3"}
        assert coverage.missing_jobs == set()

    def test_missing_jobs(self):
        """Some jobs mentioned but not enumerated."""
        from backend.onboarding import ExplicitIds

        explicit = ExplicitIds(
            machine_ids={"M1", "M2"},
            job_ids={"J1", "J2", "J3", "J4"},
        )

        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),
            ],
        )

        coverage = compute_coverage(explicit, entities)

        assert coverage.machine_coverage == 1.0
        assert coverage.job_coverage == pytest.approx(2.0 / 4.0)
        assert coverage.missing_machines == set()
        assert coverage.missing_jobs == {"J3", "J4"}

    def test_no_detected_ids(self):
        """Nothing detected in text → coverage = 1.0 (nothing to cover)."""
        from backend.onboarding import ExplicitIds

        explicit = ExplicitIds(machine_ids=set(), job_ids=set())

        entities = FactoryEntities(
            machines=[FactoryEntity(id="M1", name="assembly")],
            jobs=[FactoryEntity(id="J1", name="Job 1")],
        )

        coverage = compute_coverage(explicit, entities)

        # No detected IDs → nothing to cover → coverage = 1.0
        assert coverage.machine_coverage == 1.0
        assert coverage.job_coverage == 1.0

    def test_extra_enumerated_entities(self):
        """LLM inferred additional entities beyond detected IDs."""
        from backend.onboarding import ExplicitIds

        explicit = ExplicitIds(
            machine_ids={"M1", "M2"},
            job_ids={"J1"},
        )

        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
                FactoryEntity(id="M3", name="pack"),  # Inferred
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),  # Inferred
            ],
        )

        coverage = compute_coverage(explicit, entities)

        # All detected IDs are covered, even though extra entities exist
        assert coverage.machine_coverage == 1.0
        assert coverage.job_coverage == 1.0
        assert coverage.missing_machines == set()
        assert coverage.missing_jobs == set()

    def test_non_uniform_scenario(self):
        """Coverage test with non-uniform job paths scenario."""
        from backend.onboarding import ExplicitIds

        factory_text = """We run 4 machines (M1 assembly, M2 drill, M3 pack, M4 wrap).
Jobs J1, J2, J3 each pass through those machines.
J1 takes 2h on M1, 3h on M2, 1h on M4 (total 6h).
J2 takes 1h on M1, 2h on M2, 1h on M3 (total 4h).
J3 takes 3h on M1, 1h on M2, 2h on M4 (total 6h)."""

        explicit = extract_explicit_ids(factory_text)

        # Perfect enumeration
        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
                FactoryEntity(id="M3", name="pack"),
                FactoryEntity(id="M4", name="wrap"),
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),
                FactoryEntity(id="J3", name="Job 3"),
            ],
        )

        coverage = compute_coverage(explicit, entities)

        assert coverage.machine_coverage == 1.0
        assert coverage.job_coverage == 1.0
        assert coverage.missing_machines == set()
        assert coverage.missing_jobs == set()

    def test_under_enumeration_scenario(self):
        """LLM under-enumeration: missing M4 and J3."""
        from backend.onboarding import ExplicitIds

        factory_text = """We run 4 machines (M1 assembly, M2 drill, M3 pack, M4 wrap).
Jobs J1, J2, J3 each pass through those machines.
J1 takes 2h on M1, 3h on M2, 1h on M4 (total 6h).
J2 takes 1h on M1, 2h on M2, 1h on M3 (total 4h).
J3 takes 3h on M1, 1h on M2, 2h on M4 (total 6h)."""

        explicit = extract_explicit_ids(factory_text)

        # Under-enumeration: missing M4 and J3
        entities = FactoryEntities(
            machines=[
                FactoryEntity(id="M1", name="assembly"),
                FactoryEntity(id="M2", name="drill"),
                FactoryEntity(id="M3", name="pack"),
            ],
            jobs=[
                FactoryEntity(id="J1", name="Job 1"),
                FactoryEntity(id="J2", name="Job 2"),
            ],
        )

        coverage = compute_coverage(explicit, entities)

        assert coverage.machine_coverage == pytest.approx(0.75)  # 3/4
        assert coverage.job_coverage == pytest.approx(2.0 / 3.0)  # 2/3
        assert coverage.missing_machines == {"M4"}
        assert coverage.missing_jobs == {"J3"}
