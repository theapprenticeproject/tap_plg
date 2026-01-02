#!/usr/bin/env bash
# Local Development Startup Script
# Starts PostgreSQL and RabbitMQ containers using docker-compose

set -e
FULL_SETUP=0
START_API=0
COMPOSE_FILE="docker-compose-prod.yml"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --full-setup) FULL_SETUP=1; shift ;;
        --with-api) START_API=1; shift ;;
        --prod) COMPOSE_FILE="docker-compose-prod.yml"; shift ;;
        --dev) COMPOSE_FILE="docker-compose-dev.yml"; shift ;;
        *) break ;;
    esac
done

# Detect platform
OS_TYPE="unknown"
UNAME_OUT=$(uname -s 2>/dev/null || true)
case "${UNAME_OUT}" in
  MINGW*|MSYS*|CYGWIN*) OS_TYPE="windows-msys" ;;
  Darwin) OS_TYPE="macos" ;;
  Linux) OS_TYPE="linux" ;;
  *) OS_TYPE="unix" ;;
esac

# Detect Python executable
PY=""
if [ "${OS_TYPE}" = "windows-msys" ]; then
    PY_CANDIDATES=("py" "python3" "python" "python.exe")
else
    PY_CANDIDATES=("python3" "python" "py" "python.exe")
fi

for candidate in "${PY_CANDIDATES[@]}"; do
    if [ "$candidate" = "py" ]; then
        if command -v py >/dev/null 2>&1; then
            if py -3 -c "import sys; sys.stdout.write('Python found!!\n')" 2>/dev/null; then
                PY='py -3'
                break
            fi
        fi
        continue
    fi

    candidate_path=$(command -v "$candidate" 2>/dev/null || true)
    if [ -n "$candidate_path" ]; then
        case "$candidate_path" in
            *WindowsApps*|*windowsapps*) continue ;;
        esac

        if "$candidate" -c "import sys; sys.stdout.write('ok')" 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "ERROR: No Python 3.10+ found. Install Python or ensure it's in PATH." >&2
    exit 1
fi

# Detect container runtime (Podman or Docker)
CONTAINER_CMD=""
COMPOSE_CMD=""
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
    if command -v podman-compose &> /dev/null; then
        COMPOSE_CMD="podman-compose"
    else
        echo "ERROR: podman-compose not found. Install it:" >&2
        echo "  pip install podman-compose" >&2
        exit 1
    fi
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    elif docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    else
        echo "ERROR: docker-compose not found. Install it:" >&2
        echo "  https://docs.docker.com/compose/install/" >&2
        exit 1
    fi
else
    echo "ERROR: Neither Podman nor Docker found. Install one of them:" >&2
    echo "  Podman: https://podman.io/getting-started/installation" >&2
    echo "  Docker: https://docs.docker.com/get-docker/" >&2
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'

echo -e "${CYAN}=================================================================="
echo -e "  Plagiarism Checker - PROD Development Setup"
echo -e "  Container Runtime: ${CONTAINER_CMD}"
echo -e "  Compose File: ${COMPOSE_FILE}"
echo -e "==================================================================${NC}"
echo ""

# Validate compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}ERROR: $COMPOSE_FILE not found${NC}"
    exit 1
fi

# Load configuration from .env if it exists
if [ -f ".env" ]; then
    set -a
    source <(grep -v '^#' .env | grep -v '^$' | sed 's/\r$//')
    set +a
fi

# Configuration (with defaults)
POSTGRES_CONTAINER="plg-postgres"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-plagiarism_db}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
CLIP_MODEL_URL="${CLIP_MODEL_URL:-https://huggingface.co/laion/CLIP-ViT-L-14-laion2B-s32B-b82K/resolve/main/open_clip_pytorch_model.bin}"

stop_existing_containers() {
    local containers_exist=false
    
    # Check if compose stack is running
    if $COMPOSE_CMD -f $COMPOSE_FILE ps 2>/dev/null | grep -q "Up\|running"; then
        containers_exist=true
    fi
    
    if [ "$containers_exist" = true ]; then
        echo -e "${YELLOW}Existing containers found:${NC}"
        $COMPOSE_CMD -f $COMPOSE_FILE ps
        echo ""
        echo -e "${YELLOW}This will stop and remove existing containers.${NC}"
        read -p "Continue? (y/N): " -n 1 -r
        echo
        
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${RED}Aborted by user${NC}"
            # exit 0
        else
            echo -e "${CYAN}Stopping existing containers...${NC}"
            $COMPOSE_CMD -f $COMPOSE_FILE down
        fi   
    fi
    
    echo -e "${GREEN}[OK] Ready to start containers${NC}"
}

start_containers() {
    echo -e "${CYAN}Starting containers with $COMPOSE_FILE...${NC}"
    
    # Determine which services to start
    #local services="postgres rabbitmq pgadmin plagiarism-checker"
    local services="postgres plagiarism-checker"
    
    if [ "$START_API" -eq 1 ]; then
        services="$services api"
        echo -e "${CYAN}Including API service${NC}"
        
        # Force rebuild API container to ensure it uses Dockerfile.api (not Dockerfile)
        echo -e "${YELLOW}Rebuilding API container with Dockerfile.api...${NC}"
        $COMPOSE_CMD -f $COMPOSE_FILE build --no-cache api
        
        if [ $? -ne 0 ]; then
            echo -e "${RED}ERROR: Failed to build API container${NC}"
            exit 1
        fi
        echo -e "${GREEN}[OK] API container rebuilt${NC}"
    fi
    
    $COMPOSE_CMD -f $COMPOSE_FILE up -d $services
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}ERROR: Failed to start containers${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}[OK] Containers started${NC}"
}

wait_for_postgres() {
    echo -e "${YELLOW}Waiting for PostgreSQL...${NC}"
    
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        
        if $CONTAINER_CMD exec $POSTGRES_CONTAINER pg_isready -U $POSTGRES_USER &>/dev/null; then
            echo -e "${GREEN}[OK] PostgreSQL ready${NC}"
            return 0
        fi
        
        sleep 2
    done
    
    echo -e "${RED}ERROR: PostgreSQL timeout${NC}"
    exit 1
}


wait_for_api() {
    if [ "$START_API" -ne 1 ]; then
        return 0
    fi
    
    echo -e "${YELLOW}Waiting for API service...${NC}"
    
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        
        if curl -s -f http://localhost:8000/health &>/dev/null; then
            echo -e "${GREEN}[OK] API service ready${NC}"
            return 0
        fi
        
        sleep 2
    done
    
    echo -e "${RED}ERROR: API service timeout${NC}"
    echo -e "${YELLOW}Checking API container logs:${NC}"
    $COMPOSE_CMD -f $COMPOSE_FILE logs --tail=50 api
    exit 1
}

initialize_database() {
    if [ ! -f "database/init.sql" ]; then
        echo -e "${YELLOW}WARNING: database/init.sql not found${NC}"
        return
    fi
    
    echo -e "${CYAN}Initializing database...${NC}"
    
    # Run init.sql
    if $CONTAINER_CMD exec -i $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB < database/init.sql 2>/dev/null; then
        echo -e "${GREEN}[OK] Database schema initialized${NC}"
    else
        echo -e "${GRAY}Database schema already exists${NC}"
    fi
    
    # Create migrations tracking table if it doesn't exist
    $CONTAINER_CMD exec $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            migration_name VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT NOW()
        );
    " 2>/dev/null
    
    # Run migration scripts
    if [ -d "database/migrations" ]; then
        local migration_count=0
        for migration_file in database/migrations/*.sql; do
            if [ -f "$migration_file" ]; then
                local migration_name=$(basename "$migration_file")
                
                # Check if migration already applied
                local already_applied=$($CONTAINER_CMD exec $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB -t -c "
                    SELECT COUNT(*) FROM schema_migrations WHERE migration_name = '$migration_name';
                " 2>/dev/null | tr -d '[:space:]')
                
                if [ "$already_applied" = "0" ]; then
                    echo -e "${CYAN}Applying migration: $migration_name${NC}"
                    
                    if $CONTAINER_CMD exec -i $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB < "$migration_file" 2>/dev/null; then
                        # Record migration as applied
                        $CONTAINER_CMD exec $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
                            INSERT INTO schema_migrations (migration_name) VALUES ('$migration_name');
                        " 2>/dev/null
                        echo -e "${GREEN}[OK] Applied: $migration_name${NC}"
                        migration_count=$((migration_count + 1))
                    else
                        echo -e "${YELLOW}WARNING: Failed to apply $migration_name${NC}"
                    fi
                fi
            fi
        done
        
        if [ $migration_count -eq 0 ]; then
            echo -e "${GRAY}All migrations already applied${NC}"
        else
            echo -e "${GREEN}[OK] Applied $migration_count migration(s)${NC}"
        fi
    fi
}

create_env_file() {
    if [ -f ".env" ]; then
        echo -e "${GREEN}[OK] .env exists${NC}"
        return
    fi
    
    if [ ! -f ".env.example" ]; then
        echo -e "${RED}ERROR: .env.example not found${NC}"
        exit 1
    fi
    
    echo -e "${CYAN}Creating .env from template...${NC}"
    cp .env.example .env
    
    # Keep service names for docker-compose (containers communicate via service names)
    # No transformation needed - .env.example already has correct service names
    
    echo -e "${GREEN}[OK] .env created${NC}"
}

show_summary() {
    echo -e "\n${CYAN}=================================================================="
    echo -e "  Environment Ready!"
    echo -e "==================================================================${NC}"
    echo ""
    echo -e "${GREEN}✓ Services Running:${NC}"
    echo -e "  PostgreSQL:  localhost:$POSTGRES_PORT (with pgvector)"
    
    if [ "$START_API" -eq 1 ]; then
        echo -e "  API:         http://localhost:8000"
        echo -e "  API Docs:    http://localhost:8000/docs"
    fi
    
    echo ""
    echo -e "${CYAN}💡 Quick Start:${NC}"
    echo -e "  ${YELLOW}./start-dev-env.sh --full-setup${NC}       ${GRAY}# Development mode (default)${NC}"
    echo -e "  ${YELLOW}./start-dev-env.sh --with-api${NC}         ${GRAY}# Include API container${NC}"
    echo -e "  ${YELLOW}./start-dev-env.sh --prod${NC}              ${GRAY}# Production mode${NC}"
    echo ""
    echo -e "${CYAN}📋 Manual Setup:${NC}"
    echo -e "  1. ${YELLOW}${PY} -m venv venv${NC}"

    case "${OS_TYPE}" in
        windows-msys) echo -e "     ${YELLOW}source venv/Scripts/activate${NC}" ;;
        *) echo -e "     ${YELLOW}source venv/bin/activate${NC}" ;;
    esac

    echo -e "  2. ${YELLOW}${PY} -m pip install -r requirements.txt${NC}"
    echo -e "  3. ${YELLOW}${PY} app.py${NC}"
    echo ""
    echo -e "${CYAN}🔧 Container Commands:${NC}"
    echo -e "  ${GRAY}Logs:   $COMPOSE_CMD -f $COMPOSE_FILE logs -f${NC}"
    echo -e "  ${GRAY}Stop:   $COMPOSE_CMD -f $COMPOSE_FILE stop${NC}"
    echo -e "  ${GRAY}Remove: $COMPOSE_CMD -f $COMPOSE_FILE down${NC}"
    echo ""
    echo -e "${CYAN}==================================================================${NC}"
}

main() {
    create_env_file
    stop_existing_containers
    start_containers
    wait_for_postgres
    wait_for_rabbitmq
    wait_for_api
    initialize_database
    show_summary
    echo -e "\n${GRAY}Containers running in background. Press Ctrl+C to exit this script.${NC}"
}

setup_python_environment() {
    echo -e "\n${CYAN}=================================================================="
    echo -e "  Full Setup: Python Environment"
    echo -e "==================================================================${NC}"
    
    if [ -d "venv" ]; then
        echo -e "${GRAY}Virtual environment exists${NC}"
    else
        echo -e "${CYAN}Creating virtual environment...${NC}"
        $PY -m venv venv
        echo -e "${GREEN}[OK] venv created${NC}"
    fi
    
    echo -e "${CYAN}Activating virtual environment...${NC}"
    if [ "${OS_TYPE}" = "windows-msys" ]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi
    
    echo -e "${CYAN}Installing dependencies (5-10 minutes)...${NC}"
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r requirements.txt
    echo -e "${GREEN}[OK] Dependencies installed${NC}"
    
    echo -e "${CYAN}Creating directories...${NC}"
    mkdir -p data/reference_images data/models/clip logs
    echo -e "${GREEN}[OK] Directories created${NC}"
    
    # Download CLIP model using curl
    echo -e "${CYAN}Checking CLIP model...${NC}"
    if [ ! -f "data/models/clip/open_clip_pytorch_model.bin" ]; then
        echo -e "${YELLOW}Downloading CLIP model (this may take a while)...${NC}"
        curl -L -o data/models/clip/open_clip_pytorch_model.bin \
            ${CLIP_MODEL_URL} || {
            echo -e "${YELLOW}WARNING: CLIP model download failed, will download on first run${NC}"
        }
        
        if [ -f "data/models/clip/open_clip_pytorch_model.bin" ]; then
            echo -e "${GREEN}[OK] CLIP model downloaded${NC}"
        fi
    else
        echo -e "${GRAY}CLIP model already exists${NC}"
    fi
    
    echo -e "${CYAN}Verifying environment...${NC}"
    python -c "
import open_clip, asyncpg, aio_pika, PIL, imagehash
print('✓ All imports successful')
" || {
        echo -e "${RED}ERROR: Environment verification failed${NC}"
        exit 1
    }
    
    echo -e "\n${CYAN}=================================================================="
    echo -e "  Setup Complete!"
    echo -e "==================================================================${NC}"
    echo -e "\n${GREEN}✓ Next Steps:${NC}"
    echo -e "\n${CYAN}Terminal 1 - Worker:${NC}"
    [ "${OS_TYPE}" = "windows-msys" ] && echo -e "  ${YELLOW}source venv/Scripts/activate${NC}" || echo -e "  ${YELLOW}source venv/bin/activate${NC}"
    echo -e "  ${YELLOW}python app.py${NC}"
    echo -e "\n${CYAN}Terminal 2 - API:${NC}"
    [ "${OS_TYPE}" = "windows-msys" ] && echo -e "  ${YELLOW}source venv/Scripts/activate${NC}" || echo -e "  ${YELLOW}source venv/bin/activate${NC}"
    echo -e "  ${YELLOW}cd api && uvicorn api:app --reload --host 0.0.0.0 --port 8000${NC}"
    echo -e "\n${CYAN}API Docs:${NC} ${YELLOW}http://localhost:8000/docs${NC}"
    echo ""
}

main

if [ "$FULL_SETUP" -eq 1 ]; then
    setup_python_environment
fi
