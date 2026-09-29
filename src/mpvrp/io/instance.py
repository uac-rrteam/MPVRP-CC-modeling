from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from mpvrp.models import (
    Depot,
    DepotProductNode,
    GarageNode,
    MPVRPInstance,
    RequestNode,
    Station,
    Vehicle,
)


INSTANCE_FILENAME_RE = re.compile(r"^MPVRP_(?P<instance_id>.+?)_s\d+_d\d+_p\d+\.dat$")


def _tokens(filepath: Path) -> Iterator[str]:
    with filepath.open("r", encoding="utf-8") as instance_file:
        for line in instance_file:
            yield from line.split()


def read_instance(filename: str | Path) -> MPVRPInstance:
    """Read an instance and create its positive product-level graph nodes."""
    filepath = Path(filename)
    instance = MPVRPInstance()
    instance.source_path = filepath
    match = INSTANCE_FILENAME_RE.match(filepath.name)
    if match:
        instance.instance_id = match.group("instance_id")

    tokens = _tokens(filepath)

    def next_token() -> str:
        try:
            return next(tokens)
        except StopIteration as exc:
            raise ValueError(f"Unexpected end of instance file: {filepath}") from exc

    def next_number() -> int:
        token = next_token()
        try:
            return int(token)
        except ValueError as exc:
            raise ValueError(f"Expected an integer, found {token!r} in {filepath}") from exc

    if next_token() != "#":
        raise ValueError("The first instance token must be '#'.")
    instance.uuid = next_token()

    instance.n_prods = next_number()
    instance.n_depots_read = next_number()
    instance.n_garages = next_number()
    instance.n_stations_read = next_number()
    instance.n_vehicles = next_number()
    instance.n_depots = instance.n_depots_read
    instance.n_stations = instance.n_stations_read

    instance.changeover_cost = [
        [next_number() for _ in range(instance.n_prods)]
        for _ in range(instance.n_prods)
    ]

    home_garage_ids: list[int] = []
    for _ in range(instance.n_vehicles):
        vehicle_id = next_number()
        capacity = next_number()
        home_garage_ids.append(next_number())
        initial_product = next_number()
        instance.vehicles.append(Vehicle(vehicle_id, capacity, None, initial_product))

    global_id = 0
    for _ in range(instance.n_depots_read):
        depot_id = next_number()
        x = next_number()
        y = next_number()
        stocks: list[int] = []
        for product_id in range(1, instance.n_prods + 1):
            stock = next_number()
            stocks.append(stock)
            if stock > 0:
                instance.depot_products.append(
                    DepotProductNode(depot_id, global_id, x, y, product_id, stock)
                )
                global_id += 1
        instance.depots.append(Depot(depot_id, x, y, stocks))
    instance.n_depot_products = len(instance.depot_products)

    for _ in range(instance.n_garages):
        garage_id = next_number()
        x = next_number()
        y = next_number()
        instance.garages.append(GarageNode(garage_id, global_id, x, y))
        global_id += 1

    for _ in range(instance.n_stations_read):
        station_id = next_number()
        x = next_number()
        y = next_number()
        demands: list[int] = []
        for product_id in range(1, instance.n_prods + 1):
            demand = next_number()
            demands.append(demand)
            if demand > 0:
                instance.requests.append(
                    RequestNode(station_id, global_id, x, y, product_id, demand)
                )
                global_id += 1
        instance.stations.append(Station(station_id, x, y, demands))
    instance.n_requests = len(instance.requests)

    try:
        trailing_token = next(tokens)
    except StopIteration:
        trailing_token = None
    if trailing_token is not None:
        raise ValueError(f"Unexpected trailing token {trailing_token!r} in {filepath}")

    instance.link_vehicles(home_garage_ids)
    return instance
