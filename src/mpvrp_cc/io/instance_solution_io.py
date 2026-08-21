import math
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

from mpvrp_cc.paths import WITH_CHANGEOVER_INSTANCES_DIR, WITH_CHANGEOVER_SOLUTIONS_DIR

DEFAULT_INSTANCE_PATH = WITH_CHANGEOVER_INSTANCES_DIR / "MPVRP_005_s36_d1_p3.dat"
DEFAULT_SOLUTIONS_DIR = WITH_CHANGEOVER_SOLUTIONS_DIR
EPSILON = 1e-6
INSTANCE_FILENAME_RE = re.compile(r"^MPVRP_(?P<instance_id>.+?)_s\d+_d\d+_p\d+\.dat$")


@dataclass(frozen=True)
class MPVRPNode:
    id: int
    global_id: int
    x: int
    y: int

    def distance(self, other: 'MPVRPNode') -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    @property
    def type(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class StationNode(MPVRPNode):
    demand: List[int]

    @property
    def type(self) -> int: return 0


@dataclass(frozen=True)
class GarageNode(MPVRPNode):
    @property
    def type(self) -> int: return 1


@dataclass(frozen=True)
class DepotNode(MPVRPNode):
    stocks: List[int]

    @property
    def type(self) -> int: return 2


@dataclass(frozen=True)
class Vehicle:
    id: int
    capacity: int
    start_g: Optional[GarageNode]
    init_prod: int


class MPVRPInstance:
    def __init__(self):
        self.uuid: str = ""
        self.n_prods: int = 0
        self.n_depots: int = 0
        self.n_garages: int = 0
        self.n_stations: int = 0
        self.n_vehicles: int = 0
        self.changeover_cost: List[List[int]] = []
        self.vehicles: List[Vehicle] = []
        self.stations: List[StationNode] = []
        self.depots: List[DepotNode] = []
        self.garages: List[GarageNode] = []
        # Integer matrix intended for constraint-programming models. The MILP
        # still calls MPVRPNode.distance() to use exact Euclidean distances.
        self.dist_matrix: List[List[int]] = []
        self.source_path: Optional[Path] = None
        self.instance_id: str = "unknown"

    @staticmethod
    def read(filename: str | Path) -> 'MPVRPInstance':
        inst = MPVRPInstance()
        filepath = Path(filename)
        inst.source_path = filepath
        match = INSTANCE_FILENAME_RE.match(filepath.name)
        if match:
            inst.instance_id = match.group("instance_id")

        def token_generator():
            with filepath.open('r') as f:
                for line in f:
                    for word in line.split():
                        yield word

        tokens = token_generator()

        def next_token():
            return next(tokens)

        def next_number() -> int:
            """Parse one strict integer instance value."""
            return int(next_token())

        # Lecture des entêtes
        next_token()  # Skip the first string (uuid prefix/hash)
        inst.uuid = next_token()
        inst.n_prods = int(next_token())
        inst.n_depots = int(next_token())
        inst.n_garages = int(next_token())
        inst.n_stations = int(next_token())
        inst.n_vehicles = int(next_token())

        # Matrice de changement (changeoverCost)
        inst.changeover_cost = [[next_number() for _ in range(inst.n_prods)] for _ in range(inst.n_prods)]

        # Flotte de véhicules
        home_garage_ids = []
        for _ in range(inst.n_vehicles):
            v_id = int(next_token())
            capacity = next_number()
            home_garage_ids.append(int(next_token()))
            init_prod = int(next_token())
            inst.vehicles.append(Vehicle(v_id, capacity, None, init_prod))

        current_global_id = 0

        # Dépôts
        for _ in range(inst.n_depots):
            d_id = int(next_token())
            x = next_number()
            y = next_number()
            stocks = [next_number() for _ in range(inst.n_prods)]
            inst.depots.append(DepotNode(d_id, current_global_id, x, y, stocks))
            current_global_id += 1

        # Garages
        for _ in range(inst.n_garages):
            g_id = int(next_token())
            x = next_number()
            y = next_number()
            inst.garages.append(GarageNode(g_id, current_global_id, x, y))
            current_global_id += 1

        # Stations
        for _ in range(inst.n_stations):
            s_id = int(next_token())
            x = next_number()
            y = next_number()
            demand = [next_number() for _ in range(inst.n_prods)]
            inst.stations.append(StationNode(s_id, current_global_id, x, y, demand))
            current_global_id += 1

        # Post-traitement
        inst._link_vehicles(home_garage_ids)
        inst._build_distance_matrix()

        return inst

    def _link_vehicles(self, garage_ids: List[int]):
        for i in range(self.n_vehicles):
            target_id = garage_ids[i]
            # Recherche du garage correspondant
            garage = next((g for g in self.garages if g.id == target_id), None)
            v = self.vehicles[i]
            # Les dataclasses étant frozen, on recrée l'objet
            self.vehicles[i] = Vehicle(v.id, v.capacity, garage, v.init_prod)

    def _build_distance_matrix(self):
        all_nodes = self.depots + self.garages + self.stations
        size = len(all_nodes)
        self.dist_matrix = [[0 for _ in range(size)] for _ in range(size)]

        for i in range(size):
            for j in range(size):
                self.dist_matrix[i][j] = int(round(all_nodes[i].distance(all_nodes[j])))

    def display(self):
        print(f"UUID: {self.uuid}")
        print(f"Prods:{self.n_prods} Depots:{self.n_depots} Garages:{self.n_garages} "
              f"Stations:{self.n_stations} Vehicles:{self.n_vehicles}")

        for row in self.changeover_cost:
            print("\t".join(map(str, row)))

        for v in self.vehicles:
            g_id = v.start_g.id if v.start_g else -1
            print(f"ID:{v.id} | Cap:{v.capacity} | GarageID:{g_id} | InitProd:{v.init_prod}")

        for d in self.depots:
            stocks_str = " ".join(map(str, d.stocks))
            print(f"ID:{d.id} | X:{d.x} Y:{d.y} | Stocks: {stocks_str}")

        for g in self.garages:
            print(f"ID:{g.id} | X:{g.x} Y:{g.y}")

        for s in self.stations:
            demand_str = " ".join(map(str, s.demand))
            print(f"ID:{s.id} | X:{s.x} Y:{s.y} | Requests: {demand_str}")


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
            total += previous_node.distance(start_depot)

            previous_node = start_depot
            for station_id in _route_station_order(route):
                station = stations[station_id]
                total += previous_node.distance(station)
                previous_node = station

            end_depot = depots[int(route.get("end_depot", route["start_depot"]))]
            total += previous_node.distance(end_depot)
            previous_node = end_depot

        total += previous_node.distance(vehicle.start_g)

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
