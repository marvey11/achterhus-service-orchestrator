#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Run full test suite with coverage and threshold checks.

Options:
  -h, --html    Generate HTML coverage report
  -x, --xml     Generate XML coverage report
  -a, --all     Generate both HTML and XML coverage reports
  --help        Show this help message
EOF
  exit 1
}

# Parse long options into short flags for getopts compatibility
for arg in "$@"; do
  shift
  case "$arg" in
    '--html') set -- "$@" "-h" ;;
    '--xml')  set -- "$@" "-x" ;;
    '--all')  set -- "$@" "-a" ;;
    '--help') usage ;;
    *)        set -- "$@" "$arg" ;;
  esac
done

cov_reports=("--cov-report=term-missing")

OPTIND=1
while getopts "hxa" opt; do
  case "$opt" in
    h) cov_reports+=("--cov-report=html") ;;
    x) cov_reports+=("--cov-report=xml") ;;
    a) cov_reports+=("--cov-report=html" "--cov-report=xml") ;;
    *) usage ;;
  esac
done

echo "Running full test suite with coverage..."

if ! uv run pytest \
  --cov=orchestrator \
  "${cov_reports[@]}" \
  --cov-fail-under=80
then
  echo "❌ Tests failed or coverage below threshold."
  exit 1
fi

echo "✅ All tests passed with sufficient coverage."
