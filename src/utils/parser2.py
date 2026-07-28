from __future__ import annotations

import math
from pathlib import Path
from typing import List, cast

from .schemas import MPVRPNode, GarageNode, DepotNode, RequestNode, Vehicle

# Node Type Constants
REQUEST = 0
GARAGE = 1
DEPOT = 2
INF = math.inf

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

        # Matrix storing static arc costs independent of vehicle
        self.arc_cost: List[List[float]] = []

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
        temp_vehicles: List[tuple[int, float, int]] = []  # (id, capacity, init_prod)
        for _ in range(inst.n_vehicles):
            v_id = next_int()
            capacity = next_float()
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
                stock = next_float()
                if stock > 0:
                    node = DepotNode(
                        id=d_id,
                        global_id=current_global_id,
                        x=x,
                        y=y,
                        product=p,
                        stock=stock,
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
                y=y,
            )
            inst.garages.append(node)
            current_global_id += 1

        # Stations -> Create RequestNode for each positive demand
        for _ in range(inst.n_stations):
            s_id = next_int()
            x = next_float()
            y = next_float()
            for p in range(inst.n_prods):
                demand = next_float()
                if demand > 0:
                    node = RequestNode(
                        id=s_id,
                        global_id=current_global_id,
                        x=x,
                        y=y,
                        product=p,
                        demand=demand,
                    )
                    inst.requests.append(node)
                    current_global_id += 1

        # Combine all graph nodes in indexed order
        inst.nodes = (
            cast(List[MPVRPNode], inst.depots)
            + cast(List[MPVRPNode], inst.garages)
            + cast(List[MPVRPNode], inst.requests)
        )

        # Link vehicles with GarageNode entities
        garage_map = {g.id: g for g in inst.garages}
        for (v_id, cap, init_prod), g_id in zip(temp_vehicles, home_garage_ids):
            inst.vehicles.append(
                Vehicle(
                    id=v_id,
                    capacity=cap,
                    init_g=garage_map.get(g_id),
                    init_prod=init_prod,
                )
            )

        # Build base static arc cost matrix
        inst._build_arc_cost_matrix()

        return inst

    def _build_arc_cost_matrix(self) -> None:
        """
        Computes the arc cost matrix for a specific vehicle v, incorporating
        both distance and changeover costs according to domain transition rules.

        Returns `math.inf` for forbidden transitions.
        """
        nodes = self.nodes
        n = len(nodes)
        self.arc_cost = [[INF] * n for _ in range(n)]

        for i, ni in enumerate(nodes):
            for j, nj in enumerate(nodes):
                if i == j:
                    continue

                dist = ni.distance(nj)

                # type(i) = REQUEST AND type(j) = DEPOT
                if ni.type == REQUEST and nj.type == DEPOT:
                    assert isinstance(ni, RequestNode) and isinstance(nj, DepotNode)
                    self.arc_cost[i][j] = dist + self.changeover_cost[ni.product][nj.product]

                # type(i) = DEPOT AND type(j) = REQUEST AND prod(i) == prod(j)
                elif ni.type == DEPOT and nj.type == REQUEST:
                    assert isinstance(ni, DepotNode) and isinstance(nj, RequestNode)
                    if ni.product == nj.product:
                        self.arc_cost[i][j] = dist

                # type(i) = REQUEST AND type(j) = REQUEST AND prod(i) == prod(j)
                elif ni.type == REQUEST and nj.type == REQUEST:
                    assert isinstance(ni, RequestNode) and isinstance(nj, RequestNode)
                    if ni.product == nj.product:
                        self.arc_cost[i][j] = dist

                # type(i) = REQUEST AND j = G_v
                elif ni.type == REQUEST and nj.type == GARAGE:
                    self.arc_cost[i][j] = dist

                # i = G_v AND type(j) = DEPOT
                elif ni.type == GARAGE and nj.type == DEPOT:
                    self.arc_cost[i][j] = dist

    def vehicle_arc_cost(self, vehicle: Vehicle, i: MPVRPNode, j: MPVRPNode) -> float:
        """Compute arc cost from node i to node j for a specific vehicle, considering changeover costs."""
        if i.type == GARAGE and j.type == DEPOT:
            assert isinstance(j, DepotNode)
            dist = i.distance(j)
            return dist + self.changeover_cost[vehicle.init_prod][j.product]

        return self.arc_cost[i.global_id][j.global_id]

    def display(self) -> None:
        """Prints a concise summary of the parsed instance and its execution graph."""
        print(self.uuid)
        print(
            f"Products: {self.n_prods} | Depots (file): {self.n_depots} | "
            f"Garages: {self.n_garages} | Stations (file): {self.n_stations} | "
            f"Vehicles: {self.n_vehicles}"
        )
        print(
            f"Total nodes in graph: {len(self.nodes)} "
            f"({len(self.depots)} DepotNodes, {len(self.garages)} GarageNodes, {len(self.requests)} RequestNodes)"
        )
        print("-" * 70)

        print("\n--- CHANGEOVER COST MATRIX (PRODUCT x PRODUCT) ---")
        for p1, row in enumerate(self.changeover_cost):
            row_str = "  ".join(f"{val:6.2f}" for val in row)
            print(f"Prod {p1}: [{row_str}]")

        print("\n--- VEHICLE FLEET ---")
        for v in self.vehicles:
            g_id = v.init_g.id if v.init_g else -1
            print(
                f"Vehicle ID: {v.id:2d} | Capacity: {v.capacity:8.1f} | "
                f"Garage ID: {g_id:2d} | Initial Prod: {v.init_prod}"
            )

        print("\n--- DEPOT NODES (DepotNode) ---")
        for d in self.depots:
            print(
                f"GlobalID: {d.global_id:2d} | Depot ID: {d.id:2d} | "
                f"Pos: ({d.x:6.1f}, {d.y:6.1f}) | Prod: {d.product} | Stock: {d.stock:8.1f}"
            )

        print("\n--- GARAGE NODES (GarageNode) ---")
        for g in self.garages:
            print(
                f"GlobalID: {g.global_id:2d} | Garage ID: {g.id:2d} | "
                f"Pos: ({g.x:6.1f}, {g.y:6.1f})"
            )

        print("\n--- REQUEST NODES (RequestNode) ---")
        for r in self.requests:
            print(
                f"GlobalID: {r.global_id:2d} | Station ID: {r.id:2d} | "
                f"Pos: ({r.x:6.1f}, {r.y:6.1f}) | Prod: {r.product} | Demand: {r.demand:8.1f}"
            )

        # Count authorized transitions in the static graph
        valid_arcs = sum(
            1
            for row in self.arc_cost
            for val in row
            if val != INF
        )
        total_possible = len(self.nodes) * (len(self.nodes) - 1)
        print("\n--- ARC COST MATRIX (ARC_COST) ---")
        print(f"Allowed arcs: {valid_arcs} / {total_possible} possible transitions.")

if __name__ == "__main__":
    from pathlib import Path

    instance_file = Path("inst/MPVRP_002_s22_d5_p5.dat")
    instance = MPVRPInstance.read(instance_file)
    instance.display()