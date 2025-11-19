# Student Submission Seeder (XLSX to PostgreSQL) - Usage Guide

## Overview
Seeds student submission images from XLSX file into PostgreSQL with **ViT-L/14** CLIP embeddings (768D) and perceptual hashes. Images are downloaded from GCS paths specified in the XLSX file.

## Key Features
 **Unique Identifier**: `submission_id` (unique per row)  
 **Storage**: PostgreSQL pgvector only (no FAISS)  
 **Embeddings**: 768D CLIP (ViT-L/14)  
 **Hashes**: pHash, dHash, aHash (always computed)  
 **Fresh Table**: `student_submissions` (separate from reference_images)  
 **GCS Integration**: Downloads images from Google Cloud Storage  
 **Duplicate Protection**: Skips existing submission_ids by default

## Quick Start

```bash
# 1. Set GCS credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# 2. Install dependencies
pip install pandas openpyxl google-cloud-storage

# 3. Run seeding
python seed_from_xlsx.py --xlsx submissions.xlsx
```

## XLSX File Format

### Required Columns
| Column Name | Type | Description | Example |
|-------------|------|-------------|---------|
| `student_id` | String | Student identifier | `STU-2024-001` |
| `assignment_id` | String | Assignment identifier | `ASSIGN-CS101-HW1` |
| `submission_id` | String | **Unique** submission ID | `SUB-20241106-001` |
| `image_gcs_path` | String | GCS path to image | `gs://bucket/path/image.jpg` |

### Supported GCS Path Formats
```bash
# Format 1: gs:// protocol
gs://my-bucket/submissions/student1/image.jpg

# Format 2: HTTPS URL
https://storage.googleapis.com/my-bucket/submissions/student1/image.jpg
```

### Example XLSX
```
student_id       | assignment_id  | submission_id      | image_gcs_path
-----------------|----------------|--------------------|-----------------------------------------
STU-2024-001     | ASSIGN-HW1     | SUB-001-HW1        | gs://submissions/stu001/hw1.jpg
STU-2024-002     | ASSIGN-HW1     | SUB-002-HW1        | gs://submissions/stu002/hw1.png
STU-2024-001     | ASSIGN-HW2     | SUB-001-HW2        | gs://submissions/stu001/hw2.jpg
```

**Note:** Each row must have a **unique submission_id**. Duplicate submission_ids will be flagged during validation.

## Command-Line Arguments

```bash
python seed_from_xlsx.py --xlsx <file> [OPTIONS]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--xlsx` |  Yes | - | Path to XLSX file with submission data |
| `--skip-existing` | No | `True` | Skip submissions already in database |
| `--no-skip-existing` | No | - | Process all, update existing submissions |

## Database Schema

### Table: `student_submissions`

```sql
CREATE TABLE student_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id VARCHAR(100) UNIQUE NOT NULL,      -- Unique identifier
    student_id VARCHAR(100) NOT NULL,
    assignment_id VARCHAR(100) NOT NULL,
    gcs_path TEXT NOT NULL,
    phash VARCHAR(64),                               -- Perceptual hash
    dhash VARCHAR(64),                               -- Difference hash
    ahash VARCHAR(64),                               -- Average hash
    clip_embedding vector(768),                      -- 768D CLIP embedding
    clip_embedding_generated BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for fast queries
CREATE INDEX idx_submissions_student ON student_submissions(student_id);
CREATE INDEX idx_submissions_assignment ON student_submissions(assignment_id);
CREATE INDEX idx_submissions_submission_id ON student_submissions(submission_id);

-- pgvector HNSW index for similarity search
CREATE INDEX idx_submissions_clip_embedding ON student_submissions 
USING hnsw (clip_embedding vector_cosine_ops);
```

## GCS Authentication Setup

### Option 1: Service Account Key (Recommended)
```bash
# 1. Download service account JSON key from GCP Console
# 2. Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"

# 3. Verify permissions (read-only is sufficient)
#    - storage.objects.get
#    - storage.objects.list
```

### Option 2: Default Application Credentials
```bash
# Use gcloud CLI authentication
gcloud auth application-default login

# Script will use your default credentials
python seed_from_xlsx.py --xlsx submissions.xlsx
```

### Option 3: GCE/Cloud Run (Automatic)
When running on Google Cloud services (GCE, Cloud Run, Cloud Functions), authentication is automatic via service account.

## Usage Examples

### Basic Usage (Skip Existing)
```bash
python seed_from_xlsx.py --xlsx student_submissions.xlsx
```
**Result:** Processes only new submissions, skips duplicates

### Force Update All
```bash
python seed_from_xlsx.py --xlsx student_submissions.xlsx --no-skip-existing
```
**Result:** Processes all submissions, updates existing ones with new data

### Custom Credentials
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/home/user/gcs-key.json"
python seed_from_xlsx.py --xlsx submissions.xlsx
```

### Check What Will Be Processed
```bash
# Dry run (modify script to add --dry-run flag)
python seed_from_xlsx.py --xlsx submissions.xlsx
# Look at validation output to see:
# - Total rows
# - Unique students/assignments
# - Duplicate submission_ids
# - Existing submissions that will be skipped
```

## Processing Flow

```
1. Validate XLSX
   ├─ Check required columns
   ├─ Check for null values
   ├─ Check for duplicate submission_ids
   └─ Show statistics
   
2. Ensure Database Table
   ├─ Create student_submissions table (if not exists)
   ├─ Create indexes
   └─ Create pgvector HNSW index
   
3. Check Existing Submissions
   ├─ Query database for existing submission_ids
   └─ Filter out duplicates (if --skip-existing)
   
4. Process Each Submission
   ├─ Download image from GCS → temp file
   ├─ Validate image (not corrupted, valid dimensions)
   ├─ Generate 768D CLIP embedding (ViT-L/14)
   ├─ Compute perceptual hashes (pHash, dHash, aHash)
   ├─ Delete temp file
   └─ Collect data for batch insert
   
5. Save to Database
   ├─ Batch insert (100 rows at a time)
   ├─ ON CONFLICT: Update existing submissions
   └─ Commit transaction
   
6. Cleanup
   └─ Remove temporary download directory
```

## Output Example

```
 Initializing Student Submission Seeder with ViT-L/14...
 GCS authentication successful
 Temp directory: /tmp/submission_images_abc123
 Initialized with ViT-L/14 (768D embeddings)
 Storage: PostgreSQL pgvector only (no FAISS)
 Hashes: pHash, dHash, aHash

============================================================
 STUDENT SUBMISSION SEEDER (ViT-L/14)
============================================================

 Validating XLSX file: submissions.xlsx
 XLSX validated: 500 rows
   Students: 150
   Assignments: 10
   Submissions: 500

 Checking database table...
 Table student_submissions ready

 Checking for existing submissions...
  Found 50 existing submissions (will skip)
 Remaining to process: 450 submissions

 Processing 450 submissions with ViT-L/14...
Processing submissions: 100%|████████████| 450/450

 Successfully processed 445/450 submissions
  Failed submissions (5): ['SUB-001', 'SUB-023', ...]

 Saving 445 submissions to database...
 Saved 445 submissions to student_submissions table

============================================================
 Seeding complete!
   Processed: 445/450
   Success rate: 98.9%
============================================================

 Cleaned up temp directory: /tmp/submission_images_abc123
```

## Error Handling

### Robust Error Recovery
-  **GCS Download Failures**: Skips submission, continues processing
-  **Image Corruption**: Validates before processing, skips invalid images
-  **Embedding Failures**: Logs error, skips submission
-  **Database Errors**: Rolls back transaction, preserves data integrity
-  **Duplicate submission_ids**: Uses ON CONFLICT to update existing records
-  **Temp File Cleanup**: Always removes downloaded files (even on errors)

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| `GCS authentication failed` | Missing credentials | Set `GOOGLE_APPLICATION_CREDENTIALS` |
| `Missing required columns` | XLSX format wrong | Check column names match exactly |
| `Blob does not exist` | Wrong GCS path | Verify path format and file exists |
| `Image validation failed` | Corrupted/invalid image | Check image file in GCS |
| `Database connection error` | PostgreSQL not running | Start PostgreSQL, check credentials |
| `duplicate key value violates unique constraint` | Same submission_id twice | Use `--skip-existing` or fix XLSX |

## Performance

### Processing Speed
- **Download**: ~1-2 seconds per image (depends on size and network)
- **CLIP Embedding**: ~0.5-1 second per image (CPU)
- **Hash Computation**: ~0.1 second per image
- **Database Insert**: Batched (100 rows), ~1 second per batch

**Estimated Time:**
- 100 submissions: ~3-5 minutes
- 500 submissions: ~15-25 minutes
- 1000 submissions: ~30-50 minutes

### Optimization Tips
1. **GPU Acceleration**: Modify `CLIPHandler` to use CUDA for 10x faster embeddings
2. **Parallel Downloads**: Add `ThreadPoolExecutor` for concurrent GCS downloads
3. **Larger Batches**: Increase `page_size=100` to 500 for faster inserts
4. **Skip Hash Computation**: Modify code to skip hashes if not needed (saves ~10% time)

## Validation Checklist

Before running the script, verify:
- [ ] XLSX file has all 4 required columns
- [ ] `submission_id` values are unique
- [ ] GCS paths are valid (gs:// or https://)
- [ ] GCS credentials are set
- [ ] PostgreSQL is running
- [ ] pgvector extension is installed (`CREATE EXTENSION vector;`)
- [ ] Sufficient disk space for temp downloads

## Querying Submissions

### Find Submissions by Student
```sql
SELECT submission_id, assignment_id, gcs_path, created_at
FROM student_submissions
WHERE student_id = 'STU-2024-001'
ORDER BY created_at DESC;
```

### Find Submissions by Assignment
```sql
SELECT student_id, submission_id, gcs_path
FROM student_submissions
WHERE assignment_id = 'ASSIGN-HW1';
```

### Similarity Search (Find Similar Submissions)
```sql
-- Find submissions similar to a specific submission
SELECT 
    s2.submission_id,
    s2.student_id,
    s2.assignment_id,
    1 - (s1.clip_embedding <=> s2.clip_embedding) AS similarity
FROM student_submissions s1
CROSS JOIN student_submissions s2
WHERE s1.submission_id = 'SUB-001'
  AND s2.submission_id != 'SUB-001'
ORDER BY s1.clip_embedding <=> s2.clip_embedding
LIMIT 10;
```

### Check Processing Statistics
```sql
-- Count submissions per student
SELECT student_id, COUNT(*) as submission_count
FROM student_submissions
GROUP BY student_id
ORDER BY submission_count DESC;

-- Count submissions per assignment
SELECT assignment_id, COUNT(*) as submission_count
FROM student_submissions
GROUP BY assignment_id
ORDER BY submission_count DESC;
```

## Environment Variables

```bash
# Required for GCS
GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"

# PostgreSQL connection (if not using defaults)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=plagiarism_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
```

## Security Best Practices

1. **GCS Permissions**: Use service account with read-only access
   - Only grant: `storage.objects.get`, `storage.objects.list`
   - Restrict to specific buckets

2. **Database Credentials**: Store in environment variables, not in code
   - Use `.env` file (don't commit to Git)
   - Or use secret management (GCP Secret Manager, AWS Secrets Manager)

3. **XLSX Files**: Don't commit to Git if containing sensitive data
   - Add `*.xlsx` to `.gitignore`
   - Use secure file transfer methods

4. **Temp Files**: Automatically cleaned up after processing
   - Files deleted immediately after processing
   - Directory removed on script exit

## Troubleshooting

### Enable Debug Logging
```python
# Add to top of seed_from_xlsx.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Test GCS Connection
```bash
# Test credentials
python -c "from google.cloud import storage; print(list(storage.Client().list_buckets(max_results=1)))"
```

### Test Database Connection
```bash
# Test PostgreSQL
psql -h localhost -U postgres -d plagiarism_db -c "SELECT 1;"
```

### Verify pgvector Extension
```sql
-- Check if pgvector is installed
SELECT * FROM pg_extension WHERE extname = 'vector';

-- If not installed
CREATE EXTENSION vector;
```

## Comparison: seed_ref_images.py vs seed_from_xlsx.py

| Feature | seed_ref_images.py | seed_from_xlsx.py |
|---------|-------------------|------------------|
| **Input** | Local image directory | XLSX file with GCS paths |
| **Table** | `reference_images` | `student_submissions` |
| **Unique ID** | `REF-{filename}` | `submission_id` (from XLSX) |
| **Storage** | pgvector + FAISS (optional) | pgvector only |
| **Metadata** | category, description | student_id, assignment_id |
| **Use Case** | Reference image library | Student submission tracking |

## Next Steps

After seeding, you can:
1. **Query Database**: Find submissions by student/assignment
2. **Similarity Search**: Detect similar submissions using pgvector
3. **Plagiarism Detection**: Compare submission embeddings
4. **Analytics**: Generate statistics on submissions
5. **Integration**: Use with FastAPI endpoints for real-time queries
