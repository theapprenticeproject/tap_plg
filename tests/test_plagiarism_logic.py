"""
Unit tests for plagiarism determination logic.

Tests the complex priority-based plagiarism detection algorithm covering:
- Self-plagiarism (cross-assignment, late resubmission)
- Peer plagiarism (single match, collusion)
- Reference database matches
- Resubmission within window
- Priority ordering logic
"""

import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from image_worker.worker import ImageWorker
from datetime import datetime, timedelta


class TestPlagiarismLogic:
    """Test suite for determine_plagiarism_status method."""

    @pytest.fixture
    def worker(self):
        """Create ImageWorker instance for testing with mocked CLIP."""
        with patch("image_worker.worker.CLIPHandler") as mock_clip_class:
            # Mock the CLIP handler to avoid loading the model
            mock_clip_instance = MagicMock()
            mock_clip_instance.generate_embedding = MagicMock(
                side_effect=lambda img: np.random.randn(512).astype(np.float32)
                / np.linalg.norm(np.random.randn(512).astype(np.float32))
            )
            mock_clip_class.return_value = mock_clip_instance

            worker = ImageWorker()
            return worker

    def create_peer_result(
        self,
        is_match=False,
        submission_ids=None,
        student_ids=None,
        similarity=0.0,
    ):
        """Helper to create peer check result."""
        return {
            "is_match": is_match,
            "matched_submission_ids": submission_ids or [],
            "matched_student_ids": student_ids or [],
            "matched_assign_ids": [],
            "matched_image_urls": [],
            "matched_similarities": [similarity] if is_match else [],
            "best_similarity": similarity,
            "best_match_student_id": student_ids[0] if student_ids else None,
        }

    def create_self_result(
        self,
        is_match=False,
        same_assignment=True,
        within_window=True,
        similarity=0.0,
        days_since=0,
    ):
        """Helper to create self check result."""
        return {
            "is_match": is_match,
            "matched_submission_ids": ["SUB-001"] if is_match else [],
            "matched_assign_ids": ["A001"] if is_match else [],
            "matched_image_urls": ["http://example.com/img.jpg"] if is_match else [],
            "best_similarity": similarity,
            "days_since_last": days_since,
            "same_assignment": same_assignment,
            "within_resubmission_window": within_window,
            "previous_submission_date": datetime.utcnow() - timedelta(days=days_since),
            "previous_assign_id": "A001",
        }

    def create_ref_result(self, is_match=False, similarity=0.0):
        """Helper to create reference check result."""
        return {
            "is_match": is_match,
            "matched_ref_id": "REF-001" if is_match else None,
            "similarity": similarity,
            "image_url": "http://example.com/ref.jpg" if is_match else None,
        }

    def test_original_no_matches(self, worker):
        """Test submission with no plagiarism detected."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is False
        assert status["match_type"] == "original"
        assert status["plagiarism_source"] == "none"
        assert status["similarity_score"] == 0.0

    def test_peer_plagiarism_single_match(self, worker):
        """Test peer plagiarism with single match."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.95,
        )
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "peer"
        assert status["peer_plagiarism_detected"] is True
        assert status["similarity_score"] == 0.95
        assert len(status["matched_peer_submission_ids"]) == 1

    def test_peer_collusion_multiple_matches(self, worker):
        """Test peer collusion with multiple matches."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002", "SUB-003"],
            student_ids=["ST002", "ST003"],
            similarity=0.92,
        )
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "peer_collusion"
        assert len(status["matched_peer_submission_ids"]) == 2

    def test_self_plagiarism_cross_assignment(self, worker):
        """Test self-plagiarism across different assignments."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result(
            is_match=True, same_assignment=False, similarity=0.98, days_since=10
        )
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "self_cross_assignment"
        assert status["self_plagiarism_detected"] is True
        assert status["days_since_last_submission"] == 10

    def test_self_plagiarism_late_resubmission(self, worker):
        """Test late resubmission (same assignment, outside window)."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result(
            is_match=True,
            same_assignment=True,
            within_window=False,
            similarity=0.99,
            days_since=10,
        )
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "self_late_resubmission"
        assert status["self_plagiarism_detected"] is True

    def test_resubmission_allowed_within_window(self, worker):
        """Test allowed resubmission (same assignment, within window, no other matches)."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result(
            is_match=True,
            same_assignment=True,
            within_window=True,
            similarity=0.99,
            days_since=2,
        )
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is False
        assert status["match_type"] == "resubmission_allowed"
        assert status["resubmission_within_window"] is True
        assert status["days_since_last_submission"] == 2

    def test_reference_match(self, worker):
        """Test reference database match."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result()
        ref_result = self.create_ref_result(is_match=True, similarity=0.88)

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "reference"
        assert len(status["matched_reference_ids"]) == 1

    def test_priority_peer_over_self(self, worker):
        """Test that peer plagiarism takes priority over self."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.90,
        )
        self_result = self.create_self_result(
            is_match=True,
            same_assignment=True,
            within_window=True,
            similarity=0.99,
            days_since=1,
        )
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        # Peer should take priority even though there's a valid resubmission
        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] in ["peer", "peer_collusion"]
        assert status["peer_plagiarism_detected"] is True

    def test_priority_self_cross_assignment_over_peer(self, worker):
        """Test that self cross-assignment takes priority."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.90,
        )
        self_result = self.create_self_result(
            is_match=True, same_assignment=False, similarity=0.98, days_since=5
        )
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        # Self cross-assignment should be caught first
        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "self_cross_assignment"
        assert status["self_plagiarism_detected"] is True

    def test_priority_reference_blocks_resubmission(self, worker):
        """Test that reference match blocks allowed resubmission."""
        peer_result = self.create_peer_result()
        self_result = self.create_self_result(
            is_match=True,
            same_assignment=True,
            within_window=True,
            similarity=0.99,
            days_since=1,
        )
        ref_result = self.create_ref_result(is_match=True, similarity=0.85)

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        # Reference match should prevent resubmission allowance
        assert status["is_plagiarized"] is True
        assert status["plagiarism_source"] == "reference"

    def test_match_type_exact_duplicate(self, worker):
        """Test match_type classification for exact duplicates."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.98,  # >= 0.95
        )
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["match_type"] == "exact_duplicate"

    def test_match_type_near_duplicate(self, worker):
        """Test match_type classification for near duplicates."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.92,  # >= 0.90
        )
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["match_type"] == "near_duplicate"

    def test_match_type_semantic_match(self, worker):
        """Test match_type classification for semantic matches."""
        peer_result = self.create_peer_result(
            is_match=True,
            submission_ids=["SUB-002"],
            student_ids=["ST002"],
            similarity=0.85,  # >= 0.80
        )
        self_result = self.create_self_result()
        ref_result = self.create_ref_result()

        status = worker.determine_plagiarism_status(
            peer_result, self_result, ref_result
        )

        assert status["match_type"] == "semantic_match"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
