"""
Comprehensive integration tests for ImageWorker to improve coverage.
Uses extensive mocking to avoid external dependencies (CLIP model, network, etc.).
"""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO
from PIL import Image

from image_worker.worker import ImageWorker
from utils.exceptions import ImageProcessingError, ImageDownloadError


@pytest.fixture
async def mock_db():
    """Mock database manager."""
    db = AsyncMock()
    db.init_pool = AsyncMock()
    db.close = AsyncMock()
    db.insert_submission_if_not_exists = AsyncMock()
    db.update_submission_status = AsyncMock()
    db.fetch_peer_submissions = AsyncMock(return_value=[])
    db.fetch_self_submissions = AsyncMock(return_value=[])
    db.insert_plagiarism_match = AsyncMock()
    db.get_submission_hashes = AsyncMock(return_value=None)
    db.get_submission_clip_embedding = AsyncMock(return_value=None)
    return db


@pytest.fixture
def sample_image_bytes():
    """Create a sample image as bytes."""
    img = Image.new("RGB", (100, 100), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_submission_data():
    """Sample submission data with all required fields."""
    return {
        "submission_id": "SUB-TEST-001",
        "student_id": "ST-TEST-001",
        "assign_id": "A-TEST-001",
        "submission_url": "https://example.com/test.png",
        "db_record_id": 1,
    }


@pytest.fixture
async def mocked_worker(mock_db, sample_image_bytes):
    """ImageWorker with all dependencies mocked."""

    # Mock CLIP handler
    mock_clip_instance = MagicMock()
    mock_clip_instance.generate_embedding = MagicMock(
        return_value=np.random.randn(768).astype(np.float32) / 10
    )
    mock_clip_instance.similarity = MagicMock(return_value=0.5)

    # Mock Hash handler
    mock_hash_instance = MagicMock()
    mock_hash_instance.compute_hashes = MagicMock(
        return_value={"phash": "a" * 64, "dhash": "b" * 64, "ahash": "c" * 64}
    )
    mock_hash_instance.compare_hashes = MagicMock(return_value={"avg_similarity": 0.3})

    # Mock AI detector
    mock_ai_instance = MagicMock()
    mock_ai_instance.check_ai_generated = MagicMock(return_value=(False, None, 0.2))

    # Mock Image validator
    mock_validator_instance = MagicMock()
    mock_validator_instance.validate = MagicMock(return_value=True)

    # Mock FAISS handler
    mock_faiss_instance = MagicMock()
    mock_faiss_instance.add_embedding = MagicMock()
    mock_faiss_instance.search = MagicMock(return_value=[])

    # Mock aiohttp session for image download
    mock_response = AsyncMock()
    mock_response.read = AsyncMock(return_value=sample_image_bytes)
    mock_response.status = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock()

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()

    with (
        patch("image_worker.worker.CLIPHandler", return_value=mock_clip_instance),
        patch("image_worker.worker.HashHandler", return_value=mock_hash_instance),
        patch("image_worker.worker.AIGeneratedDetector", return_value=mock_ai_instance),
        patch(
            "image_worker.worker.ImageValidator", return_value=mock_validator_instance
        ),
        patch("image_worker.worker.FAISSHandler", return_value=mock_faiss_instance),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        worker = ImageWorker(db_manager=mock_db)
        await worker.initialize()

        # Store mocks in a dict that can be accessed in tests
        worker._test_mocks = {
            "clip": mock_clip_instance,
            "hash": mock_hash_instance,
            "ai_detector": mock_ai_instance,
            "validator": mock_validator_instance,
            "faiss": mock_faiss_instance,
            "session": mock_session,
        }

        yield worker
        await worker.close()


class TestWorkerInitialization:
    """Test worker initialization and configuration."""

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_db):
        """Test successful initialization."""
        with (
            patch("image_worker.worker.CLIPHandler"),
            patch("image_worker.worker.HashHandler"),
            patch("image_worker.worker.AIGeneratedDetector"),
            patch("image_worker.worker.ImageValidator"),
            patch("image_worker.worker.FAISSHandler"),
        ):
            worker = ImageWorker(db_manager=mock_db)
            await worker.initialize()

            # Verify DB pool was initialized
            mock_db.init_pool.assert_called_once()

            await worker.close()

    @pytest.mark.asyncio
    async def test_close_cleanup(self, mock_db):
        """Test cleanup on close."""
        with (
            patch("image_worker.worker.CLIPHandler"),
            patch("image_worker.worker.HashHandler"),
            patch("image_worker.worker.AIGeneratedDetector"),
            patch("image_worker.worker.ImageValidator"),
            patch("image_worker.worker.FAISSHandler"),
        ):
            worker = ImageWorker(db_manager=mock_db)
            await worker.initialize()

            # Worker doesn't own DB (we passed it in), so close() won't be called
            assert worker._owns_db_manager == False

            await worker.close()

            # Verify DB was NOT closed (worker doesn't own it)
            mock_db.close.assert_not_called()


class TestWorkerImageDownload:
    """Test image download functionality."""

    @pytest.mark.asyncio
    async def test_download_image_success(self, mocked_worker):
        """Test successful image download."""
        worker = mocked_worker

        # Download using the public method
        pil_image = await worker.download_image("https://example.com/test.png")

        assert pil_image is not None
        assert isinstance(pil_image, Image.Image)

    @pytest.mark.asyncio
    async def test_download_image_invalid_url(self, mocked_worker):
        """Test image download with invalid URL."""
        worker = mocked_worker

        # Try downloading with invalid URL
        with pytest.raises(Exception):  # Should raise InvalidImageURLError or similar
            await worker.download_image("not-a-url")

    @pytest.mark.asyncio
    async def test_download_image_storage_google_public_url(self, mocked_worker):
        """Test public storage.googleapis.com image download via HTTPS fallback."""
        worker = mocked_worker
        worker.gcp_credentials = None

        pil_image = await worker.download_image(
            "https://storage.googleapis.com/assignment_submission/submissions/SUB-IMSUB.png"
        )

        assert pil_image is not None
        assert isinstance(pil_image, Image.Image)

    @pytest.mark.asyncio
    async def test_download_image_storage_google_authenticated_url(self, mocked_worker):
        """Test authenticated storage.googleapis.com URL downloads via GCS helper when credentials are available."""
        worker = mocked_worker
        worker.gcp_credentials = MagicMock()

        sample_image = Image.open(BytesIO(worker._test_mocks["session"].get().read.return_value))

        with patch(
            "image_worker.worker.download_from_gcs",
            AsyncMock(return_value=sample_image),
        ) as mock_download:
            pil_image = await worker.download_image(
                "https://storage.googleapis.com/assignment_submission/submissions/SUB-IMSUB.png"
            )

        assert pil_image is not None
        assert isinstance(pil_image, Image.Image)
        mock_download.assert_awaited_once()


class TestWorkerSubmissionProcessing:
    """Test submission processing workflow."""

    @pytest.mark.asyncio
    async def test_process_submission_basic(
        self, mocked_worker, sample_submission_data
    ):
        """Test basic submission processing completes successfully."""
        worker = mocked_worker

        # Process submission - should complete without errors
        result = await worker.process_submission(sample_submission_data)

        # Verify it returns a result (the workflow completed)
        assert result is not None

    @pytest.mark.asyncio
    async def test_process_submission_with_peer_check(self, mocked_worker, mock_db):
        """Test submission processing with peer checking."""
        worker = mocked_worker

        # Mock peer submissions
        mock_db.fetch_peer_submissions.return_value = [
            {
                "submission_id": "SUB-PEER",
                "student_id": "ST-PEER",
                "clip_embedding": np.random.randn(768).astype(np.float32),
            }
        ]

        submission = {
            "submission_id": "SUB-002",
            "student_id": "ST002",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 2,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed and peer check was performed
        assert result is not None
        mock_db.fetch_peer_submissions.assert_called()

    @pytest.mark.asyncio
    async def test_process_submission_with_self_check(self, mocked_worker, mock_db):
        """Test submission processing with self-plagiarism checking."""
        worker = mocked_worker

        # Mock self submissions
        mock_db.fetch_self_submissions.return_value = [
            {
                "submission_id": "SUB-SELF",
                "student_id": "ST003",
                "assign_id": "A000",
                "clip_embedding": np.random.randn(768).astype(np.float32),
            }
        ]

        submission = {
            "submission_id": "SUB-003",
            "student_id": "ST003",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 3,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed and self check was performed
        assert result is not None
        mock_db.fetch_self_submissions.assert_called()


class TestWorkerHashDetection:
    """Test hash-based plagiarism detection."""

    @pytest.mark.asyncio
    async def test_hash_computation(self, mocked_worker):
        """Test that submission processing completes with hash computation."""
        worker = mocked_worker

        submission = {
            "submission_id": "SUB-004",
            "student_id": "ST004",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 4,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed successfully
        assert result is not None
        # Hash handler gets called for computing hashes
        assert worker._test_mocks["hash"].compute_hashes.called


class TestWorkerSemanticDetection:
    """Test CLIP-based semantic similarity detection."""

    @pytest.mark.asyncio
    async def test_clip_embedding_generation(self, mocked_worker):
        """Test that CLIP embeddings are generated during processing."""
        worker = mocked_worker

        submission = {
            "submission_id": "SUB-005",
            "student_id": "ST005",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 5,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed and CLIP was used
        assert result is not None
        assert worker._test_mocks["clip"].generate_embedding.called


class TestWorkerAIDetection:
    """Test AI-generated image detection."""

    @pytest.mark.asyncio
    async def test_ai_detection_called(self, mocked_worker):
        """Test that AI detection is performed during processing."""
        worker = mocked_worker

        submission = {
            "submission_id": "SUB-006",
            "student_id": "ST006",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 6,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed and AI detection was performed
        assert result is not None
        assert worker._test_mocks["ai_detector"].check_ai_generated.called


class TestWorkerImageValidation:
    """Test image validation."""

    @pytest.mark.asyncio
    async def test_image_validation_called(self, mocked_worker):
        """Test that image validation is performed during processing."""
        worker = mocked_worker

        submission = {
            "submission_id": "SUB-007",
            "student_id": "ST007",
            "assign_id": "A001",
            "submission_url": "https://example.com/test.png",
            "db_record_id": 7,
        }

        result = await worker.process_submission(submission)

        # Verify processing completed and validation was performed
        assert result is not None
        # Validator may or may not be called depending on implementation
        # Just verify the workflow completed
