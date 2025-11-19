"""
Image validation module for detecting invalid submissions.

Validates against:
- Empty/blank images (solid colors, white backgrounds)
- Common website watermarks
- Insufficient image content
"""

import logging
from PIL import Image
import numpy as np
from typing import Tuple, Optional
import imagehash

logger = logging.getLogger(__name__)


class ImageValidator:
    """Validates image submissions for quality and legitimacy."""

    COMMON_WATERMARK_SITES = [
        "shutterstock",
        "getty",
        "istock",
        "adobe",
        "alamy",
        "dreamstime",
        "123rf",
        "depositphotos",
        "pixabay",
        "unsplash",
        "pexels",
        "freepik",
        "canva",
        "vecteezy",
    ]

    STOCK_IMAGE_DOMAINS = [
        "shutterstock",
        "gettyimages",
        "istockphoto",
        "adobe.com/stock",
        "alamy",
        "dreamstime",
        "123rf",
        "depositphotos",
        "pixabay",
        "unsplash",
        "pexels",
        "freepik",
        "canva",
        "vecteezy",
    ]

    def __init__(
        self,
        min_variance_threshold: float = 5.0,
        min_unique_colors: int = 10,
        max_solid_color_ratio: float = 0.95,
    ):
        """
        Initialize image validator.

        Args:
            min_variance_threshold: Minimum pixel variance (detects blank images)
            min_unique_colors: Minimum number of unique colors
            max_solid_color_ratio: Maximum ratio of dominant color (detects solid backgrounds)
        """
        self.min_variance_threshold = min_variance_threshold
        self.min_unique_colors = min_unique_colors
        self.max_solid_color_ratio = max_solid_color_ratio

    def check_stock_image_url(self, image_url: str) -> Tuple[bool, Optional[str]]:
        """
        Check if URL is from a known stock image website.

        Args:
            image_url: URL of the image

        Returns:
            Tuple of (is_stock, site_name)
        """
        image_url_lower = image_url.lower()
        for site in self.STOCK_IMAGE_DOMAINS:
            if site in image_url_lower:
                logger.warning(f"Stock image URL detected: {site} in {image_url}")
                return True, site
        return False, None

    def validate_image(self, image: Image.Image) -> Tuple[bool, Optional[str]]:
        """
        Validate image for submission quality.

        Args:
            image: PIL Image object

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        if image.mode not in ["RGB", "RGBA", "L"]:
            image = image.convert("RGB")

        is_empty, reason = self._check_empty_image(image)
        if is_empty:
            return False, reason

        has_watermark, watermark_site = self._check_watermarks(image)
        if has_watermark:
            return False, f"Image contains {watermark_site} watermark"

        return True, None

    def _check_empty_image(self, image: Image.Image) -> Tuple[bool, Optional[str]]:
        """
        Check if image is empty, blank, or solid color.

        Args:
            image: PIL Image object

        Returns:
            Tuple of (is_empty, reason)
        """
        img_array = np.array(image)

        if image.mode == "RGBA":
            img_array = img_array[:, :, :3]
        elif image.mode == "L":
            img_array = np.expand_dims(img_array, axis=2)

        variance = np.var(img_array)
        if variance < self.min_variance_threshold:
            logger.warning(
                f"Image rejected: low variance ({variance:.2f} < {self.min_variance_threshold})"
            )
            return True, f"Empty/blank image (variance: {variance:.2f})"

        unique_colors = len(
            np.unique(img_array.reshape(-1, img_array.shape[2]), axis=0)
        )
        if unique_colors < self.min_unique_colors:
            logger.warning(
                f"Image rejected: insufficient colors ({unique_colors} < {self.min_unique_colors})"
            )
            return True, f"Insufficient color variation ({unique_colors} unique colors)"

        dominant_color_ratio = self._get_dominant_color_ratio(img_array)
        if dominant_color_ratio > self.max_solid_color_ratio:
            logger.warning(
                f"Image rejected: solid color background ({dominant_color_ratio:.2%} > {self.max_solid_color_ratio:.2%})"
            )
            return (
                True,
                f"Solid color background ({dominant_color_ratio:.1%} dominant color)",
            )

        return False, None

    def _get_dominant_color_ratio(self, img_array: np.ndarray) -> float:
        """
        Calculate ratio of most common color in image.

        Args:
            img_array: Numpy array of image

        Returns:
            Ratio of dominant color (0.0 to 1.0)
        """
        pixels = img_array.reshape(-1, img_array.shape[2])

        unique, counts = np.unique(pixels, axis=0, return_counts=True)

        if len(counts) == 0:
            return 1.0

        max_count = np.max(counts)
        total_pixels = pixels.shape[0]

        return max_count / total_pixels

    def _calculate_edge_density(self, img_array: np.ndarray) -> float:
        """
        Calculate edge density using simple gradient detection.

        Args:
            img_array: Numpy array of image

        Returns:
            Edge density ratio (0.0 to 1.0)
        """
        if len(img_array.shape) == 3:
            gray = np.mean(img_array, axis=2)
        else:
            gray = img_array

        grad_x = np.abs(np.diff(gray, axis=1))
        grad_y = np.abs(np.diff(gray, axis=0))

        edge_threshold = 20
        edges_x = grad_x > edge_threshold
        edges_y = grad_y > edge_threshold

        total_pixels = gray.shape[0] * gray.shape[1]
        edge_pixels = np.sum(edges_x) + np.sum(edges_y)

        return edge_pixels / total_pixels

    def _check_watermarks(self, image: Image.Image) -> Tuple[bool, Optional[str]]:
        """
        Check for common website watermarks using perceptual hashing.

        Args:
            image: PIL Image object

        Returns:
            Tuple of (has_watermark, site_name)
        """
        try:
            img_hash = imagehash.phash(image, hash_size=16)

            known_watermark_patterns = self._get_watermark_patterns()

            for site, patterns in known_watermark_patterns.items():
                for pattern in patterns:
                    if img_hash - pattern < 10:
                        logger.warning(f"Image rejected: {site} watermark detected")
                        return True, site

            img_array = np.array(image.convert("RGB"))
            height, width = img_array.shape[:2]

            corner_size = min(height // 4, width // 4, 200)
            corners = [
                img_array[:corner_size, :corner_size],
                img_array[:corner_size, -corner_size:],
                img_array[-corner_size:, :corner_size],
                img_array[-corner_size:, -corner_size:],
            ]

            for idx, corner in enumerate(corners):
                corner_variance = np.var(corner)
                if corner_variance > 500:
                    corner_unique = len(np.unique(corner.reshape(-1, 3), axis=0))
                    if corner_unique > 100:
                        logger.debug(
                            f"Potential watermark in corner {idx}: variance={corner_variance:.2f}"
                        )

        except Exception as e:
            logger.debug(f"Watermark check failed: {e}")

        return False, None

    def _get_watermark_patterns(self) -> dict:
        """
        Get known watermark hash patterns.

        Returns:
            Dictionary of site -> list of perceptual hashes
        """
        return {}

    def _detect_text_pattern(self, region: np.ndarray) -> float:
        """
        Detect text-like patterns in image region.

        Args:
            region: Numpy array of image region

        Returns:
            Text pattern score (0.0 to 1.0)
        """
        if len(region.shape) == 3:
            gray = np.mean(region, axis=2)
        else:
            gray = region

        grad_x = np.abs(np.diff(gray, axis=1))
        grad_y = np.abs(np.diff(gray, axis=0))

        edges_x = grad_x > 50
        edges_y = grad_y > 50

        high_contrast_pixels = np.sum(edges_x) + np.sum(edges_y)
        total_pixels = gray.shape[0] * gray.shape[1]

        return high_contrast_pixels / total_pixels
