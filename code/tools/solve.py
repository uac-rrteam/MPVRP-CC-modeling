from __future__ import annotations

import argparse
import csv
import importlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gurobipy import GRB

from tools.gen import configure_logging
from lp1.io.sol import write_solution
from lp1.model import solve_milp
from lp1.schemas import MPVRPInstance
from common.paths import (
	LP1_SOLUTIONS_DIR,
	LP2_SOLUTIONS_DIR,
	WITH_CHANGEOVER_INSTANCES_DIR,
	WITHOUT_CHANGEOVER_INSTANCES_DIR,
)

LOGGER = logging.getLogger("tools.solve")
DEFAULT_TIME_LIMIT = 190
REPORT_FIELDNAMES = [
	"id",
	"file",
	"instance_path",
	"status",
	"solver_status",
	"objective",
	"best_bound",
	"mip_gap",
	"mip_gap_percent",
	"node_count",
	"solver_runtime",
	"solution_file",
	"message",
]


SCENARIO_DIRECTORIES = {
	"with_changeover_costs": WITH_CHANGEOVER_INSTANCES_DIR,
	"without_changeover_costs": WITHOUT_CHANGEOVER_INSTANCES_DIR,
}

METHOD_SOLUTIONS_DIRECTORIES = {
	1: LP1_SOLUTIONS_DIR,
	2: LP2_SOLUTIONS_DIR,
}


def _solver_for_method(method: int) -> Callable[..., object]:
	"""Return the solver function for the selected LP formulation."""
	if method == 1:
		return solve_milp
	return importlib.import_module(f"lp{method}.model").solve_milp


def _instance_class_for_method(method: int) -> type:
	"""Return the instance schema used by the selected formulation."""
	if method == 1:
		return MPVRPInstance
	return importlib.import_module(f"lp{method}.schemas").MPVRPInstance


def _solution_writer_for_method(method: int) -> Callable[..., Path]:
	"""Return the solution writer used by the selected formulation."""
	if method == 1:
		return write_solution
	return importlib.import_module(f"lp{method}.io.sol").write_solution


def _solution_path(instance: Any, solutions_dir: Path) -> Path:
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


def _load_report(report_path: Path) -> dict[str, dict[str, str]]:
	"""Load completed report rows, indexed by instance ID."""
	if not report_path.exists():
		return {}
	with report_path.open(newline="", encoding="utf-8") as file:
		reader = csv.DictReader(file)
		if reader.fieldnames != REPORT_FIELDNAMES:
			raise ValueError(f"Unexpected report columns in {report_path}")
		return {row["id"]: row for row in reader}


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
	method = getattr(args, "method", 1)
	solver = _solver_for_method(method)
	instance_class = _instance_class_for_method(method)
	solution_writer = _solution_writer_for_method(method)
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
			LOGGER.info("[%s/%s] Skipping reported instance %s", index, len(rows), instance_id)
			continue
		file_name = row.get("file", "")
		instance_path = _resolve_instance_path(manifest_path, file_name)

		LOGGER.info("[%s/%s] Solving %s", index, len(rows), instance_path.name)
		start = time.perf_counter()
		status = "UNSOLVED"
		solver_status = ""
		objective = ""
		best_bound = ""
		mip_gap = ""
		mip_gap_percent = ""
		node_count = ""
		solver_runtime = ""
		solution_file = ""
		message = ""

		try:
			instance = instance_class.read(instance_path)
			solution = solver(instance, time_limit=args.time_limit, output=args.verbose)

			if solution is None:
				message = f"No incumbent solution within {args.time_limit} seconds or model infeasible."
				unsolved += 1
				LOGGER.warning("UNSOLVED %s: %s", instance_path.name, message)
			else:
				status = "SOLVED"
				solver_status = "OPTIMAL" if solution.status == GRB.OPTIMAL else "TIME_LIMIT"
				objective = f"{solution.objective:.6f}"
				best_bound = f"{solution.best_bound:.6f}"
				mip_gap = f"{solution.mip_gap:.8f}"
				mip_gap_percent = f"{100.0 * solution.mip_gap:.4f}"
				node_count = f"{solution.node_count:.0f}"
				solver_runtime = f"{solution.solver_runtime:.6f}"
				elapsed = time.perf_counter() - start
				solution_path = _solution_path(instance, args.solutions_dir)
				solution_writer(instance=instance, routes=solution.routes, filename=solution_path, resolution_time=elapsed)
				solution_file = str(solution_path)
				solved += 1
				LOGGER.info("Solved %s (%s)", instance_path.name, solver_status)
		except Exception as exc:
			message = str(exc)
			unsolved += 1
			LOGGER.warning("UNSOLVED %s: %s", instance_path.name, exc)

		report_rows[instance_id] = {
			"id": instance_id,
			"file": file_name,
			"instance_path": str(instance_path),
			"status": status,
			"solver_status": solver_status,
			"objective": objective,
			"best_bound": best_bound,
			"mip_gap": mip_gap,
			"mip_gap_percent": mip_gap_percent,
			"node_count": node_count,
			"solver_runtime": solver_runtime,
			"solution_file": solution_file,
			"message": message,
		}
		# Persist every result so an interruption loses at most the active solve.
		_write_report(report_path, report_rows, rows)

	LOGGER.info(
		"Finished. solved=%s unsolved=%s skipped=%s report=%s",
		solved,
		unsolved,
		skipped,
		report_path,
	)
	return report_path


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Solve the 100-instance benchmark set with a fixed time limit.")
	parser.add_argument(
		"--method",
		type=int,
		choices=(1, 2),
		default=1,
		help="LP formulation to use (1 or 2).",
	)
	parser.add_argument(
		"--scenario",
		choices=tuple(SCENARIO_DIRECTORIES),
		default="with_changeover_costs",
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
	args = parser.parse_args()
	instances_dir = SCENARIO_DIRECTORIES[args.scenario]
	default_solutions_dir = METHOD_SOLUTIONS_DIRECTORIES[args.method] / args.scenario
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
	except (FileNotFoundError, ValueError) as exc:
		LOGGER.error("%s", exc)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
