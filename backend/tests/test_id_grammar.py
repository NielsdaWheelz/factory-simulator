"""
Tests for ID grammar helpers (is_machine_id, is_job_id).

These tests verify that the canonical ID grammar is correctly implemented
and that all valid/invalid ID patterns are handled as specified.
"""

import pytest
from backend.onboarding import is_machine_id, is_job_id


class TestIsMachineId:
    """Tests for is_machine_id() helper function."""

    def test_simple_numeric_machine_ids(self):
        """Simple numeric machine IDs like M1, M2, M10."""
        assert is_machine_id("M1") is True
        assert is_machine_id("M2") is True
        assert is_machine_id("M10") is True
        assert is_machine_id("M99") is True

    def test_descriptive_machine_ids_with_underscore(self):
        """Descriptive machine IDs with underscore and alphanumeric chars."""
        assert is_machine_id("M1_ASSEMBLY") is True
        assert is_machine_id("M3_PACK") is True
        assert is_machine_id("M_WIDGET") is True
        assert is_machine_id("M_DRILL_1") is True

    def test_invalid_underscore_first(self):
        """M_1 format (underscore immediately after M and only digit) is invalid."""
        assert is_machine_id("M_1") is False

    def test_invalid_no_digit_or_underscore(self):
        """M alone or M only with letters is invalid."""
        assert is_machine_id("M") is False
        assert is_machine_id("MACHINE1") is False
        assert is_machine_id("MACHINE") is False

    def test_invalid_digit_before_m(self):
        """1M format is invalid (digit before M)."""
        assert is_machine_id("1M") is False

    def test_invalid_with_hyphen(self):
        """M-1 format (with hyphen) is invalid."""
        assert is_machine_id("M-1") is False

    def test_case_sensitive(self):
        """Only uppercase M is valid; lowercase m is not."""
        assert is_machine_id("M1") is True
        assert is_machine_id("m1") is False

    def test_lowercase_suffix_is_valid(self):
        """Machine IDs can have lowercase letters in the suffix."""
        assert is_machine_id("M1_assembly") is True
        assert is_machine_id("M_DRILL_a") is True

    def test_mixed_case_suffix(self):
        """Machine IDs with mixed case in suffix."""
        assert is_machine_id("M1_MixedCase") is True
        assert is_machine_id("M_Widget_A") is True

    def test_numbers_in_suffix(self):
        """Machine IDs can have numbers in the suffix."""
        assert is_machine_id("M1_ASSEMBLY_2") is True
        assert is_machine_id("M2_123") is True

    def test_underscore_only_at_boundaries(self):
        """Underscores in the middle and end are valid."""
        assert is_machine_id("M1_ASSEMBLY") is True
        assert is_machine_id("M1_ASSEMBLY_") is True
        assert is_machine_id("M_A_B_C") is True

    def test_empty_string(self):
        """Empty string is not a valid machine ID."""
        assert is_machine_id("") is False

    def test_whitespace(self):
        """Strings with whitespace are not valid."""
        assert is_machine_id("M 1") is False
        assert is_machine_id("M1 ") is False


class TestIsJobId:
    """Tests for is_job_id() helper function."""

    def test_simple_numeric_job_ids(self):
        """Simple numeric job IDs like J1, J2, J10."""
        assert is_job_id("J1") is True
        assert is_job_id("J2") is True
        assert is_job_id("J10") is True
        assert is_job_id("J99") is True

    def test_descriptive_job_ids_with_underscore(self):
        """Descriptive job IDs with underscore and alphanumeric chars."""
        assert is_job_id("J2_A") is True
        assert is_job_id("J3_WIDGET") is True
        assert is_job_id("J_ORDER") is True
        assert is_job_id("J_WIDGET_A") is True

    def test_invalid_underscore_first(self):
        """J_1 format (underscore immediately after J and only digit) is invalid."""
        assert is_job_id("J_1") is False

    def test_invalid_no_digit_or_underscore(self):
        """J alone or J only with letters is invalid."""
        assert is_job_id("J") is False
        assert is_job_id("JOB1") is False
        assert is_job_id("JOB") is False

    def test_invalid_digit_before_j(self):
        """1J format is invalid (digit before J)."""
        assert is_job_id("1J") is False

    def test_invalid_with_hyphen(self):
        """J-1 format (with hyphen) is invalid."""
        assert is_job_id("J-1") is False

    def test_case_sensitive(self):
        """Only uppercase J is valid; lowercase j is not."""
        assert is_job_id("J1") is True
        assert is_job_id("j1") is False

    def test_lowercase_suffix_is_valid(self):
        """Job IDs can have lowercase letters in the suffix."""
        assert is_job_id("J1_widget") is True
        assert is_job_id("J_order_a") is True

    def test_mixed_case_suffix(self):
        """Job IDs with mixed case in suffix."""
        assert is_job_id("J1_MixedCase") is True
        assert is_job_id("J_Widget_A") is True

    def test_numbers_in_suffix(self):
        """Job IDs can have numbers in the suffix."""
        assert is_job_id("J1_ORDER_2") is True
        assert is_job_id("J2_123") is True

    def test_underscore_only_at_boundaries(self):
        """Underscores in the middle and end are valid."""
        assert is_job_id("J1_WIDGET") is True
        assert is_job_id("J1_WIDGET_") is True
        assert is_job_id("J_A_B_C") is True

    def test_empty_string(self):
        """Empty string is not a valid job ID."""
        assert is_job_id("") is False

    def test_whitespace(self):
        """Strings with whitespace are not valid."""
        assert is_job_id("J 1") is False
        assert is_job_id("J1 ") is False


class TestIdGrammarBoundaries:
    """Test boundary cases and special scenarios."""

    def test_machine_and_job_ids_are_distinct(self):
        """M IDs are machine, J IDs are job."""
        assert is_machine_id("M1") is True
        assert is_job_id("M1") is False
        assert is_job_id("J1") is True
        assert is_machine_id("J1") is False

    def test_prefix_must_be_exact(self):
        """Only M or J prefix is valid (not MM, JJ, etc.)."""
        assert is_machine_id("MM1") is False
        assert is_job_id("JJ1") is False

    def test_leading_zeros_are_valid(self):
        """Leading zeros in machine/job IDs are valid."""
        assert is_machine_id("M01") is True
        assert is_machine_id("M001") is True
        assert is_job_id("J01") is True
        assert is_job_id("J001") is True

    def test_special_chars_not_allowed(self):
        """Only alphanumeric and underscore are allowed."""
        assert is_machine_id("M1@") is False
        assert is_machine_id("M1#") is False
        assert is_machine_id("M1$") is False
        assert is_machine_id("M1.") is False
        assert is_job_id("J1@") is False
        assert is_job_id("J1!") is False

    def test_underscore_multiple_times(self):
        """Multiple underscores in the ID are valid."""
        assert is_machine_id("M_A_B_C") is True
        assert is_job_id("J_A_B_C") is True
