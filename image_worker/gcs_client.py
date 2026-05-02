"""
GCP Cloud Storage (GCS) client helper functions for authenticated image downloads.

Provides async-compatible methods to download images from GCS buckets using
service account authentication via JSON key files.
"""

import logging
import asyncio
import json
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from PIL import Image
from google.cloud import storage
from google.oauth2 import service_account
from google.api_core.exceptions import NotFound

logger = logging.getLogger(__name__)


def resolve_gcp_key_path(key_path: str) -> Path:
    """Resolve the configured GCP key path for container and local runs."""
    configured_path = Path(key_path).expanduser()

    if configured_path.exists():
        return configured_path

    project_root = Path(__file__).resolve().parent.parent

    if configured_path.is_absolute():
        try:
            local_path = project_root / "app" / configured_path.relative_to("/app")
        except ValueError:
            local_path = configured_path
    else:
        local_path = project_root / configured_path

    return local_path


def load_gcp_credentials(key_path: str) -> Optional[service_account.Credentials]:
    """
    Load GCP service account credentials from JSON key file.

    Args:
        key_path: Path to the GCP service account JSON key file

    Returns:
        service_account.Credentials object, or None if loading fails

    Raises:
        FileNotFoundError: If key file does not exist
        ValueError: If key file is invalid JSON or missing required fields
    """
    try:
        key_file = resolve_gcp_key_path(key_path)
        if not key_file.exists():
            raise FileNotFoundError(f"GCP key file not found: {key_file}")

        with open(key_file, "r") as f:
            key_data = json.load(f)

        credentials = service_account.Credentials.from_service_account_info(key_data)
        logger.debug(f"GCP credentials loaded successfully from: {key_file}")
        return credentials

    except FileNotFoundError as e:
        logger.error(f"GCP key file error: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in GCP key file: {e}")
        raise ValueError(f"Invalid JSON in GCP key file: {e}")
    except Exception as e:
        logger.error(f"Failed to load GCP credentials: {e}")
        raise


def parse_gcs_url(gcs_url: str) -> tuple[str, str]:
    """
    Parse a GCS URL into bucket name and blob path.

    Args:
        gcs_url: GCS URL in format gs://bucket-name/path/to/object

    Returns:
        Tuple of (bucket_name, blob_path)

    Raises:
        ValueError: If URL is not a valid GCS URL
    """
    if gcs_url.startswith("gs://"):
        path = gcs_url[5:]
    elif gcs_url.startswith("https://storage.googleapis.com/"):
        # support public and authenticated GCS object URLs
        parsed = urlparse(gcs_url)
        path = parsed.path.lstrip("/")
    elif gcs_url.startswith("http://storage.googleapis.com/"):
        parsed = urlparse(gcs_url)
        path = parsed.path.lstrip("/")
    else:
        raise ValueError(f"Invalid GCS URL: {gcs_url}. Must start with 'gs://' or 'https://storage.googleapis.com/'")

    # Split bucket name and blob path
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(f"Invalid GCS URL: {gcs_url}. Must include bucket and blob path")

    bucket_name = parts[0]
    blob_path = parts[1]

    if not bucket_name or not blob_path:
        raise ValueError(f"Invalid GCS URL: {gcs_url}. Bucket and blob path cannot be empty")

    return bucket_name, blob_path


def create_gcs_client(credentials: service_account.Credentials) -> storage.Client:
    """
    Create a GCP Storage client with provided credentials.

    Args:
        credentials: GCP service account credentials

    Returns:
        google.cloud.storage.Client instance

    Raises:
        Exception: If client creation fails
    """
    try:
        client = storage.Client(credentials=credentials)
        logger.debug("GCS client created successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to create GCS client: {e}")
        raise


async def download_from_gcs(
    gcs_url: str,
    credentials: service_account.Credentials,
    timeout: int = 30,
) -> Image.Image:
    """
    Download an image from GCS bucket asynchronously.

    Args:
        gcs_url: GCS URL in format gs://bucket-name/path/to/image
        credentials: GCP service account credentials
        timeout: Download timeout in seconds

    Returns:
        PIL Image object

    Raises:
        ValueError: If URL is invalid or credentials missing
        FileNotFoundError: If bucket or blob not found
        Exception: For other GCS operation failures
    """
    try:
        bucket_name, blob_path = parse_gcs_url(gcs_url)
        logger.debug(
            f"Downloading from GCS: bucket={bucket_name}, blob={blob_path}, timeout={timeout}s"
        )

        # Run blocking GCS operations in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        image = await loop.run_in_executor(
            None,
            _download_gcs_blob_sync,
            gcs_url,
            credentials,
            bucket_name,
            blob_path,
            timeout,
        )

        logger.info(f"Successfully downloaded image from GCS: {gcs_url}")
        return image

    except Exception as e:
        logger.error(f"GCS download failed: url={gcs_url}, error={e}", exc_info=True)
        raise


def _download_gcs_blob_sync(
    gcs_url: str,
    credentials: service_account.Credentials,
    bucket_name: str,
    blob_path: str,
    timeout: int,
) -> Image.Image:
    """
    Synchronous helper to download blob from GCS (runs in executor).

    Args:
        gcs_url: Full GCS URL for logging
        credentials: GCP service account credentials
        bucket_name: Name of the GCS bucket
        blob_path: Path to the blob within the bucket
        timeout: Download timeout in seconds

    Returns:
        PIL Image object

    Raises:
        FileNotFoundError: If bucket or blob not found
        Exception: For other GCS operation failures
    """
    try:
        client = create_gcs_client(credentials)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        try:
            blob_content = blob.download_as_bytes(timeout=timeout)
        except NotFound:
            raise FileNotFoundError(
                f"GCS blob not found: gs://{bucket_name}/{blob_path}"
            )

        # Parse image
        try:
            image = Image.open(BytesIO(blob_content))
            logger.debug(
                f"Image parsed successfully: format={image.format}, size={image.size}"
            )
            return image
        except Exception as img_error:
            raise ValueError(
                f"Invalid or corrupted image format from GCS: {str(img_error)}"
            )

    except FileNotFoundError:
        raise
    except Exception as e:
        logger.error(
            f"GCS blob download error: bucket={bucket_name}, blob={blob_path}, error={e}"
        )
        raise


def is_gcs_url(url: str) -> bool:
    """
    Check if a URL is a GCS URL.

    Args:
        url: URL to check

    Returns:
        True if URL is a GCS URL using 'gs://' or 'storage.googleapis.com', False otherwise
    """
    if not url:
        return False
    return (
        url.startswith("gs://")
        or url.startswith("https://storage.googleapis.com/")
        or url.startswith("http://storage.googleapis.com/")
    )
