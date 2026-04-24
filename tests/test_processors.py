"""
Unit tests for ImageProcessor.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from processors.image_processor import ImageProcessor


class TestImageProcessor:
    """Test cases for ImageProcessor."""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock database manager."""
        db = MagicMock()
        db.insert_submission_if_not_exists = AsyncMock(return_value="record-123")
        db.update_result = AsyncMock()
        return db

    @pytest.fixture
    def mock_image_worker(self):
        """Mock image worker."""
        worker = MagicMock()
        worker.process_submission = AsyncMock()
        return worker

    @pytest.fixture
    def image_processor(self, mock_db_manager, mock_image_worker):
        """Create ImageProcessor instance with mocked dependencies."""
        return ImageProcessor(
            db_manager=mock_db_manager, image_worker=mock_image_worker
        )

    def test_init_requires_db_manager(self, mock_image_worker):
        """Test that ImageProcessor requires a db_manager."""
        with pytest.raises(ValueError, match="requires a shared db_manager"):
            ImageProcessor(db_manager=None, image_worker=mock_image_worker)

    def test_init_requires_image_worker(self, mock_db_manager):
        """Test that ImageProcessor requires an image_worker."""
        with pytest.raises(ValueError, match="requires a shared image_worker"):
            ImageProcessor(db_manager=mock_db_manager, image_worker=None)

    def test_init_success(self, mock_db_manager, mock_image_worker):
        """Test successful initialization."""
        processor = ImageProcessor(
            db_manager=mock_db_manager, image_worker=mock_image_worker
        )
        assert processor.db_manager is mock_db_manager
        assert processor.image_worker is mock_image_worker

    @pytest.mark.asyncio
    async def test_process_no_image_url(self, image_processor):
        """Test processing submission without image URL."""
        data = {"submission_id": "SUB-001", "student_id": "ST001"}

        result = await image_processor.process(data)

        assert result == {"error": "No submission_url provided"}

    @pytest.mark.asyncio
    async def test_process_with_submission_url(self, image_processor, mock_image_worker):
        """Test processing submission with submission_url."""
        data = {
            "submission_id": "SUB-001",
            "student_id": "ST001",
            "submission_url": "https://example.com/image.jpg",
        }

        expected_result = {
            "submission_id": "SUB-001",
            "is_plagiarized": True,
            "similarity_score": 0.95,
        }
        mock_image_worker.process_submission.return_value = expected_result

        result = await image_processor.process(data)

        assert result == expected_result
        mock_image_worker.process_submission.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_process_with_image_url(self, image_processor, mock_image_worker):
        """Test processing submission with image_url (alternative field)."""
        data = {
            "submission_id": "SUB-002",
            "student_id": "ST002",
            "submission_url": "https://example.com/photo.png",
        }

        expected_result = {
            "submission_id": "SUB-002",
            "is_plagiarized": False,
            "similarity_score": 0.45,
        }
        mock_image_worker.process_submission.return_value = expected_result

        result = await image_processor.process(data)

        assert result == expected_result
        mock_image_worker.process_submission.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_process_worker_returns_none(
        self, image_processor, mock_image_worker
    ):
        """Test when worker returns None."""
        data = {
            "submission_id": "SUB-003",
            "submission_url": "https://example.com/image.jpg",
        }

        mock_image_worker.process_submission.return_value = None

        result = await image_processor.process(data)

        assert result == {"error": "Processing failed"}

    @pytest.mark.asyncio
    async def test_process_worker_returns_json_string(
        self, image_processor, mock_image_worker
    ):
        """Test when worker returns JSON string."""
        data = {
            "submission_id": "SUB-004",
            "submission_url": "https://example.com/image.jpg",
        }

        expected_result = {
            "submission_id": "SUB-004",
            "is_plagiarized": True,
            "similarity_score": 0.88,
        }
        mock_image_worker.process_submission.return_value = json.dumps(expected_result)

        result = await image_processor.process(data)

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_process_worker_returns_invalid_json(
        self, image_processor, mock_image_worker
    ):
        """Test when worker returns invalid JSON string."""
        data = {
            "submission_id": "SUB-005",
            "submission_url": "https://example.com/image.jpg",
        }

        mock_image_worker.process_submission.return_value = "not valid json {{"

        result = await image_processor.process(data)

        assert "error" in result
        assert "Invalid JSON response" in result["error"]

    @pytest.mark.asyncio
    async def test_process_worker_raises_exception(
        self, image_processor, mock_image_worker
    ):
        """Test when worker raises exception."""
        data = {
            "submission_id": "SUB-006",
            "submission_url": "https://example.com/image.jpg",
        }

        mock_image_worker.process_submission.side_effect = RuntimeError(
            "Worker crashed"
        )

        result = await image_processor.process(data)

        assert "error" in result
        assert "Processing error" in result["error"]
        assert "Worker crashed" in result["error"]

    @pytest.mark.asyncio
    async def test_process_multiple_submissions(
        self, image_processor, mock_image_worker
    ):
        """Test processing multiple submissions sequentially."""
        submissions = [
            {
                "submission_id": f"SUB-{i}",
                "submission_url": f"https://example.com/image{i}.jpg",
            }
            for i in range(3)
        ]

        results = []
        for i, data in enumerate(submissions):
            mock_image_worker.process_submission.return_value = {
                "submission_id": data["submission_id"],
                "similarity_score": 0.5 + i * 0.1,
            }
            result = await image_processor.process(data)
            results.append(result)

        assert len(results) == 3
        assert results[0]["similarity_score"] == 0.5
        assert results[1]["similarity_score"] == 0.6
        assert results[2]["similarity_score"] == 0.7

