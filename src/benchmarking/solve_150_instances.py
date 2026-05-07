from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path
import sys

from gurobipy import GRB

from src.models.lp import solve_lp
from src.tools.generator import configure_logging
from src.utils.parser import DEFAULT_SOLUTIONS_DIR, MPVRPInstance, write_solution

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger("mpvrp.solve_150")
DEFAULT_TIME_LIMIT = 190


def _default_manifest_path() -> Path:
	return PROJECT_ROOT / "inst" / "manifest.csv"


def _solution_path(instance: MPVRPInstance, solutions_dir: Path) -> Path:
	return solutions_dir / (
		f"Sol_{instance.instance_id}"
		f"_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}.dat"
	)


def _resolve_instance_path(manifest_path: Path, entry: str) -> Path:
	path = Path(entry)
	if path.is_absolute():
		return path

	candidates = [manifest_path.parent / path, PROJECT_ROOT / "inst" / path, path]
	for candidate in candidates:
		if candidate.exists():
			return candidate
	return candidates[0]


def _load_manifest(manifest_path: Path) -> list[dict[str, str]]:
	with manifest_path.open(newline="") as file:
		return list(csv.DictReader(file))


def solve_dataset(args: argparse.Namespace) -> Path:
	"""Solve every manifest entry and record a CSV report."""
	manifest_path = args.manifest
	if not manifest_path.exists():
		raise FileNotFoundError(f"Manifest not found: {manifest_path}")

	report_path = args.report
	report_path.parent.mkdir(parents=True, exist_ok=True)
	args.solutions_dir.mkdir(parents=True, exist_ok=True)

	rows = _load_manifest(manifest_path)
	report_rows: list[dict[str, str]] = []
	solved = 0
	unsolved = 0

	for index, row in enumerate(rows, start=1):
		instance_id = row.get("id", f"{index:03d}")
		file_name = row.get("file", "")
		instance_path = _resolve_instance_path(manifest_path, file_name)

		LOGGER.info("[%s/%s] Solving %s", index, len(rows), instance_path.name)
		start = time.perf_counter()
		status = "UNSOLVED"
		solver_status = ""
		objective = ""
		solution_file = ""
		message = ""

		try:
			instance = MPVRPInstance.read(instance_path)
			solution = solve_lp(instance, time_limit=args.time_limit, output=args.verbose)

			if solution is None:
				message = f"No incumbent solution within {args.time_limit} seconds or model infeasible."
				unsolved += 1
				LOGGER.warning("UNSOLVED %s: %s", instance_path.name, message)
			else:
				status = "SOLVED"
				solver_status = "OPTIMAL" if solution.status == GRB.OPTIMAL else "TIME_LIMIT"
				objective = f"{solution.objective:.6f}"
				elapsed = time.perf_counter() - start
				solution_path = _solution_path(instance, args.solutions_dir)
				write_solution(instance=instance, routes=solution.routes, filename=solution_path, resolution_time=elapsed)
				solution_file = str(solution_path)
				solved += 1
				LOGGER.info("Solved %s (%s)", instance_path.name, solver_status)
		except Exception as exc:
			message = str(exc)
			unsolved += 1
			LOGGER.warning("UNSOLVED %s: %s", instance_path.name, exc)

		report_rows.append(
			{
				"id": instance_id,
				"file": file_name,
				"instance_path": str(instance_path),
				"status": status,
				"solver_status": solver_status,
				"objective": objective,
				"solution_file": solution_file,
				"message": message,
			}
		)

	with report_path.open("w", newline="") as file:
		fieldnames = ["id", "file", "instance_path", "status", "solver_status", "objective", "solution_file", "message"]
		writer = csv.DictWriter(file, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(report_rows)

	LOGGER.info("Finished. solved=%s unsolved=%s report=%s", solved, unsolved, report_path)
	return report_path


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Solve the 150-instance benchmark set with a fixed time limit.")
	parser.add_argument("--manifest", type=Path, default=_default_manifest_path(), help="CSV manifest produced by the generator.")
	parser.add_argument("--solutions-dir", type=Path, default=DEFAULT_SOLUTIONS_DIR, help="Directory where solution files are written.")
	parser.add_argument("--report", type=Path, default=DEFAULT_SOLUTIONS_DIR / "solve_150_report.csv", help="CSV report with solve status per instance.")
	parser.add_argument("--time-limit", type=int, default=DEFAULT_TIME_LIMIT, help="Per-instance Gurobi time limit in seconds.")
	parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
	parser.add_argument("--verbose", action="store_true", help="Enable debug logging and Gurobi output.")
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	configure_logging(verbose=args.verbose, quiet=args.quiet)

	if args.time_limit < 1:
		LOGGER.error("--time-limit must be at least 1.")
		return 1

	try:
		solve_dataset(args)
	except FileNotFoundError as exc:
		LOGGER.error("%s", exc)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

