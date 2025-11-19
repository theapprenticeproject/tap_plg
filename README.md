# MentorMe - Image Plagiarism Detection System

Real-time plagiarism detection for student image submissions using perceptual hashing, CLIP embeddings, and vector search.

## Features

- Perceptual hashing (pHash, dHash, aHash) for fast duplicate detection
- CLIP embeddings for semantic similarity
- Vector search with FAISS or pgvector
- AI-generated image detection (DALL-E, Midjourney, Stable Diffusion)
- Peer and self-plagiarism checking
- Async processing with RabbitMQ
- Optional student ID hashing for privacy

## Quick Start

### 1. Start Services

```bash
./start-dev-env.sh
```

This starts PostgreSQL and RabbitMQ containers using Podman and creates a `.env` file with default settings.

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run Application

```bash
python app.py
```

The application will:
- Connect to PostgreSQL and RabbitMQ
- Start listening for plagiarism check submissions
- Process images and store results in the database

## Configuration

Configuration is managed via `.env` file (auto-created by start script).

### Essential Settings

```env
# Database Connection
POSTGRES_USER=plagiarism_user
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=plagiarism_db
POSTGRES_HOST=postgres  # Use 'localhost' for local development

# Message Queue
RABBITMQ_HOST=rabbitmq  # Use 'localhost' for local development
RABBITMQ_USER=admin
RABBITMQ_PASS=admin123
```

### Detection Thresholds

```env
# Hash matching (lower = stricter)
HASH_MATCH_THRESHOLD=8  # Hamming distance

# Semantic similarity (higher = stricter)
SEMANTIC_MATCH_THRESHOLD=0.80  # 0.0 to 1.0

# Self-plagiarism grace period
RESUBMISSION_WINDOW_DAYS=14  # Days
```

### Vector Search Backend

```env
# Choose between FAISS (in-memory) or pgvector (database)
USE_PGVECTOR=false  # Set to 'true' for pgvector
```

See `.env.example` for all available options.

## Testing

### Run All Tests

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov --cov-report=html
```

### Test Status

- **Total**: 384 tests
- **Passing**: 364 (94.8%)
- **Skipped**: 20 (DB manager mocks - covered by integration tests)
- **Failing**: 0
- **Execution Time**: ~7 minutes

**Coverage by Component:**
- ✅ Integration tests: 11/11 (end-to-end workflows)
- ✅ Hash handlers: Complete coverage
- ✅ CLIP embeddings: 35/38 (3 skipped - validation tests)
- ✅ AI detection: 15/15
- ✅ FAISS handler: 22/22
- ✅ Image validator: 18/18

## Project Structure

```
mentorme/
├── app.py                      # Main application entry
├── api/
│   └── api.py                 # FastAPI REST endpoints
├── config/
│   └── config.py              # Configuration management
├── database/
│   ├── db_manager.py          # Database operations
│   ├── init.sql               # Schema definition
│   └── dumps/                 # Database backups
├── image_worker/
│   ├── worker.py              # Core detection engine
│   ├── clip_handler.py        # CLIP embeddings (768D)
│   ├── hash_handler.py        # Perceptual hashing
│   ├── ai_generated_detector.py  # AI detection
│   ├── image_validator.py     # Image validation
│   ├── faiss_handler.py       # FAISS vector backend
│   └── pgvector_handler.py    # pgvector backend
├── mq/
│   └── rmq_client.py          # RabbitMQ client
├── plag_checker/
│   ├── submissions_checker.py # Message orchestrator
│   └── submission_status.py   # Status tracking
├── processors/
│   ├── base_processor.py      # Base processor class
│   ├── image_processor.py     # Image processing
│   └── text_processor.py      # Text processing
├── scripts/
│   ├── dump_database.sh       # Database backup
│   ├── restore_database.sh    # Database restore
│   └── download_clip_model.py # CLIP model downloader
├── seeding/
│   ├── seed_ref_images.py     # Reference image indexing
│   └── seed_from_xlsx.py      # Bulk submission seeding
├── utils/
│   ├── security.py            # Student ID hashing
│   └── exceptions.py          # Custom exceptions
└── tests/                      # Test suite (384 tests)
```

## How It Works

1. **Hash Check**: Compares perceptual hashes (Hamming distance)
2. **CLIP Check**: Generates 768D embedding (ViT-L/14), searches vector index
3. **AI Detection**: Checks metadata and statistical patterns
4. **Result**: Returns plagiarism status with confidence score

Priority: Peer > Reference > Self (resubmission) > Original

## Container Management

```bash
# Check status
podman ps

# View logs
podman logs mentorme-postgres
podman logs mentorme-rabbitmq

# Stop services
podman stop mentorme-postgres mentorme-rabbitmq

# Restart services
./start-dev-env.sh
```

## Monitoring

**RabbitMQ Management UI:**
- URL: http://localhost:15672
- Login: admin/admin123

**Database Stats:**
```sql
-- Total submissions
SELECT COUNT(*) FROM submissions;

-- Plagiarism rate
SELECT 
  COUNT(*) FILTER (WHERE is_plagiarized = true) * 100.0 / COUNT(*) AS plagiarism_rate
FROM submissions;
```

## Troubleshooting

**RabbitMQ Connection Issues:**
```bash
podman restart mentorme-rabbitmq
podman logs mentorme-rabbitmq
```

**PostgreSQL Connection Issues:**
```bash
podman restart mentorme-postgres
podman exec mentorme-postgres pg_isready -U plagiarism_user
```

**Test Failures:**
```bash
pip install -r requirements-test.txt --upgrade
pytest tests/ -vv --tb=short
```

## Documentation

- **[DOCUMENTATION.md](docs/DOCUMENTATION.md)** - Complete technical documentation
- **[DATABASE_DUMPS.md](docs/DATABASE_DUMPS.md)** - Database backup/restore guide
- **[Seeding README](seeding/README.md)** - Data seeding instructions
- **[Copilot Instructions](.github/copilot-instructions.md)** - Development guidelines

## License

MIT License

## Acknowledgments

- OpenCLIP - Image embeddings
- FAISS - Vector search
- imagehash - Perceptual hashing
- asyncpg, psycopg3 - PostgreSQL drivers
- aio-pika - RabbitMQ client
# tap_plg
