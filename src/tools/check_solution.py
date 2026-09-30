"""Check saved MILP, CP, or other canonical MPVRP solutions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
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


def _solution_path(instance_path: Path, solutions_dir: Path) -> Path:
    return solutions_dir / instance_path.name.replace("MPVRP_", "Sol_", 1)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_all(instances_dir: Path, solutions_dir: Path, report_dir: Path | None = None) -> dict:
    """Check every instance, including missing solutions in the saved report."""
    instance_paths = sorted(instances_dir.glob("MPVRP_*.dat"))
    if not instance_paths:
        raise FileNotFoundError(f"No instances found in {instances_dir}")
    entries = []
    counts: Counter[str] = Counter()
    for instance_path in instance_paths:
        solution_path = _solution_path(instance_path, solutions_dir)
        entry: dict = {"instance": str(instance_path), "solution": str(solution_path)}
        if not solution_path.is_file():
            entry.update(status="MISSING", error="Matching solution file not found.")
        else:
            try:
                instance = MPVRPInstance.read(instance_path)
                report = check_solution_text(instance, solution_path.read_text(encoding="utf-8"))
                entry.update(status="VALID" if report.is_valid else "INVALID", **report.to_dict())
            except (OSError, ValueError) as exc:
                entry.update(status="ERROR", error=str(exc))
        counts[entry["status"]] += 1
        entries.append(entry)
        if report_dir is not None:
            instance_id = instance_path.stem.split("_", 2)[1]
            _write_json(report_dir / f"instance_{instance_id}.json", entry)
    return {
        "valid": counts["VALID"] == len(entries),
        "instances_dir": str(instances_dir),
        "solutions_dir": str(solutions_dir),
        "total": len(entries),
        "counts": {status: counts[status] for status in ("VALID", "INVALID", "MISSING", "ERROR")},
        "results": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one or all MPVRP-CC solutions against their instances.")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="1", help="1: changeover costs; 2: zero changeover costs.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--inst", help="Instance number (e.g. 01) or 'all'.")
    selection.add_argument("--all", action="store_true", help="Check every instance in the selected scenario.")
    selection.add_argument("--instance-path", type=Path, help="Explicit instance file for a single check.")
    parser.add_argument("--method", default="milp", help="Solution directory under data/solutions/ (default: milp).")
    parser.add_argument("--solution-path", type=Path, help="Explicit solution file for a single check.")
    parser.add_argument("--json", type=Path, help="Save a single or aggregate JSON report.")
    parser.add_argument("--report-dir", type=Path, help="With --all, save a JSON report for each instance.")
    args = parser.parse_args()
    all_instances = args.all or args.inst == "all"
    if all_instances and args.solution_path is not None:
        parser.error("--solution-path cannot be used with --all or --inst all")
    if args.report_dir is not None and not all_instances:
        parser.error("--report-dir requires --all or --inst all")
    try:
        instances_dir, scenario_dir = SCENARIOS[args.scenario]
        solutions_dir = SOLUTIONS_DIR / args.method / scenario_dir
        if all_instances:
            aggregate = check_all(instances_dir, solutions_dir, args.report_dir)
            aggregate["scenario"] = args.scenario
            aggregate["method"] = args.method
            for entry in aggregate["results"]:
                if entry["status"] != "VALID":
                    reason = entry.get("error") or "; ".join(
                        detail
                        for check in entry.get("checks", []) if check["status"] == "FAIL"
                        for detail in check["details"]
                    )
                    print(f"{Path(entry['instance']).name}: {entry['status']} — {reason}")
            summary = aggregate["counts"]
            print(f"Checked {aggregate['total']} instances: " + ", ".join(f"{summary[key]} {key.lower()}" for key in summary))
            if args.json:
                _write_json(args.json, aggregate)
                print(f"Aggregate JSON report: {args.json}")
            if args.report_dir:
                print(f"Individual JSON reports: {args.report_dir}")
            return 0 if summary["VALID"] == aggregate["total"] else 1

        instance_path = args.instance_path or find_instance(instances_dir, args.inst)
        solution_path = args.solution_path or _solution_path(instance_path, solutions_dir)
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
            _write_json(args.json, {"instance": str(instance_path), "solution": str(solution_path), **report.to_dict()})
            print(f"JSON report: {args.json}")
        return 0 if report.is_valid else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"mpvrp-check-solution: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
