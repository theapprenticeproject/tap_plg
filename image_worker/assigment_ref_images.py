import base64
import io
import os
from PIL import Image
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv
import asyncpg
from datetime import datetime
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# Environment variables
ASSIGNMENT_CACHE_DAYS = int(os.getenv("ASSIGNMENT_CACHE_DAYS", "2"))
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true"
PURGE_CACHE = os.getenv("PURGE_CACHE", "false").lower() == "true"

# Database configuration
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "database": os.getenv("POSTGRES_DB", "plagiarism_db"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
}


async def get_db_connection():
    """Create async database connection."""
    conn_string = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )
    return await asyncpg.connect(conn_string)


async def cleanup_cache():
    """Delete cached assignment reference images older than ASSIGNMENT_CACHE_DAYS."""
    try:
        conn = await get_db_connection()
        try:
            # cutoff_date = datetime.utcnow() - timedelta(days=ASSIGNMENT_CACHE_DAYS)
            
            # Delete old assignment caches (reference_ids starting with "ASSIGN-")
            result = await conn.execute(
                """
                DELETE FROM reference_images 
                WHERE reference_id LIKE 'ASSIGN-%' 
                """
            )
            
            deleted_count = int(result.split()[-1]) if result else 0
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} cached assignment reference images")
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Cache cleanup failed: {e}")


async def get_cached_assignment(assignment_id: str) -> Optional[List[Dict]]:
    """
    Retrieve cached reference images for an assignment from database.
    
    Args:
        assignment_id: Assignment identifier
        
    Returns:
        List of reference image dicts with precomputed hashes (no embeddings), or None if not cached
    """
    try:
        conn = await get_db_connection()
        try:
            # Query for cached images with this assignment_id (no clip_embedding in SELECT)
            rows = await conn.fetch(
                """
                SELECT reference_id, image_path, phash, dhash, ahash, created_at
                FROM reference_images
                WHERE reference_id LIKE $1
                ORDER BY reference_id
                """,
                f"ASSIGN-{assignment_id}-%"
            )
            
            if not rows:
                logger.info(f"No cached reference images found for assignment: {assignment_id}")
                return None
            
            # Check if cache is still valid
            oldest_created = min(row['created_at'] for row in rows)
            age_days = (datetime.utcnow() - oldest_created).days
            
            if age_days > ASSIGNMENT_CACHE_DAYS:
                logger.info(f"Cache expired for assignment {assignment_id} (age: {age_days} days)")
                return None
            
            logger.info(f"Retrieved {len(rows)} cached reference images for assignment: {assignment_id}")
            
            # Return just the hashes and name (no embeddings)
            images = []
            for row in rows:
                images.append({
                    "name": row['reference_id'] + row['image_path'],  # Image name stored in image_path
                    "phash": row['phash'],
                    "dhash": row['dhash'],
                    "ahash": row['ahash']
                })
            
            return images
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Failed to retrieve cached assignment: {e}")
        return None


async def save_to_cache(assignment_id: str, images: List[Dict]):
    """
    Save assignment reference images (hashes + embeddings) to database cache.
    
    Args:
        assignment_id: Assignment identifier
        images: List of image dicts with "name", "phash", "dhash", "ahash", and optionally "embedding"
    """
    try:
        conn = await get_db_connection()
        try:
            cached_count = 0
            
            for idx, img_data in enumerate(images):
                try:
                    # Create unique reference_id for this assignment's reference image
                    reference_id = f"ASSIGN-{assignment_id}-{idx:03d}"
                    image_name = img_data.get("name", f"ref_{idx}")
                    
                    # Check if hashes are precomputed
                    if "phash" not in img_data or "dhash" not in img_data or "ahash" not in img_data:
                        logger.warning(f"Hashes not precomputed for image {idx}, skipping cache")
                        continue
                    
                    # Extract embedding if present
                    embedding = img_data.get("embedding")
                    
                    if embedding is not None:
                        # Convert numpy array to pgvector format
                        embedding_str = '[' + ','.join(map(str, embedding.tolist())) + ']'
                        clip_generated = True
                    else:
                        embedding_str = None
                        clip_generated = False
                    
                    # Insert into database with embedding
                    await conn.execute(
                        """
                        INSERT INTO reference_images 
                        (reference_id, image_path, phash, dhash, ahash, category, description, source,
                         clip_embedding_generated, clip_embedding)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector)
                        ON CONFLICT (reference_id) DO UPDATE SET
                            image_path = EXCLUDED.image_path,
                            phash = EXCLUDED.phash,
                            dhash = EXCLUDED.dhash,
                            ahash = EXCLUDED.ahash,
                            clip_embedding_generated = EXCLUDED.clip_embedding_generated,
                            clip_embedding = EXCLUDED.clip_embedding,
                            updated_at = NOW()
                        """,
                        reference_id,
                        image_name,
                        img_data["phash"],
                        img_data["dhash"],
                        img_data["ahash"],
                        "assignment_cache",
                        f"Reference image from {image_name}",
                        f"assignment_{assignment_id}",
                        clip_generated,
                        embedding_str
                    )
                    
                    cached_count += 1
                    
                except Exception as img_err:
                    logger.error(f"Failed to cache image {idx} for assignment {assignment_id}: {img_err}")
                    continue
            
            logger.info(f"Cached {cached_count}/{len(images)} reference images for assignment: {assignment_id}")
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Failed to save to cache: {e}")


async def get_reference_images(
    assignment_id: str,
    clip_handler=None,
    hash_handler=None
) -> Optional[List[Dict]]:
    """
    Fetch reference images for an assignment from TAP LMS API with caching support.
    
    Args:
        assignment_id: Assignment identifier
        clip_handler: CLIPHandler instance from worker (optional)
        hash_handler: HashHandler instance from worker (optional)

    Returns:
        List of reference image dictionaries with precomputed hashes (no embeddings in return)
    """
    try:
        # Cleanup old cache if enabled
        if PURGE_CACHE:
            await cleanup_cache()
        
        # Check cache first if enabled
        if ENABLE_CACHE:
            cached_images = await get_cached_assignment(assignment_id)
            if cached_images is not None:
                logger.info(f"Using cached reference images for assignment: {assignment_id}")
                return cached_images
        
        # Fetch from API
        logger.info(f"Fetching reference images from API for assignment: {assignment_id}")
        images = await fetch_from_api(assignment_id, clip_handler, hash_handler)
        
        # Save to cache if enabled (embeddings will be saved to DB but not returned)
        if ENABLE_CACHE and images:
            await save_to_cache(assignment_id, images)
        
        # Remove embeddings from return object
        if images:
            for img in images:
                img.pop("embedding", None)
        
        return images
        
    except Exception as e:
        logger.error(f"Error fetching reference images: {e}")
        return None


async def fetch_from_api(
    assignment_id: str,
    clip_handler=None,
    hash_handler=None
) -> Optional[List[Dict]]:
    """
    Fetch reference images for an assignment from TAP LMS API and compute hashes + embeddings.
    
    Args:
        assignment_id: Assignment identifier
        clip_handler: CLIPHandler instance from worker (optional)
        hash_handler: HashHandler instance from worker (optional)
        
    Returns:
        List of reference image dictionaries with precomputed hashes and embeddings
    """
    api_key = os.getenv("FRAPPE_API_KEY")
    api_secret = os.getenv("FRAPPE_API_SECRET")
    base_url = os.getenv("FRAPPE_API_BASE_URL")
    
    if not all([api_key, api_secret, base_url]):
        logger.error("Missing API configuration: FRAPPE_API_KEY, FRAPPE_API_SECRET, or FRAPPE_API_BASE_URL")
        return None
    
    if hash_handler is None:
        logger.error("No hash_handler provided, cannot compute hashes")
        return None
    
    assignment_context_endpoint = "api/method/tap_lms.imgana.submission.get_assignment_context"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"token {api_key}:{api_secret}"
    }

    api_url = f"{base_url.rstrip('/')}/{assignment_context_endpoint.lstrip('/')}"
    
    try:
        # Use synchronous requests in async context (consider aiohttp for true async)
        response = requests.post(
            api_url,
            headers=headers,
            json={"assignment_id": assignment_id},
            timeout=30
        )
        
        response.raise_for_status()
        data = response.json()
        
        reference_images = data.get("message", {}).get("assignment", {}).get("reference_images", [])
        
        if not reference_images:
            logger.warning(f"No reference images found for assignment: {assignment_id}")
            return []
        
        # Process images: decode, compute hashes and embeddings, then discard PIL objects
        processed_images = []
        for image in reference_images:
            try:
                decoded_bytes = base64.b64decode(image["content"])
                image_obj = Image.open(io.BytesIO(decoded_bytes))
                
                # Compute hashes using passed handler
                hashes = hash_handler.compute_hashes(image_obj)
                
                # Generate CLIP embedding if handler provided
                embedding = None
                if clip_handler is not None:
                    try:
                        embedding = clip_handler.generate_embedding(image_obj)
                    except Exception as embed_err:
                        logger.error(f"Failed to generate embedding for {image.get('name', 'unknown')}: {embed_err}")
                
                # Close PIL Image - we don't need it anymore
                image_obj.close()
                
                # Store hashes and embedding (embedding will be saved to DB but removed before return)
                processed_images.append({
                    "name": image.get("name", f"ref_{len(processed_images)}"),
                    "phash": hashes["phash"],
                    "dhash": hashes["dhash"],
                    "ahash": hashes["ahash"],
                    "embedding": embedding  # Temporary, for save_to_cache
                })
                
            except Exception as img_err:
                logger.error(f"Failed to process image {image.get('name', 'unknown')}: {img_err}")
                continue
        
        logger.info(f"Fetched and processed {len(processed_images)} reference images from API for assignment: {assignment_id}")
        return processed_images
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for assignment {assignment_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch from API: {e}")
        return None