class MQClient:
    """Abstract base class for message queue clients."""

    # Optional queue name constant - subclasses may define this
    SUBMISSION_QUEUE: str = "submissions"

    async def connect(self):
        """Establish connection to the message queue."""
        pass

    async def handle_failed_message(self, message_body):
        """Handle a message that failed to publish."""
        pass

    async def call_retry_submission(self):
        """Trigger retry mechanism for failed messages."""
        pass

    async def publish_message(self, message_body):
        """Publish a message to the queue."""
        pass

    async def retry_failed_messages(self):
        """Retry publishing failed messages."""
        pass

    async def start_consumer(self, callback):
        """Start consuming messages with the given callback."""
        pass

    async def close(self):
        """Close connections and cleanup resources."""
        pass

    # Optional hook to publish messages to a dead-letter queue
    async def publish_to_dlq(self, message_body, reason: str = "") -> bool:
        """
        Publish a failed message to a Dead Letter Queue (optional).
        
        Args:
            message_body: The message that failed
            reason: Reason for failure
            
        Returns:
            bool: True if successfully published to DLQ, False otherwise
        """
        return False  # Default implementation does nothing
