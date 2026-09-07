#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TIME_LIMIT=300
START_ID=49

WITH_INSTANCES="$PROJECT_ROOT/data/instances/with_changeover_costs"
WITH_MANIFEST="$WITH_INSTANCES/manifest.csv"
WITH_SOLUTIONS="$PROJECT_ROOT/data/solutions/lp2/with_changeover_costs"
WITH_REPORT="$WITH_SOLUTIONS/benchmark_report_from_048.csv"

WITHOUT_MANIFEST="$PROJECT_ROOT/data/instances/without_changeover_costs/manifest.csv"
WITHOUT_SOLUTIONS="$PROJECT_ROOT/data/solutions/lp2/without_changeover_costs"
WITHOUT_REPORT="$WITHOUT_SOLUTIONS/benchmark_report.csv"

for manifest in "$WITH_MANIFEST" "$WITHOUT_MANIFEST"; do
    if [[ ! -f "$manifest" ]]; then
        printf 'Error: manifest not found: %s\n' "$manifest" >&2
        exit 1
    fi
done

# Keep the temporary manifest beside its instance files so relative paths still
# resolve correctly. It is removed automatically when the script exits.
resume_manifest="$(mktemp "$WITH_INSTANCES/.manifest_from_048.XXXXXX.csv")"
trap 'rm -f -- "$resume_manifest"' EXIT

awk -F, -v start="$START_ID" '
    NR == 1 { print; next }
    ($1 + 0) >= start { print }
' "$WITH_MANIFEST" > "$resume_manifest"

remaining_count="$(awk 'END { print NR - 1 }' "$resume_manifest")"
if (( remaining_count < 1 )); then
    printf 'Error: no instances numbered %03d or later were found.\n' "$START_ID" >&2
    exit 1
fi

cd -- "$PROJECT_ROOT"


printf '\nStarting the not-yet-run LP2 scenario without changeover costs.\n'
uv run mpvrp-solve-benchmark \
    --method 2 \
    --scenario without_changeover_costs \
    --manifest "$WITHOUT_MANIFEST" \
    --solutions-dir "$WITHOUT_SOLUTIONS" \
    --report "$WITHOUT_REPORT" \
    --time-limit "$TIME_LIMIT"

printf '\nLP2 benchmark continuation completed successfully.\n'
