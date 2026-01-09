import json
from datetime import datetime
import logging
import aiohttp
import ssl
from PIL import Image
from io import BytesIO
import time
import numpy as np
import asyncio
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urlparse
from dotenv import load_dotenv
from image_worker.assigment_ref_images import get_reference_images

from config.config import config
from database.db_manager import DatabaseManager
from image_worker.hash_handler import HashHandler
from image_worker.clip_handler import CLIPHandler
from image_worker.faiss_handler import FAISSHandler
from image_worker.pgvector_handler import PgVectorHandler
from image_worker.ai_generated_detector import AIGeneratedDetector
from image_worker.image_validator import ImageValidator
from utils.exceptions import (
    WorkerNotInitializedError,
    ValidationError,
    ImageDownloadError,
    NetworkTimeoutError,
    InvalidImageURLError,
    InvalidImageFormatError,
)

load_dotenv()

logging.basicConfig(
    level=getattr(logging, config.logging.log_level),
    format=config.logging.log_format,
)
logger = logging.getLogger(__name__)


class ImageWorker:
    def __init__(self, db_manager=None):
        self.db_manager = db_manager if db_manager else DatabaseManager()
        self._db_initialized = False
        self._owns_db_manager = db_manager is None

        self.exact_dup_threshold = config.detection.exact_dup_threshold
        self.near_dup_threshold = config.detection.near_dup_threshold
        self.semantic_threshold = config.detection.semantic_threshold
        self.hash_threshold = config.detection.hash_threshold
        self.peer_hash_threshold = config.detection.peer_hash_threshold
        self.self_hash_threshold = config.detection.self_hash_threshold
        self.enable_peer_check = config.detection.enable_peer_check
        self.enable_self_check = config.detection.enable_self_check

        self.MAX_IMAGE_SIZE = (
            config.image_processing.max_image_width,
            config.image_processing.max_image_height,
        )
        self.DOWNLOAD_TIMEOUT = config.image_processing.download_timeout
        self.DOWNLOAD_RETRIES = config.image_processing.download_retries

        self.use_pgvector = config.vector_search.use_pgvector
        self.faiss_top_k = config.vector_search.faiss_top_k
        self.faiss_index_path = config.vector_search.faiss_index_path
        self.faiss_metadata_path = config.vector_search.faiss_metadata_path

        window_minutes = config.detection.resubmission_window_minutes
        if window_minutes:
            self.resubmission_window_days = float(window_minutes) / (24 * 60)
        else:
            self.resubmission_window_days = config.detection.resubmission_window_days

        self.hash_handler = HashHandler(hash_size=config.image_processing.hash_size)
        self.clip_handler = CLIPHandler(
            model_name=config.vector_search.clip_model,
            device=config.vector_search.clip_device,
            pretrained=config.vector_search.clip_pretrained,
            local_model_path=config.vector_search.clip_local_model_path,
        )
        self.ai_detector = AIGeneratedDetector()
        self.image_validator = ImageValidator(
            min_variance_threshold=config.image_processing.min_variance_threshold,
            min_unique_colors=config.image_processing.min_unique_colors,
            max_solid_color_ratio=config.image_processing.max_solid_color_ratio,
        )

        self.vector_handler = None

        if not self.use_pgvector:
            self.vector_handler = FAISSHandler(
                dimension=768,
                index_path=self.faiss_index_path,
                metadata_path=self.faiss_metadata_path,
            )

    async def initialize(self):
        """
        Initialize async resources (database connection pool and pgvector if enabled).

        Must be called before processing submissions.
        """
        if not self._db_initialized:
            await self.db_manager.init_pool()

            if self.use_pgvector:
                self.vector_handler = PgVectorHandler(
                    self.db_manager,
                    dimension=768,
                )
                await self.vector_handler.get_stats()

            self._db_initialized = True

    async def close(self):
        if self._db_initialized:
            if self._owns_db_manager:
                await self.db_manager.close()
            self._db_initialized = False

    async def download_image(self, image_url: str) -> Image.Image:
        """
        Download image from URL with timeout and validation.

        Args:
            image_url: HTTP/HTTPS URL of the image

        Returns:
            PIL Image object

        Raises:
            InvalidImageURLError: If URL is malformed or invalid
            NetworkTimeoutError: If download times out
            InvalidImageFormatError: If file is not a valid image
            ImageDownloadError: For other download failures
        """
        max_retries = self.DOWNLOAD_RETRIES
        for attempt in range(max_retries):
            try:
                parsed = urlparse(image_url)
                if not parsed.scheme or not parsed.netloc:
                    raise InvalidImageURLError(
                        f"Invalid URL: {image_url}",
                        details={"url": image_url, "parsed": str(parsed)},
                    )

                logger.debug(
                    f"Downloading image: url={image_url[:80]}..., attempt={attempt + 1}/{max_retries}"
                )

                # Configure SSL context based on config
                if config.image_processing.disable_ssl_verify:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    logger.debug("SSL verification disabled for image download")
                    connector = aiohttp.TCPConnector(ssl=ssl_context)
                else:
                    connector = aiohttp.TCPConnector()

                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(
                        image_url,
                        timeout=aiohttp.ClientTimeout(total=self.DOWNLOAD_TIMEOUT),
                    ) as response:
                        response.raise_for_status()
                        content = await response.read()

                try:
                    image = Image.open(BytesIO(content))
                    return image
                except ValidationError:
                    raise
                except Exception as img_error:
                    raise InvalidImageFormatError(
                        f"Invalid or corrupted image format: {str(img_error)}",
                        details={"url": image_url, "error": str(img_error)},
                    )

            except asyncio.TimeoutError:
                logger.warning(
                    f"Download timeout: attempt={attempt + 1}/{max_retries}, "
                    f"timeout={self.DOWNLOAD_TIMEOUT}s"
                )
                if attempt == max_retries - 1:
                    raise NetworkTimeoutError(
                        f"Download timed out after {max_retries} attempts",
                        details={
                            "url": image_url,
                            "timeout": self.DOWNLOAD_TIMEOUT,
                            "retries": max_retries,
                        },
                    )
                await asyncio.sleep(1)

            except aiohttp.ClientError as client_error:
                logger.warning(
                    f"Download failed: attempt={attempt + 1}/{max_retries}, "
                    f"error={str(client_error)}"
                )
                if attempt == max_retries - 1:
                    raise ImageDownloadError(
                        f"Failed to download image: {str(client_error)}",
                        details={
                            "url": image_url,
                            "error": str(client_error),
                            "retries": max_retries,
                        },
                    )
                await asyncio.sleep(1)

        raise ImageDownloadError(
            f"Failed to download image after {max_retries} attempts",
            details={"url": image_url, "retries": max_retries},
        )

    def _validate_input(self, data: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        """
        Validate input data and extract required fields.

        Args:
            data: Input submission data dictionary

        Returns:
            Tuple of (submission_id, student_id, assign_id, image_url, db_record_id)

        Raises:
            ValidationError: If required fields are missing or invalid
        """
        required_fields = ["submission_id", "student_id", "img_url", "db_record_id"]
        for field in required_fields:
            if field not in data or not data[field]:
                raise ValidationError(
                    f"Missing required field: {field}",
                    details={"field": field, "data": data},
                )

        submission_id = data["submission_id"]
        student_id = data["student_id"]
        assign_id = data.get("assign_id", "N/A")
        image_url = data["img_url"]
        db_record_id = data["db_record_id"]

        return submission_id, student_id, assign_id, image_url, db_record_id

    def _sync_compare_hashes(self, hashes1, hashes2, threshold):
        return self.hash_handler.compare_all_hashes(hashes1, hashes2, threshold)

    async def _async_compare_ref(self, hashes, ref):
        loop = asyncio.get_event_loop()
        comparison = await loop.run_in_executor(
            None,
            self._sync_compare_hashes,
            hashes,
            {
                "phash": ref["phash"],
                "dhash": ref["dhash"],
                "ahash": ref["ahash"],
            },
            self.hash_threshold,
        )
        return comparison, ref

    async def _async_compare_peer(self, hashes, peer):
        loop = asyncio.get_event_loop()
        comparison = await loop.run_in_executor(
            None,
            self._sync_compare_hashes,
            hashes,
            {
                "phash": peer["phash"],
                "dhash": peer["dhash"],
                "ahash": peer["ahash"],
            },
            self.peer_hash_threshold,
        )
        return comparison, peer

    async def _async_compare_self(self, hashes, prev):
        loop = asyncio.get_event_loop()
        comparison = await loop.run_in_executor(
            None,
            self._sync_compare_hashes,
            hashes,
            {
                "phash": prev["phash"],
                "dhash": prev["dhash"],
                "ahash": prev["ahash"],
            },
            self.self_hash_threshold,
        )
        return comparison, prev

    async def check_assignment_reference_hash_match(
        self, hashes: dict, assignment_id: str
    ) -> Tuple[bool, Optional[str], Optional[float], Optional[str]]:
        """
        Check if submission matches any reference image via perceptual hash comparison.

        Uses three hash types (pHash, dHash, aHash) for robust duplicate detection.

        Args:
            hashes: Dict containing 'phash', 'dhash', 'ahash' hex strings

        Returns:
            Tuple of (is_match, reference_id, similarity_score, image_url)
            - is_match: True if hash match found
            - reference_id: UUID of matched reference (or None)
            - similarity_score: 0.0-1.0 similarity score (or None)
            - image_url: URL of matched reference image (or None)

        Raises:
            Exception: If database query fails
        """
        try:

            references = await get_reference_images(assignment_id, self.clip_handler, self.hash_handler)
            if not references:
                return False, None, None, None
            
            # for ref_image in references:
            #     if ref_image["content"] is not None:
            #         hashes = self.hash_handler.compute_hashes(ref_image["content"])
            #         ref_image['phash'] = hashes['phash']
            #         ref_image['dhash'] = hashes['dhash']
            #         ref_image['ahash'] = hashes['ahash']

            tasks = [self._async_compare_ref(hashes, ref) for ref in references]
            results = await asyncio.gather(*tasks)


            best_match = None
            best_score = 999
            best_comparison = None
            for comparison, ref in results:
                if comparison["is_match"] and comparison["avg_distance"] < best_score:
                    best_score = comparison["avg_distance"]
                    best_match = ref
                    best_comparison = comparison

            if best_match and best_comparison:
                logger.info("Assignment reference match found")
                similarity = 1 - (best_score / 64.0)
                return (
                    True,
                    str(best_match["name"]),
                    similarity,
                    str(best_match["name"]),
                )
            else:
                logger.info("No assignment reference match found")
                return False, None, None, None

        except Exception as e:
            logger.error(f"Hash check failed: {e}", exc_info=True)
            raise


    async def check_db_reference_hash_match(
        self, hashes: dict
    ) -> Tuple[bool, Optional[str], Optional[float], Optional[str]]:
        """
        Check if submission matches any reference image via perceptual hash comparison.

        Uses three hash types (pHash, dHash, aHash) for robust duplicate detection.

        Args:
            hashes: Dict containing 'phash', 'dhash', 'ahash' hex strings

        Returns:
            Tuple of (is_match, reference_id, similarity_score, image_url)
            - is_match: True if hash match found
            - reference_id: UUID of matched reference (or None)
            - similarity_score: 0.0-1.0 similarity score (or None)
            - image_url: URL of matched reference image (or None)

        Raises:
            Exception: If database query fails
        """
        try:
            references = await self.db_manager.fetch_all_reference_images()

            if not references:
                return False, None, None, None

            tasks = [self._async_compare_ref(hashes, ref) for ref in references]
            results = await asyncio.gather(*tasks)

            best_match = None
            best_score = 999
            best_comparison = None
            for comparison, ref in results:
                if comparison["is_match"] and comparison["avg_distance"] < best_score:
                    best_score = comparison["avg_distance"]
                    best_match = ref
                    best_comparison = comparison

            if best_match and best_comparison:
                similarity = 1 - (best_score / 64.0)
                return (
                    True,
                    str(best_match["reference_id"]),
                    similarity,
                    best_match.get("image_path"),
                )
            else:
                return False, None, None, None

        except Exception as e:
            logger.error(f"Hash check failed: {e}", exc_info=True)
            raise

    async def check_clip_match(
        self, image: Image.Image
    ) -> Tuple[Optional[str], float, Optional[np.ndarray]]:
        """
        Check similarity using CLIP + vector search (FAISS or pgvector)
        Retrieves top-K candidates and picks best match above threshold

        Returns:
            Tuple of (matched_ref_id, similarity_score, embedding):
                - matched_ref_id: Reference ID if match found, None otherwise
                - similarity_score: Float similarity score (0.0-1.0)
                - embedding: CLIP embedding vector or None on error
        """
        try:
            embedding = self.clip_handler.generate_embedding(image)

            if self.vector_handler is None:
                logger.error("Vector handler not initialized")
                return None, 0.0, None

            results = None
            if self.use_pgvector:
                results = await self.vector_handler.search(
                    embedding, k=self.faiss_top_k
                )  # type: ignore
            else:
                results = self.vector_handler.search(embedding, k=self.faiss_top_k)

            if not results:
                return None, 0.0, None
            
            # print("#"*70)
            # for ref_id, sim, meta in results:
            #     print(f"  Ref ID: {ref_id}, Similarity: {sim:.4f}, Meta: {meta}")
            # print("#"*70)

            matches = [
                (ref_id, sim, meta)
                for ref_id, sim, meta in results  # type: ignore
                if sim >= self.semantic_threshold
            ]

            if matches:
                ref_id, similarity, metadata = matches[0]
                return ref_id, float(similarity), embedding
            else:
                return None, 0.0, embedding

        except Exception as e:
            logger.error(f"CLIP search failed: {e}", exc_info=True)
            return None, 0.0, None

    def determine_match_type(self, similarity: float) -> str:
        """Determine plagiarism category based on similarity score"""
        if similarity >= self.exact_dup_threshold:
            return "exact_duplicate"
        elif similarity >= self.near_dup_threshold:
            return "near_duplicate"
        elif similarity >= self.semantic_threshold:
            return "semantic_match"
        else:
            return "original"

    async def update_submission(
        self,
        db_record_id: str,
        hashes: dict,
        plagiarism_status: dict,
        processing_time: int,
        clip_embedding: Optional[np.ndarray] = None,
    ):
        """
        Update submission record in PostgreSQL with comprehensive plagiarism details

        Args:
            db_record_id: UUID of the submission record
            hashes: dict with 'phash', 'dhash', 'ahash'
            plagiarism_status: dict from determine_plagiarism_status method
            processing_time: processing time in milliseconds
            clip_embedding: CLIP embedding vector (optional, for pgvector storage)
        """

        updated_record = await self.db_manager.update_submission(
            db_record_id,
            hashes,
            plagiarism_status,
            processing_time,
        )

        if (
            self.use_pgvector
            and clip_embedding is not None
            and self.vector_handler is not None
        ):
            submission_id = plagiarism_status.get("submission_id")
            if submission_id and hasattr(
                self.vector_handler, "add_submission_embedding"
            ):
                success = await self.vector_handler.add_submission_embedding(  # type: ignore
                    submission_id, clip_embedding
                )
                if success:
                    logger.debug(
                        f"Stored CLIP embedding for submission {submission_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to store CLIP embedding for submission {submission_id}"
                    )

        logger.info(
            f"Updated submission in worker {db_record_id}: {plagiarism_status['match_type']} "
            f"(similarity: {plagiarism_status['similarity_score']:.4f})"
        )
        return updated_record

    async def process_submission(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Main processing callback for image plagiarism detection.

        Args:
            data: Submission data containing submission_id, student_id, image_url, db_record_id

        Returns:
            JSON string with processing results and plagiarism status, or None on error

        Raises:
            RuntimeError: If ImageWorker not initialized
        """
        if self.vector_handler is None:
            raise WorkerNotInitializedError(
                "ImageWorker not initialized. Call initialize() before processing submissions."
            )

        start_time = time.time()
        image = None

        try:
            extracted = self._validate_input(data)
            submission_id, student_id, assign_id, image_url, db_record_id = extracted

            logger.info(f"Processing submission: {submission_id}")

            # Check for stock image URLs before downloading
            is_stock, stock_site = self.image_validator.check_stock_image_url(image_url)
            if is_stock and stock_site:
                logger.warning(
                    f"Stock image rejected: submission={submission_id}, "
                    f"source={stock_site}, url={image_url}"
                )
                stock_result = self._create_stock_image_result(
                    submission_id, student_id, assign_id, image_url, stock_site
                )
                processing_time_ms = int((time.time() - start_time) * 1000)
                return json.dumps(stock_result)

            image = await self.download_image(image_url)

            is_ai_generated, ai_source, ai_confidence = (
                self.ai_detector.check_ai_generated(image)
            )

            if is_ai_generated and ai_confidence >= 0.70:
                logger.warning(
                    f"AI-generated image rejected: submission={submission_id}, "
                    f"source={ai_source}, confidence={ai_confidence:.2f}"
                )

                ai_detection_result = self._create_ai_detection_result(
                    submission_id,
                    student_id,
                    assign_id,
                    image_url,
                    ai_source or "unknown",
                    ai_confidence,
                )

                processing_time_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    f"Database updated: submission={submission_id}, "
                    f"processing_time={processing_time_ms}ms"
                )
                return json.dumps(ai_detection_result)

            elif is_ai_generated:
                logger.info(
                    f"Low-confidence AI detection: submission={submission_id}, "
                    f"source={ai_source}, confidence={ai_confidence:.2f}, threshold=0.70"
                )

            hashes = self.hash_handler.compute_hashes(image)

            self_result = await self.check_self_submissions(
                hashes, student_id, assign_id, datetime.utcnow()
            )
            peer_result = await self.check_peer_submissions(
                hashes,
                student_id,
                self_result.get("first_submission_date_for_image", None),
            )
            # hash_check_result = await self.check_db_reference_hash_match(hashes)
            hash_check_result = await self.check_assignment_reference_hash_match(hashes,assign_id)

            (
                hash_match,
                matched_ref,
                hash_similarity,
                matched_ref_image_url,
            ) = hash_check_result

            skip_clip = (
                hash_match
                and hash_similarity is not None
                and hash_similarity >= 0.80
                and not peer_result.get("is_match")
                and not self_result.get("is_match")
            )

            matched_ref_clip = None
            clip_similarity = 0.0
            clip_embedding = None

            if skip_clip:
                logger.info(
                    f"Skipping CLIP: strong hash match (similarity={hash_similarity:.4f} >= 0.80)"
                )
            else:
                (
                    matched_ref_clip,
                    clip_similarity,
                    clip_embedding,
                ) = await self.check_clip_match(image)

            ref_result = await self._build_reference_result(
                hash_match,
                matched_ref,
                hash_similarity,
                matched_ref_image_url,
                matched_ref_clip,
                clip_similarity,
            )

            plagiarism_status = self.determine_plagiarism_status(
                peer_result, self_result, ref_result
            )
            plagiarism_status["submission_id"] = submission_id

            plagiarism_status["is_ai_generated"] = is_ai_generated
            plagiarism_status["ai_detection_source"] = (
                ai_source if is_ai_generated else None
            )
            plagiarism_status["ai_confidence"] = (
                float(ai_confidence) if is_ai_generated else 0.0
            )

            processing_time = int((time.time() - start_time) * 1000)

            await self.update_submission(
                db_record_id,
                hashes,
                plagiarism_status,
                processing_time,
                clip_embedding,
            )

            logger.info(
                f"Processing complete: submission={submission_id}, "
                f"plagiarized={plagiarism_status.get('is_plagiarized', False)}, "
                f"match_type={plagiarism_status.get('match_type', 'none')}, "
                f"similarity={plagiarism_status.get('similarity_score', 0.0):.4f}, "
                f"time={processing_time}ms"
            )

            return self.format_results(
                submission_id, assign_id, student_id, image_url, plagiarism_status
            )

        except Exception as e:
            logger.error(
                f"Failed to process submission: submission_id={data.get('submission_id', 'unknown')}, "
                f"error={e}",
                exc_info=True,
            )
            return None

        finally:
            if image:
                try:
                    image.close()
                    logger.debug("Image resources freed successfully")
                except Exception as e:
                    logger.error(f"Failed to free image resources: error={e}")

    async def check_peer_submissions(
        self,
        hashes: dict,
        current_student_id: str,
        first_submission_date_for_image=None,
    ) -> dict:
        """
        Check if submission matches any peer's submission (hash-based, async).

        Args:
            hashes: dict with 'phash', 'dhash', 'ahash'
            current_student_id: hashed student_id of current submission

        Returns:
            dict with keys:
                - is_match (bool)
                - matched_submission_ids (list)
                - matched_student_ids (list)
                - matched_image_urls (list)
                - matched_similarities (list)
                - best_similarity (float)
                - best_match_student_id (str or None)
        """
        if not self.enable_peer_check:
            return self._create_empty_peer_result()

        try:
            peer_submissions = await self.db_manager.fetch_peer_submissions(
                current_student_id, first_submission_date_for_image
            )

            if not peer_submissions:
                logger.info("No peer submissions for comparison")
                return self._create_empty_peer_result()

            tasks = [
                self._async_compare_peer(hashes, peer) for peer in peer_submissions
            ]
            results = await asyncio.gather(*tasks)

            return self._process_peer_matches(results, peer_submissions)

        except Exception as e:
            logger.error(f"Peer check failed: {e}")
            return self._create_empty_peer_result()

    async def check_self_submissions(
        self,
        hashes: dict,
        current_student_id: str,
        current_assign_id: str,
        current_submission_date,
    ) -> dict:
        """
        Check if submission matches student's own previous submissions (async).

        Logic:
        - Within resubmission window: Allowed (not flagged as plagiarism)
        - Outside window: Flagged as self-plagiarism

        Args:
            hashes: dict with 'phash', 'dhash', 'ahash'
            current_student_id: hashed student_id
            current_submission_date: datetime of current submission

        Returns:
            dict with keys:
                - is_match (bool)
                - matched_submission_ids (list)
                - best_similarity (float)
                - days_since_last (int or None)
                - within_resubmission_window (bool)
                - previous_submission_date (datetime or None)
                :param current_student_id:
                :param current_assign_id:
        """
        if not self.enable_self_check:
            return {
                "is_match": False,
                "matched_submission_ids": [],
                "best_similarity": 0.0,
                "days_since_last": None,
                "within_resubmission_window": False,
                "previous_submission_date": None,
            }

        try:
            self_submissions = await self.db_manager.fetch_self_submissions(
                current_student_id
            )

            if not self_submissions:
                logger.info("First-time submission for this student")
                return {
                    "is_match": False,
                    "matched_submission_ids": [],
                    "matched_assign_ids": [],
                    "matched_image_urls": [],
                    "best_similarity": 0.0,
                    "days_since_last": None,
                    "same_assignment": False,
                    "within_resubmission_window": False,
                    "previous_submission_date": None,
                    "previous_assign_id": None,
                }

            best_match = None
            best_score = 999
            matched_ids = []
            matched_assign_ids = []
            matched_image_urls = []

            first_submission_date_for_image = None
            for prev_sub in self_submissions:
                comparison = self.hash_handler.compare_all_hashes(
                    hashes,
                    {
                        "phash": prev_sub["phash"],
                        "dhash": prev_sub["dhash"],
                        "ahash": prev_sub["ahash"],
                    },
                    threshold=self.self_hash_threshold,
                )

                if comparison["is_match"] and comparison["avg_distance"] < best_score:
                    best_score = comparison["avg_distance"]
                    best_match = prev_sub

                if comparison["is_match"]:
                    matched_ids.append(str(prev_sub["id"]))
                    matched_assign_ids.append(prev_sub.get("assign_id", "N/A"))
                    matched_image_urls.append(prev_sub.get("image_url", ""))

                    submission_date = prev_sub.get("created_at")
                    if (
                        first_submission_date_for_image is None
                        or submission_date < first_submission_date_for_image
                    ):
                        first_submission_date_for_image = submission_date

            if best_match:
                return self._analyze_self_plagiarism(
                    best_match,
                    current_assign_id,
                    current_submission_date,
                    best_score,
                    matched_ids,
                    matched_assign_ids,
                    matched_image_urls,
                    first_submission_date_for_image,
                )
            else:
                logger.info(
                    f"No self-plagiarism detected: checked {len(self_submissions)} previous submissions"
                )
                return self._create_empty_self_result()

        except Exception as e:
            logger.error(f"Self-check failed: {e}")
            return self._create_empty_self_result()

    def determine_plagiarism_status(
        self, peer_result: dict, self_result: dict, ref_result: dict
    ) -> dict:
        """
        Determine final plagiarism status with priority: Self → Peer → Reference.

        Priority Order:
        1. Self-plagiarism (cross-assignment or late resubmission)
        2. Resubmission within window (same assignment) → Continue checks
        3. Peer plagiarism
        4. Reference database match
        5. Original (no matches)
        """
        result = self._init_plagiarism_result()

        if self_result["is_match"]:
            self_status = self._handle_self_plagiarism(self_result)
            if self_status:
                return self_status
            result["resubmission_within_window"] = True
            result["matched_self_submission_ids"] = self_result[
                "matched_submission_ids"
            ]
            result["matched_peer_assign_ids"] = self_result["matched_assign_ids"]
            result["matched_self_image_urls"] = self_result["matched_image_urls"]
            result["days_since_last_submission"] = self_result["days_since_last"]

        if peer_result["is_match"]:
            return self._handle_peer_plagiarism(peer_result)

        if ref_result["is_match"]:
            ref_status = self._handle_reference_match(ref_result)
            if ref_status["is_plagiarized"]:
                return ref_status
            if result["resubmission_within_window"]:
                result["similarity_score"] = self_result["best_similarity"]
                result["match_type"] = "resubmission_allowed"
                logger.info(
                    f"Final Status: RESUBMISSION ALLOWED (within window, "
                    f"{result['days_since_last_submission']} days, passed all checks)"
                )
                return result
            return ref_status

        if result["resubmission_within_window"]:
            result["similarity_score"] = self_result["best_similarity"]
            result["match_type"] = "resubmission_allowed"
            logger.info(
                f"Final Status: RESUBMISSION ALLOWED (within window, "
                f"{result['days_since_last_submission']} days, passed all checks)"
            )

        return result

    def _init_plagiarism_result(self) -> dict:
        """Initialize empty plagiarism result structure."""
        return {
            "is_plagiarized": False,
            "match_type": "original",
            "plagiarism_source": "none",
            "similarity_score": 0.0,
            "peer_plagiarism_detected": False,
            "self_plagiarism_detected": False,
            "resubmission_within_window": False,
            "matched_peer_submission_ids": [],
            "matched_peer_student_ids": [],
            "matched_peer_image_urls": [],
            "matched_peer_similarity_scores": [],
            "matched_peer_assign_ids": [],
            "matched_self_submission_ids": [],
            "matched_self_image_urls": [],
            "matched_reference_ids": [],
            "matched_reference_image_urls": [],
            "days_since_last_submission": None,
        }

    def _handle_self_plagiarism(self, self_result: dict) -> Optional[dict]:
        """
        Handle self-plagiarism detection.

        Returns plagiarism result if actual plagiarism, None if allowed resubmission.
        """
        if not self_result["same_assignment"]:
            result = self._init_plagiarism_result()
            result.update(
                {
                    "is_plagiarized": True,
                    "self_plagiarism_detected": True,
                    "plagiarism_source": "self_cross_assignment",
                    "similarity_score": self_result["best_similarity"],
                    "match_type": self.determine_match_type(
                        self_result["best_similarity"]
                    ),
                    "matched_self_submission_ids": self_result[
                        "matched_submission_ids"
                    ],
                    "matched_peer_assign_ids": self_result["matched_assign_ids"],
                    "matched_self_image_urls": self_result["matched_image_urls"],
                    "days_since_last_submission": self_result["days_since_last"],
                }
            )
            logger.info(
                f"Final Status: SELF-PLAGIARISM (cross-assignment) - {result['match_type']} "
                f"(prev: {self_result['previous_assign_id']})"
            )
            return result

        if (
            self_result["same_assignment"]
            and not self_result["within_resubmission_window"]
        ):
            result = self._init_plagiarism_result()
            result.update(
                {
                    "is_plagiarized": True,
                    "self_plagiarism_detected": True,
                    "plagiarism_source": "self_late_resubmission",
                    "similarity_score": self_result["best_similarity"],
                    "match_type": self.determine_match_type(
                        self_result["best_similarity"]
                    ),
                    "matched_self_submission_ids": self_result[
                        "matched_submission_ids"
                    ],
                    "matched_peer_assign_ids": self_result["matched_assign_ids"],
                    "matched_self_image_urls": self_result["matched_image_urls"],
                    "days_since_last_submission": self_result["days_since_last"],
                }
            )
            logger.info(
                f"Final Status: SELF-PLAGIARISM (late resubmission) - {result['match_type']} "
                f"({result['days_since_last_submission']} days)"
            )
            return result

        return None

    def _handle_peer_plagiarism(self, peer_result: dict) -> dict:
        """Handle peer plagiarism detection."""
        result = self._init_plagiarism_result()
        result.update(
            {
                "is_plagiarized": True,
                "peer_plagiarism_detected": True,
                "plagiarism_source": "peer"
                if len(peer_result["matched_submission_ids"]) == 1
                else "peer_collusion",
                "similarity_score": peer_result["best_similarity"],
                "match_type": self.determine_match_type(peer_result["best_similarity"]),
                "matched_peer_submission_ids": peer_result["matched_submission_ids"],
                "matched_peer_student_ids": peer_result["matched_student_ids"],
                "matched_peer_image_urls": peer_result["matched_image_urls"],
                "matched_peer_similarity_scores": peer_result["matched_similarities"],
                "matched_peer_assign_ids": peer_result["matched_assign_ids"],
            }
        )
        logger.info(
            f"Final Status: PEER PLAGIARISM ({result['plagiarism_source']}) - {result['match_type']}"
        )
        return result

    def _handle_reference_match(self, ref_result: dict) -> dict:
        """Handle reference database match."""
        result = self._init_plagiarism_result()

        match_type = self.determine_match_type(ref_result["similarity"])

        is_plagiarized = match_type != "original"
        plagiarism_source = "reference" if is_plagiarized else "none"

        result.update(
            {
                "is_plagiarized": is_plagiarized,
                "plagiarism_source": plagiarism_source,
                "similarity_score": ref_result["similarity"],
                "match_type": match_type,
            }
        )

        if is_plagiarized:
            if ref_result.get("matched_ref_id"):
                result["matched_reference_ids"] = [ref_result["matched_ref_id"]]
            if ref_result.get("image_url"):
                result["matched_reference_image_urls"] = [ref_result["image_url"]]

        logger.info(f"Final Status: REFERENCE MATCH - {result['match_type']}")
        return result

    def _create_ai_detection_result(
        self,
        submission_id: str,
        student_id: str,
        assign_id: str,
        image_url: str,
        ai_source: str,
        ai_confidence: float,
    ) -> dict:
        """Create AI detection result dictionary."""
        return {
            "submission_id": submission_id,
            "student_id": student_id,
            "assignment_id": assign_id,
            "image_url": image_url,
            "is_ai_generated": True,
            "ai_detection_source": ai_source,
            "ai_confidence": float(ai_confidence),
            "is_plagiarized": True,
            "similarity_score": float(ai_confidence),
            "match_type": "ai_generated",
            "plagiarism_source": "ai_generated",
            "similar_sources": [],
        }

    def _create_stock_image_result(
        self,
        submission_id: str,
        student_id: str,
        assign_id: str,
        image_url: str,
        stock_site: str,
    ) -> dict:
        """Create stock image detection result dictionary."""
        return {
            "submission_id": submission_id,
            "student_id": student_id,
            "assignment_id": assign_id,
            "image_url": image_url,
            "is_ai_generated": False,
            "ai_detection_source": "None",
            "ai_confidence": 0.0,
            "is_plagiarized": True,
            "similarity_score": 1.0,
            "match_type": "stock_image",
            "plagiarism_source": f"stock_image_{stock_site}",
            "similar_sources": [{"source": stock_site, "url": image_url}],
        }

    async def _build_reference_result(
        self,
        hash_match: bool,
        matched_ref: Optional[str],
        hash_similarity: Optional[float],
        matched_ref_image_url: Optional[str],
        matched_ref_clip: Optional[str],
        clip_similarity: Optional[float],
    ) -> dict:
        """Build reference result from hash or CLIP match."""
        if hash_match:
            logger.debug(
                f"Using perceptual hash match: reference_id={matched_ref}, similarity={hash_similarity:.4f}"
            )
            return {
                "is_match": True,
                "matched_ref_id": matched_ref,
                "similarity": hash_similarity,
                "image_url": matched_ref_image_url,
            }

        ref_image_url = None
        if matched_ref_clip:
            logger.debug(
                f"Fetching reference image URL: reference_id={matched_ref_clip}"
            )
            try:
                image_path_val = await self.db_manager.fetch_reference_images_by_id(
                    matched_ref_clip
                )
                if image_path_val:
                    ref_image_url = image_path_val
                    logger.debug(
                        f"Reference image URL retrieved: url={ref_image_url[:80]}..."
                    )
                else:
                    logger.warning(
                        f"Reference image URL not found in database: reference_id={matched_ref_clip}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to fetch reference image URL: reference_id={matched_ref_clip}, error={e}"
                )
        else:
            logger.debug("No CLIP match found, skipping reference image URL fetch")

        is_match = (
            clip_similarity is not None and clip_similarity >= self.semantic_threshold
        )

        return {
            "is_match": is_match,
            "matched_ref_id": matched_ref_clip,
            "similarity": clip_similarity if clip_similarity is not None else 0.0,
            "image_url": ref_image_url,
        }

    def _create_empty_peer_result(self) -> dict:
        """Create empty peer result (no matches found)."""
        return {
            "is_match": False,
            "matched_submission_ids": [],
            "matched_student_ids": [],
            "matched_assign_ids": [],
            "matched_image_urls": [],
            "matched_similarities": [],
            "best_similarity": 0.0,
            "best_match_student_id": None,
        }

    def _create_empty_self_result(self) -> dict:
        """Create empty self result (no matches found)."""
        return {
            "is_match": False,
            "matched_submission_ids": [],
            "matched_assign_ids": [],
            "matched_image_urls": [],
            "best_similarity": 0.0,
            "days_since_last": None,
            "same_assignment": False,
            "within_resubmission_window": False,
            "previous_submission_date": None,
            "previous_assign_id": None,
        }

    def _process_peer_matches(self, results: list, peer_submissions: list) -> dict:
        """Process peer comparison results and build match dictionary."""
        best_match = None
        best_score = 999
        matches = []

        for comparison, peer in results:
            if comparison["is_match"]:
                similarity = 1 - (comparison["avg_distance"] / 64.0)
                matches.append(
                    {
                        "submission_id": str(peer["id"]),
                        "student_id": peer["student_id"],
                        "assign_id": peer.get("assign_id", "N/A"),
                        "img_url": peer.get("image_url", ""),
                        "similarity": similarity,
                        "avg_distance": comparison["avg_distance"],
                    }
                )

                if comparison["avg_distance"] < best_score:
                    best_score = comparison["avg_distance"]
                    best_match = peer

        if not matches:
            logger.info(
                f"No peer plagiarism detected (checked {len(peer_submissions)} peers)"
            )
            return self._create_empty_peer_result()

        matches.sort(key=lambda x: x["similarity"], reverse=True)

        logger.info(
            f"PEER MATCH found: {len(matches)} peer submission(s) "
            f"(similarity: {matches[0]['similarity']:.4f})"
        )

        return {
            "is_match": True,
            "matched_submission_ids": [m["submission_id"] for m in matches],
            "matched_student_ids": [m["student_id"] for m in matches],
            "matched_assign_ids": [m["assign_id"] for m in matches],
            "matched_image_urls": [m["img_url"] for m in matches],
            "matched_similarities": [m["similarity"] for m in matches],
            "best_similarity": matches[0]["similarity"],
            "best_match_student_id": best_match["student_id"] if best_match else None,
        }

    def _analyze_self_plagiarism(
        self,
        best_match: dict,
        current_assign_id: str,
        current_submission_date,
        best_score: float,
        matched_ids: list,
        matched_assign_ids: list,
        matched_image_urls: list,
        first_submission_date_for_image: Optional[datetime],
    ) -> dict:
        """Analyze self-plagiarism match and determine if it's within resubmission window."""
        similarity = 1 - (best_score / 64.0)
        days_diff = (current_submission_date - best_match["created_at"]).days
        same_assignment = best_match["assign_id"] == current_assign_id

        within_window = False
        if same_assignment:
            within_window = days_diff <= self.resubmission_window_days

        if not same_assignment:
            logger.info(
                f" SELF-PLAGIARISM (cross-assignment): Reused from assignment '{best_match['assign_id']}' → '{current_assign_id}' (similarity: {similarity:.4f})"
            )
        elif same_assignment and not within_window:
            logger.info(
                f" SELF-PLAGIARISM (late resubmission): Same assignment '{current_assign_id}' after {days_diff} days (window: {self.resubmission_window_days} days, similarity: {similarity:.4f})"
            )
        elif same_assignment and within_window:
            logger.info(
                f"  RESUBMISSION within window: Same assignment '{current_assign_id}', {days_diff} days ago (similarity: {similarity:.4f}) - will check peer/reference"
            )

        return {
            "is_match": True,
            "matched_submission_ids": matched_ids,
            "matched_assign_ids": matched_assign_ids,
            "matched_image_urls": matched_image_urls,
            "best_similarity": similarity,
            "days_since_last": days_diff,
            "same_assignment": same_assignment,
            "within_resubmission_window": within_window,
            "previous_submission_date": best_match["created_at"],
            "previous_assign_id": best_match["assign_id"],
            "first_submission_date_for_image": first_submission_date_for_image,
        }

    def determine_role(self, similarity: float, match_type: str) -> str:
        """
        Determine role based on individual match similarity score

        Role classification per match (not submission-level):
        - peer_exact_match: >= 0.95 (exact duplicate)
        - peer_near_duplicate: >= 0.90 (near duplicate)
        - peer_semantic_match: >= 0.80 (semantic match)
        - self_copy: self-plagiarism
        - reference_copy: reference database match

        Args:
            similarity: Individual match similarity score (0.0 to 1.0)
            match_type: Type of match ('peer', 'self', 'reference')

        Returns:
            Role string for similar_sources array
        """
        if match_type == "self":
            return "self_copy"
        elif match_type == "reference":
            return "reference_copy"
        else:  # peer matches
            if similarity >= self.exact_dup_threshold:  # >= 0.95
                return "peer_exact_match"
            elif similarity >= self.near_dup_threshold:  # >= 0.90
                return "peer_near_duplicate"
            else:  # >= 0.80
                return "peer_semantic_match"

    def format_results(
        self,
        submission_id: str,
        assign_id: str,
        student_id: str,
        image_url: str,
        plagiarism_status: dict,
    ) -> str:
        """
        Format plagiarism results as JSON for feedback queue.

        Returns JSON string with submission results and similar sources.
        """
        try:
            similar_sources = []

            if plagiarism_status.get("is_plagiarized", False):
                if plagiarism_status.get("peer_plagiarism_detected"):
                    similar_sources.extend(self._format_peer_matches(plagiarism_status))

                if plagiarism_status.get("self_plagiarism_detected"):
                    similar_sources.extend(
                        self._format_self_matches(plagiarism_status, student_id)
                    )

                if plagiarism_status.get("matched_reference_ids"):
                    similar_sources.extend(
                        self._format_reference_matches(plagiarism_status)
                    )

            is_plagiarized = plagiarism_status.get("is_plagiarized", False)

            message = {
                "submission_id": submission_id,
                "student_id": student_id,
                "assignment_id": assign_id,
                "image_url": image_url,
                "is_plagiarized": is_plagiarized,
                "match_type": plagiarism_status["match_type"],
            }

            if is_plagiarized:
                message["similarity_score"] = plagiarism_status["similarity_score"]
                message["plagiarism_source"] = plagiarism_status["plagiarism_source"]
                message["similar_sources"] = similar_sources

            if plagiarism_status.get("is_ai_generated", False):
                message["is_ai_generated"] = True
                message["ai_detection_source"] = plagiarism_status.get(
                    "ai_detection_source"
                )
                message["ai_confidence"] = plagiarism_status.get("ai_confidence", 0.0)

            # payload_preview = json.dumps(message, indent=2)[:2000]
            # logger.info(f"Result payload preview (2000 chars):\n{payload_preview}...")
            

            return json.dumps(message)

        except Exception as e:
            logger.error(f"Failed to format results: {e}", exc_info=True)
            return json.dumps({"error": str(e)})

    def _format_peer_matches(self, plagiarism_status: dict) -> list:
        """Format peer plagiarism matches for similar_sources."""
        matches = []
        matched_ids = plagiarism_status.get("matched_peer_submission_ids", [])
        matched_students = plagiarism_status.get("matched_peer_student_ids", [])
        matched_assigns = plagiarism_status.get("matched_peer_assign_ids", [])
        matched_urls = plagiarism_status.get("matched_peer_image_urls", [])
        matched_scores = plagiarism_status.get("matched_peer_similarity_scores", [])

        for i in range(len(matched_ids)):
            similarity = matched_scores[i] if i < len(matched_scores) else 0.0
            matches.append(
                {
                    "submission_id": str(matched_ids[i])
                    if i < len(matched_ids)
                    else None,
                    "student_id": str(matched_students[i])
                    if i < len(matched_students)
                    else None,
                    "assignment_id": str(matched_assigns[i])
                    if i < len(matched_assigns)
                    else "N/A",
                    "image_url": matched_urls[i] if i < len(matched_urls) else "",
                    "similarity_score": similarity,
                    "role": self.determine_role(similarity, "peer"),
                }
            )

        return matches

    def _format_self_matches(self, plagiarism_status: dict, student_id: str) -> list:
        """Format self-plagiarism matches for similar_sources."""
        matches = []
        matched_self_ids = plagiarism_status.get("matched_self_submission_ids", [])
        matched_self_assigns = plagiarism_status.get("matched_peer_assign_ids", [])
        matched_self_urls = plagiarism_status.get("matched_self_image_urls", [])
        similarity = plagiarism_status["similarity_score"]

        for i, self_id in enumerate(matched_self_ids):
            matches.append(
                {
                    "submission_id": str(self_id),
                    "student_id": str(student_id),
                    "assignment_id": str(matched_self_assigns[i])
                    if i < len(matched_self_assigns)
                    else "N/A",
                    "image_url": matched_self_urls[i]
                    if i < len(matched_self_urls)
                    else "",
                    "similarity_score": similarity,
                    "role": "self_copy",
                }
            )

        return matches

    def _format_reference_matches(self, plagiarism_status: dict) -> list:
        """Format reference database matches for similar_sources."""
        matches = []
        matched_ref_ids = plagiarism_status.get("matched_reference_ids", [])
        matched_ref_urls = plagiarism_status.get("matched_reference_image_urls", [])
        similarity = plagiarism_status["similarity_score"]

        for i, ref_id in enumerate(matched_ref_ids):
            matches.append(
                {
                    "reference_id": str(
                        ref_id
                    ),  # REF-V2-00211 format from reference_images table
                    "image_url": matched_ref_urls[i]
                    if i < len(matched_ref_urls)
                    else "",
                    "similarity_score": similarity,
                    "role": "reference_copy",
                }
            )

        return matches
