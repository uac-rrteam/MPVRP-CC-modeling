from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lp2.schemas import MPVRPInstance


INSTANCE_TEXT = """# 00000000-0000-4000-8000-000000000000
3 2 1 2 1
10 11 12
20 21 22
30 31 32
1 100 1 2
1 0 0 50 0 70
2 3 4 0 60 0
1 0 4
1 0 3 0 15 20
2 3 0 5 0 0
"""


class LP2InstanceIOTests(unittest.TestCase):
    def _read(self) -> MPVRPInstance:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "MPVRP_TEST_s2_d2_p3.dat"
        path.write_text(INSTANCE_TEXT, encoding="utf-8")
        return MPVRPInstance.read(path)

    def test_positive_vectors_are_expanded_into_product_nodes(self) -> None:
        instance = self._read()

        self.assertEqual(instance.n_depots_read, 2)
        self.assertEqual(instance.n_depots, 2)
        self.assertEqual(instance.n_stations_read, 2)
        self.assertEqual(instance.n_stations, 2)
        self.assertEqual(instance.n_depot_products, 3)
        self.assertEqual(instance.n_requests, 3)
        self.assertIs(instance.station_products, instance.requests)
        self.assertEqual(instance.depots[0].stocks, [50, 0, 70])
        self.assertEqual(instance.stations[0].demand, [0, 15, 20])
        self.assertEqual(
            [(node.depot_id, node.product_id, node.stock) for node in instance.depot_products],
            [(1, 1, 50), (1, 3, 70), (2, 2, 60)],
        )
        self.assertEqual(
            [(node.station_id, node.product_id, node.demand) for node in instance.requests],
            [(1, 2, 15), (1, 3, 20), (2, 1, 5)],
        )

    def test_ids_and_products_remain_one_based_and_vehicle_is_linked(self) -> None:
        instance = self._read()

        self.assertEqual([node.id for node in instance.depot_products], [1, 1, 2])
        self.assertEqual([node.id for node in instance.requests], [1, 1, 2])
        self.assertEqual([node.product_id for node in instance.depot_products], [1, 3, 2])
        self.assertEqual([node.product_id for node in instance.requests], [2, 3, 1])
        self.assertEqual([node.global_id for node in instance.nodes], list(range(7)))
        self.assertIs(instance.vehicles[0].start_g, instance.garages[0])
        self.assertEqual(instance.vehicles[0].init_prod, 2)
        self.assertEqual(instance.dist_matrix, [])

    def test_distance_matrix_can_be_built_explicitly(self) -> None:
        instance = self._read()
        instance.build_distance_matrix()

        self.assertEqual(len(instance.dist_matrix), 7)
        # Depot 1 (0, 0) to garage (0, 4), and station 2 (3, 0).
        self.assertEqual(instance.dist_matrix[0][3], 4)
        self.assertEqual(instance.dist_matrix[0][6], 3)
        # Co-located product nodes have zero distance.
        self.assertEqual(instance.dist_matrix[0][1], 0)
        self.assertEqual(instance.dist_matrix[4][5], 0)


if __name__ == "__main__":
    unittest.main()
