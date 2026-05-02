"""
Unit tests for SubmissionChecker.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from plag_checker.submissions_checker import (
    SubmissionChecker,
    MessageAckManager,
)


class TestMessageAckManager:
    """Test cases for MessageAckManager context manager."""

    @pytest.fixture
    def mock_message(self):
        """Create mock RabbitMQ message."""
        message = MagicMock()
        message.ack = AsyncMock()
        message.nack = AsyncMock()
        message.reject = AsyncMock()
        return message

    @pytest.mark.asyncio
    async def test_ack_message(self, mock_message):
        """Test acknowledging a message."""
        async with MessageAckManager(mock_message) as manager:
            await manager.ack()

        assert manager.acked is True
        assert manager.action == "ack"
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_nack_message(self, mock_message):
        """Test negative acknowledgment."""
        async with MessageAckManager(mock_message) as manager:
            await manager.nack(requeue=True)

        assert manager.acked is True
        assert manager.action == "nack(requeue=True)"
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_reject_message(self, mock_message):
        """Test rejecting a message."""
        async with MessageAckManager(mock_message) as manager:
            await manager.reject(requeue=False)

        assert manager.acked is True
        assert manager.action == "reject(requeue=False)"
        mock_message.reject.assert_called_once_with(requeue=False)

    @pytest.mark.asyncio
    async def test_auto_requeue_on_exit(self, mock_message):
        """Test that message is auto-requeued if not explicitly acked."""
        async with MessageAckManager(mock_message):
            pass  # Don't ack

        # Should auto-nack with requeue=True
        mock_message.nack.assert_called_once_with(requeue=True)

    @pytest.mark.asyncio
    async def test_no_double_ack(self, mock_message):
        """Test that message can't be acked twice."""
        async with MessageAckManager(mock_message) as manager:
            await manager.ack()
            await manager.ack()  # Try again

        # Should only ack once
        assert mock_message.ack.call_count == 1


class TestSubmissionChecker:
    """Test cases for SubmissionChecker."""

    @pytest.fixture
    def mock_mq_client(self):
        """Create mock MQ client."""
        client = MagicMock()
        client.start_consumer = AsyncMock()
        client.publish_message = AsyncMock()
        client.publish_to_dlq = AsyncMock(return_value=True)
        client.close = AsyncMock()
        client.SUBMISSION_QUEUE = "test_queue"
        return client

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        db = MagicMock()
        db.init_pool = AsyncMock()
        db.close = AsyncMock()
        db.insert_submission_if_not_exists = AsyncMock(return_value="record-123")
        db.update_status = AsyncMock()
        db.update_result = AsyncMock()
        db.get_retry_count = AsyncMock(return_value=0)
        return db

    @pytest.fixture
    def mock_image_worker(self):
        """Create mock image worker."""
        worker = MagicMock()
        worker.initialize = AsyncMock()
        worker.close = AsyncMock()
        worker.process_submission = AsyncMock()
        return worker

    @pytest.fixture
    def submission_checker(self, mock_mq_client, mock_db_manager, mock_image_worker):
        """Create SubmissionChecker with mocked dependencies."""
        return SubmissionChecker(
            mq_client=mock_mq_client,
            db_manager=mock_db_manager,
            image_worker=mock_image_worker,
        )

    def test_init_with_provided_dependencies(
        self, mock_mq_client, mock_db_manager, mock_image_worker
    ):
        """Test initialization with provided dependencies."""
        checker = SubmissionChecker(
            mq_client=mock_mq_client,
            db_manager=mock_db_manager,
            image_worker=mock_image_worker,
        )

        assert checker.client is mock_mq_client
        assert checker.db is mock_db_manager
        assert checker.image_worker is mock_image_worker
        assert checker._owns_db_manager is False
        assert checker._owns_image_worker is False

    def test_init_without_db_manager(self, mock_mq_client):
        """Test initialization without db_manager creates new instance."""
        with patch("plag_checker.submissions_checker.DatabaseManager") as mock_db_class:
            checker = SubmissionChecker(mq_client=mock_mq_client)

            mock_db_class.assert_called_once()
            assert checker._owns_db_manager is True

    @pytest.mark.asyncio
    async def test_initialize(self, submission_checker, mock_db_manager):
        """Test initialization process."""
        with patch(
            "plag_checker.submissions_checker.ImageProcessor"
        ) as mock_processor_class:
            await submission_checker.initialize()

            # Should initialize database
            mock_db_manager.init_pool.assert_called_once()

            # Should create image processor
            mock_processor_class.assert_called_once()

            # Should start consumer
            submission_checker.client.start_consumer.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_processor_for_image(self, submission_checker):
        """Test getting processor for image submission."""
        submission_checker.image_processor = MagicMock()
        data = {"submission_type": "image", "submission_url": "https://example.com/image.jpg"}

        processor = submission_checker.get_processor(data)

        assert processor is submission_checker.image_processor

    @pytest.mark.asyncio
    async def test_get_processor_for_text(self, submission_checker):
        """Test getting processor for text submission."""
        data = {"submission_type": "text", "submission_text": "Some text content"}

        with pytest.raises(ValueError, match="Unsupported submission_type"):
            submission_checker.get_processor(data)

    @pytest.mark.asyncio
    async def test_get_processor_invalid_format(self, submission_checker):
        """Test getting processor with invalid format raises error."""
        data = {"submission_id": "SUB-001"}  # No submission_type or submission_url

        with pytest.raises(ValueError, match="Invalid submission format"):
            submission_checker.get_processor(data)

    @pytest.mark.asyncio
    async def test_get_processor_not_initialized(self, submission_checker):
        """Test getting processor when not initialized raises error."""
        submission_checker.image_processor = None
        data = {"submission_type": "image", "submission_url": "https://example.com/image.jpg"}

        with pytest.raises(RuntimeError, match="not initialized"):
            submission_checker.get_processor(data)

    @pytest.mark.asyncio
    async def test_process_submission_success(
        self, submission_checker, mock_db_manager
    ):
        """Test successful submission processing."""
        submission_checker.image_processor = MagicMock()
        submission_checker.image_processor.process = AsyncMock(
            return_value={
                "similar_sources": ["source1"],
                "similarity_score": 0.85,
                "is_plagiarized": True,
                "match_type": "hash",
            }
        )

        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {
                "submission_id": "SUB-001",
                "student_id": "ST001",
                "assign_id": "A001",
                "submission_type": "image",
                "submission_url": "https://example.com/image.jpg",
            }
        ).encode()
        mock_message.ack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {"x-delivery-count": 0}

        await submission_checker.process_submission(mock_message)

        mock_db_manager.insert_submission_if_not_exists.assert_called_once()
        mock_db_manager.update_result.assert_called_once()

        mock_message.ack.assert_called_once()

        submission_checker.client.publish_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_submission_non_image_skips_plagiarism(
        self, submission_checker, mock_db_manager
    ):
        """Test non-image submissions skip plagiarism and are published as original."""
        submission_checker.image_processor = MagicMock()

        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {
                "submission_id": "SUB-006",
                "student_id": "ST006",
                "assign_id": "A006",
                "submission_type": "text",
                "submission_text": "Hello WHO ARE YOU?",
            }
        ).encode()
        mock_message.ack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {"x-delivery-count": 0}

        await submission_checker.process_submission(mock_message)

        submission_checker.image_processor.process.assert_not_called()
        mock_db_manager.update_result.assert_called_once()
        submission_checker.client.publish_message.assert_called_once()
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_submission_text_submission_without_url(
        self, submission_checker, mock_db_manager
    ):
        """Test processing a text submission without submission_url."""
        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {
                "submission_id": "SUB-002",
                "student_id": "ST002",
                "assign_id": "A002",
                "submission_type": "text",
                "submission_text": "Hello",
            }
        ).encode()
        mock_message.ack = AsyncMock()
        mock_message.nack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {}

        await submission_checker.process_submission(mock_message)

        mock_db_manager.update_result.assert_called_once()
        mock_message.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_submission_invalid_json(self, submission_checker):
        """Test processing submission with invalid JSON."""
        mock_message = MagicMock()
        mock_message.body = b"invalid json {{"
        mock_message.nack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {}

        await submission_checker.process_submission(mock_message)

        # Should nack without requeue
        mock_message.nack.assert_called_once_with(requeue=False, submission_id="unknown")

    @pytest.mark.asyncio
    async def test_process_submission_retry_logic(
        self, submission_checker, mock_db_manager
    ):
        """Test retry logic for failed submissions."""
        submission_checker.image_processor = MagicMock()
        submission_checker.image_processor.process = AsyncMock(
            side_effect=Exception("Processing failed")
        )
        submission_checker.MAX_RETRIES = 3

        mock_db_manager.get_retry_count.return_value = 1

        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {
                "submission_id": "SUB-003",
                "submission_type": "image",
                "submission_url": "https://example.com/image.jpg",
            }
        ).encode()
        mock_message.nack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {}

        await submission_checker.process_submission(mock_message)

        # Should nack with requeue (retry)
        mock_message.nack.assert_called_once_with(requeue=True, submission_id="SUB-003")

        # Should update status with retry count
        mock_db_manager.update_status.assert_called()

    @pytest.mark.asyncio
    async def test_process_submission_max_retries(
        self, submission_checker, mock_db_manager
    ):
        """Test submission fails after max retries."""
        submission_checker.image_processor = MagicMock()
        submission_checker.image_processor.process = AsyncMock(
            side_effect=Exception("Processing failed")
        )
        submission_checker.MAX_RETRIES = 3

        mock_db_manager.get_retry_count.return_value = 3

        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {
                "submission_id": "SUB-004",
                "submission_type": "image",
                "submission_url": "https://example.com/image.jpg",
            }
        ).encode()
        mock_message.nack = AsyncMock()
        mock_message.redelivered = False
        mock_message.headers = {}

        await submission_checker.process_submission(mock_message)

        submission_checker.client.publish_to_dlq.assert_called_once()

        mock_message.nack.assert_called_once_with(requeue=False, submission_id="SUB-004")

    @pytest.mark.asyncio
    async def test_process_submission_poison_message(
        self, submission_checker, mock_db_manager
    ):
        """Test handling of poison messages."""
        submission_checker.MAX_RETRIES = 3

        mock_message = MagicMock()
        mock_message.body = json.dumps(
            {"submission_id": "SUB-005", "submission_type": "image", "submission_url": "http://example.com"}
        ).encode()
        mock_message.headers = {"x-delivery-count": 5}
        mock_message.redelivered = True
        mock_message.nack = AsyncMock()

        await submission_checker.process_submission(mock_message)

        # Should detect poison message and publish to DLQ
        submission_checker.client.publish_to_dlq.assert_called_once()
        mock_message.nack.assert_called_once_with(requeue=False, submission_id="SUB-005")

    @pytest.mark.asyncio
    async def test_close_owns_resources(
        self, mock_mq_client, mock_db_manager, mock_image_worker
    ):
        """Test closing when checker owns resources."""
        checker = SubmissionChecker(mq_client=mock_mq_client)
        checker.image_worker = mock_image_worker
        checker._owns_image_worker = True

        await checker.close()

        # Should close all owned resources
        mock_mq_client.close.assert_called_once()
        mock_image_worker.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_shared_resources(
        self, mock_mq_client, mock_db_manager, mock_image_worker
    ):
        """Test closing with shared resources."""
        checker = SubmissionChecker(
            mq_client=mock_mq_client,
            db_manager=mock_db_manager,
            image_worker=mock_image_worker,
        )

        await checker.close()

        # Should close MQ but not shared resources
        mock_mq_client.close.assert_called_once()
        mock_image_worker.close.assert_not_called()
        mock_db_manager.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_flag(self, submission_checker):
        """Test shutdown flag prevents processing."""
        submission_checker._shutdown = True

        mock_message = MagicMock()
        mock_message.nack = AsyncMock()

        await submission_checker.process_submission(mock_message)

        # Should requeue message immediately
        mock_message.nack.assert_called_once_with(requeue=True)
