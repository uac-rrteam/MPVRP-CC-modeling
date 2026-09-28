#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TIME_LIMIT="${TIME_LIMIT:-300}"

WITH_INSTANCES="$PROJECT_ROOT/data/instances/with_changeover_costs"
WITH_MANIFEST="$WITH_INSTANCES/manifest.csv"
WITH_SOLUTIONS="$PROJECT_ROOT/data/solutions/lp2/with_changeover_costs"
WITH_REPORT="$WITH_SOLUTIONS/benchmark_report.csv"
LEGACY_PARTIAL_REPORT="$WITH_SOLUTIONS/benchmark_report_from_048.csv"

if [[ ! -f "$WITH_MANIFEST" ]]; then
    printf 'Error: manifest not found: %s\n' "$WITH_MANIFEST" >&2
    exit 1
fi

# Preserve the already recorded 049-100 results as the starting checkpoint.
if [[ ! -f "$WITH_REPORT" && -f "$LEGACY_PARTIAL_REPORT" ]]; then
    cp -- "$LEGACY_PARTIAL_REPORT" "$WITH_REPORT"
    printf 'Seeded %s from the existing partial report.\n' "$WITH_REPORT"
fi

cd -- "$PROJECT_ROOT"
printf '\nRepairing the LP2 report with changeover costs.\n'
uv run mpvrp-solve-benchmark \
    --method 2 \
    --scenario with_changeover_costs \
    --manifest "$WITH_MANIFEST" \
    --solutions-dir "$WITH_SOLUTIONS" \
    --report "$WITH_REPORT" \
    --resume \
    --time-limit "$TIME_LIMIT"

printf '\nLP2 report repair completed: %s\n' "$WITH_REPORT"
