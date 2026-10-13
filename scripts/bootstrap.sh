#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required but was not found in PATH." >&2
  exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Error: run this script from inside a Git checkout." >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

uv sync --locked --all-extras --dev
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push --install-hooks

echo "Project bootstrapping complete."
