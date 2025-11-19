"""
Unit tests for custom exceptions.
"""

import pytest
from utils.exceptions import (
    MentorMeError,
    ImageProcessingError,
    ImageDownloadError,
    NetworkTimeoutError,
    InvalidImageURLError,
    InvalidImageFormatError,
    ImageTooLargeError,
    DetectionError,
    HashComputationError,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseNotInitializedError,
    RecordNotFoundError,
    DuplicateRecordError,
    MessageQueueError,
    MessageQueueConnectionError,
    MessagePublishError,
    MessageConsumeError,
    ConfigurationError,
    MissingConfigurationError,
    InvalidConfigurationError,
    WorkerError,
    WorkerNotInitializedError,
    ValidationError,
    create_error_response,
    _get_error_category,
)


class TestMentorMeError:
    """Test cases for base MentorMeError."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = MentorMeError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_error_with_details(self):
        """Test error with details."""
        details = {"field": "image_url", "value": "invalid"}
        error = MentorMeError("Invalid input", details=details)

        assert error.message == "Invalid input"
        assert error.details == details

    def test_error_inheritance(self):
        """Test that MentorMeError is an Exception."""
        error = MentorMeError("Test")
        assert isinstance(error, Exception)


class TestImageProcessingErrors:
    """Test image processing error hierarchy."""

    def test_image_processing_error(self):
        """Test ImageProcessingError."""
        error = ImageProcessingError("Failed to process image")
        assert isinstance(error, MentorMeError)
        assert str(error) == "Failed to process image"

    def test_image_download_error(self):
        """Test ImageDownloadError."""
        error = ImageDownloadError("Failed to download")
        assert isinstance(error, ImageProcessingError)

    def test_network_timeout_error(self):
        """Test NetworkTimeoutError."""
        error = NetworkTimeoutError("Connection timed out")
        assert isinstance(error, ImageDownloadError)

    def test_invalid_image_url_error(self):
        """Test InvalidImageURLError."""
        error = InvalidImageURLError("Invalid URL format")
        assert isinstance(error, ImageDownloadError)

    def test_invalid_image_format_error(self):
        """Test InvalidImageFormatError."""
        error = InvalidImageFormatError("Unsupported format")
        assert isinstance(error, ImageProcessingError)

    def test_image_too_large_error(self):
        """Test ImageTooLargeError."""
        error = ImageTooLargeError("Image exceeds 10MB")
        assert isinstance(error, ImageProcessingError)


class TestDetectionErrors:
    """Test detection error hierarchy."""

    def test_detection_error(self):
        """Test DetectionError."""
        error = DetectionError("Detection failed")
        assert isinstance(error, MentorMeError)

    def test_hash_computation_error(self):
        """Test HashComputationError."""
        error = HashComputationError("Hash computation failed")
        assert isinstance(error, DetectionError)

    def test_embedding_generation_error(self):
        """Test EmbeddingGenerationError."""
        error = EmbeddingGenerationError("CLIP embedding failed")
        assert isinstance(error, DetectionError)

    def test_vector_search_error(self):
        """Test VectorSearchError."""
        error = VectorSearchError("FAISS search failed")
        assert isinstance(error, DetectionError)


class TestDatabaseErrors:
    """Test database error hierarchy."""

    def test_database_error(self):
        """Test DatabaseError."""
        error = DatabaseError("Database operation failed")
        assert isinstance(error, MentorMeError)

    def test_database_connection_error(self):
        """Test DatabaseConnectionError."""
        error = DatabaseConnectionError("Connection refused")
        assert isinstance(error, DatabaseError)

    def test_database_not_initialized_error(self):
        """Test DatabaseNotInitializedError."""
        error = DatabaseNotInitializedError("Pool not initialized")
        assert isinstance(error, DatabaseError)

    def test_record_not_found_error(self):
        """Test RecordNotFoundError."""
        error = RecordNotFoundError("Record not found")
        assert isinstance(error, DatabaseError)

    def test_duplicate_record_error(self):
        """Test DuplicateRecordError."""
        error = DuplicateRecordError("Duplicate key")
        assert isinstance(error, DatabaseError)


class TestMessageQueueErrors:
    """Test message queue error hierarchy."""

    def test_message_queue_error(self):
        """Test MessageQueueError."""
        error = MessageQueueError("MQ operation failed")
        assert isinstance(error, MentorMeError)

    def test_message_queue_connection_error(self):
        """Test MessageQueueConnectionError."""
        error = MessageQueueConnectionError("Cannot connect to RabbitMQ")
        assert isinstance(error, MessageQueueError)

    def test_message_publish_error(self):
        """Test MessagePublishError."""
        error = MessagePublishError("Failed to publish")
        assert isinstance(error, MessageQueueError)

    def test_message_consume_error(self):
        """Test MessageConsumeError."""
        error = MessageConsumeError("Failed to consume")
        assert isinstance(error, MessageQueueError)


class TestConfigurationErrors:
    """Test configuration error hierarchy."""

    def test_configuration_error(self):
        """Test ConfigurationError."""
        error = ConfigurationError("Invalid config")
        assert isinstance(error, MentorMeError)

    def test_missing_configuration_error(self):
        """Test MissingConfigurationError."""
        error = MissingConfigurationError("Missing API key")
        assert isinstance(error, ConfigurationError)

    def test_invalid_configuration_error(self):
        """Test InvalidConfigurationError."""
        error = InvalidConfigurationError("Invalid port number")
        assert isinstance(error, ConfigurationError)


class TestWorkerErrors:
    """Test worker error hierarchy."""

    def test_worker_error(self):
        """Test WorkerError."""
        error = WorkerError("Worker failed")
        assert isinstance(error, MentorMeError)

    def test_worker_not_initialized_error(self):
        """Test WorkerNotInitializedError."""
        error = WorkerNotInitializedError("Worker not ready")
        assert isinstance(error, WorkerError)

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Validation failed")
        assert isinstance(error, WorkerError)


class TestErrorResponse:
    """Test error response creation."""

    def test_create_error_response_basic(self):
        """Test creating basic error response."""
        error = ValueError("Invalid input")
        response = create_error_response("SUB-001", error)

        assert response["submission_id"] == "SUB-001"
        assert response["status"] == "failed"
        assert response["error"] == "Invalid input"
        assert response["error_type"] == "ValueError"

    def test_create_error_response_with_context(self):
        """Test creating error response with context."""
        error = ImageDownloadError("Failed to download")
        context = {"url": "https://example.com/image.jpg", "status_code": 404}

        response = create_error_response("SUB-002", error, context)

        assert response["submission_id"] == "SUB-002"
        assert response["error_context"] == context
        assert response["error_category"] == "image_processing"

    def test_create_error_response_with_details(self):
        """Test error response with MentorMeError details."""
        details = {"field": "img_url", "reason": "timeout"}
        error = NetworkTimeoutError("Timeout", details=details)

        response = create_error_response("SUB-003", error)

        assert response["error_details"] == details

    def test_error_category_image_processing(self):
        """Test error category for image processing errors."""
        error = ImageDownloadError("Test")
        assert _get_error_category(error) == "image_processing"

    def test_error_category_detection(self):
        """Test error category for detection errors."""
        error = HashComputationError("Test")
        assert _get_error_category(error) == "detection"

    def test_error_category_database(self):
        """Test error category for database errors."""
        error = DatabaseConnectionError("Test")
        assert _get_error_category(error) == "database"

    def test_error_category_message_queue(self):
        """Test error category for message queue errors."""
        error = MessagePublishError("Test")
        assert _get_error_category(error) == "message_queue"

    def test_error_category_configuration(self):
        """Test error category for configuration errors."""
        error = MissingConfigurationError("Test")
        assert _get_error_category(error) == "configuration"

    def test_error_category_worker(self):
        """Test error category for worker errors."""
        error = WorkerNotInitializedError("Test")
        assert _get_error_category(error) == "worker"

    def test_error_category_unknown(self):
        """Test error category for unknown errors."""
        error = ValueError("Test")
        assert _get_error_category(error) == "unknown"


class TestExceptionDetails:
    """Test exception details functionality."""

    def test_error_with_empty_details(self):
        """Test error with empty details dict."""
        error = MentorMeError("Test", details={})
        assert error.details == {}

    def test_error_with_none_details(self):
        """Test error with None details."""
        error = MentorMeError("Test", details=None)
        assert error.details == {}

    def test_error_with_complex_details(self):
        """Test error with complex details."""
        details = {
            "submission_id": "SUB-001",
            "error_location": "hash_handler.py:42",
            "attempted_hashes": ["phash", "dhash", "ahash"],
            "metadata": {"timestamp": "2025-11-06T12:00:00", "retry": 3},
        }
        error = ImageProcessingError("Processing failed", details=details)

        assert error.details == details
        assert error.details["submission_id"] == "SUB-001"
        assert len(error.details["attempted_hashes"]) == 3

    def test_exception_message_preserved(self):
        """Test that exception message is preserved."""
        message = "This is a detailed error message with context"
        error = DetectionError(message)

        assert str(error) == message
        assert error.message == message

    def test_error_response_all_fields(self):
        """Test error response contains all expected fields."""
        details = {"key": "value"}
        context = {"context_key": "context_value"}
        error = DatabaseError("DB failed", details=details)

        response = create_error_response("SUB-999", error, context)

        # Check all expected fields
        assert "submission_id" in response
        assert "status" in response
        assert "error" in response
        assert "error_type" in response
        assert "error_category" in response
        assert "error_context" in response
        assert "error_details" in response

        assert response["submission_id"] == "SUB-999"
        assert response["status"] == "failed"
        assert response["error_type"] == "DatabaseError"
        assert response["error_category"] == "database"
