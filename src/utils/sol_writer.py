from __future__ import annotations

import math
import platform
from pathlib import Path
from typing import Any, Mapping, Sequence

from .parser2 import MPVRPInstance
from .schemas import DepotNode, GarageNode, RequestNode, Vehicle

EPSILON = 1e-6
DEFAULT_SOLUTIONS_DIR = Path(__file__).resolve().parents[2] / "sol"


# =========================================================================
# Helpers de formatage
# =========================================================================

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


# =========================================================================
# Lookups par (id physique, produit 0-based)
#
# Avec le nouveau parser, `instance.depots` / `instance.requests` contiennent
# un noeud par (entité, produit) : plusieurs noeuds peuvent partager le même
# `id` physique (un même dépôt pour deux produits différents). On ne peut
# donc plus indexer par `id` seul comme avant — il faut la paire (id, produit).
# =========================================================================

def _by_id_product(nodes: Sequence[DepotNode] | Sequence[RequestNode]) -> dict[tuple[int, int], Any]:
    return {(node.id, node.product): node for node in nodes}


def _route_product(route: Mapping[str, Any]) -> int:
    return int(route["product"])  # 1-based, comme dans le fichier solution


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


# =========================================================================
# Distance et changeover
#
# Il n'y a plus de noeud "end_depot" distinct : la dernière requête d'un trip
# est reliée DIRECTEMENT au dépôt de départ du trip suivant (règle de domaine
# Request -> Depot), et la dernière requête du dernier trip est reliée
# directement au garage. On ne rajoute donc plus le saut "station -> end_depot
# -> prochain start_depot" comme dans l'ancienne version.
# =========================================================================

def _solution_distance(instance: MPVRPInstance, grouped_routes: Mapping[int, Sequence[Mapping[str, Any]]]) -> float:
    depots_by_key = _by_id_product(instance.depots)
    requests_by_key = _by_id_product(instance.requests)
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    total = 0.0

    for vehicle_id, routes in grouped_routes.items():
        if not routes:
            continue

        vehicle = vehicles[vehicle_id]
        previous_node = vehicle.init_g

        for route in routes:
            product0 = _route_product(route) - 1  # reconvertir en 0-based pour le lookup
            start_depot = depots_by_key[(int(route["start_depot"]), product0)]
            total += previous_node.distance(start_depot)
            previous_node = start_depot

            for station_id in _route_station_order(route):
                station = requests_by_key[(station_id, product0)]
                total += previous_node.distance(station)
                previous_node = station

        total += previous_node.distance(vehicle.init_g)

    return total


def _changeover_metrics(
        instance: MPVRPInstance,
        grouped_routes: Mapping[int, Sequence[Mapping[str, Any]]],
) -> tuple[int, float]:
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    changes = 0
    cost = 0.0

    for vehicle_id, routes in grouped_routes.items():
        # vehicle.init_prod est 0-based (nouveau parser) ; on travaille en 1-based
        # ici pour rester cohérent avec route["product"].
        current_product = vehicles[vehicle_id].init_prod + 1
        for route in routes:
            next_product = _route_product(route)
            if next_product != current_product:
                changes += 1
                cost += instance.changeover_cost[current_product - 1][next_product - 1]
            current_product = next_product

    return changes, cost


# =========================================================================
# Écriture du fichier solution
# =========================================================================

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
        visit_parts = [str(vehicle.init_g.id)]
        # vehicle.init_prod est déjà 0-based, donc affiché directement (pas de -1).
        product_parts = [f"{vehicle.init_prod}({_format_cost(0.0)})"]
        current_product = vehicle.init_prod + 1  # 1-based pour comparer à route["product"]
        cumulative_changeover_cost = 0.0

        for route in vehicle_routes:
            product = _route_product(route)
            if product != current_product:
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

        visit_parts.append(str(vehicle.init_g.id))
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
    # `instance_id` n'existe pas dans parser2.MPVRPInstance (pas de regex sur le
    # nom de fichier) : on retombe sur l'uuid si l'attribut est absent.
    instance_id = getattr(instance, "instance_id", None) or instance.uuid
    return DEFAULT_SOLUTIONS_DIR / (
        f"Sol_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}_{instance_id}.dat"
    )