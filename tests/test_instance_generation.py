from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from mpvrp_cc.experiments.generate_benchmark import (
    CHANGEOVER_LEVELS,
    _level_combinations,
    _random_level_combination,
)
from mpvrp_cc.generation.instance_generator import (
    CHANGEOVER_COST_RANGES,
    _generate_mixed_transition_costs,
    _generate_transition_costs,
    generate_instance_data,
)
from mpvrp_cc.generation.config import GenerationConfig
from mpvrp_cc.generation.instance_file_io import write_instance
from mpvrp_cc.generation.validation import _minimum_uniform_trip_bound
from mpvrp_cc.io.instance_solution_io import MPVRPInstance


class ChangeoverGenerationTests(unittest.TestCase):
    def test_validation_trip_bound_matches_solver_formula(self) -> None:
        self.assertEqual(_minimum_uniform_trip_bound(100, 100, 3), 3)
        self.assertEqual(_minimum_uniform_trip_bound(500, 100, 2), 6)

    def test_main_benchmark_excludes_low_changeover_level(self) -> None:
        self.assertEqual(CHANGEOVER_LEVELS, ("normal", "high", "mixed"))

        combinations = _level_combinations(np.random.default_rng(42), 250)
        counts = {
            level: sum(changeover == level for changeover, *_ in combinations)
            for level in CHANGEOVER_LEVELS
        }

        self.assertNotIn("low", {changeover for changeover, *_ in combinations})
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_mixed_matrix_has_low_diagonal_and_material_off_diagonal(self) -> None:
        costs = _generate_mixed_transition_costs(np.random.default_rng(42), products=12)
        off_diagonal = costs[~np.eye(costs.shape[0], dtype=bool)]
        diagonal = np.diag(costs)
        low_min, low_max = CHANGEOVER_COST_RANGES["low"]
        normal_min = CHANGEOVER_COST_RANGES["normal"][0]
        high_max = CHANGEOVER_COST_RANGES["high"][1]

        self.assertTrue(np.all(diagonal >= low_min))
        self.assertTrue(np.all(diagonal <= low_max))
        self.assertTrue(np.all(off_diagonal >= normal_min))
        self.assertTrue(np.all(off_diagonal <= high_max))

    def test_every_cost_level_uses_low_same_product_preparation_costs(self) -> None:
        low_min, low_max = CHANGEOVER_COST_RANGES["low"]
        for level in ("low", "normal", "high", "mixed"):
            with self.subTest(level=level):
                config = GenerationConfig(
                    instance_code="DIAGONAL_TEST",
                    vehicles=1,
                    depots=1,
                    garages=1,
                    stations=1,
                    products=4,
                    changeover_cost_level=level,
                )
                costs = _generate_transition_costs(np.random.default_rng(42), config)
                diagonal = np.diag(costs)
                self.assertTrue(np.all(diagonal >= low_min))
                self.assertTrue(np.all(diagonal <= low_max))

    def test_backtracking_preserves_changeover_stratum(self) -> None:
        rng = np.random.default_rng(42)

        retries = [_random_level_combination(rng, "high") for _ in range(20)]

        self.assertEqual({changeover for changeover, *_ in retries}, {"high"})

    def test_generated_instance_is_integer_in_memory_file_and_parser(self) -> None:
        config = GenerationConfig(
            instance_code="INTEGER_TEST",
            vehicles=5,
            depots=2,
            garages=2,
            stations=8,
            products=3,
            changeover_cost_level="mixed",
            seed=20260819,
        )
        data = generate_instance_data(config)

        for values in (
            data.params,
            data.transition_costs,
            data.vehicles,
            data.depots,
            data.garages,
            data.stations,
        ):
            self.assertTrue(np.issubdtype(values.dtype, np.integer))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / config.filename
            write_instance(data, path)
            numeric_lines = path.read_text(encoding="utf-8").splitlines()[1:]
            numeric_tokens = [token for line in numeric_lines for token in line.split()]
            parsed = MPVRPInstance.read(path)

        self.assertTrue(all(token.lstrip("-").isdigit() for token in numeric_tokens))
        self.assertTrue(all(isinstance(cost, int) for row in parsed.changeover_cost for cost in row))
        self.assertTrue(all(isinstance(vehicle.capacity, int) for vehicle in parsed.vehicles))
        self.assertTrue(all(isinstance(node.x, int) and isinstance(node.y, int) for node in parsed.depots))
        self.assertTrue(all(isinstance(stock, int) for node in parsed.depots for stock in node.stocks))
        self.assertTrue(all(isinstance(node.x, int) and isinstance(node.y, int) for node in parsed.garages))
        self.assertTrue(all(isinstance(node.x, int) and isinstance(node.y, int) for node in parsed.stations))
        self.assertTrue(all(isinstance(demand, int) for node in parsed.stations for demand in node.demand))
        self.assertTrue(all(isinstance(distance, int) for row in parsed.dist_matrix for distance in row))

    def test_instance_parser_rejects_decimal_tokens(self) -> None:
        instance_text = (
            "# 00000000-0000-4000-8000-000000000000\n"
            "1 1 1 1 1\n"
            "25.0\n"
            "1 100 1 1\n"
            "1 0 0 100\n"
            "1 0 0\n"
            "1 1 0 10\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MPVRP_DECIMAL_s1_d1_p1.dat"
            path.write_text(instance_text, encoding="utf-8")

            with self.assertRaises(ValueError):
                MPVRPInstance.read(path)


if __name__ == "__main__":
    unittest.main()
