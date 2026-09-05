import platform
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.paths import WITH_CHANGEOVER_INSTANCES_DIR, WITH_CHANGEOVER_SOLUTIONS_DIR
from lp1.schemas import MPVRPInstance, MPVRPNode

DEFAULT_INSTANCE_PATH = WITH_CHANGEOVER_INSTANCES_DIR / "MPVRP_005_s36_d1_p3.dat"
DEFAULT_SOLUTIONS_DIR = WITH_CHANGEOVER_SOLUTIONS_DIR
EPSILON = 1e-6
def _format_number(value: float) -> str:
    if abs(value - round(value)) <= EPSILON:
        return str(int(round(value)))
    return f"{value:.2f}"


def _format_cost(value: float) -> str:
    return f"{value:.2f}"


def _processor_name() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _by_id(nodes: Sequence[MPVRPNode]) -> dict[int, MPVRPNode]:
    return {node.id: node for node in nodes}


def _route_product(route: Mapping[str, Any]) -> int:
    return int(route["product"])


def _route_load(route: Mapping[str, Any]) -> float:
    return sum(float(delivery["quantity"]) for delivery in route.get("deliveries", []))


def _route_delivery_by_station(route: Mapping[str, Any]) -> dict[int, float]:
    quantities: dict[int, float] = {}
    for delivery in route.get("deliveries", []):
        station_id = int(delivery["station"])
        quantities[station_id] = quantities.get(station_id, 0.0) + float(delivery["quantity"])
    return quantities


def _route_station_order(route: Mapping[str, Any]) -> list[int]:
    path = route.get("path")
    if path:
        station_ids = []
        for node in path:
            if isinstance(node, str) and node.startswith("S"):
                station_ids.append(int(node[1:]))
        return station_ids

    return [int(delivery["station"]) for delivery in route.get("deliveries", [])]


def _vehicle_routes(routes: Sequence[Mapping[str, Any]]) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for route in routes:
        if _route_load(route) <= EPSILON:
            continue
        grouped.setdefault(int(route["vehicle"]), []).append(route)

    for vehicle_routes in grouped.values():
        vehicle_routes.sort(key=lambda item: int(item.get("trip", 0)))
    return dict(sorted(grouped.items()))


def _solution_distance(instance: MPVRPInstance, grouped_routes: Mapping[int, Sequence[Mapping[str, Any]]]) -> float:
    depots = _by_id(instance.depots)
    stations = _by_id(instance.stations)
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    total = 0.0

    for vehicle_id, routes in grouped_routes.items():
        if not routes:
            continue

        vehicle = vehicles[vehicle_id]
        previous_node: MPVRPNode = vehicle.start_g

        for route in routes:
            start_depot = depots[int(route["start_depot"])]
            total += round(previous_node.distance(start_depot))

            previous_node = start_depot
            for station_id in _route_station_order(route):
                station = stations[station_id]
                total += round(previous_node.distance(station))
                previous_node = station

        total += round(previous_node.distance(vehicle.start_g))

    return total


def _changeover_metrics(
        instance: MPVRPInstance,
        grouped_routes: Mapping[int, Sequence[Mapping[str, Any]]],
) -> tuple[int, float]:
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    changes = 0
    cost = 0.0

    for vehicle_id, routes in grouped_routes.items():
        current_product = vehicles[vehicle_id].init_prod
        for route in routes:
            next_product = _route_product(route)
            if next_product != current_product:
                changes += 1
            cost += instance.changeover_cost[current_product - 1][next_product - 1]
            current_product = next_product

    return changes, cost


def format_solution(
        instance: MPVRPInstance,
        routes: Sequence[Mapping[str, Any]],
        resolution_time: float,
        processor: str | None = None,
) -> str:
    grouped_routes = _vehicle_routes(routes)
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    lines: list[str] = []

    for vehicle_id, vehicle_routes in grouped_routes.items():
        if not vehicle_routes:
            continue

        vehicle = vehicles[vehicle_id]
        visit_parts = [str(vehicle.start_g.id)]
        product_parts = [f"{vehicle.init_prod - 1}({_format_cost(0.0)})"]
        current_product = vehicle.init_prod
        cumulative_changeover_cost = 0.0

        for route in vehicle_routes:
            product = _route_product(route)
            cumulative_changeover_cost += instance.changeover_cost[current_product - 1][product - 1]
            current_product = product

            product_label = product - 1
            visit_parts.append(f"{int(route['start_depot'])} [{_format_number(_route_load(route))}]")
            product_parts.append(f"{product_label}({_format_cost(cumulative_changeover_cost)})")

            delivery_by_station = _route_delivery_by_station(route)
            for station_id in _route_station_order(route):
                quantity = delivery_by_station.get(station_id, 0.0)
                if quantity <= EPSILON:
                    continue
                visit_parts.append(f"{station_id} ({_format_number(quantity)})")
                product_parts.append(f"{product_label}({_format_cost(cumulative_changeover_cost)})")

        visit_parts.append(str(vehicle.start_g.id))
        lines.append(f"{vehicle_id}: " + " - ".join(visit_parts))
        lines.append(f"{vehicle_id}: " + " - ".join(product_parts))
        lines.append("")

    number_of_changes, transition_cost = _changeover_metrics(instance, grouped_routes)
    total_distance = _solution_distance(instance, grouped_routes)
    metrics = [
        str(len(grouped_routes)),
        str(number_of_changes),
        _format_cost(transition_cost),
        _format_cost(total_distance),
        processor or _processor_name(),
        f"{resolution_time:.3f}",
    ]
    lines.extend(metrics)

    return "\n".join(lines) + "\n"


def write_solution(
        instance: MPVRPInstance,
        routes: Sequence[Mapping[str, Any]],
        filename: str | Path | None = None,
        resolution_time: float = 0.0,
        processor: str | None = None,
) -> Path:
    if filename is None:
        filename = _default_solution_filename(instance)

    filepath = Path(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(format_solution(instance, routes, resolution_time, processor))
    return filepath


def _default_solution_filename(instance: MPVRPInstance) -> Path:
    return DEFAULT_SOLUTIONS_DIR / (
        f"Sol_{instance.instance_id}"
        f"_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}.dat"
    )


if __name__ == "__main__":
    try:
        instance = MPVRPInstance.read(DEFAULT_INSTANCE_PATH)
        instance.display()
    except Exception as e:
        import traceback

        traceback.print_exc()
