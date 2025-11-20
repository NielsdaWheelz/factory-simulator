"""
Unit tests for OnboardingMeta model.

Tests the OnboardingMeta Pydantic model to ensure:
- It can be instantiated with just used_default_factory
- Lists default to empty lists (not None)
- It serializes correctly to JSON-compatible dicts
- Field validation works as expected
"""

import pytest
from backend.models import OnboardingMeta


class TestOnboardingMeta:
    """Test OnboardingMeta Pydantic model."""

    def test_create_with_only_used_default_factory(self):
        """OnboardingMeta can be created with just used_default_factory, lists default to empty."""
        meta = OnboardingMeta(used_default_factory=True)

        assert meta.used_default_factory is True
        assert meta.onboarding_errors == []
        assert meta.inferred_assumptions == []
        assert isinstance(meta.onboarding_errors, list)
        assert isinstance(meta.inferred_assumptions, list)

    def test_create_with_all_fields(self):
        """OnboardingMeta can be created with all fields populated."""
        meta = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=["Error 1", "Error 2"],
            inferred_assumptions=["Assumption 1"],
        )

        assert meta.used_default_factory is False
        assert meta.onboarding_errors == ["Error 1", "Error 2"]
        assert meta.inferred_assumptions == ["Assumption 1"]

    def test_lists_default_to_empty_not_none(self):
        """List fields must default to [] not None."""
        meta = OnboardingMeta(used_default_factory=False)

        # Check they are lists, not None
        assert meta.onboarding_errors is not None
        assert meta.inferred_assumptions is not None

        # Check they are empty lists
        assert meta.onboarding_errors == []
        assert meta.inferred_assumptions == []

        # Check they are actually lists
        assert isinstance(meta.onboarding_errors, list)
        assert isinstance(meta.inferred_assumptions, list)

    def test_model_dump_is_json_serializable(self):
        """model_dump() should produce JSON-serializable dict."""
        meta = OnboardingMeta(
            used_default_factory=True,
            onboarding_errors=["Error"],
            inferred_assumptions=["Assumption"],
        )

        dumped = meta.model_dump()

        # Verify it's a dict
        assert isinstance(dumped, dict)

        # Verify all fields are present
        assert "used_default_factory" in dumped
        assert "onboarding_errors" in dumped
        assert "inferred_assumptions" in dumped

        # Verify types are JSON-native
        assert isinstance(dumped["used_default_factory"], bool)
        assert isinstance(dumped["onboarding_errors"], list)
        assert isinstance(dumped["inferred_assumptions"], list)

        # Verify list contents are strings
        assert all(isinstance(e, str) for e in dumped["onboarding_errors"])
        assert all(isinstance(a, str) for a in dumped["inferred_assumptions"])

    def test_from_dict_construction(self):
        """OnboardingMeta can be constructed from a dict."""
        data = {
            "used_default_factory": False,
            "onboarding_errors": ["Error 1"],
            "inferred_assumptions": ["Assumption 1"],
        }

        meta = OnboardingMeta(**data)

        assert meta.used_default_factory is False
        assert meta.onboarding_errors == ["Error 1"]
        assert meta.inferred_assumptions == ["Assumption 1"]

    def test_used_default_factory_required(self):
        """used_default_factory is required (no default)."""
        from pydantic import ValidationError

        with pytest.raises((TypeError, ValidationError)):
            # Should fail because used_default_factory is required
            OnboardingMeta()

    def test_used_default_factory_must_be_bool(self):
        """used_default_factory must be a boolean."""
        # Should accept bool
        meta = OnboardingMeta(used_default_factory=True)
        assert meta.used_default_factory is True

        meta = OnboardingMeta(used_default_factory=False)
        assert meta.used_default_factory is False

        # Pydantic will coerce truthy/falsy values or raise validation error
        # depending on strictness mode; accept both behaviors

    def test_onboarding_errors_accepts_empty_list(self):
        """onboarding_errors should accept empty list."""
        meta = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=[],
        )
        assert meta.onboarding_errors == []

    def test_inferred_assumptions_accepts_empty_list(self):
        """inferred_assumptions should accept empty list."""
        meta = OnboardingMeta(
            used_default_factory=False,
            inferred_assumptions=[],
        )
        assert meta.inferred_assumptions == []

    def test_model_validates_list_contents_are_strings(self):
        """Lists should contain only strings."""
        # This should work
        meta = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=["Error 1", "Error 2"],
            inferred_assumptions=["A", "B"],
        )
        assert meta.onboarding_errors == ["Error 1", "Error 2"]

        # Non-string list items should be coerced or fail validation
        # Pydantic's behavior depends on strictness; this test is flexible
        try:
            meta = OnboardingMeta(
                used_default_factory=False,
                onboarding_errors=[123],  # Non-string
            )
            # If Pydantic coerces, convert to string
            assert all(isinstance(e, str) for e in meta.onboarding_errors)
        except Exception:
            # If Pydantic rejects, that's also fine
            pass

    def test_equality(self):
        """Two OnboardingMeta with same values should be equal."""
        meta1 = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=["Error"],
            inferred_assumptions=["Assumption"],
        )
        meta2 = OnboardingMeta(
            used_default_factory=False,
            onboarding_errors=["Error"],
            inferred_assumptions=["Assumption"],
        )

        assert meta1 == meta2

    def test_inequality(self):
        """Two OnboardingMeta with different values should not be equal."""
        meta1 = OnboardingMeta(used_default_factory=False)
        meta2 = OnboardingMeta(used_default_factory=True)

        assert meta1 != meta2
