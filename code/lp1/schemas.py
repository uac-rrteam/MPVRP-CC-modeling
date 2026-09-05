from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MPVRPNode:
    id: int
    global_id: int
    x: int
    y: int

    def distance(self, other: MPVRPNode) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    @property
    def type(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class StationNode(MPVRPNode):
    demand: list[int]

    @property
    def type(self) -> int:
        return 0


@dataclass(frozen=True)
class GarageNode(MPVRPNode):
    @property
    def type(self) -> int:
        return 1


@dataclass(frozen=True)
class DepotNode(MPVRPNode):
    stocks: list[int]

    @property
    def type(self) -> int:
        return 2


@dataclass(frozen=True)
class Vehicle:
    id: int
    capacity: int
    start_g: GarageNode | None
    init_prod: int


@dataclass(frozen=True)
class MilpSolution:
    objective: int
    best_bound: float
    mip_gap: float
    node_count: int
    solver_runtime: float
    status: int
    routes: list[dict]


class MPVRPInstance:
    def __init__(self) -> None:
        self.uuid: str = ""
        self.n_prods: int = 0
        self.n_depots: int = 0
        self.n_garages: int = 0
        self.n_stations: int = 0
        self.n_vehicles: int = 0
        self.changeover_cost: list[list[int]] = []
        self.vehicles: list[Vehicle] = []
        self.stations: list[StationNode] = []
        self.depots: list[DepotNode] = []
        self.garages: list[GarageNode] = []
        self.dist_matrix: list[list[int]] = []
        self.source_path: Path | None = None
        self.instance_id: str = "unknown"

    @staticmethod
    def read(filename: str | Path) -> MPVRPInstance:
        """Compatibility entry point for the LP1 instance parser."""
        from lp1.io.inst import read_instance

        return read_instance(filename)

    def link_vehicles(self, garage_ids: list[int]) -> None:
        for index, target_id in enumerate(garage_ids):
            garage = next((item for item in self.garages if item.id == target_id), None)
            vehicle = self.vehicles[index]
            self.vehicles[index] = Vehicle(
                vehicle.id,
                vehicle.capacity,
                garage,
                vehicle.init_prod,
            )

    def build_distance_matrix(self) -> None:
        all_nodes = self.depots + self.garages + self.stations
        self.dist_matrix = [
            [int(round(origin.distance(destination))) for destination in all_nodes]
            for origin in all_nodes
        ]

    def display(self) -> None:
        print(f"UUID: {self.uuid}")
        print(
            f"Prods:{self.n_prods} Depots:{self.n_depots} "
            f"Garages:{self.n_garages} Stations:{self.n_stations} "
            f"Vehicles:{self.n_vehicles}"
        )
        for row in self.changeover_cost:
            print("\t".join(map(str, row)))
        for vehicle in self.vehicles:
            garage_id = vehicle.start_g.id if vehicle.start_g else -1
            print(
                f"ID:{vehicle.id} | Cap:{vehicle.capacity} | "
                f"GarageID:{garage_id} | InitProd:{vehicle.init_prod}"
            )
        for depot in self.depots:
            print(f"ID:{depot.id} | X:{depot.x} Y:{depot.y} | Stocks: {' '.join(map(str, depot.stocks))}")
        for garage in self.garages:
            print(f"ID:{garage.id} | X:{garage.x} Y:{garage.y}")
        for station in self.stations:
            print(
                f"ID:{station.id} | X:{station.x} Y:{station.y} | "
                f"Requests: {' '.join(map(str, station.demand))}"
            )
