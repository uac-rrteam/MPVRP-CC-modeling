#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SOLUTIONS_DIR="$PROJECT_ROOT/data/solutions/lp2/without_changeover_costs"
OUTPUT_DIR="$SOLUTIONS_DIR/reevaluated_with_changeover_costs"

shopt -s nullglob
solutions=("$SOLUTIONS_DIR"/Sol_*.dat)

if ((${#solutions[@]} == 0)); then
    echo "No solutions found in $SOLUTIONS_DIR" >&2
    exit 1
fi

echo "Reevaluating ${#solutions[@]} solution(s)..."
mkdir -p -- "$OUTPUT_DIR"

for solution in "${solutions[@]}"; do
    echo "Processing $(basename -- "$solution")"
    (
        cd -- "$PROJECT_ROOT"
        uv run mpvrp-reevaluate-changeovers \
            "$solution" \
            --output "$OUTPUT_DIR/$(basename -- "$solution")"
    )
done

echo "Reevaluation completed."
echo "Results: $OUTPUT_DIR/"
