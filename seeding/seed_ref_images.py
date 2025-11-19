import os
import sys
import argparse
import logging
from pathlib import Path
from tqdm import tqdm
import asyncio
import asyncpg
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from image_worker.clip_handler import CLIPHandler
from image_worker.hash_handler import HashHandler
from image_worker.faiss_handler import FAISSHandler


class ReferenceImageSeeder:
    def __init__(self, use_pgvector=True, use_faiss=True, compute_hashes=True, batch_size=32):
        logger.info("Initializing Reference Image Seeder with ViT-L/14...")

        # Storage options
        self.use_pgvector = use_pgvector
        self.use_faiss = use_faiss
        self.compute_hashes = compute_hashes
        self.batch_size = batch_size  # Process multiple images in one CLIP forward pass

        # Auto-detect GPU availability for faster processing
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            logger.info("GPU detected! Using CUDA for faster processing")
            # Increase batch size for GPU
            self.batch_size = max(batch_size, 64)
        else:
            logger.info("Using CPU for processing")

        # Initialize handlers with ViT-L/14 model - use local model if available
        local_model = "../data/models/clip/open_clip_pytorch_model.bin"
        self.clip_handler = CLIPHandler(
            model_name="ViT-L/14", 
            device=device,
            local_model_path=local_model if os.path.exists(local_model) else None
        )

        if self.compute_hashes:
            self.hash_handler = HashHandler()
        else:
            self.hash_handler = None

        if self.use_faiss:
            self.faiss_handler = FAISSHandler(dimension=768)  # ViT-L/14 uses 768D
           
            self.faiss_index_path = "./data/faiss_index.bin"
            self.faiss_metadata_path = "./data/faiss_metadata.json"
        else:
            self.faiss_handler = None

        logger.info(f"Storage mode: pgvector={use_pgvector}, FAISS={use_faiss}")
        logger.info(f"Compute hashes: {compute_hashes}")
        logger.info(f"Batch size: {self.batch_size}")

        if self.use_pgvector:
            self.db_config = {
                "host": os.getenv("POSTGRES_HOST", "localhost"),  # localhost when running from WSL
                "port": int(os.getenv("POSTGRES_PORT", 5432)),
                "database": os.getenv("POSTGRES_DB", "plagiarism_db"),
                "user": os.getenv("POSTGRES_USER", "postgres"),
                "password": os.getenv("POSTGRES_PASSWORD", "postgres"),  # Match .env file
            }

        logger.info("Initialized with ViT-L/14 (768D embeddings)")
        if self.use_faiss:
            logger.info(f"FAISS Index: {self.faiss_index_path}")
            logger.info(f"FAISS Metadata: {self.faiss_metadata_path}")

    def scan_images_directory(self, images_dir):
        """Scan directory for reference images with deduplication."""
        logger.info(f"Scanning directory: {images_dir}")

        image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        image_files = []
        seen_names = set()  # Avoid duplicate filenames

        for ext in image_extensions:
            for img_path in Path(images_dir).glob(f"**/*{ext}"):
                # Skip duplicates based on filename
                if img_path.name not in seen_names:
                    image_files.append(img_path)
                    seen_names.add(img_path.name)

        logger.info(f"Found {len(image_files)} unique images")
        return sorted(image_files)

    def process_all_images(self, images_dir, limit=None):
        """Process all images in directory with optimized batch processing."""
        image_files = self.scan_images_directory(images_dir)

        if not image_files:
            logger.error("No images found!")
            return None
        
        # Apply limit if specified (for testing)
        if limit and limit < len(image_files):
            logger.info(f"Limiting to first {limit} images (out of {len(image_files)} found)")
            image_files = image_files[:limit]

        logger.info(f"Processing {len(image_files)} images with ViT-L/14...")
        logger.info("Using batch processing for maximum performance")

        from PIL import Image
        import torch
        
        # Load all images first (fast I/O operation)
        logger.info("Loading images...")
        images = []
        valid_indices = []
        
        for idx, image_path in enumerate(tqdm(image_files, desc="Loading images")):
            try:
                img = Image.open(str(image_path))
                # Resize to reasonable size to save memory
                img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                images.append(img)
                valid_indices.append(idx)
            except Exception as e:
                logger.error(f"Failed to load {image_path.name}: {e}")
                continue
        
        logger.info(f"Successfully loaded {len(images)} images")
        
        # Process embeddings in batches (GPU/CPU optimized)
        logger.info("Generating CLIP embeddings in batches...")
        embeddings = []
        
        for batch_start in tqdm(range(0, len(images), self.batch_size), desc="Processing batches"):
            batch_end = min(batch_start + self.batch_size, len(images))
            batch_images = images[batch_start:batch_end]
            
            # Preprocess batch
            image_tensors = torch.stack([
                self.clip_handler.preprocess(img) for img in batch_images
            ]).to(self.clip_handler.device)
            
            # Generate embeddings for entire batch at once
            with torch.no_grad():
                batch_features = self.clip_handler.model.encode_image(image_tensors)
                batch_features = batch_features / batch_features.norm(dim=-1, keepdim=True)
            
            # Convert to numpy and add to list
            batch_embeddings = batch_features.cpu().numpy()
            embeddings.extend(batch_embeddings)
        
        logger.info(f"Generated {len(embeddings)} embeddings")
        
        # Now compute hashes in parallel (CPU-bound but lighter)
        logger.info("Computing perceptual hashes...")
        reference_data = []
        
        if self.compute_hashes:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import multiprocessing
            
            max_workers = min(multiprocessing.cpu_count() * 2, 16)
            
            def compute_hash(idx_img):
                idx, img = idx_img
                try:
                    hashes = self.hash_handler.compute_hashes(img)
                    return idx, hashes
                except Exception as e:
                    logger.error(f"Hash computation failed for image {idx}: {e}")
                    return idx, {"phash": None, "dhash": None, "ahash": None}
            
            hash_results = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(compute_hash, (i, img)): i for i, img in enumerate(images)}
                for future in tqdm(as_completed(futures), total=len(images), desc="Computing hashes"):
                    idx, hashes = future.result()
                    hash_results[idx] = hashes
        else:
            hash_results = {i: {"phash": None, "dhash": None, "ahash": None} for i in range(len(images))}
        
        # Combine everything
        logger.info("Combining results...")
        for i, (original_idx, embedding) in enumerate(zip(valid_indices, embeddings)):
            image_path = image_files[original_idx]
            hashes = hash_results[i]
            reference_id = f"REF-{original_idx:05d}"
            
            reference_data.append({
                "reference_id": reference_id,
                "image_path": str(image_path),
                "embedding": embedding,
                "phash": hashes["phash"],
                "dhash": hashes["dhash"],
                "ahash": hashes["ahash"],
                "category": "default",
                "description": f"Reference image from {image_path.name}",
                "source": "local_upload",
                "faiss_index_position": original_idx,
            })

        logger.info(f"Successfully processed {len(reference_data)} images")
        return reference_data, embeddings

    def build_faiss_index(self, reference_data, embeddings):
        """Build FAISS index from embeddings with optimized batching."""
        if not self.use_faiss:
            logger.info("Skipping FAISS index build (use_faiss=False)")
            return

        logger.info("Building ViT-L/14 FAISS index...")

        import numpy as np

        # Convert to numpy array in one operation
        embeddings_array = np.array(embeddings, dtype=np.float32)

        logger.info(f"Embedding shape: {embeddings_array.shape}")
        self.faiss_handler.create_index()
        
        # Build metadata list
        metadata = [
            {
                "reference_id": data["reference_id"],
                "image_path": data["image_path"],
                "phash": data["phash"],
                "dhash": data["dhash"],
                "ahash": data["ahash"],
                "category": data["category"],
                "description": data["description"],
            }
            for data in reference_data
        ]

        # Add all vectors at once (more efficient than one-by-one)
        self.faiss_handler.add_vectors(embeddings_array, metadata)

        self.faiss_handler.save_index(self.faiss_index_path, self.faiss_metadata_path)
        logger.info(f"FAISS index saved: {self.faiss_index_path}")
        logger.info(f"Metadata saved: {self.faiss_metadata_path}")

    def save_to_database(self, reference_data):
        """Save reference data to reference_images table."""
        if not self.use_pgvector:
            logger.info("Skipping database save (use_pgvector=False)")
            return

        logger.info(
            f"Saving {len(reference_data)} records to reference_images table..."
        )

        # Run async operation synchronously
        asyncio.run(self._save_to_database_async(reference_data))

    async def _save_to_database_async(self, reference_data):
        """Save reference images to PostgreSQL using asyncpg with optimized batch insert."""
        try:
            # Create connection string
            conn_string = (
                f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
                f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
            )
            
            # Use connection pool for better performance with large datasets
            pool = await asyncpg.create_pool(
                conn_string,
                min_size=1,
                max_size=10,
                command_timeout=60
            )

            # Prepare batch insert with conditional clip_embedding
            if self.use_pgvector:
                insert_query = """
                    INSERT INTO reference_images 
                    (reference_id, image_path, phash, dhash, ahash, category, description, source, faiss_index_position, clip_embedding_generated, clip_embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector)
                    ON CONFLICT (reference_id) DO UPDATE SET
                        image_path = EXCLUDED.image_path,
                        phash = EXCLUDED.phash,
                        dhash = EXCLUDED.dhash,
                        ahash = EXCLUDED.ahash,
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        source = EXCLUDED.source,
                        faiss_index_position = EXCLUDED.faiss_index_position,
                        clip_embedding_generated = EXCLUDED.clip_embedding_generated,
                        clip_embedding = EXCLUDED.clip_embedding,
                        updated_at = NOW()
                """

                # Process in large batches for optimal performance
                batch_size = 500
                total_batches = (len(reference_data) + batch_size - 1) // batch_size
                
                logger.info(f"Inserting {len(reference_data)} records in {total_batches} batches")
                
                async with pool.acquire() as conn:
                    for batch_idx in range(0, len(reference_data), batch_size):
                        batch_end = min(batch_idx + batch_size, len(reference_data))
                        batch = reference_data[batch_idx:batch_end]
                        
                        batch_data = [
                            (
                                data["reference_id"],
                                data["image_path"],
                                data["phash"],
                                data["dhash"],
                                data["ahash"],
                                data["category"],
                                data["description"],
                                data["source"],
                                data["faiss_index_position"],
                                True,
                                # Convert numpy array to PostgreSQL array string format for pgvector
                                '[' + ','.join(map(str, data["embedding"].tolist())) + ']',
                            )
                            for data in batch
                        ]

                        # Use transaction for better performance
                        async with conn.transaction():
                            await conn.executemany(insert_query, batch_data)
                        
                        logger.info(f"Saved batch {batch_idx//batch_size + 1}/{total_batches}")

            logger.info(f"Saved {len(reference_data)} records to reference_images")
            logger.info(f"Embeddings stored in pgvector: {self.use_pgvector}")

            await pool.close()

        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            raise

    def seed_reference_images(self, images_dir, limit=None):
        """Main seeding workflow."""
        logger.info("=" * 60)
        logger.info("REFERENCE IMAGE SEEDER (ViT-L/14)")
        logger.info("=" * 60)
        
        if limit:
            logger.info(f"TEST MODE: Processing only {limit} images")

        try:
            # Process all images
            result = self.process_all_images(images_dir, limit=limit)
            if not result:
                return False

            reference_data, embeddings = result

            # Build FAISS index
            self.build_faiss_index(reference_data, embeddings)

            # Save to database
            self.save_to_database(reference_data)

            logger.info("=" * 60)
            logger.info(f"Successfully seeded {len(reference_data)} images with ViT-L/14!")
            logger.info("=" * 60)

            return True
        except KeyboardInterrupt:
            logger.error("\n\nSeeding interrupted by user. Exiting...")
            return False


def main():
    parser = argparse.ArgumentParser(description="Seed reference images with ViT-L/14")
    parser.add_argument(
        "--images-dir",
        type=str,
        required=True,
        help="Directory containing reference images",
    )
    parser.add_argument(
        "--use-pgvector",
        action="store_true",
        default=True,
        help="Store embeddings in PostgreSQL pgvector (default: True)",
    )
    parser.add_argument(
        "--no-pgvector",
        action="store_false",
        dest="use_pgvector",
        help="Skip storing embeddings in pgvector",
    )
    parser.add_argument(
        "--use-faiss",
        action="store_true",
        default=True,
        help="Store embeddings in FAISS index (default: True)",
    )
    parser.add_argument(
        "--no-faiss",
        action="store_false",
        dest="use_faiss",
        help="Skip building FAISS index",
    )
    parser.add_argument(
        "--compute-hashes",
        action="store_true",
        default=True,
        help="Compute perceptual hashes (pHash, dHash, aHash) (default: True)",
    )
    parser.add_argument(
        "--no-hashes",
        action="store_false",
        dest="compute_hashes",
        help="Skip computing perceptual hashes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of images to process (for testing, e.g., --limit 10)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.images_dir):
        logger.error(f"Directory not found: {args.images_dir}")
        sys.exit(1)

    # Validate storage options
    if not args.use_pgvector and not args.use_faiss:
        logger.error(
            "Error: At least one storage method (pgvector or FAISS) must be enabled!"
        )
        sys.exit(1)

    logger.info("Configuration:")
    logger.info(f"   Images directory: {args.images_dir}")
    logger.info(f"   Use pgvector: {args.use_pgvector}")
    logger.info(f"   Use FAISS: {args.use_faiss}")
    logger.info(f"   Compute hashes: {args.compute_hashes}")
    if args.limit:
        logger.info(f"   Limit: {args.limit} images (TEST MODE)")

    try:
        # Initialize seeder
        seeder = ReferenceImageSeeder(
            use_pgvector=args.use_pgvector,
            use_faiss=args.use_faiss,
            compute_hashes=args.compute_hashes,
        )
        success = seeder.seed_reference_images(args.images_dir, limit=args.limit)

        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.error("\n\nInterrupted by user (Ctrl+C). Exiting gracefully...")
        sys.exit(130)  # Standard exit code for Ctrl+C


if __name__ == "__main__":
    main()
