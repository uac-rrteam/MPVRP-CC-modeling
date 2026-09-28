from __future__ import annotations

import argparse
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gurobipy import GRB

from tools.solve import solve_dataset
from lp1.model import MilpSolution


class BenchmarkReportTests(unittest.TestCase):
    def test_solver_diagnostics_are_written_to_report(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 1 1 1 1\n"
            "0\n"
            "1 100 1 1\n"
            "1 0 0 100\n"
            "1 0 0\n"
            "1 1 1 10\n"
        )
        mocked_solution = MilpSolution(
            objective=125.5,
            best_bound=100.0,
            mip_gap=0.20318725,
            node_count=4321.0,
            solver_runtime=190.012345,
            status=GRB.TIME_LIMIT,
            routes=[],
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance_path = root / "MPVRP_001_s1_d1_p1.dat"
            instance_path.write_text(instance_text, encoding="utf-8")
            manifest_path = root / "manifest.csv"
            manifest_path.write_text(
                "id,file\n001,MPVRP_001_s1_d1_p1.dat\n",
                encoding="utf-8",
            )
            report_path = root / "solutions" / "benchmark_report.csv"
            args = argparse.Namespace(
                manifest=manifest_path,
                report=report_path,
                solutions_dir=root / "solutions",
                time_limit=190,
                verbose=False,
            )

            with (
                patch("tools.solve.solve_milp", return_value=mocked_solution),
                patch("tools.solve.write_solution"),
            ):
                solve_dataset(args)

            with report_path.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["objective"], "125.500000")
        self.assertEqual(row["best_bound"], "100.000000")
        self.assertEqual(row["mip_gap"], "0.20318725")
        self.assertEqual(row["mip_gap_percent"], "20.3187")
        self.assertEqual(row["node_count"], "4321")
        self.assertEqual(row["solver_runtime"], "190.012345")

    def test_resume_keeps_existing_rows_and_solves_only_missing_ids(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 1 1 1 1\n"
            "0\n"
            "1 100 1 1\n"
            "1 0 0 100\n"
            "1 0 0\n"
            "1 1 1 10\n"
        )
        mocked_solution = MilpSolution(
            objective=10.0,
            best_bound=10.0,
            mip_gap=0.0,
            node_count=1.0,
            solver_runtime=0.1,
            status=GRB.OPTIMAL,
            routes=[],
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for instance_id in ("001", "002"):
                (root / f"MPVRP_{instance_id}_s1_d1_p1.dat").write_text(instance_text, encoding="utf-8")
            manifest_path = root / "manifest.csv"
            manifest_path.write_text(
                "id,file\n"
                "001,MPVRP_001_s1_d1_p1.dat\n"
                "002,MPVRP_002_s1_d1_p1.dat\n",
                encoding="utf-8",
            )
            report_path = root / "solutions" / "benchmark_report.csv"
            args = argparse.Namespace(
                manifest=manifest_path,
                report=report_path,
                solutions_dir=root / "solutions",
                time_limit=190,
                verbose=False,
                resume=False,
            )

            with (
                patch("tools.solve.solve_milp", return_value=mocked_solution),
                patch("tools.solve.write_solution"),
            ):
                solve_dataset(args)

            report_lines = report_path.read_text(encoding="utf-8").splitlines()
            report_path.write_text("\n".join(report_lines[:2]) + "\n", encoding="utf-8")
            args.resume = True

            with (
                patch("tools.solve.solve_milp", return_value=mocked_solution) as solver,
                patch("tools.solve.write_solution"),
            ):
                solve_dataset(args)

            with report_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual([row["id"] for row in rows], ["001", "002"])
        self.assertEqual(solver.call_count, 1)


if __name__ == "__main__":
    unittest.main()
