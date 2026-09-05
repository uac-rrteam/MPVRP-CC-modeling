from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from lp1.schemas import DepotNode, GarageNode, MPVRPInstance, StationNode, Vehicle


INSTANCE_FILENAME_RE = re.compile(r"^MPVRP_(?P<instance_id>.+?)_s\d+_d\d+_p\d+\.dat$")


def _tokens(filepath: Path) -> Iterator[str]:
    with filepath.open("r", encoding="utf-8") as instance_file:
        for line in instance_file:
            yield from line.split()


def read_instance(filename: str | Path) -> MPVRPInstance:
    """Parse an instance file into the data structures used by LP1."""
    instance = MPVRPInstance()
    filepath = Path(filename)
    instance.source_path = filepath
    match = INSTANCE_FILENAME_RE.match(filepath.name)
    if match:
        instance.instance_id = match.group("instance_id")

    tokens = _tokens(filepath)

    def next_token() -> str:
        return next(tokens)

    def next_number() -> int:
        return int(next_token())

    next_token()  # UUID marker.
    instance.uuid = next_token()
    instance.n_prods = next_number()
    instance.n_depots = next_number()
    instance.n_garages = next_number()
    instance.n_stations = next_number()
    instance.n_vehicles = next_number()

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
    for _ in range(instance.n_depots):
        depot_id = next_number()
        x = next_number()
        y = next_number()
        stocks = [next_number() for _ in range(instance.n_prods)]
        instance.depots.append(DepotNode(depot_id, global_id, x, y, stocks))
        global_id += 1

    for _ in range(instance.n_garages):
        garage_id = next_number()
        x = next_number()
        y = next_number()
        instance.garages.append(GarageNode(garage_id, global_id, x, y))
        global_id += 1

    for _ in range(instance.n_stations):
        station_id = next_number()
        x = next_number()
        y = next_number()
        demand = [next_number() for _ in range(instance.n_prods)]
        instance.stations.append(StationNode(station_id, global_id, x, y, demand))
        global_id += 1

    instance.link_vehicles(home_garage_ids)
    instance.build_distance_matrix()
    return instance
