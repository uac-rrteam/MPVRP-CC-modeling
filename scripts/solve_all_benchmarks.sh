#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd -- "$PROJECT_ROOT"

echo "Solving the benchmark with changeover costs..."
uv run mpvrp-solve-benchmark \
    --scenario with_changeover_costs \
    --time-limit 190

echo "Solving the benchmark without changeover costs..."
uv run mpvrp-solve-benchmark \
    --scenario without_changeover_costs \
    --time-limit 190

echo "Both benchmark scenarios have been completed."
