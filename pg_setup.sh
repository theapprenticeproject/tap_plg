COMPOSE_FILE="docker-postgres.yml"
COMPOSE_CMD="podman-compose"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'


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

$COMPOSE_CMD -f $COMPOSE_FILE up -d

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

main() {
    wait_for_postgres
    initialize_database
    echo -e "\n${GRAY}Containers running in background. Press Ctrl+C to exit this script.${NC}"
}

main
echo "Setup Complete"
