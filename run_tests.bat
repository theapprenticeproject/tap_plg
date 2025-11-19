@echo off
REM Test execution helper script for MentorMe plagiarism detection system (Windows)

setlocal enabledelayedexpansion

echo ==============================================================================
echo MentorMe Test Suite Runner
echo ==============================================================================
echo.

REM Check if pytest is installed
python -m pytest --version >nul 2>&1
if errorlevel 1 (
    echo Error: pytest not installed
    echo Install with: pip install -r requirements-test.txt
    exit /b 1
)

echo [OK] pytest is installed
echo.

REM Parse command line arguments
set MODE=%1
if "%MODE%"=="" set MODE=full

if "%MODE%"=="full" goto :full
if "%MODE%"=="quick" goto :quick
if "%MODE%"=="unit" goto :unit
if "%MODE%"=="integration" goto :integration
if "%MODE%"=="failed" goto :failed
if "%MODE%"=="validate" goto :validate
goto :usage

:full
echo Running full test suite with coverage...
echo ------------------------------------------------------------------------------
python -m pytest tests/ ^
    -v ^
    --cov=image_worker ^
    --cov=database ^
    --cov=mq ^
    --cov=processors ^
    --cov=utils ^
    --cov=plag_checker ^
    --cov=config ^
    --cov-report=term ^
    --cov-report=html ^
    --cov-report=xml ^
    --tb=short ^
    -ra
goto :result

:quick
echo Running tests without coverage (quick mode)...
echo ------------------------------------------------------------------------------
python -m pytest tests/ -v --tb=short
goto :result

:unit
echo Running unit tests only...
echo ------------------------------------------------------------------------------
python -m pytest tests/ -v -m unit --tb=short
goto :result

:integration
echo Running integration tests only...
echo ------------------------------------------------------------------------------
python -m pytest tests/ -v -m integration --tb=short
goto :result

:failed
echo Re-running previously failed tests...
echo ------------------------------------------------------------------------------
python -m pytest tests/ -v --lf --tb=short
goto :result

:validate
echo Running validation script...
echo ------------------------------------------------------------------------------
python tests\validate_tests.py
goto :result

:usage
echo Usage: %0 [mode]
echo.
echo Modes:
echo   full        - Run all tests with coverage (default)
echo   quick       - Run all tests without coverage
echo   unit        - Run unit tests only
echo   integration - Run integration tests only
echo   failed      - Re-run previously failed tests
echo   validate    - Run validation script
echo.
echo Examples:
echo   %0              # Run full suite with coverage
echo   %0 quick        # Quick run without coverage
echo   %0 failed       # Re-run failed tests
exit /b 1

:result
set TEST_EXIT_CODE=%errorlevel%

echo.
echo ==============================================================================
if %TEST_EXIT_CODE%==0 (
    echo [OK] All tests passed!
    echo.
    if "%MODE%"=="full" (
        echo Coverage report: htmlcov\index.html
    )
) else (
    echo [FAILED] Some tests failed (exit code: %TEST_EXIT_CODE%)
)
echo ==============================================================================

exit /b %TEST_EXIT_CODE%
