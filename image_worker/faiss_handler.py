import faiss
import numpy as np
import json
import logging
from typing import List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class FAISSHandler:
    """
    FAISS vector search handler for finding similar images
    Uses IndexFlatIP (inner product) for cosine similarity search
    """

    def __init__(
        self,
        dimension: int = 512,
        index_path: Optional[str] = None,
        metadata_path: Optional[str] = None,
    ):
        """
        Args:
            dimension: Embedding dimension (512 for CLIP ViT-B/32)
            index_path: Path to load existing FAISS index
            metadata_path: Path to load metadata JSON
        """
        self.dimension = dimension
        self.index = None
        self.metadata = []

        if index_path and Path(index_path).exists():
            self.load_index(index_path, metadata_path)
        else:
            self.create_index()

    def create_index(self):
        """Create a new FAISS index (IndexFlatIP for cosine similarity)"""
        try:
            # IndexFlatIP - Inner Product (since vectors are normalized, IP = cosine similarity)
            self.index = faiss.IndexFlatIP(self.dimension)
            logger.info(f"Created new FAISS index (dimension={self.dimension})")

        except Exception as e:
            logger.error(f"Failed to create FAISS index: {e}")
            raise

    def add_vectors(self, embeddings: np.ndarray, metadata: List[dict]):
        """
        Add vectors to the index

        Args:
            embeddings: numpy array of shape (N, 512)
            metadata: List of N dicts with reference info
        """
        try:
            if embeddings.shape[0] != len(metadata):
                raise ValueError("Number of embeddings must match metadata length")

            self.index.add(embeddings.astype("float32"))
            self.metadata.extend(metadata)

            logger.info(
                f"Added {len(embeddings)} vectors to FAISS index (total: {self.index.ntotal})"
            )

        except Exception as e:
            logger.error(f"Failed to add vectors to index: {e}")
            raise

    def search(
        self, query_embedding: np.ndarray, k: int = 5
    ) -> List[Tuple[str, float, dict]]:
        """
        Search for top-K similar vectors

        Args:
            query_embedding: Query vector (512D)
            k: Number of results to return

        Returns:
            List of tuples: (reference_id, similarity_score, metadata_dict)
        """
        try:
            if self.index is None or self.index.ntotal == 0:
                logger.warning("FAISS index is empty, cannot search")
                return []

            if query_embedding.ndim == 1:
                query_embedding = query_embedding.reshape(1, -1)

            similarities, indices = self.index.search(
                query_embedding.astype("float32"), k
            )

            results = []
            for i, (sim, idx) in enumerate(zip(similarities[0], indices[0])):
                if idx < len(self.metadata):  # Valid index
                    meta = self.metadata[idx]
                    results.append((meta["reference_id"], float(sim), meta))
                    logger.debug(f"  {i + 1}. {meta['reference_id']}: {sim:.4f}")

            logger.info(f"FAISS search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"FAISS search failed: {e}")
            return []

    def save_index(self, index_path: str, metadata_path: str):
        """
        Save FAISS index and metadata to disk

        Args:
            index_path: Path to save .bin index file
            metadata_path: Path to save .json metadata file
        """
        try:
            Path(index_path).parent.mkdir(parents=True, exist_ok=True)
            Path(metadata_path).parent.mkdir(parents=True, exist_ok=True)

            # Save index
            faiss.write_index(self.index, index_path)

            # Save metadata
            with open(metadata_path, "w") as f:
                json.dump(self.metadata, f, indent=2)

            logger.info(f"Saved FAISS index to {index_path}")
            logger.info(f"Saved metadata to {metadata_path}")

        except Exception as e:
            logger.error(f"Failed to save FAISS index: {e}")
            raise

    def load_index(self, index_path: str, metadata_path: Optional[str] = None):
        """
        Load FAISS index and metadata from disk

        Args:
            index_path: Path to .bin index file
            metadata_path: Path to .json metadata file
        """
        try:
            # Load index
            self.index = faiss.read_index(index_path)
            logger.info(
                f"Loaded FAISS index from {index_path} ({self.index.ntotal} vectors)"
            )

            if metadata_path and Path(metadata_path).exists():
                with open(metadata_path, "r") as f:
                    self.metadata = json.load(f)
                logger.info(f"Loaded metadata ({len(self.metadata)} entries)")

        except Exception as e:
            logger.error(f"Failed to load FAISS index: {e}")
            raise

    def get_stats(self) -> dict:
        """
        Get statistics about the FAISS index

        Returns:
            dict with index stats
        """
        return {
            "total_vectors": self.index.ntotal if self.index else 0,
            "dimension": self.dimension,
            "metadata_count": len(self.metadata),
            "is_trained": self.index.is_trained if self.index else False,
        }
