import os
import sys
import argparse
import logging
from pathlib import Path
from tqdm import tqdm
import asyncio
import asyncpg
import pandas as pd
from google.cloud import storage
from PIL import Image
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Import handlers
from image_worker.clip_handler import CLIPHandler
from image_worker.hash_handler import HashHandler


class StudentSubmissionSeeder:
    def __init__(self):
        logger.info("Initializing Student Submission Seeder with ViT-L/14...")

        self.clip_handler = CLIPHandler(model_name="ViT-L/14", device="cpu")
        self.hash_handler = HashHandler()

        self.db_config = {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", 5432)),
            "database": os.getenv("POSTGRES_DB", "plagiarism_db"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD"),  # SECURITY: No default password
        }

        # Validate required credentials
        if not self.db_config["password"]:
            raise ValueError(
                "POSTGRES_PASSWORD environment variable is required for database connection"
            )

        try:
            self.gcs_client = storage.Client()
            logger.info("GCS authentication successful")
        except Exception as e:
            logger.error(f"GCS authentication failed: {e}")
            logger.info("Set GOOGLE_APPLICATION_CREDENTIALS environment variable")
            sys.exit(1)

        self.temp_dir = tempfile.mkdtemp(prefix="submission_images_")
        logger.info(f"Temp directory: {self.temp_dir}")

        logger.info("Initialized with ViT-L/14 (768D embeddings)")
        logger.info("Storage: PostgreSQL pgvector only (no FAISS)")
        logger.info("Hashes: pHash, dHash, aHash")

    def validate_xlsx(self, xlsx_path):
        """Validate XLSX file has required columns."""
        logger.info(f"Validating XLSX file: {xlsx_path}")

        try:
            df = pd.read_excel(xlsx_path)
        except Exception as e:
            logger.error(f"Error reading XLSX: {e}")
            sys.exit(1)

        required_columns = [
            "student_id",
            "assignment_id",
            "submission_id",
            "image_gcs_path",
        ]
        missing_columns = set(required_columns) - set(df.columns)

        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            logger.error(f"Available columns: {list(df.columns)}")
            sys.exit(1)

        null_counts = df[required_columns].isnull().sum()
        if null_counts.any():
            logger.warning("Found null values in columns:")
            for col, count in null_counts.items():
                if count > 0:
                    logger.warning(f"   - {col}: {count} null values")

        duplicate_submissions = df[df.duplicated(subset=["submission_id"], keep=False)]
        if not duplicate_submissions.empty:
            logger.warning(
                f"Found {len(duplicate_submissions)} duplicate submission_ids"
            )
            logger.warning(
                f"   First few duplicates: {duplicate_submissions['submission_id'].head().tolist()}"
            )

        logger.info(f"XLSX validated: {len(df)} rows")
        logger.info(f"   Students: {df['student_id'].nunique()}")
        logger.info(f"   Assignments: {df['assignment_id'].nunique()}")
        logger.info(f"   Submissions: {df['submission_id'].nunique()}")

        return df

    def parse_gcs_path(self, gcs_path):
        """
        Parse GCS path to extract bucket and blob name.

        Supports:
        - gs://bucket-name/path/to/image.jpg
        - https://storage.googleapis.com/bucket-name/path/to/image.jpg
        """
        gcs_path = gcs_path.strip()

        if gcs_path.startswith("gs://"):
            path_without_prefix = gcs_path.replace("gs://", "")
            parts = path_without_prefix.split("/", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid GCS path format: {gcs_path}")
            bucket_name, blob_name = parts

        elif "storage.googleapis.com" in gcs_path:
            path_part = gcs_path.split("storage.googleapis.com/")[1]
            parts = path_part.split("/", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid GCS URL format: {gcs_path}")
            bucket_name, blob_name = parts

        else:
            raise ValueError(
                f"Unsupported GCS path format: {gcs_path}. Use gs:// or https://storage.googleapis.com/"
            )

        return bucket_name, blob_name

    def download_from_gcs(self, gcs_path, submission_id):
        """Download image from GCS to temp directory."""
        try:
            bucket_name, blob_name = self.parse_gcs_path(gcs_path)

            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            if not blob.exists():
                logger.error(f"Blob does not exist: {gcs_path}")
                return None

            file_extension = Path(blob_name).suffix
            local_filename = f"{submission_id}{file_extension}"
            local_path = Path(self.temp_dir) / local_filename

            blob.download_to_filename(str(local_path))

            return str(local_path)

        except Exception as e:
            logger.error(f"Error downloading {gcs_path}: {e}")
            return None

    def validate_image(self, image_path):
        """Validate image file is not corrupted and has valid dimensions."""
        try:
            img = Image.open(image_path)
            img.verify()

            img = Image.open(image_path)

            if img.width < 10 or img.height < 10:
                logger.warning(f"Image too small: {img.size}")
                return False

            try:
                img.convert("RGB")
            except Exception:
                logger.warning("Cannot convert image to RGB")
                return False

            return True

        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return False

    def process_submission(self, row):
        """Process single submission: download, validate, generate embeddings and hashes."""
        submission_id = row["submission_id"]
        student_id = row["student_id"]
        assignment_id = row["assignment_id"]
        gcs_path = row["image_gcs_path"]

        try:
            local_path = self.download_from_gcs(gcs_path, submission_id)
            if not local_path:
                return None

            if not self.validate_image(local_path):
                os.remove(local_path)
                return None

            image = Image.open(local_path)

            embedding = self.clip_handler.generate_embedding(image)
            if embedding is None:
                logger.error(
                    f"Failed to generate embedding for submission {submission_id}"
                )
                os.remove(local_path)
                return None

            hashes = self.hash_handler.compute_hashes(image)
            if not hashes:
                logger.error(f"Failed to compute hashes for submission {submission_id}")
                os.remove(local_path)
                return None

            os.remove(local_path)

            return {
                "submission_id": submission_id,
                "student_id": student_id,
                "assignment_id": assignment_id,
                "gcs_path": gcs_path,
                "embedding": embedding,
                "phash": hashes["phash"],
                "dhash": hashes["dhash"],
                "ahash": hashes["ahash"],
            }

        except Exception as e:
            logger.error(f"Error processing submission {submission_id}: {e}")
            if "local_path" in locals() and os.path.exists(local_path):
                os.remove(local_path)
            return None

    def ensure_table_exists(self):
        """Create student_submissions table if it doesn't exist."""
        logger.info("Checking database table...")
        asyncio.run(self._ensure_table_exists_async())

    async def _ensure_table_exists_async(self):
        """Create student_submissions table if it doesn't exist (async)."""
        try:
            conn_string = (
                f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
                f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
            )
            conn = await asyncpg.connect(conn_string)
            
            create_table_query = """
                CREATE TABLE IF NOT EXISTS student_submissions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    submission_id VARCHAR(100) UNIQUE NOT NULL,
                    student_id VARCHAR(100) NOT NULL,
                    assignment_id VARCHAR(100) NOT NULL,
                    gcs_path TEXT NOT NULL,
                    phash VARCHAR(64),
                    dhash VARCHAR(64),
                    ahash VARCHAR(64),
                    clip_embedding vector(768),
                    clip_embedding_generated BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                
                -- Create indexes for fast lookups
                CREATE INDEX IF NOT EXISTS idx_submissions_student ON student_submissions(student_id);
                CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON student_submissions(assignment_id);
                CREATE INDEX IF NOT EXISTS idx_submissions_submission_id ON student_submissions(submission_id);
                
                -- Create pgvector index for similarity search (HNSW for performance)
                CREATE INDEX IF NOT EXISTS idx_submissions_clip_embedding ON student_submissions 
                USING hnsw (clip_embedding vector_cosine_ops);
            """

            await conn.execute(create_table_query)

            logger.info("Table student_submissions ready")

            await conn.close()

        except Exception as e:
            logger.error(f"Database error: {e}")
            sys.exit(1)

    def check_existing_submissions(self, submission_ids):
        """Check which submission_ids already exist in database."""
        return asyncio.run(self._check_existing_submissions_async(submission_ids))

    async def _check_existing_submissions_async(self, submission_ids):
        """Check which submission_ids already exist in database (async)."""
        try:
            conn_string = (
                f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
                f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
            )
            conn = await asyncpg.connect(conn_string)

            rows = await conn.fetch(
                "SELECT submission_id FROM student_submissions WHERE submission_id = ANY($1)",
                submission_ids,
            )

            existing = set(row['submission_id'] for row in rows)

            await conn.close()

            return existing

        except Exception as e:
            logger.error(f"Error checking existing submissions: {e}")
            return set()

    def save_to_database(self, submission_data_list):
        """Save submission data to student_submissions table in PostgreSQL."""
        if not submission_data_list:
            logger.warning("No data to save")
            return

        logger.info(f"Saving {len(submission_data_list)} submissions to database...")
        asyncio.run(self._save_to_database_async(submission_data_list))

    async def _save_to_database_async(self, submission_data_list):
        """Save submission data to student_submissions table in PostgreSQL (async)."""
        try:
            conn_string = (
                f"postgresql://{self.db_config['user']}:{self.db_config['password']}"
                f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
            )
            conn = await asyncpg.connect(conn_string)

            insert_query = """
                INSERT INTO student_submissions 
                (submission_id, student_id, assignment_id, gcs_path, 
                 phash, dhash, ahash, clip_embedding, clip_embedding_generated)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9)
                ON CONFLICT (submission_id) DO UPDATE SET
                    student_id = EXCLUDED.student_id,
                    assignment_id = EXCLUDED.assignment_id,
                    gcs_path = EXCLUDED.gcs_path,
                    phash = EXCLUDED.phash,
                    dhash = EXCLUDED.dhash,
                    ahash = EXCLUDED.ahash,
                    clip_embedding = EXCLUDED.clip_embedding,
                    clip_embedding_generated = EXCLUDED.clip_embedding_generated,
                    updated_at = NOW()
            """

            batch_data = [
                (
                    data["submission_id"],
                    data["student_id"],
                    data["assignment_id"],
                    data["gcs_path"],
                    data["phash"],
                    data["dhash"],
                    data["ahash"],
                    data["embedding"].tolist(),  # Convert numpy array to list for pgvector
                    True,
                )
                for data in submission_data_list
            ]

            await conn.executemany(insert_query, batch_data)

            logger.info(
                f"Saved {len(submission_data_list)} submissions to student_submissions table"
            )

            await conn.close()

        except Exception as e:
            logger.error(f"Database error: {e}")
            raise

    def seed_from_xlsx(self, xlsx_path, skip_existing=True):
        """Main seeding workflow from XLSX file."""
        logger.info("=" * 60)
        logger.info("STUDENT SUBMISSION SEEDER (ViT-L/14)")
        logger.info("=" * 60)

        df = self.validate_xlsx(xlsx_path)

        self.ensure_table_exists()

        if skip_existing:
            logger.info("Checking for existing submissions...")
            all_submission_ids = df["submission_id"].tolist()
            existing_submissions = self.check_existing_submissions(all_submission_ids)

            if existing_submissions:
                logger.warning(
                    f"Found {len(existing_submissions)} existing submissions (will skip)"
                )
                df = df[~df["submission_id"].isin(existing_submissions)]
                logger.info(f"Remaining to process: {len(df)} submissions")

            if df.empty:
                logger.info("All submissions already processed!")
                return True

        logger.info(f"Processing {len(df)} submissions with ViT-L/14...")

        submission_data_list = []
        failed_submissions = []

        for idx, row in tqdm(
            df.iterrows(), total=len(df), desc="Processing submissions"
        ):
            data = self.process_submission(row)
            if data:
                submission_data_list.append(data)
            else:
                failed_submissions.append(row["submission_id"])

        logger.info(
            f"Successfully processed {len(submission_data_list)}/{len(df)} submissions"
        )

        if failed_submissions:
            logger.warning(
                f"Failed submissions ({len(failed_submissions)}): {failed_submissions[:10]}..."
            )

        if submission_data_list:
            self.save_to_database(submission_data_list)

        logger.info("=" * 60)
        logger.info("Seeding complete!")
        logger.info(f"   Processed: {len(submission_data_list)}/{len(df)}")
        logger.info(
            f"   Success rate: {len(submission_data_list) / len(df) * 100:.1f}%"
        )
        logger.info("=" * 60)

        return True

    def cleanup(self):
        """Clean up temporary directory."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            logger.info(f"Cleaned up temp directory: {self.temp_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Seed student submissions from XLSX with GCS image paths (ViT-L/14, 768D)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python seed_from_xlsx.py --xlsx submissions.xlsx
  
  # Process all (including existing)
  python seed_from_xlsx.py --xlsx submissions.xlsx --no-skip-existing
  
  # With custom GCS credentials
  export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
  python seed_from_xlsx.py --xlsx submissions.xlsx

Required XLSX columns:
  - student_id
  - assignment_id
  - submission_id (unique identifier)
  - image_gcs_path (gs://bucket/path or https://storage.googleapis.com/bucket/path)
        """,
    )

    parser.add_argument(
        "--xlsx",
        type=str,
        required=True,
        help="Path to XLSX file with student submission data",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip submissions that already exist in database (default: True)",
    )

    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="Process all submissions, update existing ones",
    )

    args = parser.parse_args()

    # Validate XLSX file exists
    if not os.path.exists(args.xlsx):
        logger.error(f"XLSX file not found: {args.xlsx}")
        sys.exit(1)

    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set")
        logger.info("   If using default credentials, this is fine.")
        logger.info(
            '   Otherwise, set: export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"'
        )

    logger.info("Configuration:")
    logger.info(f"   XLSX file: {args.xlsx}")
    logger.info(f"   Skip existing: {args.skip_existing}")
    logger.info("   Storage: PostgreSQL pgvector only")
    logger.info("   Model: ViT-L/14 (768D embeddings)")
    logger.info("   Hashes: pHash, dHash, aHash")

    seeder = StudentSubmissionSeeder()

    try:
        success = seeder.seed_from_xlsx(args.xlsx, skip_existing=args.skip_existing)
        sys.exit(0 if success else 1)

    finally:
        seeder.cleanup()


if __name__ == "__main__":
    main()
