#!/usr/bin/env python3
"""
Test validation script for MentorMe plagiarism detection system.
Runs all tests and validates coverage meets requirements.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=False
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)


def main():
    """Run all tests and validate coverage."""
    print("=" * 80)
    print("MentorMe Test Suite Validation")
    print("=" * 80)
    print()

    # Check if pytest is installed
    print("Checking dependencies...")
    returncode, _, _ = run_command("python -m pytest --version")
    if returncode != 0:
        print(
            "❌ pytest not installed. Install with: pip install -r requirements-test.txt"
        )
        return 1
    print("✓ pytest installed")
    print()

    # Run tests with coverage
    print("Running test suite with coverage...")
    print("-" * 80)

    cmd = (
        "python -m pytest tests/ "
        "-v "
        "--cov=image_worker "
        "--cov=database "
        "--cov=mq "
        "--cov=processors "
        "--cov=utils "
        "--cov=plag_checker "
        "--cov=config "
        "--cov-report=term "
        "--cov-report=html "
        "--cov-report=xml "
        "--tb=short "
        "-ra"
    )

    returncode, stdout, stderr = run_command(cmd)

    print(stdout)
    if stderr:
        print("STDERR:", stderr)
    print("-" * 80)
    print()

    # Parse coverage results
    coverage_file = Path("coverage.xml")
    if coverage_file.exists():
        try:
            import xml.etree.ElementTree as ET

            tree = ET.parse(coverage_file)
            root = tree.getroot()

            # Get overall coverage
            line_rate = float(root.attrib.get("line-rate", 0))
            coverage_pct = line_rate * 100

            print(f"Overall Coverage: {coverage_pct:.2f}%")

            if coverage_pct >= 85:
                print("✓ Coverage meets 85% threshold")
            else:
                print(f"❌ Coverage below 85% threshold (got {coverage_pct:.2f}%)")

        except Exception as e:
            print(f"⚠ Could not parse coverage results: {e}")
    else:
        print("⚠ Coverage XML file not found")

    print()

    # Summary
    print("=" * 80)
    if returncode == 0:
        print("✓ All tests passed!")
    else:
        print(f"❌ Some tests failed (exit code: {returncode})")
    print("=" * 80)

    return returncode


if __name__ == "__main__":
    sys.exit(main())
