"""
Pytest configuration and shared fixtures for all tests.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock
from io import BytesIO

import pytest
import numpy as np
from PIL import Image

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set environment variables before any imports that use config
os.environ.update(
    {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test_db",
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password",
        "RABBITMQ_HOST": "localhost",
        "RABBITMQ_PORT": "5672",
        "RABBITMQ_USER": "guest",
        "RABBITMQ_PASS": "guest",
        "HASH_STUDENT_IDS": "false",
        "USE_PGVECTOR": "false",
    }
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_image() -> Image.Image:
    """Create a simple test image with gradient."""
    img_array = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(100):
        img_array[i, :] = [i * 2, i * 2, i * 2]
    return Image.fromarray(img_array, "RGB")


@pytest.fixture
def identical_image(sample_image: Image.Image) -> Image.Image:
    """Create an identical copy of sample image."""
    return sample_image.copy()


@pytest.fixture
def similar_image() -> Image.Image:
    """Create a similar but slightly different image."""
    img_array = np.zeros((100, 100, 3), dtype=np.uint8)
    for i in range(100):
        img_array[i, :] = [i * 2 + 5, i * 2 + 5, i * 2 + 5]
    return Image.fromarray(img_array, "RGB")


@pytest.fixture
def different_image() -> Image.Image:
    """Create a completely different image."""
    np.random.seed(123)
    img_array = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    return Image.fromarray(img_array, "RGB")


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    mock = AsyncMock()
    mock.pool = MagicMock()
    mock.init_pool = AsyncMock()
    mock.close = AsyncMock()
    mock.insert_submission_if_not_exists = AsyncMock(
        return_value="123e4567-e89b-12d3-a456-426614174000"
    )
    mock.update_submission = AsyncMock(return_value={"id": "test-id"})
    mock.fetch_peer_submissions = AsyncMock(return_value=[])
    mock.fetch_self_submissions = AsyncMock(return_value=[])
    mock.fetch_reference_images_by_id = AsyncMock(
        return_value="http://example.com/image.jpg"
    )
    return mock


@pytest.fixture
def mock_mq_client():
    """Create a mock message queue client."""
    mock = AsyncMock()
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.publish = AsyncMock()
    mock.consume = AsyncMock()
    return mock


@pytest.fixture
def sample_submission_data(sample_hashes, sample_clip_embedding):
    """Sample submission data for testing."""
    return {
        "submission_id": "SUB-001",
        "student_id": "ST001",
        "assign_id": "A001",
        "img_url": "https://example.com/image.jpg",
        "db_record_id": "123e4567-e89b-12d3-a456-426614174000",
        "hashes": sample_hashes,
        "clip_embedding": sample_clip_embedding,
    }


@pytest.fixture
def sample_hashes():
    """Sample hash dictionary for testing."""
    return {
        "phash": "abc123def4567890",
        "dhash": "1234567890abcdef",
        "ahash": "fedcba0987654321",
    }


@pytest.fixture
def sample_clip_embedding():
    """Sample CLIP embedding vector (512D normalized)."""
    np.random.seed(42)
    embedding = np.random.randn(512).astype(np.float32)
    embedding = embedding / np.linalg.norm(embedding)
    return embedding


@pytest.fixture
def set_test_env():
    """Set environment variables for testing."""
    original_env = os.environ.copy()

    os.environ.update(
        {
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "test_db",
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test_password",
            "RABBITMQ_HOST": "localhost",
            "RABBITMQ_PORT": "5672",
            "RABBITMQ_USER": "guest",
            "RABBITMQ_PASS": "guest",
            "HASH_STUDENT_IDS": "true",
            "ENVIRONMENT": "testing",
        }
    )

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
async def mock_asyncpg_pool():
    """Create a comprehensive mock asyncpg connection pool with realistic responses."""
    pool = AsyncMock()
    pool.close = AsyncMock()
    pool.acquire = AsyncMock()

    # Mock connection context manager with comprehensive methods
    conn = AsyncMock()

    # Mock execute - returns command tag
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    # Mock fetch - returns list of records
    conn.fetch = AsyncMock(return_value=[])

    # Mock fetchrow - returns single record or None
    def mock_fetchrow_side_effect(*args, **kwargs):
        # Return realistic data based on query
        query = args[0] if args else ""
        if "SELECT id FROM submissions" in query or "INSERT INTO submissions" in query:
            return {"id": "123e4567-e89b-12d3-a456-426614174000"}
        elif "SELECT * FROM submissions WHERE submission_id" in query:
            return {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "submission_id": "SUB-001",
                "student_id": "ST001",
                "assign_id": "A001",
                "img_url": "https://example.com/image.jpg",
                "is_plagiarized": False,
                "plag_source": None,
                "plag_confidence": None,
            }
        return None

    conn.fetchrow = AsyncMock(side_effect=mock_fetchrow_side_effect)

    # Mock fetchval - returns single value
    conn.fetchval = AsyncMock(return_value="123e4567-e89b-12d3-a456-426614174000")

    # Mock transaction context manager
    transaction = AsyncMock()
    transaction.commit = AsyncMock()
    transaction.rollback = AsyncMock()
    conn.transaction.return_value.__aenter__ = AsyncMock(return_value=transaction)
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    # Setup pool.acquire context manager
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    return pool


@pytest.fixture
async def mock_create_pool(mock_asyncpg_pool):
    """Create a mock for asyncpg.create_pool that returns the pool."""

    async def _create_pool(*args, **kwargs):
        # Return the pool directly
        return mock_asyncpg_pool

    return _create_pool


@pytest.fixture
def mock_image_response(sample_image):
    """Create a mock HTTP response with image data."""
    # Convert PIL image to bytes
    img_bytes = BytesIO()
    sample_image.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    mock_response = MagicMock()
    mock_response.read = MagicMock(return_value=img_bytes.read())
    mock_response.status = 200
    mock_response.raise_for_status = MagicMock()

    return mock_response


@pytest.fixture
def mock_aiohttp_session(mock_image_response):
    """Create a mock aiohttp session for download tests."""
    mock_session = AsyncMock()

    # Create a mock response that works as async context manager
    mock_get_response = AsyncMock()
    mock_get_response.read = AsyncMock(return_value=mock_image_response.read())
    mock_get_response.raise_for_status = AsyncMock()
    mock_get_response.status = 200
    mock_get_response.__aenter__ = AsyncMock(return_value=mock_get_response)
    mock_get_response.__aexit__ = AsyncMock(return_value=None)

    # Mock session.get() to return the response context manager
    mock_session.get = MagicMock(return_value=mock_get_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    return mock_session


@pytest.fixture
def mock_rabbitmq_connection():
    """Create a mock RabbitMQ connection."""
    mock_conn = AsyncMock()
    mock_channel = AsyncMock()

    mock_channel.declare_queue = AsyncMock()
    mock_channel.declare_exchange = AsyncMock()
    mock_channel.bind = AsyncMock()
    mock_channel.publish = AsyncMock()
    mock_channel.consume = AsyncMock()
    mock_channel.ack = AsyncMock()
    mock_channel.nack = AsyncMock()

    mock_conn.channel = AsyncMock(return_value=mock_channel)
    mock_conn.close = AsyncMock()

    return mock_conn


@pytest.fixture
async def mock_faiss_index():
    """Create a mock FAISS index."""
    import faiss

    # Create a small real FAISS index for testing
    dimension = 512
    index = faiss.IndexFlatL2(dimension)

    # Add some test vectors
    np.random.seed(42)
    test_vectors = np.random.randn(10, dimension).astype("float32")
    index.add(test_vectors)

    return index


@pytest.fixture
def mock_clip_model():
    """Create a mock CLIP model."""
    mock_model = MagicMock()
    mock_preprocess = MagicMock()

    # Mock model returns normalized embeddings (512D)
    def mock_encode_image(image_tensor):
        np.random.seed(42)
        embedding = np.random.randn(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        # Return mock tensor with numpy() method
        mock_tensor = MagicMock()
        mock_tensor.cpu.return_value.numpy.return_value = embedding.reshape(1, -1)
        return mock_tensor

    mock_model.encode_image = MagicMock(side_effect=mock_encode_image)

    return mock_model, mock_preprocess
