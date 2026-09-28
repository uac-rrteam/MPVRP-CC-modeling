#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TIME_LIMIT=300

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
MAGENTA='\033[1;35m'
CYAN='\033[1;36m'
BOLD='\033[1m'
RESET='\033[0m'

WITH_MANIFEST="$PROJECT_ROOT/data/instances/with_changeover_costs/manifest.csv"
WITHOUT_MANIFEST="$PROJECT_ROOT/data/instances/without_changeover_costs/manifest.csv"

count_instances() {
    local manifest="$1"
    if [[ ! -f "$manifest" ]]; then
        printf '%bError: manifest not found: %s%b\n' "$RED" "$manifest" "$RESET" >&2
        exit 1
    fi
    awk 'NR > 1 && NF { count++ } END { print count + 0 }' "$manifest"
}

with_count="$(count_instances "$WITH_MANIFEST")"
without_count="$(count_instances "$WITHOUT_MANIFEST")"
total_runs=$((2 * with_count + 2 * without_count))
estimated_seconds=$((total_runs * TIME_LIMIT))
estimated_hours=$((estimated_seconds / 3600))
estimated_minutes=$(((estimated_seconds % 3600) / 60))

printf '%bEstimated maximum compute time: %d hour(s) %d minute(s) (%d runs × %d seconds)%b\n' \
    "$RED" "$estimated_hours" "$estimated_minutes" "$total_runs" "$TIME_LIMIT" "$RESET"

run_stage() {
    local number="$1"
    local method="$2"
    local scenario="$3"
    local color="$4"
    local label="$5"
    local output_dir="$PROJECT_ROOT/data/solutions/lp${method}/${scenario}"

    printf '\n%b%b[%s/4] %s%b\n' "$BOLD" "$color" "$number" "$label" "$RESET"
    printf '%bOutput: %s%b\n' "$CYAN" "$output_dir" "$RESET"

    uv run mpvrp-solve-benchmark \
        --method "$method" \
        --scenario "$scenario" \
        --resume \
        --time-limit "$TIME_LIMIT"

    printf '%bCompleted: %s%b\n' "$GREEN" "$label" "$RESET"
}

cd -- "$PROJECT_ROOT"

# run_stage 1 1 with_changeover_costs "$BLUE" \
#     "LP1 — instances with changeover costs"
run_stage 2 2 with_changeover_costs "$MAGENTA" \
    "LP2 — instances with changeover costs"
# run_stage 3 1 without_changeover_costs "$YELLOW" \
#     "LP1 — instances without changeover costs"
run_stage 4 2 without_changeover_costs "$CYAN" \
    "LP2 — instances without changeover costs"

printf '\n%bAll four benchmark runs completed successfully.%b\n' "$GREEN" "$RESET"
