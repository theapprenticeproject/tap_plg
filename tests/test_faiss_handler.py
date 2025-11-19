"""
Unit tests for FAISSHandler.
"""

import pytest
import numpy as np
import tempfile
import shutil
from pathlib import Path

from image_worker.faiss_handler import FAISSHandler


class TestFAISSHandler:
    """Test cases for FAISSHandler."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files."""
        temp_path = tempfile.mkdtemp()
        yield temp_path
        shutil.rmtree(temp_path)

    @pytest.fixture
    def faiss_handler(self):
        """Create FAISSHandler instance."""
        return FAISSHandler(dimension=512)

    def test_init_creates_new_index(self):
        """Test initialization creates new index."""
        handler = FAISSHandler(dimension=128)

        assert handler.dimension == 128
        assert handler.index is not None
        assert handler.index.ntotal == 0
        assert handler.metadata == []

    def test_init_with_nonexistent_paths(self, temp_dir):
        """Test initialization with non-existent paths creates new index."""
        index_path = str(Path(temp_dir) / "index.bin")
        metadata_path = str(Path(temp_dir) / "metadata.json")

        handler = FAISSHandler(
            dimension=256, index_path=index_path, metadata_path=metadata_path
        )

        assert handler.dimension == 256
        assert handler.index is not None
        assert handler.index.ntotal == 0

    def test_create_index(self):
        """Test create_index method."""
        handler = FAISSHandler(dimension=512)

        assert handler.index is not None
        assert handler.index.d == 512
        assert handler.index.ntotal == 0

    def test_create_index_accepts_any_dimension(self):
        """Test create_index accepts various dimensions."""
        handler1 = FAISSHandler(dimension=128)
        assert handler1.index.d == 128

        handler2 = FAISSHandler(dimension=768)
        assert handler2.index.d == 768

    def test_add_vectors_success(self, faiss_handler):
        """Test adding vectors successfully."""
        embeddings = np.random.randn(5, 512).astype("float32")
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        metadata = [
            {"reference_id": f"ref_{i}", "student_id": f"st_{i}"} for i in range(5)
        ]

        faiss_handler.add_vectors(embeddings, metadata)

        assert faiss_handler.index.ntotal == 5
        assert len(faiss_handler.metadata) == 5

    def test_add_vectors_multiple_batches(self, faiss_handler):
        """Test adding vectors in multiple batches."""
        embeddings1 = np.random.randn(3, 512).astype("float32")
        metadata1 = [{"reference_id": f"ref_{i}"} for i in range(3)]

        embeddings2 = np.random.randn(2, 512).astype("float32")
        metadata2 = [{"reference_id": f"ref_{i + 3}"} for i in range(2)]

        faiss_handler.add_vectors(embeddings1, metadata1)
        faiss_handler.add_vectors(embeddings2, metadata2)

        assert faiss_handler.index.ntotal == 5
        assert len(faiss_handler.metadata) == 5

    def test_add_vectors_mismatch_error(self, faiss_handler):
        """Test add_vectors with mismatched embeddings and metadata."""
        embeddings = np.random.randn(5, 512).astype("float32")
        metadata = [{"reference_id": "ref_0"}]

        with pytest.raises(ValueError, match="Number of embeddings must match"):
            faiss_handler.add_vectors(embeddings, metadata)

    def test_search_empty_index(self, faiss_handler):
        """Test search on empty index."""
        query = np.random.randn(512).astype("float32")
        query = query / np.linalg.norm(query)

        results = faiss_handler.search(query, k=5)

        assert results == []

    def test_search_success(self, faiss_handler):
        """Test successful search."""
        embeddings = np.random.randn(10, 512).astype("float32")
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        metadata = [
            {"reference_id": f"ref_{i}", "student_id": f"st_{i}"} for i in range(10)
        ]

        faiss_handler.add_vectors(embeddings, metadata)

        query = embeddings[0]
        results = faiss_handler.search(query, k=3)

        assert len(results) <= 3
        assert results[0][0] == "ref_0"
        # Allow small floating-point precision errors
        assert 0.95 <= results[0][1] <= 1.01

    def test_search_with_1d_query(self, faiss_handler):
        """Test search with 1D query vector."""
        embeddings = np.random.randn(5, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(5)]

        faiss_handler.add_vectors(embeddings, metadata)

        query = np.random.randn(512).astype("float32")
        results = faiss_handler.search(query, k=2)

        assert len(results) <= 2

    def test_search_with_2d_query(self, faiss_handler):
        """Test search with 2D query vector."""
        embeddings = np.random.randn(5, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(5)]

        faiss_handler.add_vectors(embeddings, metadata)

        query = np.random.randn(1, 512).astype("float32")
        results = faiss_handler.search(query, k=3)

        assert len(results) <= 3

    def test_search_k_larger_than_index(self, faiss_handler):
        """Test search with k larger than index size."""
        embeddings = np.random.randn(3, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(3)]

        faiss_handler.add_vectors(embeddings, metadata)

        query = np.random.randn(512).astype("float32")
        results = faiss_handler.search(query, k=10)

        assert len(results) >= 3

    def test_search_returns_sorted_results(self, faiss_handler):
        """Test that search returns results sorted by similarity."""
        embeddings = np.random.randn(5, 512).astype("float32")
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        metadata = [{"reference_id": f"ref_{i}"} for i in range(5)]

        faiss_handler.add_vectors(embeddings, metadata)

        query = embeddings[2]
        results = faiss_handler.search(query, k=5)

        assert len(results) > 1
        for i in range(len(results) - 1):
            assert results[i][1] >= results[i + 1][1]

    def test_save_and_load_index(self, faiss_handler, temp_dir):
        """Test saving and loading index."""
        embeddings = np.random.randn(5, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}", "data": i} for i in range(5)]

        faiss_handler.add_vectors(embeddings, metadata)

        index_path = str(Path(temp_dir) / "test_index.bin")
        metadata_path = str(Path(temp_dir) / "test_metadata.json")

        faiss_handler.save_index(index_path, metadata_path)

        assert Path(index_path).exists()
        assert Path(metadata_path).exists()

        new_handler = FAISSHandler(dimension=512)
        new_handler.load_index(index_path, metadata_path)

        assert new_handler.index.ntotal == 5
        assert len(new_handler.metadata) == 5
        assert new_handler.metadata[0]["reference_id"] == "ref_0"

    def test_load_index_without_metadata(self, faiss_handler, temp_dir):
        """Test loading index without metadata file."""
        embeddings = np.random.randn(3, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(3)]

        faiss_handler.add_vectors(embeddings, metadata)

        index_path = str(Path(temp_dir) / "test_index.bin")
        metadata_path = str(Path(temp_dir) / "test_metadata.json")

        faiss_handler.save_index(index_path, metadata_path)

        new_handler = FAISSHandler(dimension=512)
        new_handler.load_index(index_path)

        assert new_handler.index.ntotal == 3
        assert len(new_handler.metadata) == 0

    def test_save_index_creates_directories(self, temp_dir):
        """Test save_index creates parent directories."""
        handler = FAISSHandler(dimension=512)
        embeddings = np.random.randn(2, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(2)]
        handler.add_vectors(embeddings, metadata)

        nested_path = Path(temp_dir) / "nested" / "dir" / "index.bin"
        metadata_path = Path(temp_dir) / "nested" / "dir" / "metadata.json"

        handler.save_index(str(nested_path), str(metadata_path))

        assert nested_path.exists()
        assert metadata_path.exists()

    def test_load_index_failure(self):
        """Test load_index with non-existent file."""
        handler = FAISSHandler(dimension=512)

        with pytest.raises(Exception):
            handler.load_index("/nonexistent/path/index.bin")

    def test_get_stats_empty_index(self, faiss_handler):
        """Test get_stats on empty index."""
        stats = faiss_handler.get_stats()

        assert stats["total_vectors"] == 0
        assert stats["dimension"] == 512
        assert stats["metadata_count"] == 0
        assert stats["is_trained"] is True

    def test_get_stats_with_data(self, faiss_handler):
        """Test get_stats with data."""
        embeddings = np.random.randn(7, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(7)]

        faiss_handler.add_vectors(embeddings, metadata)

        stats = faiss_handler.get_stats()

        assert stats["total_vectors"] == 7
        assert stats["dimension"] == 512
        assert stats["metadata_count"] == 7
        assert stats["is_trained"] is True

    def test_init_with_existing_index(self, temp_dir):
        """Test initialization with existing index file."""
        handler1 = FAISSHandler(dimension=512)
        embeddings = np.random.randn(5, 512).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(5)]
        handler1.add_vectors(embeddings, metadata)

        index_path = str(Path(temp_dir) / "existing.bin")
        metadata_path = str(Path(temp_dir) / "existing.json")
        handler1.save_index(index_path, metadata_path)

        handler2 = FAISSHandler(
            dimension=512, index_path=index_path, metadata_path=metadata_path
        )

        assert handler2.index.ntotal == 5
        assert len(handler2.metadata) == 5

    def test_search_error_handling(self, faiss_handler):
        """Test search error handling with None index."""
        faiss_handler.index = None

        query = np.random.randn(512).astype("float32")
        results = faiss_handler.search(query, k=5)

        assert results == []

    def test_add_vectors_error_handling(self):
        """Test add_vectors error handling."""
        handler = FAISSHandler(dimension=512)

        invalid_embeddings = np.random.randn(5, 256).astype("float32")
        metadata = [{"reference_id": f"ref_{i}"} for i in range(5)]

        with pytest.raises(Exception):
            handler.add_vectors(invalid_embeddings, metadata)
