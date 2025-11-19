"""
Unit tests for ImageValidator.
"""

import pytest
import numpy as np
from PIL import Image
from image_worker.image_validator import ImageValidator


class TestImageValidator:
    """Test cases for ImageValidator."""

    @pytest.fixture
    def validator(self):
        """Create ImageValidator instance."""
        return ImageValidator(
            min_variance_threshold=5.0,
            min_unique_colors=10,
            max_solid_color_ratio=0.95,
        )

    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters."""
        validator = ImageValidator(
            min_variance_threshold=10.0,
            min_unique_colors=20,
            max_solid_color_ratio=0.90,
        )

        assert validator.min_variance_threshold == 10.0
        assert validator.min_unique_colors == 20
        assert validator.max_solid_color_ratio == 0.90

    def test_validate_normal_image(self, validator):
        """Test validation of normal image with content."""
        img_array = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        gradient = np.linspace(0, 255, 200).reshape(200, 1)
        img_array = img_array + gradient.astype(np.uint8)
        img_array = np.clip(img_array, 0, 255).astype(np.uint8)

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is True
        assert reason is None

    def test_reject_solid_white_image(self, validator):
        """Test rejection of solid white image."""
        img_array = np.full((200, 200, 3), 255, dtype=np.uint8)
        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert "variance" in reason.lower() or "color" in reason.lower()

    def test_reject_solid_black_image(self, validator):
        """Test rejection of solid black image."""
        img_array = np.zeros((200, 200, 3), dtype=np.uint8)
        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert "variance" in reason.lower() or "color" in reason.lower()

    def test_reject_solid_color_image(self, validator):
        """Test rejection of solid color (red) image."""
        img_array = np.zeros((200, 200, 3), dtype=np.uint8)
        img_array[:, :, 0] = 255
        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert reason is not None

    def test_reject_low_variance_image(self, validator):
        """Test rejection of image with very low variance."""
        img_array = np.full((200, 200, 3), 128, dtype=np.uint8)
        noise = np.random.randint(-2, 3, (200, 200, 3))
        img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert "variance" in reason.lower()

    def test_reject_insufficient_colors(self, validator):
        """Test rejection of image with too few unique colors."""
        img_array = np.zeros((200, 200, 3), dtype=np.uint8)
        for i in range(5):
            img_array[i * 40 : (i + 1) * 40, :, :] = i * 50

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert "color" in reason.lower()

    def test_accept_image_with_edges(self, validator):
        """Test acceptance of image with sufficient edge content."""
        img_array = np.zeros((200, 200, 3), dtype=np.uint8)

        for i in range(0, 200, 10):
            img_array[i : i + 5, :, :] = 255
            img_array[:, i : i + 5, :] = 128

        for i in range(50):
            x, y = np.random.randint(0, 200, 2)
            img_array[y : y + 10, x : x + 10, :] = np.random.randint(0, 255, 3)

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is True
        assert reason is None

    def test_convert_grayscale_image(self, validator):
        """Test validation of grayscale image (should be converted)."""
        img_array = np.random.randint(0, 255, (200, 200), dtype=np.uint8)
        gradient = np.linspace(0, 255, 200).reshape(200, 1)
        img_array = np.clip(img_array + gradient, 0, 255).astype(np.uint8)

        image = Image.fromarray(img_array, mode="L")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is True
        assert reason is None

    def test_convert_rgba_image(self, validator):
        """Test validation of RGBA image."""
        img_array = np.random.randint(0, 255, (200, 200, 4), dtype=np.uint8)
        gradient = np.linspace(0, 255, 200).reshape(200, 1, 1)
        img_array[:, :, :3] = np.clip(img_array[:, :, :3] + gradient, 0, 255).astype(
            np.uint8
        )
        img_array[:, :, 3] = 255

        image = Image.fromarray(img_array, mode="RGBA")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is True
        assert reason is None

    def test_dominant_color_ratio_calculation(self, validator):
        """Test dominant color ratio calculation."""
        img_array = np.full((100, 100, 3), [255, 0, 0], dtype=np.uint8)
        img_array[0:10, 0:10, :] = [0, 255, 0]

        ratio = validator._get_dominant_color_ratio(img_array)

        assert ratio > 0.95
        assert ratio <= 1.0

    def test_edge_density_calculation(self, validator):
        """Test edge density calculation."""
        img_array = np.zeros((100, 100, 3), dtype=np.uint8)

        for i in range(0, 100, 10):
            img_array[i : i + 2, :, :] = 255

        edge_density = validator._calculate_edge_density(img_array)

        assert edge_density > 0

    def test_watermark_check_no_watermark(self, validator):
        """Test watermark detection on clean image."""
        img_array = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        image = Image.fromarray(img_array, mode="RGB")

        has_watermark, site = validator._check_watermarks(image)

        assert has_watermark is False
        assert site is None

    def test_reject_mostly_solid_background(self, validator):
        """Test rejection of image with 96% solid background."""
        img_array = np.full((200, 200, 3), 200, dtype=np.uint8)

        small_content = np.random.randint(0, 255, (8, 8, 3), dtype=np.uint8)
        img_array[96:104, 96:104, :] = small_content

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is False
        assert "solid color" in reason.lower() or "background" in reason.lower()

    def test_accept_complex_image(self, validator):
        """Test acceptance of complex image with varied content."""
        img_array = np.zeros((200, 200, 3), dtype=np.uint8)

        for i in range(10):
            for j in range(10):
                color = [i * 25, j * 25, (i + j) * 12]
                img_array[i * 20 : (i + 1) * 20, j * 20 : (j + 1) * 20, :] = color

        for i in range(0, 200, 10):
            img_array[i : i + 2, :, :] = 255
            img_array[:, i : i + 2, :] = 128

        noise = np.random.randint(-15, 16, (200, 200, 3))
        img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

        image = Image.fromarray(img_array, mode="RGB")

        is_valid, reason = validator.validate_image(image)

        assert is_valid is True
        assert reason is None

    def test_text_pattern_detection(self, validator):
        """Test text pattern detection in image region."""
        region = np.full((100, 100, 3), 255, dtype=np.uint8)

        for i in range(10, 90, 10):
            region[i : i + 3, 10:90, :] = 0

        score = validator._detect_text_pattern(region)

        assert score > 0
