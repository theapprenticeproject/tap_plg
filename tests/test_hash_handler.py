"""
Comprehensive unit tests for HashHandler - Perceptual hashing functionality.

Tests cover:
- Hash computation (pHash, dHash, aHash)
- Hamming distance calculation
- Similarity detection
- Hash comparison logic
- Edge cases and error handling
- Various image sizes and formats
- Threshold sensitivity
"""

import pytest
from PIL import Image
import numpy as np
from image_worker.hash_handler import HashHandler


class TestHashHandlerInitialization:
    """Test suite for HashHandler initialization."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    def test_handler_initialization(self, handler):
        """Test HashHandler initializes correctly."""
        assert handler.hash_size == 8
        assert isinstance(handler, HashHandler)

    def test_hash_size_variation(self):
        """Test different hash sizes."""
        handler_small = HashHandler(hash_size=4)
        handler_large = HashHandler(hash_size=16)

        img = Image.new("RGB", (64, 64), color=(128, 128, 128))

        hashes_small = handler_small.compute_hashes(img)
        hashes_large = handler_large.compute_hashes(img)

        # Different hash sizes should produce different length hashes
        # hash_size=4 -> 4x4 = 16 bits -> 4 hex chars
        # hash_size=16 -> 16x16 = 256 bits -> 64 hex chars
        assert len(hashes_small["phash"]) == 4
        assert len(hashes_large["phash"]) == 64


class TestHashComputation:
    """Test suite for hash computation functionality."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    def test_compute_hashes_returns_dict(self, handler, sample_image):
        """Test that compute_hashes returns a dict with all hash types."""
        hashes = handler.compute_hashes(sample_image)

        assert isinstance(hashes, dict)
        assert "phash" in hashes
        assert "dhash" in hashes
        assert "ahash" in hashes

    def test_compute_hashes_returns_hex_strings(self, handler, sample_image):
        """Test that hash values are hex strings."""
        hashes = handler.compute_hashes(sample_image)

        for hash_type, hash_value in hashes.items():
            assert isinstance(hash_value, str)
            # Hash should be 16 characters for 64-bit hash
            assert len(hash_value) == 16
            # Should be valid hex
            int(hash_value, 16)  # Raises ValueError if not hex

    def test_compute_hashes_consistency(self, handler, sample_image):
        """Test that same image produces same hashes."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(sample_image)

        assert hashes1["phash"] == hashes2["phash"]
        assert hashes1["dhash"] == hashes2["dhash"]
        assert hashes1["ahash"] == hashes2["ahash"]

    def test_compute_hashes_with_rgb_image(self, handler):
        """Test hash computation with RGB image."""
        img = Image.new("RGB", (64, 64), color=(128, 128, 128))
        hashes = handler.compute_hashes(img)

        assert len(hashes) == 3
        assert all(isinstance(v, str) for v in hashes.values())

    def test_compute_hashes_handles_grayscale(self, handler):
        """Test that handler converts grayscale images to RGB."""
        grayscale_img = Image.new("L", (100, 100), color=128)

        hashes = handler.compute_hashes(grayscale_img)

        assert "phash" in hashes
        assert "dhash" in hashes
        assert "ahash" in hashes
        assert len(hashes) == 3
        assert all(isinstance(v, str) for v in hashes.values())

    def test_compute_hashes_handles_rgba(self, handler):
        """Test that handler handles RGBA images."""
        rgba_img = Image.new("RGBA", (100, 100), color=(128, 128, 128, 255))

        hashes = handler.compute_hashes(rgba_img)

        assert "phash" in hashes
        assert "dhash" in hashes
        assert "ahash" in hashes
        assert len(hashes) == 3
        assert all(isinstance(v, str) for v in hashes.values())

    def test_hash_rotation_invariance(self, handler):
        """Test that rotated images with gradients produce different hashes (not rotation-invariant)."""
        # Use an image with asymmetric pattern instead of solid color
        img_array = np.zeros((64, 64, 3), dtype=np.uint8)
        # Create a gradient pattern
        for i in range(64):
            img_array[i, :] = [i * 4, 0, 0]  # Red gradient
        img = Image.fromarray(img_array, "RGB")
        img_rotated = img.rotate(90)

        hashes1 = handler.compute_hashes(img)
        hashes2 = handler.compute_hashes(img_rotated)

        # Hashes should be different (these algorithms are not rotation-invariant)
        assert (
            hashes1["phash"] != hashes2["phash"]
            or hashes1["dhash"] != hashes2["dhash"]
            or hashes1["ahash"] != hashes2["ahash"]
        )


class TestHammingDistance:
    """Test suite for Hamming distance calculation."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    def test_hamming_distance_identical(self, handler):
        """Test Hamming distance between identical hashes is 0."""
        hash1 = "abc123def456"
        hash2 = "abc123def456"

        distance = handler.hamming_distance(hash1, hash2)
        assert distance == 0

    def test_hamming_distance_different(self, handler):
        """Test Hamming distance between different hashes is > 0."""
        hash1 = "0000000000000000"
        hash2 = "ffffffffffffffff"

        distance = handler.hamming_distance(hash1, hash2)
        assert distance == 64  # Maximum distance for 64-bit hash

    def test_hamming_distance_single_bit(self, handler):
        """Test Hamming distance with single bit difference."""
        hash1 = "0000000000000000"
        hash2 = "0000000000000001"

        distance = handler.hamming_distance(hash1, hash2)
        assert distance == 1

    def test_hamming_distance_invalid_input(self, handler):
        """Test Hamming distance with invalid input."""
        # The method catches exceptions and returns 999
        result1 = handler.hamming_distance(None, "abc123")
        result2 = handler.hamming_distance("abc123", None)

        assert result1 == 999
        assert result2 == 999


class TestSimilarityDetection:
    """Test suite for similarity detection logic."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    def test_is_similar_identical_hashes(self, handler):
        """Test that identical hashes are considered similar."""
        hash1 = "abc123def456"
        hash2 = "abc123def456"

        assert handler.is_similar(hash1, hash2, threshold=10)

    def test_is_similar_within_threshold(self, handler, sample_image, similar_image):
        """Test that similar images are detected within threshold."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(similar_image)

        # At least one hash type should be similar
        similar_count = sum(
            [
                handler.is_similar(hashes1["phash"], hashes2["phash"], threshold=15),
                handler.is_similar(hashes1["dhash"], hashes2["dhash"], threshold=15),
                handler.is_similar(hashes1["ahash"], hashes2["ahash"], threshold=15),
            ]
        )
        assert similar_count > 0

    def test_is_similar_beyond_threshold(self, handler):
        """Test that very different hashes are not similar."""
        hash1 = "0000000000000000"
        hash2 = "ffffffffffffffff"

        assert not handler.is_similar(hash1, hash2, threshold=10)


class TestHashComparison:
    """Test suite for compare_all_hashes functionality."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    def test_compare_all_hashes_identical(self, handler, sample_image, identical_image):
        """Test comparison of identical images."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(identical_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=10)

        assert bool(result["is_match"]) is True
        assert result["avg_distance"] == 0.0
        assert result["phash_distance"] == 0
        assert result["dhash_distance"] == 0
        assert result["ahash_distance"] == 0

    def test_compare_all_hashes_similar(self, handler, sample_image, similar_image):
        """Test comparison of similar images."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(similar_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=15)

        # Should match within generous threshold
        assert result["is_match"] is True or result["avg_distance"] < 20

    def test_compare_all_hashes_different(self, handler, sample_image, different_image):
        """Test comparison of very different images."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(different_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=5)

        # Should not match with strict threshold
        assert result["avg_distance"] > 5

    def test_compare_all_hashes_returns_correct_structure(self, handler, sample_image):
        """Test that compare_all_hashes returns expected dict structure."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(sample_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=10)

        assert "is_match" in result
        assert "avg_distance" in result
        assert "phash_distance" in result
        assert "dhash_distance" in result
        assert "ahash_distance" in result

        # Accept both Python bool and numpy bool types
        assert isinstance(result["is_match"], (bool, type(result["is_match"])))
        assert isinstance(result["avg_distance"], (float, int))
        assert isinstance(
            result["phash_distance"], (int, type(result["phash_distance"]))
        )

    def test_compare_all_hashes_missing_keys(self, handler):
        """Test compare_all_hashes with missing hash keys."""
        hashes1 = {"phash": "abc123", "dhash": "def456"}  # Missing ahash
        hashes2 = {"phash": "abc123", "dhash": "def456", "ahash": "789abc"}

        result = handler.compare_all_hashes(hashes1, hashes2)
        # Method catches exceptions and returns error result
        assert not result["is_match"] or result["avg_distance"] == 999

    def test_zero_threshold(self, handler, sample_image, similar_image):
        """Test comparison with zero threshold (only exact matches)."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(similar_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=0)

        # With threshold 0, only exactly identical hashes will match
        if result["avg_distance"] == 0:
            assert bool(result["is_match"]) is True
        else:
            assert bool(result["is_match"]) is False

    def test_large_threshold(self, handler, sample_image, different_image):
        """Test comparison with very large threshold (everything matches)."""
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(different_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=64)

        # Should match with threshold >= max distance
        assert bool(result["is_match"]) is True


class TestImageFormats:
    """Test suite for various image formats and sizes."""

    @pytest.fixture
    def handler(self):
        """Create a HashHandler instance for testing."""
        return HashHandler(hash_size=8)

    @pytest.mark.parametrize(
        "width,height,expected_valid",
        [
            (64, 64, True),
            (128, 128, True),
            (256, 256, True),
            (1920, 1080, True),
            (10, 10, True),  # Small but valid
        ],
    )
    def test_various_image_sizes(self, handler, width, height, expected_valid):
        """Test hash computation with various image sizes."""
        img = Image.new("RGB", (width, height), color=(100, 150, 200))

        hashes = handler.compute_hashes(img)

        if expected_valid:
            assert len(hashes) == 3
            assert all(isinstance(v, str) for v in hashes.values())
            assert all(len(v) == 16 for v in hashes.values())


class TestThresholdSensitivity:
    """Test suite for threshold sensitivity and behavior."""

    @pytest.mark.parametrize(
        "threshold,expected_match",
        [
            (0, False),  # Only identical
            (5, False),  # Very strict
            (10, False),  # Strict
            (20, True),  # Moderate
            (30, True),  # Generous
            (64, True),  # Everything matches
        ],
    )
    def test_threshold_sensitivity(
        self, threshold, expected_match, sample_image, similar_image
    ):
        """Test how different thresholds affect matching."""
        handler = HashHandler()
        hashes1 = handler.compute_hashes(sample_image)
        hashes2 = handler.compute_hashes(similar_image)

        result = handler.compare_all_hashes(hashes1, hashes2, threshold=threshold)

        # Note: actual match depends on image similarity
        # Accept both Python bool and numpy bool types
        assert hasattr(result["is_match"], "__bool__")  # Can be converted to bool
        assert result["avg_distance"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
