from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Mapping, Sequence

from mpvrp.models import MPVRPInstance

EPSILON = 1e-6


def _format_number(value: float) -> str:
    if abs(value - round(value)) <= EPSILON:
        return str(int(round(value)))
    return f"{value:.2f}"


def _processor_name() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _route_load(route: Mapping[str, Any]) -> float:
    return sum(float(delivery["quantity"]) for delivery in route.get("deliveries", []))


def _route_stations(route: Mapping[str, Any]) -> list[int]:
    path = route.get("path")
    if path:
        return [int(node[1:]) for node in path if isinstance(node, str) and node.startswith("S")]
    return [int(delivery["station"]) for delivery in route.get("deliveries", [])]


def _group_routes(routes: Sequence[Mapping[str, Any]]) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for route in routes:
        if _route_load(route) > EPSILON:
            grouped.setdefault(int(route["vehicle"]), []).append(route)
    for vehicle_routes in grouped.values():
        vehicle_routes.sort(key=lambda route: int(route.get("trip", 0)))
    return dict(sorted(grouped.items()))


def format_solution(
    instance: MPVRPInstance,
    routes: Sequence[Mapping[str, Any]],
    resolution_time: float,
    processor: str | None = None,
) -> str:
    """Return a solution in the repository's canonical text format."""
    grouped = _group_routes(routes)
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    depots = {depot.id: depot for depot in instance.depots}
    stations = {station.id: station for station in instance.stations}
    lines: list[str] = []
    changes = 0
    changeover_cost = 0.0
    distance = 0.0

    for vehicle_id, vehicle_routes in grouped.items():
        vehicle = vehicles[vehicle_id]
        current_product = vehicle.init_prod
        previous_node = vehicle.start_g
        visit_parts = [str(vehicle.start_g.id)]
        product_parts = [f"{current_product - 1}(0.00)"]
        cumulative_cost = 0.0

        for route in vehicle_routes:
            product = int(route["product"])
            if product != current_product:
                changes += 1
            cumulative_cost += instance.changeover_cost[current_product - 1][product - 1]
            changeover_cost += instance.changeover_cost[current_product - 1][product - 1]
            current_product = product

            depot = depots[int(route["start_depot"])]
            distance += round(previous_node.distance(depot))
            previous_node = depot
            visit_parts.append(f"{depot.id} [{_format_number(_route_load(route))}]")
            product_parts.append(f"{product - 1}({cumulative_cost:.2f})")

            quantities: dict[int, float] = {}
            for delivery in route.get("deliveries", []):
                station_id = int(delivery["station"])
                quantities[station_id] = quantities.get(station_id, 0.0) + float(delivery["quantity"])
            for station_id in _route_stations(route):
                quantity = quantities.get(station_id, 0.0)
                if quantity <= EPSILON:
                    continue
                station = stations[station_id]
                distance += round(previous_node.distance(station))
                previous_node = station
                visit_parts.append(f"{station_id} ({_format_number(quantity)})")
                product_parts.append(f"{product - 1}({cumulative_cost:.2f})")

        distance += round(previous_node.distance(vehicle.start_g))
        visit_parts.append(str(vehicle.start_g.id))
        lines.extend((f"{vehicle_id}: " + " - ".join(visit_parts), f"{vehicle_id}: " + " - ".join(product_parts), ""))

    lines.extend(
        (
            str(len(grouped)),
            str(changes),
            f"{changeover_cost:.2f}",
            f"{distance:.2f}",
            processor or _processor_name(),
            f"{resolution_time:.3f}",
        )
    )
    return "\n".join(lines) + "\n"


def write_solution(
    instance: MPVRPInstance,
    routes: Sequence[Mapping[str, Any]],
    filename: str | Path,
    resolution_time: float = 0.0,
    processor: str | None = None,
) -> Path:
    """Write a solution in the repository's canonical format."""
    filepath = Path(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        format_solution(instance, routes, resolution_time, processor),
        encoding="utf-8",
    )
    return filepath
