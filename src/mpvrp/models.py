from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


class NodeType(IntEnum):
    STATION = 0
    GARAGE = 1
    DEPOT = 2


@dataclass(frozen=True)
class Depot:
    """A physical depot as represented in the instance file."""

    id: int
    x: int
    y: int
    stocks: list[int]

    def distance(self, other: Station | MPVRPNode) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class Station:
    """A physical station as represented in the instance file."""

    id: int
    x: int
    y: int
    demand: list[int]

    def distance(self, other: Depot | MPVRPNode) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class MPVRPNode:
    """Base node in the expanded MILP execution graph."""

    id: int
    global_id: int
    x: int
    y: int

    def distance(self, other: MPVRPNode) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    @property
    def type(self) -> NodeType:
        raise NotImplementedError

    @property
    def product(self) -> int:
        return -1


@dataclass(frozen=True)
class RequestNode(MPVRPNode):
    """A physical station's positive demand for one product."""

    product_id: int
    demand: int

    @property
    def type(self) -> NodeType:
        return NodeType.STATION

    @property
    def product(self) -> int:
        return self.product_id

    @property
    def station_id(self) -> int:
        return self.id


@dataclass(frozen=True)
class GarageNode(MPVRPNode):
    @property
    def type(self) -> NodeType:
        return NodeType.GARAGE


@dataclass(frozen=True)
class DepotProductNode(MPVRPNode):
    """A physical depot's positive stock for one product."""

    product_id: int
    stock: int

    @property
    def type(self) -> NodeType:
        return NodeType.DEPOT

    @property
    def product(self) -> int:
        return self.product_id

    @property
    def depot_id(self) -> int:
        return self.id


StationProductNode = RequestNode


@dataclass(frozen=True)
class Vehicle:
    id: int
    capacity: int
    start_g: GarageNode | None
    init_prod: int


class MPVRPInstance:
    """Physical input entities and their product-level execution graph."""

    def __init__(self) -> None:
        self.uuid: str = ""
        self.n_prods: int = 0
        self.n_depots_read: int = 0
        self.n_depots: int = 0
        self.n_depot_products: int = 0
        self.n_garages: int = 0
        self.n_stations_read: int = 0
        self.n_stations: int = 0
        self.n_requests: int = 0
        self.n_vehicles: int = 0

        self.changeover_cost: list[list[int]] = []
        self.vehicles: list[Vehicle] = []
        self.requests: list[RequestNode] = []
        self.depot_products: list[DepotProductNode] = []
        self.garages: list[GarageNode] = []
        self.depots: list[Depot] = []
        self.stations: list[Station] = []

        self.dist_matrix: list[list[int]] = []
        self.source_path: Path | None = None
        self.instance_id: str = "unknown"

    @property
    def station_products(self) -> list[RequestNode]:
        return self.requests

    @property
    def nodes(self) -> list[MPVRPNode]:
        """All expanded graph nodes in global-id order."""
        return [*self.depot_products, *self.garages, *self.requests]

    @staticmethod
    def read(filename: str | Path) -> MPVRPInstance:
        from mpvrp.io.instance import read_instance

        return read_instance(filename)

    def link_vehicles(self, garage_ids: list[int]) -> None:
        if len(garage_ids) != len(self.vehicles):
            raise ValueError("Each vehicle must have exactly one home garage.")

        garages_by_id = {garage.id: garage for garage in self.garages}
        for index, garage_id in enumerate(garage_ids):
            try:
                garage = garages_by_id[garage_id]
            except KeyError as exc:
                raise ValueError(f"Unknown home garage id {garage_id}.") from exc
            vehicle = self.vehicles[index]
            self.vehicles[index] = Vehicle(
                vehicle.id,
                vehicle.capacity,
                garage,
                vehicle.init_prod,
            )

    def build_distance_matrix(self) -> None:
        nodes = self.nodes
        if any(node.global_id != index for index, node in enumerate(nodes)):
            raise ValueError("Node global ids must match distance-matrix order.")
        self.dist_matrix = [
            [int(round(origin.distance(destination))) for destination in nodes]
            for origin in nodes
        ]

    def display(self) -> None:
        print(f"UUID: {self.uuid}")
        print(
            f"Prods:{self.n_prods} Depots:{self.n_depots} "
            f"DepotProducts:{self.n_depot_products} Garages:{self.n_garages} "
            f"Stations:{self.n_stations} Requests:{self.n_requests} "
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
            print(
                f"Depot ID:{depot.id} | X:{depot.x} Y:{depot.y} | "
                f"Stocks: {' '.join(map(str, depot.stocks))}"
            )
        for depot_product in self.depot_products:
            print(
                f"DepotProduct ID:{depot_product.id} | GlobalID:{depot_product.global_id} | "
                f"Product:{depot_product.product_id} | Stock:{depot_product.stock}"
            )
        for garage in self.garages:
            print(f"Garage ID:{garage.id} | X:{garage.x} Y:{garage.y}")
        for station in self.stations:
            print(
                f"Station ID:{station.id} | X:{station.x} Y:{station.y} | "
                f"Demand: {' '.join(map(str, station.demand))}"
            )
        for request in self.requests:
            print(
                f"Request ID:{request.id} | GlobalID:{request.global_id} | "
                f"Product:{request.product_id} | Demand:{request.demand}"
            )
