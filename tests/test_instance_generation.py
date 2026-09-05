from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.benchmark import (
    CHANGEOVER_LEVELS,
    _level_combinations,
    _random_level_combination,
)
from tools.gen import (
    CHANGEOVER_COST_RANGES,
    _generate_mixed_transition_costs,
    _repair_fragmented_depot_stocks,
    _generate_transition_costs,
    generate_instance_data,
)
from tools.gen_data import GenerationConfig, VerificationReport
from tools.gen_io import load_instance_file, write_instance
from tools.validation import (
    _maximum_uniform_trip_bound,
    maximum_station_product_delivery,
    validate_instance_data,
)
from lp1.schemas import MPVRPInstance


class ChangeoverGenerationTests(unittest.TestCase):
    def test_fragmented_stock_bound_matches_instance_073_shortage(self) -> None:
        maximum = maximum_station_product_delivery(
            np.array([5800, 8981]),
            np.array([4083, 4344, 6131, 5492, 6140, 0]),
        )

        self.assertEqual(maximum, 11940)

    def test_fragmented_stock_repair_preserves_stock_and_covers_demand(self) -> None:
        capacities = np.array([5800, 8981])
        depots = np.array(
            [
                [1, 0, 0, 4083],
                [2, 0, 0, 4344],
                [3, 0, 0, 6131],
                [4, 0, 0, 5492],
                [5, 0, 0, 6140],
                [6, 0, 0, 0],
            ]
        )
        stations = np.array([[1, 0, 0, 14215]])
        original_total = int(depots[:, 3].sum())

        _repair_fragmented_depot_stocks(depots, stations, capacities)

        self.assertEqual(int(depots[:, 3].sum()), original_total)
        self.assertGreaterEqual(
            maximum_station_product_delivery(capacities, depots[:, 3]),
            14215,
        )

    def test_generated_stock_is_compatible_with_distinct_vehicle_visits(self) -> None:
        config = GenerationConfig(
            instance_code="FRAGMENTATION_TEST",
            vehicles=2,
            depots=6,
            garages=3,
            stations=5,
            products=3,
            capacity_level="mixed",
            demand_level="high",
            stock_level="low",
            demand_probability=0.7,
            seed=2048827690,
        )

        report = validate_instance_data(generate_instance_data(config))

        self.assertTrue(report.is_valid, report.errors)

    def test_validation_trip_bound_matches_solver_formula(self) -> None:
        self.assertEqual(_maximum_uniform_trip_bound(100, 100, 3), 3)
        self.assertEqual(_maximum_uniform_trip_bound(500, 100, 2), 6)

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
