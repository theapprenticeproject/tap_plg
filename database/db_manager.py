import logging
import os
from dotenv import load_dotenv
from datetime import datetime
import json
from typing import Optional, Any, List, Iterable

import numbers

import asyncpg

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Handles PostgreSQL connection pooling and CRUD operations for submissions.

    This class manages database connections using asyncpg connection pool
    for efficient resource utilization and automatic connection management.

    Attributes:
        pool: asyncpg connection pool instance

    Example:
        db = DatabaseManager()
        await db.init_pool()
        try:
            # Use database operations
            await db.insert_submission_if_not_exists(data, submission_url)
        finally:
            await db.close()
    """

    def __init__(self):
        """
        Initialize database manager with environment configuration.

        Loads configuration from environment variables:
        - POSTGRES_USER or DB_USER
        - POSTGRES_PASSWORD or DB_PASSWORD
        - POSTGRES_DB or DB_NAME
        - POSTGRES_HOST or DB_HOST
        - POSTGRES_PORT or DB_PORT (default: 5432)
        """
        load_dotenv()
        self.pool = None
        self._closed = False

    async def init_pool(self):
        """
        Initialize asyncpg connection pool with retry logic.

        Creates a connection pool with automatic reconnection and health checks.
        Uses environment variables for configuration with fallbacks.

        Raises:
            asyncpg.PostgresError: If connection fails after retries
            ValueError: If required environment variables are missing
        """
        if self.pool is not None and not self._closed:
            logger.warning("Database pool already initialized")
            return

        db_user = os.getenv("POSTGRES_USER") or os.getenv("DB_USER")
        db_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD")
        db_name = os.getenv("POSTGRES_DB") or os.getenv("DB_NAME")
        db_host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST", "localhost")
        db_port = int(os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT", "5432"))
        # db_port = 5435  # TEMP OVERRIDE FOR TESTING



        if not all([db_user, db_password, db_name]):
            raise ValueError("Missing required database environment variables")

        try:
            self.pool = await asyncpg.create_pool(
                user=str(db_user),
                password=str(db_password),
                database=str(db_name),
                host=db_host,
                port=db_port,
                min_size=5,
                max_size=20,
            )
            self._closed = False
            logger.info(
                f"PostgreSQL async pool initialized (host={db_host}, db={db_name}, pool_size=5-20)"
            )
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise

    def _check_pool(self):
        """Check if pool is initialized and not closed."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized. Call init_pool() first.")
        if self._closed:
            raise RuntimeError(
                "Database pool is closed. Cannot perform operations during shutdown."
            )

    async def _fetch(self, query: str, *params) -> List[dict]:
        self._check_pool()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return rows

    async def _fetchrow(self, query: str, *params) -> Optional[dict]:
        self._check_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return row

    async def _fetchval(self, query: str, *params) -> Any:
        self._check_pool()
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(query, *params)
            return val

    async def _execute(self, query: str, *params) -> str:
        self._check_pool()
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *params)
            return result

    def _convert_query_placeholders(self, query: str) -> str:
        return query

    def _normalize_vector(self, embedding_list: Optional[Any]) -> str:
        """Ensure embedding_list is a plain list of floats and convert to pgvector string format.

        Accepts lists, tuples, numpy arrays (with .tolist()), and converts elements to float.
        Returns a string in pgvector format: '[0.1, 0.2, 0.3]'
        Raises ValueError for unsupported types.
        """
        if embedding_list is None:
            return "[]"

        tolist = getattr(embedding_list, "tolist", None)
        if callable(tolist):
            try:
                res = tolist()
                if not isinstance(res, Iterable):
                    raise ValueError("Embedding.tolist() did not return an iterable")
                embedding = list(res)
            except Exception:
                raise ValueError("Embedding.tolist() failed or returned non-iterable")
        else:
            try:
                embedding = list(embedding_list)
            except Exception:
                raise ValueError(
                    "Embedding must be an iterable of numbers or provide tolist()"
                )

        normalized = []
        for v in embedding:
            if not isinstance(v, numbers.Number):
                raise ValueError("Embedding elements must be numeric")
            normalized.append(float(v))  # type: ignore
        
        # Convert to pgvector string format: '[0.1, 0.2, 0.3]'
        return str(normalized)

    async def insert_submission_if_not_exists(
        self, submission_data: dict, submission_url: Optional[str], status: int
    ):
        """
        Insert a new submission if it doesn't already exist.

        Uses INSERT ... ON CONFLICT for atomic upsert operation to prevent race conditions.

        Args:
            submission_data: Dict containing submission_id, student_id, assign_id, submission_url, submission_type, submission_text
            submission_url: URL of the submitted content
            status: Initial submission status

        Returns:
            UUID - Database record ID of the submission (existing or new)

        Raises:
            asyncpg.PostgresError: If database operation fails
            ValueError: If submission_id is missing
            RuntimeError: If database pool is closed or not initialized
        """
        self._check_pool()

        submission_id = submission_data.get("submission_id")
        if not submission_id:
            raise ValueError("submission_id is required")

        try:
            insert_sql = """
                INSERT INTO submissions (submission_id, student_id, assign_id, submission_url, submission_type, submission_text, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (submission_id) DO NOTHING
                RETURNING id;
                """

            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        insert_sql,
                        submission_id,
                        submission_data.get("student_id"),
                        submission_data.get("assign_id"),
                            submission_data.get("submission_url") or submission_url,
                        submission_data.get("submission_type"),
                        submission_data.get("submission_text"),
                        status,
                    )

                    if row is None:
                        existing = await conn.fetchrow(
                            "SELECT id FROM submissions WHERE submission_id = $1",
                            submission_id,
                        )
                        record_id = existing["id"] if existing else None
                        logger.info(
                            f"Submission {submission_id} already exists with record ID {record_id}"
                        )
                    else:
                        record_id = row["id"]
                        logger.info(
                            f"Inserted new submission {submission_id} with record ID {record_id}"
                        )

                    submission_data["db_record_id"] = str(record_id)
                    return record_id

        except Exception as e:
            logger.error(f"Failed to insert submission {submission_id}: {e}")
            raise

    async def update_result(self, submission_id: str, result: dict, status_val: int):
        """
        Update database with plagiarism results.

        Args:
            submission_id: Unique submission identifier
            result: Dict containing plagiarism detection results

        Raises:
            asyncpg.PostgresError: If update fails
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            logger.debug(f"Updating result for submission {submission_id}")
            await self._execute(
                """
                UPDATE submissions
                SET result = $1,
                    status = $2,
                    updated_at = NOW()
                WHERE submission_id = $3;
                """,
                json.dumps(result),
                status_val,
                submission_id,
            )
            logger.info(f"Updated results for submission {submission_id}")
        except Exception as e:
            logger.error(f"Failed to update result for {submission_id}: {e}")
            raise

    async def update_status(
        self,
        submission_id: str,
        status_value: int,
        retry_count_value: int,
        message_value: str,
    ):
        """
        Update submission status and retry metadata.

        Args:
            submission_id: Unique submission identifier
            status_value: New status code
            retry_count_value: Retry counter value
            message_value: Human-readable status message

        Raises:
            asyncpg.PostgresError: If update fails
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            logger.debug(f"Updating status for {submission_id} to {status_value}")
            result = await self._execute(
                """
                UPDATE submissions
                SET status = $1,
                    retry_count = $2,
                    message = $3,
                    updated_at = NOW()
                WHERE submission_id = $4;
                """,
                status_value,
                retry_count_value,
                message_value,
                submission_id,
            )
            if result == "UPDATE 0":
                logger.warning(f"No submission found with ID {submission_id}")
            else:
                logger.info(f"Updated status for {submission_id} to {status_value}")
        except Exception as e:
            logger.error(f"Failed to update status for {submission_id}: {e}")
            raise

    async def update_submission(
        self,
        db_record_id: str,
        hashes: dict,
        plagiarism_status: dict,
        processing_time: int,
    ):
        """
        Update submission record with comprehensive plagiarism detection results.

        Uses transaction to ensure atomicity of the update operation.

        Args:
            db_record_id: UUID of the submission record
            hashes: Dict with 'phash', 'dhash', 'ahash' keys
            plagiarism_status: Dict from determine_plagiarism_status method containing:
                - is_plagiarized (bool)
                - similarity_score (float)
                - match_type (str)
                - matched_reference_ids (list)
                - matched_reference_image_urls (list)
                - peer_plagiarism_detected (bool)
                - matched_peer_submission_ids (list)
                - matched_peer_student_ids (list)
                - matched_peer_image_urls (list)
                - matched_peer_similarity_scores (list)
                - self_plagiarism_detected (bool)
                - matched_self_submission_ids (list)
                - resubmission_within_window (bool)
                - days_since_last_submission (int or None)
                - plagiarism_source (str)
            processing_time: Processing time in milliseconds

        Returns:
            asyncpg.Record: Updated database record

        Raises:
            asyncpg.PostgresError: If update fails
            ValueError: If no record found with given ID
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            q = """
                        UPDATE submissions
                        SET phash = $1, dhash = $2, ahash = $3,
                            is_plagiarized = $4, similarity_score = $5,
                            match_type = $6, 
                            matched_reference_ids = $7,
                            matched_reference_image_urls = $8,
                            peer_plagiarism_detected = $9,
                            matched_peer_submission_ids = $10,
                            matched_peer_student_ids = $11,
                            matched_peer_image_urls = $12,
                            matched_peer_similarity_scores = $13,
                            self_plagiarism_detected = $14,
                            matched_self_submission_ids = $15,
                            resubmission_within_window = $16,
                            days_since_last_submission = $17,
                            plagiarism_source = $18,
                            processed_at = $19, processing_time_ms = $20,
                            clip_embedding_generated = $21,
                            updated_at = $22,
                            matched_peer_assign_ids = $23,
                            matched_self_image_urls = $24,
                            is_ai_generated = $25,
                            ai_detection_source = $26,
                            ai_confidence = $27
                        WHERE id = $28
                        RETURNING *;
                        """

            updated_record = await self._fetchrow(
                q,
                hashes["phash"],
                hashes["dhash"],
                hashes["ahash"],
                plagiarism_status["is_plagiarized"],
                plagiarism_status["similarity_score"],
                plagiarism_status["match_type"],
                plagiarism_status.get("matched_reference_ids", []),
                plagiarism_status.get("matched_reference_image_urls", []),
                plagiarism_status["peer_plagiarism_detected"],
                plagiarism_status.get("matched_peer_submission_ids", []),
                plagiarism_status.get("matched_peer_student_ids", []),
                plagiarism_status.get("matched_peer_image_urls", []),
                plagiarism_status.get("matched_peer_similarity_scores", []),
                plagiarism_status["self_plagiarism_detected"],
                plagiarism_status.get("matched_self_submission_ids", []),
                plagiarism_status["resubmission_within_window"],
                plagiarism_status["days_since_last_submission"],
                plagiarism_status["plagiarism_source"],
                datetime.utcnow(),
                processing_time,
                True,  # clip_embedding_generated
                datetime.utcnow(),
                plagiarism_status["matched_peer_assign_ids"],
                plagiarism_status["matched_self_image_urls"],  # array (NEW)
                plagiarism_status.get("is_ai_generated", False),
                plagiarism_status.get("ai_detection_source"),
                plagiarism_status.get("ai_confidence", 0.0),
                db_record_id,
            )

            if not updated_record:
                raise ValueError(f"No record found with ID {db_record_id}")

            logger.info(
                f"Updated submission in db manager {db_record_id}: "
                f"{plagiarism_status['match_type']} "
                f"(similarity: {plagiarism_status['similarity_score']:.4f})"
            )

            return updated_record
        except Exception as e:
            logger.error(f"Failed to update submission {db_record_id}: {e}")
            raise

    async def get_retry_count(self, submission_id):
        query = "SELECT retry_count FROM submissions WHERE id = $1"
        row = await self._fetchrow(query, submission_id)
        if row:
            return row.get("retry_count")
        return None

    async def get_pending_to_process(self):
        """
        Return unprocessed submissions (e.g., MQ down before processing).

        Returns:
            List of asyncpg.Record objects with status='RECEIVED'
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            records = await self._fetch(
                "SELECT * FROM submissions WHERE status = 'RECEIVED' ORDER BY created_at;"
            )
            logger.info(f"Found {len(records)} pending submissions")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch pending submissions: {e}")
            raise

    async def get_results_not_pushed(self):
        """
        Return processed but not pushed results (e.g., MQ down after processing).

        Returns:
            List of asyncpg.Record objects with status='PENDING_FEEDBACK_PUSH'
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            records = await self._fetch(
                "SELECT * FROM submissions WHERE status = 'PENDING_FEEDBACK_PUSH' ORDER BY processed_at;"
            )
            logger.info(f"Found {len(records)} results pending push")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch unpushed results: {e}")
            raise

    async def fetch_all_reference_images(self):
        """
        Fetch all reference images from database.

        Returns:
            List of asyncpg.Record objects with reference image data

        Raises:
            asyncpg.PostgresError: If query fails
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            records = await self._fetch(
                """
                    SELECT id, reference_id, phash, dhash, ahash, image_path 
                    FROM reference_images
                    ORDER BY created_at;
                    """
            )
            logger.debug(f"Fetched {len(records)} reference images")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch reference images: {e}")
            raise

    async def fetch_reference_images_by_id(self, reference_id):
        """
        Fetch all reference images from database.

        Returns:
            List of asyncpg.Record objects with reference image data

        Raises:
            asyncpg.PostgresError: If query fails
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            image_path = await self._fetchval(
                """
                    SELECT image_path 
                    FROM reference_images where reference_id = $1;
                    """,
                reference_id,
            )
            logger.debug(f"Fetched {len(image_path)} reference images")
            return image_path
        except Exception as e:
            logger.error(f"Failed to fetch reference images: {e}")
            raise

    async def close(self):
        """
        Close the database connection pool and release all resources.

        This should be called during application shutdown to ensure
        all database connections are properly released.
        """
        if self.pool and not self._closed:
            try:
                await self.pool.close()
                self._closed = True
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}")
                raise
        else:
            logger.debug("Database pool already closed or not initialized")

    async def fetch_peer_submissions(
        self,
        current_student_id: str,
        first_submission_date_for_image: Optional[datetime] = None,
    ):
        """
        Fetch all peer submissions (excluding current student) for plagiarism checking.

        Args:
            current_student_id: Hashed student ID to exclude from results

        Returns:
            List of asyncpg.Record objects with peer submission data
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            if first_submission_date_for_image:
                # FIXED: Only check peers who submitted AFTER the student's first submission
                # This prevents flagging the original submitter as a plagiarist
                records = await self._fetch(
                    """
                        SELECT id, student_id, assign_id, submission_url, phash, dhash, ahash, created_at
                        FROM submissions
                        WHERE student_id != $1
                        AND created_at > $2
                        AND phash IS NOT NULL 
                        AND dhash IS NOT NULL 
                        AND ahash IS NOT NULL
                        ORDER BY created_at ASC;
                    """,
                    current_student_id,
                    first_submission_date_for_image,
                )
            else:
                records = await self._fetch(
                    """
                        SELECT id, student_id, assign_id, submission_url, phash, dhash, ahash, created_at
                        FROM submissions
                        WHERE student_id != $1
                        AND phash IS NOT NULL 
                        AND dhash IS NOT NULL 
                        AND ahash IS NOT NULL
                        ORDER BY created_at DESC;
                    """,
                    current_student_id,
                )
            logger.debug(f"Fetched {len(records)} peer submissions")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch peer submissions: {e}")
            raise

    async def fetch_self_submissions(self, current_student_id: str):
        """
        Fetch student's own previous submissions for self-plagiarism checking.

        Args:
            current_student_id: Hashed student ID

        Returns:
            List of asyncpg.Record objects with student's previous submissions
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            records = await self._fetch(
                """
                    SELECT id, created_at, phash, dhash, ahash, assign_id, submission_url 
                    FROM submissions 
                    WHERE student_id = $1 
                    AND phash IS NOT NULL 
                    AND dhash IS NOT NULL 
                    AND ahash IS NOT NULL
                    ORDER BY created_at DESC;
                    """,
                current_student_id,
            )
            logger.debug(f"Fetched {len(records)} self submissions for student")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch self submissions: {e}")
            raise

    # ========================================================================
    # PGVECTOR METHODS - Vector similarity search operations
    # ========================================================================

    async def pgvector_search_reference_images(self, embedding_list: list, k: int = 5):
        """
        Search for top-K similar reference images using cosine similarity.

        Args:
            embedding_list: Query vector as list (512D)
            k: Number of results to return

        Returns:
            List of asyncpg.Record objects with similarity scores
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            vec = self._normalize_vector(embedding_list)
            results = await self._fetch(
                """
                    SELECT 
                        reference_id,
                        id,
                        image_path,
                        category,
                        description,
                        (clip_embedding <#> $1::vector) * -1 as similarity
                    FROM reference_images
                    WHERE clip_embedding IS NOT NULL
                    ORDER BY clip_embedding <#> $1::vector
                    LIMIT $2;
                    """,
                vec,
                k,
            )
            logger.debug(f"pgvector search returned {len(results)} reference images")
            return results
        except Exception as e:
            logger.error(f"pgvector reference search failed: {e}")
            raise

    async def pgvector_search_peer_submissions(
        self, embedding_list: list, current_student_id: str, k: int = 10
    ):
        """
        Search for similar submissions from OTHER students (peer plagiarism).

        Args:
            embedding_list: Query vector as list (512D)
            current_student_id: Student ID to exclude from results
            k: Number of results to return

        Returns:
            List of asyncpg.Record objects with similarity scores
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            vec = self._normalize_vector(embedding_list)
            results = await self._fetch(
                """
                        SELECT 
                        submission_id,
                        student_id,
                        assign_id,
                        submission_url,
                        created_at,
                        (clip_embedding <#> $1::vector) * -1 as similarity
                    FROM submissions
                    WHERE clip_embedding IS NOT NULL
                    AND student_id != $2
                    ORDER BY clip_embedding <#> $1::vector
                    LIMIT $3;
                    """,
                vec,
                current_student_id,
                k,
            )
            logger.debug(f"pgvector peer search returned {len(results)} submissions")
            return results
        except Exception as e:
            logger.error(f"pgvector peer search failed: {e}")
            raise

    async def pgvector_search_self_submissions(
        self,
        embedding_list: list,
        current_student_id: str,
        current_assign_id: str,
        k: int = 10,
    ):
        """
        Search for similar submissions from SAME student in DIFFERENT assignments (self-plagiarism).

        Args:
            embedding_list: Query vector as list (512D)
            current_student_id: Student ID to match
            current_assign_id: Assignment ID to exclude from results
            k: Number of results to return

        Returns:
            List of asyncpg.Record objects with similarity scores
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            vec = self._normalize_vector(embedding_list)
            results = await self._fetch(
                """
                        SELECT 
                        submission_id,
                        student_id,
                        assign_id,
                        submission_url,
                        created_at,
                        (clip_embedding <#> $1::vector) * -1 as similarity
                    FROM submissions
                    WHERE clip_embedding IS NOT NULL
                    AND student_id = $2
                    AND assign_id != $3
                    ORDER BY clip_embedding <#> $1::vector
                    LIMIT $4;
                    """,
                vec,
                current_student_id,
                current_assign_id,
                k,
            )
            logger.debug(f"pgvector self search returned {len(results)} submissions")
            return results
        except Exception as e:
            logger.error(f"pgvector self search failed: {e}")
            raise

    async def pgvector_add_reference_embedding(
        self, reference_id: str, embedding_list: list
    ) -> bool:
        """
        Add or update embedding for a reference image.

        Args:
            reference_id: Reference image ID
            embedding_list: CLIP embedding as list (512D)

        Returns:
            True if successful
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            vec = self._normalize_vector(embedding_list)

            await self._execute(
                """
                    UPDATE reference_images 
                    SET clip_embedding = $1::vector,
                        clip_embedding_generated = true
                    WHERE reference_id = $2;
                    """,
                vec,
                reference_id,
            )
            logger.debug(f"Added embedding for reference {reference_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add reference embedding: {e}")
            return False

    async def pgvector_add_submission_embedding(
        self, submission_id: str, embedding_list: list
    ) -> bool:
        """
        Add or update embedding for a submission.

        Args:
            submission_id: Submission ID
            embedding_list: CLIP embedding as list (512D)

        Returns:
            True if successful
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            vec = self._normalize_vector(embedding_list)

            await self._execute(
                """
                    UPDATE submissions 
                    SET clip_embedding = $1::vector,
                        clip_embedding_generated = true
                    WHERE submission_id = $2;
                    """,
                vec,
                submission_id,
            )
            logger.debug(f"Added embedding for submission {submission_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add submission embedding: {e}")
            return False

    async def pgvector_get_stats(self):
        """
        Get statistics about stored embeddings.

        Returns:
            Tuple of (reference_count, submission_count)
        """
        if not self.pool:
            raise RuntimeError("Database pool not initialized")

        try:
            async with self.pool.acquire() as conn:
                ref_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM reference_images WHERE clip_embedding IS NOT NULL"
                )
                sub_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM submissions WHERE clip_embedding IS NOT NULL"
                )
            return ref_count, sub_count
        except Exception as e:
            logger.error(f"Failed to get pgvector stats: {e}")
            return 0, 0
