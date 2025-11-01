#!/bin/bash

set -euo pipefail

# Default values
DEFAULT_TIMEOUT=60
SUDO_CMD="sudo"

# Function to display help
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -h, --help          Display this help message"
    echo "  -t, --timeout       Timeout for each test in seconds (default: $DEFAULT_TIMEOUT)"
    echo "  --no-sudo           Run functional tests without sudo"
}

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -h|--help)
        usage
        exit 0
        ;;
        -t|--timeout)
        TIMEOUT="$2"
        shift
        shift
        ;;
        --no-sudo)
        SUDO_CMD=""
        shift
        ;;
        *)
        echo "Unknown option: $1"
        usage
        exit 1
        ;;
    esac
done

# Set timeout to default if not provided
TIMEOUT=${TIMEOUT:-$DEFAULT_TIMEOUT}

echo "Running unit tests with a timeout of $TIMEOUT seconds per test..."
python3 -m pytest --timeout=$TIMEOUT tests/

echo "Running functional tests with a timeout of $TIMEOUT seconds per test..."
$SUDO_CMD "PYTHONPATH=$(pwd)" python3 -m pytest --timeout=$TIMEOUT tests/test_functional.py
