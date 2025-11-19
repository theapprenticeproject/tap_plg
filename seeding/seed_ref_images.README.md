# Reference Image Seeder - Usage Guide 
 ------
# Current this script expects images to be present in a folder in the below specified path , in later release this script accepts the xlsv sheet and generate embeddings/hahses (under development)
------
## Overview
Seeds reference images into the plagiarism detection system using **ViT-L/14** CLIP model (768D embeddings).

## Quick Start

```bash
# Basic usage (pgvector + FAISS + hashes)
python seed_ref_images.py --images-dir /path/to/reference_images

# Only pgvector storage
python seed_ref_images.py --images-dir /path/to/images --no-faiss

# Only FAISS index
python seed_ref_images.py --images-dir /path/to/images --no-pgvector

# Skip hash computation for faster processing
python seed_ref_images.py --images-dir /path/to/images --no-hashes
```

## Directory Structure

```
project/
├── utils/
│   ├── seed_ref_images.py
│   ├── clip_handler.py
│   ├── hash_handler.py
│   └── faiss_handler.py
├── data/                          # Auto-created
│   ├── faiss_index.bin           # Generated FAISS index
│   └── faiss_metadata.json       # FAISS metadata
└── reference_images/              # Your images folder
    ├── category1/
    │   ├── image1.jpg
    │   └── image2.png
    └── category2/
        └── image3.jpg
```

**Note:** Images directory can be anywhere, just provide the full path with `--images-dir`

## Command-Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--images-dir` | **Required** | Path to directory containing reference images |
| `--use-pgvector` | `True` | Store 768D embeddings in PostgreSQL |
| `--no-pgvector` | - | Skip PostgreSQL storage |
| `--use-faiss` | `True` | Build FAISS index file |
| `--no-faiss` | - | Skip FAISS index building |
| `--compute-hashes` | `True` | Compute perceptual hashes (pHash, dHash, aHash) |
| `--no-hashes` | - | Skip hash computation |

## Supported Image Formats
- `.jpg`, `.jpeg`
- `.png`
- `.bmp`
- `.webp`

## What Gets Generated

### 1. PostgreSQL Database (if `--use-pgvector`)
- Stores in `reference_images` table
- Includes:
  - Reference ID: `REF-{filename}`
  - Image path
  - Perceptual hashes (pHash, dHash, aHash)
  - 768D CLIP embedding (pgvector)
  - Metadata (category, description)

### 2. FAISS Index (if `--use-faiss`)
- `data/faiss_index.bin` - Binary index file
- `data/faiss_metadata.json` - Associated metadata

### 3. Perceptual Hashes (if `--compute-hashes`)
- **pHash** - Perceptual hash
- **dHash** - Difference hash  
- **aHash** - Average hash

## Environment Variables

Required when using `--use-pgvector`:
```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=plagiarism_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
```

## Processing Details

**CLIP Model:** ViT-L/14 (laion2B-s32B-b82K)  
**Embedding Dimension:** 768D  
**Device:** CPU (configurable in code)  
**Download Source:** HuggingFace Hub (automatic, ~3.5GB)

## Examples

### Full Pipeline (Production)
```bash
python seed_ref_images.py --images-dir ./reference_images
```
**Result:** Stores in both PostgreSQL + FAISS, computes all hashes

### Fast Prototyping (FAISS Only)
```bash
python seed_ref_images.py --images-dir ./test_images --no-pgvector --no-hashes
```
**Result:** Only builds FAISS index, skips database and hash computation

### Database Only (No FAISS)
```bash
python seed_ref_images.py --images-dir ./images --no-faiss
```
**Result:** Stores everything in PostgreSQL, no FAISS index file

## Output Example

```
 Initializing Reference Image Seeder with ViT-L/14...
 Storage mode: pgvector=True, FAISS=True
 Compute hashes: True

 Scanning directory: ./reference_images
 Found 150 images

 Processing 150 images with ViT-L/14...
Processing images: 100%|████████████| 150/150

 Successfully processed 150 images

 Building ViT-L/14 FAISS index...
Embedding shape: (150, 768)
 FAISS index saved: ./data/faiss_index.bin
 Metadata saved: ./data/faiss_metadata.json

 Saving 150 records to reference_images table...
 Saved 150 records to reference_images
 Embeddings stored in pgvector: True

============================================================
 Successfully seeded 150 images with ViT-L/14!
============================================================
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Directory not found` | Check path with `--images-dir`, use absolute path |
| `Database connection error` | Verify PostgreSQL is running and credentials in `.env` |
| `At least one storage method must be enabled` | Cannot use both `--no-pgvector` and `--no-faiss` |
| `No images found` | Check image formats and directory structure |

## Performance Tips

- **Skip hashes** (`--no-hashes`) for 20-30% faster processing
- **Use FAISS only** (`--no-pgvector`) for offline testing
- Images are processed sequentially (add multiprocessing for speed)
- First run downloads ~3.5GB CLIP model (cached afterward)

## Database Schema

```sql
CREATE TABLE reference_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_id VARCHAR(100) UNIQUE NOT NULL,
    image_path TEXT NOT NULL,
    phash VARCHAR(64),
    dhash VARCHAR(64),
    ahash VARCHAR(64),
    category VARCHAR(100),
    description TEXT,
    source VARCHAR(200),
    faiss_index_position INTEGER,
    clip_embedding_generated BOOLEAN DEFAULT FALSE,
    clip_embedding vector(768),  -- pgvector
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```
