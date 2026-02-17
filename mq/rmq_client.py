import aio_pika
import asyncio
import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from mq.mq_client import MQClient

logger = logging.getLogger(__name__)


class RabbitMQClient(MQClient):
    """
    Handles RabbitMQ connection, queue declarations, publishing, and retries.

    Features:
    - Robust connection with retry logic
    - Message acknowledgment handling
    - Failed message retry with exponential backoff
    - Graceful shutdown support

    Attributes:
        connection: aio_pika connection instance
        channel: aio_pika channel instance
    """

    def __init__(self):
        """Initialize RabbitMQ client with environment configuration."""
        load_dotenv()

        # Environment configurations
        self.RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
        self.RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
        self.RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
        self.RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
        self.RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

        self.SUBMISSION_QUEUE = os.getenv("SUBMISSION_QUEUE", "plagiarism_submissions")
        self.FEEDBACK_QUEUE = os.getenv("FEEDBACK_QUEUE", "plagiarism_feedback")
        self.DEAD_LETTER_QUEUE = os.getenv("DEAD_LETTER_QUEUE", "")  # Optional DLQ

        self.PREFETCH_COUNT = int(os.getenv("RABBITMQ_PREFETCH_COUNT", "5"))
        self.STARTUP_RETRY_LIMIT = int(os.getenv("STARTUP_RETRY_LIMIT", "5"))
        self.STARTUP_RETRY_DELAY = int(os.getenv("STARTUP_RETRY_DELAY", "10"))
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
        self.RETRY_BACKOFF_SECONDS = int(os.getenv("RETRY_BACKOFF_SECONDS", "30"))

        self.RABBITMQ_URL = (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASS}@"
            f"{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{self.RABBITMQ_VHOST}"
        )

        # State variables
        self.retry_submission = None
        self.connection = None
        self.channel = None
        self.submission_queue = None
        self.feedback_queue = None
        self.dead_letter_queue = None
        self._closed = False

        logger.info(
            f"RabbitMQ client initialized: host={self.RABBITMQ_HOST}, "
            f"submission_queue={self.SUBMISSION_QUEUE}, "
            f"feedback_queue={self.FEEDBACK_QUEUE}, "
            f"prefetch_count={self.PREFETCH_COUNT}, "
            f"dlq={'enabled: ' + self.DEAD_LETTER_QUEUE if self.DEAD_LETTER_QUEUE else 'disabled'}"
        )

    async def connect(self):
        """
        Try connecting to RabbitMQ with retries.

        Sets up:
        - Robust connection with automatic reconnection
        - Channel with prefetch limit (process messages in parallel)
        - Durable queues for persistence
        - Optional Dead Letter Queue for permanently failed messages
        """
        attempt = 1
        while attempt <= self.STARTUP_RETRY_LIMIT:
            try:
                logger.info(
                    f"Connecting to RabbitMQ (attempt {attempt}/{self.STARTUP_RETRY_LIMIT})..."
                )
                # Increase heartbeat to 600 seconds (10 minutes) for slow CLIP inference on CPU
                # Also increase connection timeout for initial connection
                self.connection = await aio_pika.connect_robust(
                    self.RABBITMQ_URL, heartbeat=600, timeout=30
                )
                self.channel = await self.connection.channel()

                # Set prefetch count to 1 to avoid multiple slow CLIP inferences in parallel
                # This prevents heartbeat timeouts from multiple long-running tasks
                prefetch = int(os.getenv("RABBITMQ_PREFETCH_COUNT", "1"))
                await self.channel.set_qos(prefetch_count=prefetch)

                # Declare Dead Letter Queue first if configured
                if self.DEAD_LETTER_QUEUE:
                    self.dead_letter_queue = await self.channel.declare_queue(
                        self.DEAD_LETTER_QUEUE, durable=True
                    )
                    logger.info(f"Dead Letter Queue declared: {self.DEAD_LETTER_QUEUE}")


                try:
                    # First try passive declaration to check if queue exists
                    self.submission_queue = await self.channel.declare_queue(
                        self.SUBMISSION_QUEUE, 
                        durable=True,
                        passive=True  # Only check, don't create
                    )
                    logger.info(f"Submission queue already exists: {self.SUBMISSION_QUEUE}")
                except Exception:
                    # Queue doesn't exist, create it
                    self.submission_queue = await self.channel.declare_queue(
                        self.SUBMISSION_QUEUE, 
                        durable=True
                    )
                    logger.info(f"Submission queue created: {self.SUBMISSION_QUEUE}")


                
                try:
                    # First try passive declaration to check if queue exists
                    self.feedback_queue = await self.channel.declare_queue(
                        self.FEEDBACK_QUEUE, 
                        durable=True,
                        passive=True  # Only check, don't create
                    )
                    logger.info(f"Feedback queue already exists: {self.FEEDBACK_QUEUE}")
                except Exception:
                    # Queue doesn't exist, create it
                    self.feedback_queue = await self.channel.declare_queue(
                        self.FEEDBACK_QUEUE, 
                        durable=True
                    )
                    logger.info(f"Feedback queue created: {self.FEEDBACK_QUEUE}")


                logger.info(
                    f"Connected to RabbitMQ with prefetch_count={self.PREFETCH_COUNT}, all queues declared"
                )
                return
            except Exception as e:
                logger.error(f"RabbitMQ connection failed: {e}")
                attempt += 1
                if attempt > self.STARTUP_RETRY_LIMIT:
                    logger.error(
                        "Could not connect to RabbitMQ after multiple attempts."
                    )
                    raise e
                await asyncio.sleep(self.STARTUP_RETRY_DELAY)

    async def publish_message(self, message_body):
        """Publish to feedback queue and handle failures."""
        try:
            await self.channel.default_exchange.publish(
                aio_pika.Message(body=json.dumps(message_body).encode()),
                routing_key=self.FEEDBACK_QUEUE,
            )
            logger.info(
                f"Published submission {message_body.get('submission_id')} for user {message_body.get('student_id')}"
            )
            logger.info(f"Published message body: {message_body}")
        except asyncio.CancelledError as e:
            logger.warning("publish_message CancelledError")
            raise Exception("publish_message CancelledError") from e
        except (
            asyncio.TimeoutError,
            aio_pika.exceptions.AMQPConnectionError,
            aio_pika.exceptions.ChannelInvalidStateError,
        ) as e:
            logger.error(f"RabbitMQ unavailable to publish: {e}")
            raise Exception("RabbitMQ unavailable to publish") from e

    async def publish_to_dlq(self, message_body, reason: str = "Max retries exceeded"):
        """
        Publish permanently failed message to Dead Letter Queue.

        Args:
            message_body: The original message that failed (dict)
            reason: Reason for failure (string)

        Note:
            Only publishes if DEAD_LETTER_QUEUE is configured in environment.
            Enriches the message with failure metadata for debugging.
        """
        if not self.DEAD_LETTER_QUEUE:
            logger.debug("Dead Letter Queue not configured, skipping DLQ publish")
            return False

        try:
            # Extract key identifiers for logging
            submission_id = message_body.get("submission_id", "unknown")
            student_id = message_body.get("student_id", "unknown")

            # Add comprehensive failure metadata
            dlq_message = {
                "original_message": message_body,
                "failure_reason": reason,
                "failed_at": datetime.utcnow().isoformat(),
                "submission_id": submission_id,
                "student_id": student_id,
                "retry_count": message_body.get("retry_count", 0),
                "dlq_source": "plagiarism_checker",
            }

            await self.channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(dlq_message).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers={
                        "x-failed-at": datetime.utcnow().isoformat(),
                        "x-failure-reason": reason[
                            :255
                        ],  # Truncate for header size limit
                        "x-submission-id": submission_id,
                    },
                ),
                routing_key=self.DEAD_LETTER_QUEUE,
            )
            logger.warning(
                f"Published failed message to DLQ: submission_id={submission_id}, "
                f"student_id={student_id}, reason={reason[:100]}"
            )
            return True

        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to publish to DLQ for submission {message_body.get('submission_id', 'unknown')}: {e}. "
                f"Message details: {json.dumps(message_body, default=str)[:500]}"
            )
            return False

    async def start_consumer(self, callback):
        """Start consuming messages from the submission queue."""
        await self.connect()
        await self.submission_queue.consume(lambda msg: callback(msg))

    async def close(self):
        """Close RabbitMQ connection and cancel pending tasks."""
        if self._closed:
            return

        self._closed = True
        logger.info("Closing RabbitMQ client...")

        # Cancel retry tasks
        if self.retry_submission and not self.retry_submission.done():
            self.retry_submission.cancel()
            try:
                await self.retry_submission
            except asyncio.CancelledError:
                pass

        if self.connection:
            await self.connection.close()
            logger.info("RabbitMQ connection closed")
