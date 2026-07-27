from __future__ import annotations

import math
from pathlib import Path
from typing import List, cast

from .schemas import MPVRPNode, GarageNode, DepotNode, RequestNode, Vehicle


class MPVRPInstance:
    def __init__(self):
        self.uuid: str = ""
        self.n_prods: int = 0
        self.n_depots: int = 0
        self.n_garages: int = 0
        self.n_stations: int = 0
        self.n_vehicles: int = 0

        self.changeover_cost: List[List[float]] = []
        self.vehicles: List[Vehicle] = []
        self.garages: List[GarageNode] = []
        self.depots: List[DepotNode] = []
        self.requests: List[RequestNode] = []
        self.nodes: List[MPVRPNode] = []

    @staticmethod
    def read(filename: str | Path) -> MPVRPInstance:
        inst = MPVRPInstance()
        filepath = Path(filename)

        def token_generator():
            with filepath.open("r", encoding="utf-8") as f:
                for line in f:
                    for word in line.split():
                        yield word

        tokens = token_generator()

        def next_token() -> str:
            return next(tokens)

        def next_int() -> int:
            return int(next_token())

        def next_float() -> float:
            return float(next_token())

        # Header: UUID
        next_token()  # Skip '#'
        inst.uuid = next_token()

        # Dimensions
        inst.n_prods = next_int()
        inst.n_depots = next_int()
        inst.n_garages = next_int()
        inst.n_stations = next_int()
        inst.n_vehicles = next_int()

        # Changeover cost matrix
        inst.changeover_cost = [
            [next_float() for _ in range(inst.n_prods)]
            for _ in range(inst.n_prods)
        ]

        # Vehicle fleet (store initial garage ID temporarily)
        home_garage_ids: List[int] = []
        temp_vehicles: List[tuple[int, int, int]] = []  # (id, capacity, init_prod)
        for _ in range(inst.n_vehicles):
            v_id = next_int()
            capacity = int(round(next_float()))
            home_garage_ids.append(next_int())
            init_prod = next_int() - 1  # 0-based product index
            temp_vehicles.append((v_id, capacity, init_prod))

        current_global_id = 0

        # Depots -> Create DepotNode for each positive stock
        for _ in range(inst.n_depots):
            d_id = next_int()
            x = next_float()
            y = next_float()
            for p in range(inst.n_prods):
                stock = int(round(next_float()))
                if stock > 0:
                    node = DepotNode(
                        id=d_id,
                        global_id=current_global_id,
                        x=x,
                        y=y,
                        product=p,
                        stock=stock
                    )
                    inst.depots.append(node)
                    current_global_id += 1

        # Garages -> Create GarageNode
        for _ in range(inst.n_garages):
            g_id = next_int()
            x = next_float()
            y = next_float()
            node = GarageNode(
                id=g_id,
                global_id=current_global_id,
                x=x,
                y=y
            )
            inst.garages.append(node)
            current_global_id += 1

        # Stations -> Create RequestNode for each positive demand
        for _ in range(inst.n_stations):
            s_id = next_int()
            x = next_float()
            y = next_float()
            for p in range(inst.n_prods):
                demand = int(round(next_float()))
                if demand > 0:
                    node = RequestNode(
                        id=s_id,
                        global_id=current_global_id,
                        x=x,
                        y=y,
                        product=p,
                        demand=demand
                    )
                    inst.requests.append(node)
                    current_global_id += 1

        # Combine all graph nodes in indexed order
        inst.nodes = cast(List[MPVRPNode], inst.depots) + cast(List[MPVRPNode], inst.garages) + cast(List[MPVRPNode], inst.requests)

        # Link vehicles with GarageNode entities
        garage_map = {g.id: g for g in inst.garages}
        for (v_id, cap, init_prod), g_id in zip(temp_vehicles, home_garage_ids):
            inst.vehicles.append(
                Vehicle(
                    id=v_id,
                    capacity=cap,
                    init_g=garage_map.get(g_id),
                    init_prod=init_prod
                )
            )

        return inst

    def compute_cost_matrix_for_vehicle(self, vehicle: Vehicle) -> List[List[float]]:
        """
        Computes the arc cost matrix for a specific vehicle v, incorporating
        both distance and changeover costs according to domain transition rules.

        Returns math.inf for forbidden transitions.
        """
        n = len(self.nodes)
        cost_matrix = [[math.inf] * n for _ in range(n)]

        for i_idx, i in enumerate(self.nodes):
            for j_idx, j in enumerate(self.nodes):
                if i_idx == j_idx:
                    continue

                # 1. i = G_v AND type(j) = DEPOT
                if i.type == 1 and isinstance(i, GarageNode) and i == vehicle.init_g and j.type == 2 and isinstance(j, DepotNode):
                    cost_matrix[i_idx][j_idx] = i.distance(j) + self.changeover_cost[vehicle.init_prod][j.product]

                # 2. type(i) = DEPOT AND type(j) = REQUEST AND prod(i) == prod(j)
                elif i.type == 2 and isinstance(i, DepotNode) and j.type == 0 and isinstance(j, RequestNode):
                    if i.product == j.product:
                        cost_matrix[i_idx][j_idx] = i.distance(j)

                # 3. type(i) = REQUEST AND j = G_v
                elif i.type == 0 and isinstance(i, RequestNode) and j.type == 1 and isinstance(j, GarageNode) and j == vehicle.init_g:
                    cost_matrix[i_idx][j_idx] = i.distance(j)

                # 4. type(i) = REQUEST AND type(j) = DEPOT
                elif i.type == 0 and isinstance(i, RequestNode) and j.type == 2 and isinstance(j, DepotNode):
                    cost_matrix[i_idx][j_idx] = i.distance(j) + self.changeover_cost[i.product][j.product]

                # 5. type(i) = REQUEST AND type(j) = REQUEST AND prod(i) == prod(j)
                elif i.type == 0 and isinstance(i, RequestNode) and j.type == 0 and isinstance(j, RequestNode):
                    if i.product == j.product:
                        cost_matrix[i_idx][j_idx] = i.distance(j)

        return cost_matrix