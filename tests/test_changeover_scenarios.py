from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mpvrp_cc.experiments.create_changeover_scenarios import zero_changeover_costs
from mpvrp_cc.io.instance_solution_io import MPVRPInstance


class ChangeoverScenarioTests(unittest.TestCase):
    def test_only_changeover_matrix_is_zeroed(self) -> None:
        source_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "2 1 1 1 1\n"
            "0 12.5\n"
            "8.75 0\n"
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
            self.assertEqual(parsed.changeover_cost, [[0.0, 0.0], [0.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
