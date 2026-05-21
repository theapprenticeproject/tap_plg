from .base_processor import BaseProcessor
import logging
import json

logger = logging.getLogger(__name__)


class ImageProcessor(BaseProcessor):
    """
    Processor for image-based submissions.

    Handles image plagiarism detection using perceptual hashing, CLIP embeddings,
    and FAISS vector search.
    """

    def __init__(self, db_manager=None, image_worker=None):
        if db_manager is None:
            raise ValueError("ImageProcessor requires a shared db_manager instance")
        if image_worker is None:
            raise ValueError("ImageProcessor requires a shared image_worker instance")

        self.db_manager = db_manager
        self.image_worker = image_worker
        logger.info("ImageProcessor initialized with shared ImageWorker instance")

    async def process(self, data: dict) -> dict:
        """
        Process an image submission for plagiarism detection.

        Args:
            data: dict containing:
                - submission_url: URL of the image to process
                - submission_id: unique submission identifier
                - student_id: hashed student identifier
                - assign_id: assignment identifier
                - db_record_id: database record ID (added by insert)

        Returns:
            dict with plagiarism detection results or error message
        """
        submission_url = data.get("submission_url")

        if not submission_url:
            logger.error("No submission_url provided in submission data")
            return {"error": "No submission_url provided"}

        try:
            logger.info(f"Processing image submission: {data.get('submission_id')}")

            # Use shared ImageWorker instance - models already loaded
            result = await self.image_worker.process_submission(data)

            if result is None:
                logger.warning(
                    f"Worker returned None for submission {data.get('submission_id')}"
                )
                return {"error": "Processing failed"}

            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to parse worker result as JSON: {result[:100]}"
                    )
                    return {"error": "Invalid JSON response from worker"}

            logger.debug("Result payload ")
            logger.debug(json.dumps(result, indent=2))

            logger.info(
                f"Successfully processed submission: {data.get('submission_id')}"
            )
            return result

        except Exception as e:
            logger.error(f"Error processing image submission: {e}", exc_info=True)
            return {"error": f"Processing error: {str(e)}"}
