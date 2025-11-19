import imagehash
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class HashHandler:
    """
    Perceptual hashing handler using imagehash library
    Computes pHash, dHash, and aHash for image comparison
    """

    def __init__(self, hash_size: int = 8):
        """
        Args:
            hash_size: Size of the hash (8 = 64-bit hash)
        """
        self.hash_size = hash_size
        logger.info(f"HashHandler initialized with hash_size={hash_size}")

    def compute_hashes(self, image: Image.Image) -> dict:
        """
        Compute all three perceptual hashes

        Args:
            image: PIL Image object

        Returns:
            dict with 'phash', 'dhash', 'ahash' as hex strings
        """
        try:
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Compute hashes
            phash = str(imagehash.phash(image, hash_size=self.hash_size))
            dhash = str(imagehash.dhash(image, hash_size=self.hash_size))
            ahash = str(imagehash.average_hash(image, hash_size=self.hash_size))

            logger.debug(
                f"Computed hashes: pHash={phash[:8]}..., dHash={dhash[:8]}..., aHash={ahash[:8]}..."
            )

            return {"phash": phash, "dhash": dhash, "ahash": ahash}

        except Exception as e:
            logger.error(f"Failed to compute hashes: {e}")
            raise

    def hamming_distance(self, hash1: str, hash2: str) -> int:
        """
        Calculate Hamming distance between two hash strings

        Args:
            hash1: First hash (hex string)
            hash2: Second hash (hex string)

        Returns:
            Hamming distance (number of differing bits)
        """
        try:
            # Convert hex strings to imagehash objects for comparison
            h1 = imagehash.hex_to_hash(hash1)
            h2 = imagehash.hex_to_hash(hash2)

            distance = h1 - h2
            return distance

        except Exception as e:
            logger.error(f"Failed to calculate Hamming distance: {e}")
            return 999

    def is_similar(self, hash1: str, hash2: str, threshold: int = 10) -> bool:
        """
        Check if two hashes are similar based on Hamming distance

        Args:
            hash1: First hash
            hash2: Second hash
            threshold: Maximum Hamming distance to consider similar (default: 10)

        Returns:
            True if similar, False otherwise
        """
        distance = self.hamming_distance(hash1, hash2)
        return distance <= threshold

    def compare_all_hashes(
        self, hashes1: dict, hashes2: dict, threshold: int = 10
    ) -> dict:
        """
        Compare all three hash types and return similarity scores

        Args:
            hashes1: Dict with phash, dhash, ahash
            hashes2: Dict with phash, dhash, ahash
            threshold: Similarity threshold

        Returns:
            dict with comparison results
        """
        try:
            phash_dist = self.hamming_distance(hashes1["phash"], hashes2["phash"])
            dhash_dist = self.hamming_distance(hashes1["dhash"], hashes2["dhash"])
            ahash_dist = self.hamming_distance(hashes1["ahash"], hashes2["ahash"])

            # Avg distance
            avg_distance = (phash_dist + dhash_dist + ahash_dist) / 3

            # Determine if match using MAJORITY VOTING (at least 2 out of 3 hashes must match)
            # This prevents false positives from single hash matches
            matches_count = sum([
                phash_dist <= threshold,
                dhash_dist <= threshold,
                ahash_dist <= threshold
            ])
            is_match = matches_count >= 2

            return {
                "phash_distance": phash_dist,
                "dhash_distance": dhash_dist,
                "ahash_distance": ahash_dist,
                "avg_distance": avg_distance,
                "is_match": is_match,
                "matches_count": matches_count,  # Number of hashes that matched
                "best_match_type": min(
                    [
                        ("phash", phash_dist),
                        ("dhash", dhash_dist),
                        ("ahash", ahash_dist),
                    ],
                    key=lambda x: x[1],
                )[0],
            }

        except Exception as e:
            logger.error(f"Failed to compare hashes: {e}")
            return {
                "phash_distance": 999,
                "dhash_distance": 999,
                "ahash_distance": 999,
                "avg_distance": 999,
                "is_match": False,
                "best_match_type": "none",
            }
