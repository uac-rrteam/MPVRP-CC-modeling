from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.scenarios import zero_changeover_costs
from tools.reevaluate import reevaluate_solution_text
from lp1.io.sol import format_solution
from lp1.schemas import MPVRPInstance


class ChangeoverScenarioTests(unittest.TestCase):
    def test_only_changeover_matrix_is_zeroed(self) -> None:
        source_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "2 1 1 1 1\n"
            "3 13\n"
            "9 4\n"
            "1 100 1 1\n"
            "1 0 0 100 100\n"
            "1 0 0\n"
            "1 1 1 10 20\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "MPVRP_TEST_s1_d1_p2.dat"
            destination = Path(directory) / "paired" / source.name
            source.write_text(source_text, encoding="utf-8")

            zero_changeover_costs(source, destination)

            source_lines = source.read_text(encoding="utf-8").splitlines()
            paired_lines = destination.read_text(encoding="utf-8").splitlines()
            self.assertEqual(paired_lines[2:4], ["0\t0", "0\t0"])
            self.assertEqual(paired_lines[:2], source_lines[:2])
            self.assertEqual(paired_lines[4:], source_lines[4:])

            parsed = MPVRPInstance.read(destination)
            self.assertEqual(parsed.changeover_cost, [[0, 0], [0, 0]])

    def test_fixed_solution_is_repriced_without_changing_routes(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "2 1 1 1 1\n"
            "3 13\n"
            "9 4\n"
            "1 100 1 1\n"
            "1 0 0 100 100\n"
            "1 0 0\n"
            "1 1 1 10 20\n"
        )
        solution_text = (
            "1: 1 - 1 [10] - 1 (10) - 1 [20] - 1 (20) - 1\n"
            "1: 0(0.00) - 0(0.00) - 0(0.00) - 1(0.00) - 1(0.00)\n"
            "\n"
            "1\n"
            "1\n"
            "0.00\n"
            "10.00\n"
            "Test CPU\n"
            "1.000\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            instance_path = Path(directory) / "MPVRP_TEST_s1_d1_p2.dat"
            instance_path.write_text(instance_text, encoding="utf-8")
            instance = MPVRPInstance.read(instance_path)
            updated, changes, cost = reevaluate_solution_text(solution_text, instance)

        self.assertEqual(changes, 1)
        self.assertEqual(cost, 16)
        self.assertIn("0(0.00) - 0(3.00) - 0(3.00) - 1(16.00) - 1(16.00)", updated)
        self.assertIn("\n1\n1\n16.00\n10.00\n", updated)
        self.assertEqual(updated.splitlines()[0], solution_text.splitlines()[0])

    def test_same_product_trip_pays_preparation_without_counting_a_change(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 1 1 1 1\n"
            "3\n"
            "1 100 1 1\n"
            "1 0 0 100\n"
            "1 0 0\n"
            "1 1 0 10\n"
        )
        routes = [
            {
                "vehicle": 1,
                "trip": 0,
                "product": 1,
                "start_depot": 1,
                "deliveries": [{"station": 1, "quantity": 10}],
                "path": ["S1"],
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            instance_path = Path(directory) / "MPVRP_TEST_s1_d1_p1.dat"
            instance_path.write_text(instance_text, encoding="utf-8")
            solution = format_solution(MPVRPInstance.read(instance_path), routes, 0.1, "Test CPU")

        metrics = solution.splitlines()[-6:]
        self.assertIn("0(0.00) - 0(3.00) - 0(3.00)", solution)
        self.assertEqual(metrics[1], "0")
        self.assertEqual(metrics[2], "3.00")

    def test_distance_follows_the_serialized_route_and_rounds_each_arc(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 2 1 2 1\n"
            "0\n"
            "1 100 1 1\n"
            "1 1 1 10\n"
            "2 4 0 10\n"
            "1 0 0\n"
            "1 2 0 5\n"
            "2 5 0 5\n"
        )
        routes = [
            {
                "vehicle": 1,
                "trip": 1,
                "product": 1,
                "start_depot": 1,
                "path": ["D1", "S1", "D2"],
                "deliveries": [{"station": 1, "quantity": 5}],
            },
            {
                "vehicle": 1,
                "trip": 2,
                "product": 1,
                "start_depot": 2,
                "path": ["D2", "S2"],
                "deliveries": [{"station": 2, "quantity": 5}],
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            instance_path = Path(directory) / "MPVRP_TEST_s2_d2_p1.dat"
            instance_path.write_text(instance_text, encoding="utf-8")
            solution = format_solution(MPVRPInstance.read(instance_path), routes, 0.1, "Test CPU")

        lines = solution.splitlines()
        self.assertEqual(
            lines[0],
            "1: 1 - 1 [5] - 1 (5) - 2 [5] - 2 (5) - 1",
        )
        # Rounded arcs: G-D1=1, D1-S1=1, S1-D2=2, D2-S2=1, S2-G=5.
        self.assertEqual(lines[-3], "10.00")


if __name__ == "__main__":
    unittest.main()
