"""
Centralized configuration management with validation.

Uses pydantic for type validation and sensible defaults.
All configuration can be overridden via environment variables.
"""

import logging
from typing import Optional, Literal
from pydantic import BaseSettings, Field, validator
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


class DatabaseConfig(BaseSettings):
    """Database connection configuration."""

    user: str = Field(..., env="POSTGRES_USER")
    password: str = Field(..., env="POSTGRES_PASSWORD")
    database: str = Field(..., env="POSTGRES_DB")
    host: str = Field(default="localhost", env="POSTGRES_HOST")
    port: int = Field(default=5432, env="POSTGRES_PORT")
    min_pool_size: int = Field(default=5, env="DB_MIN_POOL_SIZE")
    max_pool_size: int = Field(default=20, env="DB_MAX_POOL_SIZE")
    command_timeout: int = Field(default=60, env="DB_COMMAND_TIMEOUT")
    connection_timeout: int = Field(default=30, env="DB_CONNECTION_TIMEOUT")

    @validator("port")
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @validator("min_pool_size", "max_pool_size")
    def validate_pool_size(cls, v):
        if v < 1:
            raise ValueError("Pool size must be at least 1")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


class RabbitMQConfig(BaseSettings):
    """RabbitMQ message queue configuration."""

    host: str = Field(default="localhost", env="RABBITMQ_HOST")
    port: int = Field(default=5672, env="RABBITMQ_PORT")
    vhost: str = Field(default="/", env="RABBITMQ_VHOST")
    user: str = Field(default="guest", env="RABBITMQ_USER")
    password: str = Field(default="guest", env="RABBITMQ_PASS")
    submission_queue: str = Field(
        default="plagiarism_submissions", env="SUBMISSION_QUEUE"
    )
    feedback_queue: str = Field(default="plagiarism_feedback", env="FEEDBACK_QUEUE")
    prefetch_count: int = Field(default=10, env="RABBITMQ_PREFETCH_COUNT")
    startup_retry_limit: int = Field(default=5, env="STARTUP_RETRY_LIMIT")
    startup_retry_delay: int = Field(default=10, env="STARTUP_RETRY_DELAY")
    max_retries: int = Field(default=3, env="MAX_RETRIES")
    retry_backoff_seconds: int = Field(default=30, env="RETRY_BACKOFF_SECONDS")

    @validator("port")
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @validator("prefetch_count")
    def validate_prefetch(cls, v):
        if v < 1 or v > 100:
            raise ValueError("Prefetch count must be between 1 and 100")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def url(self) -> str:
        """Generate RabbitMQ connection URL."""
        return (
            f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"
        )


class DetectionConfig(BaseSettings):
    """Plagiarism detection algorithm configuration."""

    exact_dup_threshold: float = Field(default=0.95, env="EXACT_DUPLICATE_THRESHOLD")
    near_dup_threshold: float = Field(default=0.90, env="NEAR_DUPLICATE_THRESHOLD")
    semantic_threshold: float = Field(default=0.80, env="SEMANTIC_MATCH_THRESHOLD")

    # Hash matching thresholds (Hamming distance, 0-64 bits)
    hash_threshold: int = Field(default=8, env="HASH_MATCH_THRESHOLD")
    peer_hash_threshold: int = Field(default=8, env="PEER_HASH_THRESHOLD")
    self_hash_threshold: int = Field(default=8, env="SELF_HASH_THRESHOLD")

    # Resubmission window (days)
    resubmission_window_days: int = Field(default=7, env="RESUBMISSION_WINDOW_DAYS")
    resubmission_window_minutes: Optional[int] = Field(
        default=None, env="RESUBMISSION_WINDOW_MINUTES"
    )

    # Feature flags
    enable_peer_check: bool = Field(default=True, env="ENABLE_PEER_CHECK")
    enable_self_check: bool = Field(default=True, env="ENABLE_SELF_CHECK")

    @validator("exact_dup_threshold", "near_dup_threshold", "semantic_threshold")
    def validate_threshold(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Threshold must be between 0.0 and 1.0")
        return v

    @validator("hash_threshold", "peer_hash_threshold", "self_hash_threshold")
    def validate_hash_threshold(cls, v):
        if not 0 <= v <= 64:
            raise ValueError("Hash threshold must be between 0 and 64 bits")
        return v

    @validator("resubmission_window_days")
    def validate_resubmission_window(cls, v):
        if v < 0:
            raise ValueError("Resubmission window must be non-negative")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


class VectorSearchConfig(BaseSettings):
    """Vector search (FAISS/pgvector) configuration."""

    use_pgvector: bool = Field(default=False, env="USE_PGVECTOR")
    faiss_top_k: int = Field(default=4, env="FAISS_TOP_K")
    faiss_index_path: str = Field(
        default="./data/faiss_index.bin", env="FAISS_INDEX_PATH"
    )
    faiss_metadata_path: str = Field(
        default="./data/faiss_metadata.json", env="FAISS_METADATA_PATH"
    )
    clip_model: str = Field(default="ViT-B/32", env="CLIP_MODEL")
    clip_device: Literal["cpu", "cuda"] = Field(default="cpu", env="CLIP_DEVICE")
    clip_pretrained: str = Field(default="laion2B-s32B-b82K", env="CLIP_PRETRAINED")
    clip_local_model_path: Optional[str] = Field(
        default=None, env="CLIP_LOCAL_MODEL_PATH"
    )
    embedding_dimension: int = Field(default=512, env="EMBEDDING_DIMENSION")

    @validator("faiss_top_k")
    def validate_top_k(cls, v):
        if not 1 <= v <= 100:
            raise ValueError("FAISS top-K must be between 1 and 100")
        return v

    @validator("embedding_dimension")
    def validate_dimension(cls, v):
        if v not in [512, 768, 1024]:
            raise ValueError("Embedding dimension must be 512, 768, or 1024")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


class ImageProcessingConfig(BaseSettings):
    """Image download and processing configuration."""

    max_image_width: int = Field(default=512, env="MAX_IMAGE_WIDTH")
    max_image_height: int = Field(default=512, env="MAX_IMAGE_HEIGHT")
    download_timeout: int = Field(default=30, env="IMAGE_DOWNLOAD_TIMEOUT")
    download_retries: int = Field(default=3, env="IMAGE_DOWNLOAD_RETRIES")
    hash_size: int = Field(default=8, env="HASH_SIZE")
    disable_ssl_verify: bool = Field(default=False, env="DISABLE_SSL_VERIFY")

    # Image validation thresholds
    min_variance_threshold: float = Field(default=5.0, env="IMAGE_MIN_VARIANCE")
    min_unique_colors: int = Field(default=10, env="IMAGE_MIN_UNIQUE_COLORS")
    max_solid_color_ratio: float = Field(
        default=0.95, env="IMAGE_MAX_SOLID_COLOR_RATIO"
    )

    @validator("max_image_width", "max_image_height")
    def validate_dimensions(cls, v):
        if not 64 <= v <= 4096:
            raise ValueError("Image dimensions must be between 64 and 4096 pixels")
        return v

    @validator("download_timeout")
    def validate_timeout(cls, v):
        if not 1 <= v <= 300:
            raise ValueError("Download timeout must be between 1 and 300 seconds")
        return v

    @validator("download_retries")
    def validate_retries(cls, v):
        if not 0 <= v <= 10:
            raise ValueError("Download retries must be between 0 and 10")
        return v

    @validator("hash_size")
    def validate_hash_size(cls, v):
        if v not in [8, 16]:
            raise ValueError("Hash size must be 8 or 16 (for 64-bit or 256-bit hash)")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", env="LOG_LEVEL"
    )
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="LOG_FORMAT",
    )

    class Config:
        env_file = ".env"
        case_sensitive = False


class AppConfig(BaseSettings):
    """Main application configuration aggregating all sub-configs."""

    database: DatabaseConfig = DatabaseConfig()
    rabbitmq: RabbitMQConfig = RabbitMQConfig()
    detection: DetectionConfig = DetectionConfig()
    vector_search: VectorSearchConfig = VectorSearchConfig()
    image_processing: ImageProcessingConfig = ImageProcessingConfig()
    logging: LoggingConfig = LoggingConfig()

    app_name: str = Field(default="MentorMe Plagiarism Detection", env="APP_NAME")
    app_version: str = Field(default="1.0.0", env="APP_VERSION")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", env="ENVIRONMENT"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False

    def validate_all(self) -> None:
        """
        Validate all configuration settings.

        Raises:
            ValueError: If any configuration is invalid
        """

        if self.detection.near_dup_threshold >= self.detection.exact_dup_threshold:
            raise ValueError(
                "Near duplicate threshold must be less than exact duplicate threshold"
            )

        if self.detection.semantic_threshold >= self.detection.near_dup_threshold:
            raise ValueError(
                "Semantic threshold must be less than near duplicate threshold"
            )

    def print_config(self) -> str:
        """Print configuration summary (without sensitive data)."""
        config_summary = f"""
MentorMe Plagiarism Detection System Configuration
====================================================
Environment: {self.environment}
Version: {self.app_version}

Database:
  Host: {self.database.host}:{self.database.port}
  Database: {self.database.database}
  Pool Size: {self.database.min_pool_size}-{self.database.max_pool_size}

Message Queue:
  Host: {self.rabbitmq.host}:{self.rabbitmq.port}
  Submission Queue: {self.rabbitmq.submission_queue}
  Feedback Queue: {self.rabbitmq.feedback_queue}
  Prefetch Count: {self.rabbitmq.prefetch_count}

Detection Thresholds:
  Exact Duplicate: {self.detection.exact_dup_threshold}
  Near Duplicate: {self.detection.near_dup_threshold}
  Semantic Match: {self.detection.semantic_threshold}
  Hash Threshold: {self.detection.hash_threshold} bits
  Resubmission Window: {self.detection.resubmission_window_days} days

Vector Search:
  Backend: {"pgvector" if self.vector_search.use_pgvector else "FAISS"}
  CLIP Model: {self.vector_search.clip_model}
  Device: {self.vector_search.clip_device}
  Top-K Results: {self.vector_search.faiss_top_k}

Image Processing:
  Max Size: {self.image_processing.max_image_width}x{self.image_processing.max_image_height}
  Download Timeout: {self.image_processing.download_timeout}s
  Download Retries: {self.image_processing.download_retries}

Logging:
  Level: {self.logging.log_level}
====================================================
"""
        return config_summary


# Global configuration instance
try:
    config = AppConfig()
    config.validate_all()
except Exception as e:
    logger.error(f"Configuration error: {e}")
    raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info(config.print_config())
