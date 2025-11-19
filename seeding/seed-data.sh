#!/usr/bin/env bash
# Data Seeding Script
# Seeds reference images and student submissions into the plagiarism detection system

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'

# Detect Python executable with asyncpg installed
PY=""
for pycmd in python python3 "py -3"; do
    if command -v $(echo $pycmd | awk '{print $1}') &> /dev/null; then
        if $pycmd -c "import asyncpg" &> /dev/null; then
            PY="$pycmd"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo -e "${RED}ERROR: Python with asyncpg not found${NC}"
    echo -e "${YELLOW}Install asyncpg: pip install asyncpg${NC}"
    exit 1
fi

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    set -a
    source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
    set +a
fi

# Default values
SEED_REF_IMAGES=1
SEED_SUBMISSIONS=0
USE_PGVECTOR=1
USE_FAISS=0
COMPUTE_HASHES=1
REF_IMAGES_DIR="../data/reference_images"
XLSX_FILE=""
LIMIT=""

# Parse command line arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --ref-images) SEED_REF_IMAGES=1; shift ;;
        --submissions) SEED_SUBMISSIONS=1; shift ;;
        --all) SEED_REF_IMAGES=1; SEED_SUBMISSIONS=1; shift ;;
        --no-pgvector) USE_PGVECTOR=0; shift ;;
        --no-faiss) USE_FAISS=0; shift ;;
        --no-hashes) COMPUTE_HASHES=0; shift ;;
        --ref-dir) REF_IMAGES_DIR="$2"; shift 2 ;;
        --xlsx) XLSX_FILE="$2"; shift 2 ;;
        --limit) LIMIT="$2"; shift 2 ;;
        --help) 
            echo -e "${CYAN}Usage: ./seeding/seed-data.sh [OPTIONS]${NC}"
            echo ""
            echo "Options:"
            echo "  --ref-images       Seed reference images"
            echo "  --submissions      Seed student submissions from XLSX"
            echo "  --all              Seed both reference images and submissions"
            echo "  --no-pgvector      Skip PostgreSQL pgvector storage"
            echo "  --no-faiss         Skip FAISS index creation"
            echo "  --no-hashes        Skip perceptual hash computation"
            echo "  --ref-dir DIR      Reference images directory (default: ./data/reference_images)"
            echo "  --xlsx FILE        XLSX file for submissions"
            echo "  --limit N          Process only N images (for testing, e.g., --limit 10)"
            echo "  --help             Show this help message"
            echo ""
            echo "Examples:"
            echo "  ${YELLOW}./seeding/seed-data.sh --ref-images${NC}"
            echo "  ${YELLOW}./seeding/seed-data.sh --ref-images --limit 10${NC}  ${GRAY}# Test with 10 images${NC}"
            echo "  ${YELLOW}./seeding/seed-data.sh --submissions --xlsx data/submissions.xlsx${NC}"
            echo "  ${YELLOW}./seeding/seed-data.sh --all${NC}"
            exit 0
            ;;
        *) 
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate that at least one action is specified
if [ "$SEED_REF_IMAGES" -eq 0 ] && [ "$SEED_SUBMISSIONS" -eq 0 ]; then
    echo -e "${RED}ERROR: No action specified. Use --ref-images, --submissions, or --all${NC}"
    echo "Use --help for usage information"
    exit 1
fi

echo -e "${CYAN}=================================================================="
echo -e "  MentorMe Plagiarism Checker - Data Seeding"
echo -e "==================================================================${NC}"
echo ""

# Seed reference images
if [ "$SEED_REF_IMAGES" -eq 1 ]; then
    echo -e "${CYAN}=================================================================="
    echo -e "  Seeding Reference Images"
    echo -e "==================================================================${NC}"
    echo ""
    
    if [ ! -d "$REF_IMAGES_DIR" ]; then
        echo -e "${RED}ERROR: Reference images directory not found: $REF_IMAGES_DIR${NC}"
        exit 1
    fi
    
    # Build command arguments
    CMD="$PY seed_ref_images.py --images-dir $REF_IMAGES_DIR"
    
    if [ "$USE_PGVECTOR" -eq 0 ]; then
        CMD="$CMD --no-pgvector"
    else
        CMD="$CMD --use-pgvector"
    fi
    
    if [ "$USE_FAISS" -eq 0 ]; then
        CMD="$CMD --no-faiss"
    else
        CMD="$CMD --use-faiss"
    fi
    
    if [ "$COMPUTE_HASHES" -eq 0 ]; then
        CMD="$CMD --no-hashes"
    else
        CMD="$CMD --compute-hashes"
    fi
    
    if [ -n "$LIMIT" ]; then
        CMD="$CMD --limit $LIMIT"
    fi
    
    echo -e "${YELLOW}Running: $CMD${NC}"
    echo ""
    
    eval $CMD
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}[OK] Reference images seeded successfully${NC}"
    else
        echo ""
        echo -e "${RED}ERROR: Failed to seed reference images${NC}"
        exit 1
    fi
fi
# Seed student submissions
if [ "$SEED_SUBMISSIONS" -eq 1 ]; then
    echo -e "${CYAN}=================================================================="
    echo -e "  Seeding Student Submissions"
    echo -e "==================================================================${NC}"
    echo ""
    
    if [ -z "$XLSX_FILE" ]; then
        echo -e "${RED}ERROR: XLSX file not specified. Use --xlsx FILE${NC}"
        exit 1
    fi
    
    if [ ! -f "$XLSX_FILE" ]; then
        echo -e "${RED}ERROR: XLSX file not found: $XLSX_FILE${NC}"
        exit 1
    fi
    
    CMD="$PY seed_from_xlsx.py --xlsx $XLSX_FILE"
    
    echo -e "${YELLOW}Running: $CMD${NC}"
    echo ""
    
    eval $CMD
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}[OK] Student submissions seeded successfully${NC}"
    else
        echo ""
        echo -e "${RED}ERROR: Failed to seed student submissions${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${CYAN}=================================================================="
echo -e "  Seeding Complete!"
echo -e "==================================================================${NC}"
echo ""
echo -e "${GREEN}✓ Data seeding completed successfully${NC}"
echo ""
echo -e "${CYAN}Next Steps:${NC}"
echo -e "  ${YELLOW}./start-dev-env.sh --with-api${NC}  ${GRAY}# Start the application${NC}"
echo ""
