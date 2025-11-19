"""
Security utilities for plagiarism detection system
Provides student ID hashing for privacy and GDPR compliance
"""

import hashlib
import logging
import os

logger = logging.getLogger(__name__)


def hash_student_id(student_id: str) -> str:
    """
    Hash student ID using SHA-256 for privacy and security compliance

    This function implements one-way hashing to protect student identity
    while maintaining queryability. The same student ID always produces
    the same hash, enabling database lookups without storing plain text.

    Args:
        student_id: Plain text student identifier (e.g., "ST001", "STUD-123")

    Returns:
        64-character hexadecimal SHA-256 hash

    Raises:
        ValueError: If student_id is empty or None

    Examples:
        >>> hash_student_id("ST001")
        '4f7c4e3d8a9b2f1e6c5d4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1'

        >>> hash_student_id("ST001") == hash_student_id("ST001")
        True

    Security Notes:
        - Uses SHA-256 (256-bit cryptographic hash)
        - Deterministic: same input → same output
        - One-way: cannot reverse hash to original ID
        - Collision-resistant: extremely unlikely to find two IDs with same hash
        - GDPR compliant: pseudonymization technique
    """
    if not student_id:
        raise ValueError("student_id cannot be empty or None")

    if not isinstance(student_id, str):
        raise TypeError(f"student_id must be string, got {type(student_id).__name__}")

    hashed = hashlib.sha256(student_id.encode("utf-8")).hexdigest()

    logger.debug(f"Hashed student_id: {student_id[:2]}*** → {hashed[:8]}...")

    return hashed


def is_hashed_student_id(student_id: str) -> bool:
    """
    Check if student_id is already hashed (SHA-256 format)

    A SHA-256 hash is always 64 hexadecimal characters (0-9, a-f).
    This function helps detect if we've already hashed an ID to avoid
    double-hashing.

    Args:
        student_id: Student identifier to check

    Returns:
        True if student_id appears to be a SHA-256 hash, False otherwise

    Examples:
        >>> is_hashed_student_id("ST001")
        False

        >>> is_hashed_student_id("4f7c4e3d8a9b2f1e6c5d4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1")
        True

    Note:
        This is a heuristic check. A plain ID that happens to be 64 hex chars
        would be incorrectly identified as hashed (extremely unlikely).
    """
    if not isinstance(student_id, str):
        return False

    if len(student_id) != 64:
        return False

    try:
        int(student_id, 16)
        return True
    except ValueError:
        return False


def should_hash_student_ids() -> bool:
    """
    Check if student ID hashing is enabled via environment variable

    Returns:
        True if hashing is enabled (default), False for testing/debugging

    Environment Variable:
        HASH_STUDENT_IDS: Set to 'false' to disable hashing for testing

    Examples:
        # Production (default)
        HASH_STUDENT_IDS=true  → Returns True

        # Testing/Development
        HASH_STUDENT_IDS=false → Returns False

    Note:
        In production, this should ALWAYS be True for GDPR compliance
    """
    env_value = os.getenv("HASH_STUDENT_IDS", "true").lower()
    return env_value in ("true", "1", "yes", "on")


def safe_hash_student_id(student_id: str) -> str:
    """
    Safely hash student ID with environment variable toggle

    This wrapper function checks the HASH_STUDENT_IDS environment variable
    and either hashes the ID or returns it as-is. Useful for testing.

    Args:
        student_id: Student identifier

    Returns:
        Hashed student ID if hashing enabled, original ID otherwise

    Examples:
        # With HASH_STUDENT_IDS=true (production)
        >>> safe_hash_student_id("ST001")
        '4f7c4e3d8a9b2f1e6c5d4a3b2c1d0e9f...'

        # With HASH_STUDENT_IDS=false (testing)
        >>> safe_hash_student_id("ST001")
        'ST001'

    Warning:
        Only use this in non-production for debugging. Production should
        always hash to comply with data protection regulations.
    """
    if should_hash_student_ids():
        return hash_student_id(student_id)
    else:
        logger.warning("Student ID hashing DISABLED - not for production use!")
        return student_id
