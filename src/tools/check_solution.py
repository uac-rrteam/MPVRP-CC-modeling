"""Check a saved MILP, CP, or other canonical MPVRP solution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mpvrp.checker import check_solution_text
from mpvrp.models import MPVRPInstance
from paths import CHANGEOVER_INSTANCES_DIR, SOLUTIONS_DIR, ZERO_CHANGEOVER_INSTANCES_DIR

SCENARIOS = {"1": (CHANGEOVER_INSTANCES_DIR, "in"), "2": (ZERO_CHANGEOVER_INSTANCES_DIR, "out")}


def find_instance(instances_dir: Path, number: str) -> Path:
    if not number.isdigit() or int(number) < 1:
        raise ValueError("--inst must be a positive instance number.")
    number = f"{int(number):03d}"
    matches = sorted(instances_dir.glob(f"MPVRP_{number}_s*_d*_p*.dat"))
    if len(matches) != 1:
        raise ValueError(f"Expected one instance {number} in {instances_dir}; found {len(matches)}.")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one MPVRP-CC solution against its instance.")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="1", help="1: changeover costs; 2: zero changeover costs.")
    parser.add_argument("--inst", help="Instance number, e.g. 01 or 001.")
    parser.add_argument("--method", default="milp", help="Solution directory under data/solutions/ (default: milp).")
    parser.add_argument("--instance-path", type=Path, help="Explicit instance file; replaces --inst lookup.")
    parser.add_argument("--solution-path", type=Path, help="Explicit solution file; replaces --method lookup.")
    parser.add_argument("--json", type=Path, help="Write the full report as JSON.")
    args = parser.parse_args()
    if args.instance_path is None and args.inst is None:
        parser.error("provide --inst or --instance-path")
    try:
        instances_dir, scenario_dir = SCENARIOS[args.scenario]
        instance_path = args.instance_path or find_instance(instances_dir, args.inst)
        solution_path = args.solution_path or (
            SOLUTIONS_DIR / args.method / scenario_dir / instance_path.name.replace("MPVRP_", "Sol_", 1)
        )
        instance = MPVRPInstance.read(instance_path)
        report = check_solution_text(instance, solution_path.read_text(encoding="utf-8"))
        print(f"Instance: {instance_path}")
        print(f"Solution: {solution_path}")
        print(f"Result: {'VALID' if report.is_valid else 'INVALID'}")
        for check in report.checks.values():
            print(f"[{check.status}] {check.name}")
            for detail in check.details:
                print(f"  - {detail}")
        if report.calculated:
            print("Calculated: " + ", ".join(f"{key}={value:g}" for key, value in report.calculated.items()))
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({
                "instance": str(instance_path),
                "solution": str(solution_path),
                **report.to_dict(),
            }, indent=2) + "\n", encoding="utf-8")
            print(f"JSON report: {args.json}")
        return 0 if report.is_valid else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"mpvrp-check-solution: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
