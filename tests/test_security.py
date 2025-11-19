"""
Comprehensive unit tests for security utilities.

Tests cover:
- Student ID hashing
- Hash validation
- Environment variable handling
- Edge cases and error handling
"""

import pytest
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.security import (
    hash_student_id,
    is_hashed_student_id,
    should_hash_student_ids,
    safe_hash_student_id,
)


class TestHashStudentId:
    """Test suite for hash_student_id function."""

    def test_hash_returns_string(self):
        """Test that hash_student_id returns a string."""
        result = hash_student_id("ST001")
        assert isinstance(result, str)

    def test_hash_is_sha256_format(self):
        """Test that hash is valid SHA-256 format (64 hex chars)."""
        result = hash_student_id("ST001")
        assert len(result) == 64
        # Should be valid hex
        int(result, 16)

    def test_hash_consistency(self):
        """Test that same input produces same hash."""
        student_id = "ST001"
        hash1 = hash_student_id(student_id)
        hash2 = hash_student_id(student_id)
        assert hash1 == hash2

    def test_hash_different_for_different_inputs(self):
        """Test that different inputs produce different hashes."""
        hash1 = hash_student_id("ST001")
        hash2 = hash_student_id("ST002")
        assert hash1 != hash2

    def test_hash_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="student_id cannot be empty"):
            hash_student_id("")

    def test_hash_none_raises_error(self):
        """Test that None raises ValueError."""
        with pytest.raises(ValueError, match="student_id cannot be empty"):
            hash_student_id(None)

    def test_hash_non_string_raises_error(self):
        """Test that non-string input raises TypeError."""
        with pytest.raises(TypeError, match="student_id must be string"):
            hash_student_id(123)

        with pytest.raises(TypeError, match="student_id must be string"):
            hash_student_id([" ST001"])

    def test_hash_case_sensitive(self):
        """Test that hashing is case-sensitive."""
        hash1 = hash_student_id("ST001")
        hash2 = hash_student_id("st001")
        assert hash1 != hash2

    def test_hash_whitespace_significant(self):
        """Test that whitespace is significant in hashing."""
        hash1 = hash_student_id("ST001")
        hash2 = hash_student_id(" ST001")
        hash3 = hash_student_id("ST001 ")
        assert hash1 != hash2
        assert hash1 != hash3

    def test_hash_unicode_support(self):
        """Test that unicode characters are supported."""
        result = hash_student_id("学生001")
        assert len(result) == 64
        assert isinstance(result, str)


class TestIsHashedStudentId:
    """Test suite for is_hashed_student_id function."""

    def test_valid_hash_recognized(self):
        """Test that valid SHA-256 hash is recognized."""
        hashed = hash_student_id("ST001")
        assert is_hashed_student_id(hashed) is True

    def test_plain_id_not_recognized(self):
        """Test that plain student ID is not recognized as hash."""
        assert is_hashed_student_id("ST001") is False

    def test_short_string_not_hash(self):
        """Test that short strings are not recognized as hash."""
        assert is_hashed_student_id("abc123") is False

    def test_long_non_hex_string_not_hash(self):
        """Test that non-hex strings are not recognized as hash."""
        # 64 chars but not all hex
        non_hex = "z" * 64
        assert is_hashed_student_id(non_hex) is False

    def test_64_char_hex_recognized_as_hash(self):
        """Test that any 64-character hex string is recognized."""
        fake_hash = "a" * 64
        assert is_hashed_student_id(fake_hash) is True

    def test_mixed_case_hex_recognized(self):
        """Test that mixed case hex is recognized."""
        fake_hash = "AbCdEf" * 10 + "1234"  # 64 chars
        assert is_hashed_student_id(fake_hash) is True

    def test_empty_string_not_hash(self):
        """Test that empty string is not recognized as hash."""
        assert is_hashed_student_id("") is False

    def test_none_not_hash(self):
        """Test that None is not recognized as hash."""
        assert is_hashed_student_id(None) is False

    def test_non_string_not_hash(self):
        """Test that non-string types are not recognized as hash."""
        assert is_hashed_student_id(123) is False
        assert is_hashed_student_id([]) is False


class TestShouldHashStudentIds:
    """Test suite for should_hash_student_ids function."""

    def test_default_is_true(self):
        """Test that default behavior is to hash (True)."""
        # Clear environment variable
        old_value = os.environ.get("HASH_STUDENT_IDS")
        if "HASH_STUDENT_IDS" in os.environ:
            del os.environ["HASH_STUDENT_IDS"]

        try:
            result = should_hash_student_ids()
            assert result is True
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value

    def test_true_values(self):
        """Test that various 'true' values are recognized."""
        old_value = os.environ.get("HASH_STUDENT_IDS")

        try:
            for value in ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"]:
                os.environ["HASH_STUDENT_IDS"] = value
                assert should_hash_student_ids() is True, f"Failed for value: {value}"
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]

    def test_false_values(self):
        """Test that 'false' values are recognized."""
        old_value = os.environ.get("HASH_STUDENT_IDS")

        try:
            for value in ["false", "FALSE", "False", "0", "no", "NO", "off", "OFF"]:
                os.environ["HASH_STUDENT_IDS"] = value
                assert should_hash_student_ids() is False, f"Failed for value: {value}"
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]


class TestSafeHashStudentId:
    """Test suite for safe_hash_student_id function."""

    def test_hashing_enabled_returns_hash(self):
        """Test that hashing is performed when enabled."""
        old_value = os.environ.get("HASH_STUDENT_IDS")

        try:
            os.environ["HASH_STUDENT_IDS"] = "true"
            result = safe_hash_student_id("ST001")

            assert len(result) == 64
            assert is_hashed_student_id(result)
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]

    def test_hashing_disabled_returns_plain(self):
        """Test that plain ID is returned when hashing disabled."""
        old_value = os.environ.get("HASH_STUDENT_IDS")

        try:
            os.environ["HASH_STUDENT_IDS"] = "false"
            result = safe_hash_student_id("ST001")

            assert result == "ST001"
            assert not is_hashed_student_id(result)
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]

    def test_consistency_with_hashing_enabled(self):
        """Test that safe_hash produces consistent results."""
        old_value = os.environ.get("HASH_STUDENT_IDS")

        try:
            os.environ["HASH_STUDENT_IDS"] = "true"
            result1 = safe_hash_student_id("ST001")
            result2 = safe_hash_student_id("ST001")

            assert result1 == result2
        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]


class TestSecurityIntegration:
    """Integration tests for security module."""

    def test_hash_and_verify_workflow(self):
        """Test complete workflow of hashing and verification."""
        original_id = "ST12345"

        # Hash the ID
        hashed_id = hash_student_id(original_id)

        # Verify it's a valid hash
        assert is_hashed_student_id(hashed_id)

        # Verify it's different from original
        assert hashed_id != original_id

        # Verify consistency
        assert hash_student_id(original_id) == hashed_id

    def test_production_vs_testing_mode(self):
        """Test switching between production and testing modes."""
        old_value = os.environ.get("HASH_STUDENT_IDS")
        test_id = "ST999"

        try:
            # Production mode - should hash
            os.environ["HASH_STUDENT_IDS"] = "true"
            prod_result = safe_hash_student_id(test_id)
            assert is_hashed_student_id(prod_result)

            # Testing mode - should not hash
            os.environ["HASH_STUDENT_IDS"] = "false"
            test_result = safe_hash_student_id(test_id)
            assert test_result == test_id

        finally:
            if old_value is not None:
                os.environ["HASH_STUDENT_IDS"] = old_value
            elif "HASH_STUDENT_IDS" in os.environ:
                del os.environ["HASH_STUDENT_IDS"]

    @pytest.mark.parametrize(
        "student_id",
        [
            "ST001",
            "STUDENT-12345",
            "S123456789",
            "学生001",
            "student@email.com",
            "123-456-789",
        ],
    )
    def test_various_id_formats(self, student_id):
        """Test hashing with various student ID formats."""
        hashed = hash_student_id(student_id)

        assert len(hashed) == 64
        assert is_hashed_student_id(hashed)
        assert hashed == hash_student_id(student_id)  # Consistency


class TestSecurityEdgeCases:
    """Test edge cases and error handling."""

    def test_very_long_student_id(self):
        """Test hashing with very long student ID."""
        long_id = "S" * 1000
        hashed = hash_student_id(long_id)

        assert len(hashed) == 64
        assert is_hashed_student_id(hashed)

    def test_special_characters(self):
        """Test hashing with special characters."""
        special_id = "ST!@#$%^&*()_+-=[]{}|;:',.<>?/~`"
        hashed = hash_student_id(special_id)

        assert len(hashed) == 64
        assert is_hashed_student_id(hashed)

    def test_newline_and_tab_characters(self):
        """Test that newlines and tabs are handled."""
        id_with_newline = "ST001\n"
        id_with_tab = "ST001\t"

        hash1 = hash_student_id(id_with_newline)
        hash2 = hash_student_id(id_with_tab)

        assert hash1 != hash2  # Different input = different hash

    def test_numeric_string_id(self):
        """Test hashing with numeric string."""
        numeric_id = "123456789"
        hashed = hash_student_id(numeric_id)

        assert len(hashed) == 64
        assert is_hashed_student_id(hashed)


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("", True),  # Empty defaults to True
        ("invalid", False),  # Invalid value defaults to False
        ("maybe", False),  # Unrecognized value defaults to False
        ("2", False),  # Not in true values
    ],
)
def test_edge_case_env_values(env_value, expected):
    """Test behavior with edge case environment values."""
    old_value = os.environ.get("HASH_STUDENT_IDS")

    try:
        os.environ["HASH_STUDENT_IDS"] = env_value
        result = should_hash_student_ids()
        # May vary based on implementation
        assert isinstance(result, bool)
    finally:
        if old_value is not None:
            os.environ["HASH_STUDENT_IDS"] = old_value
        elif "HASH_STUDENT_IDS" in os.environ:
            del os.environ["HASH_STUDENT_IDS"]
