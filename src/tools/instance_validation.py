from __future__ import annotations

import sys
from math import ceil

import numpy as np

from src.tools.instance_schema import (
    EPSILON, GenerationConfig, InstanceData, ParsedInstance, PROJECT_ROOT, VerificationReport
)
from src.utils.parser import MPVRPInstance

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))



def validate_generation_config(config: GenerationConfig) -> VerificationReport:
    """Validate generator options before any random instance data is created."""
    report = VerificationReport()
    for name, value in {
        "vehicles": config.vehicles,
        "depots": config.depots,
        "garages": config.garages,
        "stations": config.stations,
        "products": config.products,
    }.items():
        if value < 1:
            report.error(f"{name} must be at least 1.")

    if config.grid_size <= 0:
        report.error("grid_size must be positive.")
    if not 0 < config.demand_probability <= 1:
        report.error("demand_probability must be in (0, 1].")
    if config.changeover_cost_level not in {"low", "normal", "high", "mixed"}:
        report.error("changeover_cost_level must be one of: low, normal, high, mixed.")
    if config.capacity_level not in {"low", "medium", "large", "mixed"}:
        report.error("capacity_level must be one of: low, medium, large, mixed.")
    if config.demand_level not in {"low", "medium", "high", "mixed"}:
        report.error("demand_level must be one of: low, medium, high, mixed.")
    if config.stock_level not in {"low", "medium", "high", "mixed"}:
        report.error("stock_level must be one of: low, medium, high, mixed.")
    if config.coordinate_strategy not in {"uniform", "clustered", "corridor"}:
        report.error("coordinate_strategy must be one of: uniform, clustered, corridor.")
    if config.min_point_distance > config.grid_size:
        report.warning("min_point_distance is larger than the grid; coordinate retries may be exhausted.")
    return report


def validate_instance_data(data: InstanceData) -> VerificationReport:
    """Validate an in-memory instance against parser and LP feasibility rules."""
    report = VerificationReport()
    nb_p, nb_d, nb_g, nb_s, nb_v = [int(value) for value in data.params]
    expected_shapes = {
        "transition_costs": ((nb_p, nb_p), data.transition_costs.shape),
        "vehicles": ((nb_v, 4), data.vehicles.shape),
        "depots": ((nb_d, 3 + nb_p), data.depots.shape),
        "garages": ((nb_g, 3), data.garages.shape),
        "stations": ((nb_s, 3 + nb_p), data.stations.shape),
    }
    for name, (expected, actual) in expected_shapes.items():
        if actual != expected:
            report.error(f"{name} shape is {actual}; expected {expected}.")
    if report.errors:
        return report

    for name, rows, count in (
        ("Vehicle", data.vehicles, nb_v),
        ("Depot", data.depots, nb_d),
        ("Garage", data.garages, nb_g),
        ("Station", data.stations, nb_s),
    ):
        _check_ids(name, rows, count, report)

    _check_matrix(data, report)

    if np.any(data.vehicles[:, 1] <= EPSILON):
        report.error("Vehicle capacities must be positive.")
    if not set(data.vehicles[:, 2].astype(int)).issubset(set(range(1, nb_g + 1))):
        report.error("Every vehicle home garage must reference an existing garage.")
    if not set(data.vehicles[:, 3].astype(int)).issubset(set(range(1, nb_p + 1))):
        report.error("Every vehicle initial product must be in [1, NbProducts].")

    _check_nonnegative("Depot stocks", data.depots[:, 3:], report)
    _check_nonnegative("Station demands", data.stations[:, 3:], report)
    if np.any(data.stations[:, 3:].sum(axis=1) <= EPSILON):
        report.error("Every station must have at least one positive demand.")

    total_stock = data.depots[:, 3:].sum(axis=0)
    total_demand = data.stations[:, 3:].sum(axis=0)
    for product_idx, (stock, demand) in enumerate(zip(total_stock, total_demand), start=1):
        if demand <= EPSILON:
            report.warning(f"Product {product_idx} has no demand.")
        if stock + EPSILON < demand:
            report.error(f"Product {product_idx}: total stock {stock:.2f} < total demand {demand:.2f}.")

    total_capacity = float(data.vehicles[:, 1].sum())
    if total_capacity <= EPSILON:
        report.error("Fleet has no usable capacity.")
    else:
        for station in data.stations:
            station_id = int(station[0])
            for product_idx, demand in enumerate(station[3:], start=1):
                if demand > total_capacity + EPSILON:
                    report.error(
                        f"Station {station_id}, product {product_idx}: demand {demand:.2f} exceeds "
                        f"total fleet capacity {total_capacity:.2f}. lp.py permits at most one visit "
                        "per vehicle for a station/product pair."
                    )

        _check_default_trip_bound_scenario(data, report)

    _check_geographic_overlap(data, report)
    return report


def validate_parsed_instance(instance: ParsedInstance) -> VerificationReport:
    """Validate a loaded file and confirm compatibility with the LP parser."""
    report = validate_instance_data(instance)
    report.infos.insert(0, f"UUID: {instance.uuid}")
    report.infos.insert(
        1,
        "Dimensions: "
        f"products={instance.nb_products}, depots={instance.nb_depots}, garages={instance.nb_garages}, "
        f"stations={instance.nb_stations}, vehicles={instance.nb_vehicles}.",
    )
    _check_lp_parser_compatibility(instance, report)
    return report


def _check_ids(name: str, rows: np.ndarray, count: int, report: VerificationReport) -> None:
    """Check that entity IDs are integer, unique, contiguous, and one-based."""
    ids = rows[:, 0]
    rounded = np.round(ids).astype(int)
    if not np.allclose(ids, rounded):
        report.error(f"{name} IDs must be integers.")
        return
    actual = set(rounded.tolist())
    expected = set(range(1, count + 1))
    if len(rounded) != len(actual):
        report.error(f"{name} IDs must be unique.")
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            report.error(f"{name} IDs missing: {missing}.")
        if extra:
            report.error(f"{name} IDs out of range: {extra}; expected [1, {count}].")


def _check_matrix(data: InstanceData, report: VerificationReport) -> None:
    """Validate transition costs and warn on unusual symmetric matrices."""
    matrix = data.transition_costs
    if not np.all(np.isfinite(matrix)):
        report.error("Transition costs must be finite.")
    if np.any(matrix < -EPSILON):
        report.error("Transition costs must be non-negative.")
    if not np.allclose(np.diag(matrix), 0.0):
        report.error("Transition cost diagonal must be zero.")
    if not np.allclose(matrix, matrix.T):
        return

    violations = []
    for i in range(data.nb_products):
        for k in range(data.nb_products):
            if i == k:
                continue
            for j in range(data.nb_products):
                if j in (i, k):
                    continue
                direct = matrix[i, k]
                indirect = matrix[i, j] + matrix[j, k]
                if direct > indirect + EPSILON:
                    violations.append((i + 1, j + 1, k + 1, direct, indirect))
    if violations:
        report.warning(
            f"Transition costs violate triangle inequality in {len(violations)} case(s); "
            "this is allowed by lp.py but may affect changeover incentives."
        )


def _check_nonnegative(name: str, values: np.ndarray, report: VerificationReport) -> None:
    """Check that an array contains no negative values."""
    if np.any(values < -EPSILON):
        report.error(f"{name} must be non-negative.")


def _check_default_trip_bound_scenario(data: InstanceData, report: VerificationReport) -> None:
    """Simulate necessary feasibility conditions for lp.py's default trip bound."""
    total_capacity = float(data.vehicles[:, 1].sum())
    product_demands = data.stations[:, 3:].sum(axis=0)
    total_demand = float(product_demands.sum())
    min_trips = _minimum_uniform_trip_bound(total_demand, total_capacity)
    report.info(f"Minimum uniform trip bound used by lp.py default: {min_trips}.")

    active_products = int(np.count_nonzero(product_demands > EPSILON))
    if min_trips < active_products:
        report.error(
            "Default LP trip bound is lower than the number of demanded products: "
            f"bound={min_trips}, demanded_products={active_products}. Each mini-route carries exactly one product."
        )

    total_slots = data.nb_vehicles * min_trips
    if total_slots < active_products:
        report.error(
            "Default LP trip slots cannot assign at least one mini-route to each demanded product: "
            f"vehicles * bound = {data.nb_vehicles} * {min_trips} = {total_slots}, "
            f"demanded_products={active_products}."
        )

    required_slots = _minimum_product_slots(data, product_demands)
    if required_slots > total_slots:
        report.error(
            "Default LP trip slots are insufficient for product-level capacity lower bounds: "
            f"required_slots={required_slots}, available_slots={total_slots}."
        )

    _simulate_product_capacity_scenarios(data, min_trips, report)


def _minimum_uniform_trip_bound(total_demand: float, total_capacity: float) -> int:
    """Return the same uniform per-vehicle trip bound used by models/lp.py."""
    if total_demand <= EPSILON:
        return 0
    return ceil(total_demand / total_capacity)


def _minimum_product_slots(data: InstanceData, product_demands: np.ndarray) -> int:
    """Estimate the minimum number of single-product trip slots needed."""
    max_vehicle_capacity = float(data.vehicles[:, 1].max())
    required = 0
    for product_idx, product_demand in enumerate(product_demands):
        if product_demand <= EPSILON:
            continue

        aggregate_slots = ceil(product_demand / max_vehicle_capacity)
        station_slots = max(
            _minimum_distinct_vehicle_slots(float(demand), data.vehicles[:, 1])
            for demand in data.stations[:, 3 + product_idx]
            if demand > EPSILON
        )
        required += max(1, aggregate_slots, station_slots)
    return required


def _minimum_distinct_vehicle_slots(demand: float, capacities: np.ndarray) -> int:
    """Find how many different vehicles are needed for one station/product demand."""
    remaining = demand
    for slots, capacity in enumerate(sorted(capacities, reverse=True), start=1):
        remaining -= float(capacity)
        if remaining <= EPSILON:
            return slots
    return len(capacities) + 1


def _simulate_product_capacity_scenarios(data: InstanceData, min_trips: int, report: VerificationReport) -> None:
    """Greedily test whether each product can fit into default trip capacity."""
    if min_trips < 1:
        return

    capacities = data.vehicles[:, 1].astype(float)
    for product_idx in range(data.nb_products):
        demands = [
            (int(station[0]), float(station[3 + product_idx]))
            for station in data.stations
            if station[3 + product_idx] > EPSILON
        ]
        if not demands:
            continue

        remaining_by_vehicle = [[float(capacity)] * min_trips for capacity in capacities]
        for station_id, demand in sorted(demands, key=lambda item: item[1], reverse=True):
            if not _assign_station_product_demand(demand, remaining_by_vehicle):
                report.warning(
                    f"Product {product_idx + 1}, station {station_id}: demand {demand:.2f} cannot be assigned "
                    f"by the greedy scenario within {min_trips} default trip(s) per vehicle without visiting the same "
                    "station/product twice with one vehicle."
                )
                break


def _assign_station_product_demand(demand: float, remaining_by_vehicle: list[list[float]]) -> bool:
    """Assign one station/product demand across distinct vehicles if possible."""
    remaining = demand
    used_vehicles: set[int] = set()

    while remaining > EPSILON:
        best_vehicle = None
        best_trip = None
        best_capacity = 0.0
        for vehicle_idx, trip_capacities in enumerate(remaining_by_vehicle):
            if vehicle_idx in used_vehicles:
                continue
            for trip_idx, capacity in enumerate(trip_capacities):
                if capacity > best_capacity + EPSILON:
                    best_vehicle = vehicle_idx
                    best_trip = trip_idx
                    best_capacity = capacity

        if best_vehicle is None or best_trip is None:
            return False

        delivered = min(remaining, best_capacity)
        remaining_by_vehicle[best_vehicle][best_trip] -= delivered
        used_vehicles.add(best_vehicle)
        remaining -= delivered

    return True


def _check_geographic_overlap(data: InstanceData, report: VerificationReport) -> None:
    """Warn when generated physical locations are almost identical."""
    points: list[tuple[str, int, float, float]] = []
    for row in data.depots:
        points.append(("Depot", int(row[0]), float(row[1]), float(row[2])))
    for row in data.garages:
        points.append(("Garage", int(row[0]), float(row[1]), float(row[2])))
    for row in data.stations:
        points.append(("Station", int(row[0]), float(row[1]), float(row[2])))

    overlaps: list[str] = []
    for idx, first in enumerate(points):
        for second in points[idx + 1 :]:
            distance = float(np.hypot(first[2] - second[2], first[3] - second[3]))
            if distance < 0.1:
                overlaps.append(f"{first[0]} {first[1]} and {second[0]} {second[1]} (distance={distance:.3f})")
    if overlaps:
        report.warning(f"Geographic overlap detected: {len(overlaps)} pair(s). First cases: {overlaps[:5]}.")


def _check_lp_parser_compatibility(instance: ParsedInstance, report: VerificationReport) -> None:
    """Load the file through utils.parser to catch format mismatches."""
    try:
        lp_instance = MPVRPInstance.read(instance.filepath)
    except Exception as exc:
        report.error(f"utils.parser.MPVRPInstance.read() cannot parse this file: {exc}")
        return

    if any(vehicle.start_g is None for vehicle in lp_instance.vehicules):
        report.error("utils.parser.MPVRPInstance.read() parsed at least one vehicle with no linked garage.")
        return

    parsed_dimensions = (
        lp_instance.n_prods,
        lp_instance.n_depots,
        lp_instance.n_garages,
        lp_instance.n_stations,
        lp_instance.n_vehicules,
    )
    expected_dimensions = tuple(int(value) for value in instance.params)
    if parsed_dimensions != expected_dimensions:
        report.error(
            "utils.parser.MPVRPInstance.read() dimensions differ from file header: "
            f"{parsed_dimensions} != {expected_dimensions}."
        )
    else:
        report.info("LP parser compatibility: ok.")
