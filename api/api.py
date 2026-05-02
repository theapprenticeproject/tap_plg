import datetime
import logging
import sys
from pathlib import Path
from typing import Optional, List
import asyncio

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import aio_pika
import json
import uuid
from dotenv import load_dotenv
import os

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.security import safe_hash_student_id

load_dotenv()

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_log_format() -> str:
    log_format = os.getenv("LOG_FORMAT", DEFAULT_LOG_FORMAT)
    if log_format.lower() == "json":
        return DEFAULT_LOG_FORMAT
    return log_format


# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format=get_log_format(),
)
logger = logging.getLogger(__name__)

# RabbitMQ Configuration
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "admin")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "admin123")

#PRINT THE RABBITMQ CONFIG FOR DEBUGGING
# logger.info("###################")
# logger.info(f"RABBITMQ_HOST={RABBITMQ_HOST}")
# logger.info(f"RABBITMQ_PORT={RABBITMQ_PORT}")
# logger.info(f"RABBITMQ_VHOST={RABBITMQ_VHOST}")
# logger.info(f"RABBITMQ_USER={RABBITMQ_USER}")
# logger.info("###################")

SUBMISSION_QUEUE = os.getenv("SUBMISSION_QUEUE", "plagiarism_submissions")
FEEDBACK_QUEUE = os.getenv("FEEDBACK_QUEUE", "plagiarism_feedback")

RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}"

# FastAPI App
app = FastAPI(
    title="MentorMe Plagiarism Checker API",
    description="API for submitting and retrieving plagiarism detection results",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# Pydantic Models
class SubmissionRequest(BaseModel):
    """Request model for submission creation"""

    student_id: str = Field(..., description="Student identifier", min_length=1)
    submission_type: str = Field(..., description="Type of submission: text, audio, video, or image")
    submission_url: Optional[str] = Field(
        None, description="URL of the submitted resource (required for image submissions)"
    )
    submission_text: Optional[str] = Field(
        None, description="Text content of the submission (required for text submissions)"
    )
    submitted_at: Optional[str] = Field(
        None,
        description="Original submission timestamp in ISO format. If provided, this value is preserved in the processed result.",
    )
    assignment_id: Optional[str] = Field(None, description="Assignment identifier")

    @validator("submission_type")
    def validate_submission_type(cls, v):
        """Validate that submission_type is one of the supported values"""
        allowed = {"text", "audio", "video", "image"}
        if v not in allowed:
            raise ValueError(f"submission_type must be one of {sorted(allowed)}")
        return v

    @validator("submission_url", always=True)
    def validate_submission_url(cls, v, values):
        if values.get("submission_type") == "image":
            if not v or not v.strip():
                raise ValueError("submission_url is required for image submissions")
            return v.strip()
        return v

    @validator("submission_text", always=True)
    def validate_submission_text(cls, v, values):
        if values.get("submission_type") == "text":
            if not v or not v.strip():
                raise ValueError("submission_text is required for text submissions")
            return v.strip()
        return v

    @validator("student_id")
    def validate_student_id(cls, v):
        """Validate that student_id is not empty"""
        if not v or not v.strip():
            raise ValueError("student_id cannot be empty")
        return v.strip()


class SubmissionResponse(BaseModel):
    """Response model for successful submission"""

    status: str = Field(..., description="Status of the submission")
    submission_id: str = Field(..., description="Unique submission identifier")
    message: str = Field(..., description="Human-readable message")
    timestamp: str = Field(..., description="Submission timestamp in ISO format")


class HealthResponse(BaseModel):
    """Response model for health check"""

    status: str = Field(..., description="Service health status")
    timestamp: str = Field(..., description="Current timestamp in ISO format")
    service: str = Field(..., description="Service name")


class ErrorResponse(BaseModel):
    """Response model for errors"""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    timestamp: str = Field(..., description="Error timestamp in ISO format")


class PlagiarismResult(BaseModel):
    """Model for individual plagiarism result"""

    student_id: str
    submission_id: str
    similarity_score: Optional[float] = None
    status: str
    matched_references: Optional[List[dict]] = None
    timestamp: Optional[str] = None


class ResultsResponse(BaseModel):
    """Response model for plagiarism results"""

    student_id_hash: str = Field(..., description="Hashed student identifier")
    results: List[dict] = Field(..., description="List of plagiarism check results")
    count: int = Field(..., description="Number of results returned")
    timestamp: str = Field(..., description="Response timestamp in ISO format")


@app.get("/", response_model=dict, tags=["General"])
async def root():
    """
    Root endpoint - API information

    Returns basic information about the API service.
    """
    return {
        "service": "MentorMe Plagiarism Checker API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "submit": "/api/v1/submissions",
            "results": "/api/v1/results/{student_id}",
        },
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
async def health():
    """
    Health check endpoint

    Returns the current health status of the API service.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.datetime.utcnow().isoformat(),
        service="MentorMe Plagiarism Checker API",
    )


async def send_to_rabbitmq(message: dict, queue_name: str):
    """
    Send message to RabbitMQ queue

    Args:
        message: Dictionary containing the message payload
        queue_name: Name of the target queue

    Raises:
        HTTPException: If connection to RabbitMQ fails
    """
    try:
        connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=10)
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue(queue_name, durable=True)

            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=queue.name,
            )

        logger.info(
            f"Message sent to queue '{queue_name}': {message.get('submission_id', 'N/A')}"
        )
    except Exception as e:
        logger.error(f"Failed to send message to RabbitMQ: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Message queue service unavailable: {str(e)}",
        )


@app.post(
    "/api/v1/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Submissions"],
    responses={
        201: {"description": "Submission created successfully"},
        400: {"description": "Invalid request data"},
        503: {"description": "Service unavailable"},
    },
)
async def create_submission(request: SubmissionRequest):
    """
    Submit a new user submission for plagiarism detection

    Creates a new plagiarism check submission by sending submission metadata
    to the processing queue.

    Args:
        request: Submission request containing student_id, submission_type, submission_url, and optional assignment_id

    Returns:
        SubmissionResponse with submission details and unique ID

    Raises:
        HTTPException: If validation fails or service is unavailable
    """
    try:
        # Hash student ID for privacy
        hashed_student_id = safe_hash_student_id(request.student_id)

        # Generate unique IDs
        submission_id = str(uuid.uuid4())
        assignment_id = request.assignment_id or str(uuid.uuid4())

        # Log submission (with masked student ID)
        logger.info(
            "Received submission",
            extra={
                "student_id_masked": request.student_id[:2] + "***",
                "student_id_hashed": hashed_student_id[:8] + "...",
                "submission_id": submission_id,
                "assignment_id": assignment_id,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            },
        )

        # Prepare payload for processing queue
        payload = {
            "student_id": hashed_student_id,
            "submission_id": submission_id,
            "submission_type": request.submission_type,
            "submission_url": request.submission_url,
            "submission_text": request.submission_text,
            "submitted_at": request.submitted_at,
            "assign_id": assignment_id,
        }

        # Send to RabbitMQ
        await send_to_rabbitmq(payload, SUBMISSION_QUEUE)

        return SubmissionResponse(
            status="success",
            submission_id=submission_id,
            message="Submission queued for plagiarism detection",
            timestamp=datetime.datetime.utcnow().isoformat(),
        )

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_submission: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the submission",
        )


@app.get(
    "/api/v1/results/{student_id}",
    response_model=ResultsResponse,
    tags=["Results"],
    responses={
        200: {"description": "Results retrieved successfully"},
        404: {"description": "No results found for student"},
        503: {"description": "Service unavailable"},
    },
)
async def get_results(student_id: str):
    """
    Retrieve plagiarism detection results for a student

    Fetches all available plagiarism check results from the feedback queue
    for the specified student ID.

    Args:
        student_id: Student identifier

    Returns:
        ResultsResponse containing all plagiarism check results for the student

    Raises:
        HTTPException: If service is unavailable or student_id is invalid
    """
    try:
        # Validate student_id
        if not student_id or not student_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="student_id cannot be empty",
            )

        # Hash student ID for privacy
        hashed_student_id = safe_hash_student_id(student_id.strip())

        logger.info(
            "Fetching results",
            extra={
                "student_id_masked": student_id[:2] + "***",
                "student_id_hashed": hashed_student_id[:8] + "...",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            },
        )

        # Connect to RabbitMQ
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=10)
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Results service temporarily unavailable",
            )

        user_results = []

        try:
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=100)
                queue = await channel.declare_queue(FEEDBACK_QUEUE, durable=True)

                # Retrieve messages from queue with timeout
                message_count = 0
                max_messages = 1000  # Limit to prevent infinite loops

                while message_count < max_messages:
                    try:
                        # Use timeout to prevent hanging (timeout in seconds)
                        message = await asyncio.wait_for(
                            queue.get(fail=False), timeout=2.0
                        )

                        if message is None:
                            # No more messages in queue
                            break

                        message_count += 1

                        try:
                            data = json.loads(message.body.decode())

                            # Filter by student ID
                            if data.get("student_id") == hashed_student_id:
                                user_results.append(data)
                                await message.ack()
                            else:
                                # Requeue message for other students
                                await message.reject(requeue=True)

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to decode message: {str(e)}")
                            await message.reject(requeue=False)

                    except asyncio.TimeoutError:
                        # No more messages available within timeout
                        break

        except Exception as e:
            logger.error(f"Error retrieving results: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error retrieving results from queue",
            )

        logger.info(
            "Results retrieved",
            extra={
                "student_id_masked": student_id[:2] + "***",
                "student_id_hashed": hashed_student_id[:8] + "...",
                "results_count": len(user_results),
                "timestamp": datetime.datetime.utcnow().isoformat(),
            },
        )

        return ResultsResponse(
            student_id_hash=hashed_student_id[:16] + "...",
            results=user_results,
            count=len(user_results),
            timestamp=datetime.datetime.utcnow().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_results: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while retrieving results",
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
            "timestamp": datetime.datetime.utcnow().isoformat(),
        },
    )


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting MentorMe Plagiarism Checker API...")
    logger.info(f"RabbitMQ URL: {RABBITMQ_HOST}:{RABBITMQ_PORT}")
    logger.info(f"Submission Queue: {SUBMISSION_QUEUE}")
    logger.info(f"Feedback Queue: {FEEDBACK_QUEUE}")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
