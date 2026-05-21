#!/usr/bin/env pwsh
# Local Development Startup Script
# Starts PostgreSQL and RabbitMQ containers using docker-compose

$ErrorActionPreference = "Stop"

# Parse command line arguments
$COMPOSE_FILE = "docker-compose-dev.yml"
$START_API = $false
$FULL_SETUP = $false

foreach ($arg in $args) {
    switch ($arg) {
        "--prod" { $COMPOSE_FILE = "docker-compose-prod.yml" }
        "--dev" { $COMPOSE_FILE = "docker-compose-dev.yml" }
        "--with-api" { $START_API = $true }
        "--full-setup" { $FULL_SETUP = $true }
    }
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  MentorMe Plagiarism Checker - Local Development Setup" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""

# Detect container runtime (Podman or Docker)
$CONTAINER_CMD = $null
$COMPOSE_CMD = $null

if (Get-Command podman -ErrorAction SilentlyContinue) {
    $CONTAINER_CMD = "podman"
    if (Get-Command podman-compose -ErrorAction SilentlyContinue) {
        $COMPOSE_CMD = "podman-compose"
    } else {
        Write-Host "ERROR: podman-compose not found" -ForegroundColor Red
        Write-Host "Install it: pip install podman-compose" -ForegroundColor Yellow
        exit 1
    }
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    $CONTAINER_CMD = "docker"
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $COMPOSE_CMD = "docker-compose"
    } else {
        try {
            & docker compose version 2>$null
            $COMPOSE_CMD = "docker compose"
        } catch {
            Write-Host "ERROR: docker-compose not found" -ForegroundColor Red
            Write-Host "Install it: https://docs.docker.com/compose/install/" -ForegroundColor Yellow
            exit 1
        }
    }
} else {
    Write-Host "ERROR: Neither Podman nor Docker found" -ForegroundColor Red
    Write-Host "Install one of them:" -ForegroundColor Yellow
    Write-Host "  Podman: https://podman.io/getting-started/installation" -ForegroundColor Yellow
    Write-Host "  Docker: https://docs.docker.com/get-docker/" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using container runtime: $CONTAINER_CMD" -ForegroundColor Green
Write-Host "Compose file: $COMPOSE_FILE" -ForegroundColor Green
Write-Host ""

# Validate compose file exists
if (!(Test-Path $COMPOSE_FILE)) {
    Write-Host "ERROR: $COMPOSE_FILE not found" -ForegroundColor Red
    exit 1
}

# Load configuration from .env if it exists
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Item -Path "env:$name" -Value $value
        }
    }
}

# Configuration (with defaults from environment or hardcoded)
$POSTGRES_CONTAINER = "plg-postgres"
$RABBITMQ_CONTAINER = "plg-rabbitmq"
$POSTGRES_PORT = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { 5432 }
$RABBITMQ_PORT = if ($env:RABBITMQ_PORT) { $env:RABBITMQ_PORT } else { 5672 }
$RABBITMQ_MGMT_PORT = if ($env:RABBITMQ_MANAGEMENT_PORT) { $env:RABBITMQ_MANAGEMENT_PORT } else { 15672 }
$POSTGRES_PASSWORD = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "postgres" }
$POSTGRES_DB = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "plagiarism_db" }
$POSTGRES_USER = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "postgres" }
$RABBITMQ_USER = if ($env:RABBITMQ_USER) { $env:RABBITMQ_USER } else { "admin" }
$RABBITMQ_PASS = if ($env:RABBITMQ_PASS) { $env:RABBITMQ_PASS } else { "admin123" }
$CLIP_MODEL_URL = if ($env:CLIP_MODEL_URL) { $env:CLIP_MODEL_URL } else { "https://huggingface.co/laion/CLIP-ViT-L-14-laion2B-s32B-b82K/resolve/main/open_clip_pytorch_model.bin" }

function Stop-ExistingContainers {
    $containersExist = $false
    
    # Check if compose stack is running
    $composePs = & $COMPOSE_CMD -f $COMPOSE_FILE ps 2>$null
    if ($composePs -match "Up|running") {
        $containersExist = $true
    }
    
    if ($containersExist) {
        Write-Host "Existing containers found:" -ForegroundColor Yellow
        & $COMPOSE_CMD -f $COMPOSE_FILE ps
        Write-Host ""
        Write-Host "This will stop and remove existing containers." -ForegroundColor Yellow
        
        $confirmation = Read-Host "Continue? (y/N)"
        
        if ($confirmation -notmatch '^[Yy]$') {
            Write-Host "Aborted by user" -ForegroundColor Red
            exit 0
        }
        
        Write-Host "Stopping existing containers..." -ForegroundColor Cyan
        & $COMPOSE_CMD -f $COMPOSE_FILE down
    }
    
    Write-Host "[OK] Ready to start containers" -ForegroundColor Green
}

function Start-Containers {
    Write-Host "Starting containers with $COMPOSE_FILE..." -ForegroundColor Cyan
    
    # Determine which services to start
    $services = @("postgres", "rabbitmq", "pgadmin", "plagiarism-checker")
    
    if ($START_API) {
        $services += "api"
        Write-Host "Including API service" -ForegroundColor Cyan
        
        # Force rebuild API container to ensure it uses Dockerfile.api (not Dockerfile)
        Write-Host "Rebuilding API container with Dockerfile.api..." -ForegroundColor Yellow
        & $COMPOSE_CMD -f $COMPOSE_FILE build --no-cache api
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Failed to build API container" -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] API container rebuilt" -ForegroundColor Green
    }
    
    & $COMPOSE_CMD -f $COMPOSE_FILE up -d $services
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to start containers" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "[OK] Containers started" -ForegroundColor Green
}

function Wait-ForPostgres {
    Write-Host "Waiting for PostgreSQL..." -ForegroundColor Yellow
    
    $maxAttempts = 30
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        
        $result = & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres pg_isready -U $POSTGRES_USER 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] PostgreSQL ready" -ForegroundColor Green
            return
        }
        
        Start-Sleep -Seconds 2
    }
    
    Write-Host "ERROR: PostgreSQL timeout" -ForegroundColor Red
    exit 1
}

function Wait-ForRabbitMQ {
    Write-Host "Waiting for RabbitMQ..." -ForegroundColor Yellow
    
    $maxAttempts = 30
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:${RABBITMQ_MGMT_PORT}" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host "[OK] RabbitMQ ready" -ForegroundColor Green
                return
            }
        } catch { }
        
        Start-Sleep -Seconds 2
    }
    
    Write-Host "ERROR: RabbitMQ timeout" -ForegroundColor Red
    exit 1
}

function Wait-ForAPI {
    if (-not $START_API) {
        return
    }
    
    Write-Host "Waiting for API service..." -ForegroundColor Yellow
    
    $maxAttempts = 30
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $attempt++
        
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Host "[OK] API service ready" -ForegroundColor Green
                return
            }
        } catch { }
        
        Start-Sleep -Seconds 2
    }
    
    Write-Host "ERROR: API service timeout" -ForegroundColor Red
    Write-Host "Checking API container logs:" -ForegroundColor Yellow
    & $COMPOSE_CMD -f $COMPOSE_FILE logs --tail=50 api
    exit 1
}

function Initialize-Database {
    if (!(Test-Path "database/init.sql")) {
        Write-Host "WARNING: database/init.sql not found" -ForegroundColor Yellow
        return
    }
    
    Write-Host "Initializing database..." -ForegroundColor Cyan
    
    # Run init.sql
    Get-Content "database/init.sql" | & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Database schema initialized" -ForegroundColor Green
    } else {
        Write-Host "Database schema already exists" -ForegroundColor Gray
    }
    
    # Create migrations tracking table
    & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c @"
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            migration_name VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT NOW()
        );
"@ 2>$null
    
    # Run migration scripts
    if (Test-Path "database/migrations") {
        $migrationCount = 0
        Get-ChildItem "database/migrations/*.sql" | ForEach-Object {
            $migrationName = $_.Name
            
            # Check if migration already applied
            $alreadyApplied = & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -t -c "SELECT COUNT(*) FROM schema_migrations WHERE migration_name = '$migrationName';" 2>$null
            $alreadyApplied = ($alreadyApplied -replace '\s','')
            
            if ($alreadyApplied -eq "0") {
                Write-Host "Applying migration: $migrationName" -ForegroundColor Cyan
                
                Get-Content $_.FullName | & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB 2>$null
                
                if ($LASTEXITCODE -eq 0) {
                    # Record migration as applied
                    & $COMPOSE_CMD -f $COMPOSE_FILE exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "INSERT INTO schema_migrations (migration_name) VALUES ('$migrationName');" 2>$null
                    Write-Host "[OK] Applied: $migrationName" -ForegroundColor Green
                    $migrationCount++
                } else {
                    Write-Host "WARNING: Failed to apply $migrationName" -ForegroundColor Yellow
                }
            }
        }
        
        if ($migrationCount -eq 0) {
            Write-Host "All migrations already applied" -ForegroundColor Gray
        } else {
            Write-Host "[OK] Applied $migrationCount migration(s)" -ForegroundColor Green
        }
    }
}

function Create-EnvFile {
    if (Test-Path ".env") {
        Write-Host "[OK] .env exists" -ForegroundColor Green
        return
    }
    
    if (!(Test-Path ".env.example")) {
        Write-Host "ERROR: .env.example not found" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "Creating .env from template..." -ForegroundColor Cyan
    
    # Copy .env.example to .env without modifications
    # Service names (rabbitmq, postgres) work correctly within docker-compose network
    Copy-Item ".env.example" ".env"
    
    Write-Host "[OK] .env created" -ForegroundColor Green
}

function Show-Summary {
    Write-Host "`n==================================================================" -ForegroundColor Cyan
    Write-Host "  Environment Ready!" -ForegroundColor Green
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "✓ Services Running:" -ForegroundColor Green
    Write-Host "  PostgreSQL:  localhost:${POSTGRES_PORT} (with pgvector)"
    Write-Host "  RabbitMQ:    localhost:${RABBITMQ_PORT}"
    Write-Host "  RabbitMQ UI: http://localhost:${RABBITMQ_MGMT_PORT} ($RABBITMQ_USER/$RABBITMQ_PASS)"
    
    if ($START_API) {
        Write-Host "  API:         http://localhost:8000"
        Write-Host "  API Docs:    http://localhost:8000/docs"
    }
    
    Write-Host ""
    Write-Host "� Quick Start:" -ForegroundColor Cyan
    Write-Host "  .\start-dev-env.ps1 --full-setup       # Development mode (default)" -ForegroundColor Yellow
    Write-Host "  .\start-dev-env.ps1 --with-api         # Include API container" -ForegroundColor Yellow
    Write-Host "  .\start-dev-env.ps1 --prod             # Production mode" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "📋 Manual Setup:" -ForegroundColor Cyan
    Write-Host "  1. python -m venv venv" -ForegroundColor Yellow
    Write-Host "     .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  2. python -m pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host "  3. python app.py" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "🔧 Container Commands:" -ForegroundColor Cyan
    Write-Host "  Logs:   $COMPOSE_CMD -f $COMPOSE_FILE logs -f" -ForegroundColor Gray
    Write-Host "  Stop:   $COMPOSE_CMD -f $COMPOSE_FILE stop" -ForegroundColor Gray
    Write-Host "  Remove: $COMPOSE_CMD -f $COMPOSE_FILE down" -ForegroundColor Gray
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
}

function Setup-PythonEnvironment {
    Write-Host "`n==================================================================" -ForegroundColor Cyan
    Write-Host "  Full Setup: Python Environment" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    
    if (Test-Path "venv") {
        Write-Host "Virtual environment exists" -ForegroundColor Gray
    } else {
        Write-Host "Creating virtual environment..." -ForegroundColor Cyan
        python -m venv venv
        Write-Host "[OK] venv created" -ForegroundColor Green
    }
    
    Write-Host "Activating virtual environment..." -ForegroundColor Cyan
    & ".\venv\Scripts\Activate.ps1"
    
    Write-Host "Installing dependencies (5-10 minutes)..." -ForegroundColor Cyan
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r requirements.txt
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
    
    Write-Host "Creating directories..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path "data/reference_images", "data/models/clip", "logs" | Out-Null
    Write-Host "[OK] Directories created" -ForegroundColor Green
    
    # Download CLIP model
    Write-Host "Checking CLIP model..." -ForegroundColor Cyan
    if (!(Test-Path "data/models/clip/open_clip_pytorch_model.bin")) {
        Write-Host "Downloading CLIP model (this may take a while)..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest -Uri $CLIP_MODEL_URL -OutFile "data/models/clip/open_clip_pytorch_model.bin" -UseBasicParsing
            Write-Host "[OK] CLIP model downloaded" -ForegroundColor Green
        } catch {
            Write-Host "WARNING: CLIP model download failed, will download on first run" -ForegroundColor Yellow
        }
    } else {
        Write-Host "CLIP model already exists" -ForegroundColor Gray
    }
    
    Write-Host "Verifying environment..." -ForegroundColor Cyan
    $verifyScript = @"
import open_clip, asyncpg, aio_pika, PIL, imagehash
print('✓ All imports successful')
"@
    
    try {
        python -c $verifyScript
    } catch {
        Write-Host "ERROR: Environment verification failed" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "`n==================================================================" -ForegroundColor Cyan
    Write-Host "  Setup Complete!" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host "`n✓ Next Steps:" -ForegroundColor Green
    Write-Host "`nTerminal 1 - Worker:" -ForegroundColor Cyan
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  python app.py" -ForegroundColor Yellow
    Write-Host "`nTerminal 2 - API:" -ForegroundColor Cyan
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  cd api && uvicorn api:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Yellow
    Write-Host "`nAPI Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host ""
}

try {
    Create-EnvFile
    Stop-ExistingContainers
    Start-Containers
    Wait-ForPostgres
    Wait-ForRabbitMQ
    Wait-ForAPI
    Initialize-Database
    Show-Summary
    
    Write-Host "`nContainers running in background. Press Ctrl+C to exit this script." -ForegroundColor Gray
    
    if ($FULL_SETUP) {
        Setup-PythonEnvironment
    }
    
} catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    exit 1
}
