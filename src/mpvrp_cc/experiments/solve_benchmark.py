from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path

from gurobipy import GRB

from mpvrp_cc.generation.instance_generator import configure_logging
from mpvrp_cc.io.instance_solution_io import MPVRPInstance, write_solution
from mpvrp_cc.optimization.milp_solver import solve_milp
from mpvrp_cc.paths import (
	WITH_CHANGEOVER_INSTANCES_DIR,
	WITH_CHANGEOVER_SOLUTIONS_DIR,
	WITHOUT_CHANGEOVER_INSTANCES_DIR,
	WITHOUT_CHANGEOVER_SOLUTIONS_DIR,
)

LOGGER = logging.getLogger("mpvrp_cc.solve_benchmark")
DEFAULT_TIME_LIMIT = 190


SCENARIO_DIRECTORIES = {
	"with_changeover_costs": (WITH_CHANGEOVER_INSTANCES_DIR, WITH_CHANGEOVER_SOLUTIONS_DIR),
	"without_changeover_costs": (WITHOUT_CHANGEOVER_INSTANCES_DIR, WITHOUT_CHANGEOVER_SOLUTIONS_DIR),
}


def _solution_path(instance: MPVRPInstance, solutions_dir: Path) -> Path:
	return solutions_dir / (
		f"Sol_{instance.instance_id}"
		f"_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}.dat"
	)


def _resolve_instance_path(manifest_path: Path, entry: str) -> Path:
	path = Path(entry)
	if path.is_absolute():
		return path

	candidates = [manifest_path.parent / path, path]
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
			solution = solve_milp(instance, time_limit=args.time_limit, output=args.verbose)

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
	parser.add_argument(
		"--scenario",
		choices=tuple(SCENARIO_DIRECTORIES),
		default="with_changeover_costs",
		help="Experimental scenario to solve.",
	)
	parser.add_argument("--manifest", type=Path, help="Override the scenario manifest.")
	parser.add_argument("--solutions-dir", type=Path, help="Override the scenario solution directory.")
	parser.add_argument("--report", type=Path, help="Override the scenario report path.")
	parser.add_argument("--time-limit", type=int, default=DEFAULT_TIME_LIMIT, help="Per-instance Gurobi time limit in seconds.")
	parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
	parser.add_argument("--verbose", action="store_true", help="Enable debug logging and Gurobi output.")
	args = parser.parse_args()
	instances_dir, default_solutions_dir = SCENARIO_DIRECTORIES[args.scenario]
	args.manifest = args.manifest or instances_dir / "manifest.csv"
	args.solutions_dir = args.solutions_dir or default_solutions_dir
	args.report = args.report or default_solutions_dir / "benchmark_report.csv"
	return args


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
