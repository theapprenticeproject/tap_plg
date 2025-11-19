import json
import logging
import os

from plag_checker.submission_status import SubmissionStatus
from mq.mq_client import MQClient
from database.db_manager import DatabaseManager
from processors.image_processor import ImageProcessor
from processors.text_processor import TextProcessor

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from image_worker.worker import ImageWorker

logger = logging.getLogger(__name__)


class MessageAckManager:
    """
    Context manager to ensure message acknowledgment happens exactly once.
    Prevents race conditions and message loss.
    """

    def __init__(self, message):
        self.message = message
        self.acked = False
        self.action = None  # Will be 'ack', 'nack', or 'reject'

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Ensure message is acknowledged exactly once on exit."""
        if not self.acked:
            # Default behavior: reject without requeue on unhandled errors
            logger.warning(
                "Message not explicitly acknowledged, rejecting (requeue=False)"
            )
            try:
                await self.message.reject(requeue=False)
                self.acked = True
                self.action = "reject(cleanup)"
            except Exception as e:
                logger.critical(f"CRITICAL: Failed to reject message in cleanup: {e}")
                # DO NOT set self.acked = True here - let finally block handle it
        return False  # Don't suppress exceptions

    async def ack(self):
        """Acknowledge successful processing."""
        if self.acked:
            logger.warning("Attempted to ack already-acknowledged message")
            return
        await self.message.ack()
        self.acked = True
        self.action = "ack"

    async def nack(self, requeue: bool = True):
        """Negative acknowledgment (for retry)."""
        if self.acked:
            logger.warning("Attempted to nack already-acknowledged message")
            return
        await self.message.nack(requeue=requeue)
        self.acked = True
        self.action = f"nack(requeue={requeue})"

    async def reject(self, requeue: bool = False):
        """Reject message (typically for poison messages)."""
        if self.acked:
            logger.warning("Attempted to reject already-acknowledged message")
            return
        await self.message.reject(requeue=requeue)
        self.acked = True
        self.action = f"reject(requeue={requeue})"


class SubmissionChecker:
    def __init__(
        self,
        mq_client: MQClient,
        db_manager: "DatabaseManager | None" = None,
        image_worker: "ImageWorker | None" = None,
        startup_retry_delay: int = 30,
    ):
        self.client = mq_client
        self.db = db_manager if db_manager else DatabaseManager()
        self._owns_db_manager = db_manager is None

        # Initialize processors with shared resources
        # Image worker will be initialized in initialize() if not provided
        self.image_worker = image_worker
        self._owns_image_worker = image_worker is None

        self.image_processor = None  # Will be set after image_worker initialization
        self.text_processor = TextProcessor()

        self.STARTUP_RETRY_DELAY = startup_retry_delay
        self.MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
        self._shutdown = False

    async def initialize(self):
        await self.start_db()

        # Initialize ImageWorker if not provided (load models once)
        if self._owns_image_worker:
            from image_worker.worker import ImageWorker

            self.image_worker = ImageWorker(db_manager=self.db)
            await self.image_worker.initialize()

        # Now initialize ImageProcessor with the shared worker
        self.image_processor = ImageProcessor(
            db_manager=self.db, image_worker=self.image_worker
        )

        # Validate system is ready before starting consumer
        if self.image_processor is None:
            raise RuntimeError("ImageProcessor failed to initialize")
        if self.image_worker is None:
            raise RuntimeError("ImageWorker failed to initialize")

        await self.start_consumer()

    async def process_submission(self, submission):
        if self._shutdown:
            logger.warning("Shutdown in progress, rejecting message")
            try:
                await submission.nack(requeue=False)
            except Exception as e:
                logger.error(f"Failed to nack message during shutdown: {e}")
            return

        retry_count = 0
        status = SubmissionStatus.SUBMITTED
        submission_id = "unknown"
        data = {}
        message_acked = False

        try:
            body = submission.body

            if isinstance(body, (bytes, bytearray)):
                text = body.decode("utf-8", errors="replace")
                data = json.loads(text)
            elif isinstance(body, str):
                data = json.loads(body)
            elif isinstance(body, dict):
                data = body
            else:
                try:
                    data = json.loads(str(body))
                except Exception:
                    data = {"payload": body}

            submission_id = data.get("submission_id", "unknown")

            redelivered = getattr(submission, "redelivered", False)
            delivery_count = 0

            if hasattr(submission, "headers") and submission.headers:
                delivery_count = submission.headers.get("x-delivery-count", 0)

            if redelivered and delivery_count == 0:
                delivery_count = 1

            if delivery_count > self.MAX_RETRIES:
                logger.error(
                    f"Poison message detected for submission {submission_id}: "
                    f"delivery_count={delivery_count} exceeds MAX_RETRIES={self.MAX_RETRIES}"
                )
                await self.db.update_status(
                    submission_id,
                    SubmissionStatus.FAILED,
                    delivery_count,
                    f"Poison message: exceeded {self.MAX_RETRIES} redelivery attempts",
                )

                dlq_success = await self.client.publish_to_dlq(
                    data,
                    reason=f"Poison message: {delivery_count} redeliveries exceeded MAX_RETRIES={self.MAX_RETRIES}",
                )
                if not dlq_success:
                    logger.error(
                        f"Failed to send poison message to DLQ for submission {submission_id}"
                    )

                await submission.nack(
                    submission, requeue=False, submission_id=submission_id
                )
                message_acked = True
                return

            image_url = data.get("img_url") or data.get("image_url")

            record_id = await self.db.insert_submission_if_not_exists(
                data, image_url or "", status
            )
            if not image_url:
                logger.error(f"No image URL in submission {submission_id}")
                await self.db.update_status(
                    submission_id,
                    SubmissionStatus.FAILED,
                    0,
                    "No image URL in submission",
                )
                await submission.nack(
                    submission, requeue=False, submission_id=submission_id
                )
                message_acked = True
                return

            retry_count = await self.db.get_retry_count(record_id)
            if not isinstance(retry_count, int):
                retry_count = 0

            data["db_record_id"] = str(record_id)  # Convert UUID to string

            # Get processor and validate initialization
            try:
                processor = self.get_processor(data)
            except RuntimeError as init_error:
                # Processor not initialized - this is a system error, should retry
                logger.error(f"System not ready: {init_error}")
                await self.db.update_status(
                    submission_id,
                    SubmissionStatus.FAILED,
                    0,
                    f"System initialization error: {str(init_error)}",
                )
                await submission.nack(
                    submission, requeue=True, submission_id=submission_id
                )  # Retry - system might be initializing
                message_acked = True
                return
            except ValueError as validation_error:
                # Invalid message format - should not retry
                logger.error(
                    f"Invalid message format for submission {submission_id}: {validation_error}"
                )
                await self.db.update_status(
                    submission_id,
                    SubmissionStatus.FAILED,
                    0,
                    f"Invalid message format: {str(validation_error)}",
                )
                await submission.nack(
                    submission, requeue=False, submission_id=submission_id
                )  # Don't retry invalid format
                message_acked = True
                return

            result_text = await processor.process(data)

            try:
                if isinstance(result_text, (str, bytes, bytearray)):
                    result_text = json.loads(result_text)

                if not isinstance(result_text, dict):
                    raise ValueError("Processing result is not a JSON object")

                if result_text.get("error") is not None:
                    error_msg = result_text.get("error", "Unknown error")
                    logger.warning(
                        f"Invalid result for submission {submission_id}: {error_msg}"
                    )
                    raise ValueError(f"Invalid result: {error_msg}")
            except (json.JSONDecodeError, ValueError) as parse_error:
                logger.warning(
                    f"Invalid result for submission {submission_id}: {parse_error}"
                )
                await self.db.update_status(
                    submission_id or "unknown",
                    SubmissionStatus.FAILED,
                    int(retry_count or 0),
                    f"Invalid processing result: {str(parse_error)}",
                )
                await submission.nack(requeue=False)
                message_acked = True
                return

            data["similar_sources"] = result_text.get("similar_sources")
            data["similarity_score"] = result_text.get("similarity_score")
            data["is_plagiarized"] = result_text.get("is_plagiarized")
            data["match_type"] = result_text.get("match_type")

            publish_data = {k: v for k, v in data.items() if k != "db_record_id"}

            message_to_update_db = {
                "similar_sources": data["similar_sources"],
                "similarity_score": data["similarity_score"],
            }

            await self.db.update_result(
                submission_id, message_to_update_db, SubmissionStatus.EVALUATED
            )
            status = SubmissionStatus.EVALUATED
            await self.client.publish_message(publish_data)

            await submission.ack()
            message_acked = True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
            await submission.nack(
                submission, requeue=False, submission_id=submission_id
            )
            message_acked = True

        except RuntimeError as e:
            if "pool is closed" in str(e).lower():
                logger.warning(
                    f"Database pool closed during processing of {submission_id}, "
                    f"rejecting message (shutdown={self._shutdown})"
                )
                await submission.nack(
                    submission, requeue=False, submission_id=submission_id
                )
                message_acked = True
            else:
                raise

        except Exception as e:
            logger.error(
                f"Error processing submission {submission_id}: type={type(e).__name__}, message={str(e)}",
                exc_info=True,
            )
            try:
                rc = int(retry_count or 0)

                if rc < self.MAX_RETRIES:
                    await self.db.update_status(
                        submission_id or "unknown",
                        status,
                        rc + 1,
                        f"Retry {rc + 1}/{self.MAX_RETRIES}: {str(e)[:200]}",
                    )
                    await submission.nack(
                        submission, requeue=True, submission_id=submission_id
                    )
                    message_acked = True
                else:
                    await self.db.update_status(
                        submission_id or "unknown",
                        SubmissionStatus.FAILED,
                        rc,
                        f"Max retries ({self.MAX_RETRIES}) exceeded: {str(e)[:200]}",
                    )

                    dlq_success = await self.client.publish_to_dlq(
                        data or {},
                        reason=f"Max retries ({rc}) exceeded: {str(e)[:100]}",
                    )
                    if not dlq_success:
                        logger.error(
                            f"Failed to send max-retry message to DLQ for submission {submission_id}"
                        )

                    await submission.nack(
                        submission, requeue=False, submission_id=submission_id
                    )
                    message_acked = True
                    logger.warning(
                        f"Message discarded after {rc} retries and sent to DLQ"
                    )
            except Exception as nack_error:
                logger.error(
                    f"Failed to handle error for {submission_id}: {nack_error}"
                )
                # Don't re-raise - message will be handled in finally block

        finally:
            # Final safety net: ensure message is acknowledged
            if not message_acked:
                logger.warning(
                    f"Emergency reject for un-acknowledged message {submission_id}"
                )
                await submission.reject()
                message_acked = True

    def get_processor(self, data: dict):
        """
        Get the appropriate processor for the submission data.

        Raises:
            RuntimeError: If processor is not initialized
            ValueError: If data format is invalid
        """
        if data.get("img_url"):
            if self.image_processor is None:
                raise RuntimeError(
                    "ImageProcessor not initialized - initialize() must be called before processing messages"
                )
            return self.image_processor
        elif data.get("text"):
            return self.text_processor
        else:
            raise ValueError(
                "Invalid submission format: missing both 'img_url' and 'text' fields"
            )

    async def start_consumer(self):
        await self.client.start_consumer(self.process_submission)

    async def start_db(self):
        await self.db.init_pool()

    async def close(self):
        self._shutdown = True

        await self.client.close()

        # Close ImageWorker if we own it
        if self._owns_image_worker and self.image_worker is not None:
            await self.image_worker.close()

        if self._owns_db_manager:
            await self.db.close()
