# Data Seeding Guide

Seed reference images and student submissions into the plagiarism detection database.

## Quick Start

```bash
# 1. Start services
./start-dev-env.sh

# 2. Seed reference images
./seeding/seed-data.sh --ref-images

# 3. (Optional) Seed submissions from Excel file
./seeding/seed-data.sh --submissions --xlsx data/submissions.xlsx
```

## Prerequisites

1. **Services Running**
   ```bash
   ./start-dev-env.sh
   ```
   This starts PostgreSQL and RabbitMQ.

2. **Python Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **CLIP Model** (Downloads automatically on first use)
   ```bash
   # Optional: Pre-download to avoid delay
   python scripts/download_clip_model.py
   ```

## Usage

### Basic Commands

```bash
# Seed reference images only
./seeding/seed-data.sh --ref-images

# Seed with custom directory
./seeding/seed-data.sh --ref-images --ref-dir /path/to/images

# Seed student submissions from Excel
./seeding/seed-data.sh --submissions --xlsx data/submissions.xlsx

# Seed both
./seeding/seed-data.sh --all --xlsx data/submissions.xlsx
```

### Advanced Options

```bash
# Skip specific backends (for faster seeding)
./seeding/seed-data.sh --ref-images --no-pgvector  # Skip pgvector
./seeding/seed-data.sh --ref-images --no-faiss     # Skip FAISS index
./seeding/seed-data.sh --ref-images --no-hashes    # Skip hash generation
```

**Note:** PowerShell version (`seed-data.ps1`) available for Windows users.

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--ref-images` | Seed reference images |
| `--submissions` | Seed student submissions from Excel |
| `--all` | Seed both reference images and submissions |
| `--xlsx FILE` | Path to Excel file (required for submissions) |
| `--ref-dir DIR` | Custom reference images directory (default: `./data/reference_images`) |
| `--no-pgvector` | Skip pgvector storage |
| `--no-faiss` | Skip FAISS index creation |
| `--no-hashes` | Skip hash generation |
## Command-Line Options

| Option | Description |
|--------|-------------|
| `--ref-images` | Seed reference images |
| `--submissions` | Seed student submissions from Excel |
| `--all` | Seed both reference images and submissions |
| `--xlsx FILE` | Path to Excel file (required for submissions) |
| `--ref-dir DIR` | Custom reference images directory (default: `./data/reference_images`) |
| `--no-pgvector` | Skip pgvector storage |
| `--no-faiss` | Skip FAISS index creation |
| `--no-hashes` | Skip hash generation |

## Data Structure

### Reference Images Directory

Organize images by assignment:

```
data/reference_images/
├── assignment1/
│   ├── image1.jpg
│   ├── image2.png
│   └── image3.jpg
├── assignment2/
│   └── diagram.png
└── assignment3/
    └── screenshot.jpg
```

### XLSX File Format

The Excel file for student submissions should have columns:
- `submission_id`: Unique submission identifier
- `student_id`: Student identifier
- `assignment_id`: Assignment identifier
- `image_url`: URL or path to submission image
- (Additional columns as defined in `seed_from_xlsx.py`)

## What Gets Seeded

### Reference Images (`--ref-images`)

1. **Database Records**: Images stored in `reference_images` table
2. **CLIP Embeddings**: 768-D vector embeddings (ViT-L/14) in pgvector and/or FAISS
3. **Perceptual Hashes**: pHash, dHash, aHash for similarity detection
4. **FAISS Index**: Local index file at `./data/faiss_index.bin`
5. **Metadata**: JSON metadata at `./data/faiss_metadata.json`

### Student Submissions (`--submissions`)

1. **Database Records**: Submissions stored in `submissions` table
2. **CLIP Embeddings**: 768-D vector embeddings for semantic similarity
3. **Perceptual Hashes**: Image hashes for duplicate detection

## Troubleshooting

### Database Connection Failed

```bash
ERROR: Cannot connect to database
```

**Solution**: Start the database first
```bash
./start-dev-env.sh
```

### Reference Images Directory Not Found

```bash
ERROR: Reference images directory not found: ./data/reference_images
```

**Solution**: Create the directory and add images
```bash
mkdir -p data/reference_images/assignment1
# Add your images to the directory
```

### XLSX File Not Found

```bash
ERROR: XLSX file not found: data/submissions.xlsx
```

**Solution**: Provide the correct path to your Excel file
```bash
./seeding/seed-data.sh --submissions --xlsx /correct/path/submissions.xlsx
```

### CLIP Model Not Found

```bash
ERROR: CLIP model not found
```

**Solution**: Download the model first
```bash
python scripts/download_clip_model.py
```

## Examples

### Quick Start - Seed Test Data

```bash
# 1. Start the database
./start-dev-env.sh

# 2. Download CLIP model (one-time setup)
python scripts/download_clip_model.py

# 3. Create test reference images
mkdir -p data/reference_images/test_assignment
cp /path/to/test/images/*.jpg data/reference_images/test_assignment/

# 4. Seed reference images
./seeding/seed-data.sh --ref-images

# 5. Seed submissions (if you have XLSX file)
./seeding/seed-data.sh --submissions --xlsx data/test_submissions.xlsx
```

### Production Seeding

```bash
# Seed all data with all backends
./seeding/seed-data.sh --all \
  --ref-dir /production/reference_images \
  --xlsx /production/submissions.xlsx
```

### Development - Minimal Setup

```bash
# Seed only with perceptual hashes (faster, no ML models)
./seeding/seed-data.sh --ref-images --no-pgvector --no-faiss
```

## Next Steps

After seeding data:

1. **Start the Application**
   ```bash
   python app.py
   ```

2. **Test Plagiarism Detection**
   - Submit images through RabbitMQ
   - Check results in PostgreSQL database

## Related Scripts

- `seeding/seed_ref_images.py` - Reference images seeder (called by orchestrator)
- `seeding/seed_from_xlsx.py` - Student submissions seeder (called by orchestrator)
- `start-dev-env.sh` - Environment setup script
- `scripts/download_clip_model.py` - CLIP model downloader

## Architecture

```
seeding/seed-data.sh (Orchestrator)
    ├── Load .env variables
    ├── Check database connection
    ├── Call seeding/seed_ref_images.py
    │   ├── CLIPHandler: Generate 768D embeddings (ViT-L/14)
    │   ├── HashHandler: Compute perceptual hashes
    │   ├── FAISSHandler: Build FAISS index
    │   └── PostgreSQL: Store vectors with pgvector
    └── Call seeding/seed_from_xlsx.py
        ├── Parse Excel file
        ├── CLIPHandler: Generate 768D embeddings
        ├── HashHandler: Compute hashes
        └── PostgreSQL: Store submission records
```
