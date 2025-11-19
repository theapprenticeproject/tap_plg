"""
Unit tests for RabbitMQClient.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
import json
from datetime import datetime

from mq.rmq_client import RabbitMQClient


class TestRabbitMQClient:
    """Test cases for RabbitMQClient."""

    @pytest.fixture
    def rmq_client(self):
        """Create RabbitMQClient instance."""
        with patch.dict(
            "os.environ",
            {
                "RABBITMQ_HOST": "test-host",
                "RABBITMQ_PORT": "5672",
                "RABBITMQ_USER": "testuser",
                "RABBITMQ_PASS": "testpass",
                "SUBMISSION_QUEUE": "test_submissions",
                "FEEDBACK_QUEUE": "test_feedback",
                "DEAD_LETTER_QUEUE": "test_dlq",
                "RABBITMQ_PREFETCH_COUNT": "10",
                "MAX_RETRIES": "5",
            },
        ):
            return RabbitMQClient()

    def test_init_default_values(self):
        """Test initialization with default values from config."""
        client = RabbitMQClient()

        # Values come from config, not hardcoded defaults
        assert client.RABBITMQ_HOST in ["localhost", "rabbitmq"]
        assert client.RABBITMQ_PORT in ["5672", 5672]
        assert client.SUBMISSION_QUEUE == "plagiarism_submissions"
        assert client.FEEDBACK_QUEUE == "plagiarism_feedback"
        assert client.PREFETCH_COUNT in [1, 5, 10]  # Can vary by config
        assert client.MAX_RETRIES >= 3

    def test_init_with_environment_variables(self, rmq_client):
        """Test initialization with environment variables."""
        assert rmq_client.RABBITMQ_HOST == "test-host"
        assert rmq_client.RABBITMQ_PORT == "5672"
        assert rmq_client.RABBITMQ_USER == "testuser"
        assert rmq_client.RABBITMQ_PASS == "testpass"
        assert rmq_client.SUBMISSION_QUEUE == "test_submissions"
        assert rmq_client.FEEDBACK_QUEUE == "test_feedback"
        assert rmq_client.DEAD_LETTER_QUEUE == "test_dlq"
        assert rmq_client.PREFETCH_COUNT == 10
        assert rmq_client.MAX_RETRIES == 5

    def test_rabbitmq_url_construction(self, rmq_client):
        """Test RabbitMQ URL is constructed correctly."""
        expected_url = "amqp://testuser:testpass@test-host:5672//"
        assert rmq_client.RABBITMQ_URL == expected_url

    @pytest.mark.asyncio
    async def test_connect_success(self, rmq_client):
        """Test successful connection to RabbitMQ."""
        with patch("mq.rmq_client.aio_pika") as mock_aio_pika:
            # Mock connection
            mock_connection = AsyncMock()
            mock_channel = AsyncMock()
            mock_queue = AsyncMock()

            mock_aio_pika.connect_robust = AsyncMock(return_value=mock_connection)
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            await rmq_client.connect()

            # Verify connection was established
            mock_aio_pika.connect_robust.assert_called_once_with(
                rmq_client.RABBITMQ_URL
            )
            mock_connection.channel.assert_called_once()
            mock_channel.set_qos.assert_called_once_with(prefetch_count=10)

            # Verify queues were declared (DLQ + submission + feedback)
            assert mock_channel.declare_queue.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_retry_on_failure(self, rmq_client):
        """Test connection retry logic on failure."""
        with (
            patch("mq.rmq_client.aio_pika") as mock_aio_pika,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            # First two attempts fail, third succeeds
            mock_connection = AsyncMock()
            mock_channel = AsyncMock()
            mock_queue = AsyncMock()

            mock_aio_pika.connect_robust = AsyncMock(
                side_effect=[
                    Exception("Connection failed"),
                    Exception("Connection failed"),
                    mock_connection,
                ]
            )
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            await rmq_client.connect()

            # Verify retries occurred
            assert mock_aio_pika.connect_robust.call_count == 3
            assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_connect_max_retries_exceeded(self, rmq_client):
        """Test connection fails after max retries."""
        with (
            patch("mq.rmq_client.aio_pika") as mock_aio_pika,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            # All attempts fail
            mock_aio_pika.connect_robust = AsyncMock(
                side_effect=Exception("Connection failed")
            )

            with pytest.raises(Exception, match="Connection failed"):
                await rmq_client.connect()

    @pytest.mark.asyncio
    async def test_publish_message_success(self, rmq_client):
        """Test successful message publishing."""
        with patch("mq.rmq_client.aio_pika") as mock_aio_pika:
            mock_channel = AsyncMock()
            mock_exchange = AsyncMock()
            mock_channel.default_exchange = mock_exchange
            rmq_client.channel = mock_channel
            rmq_client.FEEDBACK_QUEUE = "test_feedback"

            message_body = {
                "submission_id": "SUB-001",
                "student_id": "ST001",
                "result": "plagiarized",
            }

            await rmq_client.publish_message(message_body)

            mock_exchange.publish.assert_called_once()

            call_args = mock_aio_pika.Message.call_args
            assert call_args[1]["body"] == json.dumps(message_body).encode()

            publish_call_args = mock_exchange.publish.call_args
            assert publish_call_args[1]["routing_key"] == "test_feedback"

    @pytest.mark.asyncio
    async def test_publish_message_timeout_error(self, rmq_client):
        """Test publish message handles timeout error."""
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_exchange.publish = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
        mock_channel.default_exchange = mock_exchange
        rmq_client.channel = mock_channel

        message_body = {"submission_id": "SUB-002"}

        with pytest.raises(Exception, match="RabbitMQ unavailable"):
            await rmq_client.publish_message(message_body)

    @pytest.mark.asyncio
    async def test_publish_to_dlq_success(self, rmq_client):
        """Test successful DLQ publishing."""
        with patch("mq.rmq_client.aio_pika") as mock_aio_pika:
            mock_channel = AsyncMock()
            mock_exchange = AsyncMock()
            mock_channel.default_exchange = mock_exchange
            rmq_client.channel = mock_channel
            rmq_client.DEAD_LETTER_QUEUE = "test_dlq"

            message_body = {
                "submission_id": "SUB-003",
                "student_id": "ST003",
            }
            reason = "Max retries exceeded"

            result = await rmq_client.publish_to_dlq(message_body, reason)

            assert result is True
            mock_exchange.publish.assert_called_once()

            call_args = mock_aio_pika.Message.call_args
            dlq_data = json.loads(call_args[1]["body"].decode())

            assert dlq_data["original_message"] == message_body
            assert dlq_data["failure_reason"] == reason
            assert dlq_data["submission_id"] == "SUB-003"
            assert "failed_at" in dlq_data

    @pytest.mark.asyncio
    async def test_publish_to_dlq_no_dlq_configured(self, rmq_client):
        """Test DLQ publish when DLQ not configured."""
        rmq_client.DEAD_LETTER_QUEUE = ""

        message_body = {"submission_id": "SUB-004"}
        result = await rmq_client.publish_to_dlq(message_body, "Test reason")

        assert result is False

    @pytest.mark.asyncio
    async def test_publish_to_dlq_publish_fails(self, rmq_client):
        """Test DLQ publish failure is handled."""
        with patch("mq.rmq_client.aio_pika"):
            mock_channel = AsyncMock()
            mock_exchange = AsyncMock()
            mock_exchange.publish = AsyncMock(side_effect=Exception("Publish failed"))
            mock_channel.default_exchange = mock_exchange
            rmq_client.channel = mock_channel
            rmq_client.DEAD_LETTER_QUEUE = "test_dlq"

            message_body = {"submission_id": "SUB-005"}
            result = await rmq_client.publish_to_dlq(message_body, "Test reason")

            assert result is False

    @pytest.mark.asyncio
    async def test_start_consumer(self, rmq_client):
        """Test starting message consumer."""
        with patch("mq.rmq_client.aio_pika") as mock_aio_pika:
            # Mock connection and queue
            mock_connection = AsyncMock()
            mock_channel = AsyncMock()
            mock_queue = AsyncMock()

            mock_aio_pika.connect_robust = AsyncMock(return_value=mock_connection)
            mock_connection.channel = AsyncMock(return_value=mock_channel)
            mock_channel.set_qos = AsyncMock()
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

            # Mock callback
            callback = AsyncMock()

            await rmq_client.start_consumer(callback)

            # Verify consumer was started
            mock_queue.consume.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, rmq_client):
        """Test closing RabbitMQ connection."""
        mock_connection = AsyncMock()
        rmq_client.connection = mock_connection
        rmq_client._closed = False

        await rmq_client.close()

        mock_connection.close.assert_called_once()
        assert rmq_client._closed is True

    @pytest.mark.asyncio
    async def test_close_idempotent(self, rmq_client):
        """Test that close can be called multiple times safely."""
        mock_connection = AsyncMock()
        rmq_client.connection = mock_connection
        rmq_client._closed = False

        await rmq_client.close()
        await rmq_client.close()  # Call again

        # Should only close once
        assert mock_connection.close.call_count == 1
        assert rmq_client._closed is True

    @pytest.mark.asyncio
    async def test_close_with_retry_task(self, rmq_client):
        """Test closing with active retry task."""
        mock_connection = AsyncMock()

        async def mock_cancelled_task():
            raise asyncio.CancelledError()

        mock_retry_task = asyncio.create_task(mock_cancelled_task())
        await asyncio.sleep(0)

        rmq_client.connection = mock_connection
        rmq_client.retry_submission = mock_retry_task
        rmq_client._closed = False

        await rmq_client.close()

        mock_connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_dlq_message_metadata(self, rmq_client):
        """Test DLQ message contains proper metadata."""
        with (
            patch("mq.rmq_client.aio_pika") as mock_aio_pika,
            patch("mq.rmq_client.datetime") as mock_datetime,
        ):
            mock_now = datetime(2025, 11, 6, 12, 0, 0)
            mock_datetime.utcnow.return_value = mock_now

            mock_channel = AsyncMock()
            mock_exchange = AsyncMock()
            mock_channel.default_exchange = mock_exchange
            rmq_client.channel = mock_channel
            rmq_client.DEAD_LETTER_QUEUE = "test_dlq"

            message_body = {
                "submission_id": "SUB-006",
                "student_id": "ST006",
                "retry_count": 3,
            }

            await rmq_client.publish_to_dlq(message_body, "Processing failed")

            call_args = mock_aio_pika.Message.call_args
            dlq_data = json.loads(call_args[1]["body"].decode())

            assert dlq_data["submission_id"] == "SUB-006"
            assert dlq_data["student_id"] == "ST006"
            assert dlq_data["retry_count"] == 3
            assert dlq_data["dlq_source"] == "plagiarism_checker"
            assert dlq_data["failed_at"] == mock_now.isoformat()
