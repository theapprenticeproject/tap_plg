import logging
import numpy as np
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class PgVectorHandler:
    """
    PostgreSQL pgvector handler for finding similar images using vector similarity search.
    Drop-in replacement for FAISS with database-native vector search.
    """

    def __init__(
        self,
        db_manager,
        dimension: int = 512,
    ):
        """
        Args:
            db_manager: DatabaseManager instance with initialized connection pool
            dimension: Full embedding dimension (512 for CLIP ViT-B/32)
        """
        self.db_manager = db_manager
        self.dimension = dimension

        logger.info(f"PgVectorHandler initialized (dimension={dimension})")

    async def search(
        self, query_embedding: np.ndarray, k: int = 5
    ) -> List[Tuple[str, float, dict]]:
        """
        Search for top-K similar vectors using cosine similarity.

        Args:
            query_embedding: Query vector (512D)
            k: Number of results to return

        Returns:
            List of tuples: (reference_id, similarity_score, metadata_dict)
        """
        try:
            if not self.db_manager.pool:
                raise RuntimeError("Database pool not initialized")

            # Convert numpy array to list for pgvector
            embedding_list = query_embedding.tolist()

            results = await self.db_manager.pgvector_search_reference_images(
                embedding_list, k
            )

            # Format results to match FAISS handler interface
            formatted_results = []
            for i, row in enumerate(results):
                similarity = float(row["similarity"])
                metadata = {
                    "reference_id": row["reference_id"],
                    "category": row.get("category", "general"),
                    "description": row.get("description", ""),
                    "image_path": row.get("image_path", ""),
                }
                formatted_results.append((row["reference_id"], similarity, metadata))
                logger.debug(f"  {i + 1}. {row['reference_id']}: {similarity:.4f}")

            logger.info(f"pgvector search returned {len(formatted_results)} results")
            return formatted_results

        except Exception as e:
            logger.error(f"pgvector search failed: {e}")
            return []

    async def add_embedding(
        self, reference_id: str, embedding: np.ndarray, metadata: Optional[dict] = None
    ) -> bool:
        """
        Add or update embedding for a reference image.

        Args:
            reference_id: Reference image ID
            embedding: CLIP embedding (512D)
            metadata: Additional metadata (optional, not used in update)

        Returns:
            True if successful
        """
        try:
            if not self.db_manager.pool:
                raise RuntimeError("Database pool not initialized")

            embedding_list = embedding.tolist()

            # Call db_manager method for SQL execution
            success = await self.db_manager.pgvector_add_reference_embedding(
                reference_id, embedding_list
            )

            if success:
                logger.debug(f"Added embedding for {reference_id}")
            return success

        except Exception as e:
            logger.error(f"Failed to add embedding: {e}")
            return False

    async def search_peer_submissions(
        self, query_embedding: np.ndarray, current_student_id: str, k: int = 10
    ) -> List[Tuple[str, float, dict]]:
        """
        Search for similar submissions from OTHER students (peer plagiarism).

        Args:
            query_embedding: Query vector (512D)
            current_student_id: Student ID to exclude from results
            k: Number of results to return

        Returns:
            List of tuples: (submission_id, similarity_score, metadata_dict)
        """
        try:
            if not self.db_manager.pool:
                raise RuntimeError("Database pool not initialized")

            embedding_list = query_embedding.tolist()

            results = await self.db_manager.pgvector_search_peer_submissions(
                embedding_list, current_student_id, k
            )

            formatted_results = []
            for row in results:
                similarity = float(row["similarity"])
                metadata = {
                    "submission_id": row["submission_id"],
                    "student_id": row["student_id"],
                    "assign_id": row.get("assign_id", ""),
                    "image_url": row.get("image_url", ""),
                    "created_at": row["created_at"],
                }
                formatted_results.append((row["submission_id"], similarity, metadata))

            logger.debug(
                f"pgvector peer search returned {len(formatted_results)} results"
            )
            return formatted_results

        except Exception as e:
            logger.error(f"pgvector peer search failed: {e}")
            return []

    async def search_self_submissions(
        self,
        query_embedding: np.ndarray,
        current_student_id: str,
        current_assign_id: str,
        k: int = 10,
    ) -> List[Tuple[str, float, dict]]:
        """
        Search for similar submissions from SAME student in DIFFERENT assignments (self-plagiarism).

        Args:
            query_embedding: Query vector (512D)
            current_student_id: Student ID to match
            current_assign_id: Assignment ID to exclude from results
            k: Number of results to return

        Returns:
            List of tuples: (submission_id, similarity_score, metadata_dict)
        """
        try:
            if not self.db_manager.pool:
                raise RuntimeError("Database pool not initialized")

            embedding_list = query_embedding.tolist()

            results = await self.db_manager.pgvector_search_self_submissions(
                embedding_list, current_student_id, current_assign_id, k
            )

            formatted_results = []
            for row in results:
                similarity = float(row["similarity"])
                metadata = {
                    "submission_id": row["submission_id"],
                    "student_id": row["student_id"],
                    "assign_id": row.get("assign_id", ""),
                    "image_url": row.get("image_url", ""),
                    "created_at": row["created_at"],
                }
                formatted_results.append((row["submission_id"], similarity, metadata))

            logger.debug(
                f"pgvector self search returned {len(formatted_results)} results"
            )
            return formatted_results

        except Exception as e:
            logger.error(f"pgvector self search failed: {e}")
            return []

    async def add_submission_embedding(
        self, submission_id: str, embedding: np.ndarray
    ) -> bool:
        """
        Add or update embedding for a submission.

        Args:
            submission_id: Submission ID
            embedding: CLIP embedding (512D)

        Returns:
            True if successful
        """
        try:
            if not self.db_manager.pool:
                raise RuntimeError("Database pool not initialized")

            embedding_list = embedding.tolist()

            # Call db_manager method for SQL execution
            success = await self.db_manager.pgvector_add_submission_embedding(
                submission_id, embedding_list
            )

            if success:
                logger.debug(f"Added embedding for submission {submission_id}")
            return success

        except Exception as e:
            logger.error(f"Failed to add submission embedding: {e}")
            return False

    async def get_stats(self) -> dict:
        """
        Get statistics about stored embeddings.

        Returns:
            dict with index stats matching FAISS handler interface
        """
        try:
            if not self.db_manager.pool:
                return {"total_vectors": 0, "dimension": self.dimension}

            # Call db_manager method for SQL execution
            ref_count, sub_count = await self.db_manager.pgvector_get_stats()

            stats = {
                "total_vectors": ref_count,
                "submission_vectors": sub_count,
                "dimension": self.dimension,
                "metadata_count": ref_count,
                "index_type": "pgvector (HNSW)",
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"total_vectors": 0, "dimension": self.dimension}
