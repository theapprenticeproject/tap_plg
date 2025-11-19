"""
Comprehensive tests for config module.

Tests for configuration validation, environment variable loading,
and pydantic model validation.
"""

import pytest
from pydantic import ValidationError

from config.config import (
    DatabaseConfig,
    RabbitMQConfig,
    DetectionConfig,
    VectorSearchConfig,
    ImageProcessingConfig,
    AppConfig,
    config,
)


class TestDatabaseConfig:
    """Tests for database configuration."""

    def test_database_config_defaults(self):
        """Test database config defaults."""
        db_config = DatabaseConfig()

        assert db_config.host == "localhost"
        assert db_config.port == 5432
        assert db_config.min_pool_size == 5
        assert db_config.max_pool_size == 20

    def test_database_config_invalid_port(self, monkeypatch):
        """Test database config with invalid port."""
        monkeypatch.setenv("POSTGRES_PORT", "99999")

        with pytest.raises(ValidationError):
            DatabaseConfig()

    def test_database_config_pool_size_validation(self, monkeypatch):
        """Test database config pool size validation."""
        monkeypatch.setenv("DB_MIN_POOL_SIZE", "0")

        with pytest.raises(ValidationError):
            DatabaseConfig()


class TestRabbitMQConfig:
    """Tests for RabbitMQ configuration."""

    def test_rabbitmq_config_defaults(self):
        """Test RabbitMQ config defaults."""
        mq_config = RabbitMQConfig()

        assert mq_config.host == "localhost"
        assert mq_config.port == 5672
        assert mq_config.vhost == "/"
        assert mq_config.submission_queue == "plagiarism_submissions"
        assert mq_config.feedback_queue == "plagiarism_feedback"

    def test_rabbitmq_url_generation(self):
        """Test RabbitMQ URL generation."""
        mq_config = RabbitMQConfig()
        url = mq_config.url

        assert "amqp://" in url
        assert "@" in url
        assert ":" in url

    def test_rabbitmq_invalid_port(self, monkeypatch):
        """Test RabbitMQ config with invalid port."""
        monkeypatch.setenv("RABBITMQ_PORT", "0")

        with pytest.raises(ValidationError):
            RabbitMQConfig()

    def test_rabbitmq_invalid_prefetch_count(self, monkeypatch):
        """Test RabbitMQ config with invalid prefetch count."""
        monkeypatch.setenv("RABBITMQ_PREFETCH_COUNT", "150")

        with pytest.raises(ValidationError):
            RabbitMQConfig()


class TestDetectionConfig:
    """Tests for detection configuration."""

    def test_detection_config_defaults(self):
        """Test detection config defaults."""
        det_config = DetectionConfig()

        assert det_config.exact_dup_threshold == 0.95
        assert det_config.near_dup_threshold == 0.90
        assert det_config.semantic_threshold == 0.80

    def test_detection_config_custom_values(self, monkeypatch):
        """Test detection config with custom values."""
        monkeypatch.setenv("EXACT_DUPLICATE_THRESHOLD", "0.98")
        monkeypatch.setenv("NEAR_DUPLICATE_THRESHOLD", "0.92")
        monkeypatch.setenv("SEMANTIC_MATCH_THRESHOLD", "0.85")

        det_config = DetectionConfig()

        assert det_config.exact_dup_threshold == 0.98
        assert det_config.near_dup_threshold == 0.92
        assert det_config.semantic_threshold == 0.85

    def test_detection_config_threshold_validation(self, monkeypatch):
        """Test detection config threshold validation."""
        monkeypatch.setenv("EXACT_DUPLICATE_THRESHOLD", "1.5")

        with pytest.raises(ValidationError):
            DetectionConfig()


class TestVectorSearchConfig:
    """Tests for vector search configuration."""

    def test_vector_search_config_defaults(self):
        """Test vector search config defaults."""
        vec_config = VectorSearchConfig()

        assert not vec_config.use_pgvector
        assert vec_config.faiss_top_k == 4
        # Default can be overridden by .env, so check it's a valid model name
        assert vec_config.clip_model in ["ViT-B/32", "ViT-L/14", "ViT-L-14"]

    def test_vector_search_pgvector_mode(self, monkeypatch):
        """Test vector search with pgvector enabled."""
        monkeypatch.setenv("USE_PGVECTOR", "true")

        vec_config = VectorSearchConfig()

        assert vec_config.use_pgvector


class TestImageProcessingConfig:
    """Tests for image processing configuration."""

    def test_image_processing_defaults(self):
        """Test image processing config defaults."""
        img_config = ImageProcessingConfig()

        assert img_config.max_image_width == 512
        assert img_config.max_image_height == 512
        assert img_config.hash_size == 8

    def test_image_processing_custom_values(self, monkeypatch):
        """Test image processing with custom values."""
        monkeypatch.setenv("MAX_IMAGE_WIDTH", "1024")
        monkeypatch.setenv("HASH_SIZE", "16")

        img_config = ImageProcessingConfig()

        assert img_config.max_image_width == 1024
        assert img_config.hash_size == 16


class TestAppConfig:
    """Tests for application configuration."""

    def test_app_config_initialization(self):
        """Test application config initialization."""
        app_config = AppConfig()

        assert app_config.database is not None
        assert app_config.rabbitmq is not None
        assert app_config.detection is not None
        assert app_config.vector_search is not None
        assert app_config.image_processing is not None

    def test_global_config_instance(self):
        """Test global config instance exists."""
        assert config is not None
        assert isinstance(config, AppConfig)

    def test_config_components_accessible(self):
        """Test that all config components are accessible."""
        assert hasattr(config, "database")
        assert hasattr(config, "rabbitmq")
        assert hasattr(config, "detection")
        assert hasattr(config, "vector_search")
        assert hasattr(config, "image_processing")

    def test_config_print(self):
        """Test config print method."""
        config_str = config.print_config()
        assert "MentorMe Plagiarism Detection System Configuration" in config_str
        assert "Database:" in config_str
        assert "Message Queue:" in config_str

    def test_config_validation(self):
        """Test config validation method."""
        # Should not raise for default values
        config.validate_all()
