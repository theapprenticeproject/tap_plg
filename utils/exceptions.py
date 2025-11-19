"""
Custom exception hierarchy for MentorMe plagiarism detection system.

This module defines a structured error taxonomy for better error handling,
debugging, and monitoring.
"""

from typing import Optional, Dict, Any


class MentorMeError(Exception):
    """Base exception for all MentorMe errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Image Processing Errors
class ImageProcessingError(MentorMeError):
    """Base exception for image processing failures."""

    pass


class ImageDownloadError(ImageProcessingError):
    """Failed to download image from URL."""

    pass


class NetworkTimeoutError(ImageDownloadError):
    """Network timeout while downloading image."""

    pass


class InvalidImageURLError(ImageDownloadError):
    """Invalid or malformed image URL."""

    pass


class InvalidImageFormatError(ImageProcessingError):
    """Image format is not supported or corrupted."""

    pass


class ImageTooLargeError(ImageProcessingError):
    """Image exceeds maximum allowed size."""

    pass


# Detection Errors
class DetectionError(MentorMeError):
    """Base exception for plagiarism detection failures."""

    pass


class HashComputationError(DetectionError):
    """Failed to compute perceptual hashes."""

    pass


class EmbeddingGenerationError(DetectionError):
    """Failed to generate CLIP embeddings."""

    pass


class VectorSearchError(DetectionError):
    """Failed to perform vector similarity search."""

    pass


# Database Errors
class DatabaseError(MentorMeError):
    """Base exception for database operations."""

    pass


class DatabaseConnectionError(DatabaseError):
    """Failed to connect to database."""

    pass


class DatabaseNotInitializedError(DatabaseError):
    """Database connection pool not initialized."""

    pass


class RecordNotFoundError(DatabaseError):
    """Requested database record not found."""

    pass


class DuplicateRecordError(DatabaseError):
    """Attempted to insert duplicate record."""

    pass


# Message Queue Errors
class MessageQueueError(MentorMeError):
    """Base exception for message queue operations."""

    pass


class MessageQueueConnectionError(MessageQueueError):
    """Failed to connect to message queue."""

    pass


class MessagePublishError(MessageQueueError):
    """Failed to publish message to queue."""

    pass


class MessageConsumeError(MessageQueueError):
    """Failed to consume message from queue."""

    pass


# Configuration Errors
class ConfigurationError(MentorMeError):
    """Base exception for configuration issues."""

    pass


class MissingConfigurationError(ConfigurationError):
    """Required configuration parameter is missing."""

    pass


class InvalidConfigurationError(ConfigurationError):
    """Configuration parameter has invalid value."""

    pass


# Worker Errors
class WorkerError(MentorMeError):
    """Base exception for worker-level errors."""

    pass


class WorkerNotInitializedError(WorkerError):
    """Worker not properly initialized before use."""

    pass


class ValidationError(WorkerError):
    """Input validation failed."""

    pass


# Utility function to create structured error response
def create_error_response(
    submission_id: str,
    error: Exception,
    error_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create standardized error response for failed submissions.

    Args:
        submission_id: Submission identifier
        error: Exception that occurred
        error_context: Additional context about the error

    Returns:
        Dictionary with error details
    """
    error_response: Dict[str, Any] = {
        "submission_id": submission_id,
        "status": "failed",
        "error": str(error),
        "error_type": type(error).__name__,
        "error_category": _get_error_category(error),
    }

    if error_context:
        error_response["error_context"] = error_context

    if isinstance(error, MentorMeError) and error.details:
        error_response["error_details"] = error.details

    return error_response


def _get_error_category(error: Exception) -> str:
    """Determine error category for monitoring/alerting."""
    if isinstance(error, ImageProcessingError):
        return "image_processing"
    elif isinstance(error, DetectionError):
        return "detection"
    elif isinstance(error, DatabaseError):
        return "database"
    elif isinstance(error, MessageQueueError):
        return "message_queue"
    elif isinstance(error, ConfigurationError):
        return "configuration"
    elif isinstance(error, WorkerError):
        return "worker"
    else:
        return "unknown"
