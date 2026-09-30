from __future__ import annotations

import argparse
import csv
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from gurobipy import GRB
from loguru import logger

from tools.run_logging import configure_run_logging
from mpvrp.checker import check_solution_text
from mpvrp.io.solution import write_solution
from milp.solver import solve_milp
from mpvrp.models import MPVRPInstance
from paths import (
	CHANGEOVER_INSTANCES_DIR,
	CHANGEOVER_SOLUTIONS_DIR,
	ZERO_CHANGEOVER_INSTANCES_DIR,
	ZERO_CHANGEOVER_SOLUTIONS_DIR,
)

LOGGER = logger
DEFAULT_TIME_LIMIT = 190
@dataclass
class BenchmarkResult:
	id: str
	file: str
	instance_path: str
	status: str = "UNSOLVED"
	solver_status: str = ""
	objective: str = ""
	solver_objective: str = ""
	best_bound: str = ""
	mip_gap: str = ""
	mip_gap_percent: str = ""
	node_count: str = ""
	solver_runtime: str = ""
	solution_file: str = ""
	message: str = ""


REPORT_FIELDNAMES = [field.name for field in fields(BenchmarkResult)]


SCENARIO_DIRECTORIES = {
	"1": CHANGEOVER_INSTANCES_DIR,
	"2": ZERO_CHANGEOVER_INSTANCES_DIR,
}

SCENARIO_SOLUTION_DIRECTORIES = {
	"1": CHANGEOVER_SOLUTIONS_DIR,
	"2": ZERO_CHANGEOVER_SOLUTIONS_DIR,
}


def _solution_path(instance: Any, solutions_dir: Path) -> Path:
	return solutions_dir / (
		f"Sol_{instance.instance_id}"
		f"_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}.dat"
	)


def _validated_route_objective(instance: MPVRPInstance, solution_path: Path) -> float:
	"""Return the objective represented by the saved, checked route."""
	report = check_solution_text(instance, solution_path.read_text(encoding="utf-8"))
	if not report.is_valid:
		failures = [
			detail
			for check in report.checks.values() if check.status == "FAIL"
			for detail in check.details
		]
		raise ValueError(f"Saved solution failed verification: {'; '.join(failures)}")
	return float(report.calculated["distance"] + report.calculated["changeover_cost"])


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


def _load_report(report_path: Path) -> dict[str, dict[str, str]]:
	"""Load completed report rows, indexed by instance ID."""
	if not report_path.exists():
		return {}
	with report_path.open(newline="", encoding="utf-8") as file:
		reader = csv.DictReader(file)
		legacy_fields = [name for name in REPORT_FIELDNAMES if name != "solver_objective"]
		if reader.fieldnames not in (REPORT_FIELDNAMES, legacy_fields):
			raise ValueError(f"Unexpected report columns in {report_path}")
		rows = list(reader)
		if reader.fieldnames == legacy_fields:
			for row in rows:
				row["solver_objective"] = row["objective"]
		return {row["id"]: row for row in rows}


def _write_report(
	report_path: Path,
	report_rows: dict[str, dict[str, str]],
	manifest_rows: list[dict[str, str]],
) -> None:
	"""Atomically checkpoint report rows in manifest order."""
	manifest_ids = [
		row.get("id", f"{index:03d}")
		for index, row in enumerate(manifest_rows, start=1)
	]
	ordered_rows = [report_rows[instance_id] for instance_id in manifest_ids if instance_id in report_rows]
	known_ids = set(manifest_ids)
	ordered_rows.extend(row for instance_id, row in report_rows.items() if instance_id not in known_ids)

	temporary_path = report_path.with_name(f".{report_path.name}.tmp")
	with temporary_path.open("w", newline="", encoding="utf-8") as file:
		writer = csv.DictWriter(file, fieldnames=REPORT_FIELDNAMES)
		writer.writeheader()
		writer.writerows(ordered_rows)
	temporary_path.replace(report_path)


def solve_dataset(args: argparse.Namespace) -> Path:
	"""Solve every manifest entry and record a CSV report."""
	manifest_path = args.manifest
	if not manifest_path.exists():
		raise FileNotFoundError(f"Manifest not found: {manifest_path}")

	report_path = args.report
	report_path.parent.mkdir(parents=True, exist_ok=True)
	args.solutions_dir.mkdir(parents=True, exist_ok=True)

	rows = _load_manifest(manifest_path)
	report_rows = _load_report(report_path) if getattr(args, "resume", False) else {}
	_write_report(report_path, report_rows, rows)
	solved = 0
	unsolved = 0
	skipped = 0

	for index, row in enumerate(rows, start=1):
		instance_id = row.get("id", f"{index:03d}")
		if instance_id in report_rows:
			skipped += 1
			LOGGER.info("[{}/{}] Skipping reported instance {}", index, len(rows), instance_id)
			continue
		file_name = row.get("file", "")
		instance_path = _resolve_instance_path(manifest_path, file_name)

		LOGGER.info("[{}/{}] Solving {}", index, len(rows), instance_path.name)
		start = time.perf_counter()
		result = BenchmarkResult(instance_id, file_name, str(instance_path))

		try:
			instance = MPVRPInstance.read(instance_path)
			solution = solve_milp(instance, time_limit=args.time_limit, output=args.verbose)

			if solution is None:
				result.message = f"No incumbent solution within {args.time_limit} seconds or model infeasible."
				unsolved += 1
				LOGGER.warning("UNSOLVED {}: {}", instance_path.name, result.message)
			else:
				elapsed = time.perf_counter() - start
				solution_path = _solution_path(instance, args.solutions_dir)
				write_solution(instance=instance, routes=solution.routes, filename=solution_path, resolution_time=elapsed)
				route_objective = _validated_route_objective(instance, solution_path)
				result.status = "OPTIMAL" if solution.status == GRB.OPTIMAL else "SOLVED"
				result.solver_status = "OPTIMAL" if solution.status == GRB.OPTIMAL else "TIME_LIMIT"
				result.objective = f"{route_objective:.6f}"
				result.solver_objective = f"{solution.objective:.6f}"
				result.best_bound = f"{solution.best_bound:.6f}"
				result.mip_gap = f"{solution.mip_gap:.8f}"
				result.mip_gap_percent = f"{100.0 * solution.mip_gap:.4f}"
				result.node_count = f"{solution.node_count:.0f}"
				result.solver_runtime = f"{solution.solver_runtime:.6f}"
				result.solution_file = str(solution_path)
				solved += 1
				LOGGER.info("{} {} objective={} gap={}", result.status, instance_path.name, result.objective, result.mip_gap)
		except Exception as exc:
			result.message = str(exc)
			unsolved += 1
			LOGGER.exception("UNSOLVED {}: {}", instance_path.name, exc)

		report_rows[instance_id] = asdict(result)
		# Persist every result so an interruption loses at most the active solve.
		_write_report(report_path, report_rows, rows)

	LOGGER.info(
		"Finished. solved={} unsolved={} skipped={} report={}",
		solved,
		unsolved,
		skipped,
		report_path,
	)
	return report_path


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Solve the 100-instance benchmark set with a fixed time limit. 1=with changeover costs, 2=without changeover costs.")
	parser.add_argument(
		"--scenario",
		choices=tuple(SCENARIO_DIRECTORIES),
		default="1",
		help="Experimental scenario to solve.",
	)
	parser.add_argument("--manifest", type=Path, help="Override the scenario manifest.")
	parser.add_argument("--solutions-dir", type=Path, help="Override the scenario solution directory.")
	parser.add_argument("--report", type=Path, help="Override the scenario report path.")
	parser.add_argument(
		"--resume",
		action="store_true",
		help="Keep existing report rows and solve only manifest IDs not yet reported.",
	)
	parser.add_argument("--time-limit", type=int, default=DEFAULT_TIME_LIMIT, help="Per-instance Gurobi time limit in seconds.")
	parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
	parser.add_argument("--verbose", action="store_true", help="Enable debug logging and Gurobi output.")
	parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
	args = parser.parse_args()
	instances_dir = SCENARIO_DIRECTORIES[args.scenario]
	default_solutions_dir = SCENARIO_SOLUTION_DIRECTORIES[args.scenario]
	args.manifest = args.manifest or instances_dir / "manifest.csv"
	args.solutions_dir = args.solutions_dir or default_solutions_dir
	args.report = args.report or default_solutions_dir / "benchmark_report.csv"
	return args


def main() -> int:
	args = parse_args()
	configure_run_logging("solve_benchmark", verbose=args.verbose, quiet=args.quiet, log_dir=args.log_dir)

	if args.time_limit < 1:
		LOGGER.error("--time-limit must be at least 1.")
		return 1

	try:
		solve_dataset(args)
	except (FileNotFoundError, ValueError) as exc:
		LOGGER.error("{}", exc)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
