from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lp1.schemas import MPVRPInstance
from lp1.model import _maximum_uniform_trip_bound


class MilpFormulationTests(unittest.TestCase):
    def test_default_trip_bound_uses_aggregate_capacity_formula(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 3 1 3 1\n"
            "0\n"
            "1 100 1 1\n"
            "1 0 0 1\n"
            "2 1 0 1\n"
            "3 2 0 1\n"
            "1 0 0\n"
            "1 0 1 1\n"
            "2 1 1 1\n"
            "3 2 1 1\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MPVRP_TEST_s3_d3_p1.dat"
            path.write_text(instance_text, encoding="utf-8")
            instance = MPVRPInstance.read(path)

        self.assertEqual(_maximum_uniform_trip_bound(instance), 2)


if __name__ == "__main__":
    unittest.main()
