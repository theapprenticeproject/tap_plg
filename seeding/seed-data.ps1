# Data Seeding Script (PowerShell)
# Seeds reference images and student submissions into the plagiarism detection system

param(
    [switch]$RefImages,
    [switch]$Submissions,
    [switch]$All,
    [switch]$NoPgvector,
    [switch]$NoFaiss,
    [switch]$NoHashes,
    [string]$RefDir = "./data/reference_images",
    [string]$Xlsx = "",
    [switch]$Help
)

# Colors
$Red = "Red"
$Green = "Green"
$Yellow = "Yellow"
$Cyan = "Cyan"
$Gray = "Gray"

# Show help
if ($Help) {
    Write-Host "Usage: .\seeding\seed-data.ps1 [OPTIONS]" -ForegroundColor $Cyan
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -RefImages         Seed reference images"
    Write-Host "  -Submissions       Seed student submissions from XLSX"
    Write-Host "  -All               Seed both reference images and submissions"
    Write-Host "  -NoPgvector        Skip PostgreSQL pgvector storage"
    Write-Host "  -NoFaiss           Skip FAISS index creation"
    Write-Host "  -NoHashes          Skip perceptual hash computation"
    Write-Host "  -RefDir DIR        Reference images directory (default: ./data/reference_images)"
    Write-Host "  -Xlsx FILE         XLSX file for submissions"
    Write-Host "  -Help              Show this help message"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor $Cyan
    Write-Host "  .\seeding\seed-data.ps1 -RefImages" -ForegroundColor $Yellow
    Write-Host "  .\seeding\seed-data.ps1 -Submissions -Xlsx data/submissions.xlsx" -ForegroundColor $Yellow
    Write-Host "  .\seeding\seed-data.ps1 -All" -ForegroundColor $Yellow
    exit 0
}

# Detect Python
$Python = $null
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $Python = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
} else {
    Write-Host "ERROR: Python not found" -ForegroundColor $Red
    exit 1
}

# Load environment variables from .env
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and !$line.StartsWith("#")) {
            $parts = $line -split "=", 2
            if ($parts.Length -eq 2) {
                $key = $parts[0].Trim()
                $value = $parts[1].Trim().Trim('"')
                Set-Item -Path "env:$key" -Value $value
            }
        }
    }
}

# Determine actions
$SeedRefImages = $RefImages.IsPresent -or $All.IsPresent
$SeedSubmissions = $Submissions.IsPresent -or $All.IsPresent

# Validate that at least one action is specified
if (!$SeedRefImages -and !$SeedSubmissions) {
    Write-Host "ERROR: No action specified. Use -RefImages, -Submissions, or -All" -ForegroundColor $Red
    Write-Host "Use -Help for usage information"
    exit 1
}

Write-Host "==================================================================" -ForegroundColor $Cyan
Write-Host "  MentorMe Plagiarism Checker - Data Seeding" -ForegroundColor $Cyan
Write-Host "==================================================================" -ForegroundColor $Cyan
Write-Host ""

# Seed reference images
if ($SeedRefImages) {
    Write-Host "==================================================================" -ForegroundColor $Cyan
    Write-Host "  Seeding Reference Images" -ForegroundColor $Cyan
    Write-Host "==================================================================" -ForegroundColor $Cyan
    Write-Host ""
    
    if (!(Test-Path $RefDir)) {
        Write-Host "ERROR: Reference images directory not found: $RefDir" -ForegroundColor $Red
        exit 1
    }
    
    # Build command arguments
    $args = @("seeding/seed_ref_images.py", "--images-dir", $RefDir)
    
    if (!$NoPgvector.IsPresent) {
        $args += "--use-pgvector"
    }
    
    if (!$NoFaiss.IsPresent) {
        $args += "--use-faiss"
    }
    
    if (!$NoHashes.IsPresent) {
        $args += "--compute-hashes"
    }
    
    Write-Host "Running: $Python $($args -join ' ')" -ForegroundColor $Yellow
    Write-Host ""
    
    & $Python $args
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "[OK] Reference images seeded successfully" -ForegroundColor $Green
    } else {
        Write-Host ""
        Write-Host "ERROR: Failed to seed reference images" -ForegroundColor $Red
        exit 1
    }
}

# Seed student submissions
if ($SeedSubmissions) {
    Write-Host "==================================================================" -ForegroundColor $Cyan
    Write-Host "  Seeding Student Submissions" -ForegroundColor $Cyan
    Write-Host "==================================================================" -ForegroundColor $Cyan
    Write-Host ""
    
    if ([string]::IsNullOrEmpty($Xlsx)) {
        Write-Host "ERROR: XLSX file not specified. Use -Xlsx FILE" -ForegroundColor $Red
        exit 1
    }
    
    if (!(Test-Path $Xlsx)) {
        Write-Host "ERROR: XLSX file not found: $Xlsx" -ForegroundColor $Red
        exit 1
    }
    
    $args = @("seeding/seed_from_xlsx.py", "--xlsx", $Xlsx)
    
    Write-Host "Running: $Python $($args -join ' ')" -ForegroundColor $Yellow
    Write-Host ""
    
    & $Python $args
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "[OK] Student submissions seeded successfully" -ForegroundColor $Green
    } else {
        Write-Host ""
        Write-Host "ERROR: Failed to seed student submissions" -ForegroundColor $Red
        exit 1
    }
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor $Cyan
Write-Host "  Seeding Complete!" -ForegroundColor $Cyan
Write-Host "==================================================================" -ForegroundColor $Cyan
Write-Host ""
Write-Host "✓ Data seeding completed successfully" -ForegroundColor $Green
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor $Cyan
Write-Host "  .\start-dev-env.ps1 -WithApi" -ForegroundColor $Yellow -NoNewline
Write-Host "  # Start the application" -ForegroundColor $Gray
Write-Host ""
