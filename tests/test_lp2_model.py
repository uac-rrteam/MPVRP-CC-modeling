from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lp2.io.sol import write_solution
from lp2.model import _maximum_uniform_trip_bound, _validate_trip_bound
from lp2.schemas import MPVRPInstance


class LP2ModelTests(unittest.TestCase):
    def _read(self, demand: int = 21) -> MPVRPInstance:
        text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 1 1 1 2\n"
            "25\n"
            "1 10 1 1\n"
            "2 5 1 1\n"
            f"1 0 0 {demand}\n"
            "1 0 0\n"
            f"1 3 4 {demand}\n"
        )
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "MPVRP_TEST_s1_d1_p1.dat"
        path.write_text(text, encoding="utf-8")
        return MPVRPInstance.read(path)

    def test_trip_bound_uses_expanded_request_demands(self) -> None:
        instance = self._read()

        self.assertEqual(sum(request.demand for request in instance.requests), 21)
        self.assertEqual(_maximum_uniform_trip_bound(instance), 3)

    def test_rejects_horizon_with_insufficient_fleet_capacity(self) -> None:
        instance = self._read()

        with self.assertRaisesRegex(ValueError, "too small"):
            _validate_trip_bound(instance, 1)

    def test_routes_use_the_canonical_solution_format(self) -> None:
        instance = self._read()
        routes = [
            {
                "vehicle": 1,
                "trip": 1,
                "product": 1,
                "start_depot": 1,
                "path": ["D1", "S1"],
                "deliveries": [{"station": 1, "product": 1, "quantity": 10}],
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "solution.dat"
            write_solution(instance, routes, output, resolution_time=0.1, processor="test")
            contents = output.read_text(encoding="utf-8")

        self.assertIn("1: 1 - 1 [10] - 1 (10) - 1", contents)
        self.assertIn("1: 0(0.00) - 0(25.00) - 0(25.00)", contents)


if __name__ == "__main__":
    unittest.main()
