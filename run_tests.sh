#!/bin/bash
# Test execution helper script for MentorMe plagiarism detection system

set -e

echo "=============================================================================="
echo "MentorMe Test Suite Runner"
echo "=============================================================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ $2${NC}"
    else
        echo -e "${RED}✗ $2${NC}"
    fi
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    print_warning "No virtual environment detected. Consider activating one:"
    echo "  source venv/bin/activate  # or your venv path"
    echo ""
fi

# Check if pytest is installed
if ! python -m pytest --version &> /dev/null; then
    echo -e "${RED}Error: pytest not installed${NC}"
    echo "Install with: pip install -r requirements-test.txt"
    exit 1
fi

print_status 0 "pytest is installed"
echo ""

# Parse command line arguments
MODE=${1:-full}

case $MODE in
    full)
        echo "Running full test suite with coverage..."
        echo "------------------------------------------------------------------------------"
        python -m pytest tests/ \
            -v \
            --cov=image_worker \
            --cov=database \
            --cov=mq \
            --cov=processors \
            --cov=utils \
            --cov=plag_checker \
            --cov=config \
            --cov-report=term \
            --cov-report=html \
            --cov-report=xml \
            --tb=short \
            -ra
        ;;
    
    quick)
        echo "Running tests without coverage (quick mode)..."
        echo "------------------------------------------------------------------------------"
        python -m pytest tests/ -v --tb=short
        ;;
    
    unit)
        echo "Running unit tests only..."
        echo "------------------------------------------------------------------------------"
        python -m pytest tests/ \
            -v \
            -m unit \
            --tb=short
        ;;
    
    integration)
        echo "Running integration tests only..."
        echo "------------------------------------------------------------------------------"
        python -m pytest tests/ \
            -v \
            -m integration \
            --tb=short
        ;;
    
    failed)
        echo "Re-running previously failed tests..."
        echo "------------------------------------------------------------------------------"
        python -m pytest tests/ -v --lf --tb=short
        ;;
    
    validate)
        echo "Running validation script..."
        echo "------------------------------------------------------------------------------"
        python tests/validate_tests.py
        ;;
    
    watch)
        echo "Running tests in watch mode (requires pytest-watch)..."
        echo "------------------------------------------------------------------------------"
        if command -v ptw &> /dev/null; then
            ptw tests/ -- -v --tb=short
        else
            print_warning "pytest-watch not installed. Install with: pip install pytest-watch"
            exit 1
        fi
        ;;
    
    *)
        echo "Usage: $0 [mode]"
        echo ""
        echo "Modes:"
        echo "  full        - Run all tests with coverage (default)"
        echo "  quick       - Run all tests without coverage"
        echo "  unit        - Run unit tests only"
        echo "  integration - Run integration tests only"
        echo "  failed      - Re-run previously failed tests"
        echo "  validate    - Run validation script"
        echo "  watch       - Run tests in watch mode (auto-rerun on changes)"
        echo ""
        echo "Examples:"
        echo "  $0              # Run full suite with coverage"
        echo "  $0 quick        # Quick run without coverage"
        echo "  $0 failed       # Re-run failed tests"
        exit 1
        ;;
esac

TEST_EXIT_CODE=$?

echo ""
echo "=============================================================================="
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_status 0 "All tests passed!"
    echo ""
    if [ "$MODE" = "full" ]; then
        echo "Coverage report: htmlcov/index.html"
    fi
else
    print_status 1 "Some tests failed (exit code: $TEST_EXIT_CODE)"
fi
echo "=============================================================================="

exit $TEST_EXIT_CODE
