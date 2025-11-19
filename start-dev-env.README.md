# Local Development Setup Scripts - Quick Guide

## Overview
Automated scripts to set up local development environment for MentorMe Plagiarism Detection System.

---

## Files
- `start-dev-env.sh` - Bash script (Linux/macOS/Git Bash)
- `start-dev-env.ps1` - PowerShell script (Windows)

---

## Quick Start

### **Option 1: Complete Setup (Recommended)** 
Everything in one command - infrastructure + Python environment + dependencies:

```bash
# Linux/macOS/Git Bash
chmod +x start-dev-env.sh
./start-dev-env.sh --full-setup

# Windows PowerShell
.\start-dev-env.ps1 --full-setup
```

**What it does:**
- Creates PostgreSQL container (port 5432)
- Creates RabbitMQ container (ports 5672, 15672)
- Initializes database schema
- Creates `.env` configuration file
- Creates Python virtual environment
- Installs all dependencies (~5-10 minutes)
- Downloads CLIP model from HuggingFace (~3.5GB)
- Verifies setup

**Time:** ~10-15 minutes (first run)

---

### **Option 2: Infrastructure Only** (Default)
Just containers + database, manual Python setup:

```bash
# Linux/macOS/Git Bash
./start-dev-env.sh

# Windows PowerShell
.\start-dev-env.ps1
```

**What it does:**
- Creates PostgreSQL + RabbitMQ containers
- Initializes database
- Creates `.env` file

**Then manually:**
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\Activate.ps1  # Windows

pip install -r requirements.txt
```

---

### **Option 3: With Wheelhouse** (Offline Installs)
Pre-compile dependencies for faster/offline installs:

```bash
# Linux/macOS/Git Bash
./start-dev-env.sh --build-wheelhouse

# Then install offline:
pip install --no-index --find-links=wheelhouse -r requirements.txt
```

---

## Available Flags

| Flag | Description |
|------|-------------|
| `--full-setup` | Complete setup: infrastructure + Python + dependencies |
| `--build-wheelhouse` | Build wheelhouse for offline dependency installation |
| (no flags) | Infrastructure only (containers + database) |

---

## What Gets Created

### **Infrastructure**
| Service | Port | Access | Credentials |
|---------|------|--------|-------------|
| PostgreSQL | 5432 | localhost:5432 | postgres/postgres |
| RabbitMQ (AMQP) | 5672 | localhost:5672 | admin/admin123 |
| RabbitMQ (Management UI) | 15672 | http://localhost:15672 | guest/guest |

### **Files**
- `.env` - Environment configuration (from `.env.example`)
- `venv/` - Python virtual environment (if `--full-setup`)
- `data/` - Data directories (reference_images, temp_images)
- `models/` - Model cache directory
- `logs/` - Application logs directory

### **Database**
- Database: `plagiarism_db`
- Tables: `submissions`, `reference_images`, `feedback_logs`
- Extension: pgvector
- Indexes: B-tree, HNSW vector indexes

---

## After Setup

### **Start the Application**

**Terminal 1 - Worker:**
```bash
source venv/bin/activate  # Linux/macOS
# OR
.\venv\Scripts\Activate.ps1  # Windows

python app.py
```

**Terminal 2 - API Server:**
```bash
source venv/bin/activate

uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

**Access API:** http://localhost:8000/docs

---

## Prerequisites

### **Required**
- **Podman** (or Docker) - Container runtime
- **Python 3.10+** - Application runtime
- **8GB+ RAM** - For CLIP model
- **10GB+ disk** - For dependencies and models

### **Optional**
- **CUDA GPU** - For faster CLIP inference (10x speedup)
- **curl** - For health checks

---

## Troubleshooting

### **"Podman not found"**
```bash
# Install Podman: https://podman.io/getting-started/installation
```

### **"Python not found"**
```bash
# Install Python 3.10+: https://www.python.org/downloads/
```

### **"Port already in use"**
```bash
# Stop existing containers
podman stop mentorme-postgres mentorme-rabbitmq
podman rm mentorme-postgres mentorme-rabbitmq

# Or change ports in script (POSTGRES_PORT, RABBITMQ_PORT)
```

### **"Database connection failed"**
```bash
# Check PostgreSQL is running
podman ps | grep mentorme-postgres

# Check logs
podman logs mentorme-postgres

# Restart container
podman restart mentorme-postgres
```

### **"RabbitMQ not ready"**
```bash
# Check RabbitMQ is running
podman ps | grep mentorme-rabbitmq

# Access management UI
open http://localhost:15672  # guest/guest

# Restart container
podman restart mentorme-rabbitmq
```

---

## Container Management

### **View Logs**
```bash
podman logs mentorme-postgres
podman logs mentorme-rabbitmq
podman logs -f mentorme-postgres  # Follow mode
```

### **Stop Containers**
```bash
podman stop mentorme-postgres mentorme-rabbitmq
```

### **Remove Containers**
```bash
podman rm mentorme-postgres mentorme-rabbitmq
```

### **Restart Containers**
```bash
podman restart mentorme-postgres mentorme-rabbitmq
```

### **Check Running Containers**
```bash
podman ps
```

---

## Configuration Override

### **Edit `.env` After Creation**
Script creates `.env` from `.env.example` with localhost overrides. You can modify:

```bash
# Example: Use different CLIP model
CLIP_MODEL=ViT-B/32  # Smaller, faster model (512D)

# Example: Enable GPU
CLIP_DEVICE=cuda

# Example: Enable pgvector instead of FAISS
USE_PGVECTOR=true
```

### **Environment Variables Priority**
1. System environment variables (highest)
2. `.env` file
3. `config.py` defaults (lowest)

---

## What This Script Does NOT Do

 **Does not start the application** - You must run `python app.py` and `uvicorn api:app`  
 **Does not seed reference images** - Use `./seeding/seed-data.sh` or `python seeding/seed_ref_images.py`  
 **Does not expose port 8000** - Only exposed when API is running  
 **Does not use Docker Compose** - Uses Podman containers directly  

---

## Comparison: Script vs Docker Compose

| Feature | This Script | Docker Compose |
|---------|-------------|----------------|
| **Tool** | Podman | Docker |
| **Python App** | Runs on host | Runs in container |
| **Development** |  Faster (direct edits) |  Requires rebuild |
| **Debugging** |  Native debugger |  Remote debugging |
| **Production** |  Not recommended |  Best practice |
| **Dependencies** | Installed on host | Isolated in container |

---

## Examples

### **First-Time Setup**
```bash
# Complete automated setup
./start-dev-env.sh --full-setup

# Start worker
source venv/bin/activate
python app.py

# In another terminal, start API
source venv/bin/activate
uvicorn api:app --host 0.0.0.0 --port 8000
```

### **Daily Development**
```bash
# Containers already exist, just start them
podman start mentorme-postgres mentorme-rabbitmq

# Activate venv and run
source venv/bin/activate
python app.py
```

### **Clean Restart**
```bash
# Stop and remove everything
podman stop mentorme-postgres mentorme-rabbitmq
podman rm mentorme-postgres mentorme-rabbitmq

# Run script again
./start-dev-env.sh --full-setup
```

---

## Next Steps After Setup

1. **(Optional) Seed reference images:**
   ```bash
   ./seeding/seed-data.sh --ref-images
   # Or directly: python seeding/seed_ref_images.py --directory data/reference_images
   ```

2. **Test the system:**
   ```bash
   python tests/simulation_e2e.py --vm-ip localhost \
     --image https://example.com/test.jpg \
     --student-id ST001 --assign-id A001
   ```

3. **Access API documentation:**
   - OpenAPI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

4. **Monitor queues:**
   - RabbitMQ UI: http://localhost:15672

---

## Support

- **Documentation:** See `DOCUMENTATION.md` for complete system documentation
- **Issues:** Check logs in `logs/` directory
- **Database:** Connect with any PostgreSQL client to `localhost:5432`

---

**Last Updated:** November 6, 2025  
**Version:** 1.0.0
