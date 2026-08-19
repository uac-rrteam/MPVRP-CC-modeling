from __future__ import annotations

from math import ceil

import numpy as np

from mpvrp_cc.generation.config import (
    EPSILON, GenerationConfig, InstanceData, ParsedInstance, VerificationReport
)
from mpvrp_cc.io.instance_solution_io import MPVRPInstance



def validate_generation_config(config: GenerationConfig) -> VerificationReport:
    """Validate generator options before any random instance data is created.

    This function checks that all configuration parameters are within valid ranges
    and logically consistent before generation begins. It catches configuration errors
    early to prevent wasting computation on invalid instances.
    """
    report = VerificationReport()

    # Check that all problem dimensions are at least 1
    for name, value in {
        "vehicles": config.vehicles,
        "depots": config.depots,
        "garages": config.garages,
        "stations": config.stations,
        "products": config.products,
    }.items():
        if value < 1:
            report.error(f"{name} must be at least 1.")

    # Validate spatial parameters
    if not isinstance(config.grid_size, (int, np.integer)):
        report.error("grid_size must be an integer.")
    elif config.grid_size <= 0:
        report.error("grid_size must be positive.")
    if not isinstance(config.min_point_distance, (int, np.integer)):
        report.error("min_point_distance must be an integer.")
    elif config.min_point_distance < 1:
        report.error("min_point_distance must be at least 1.")
    if not 0 < config.demand_probability <= 1:
        report.error("demand_probability must be in (0, 1].")

    # Validate difficulty level selections (must be one of the defined levels)
    if config.changeover_cost_level not in {"low", "normal", "high", "mixed"}:
        report.error("changeover_cost_level must be one of: low, normal, high, mixed.")
    if config.capacity_level not in {"low", "medium", "large", "mixed"}:
        report.error("capacity_level must be one of: low, medium, large, mixed.")
    if config.demand_level not in {"low", "medium", "high", "mixed"}:
        report.error("demand_level must be one of: low, medium, high, mixed.")
    if config.stock_level not in {"low", "medium", "high", "mixed"}:
        report.error("stock_level must be one of: low, medium, high, mixed.")

    # Validate spatial layout strategy
    if config.coordinate_strategy not in {"uniform", "clustered", "corridor"}:
        report.error("coordinate_strategy must be one of: uniform, clustered, corridor.")

    # Warn if minimum point distance is too large relative to grid size
    if (
        isinstance(config.grid_size, (int, np.integer))
        and isinstance(config.min_point_distance, (int, np.integer))
        and config.min_point_distance > config.grid_size
    ):
        report.warning("min_point_distance is larger than the grid; coordinate retries may be exhausted.")

    return report


def validate_instance_data(data: InstanceData) -> VerificationReport:
    """Validate an in-memory instance against parser and LP feasibility rules.

    This comprehensive validation checks:
    - Array shapes match expected dimensions
    - IDs are unique, integer, and contiguous
    - All numeric values are non-negative and finite
    - Stocks cover all demands with proper surplus
    - Trip bounds and vehicle capacity constraints are satisfiable
    - Geographic locations don't have problematic overlaps
    """
    report = VerificationReport()
    nb_p, nb_d, nb_g, nb_s, nb_v = [int(value) for value in data.params]

    # Check that array dimensions match the problem parameters
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

    # Exit early if shape errors exist (can't proceed with validation)
    if report.errors:
        return report

    # Check entity IDs (vehicles, depots, garages, stations) are valid
    for name, rows, count in (
        ("Vehicle", data.vehicles, nb_v),
        ("Depot", data.depots, nb_d),
        ("Garage", data.garages, nb_g),
        ("Station", data.stations, nb_s),
    ):
        _check_ids(name, rows, count, report)

    # Validate the transition cost matrix (product changeover costs)
    _check_matrix(data, report)

    # Check vehicle properties
    if np.any(data.vehicles[:, 1] <= EPSILON):
        report.error("Vehicle capacities must be positive.")
    if not set(data.vehicles[:, 2].astype(int)).issubset(set(range(1, nb_g + 1))):
        report.error("Every vehicle home garage must reference an existing garage.")
    if not set(data.vehicles[:, 3].astype(int)).issubset(set(range(1, nb_p + 1))):
        report.error("Every vehicle initial product must be in [1, NbProducts].")

    # Check depot stocks and station demands are non-negative
    _check_nonnegative("Depot stocks", data.depots[:, 3:], report)
    _check_nonnegative("Station demands", data.stations[:, 3:], report)

    # Ensure no empty stations (every station must demand something)
    if np.any(data.stations[:, 3:].sum(axis=1) <= EPSILON):
        report.error("Every station must have at least one positive demand.")

    # Check demand coverage: depots must have enough stock for all demands
    total_stock = data.depots[:, 3:].sum(axis=0)
    total_demand = data.stations[:, 3:].sum(axis=0)
    for product_idx, (stock, demand) in enumerate(zip(total_stock, total_demand), start=1):
        if demand <= EPSILON:
            report.warning(f"Product {product_idx} has no demand.")
        if stock + EPSILON < demand:
            report.error(f"Product {product_idx}: total stock {stock:.2f} < total demand {demand:.2f}.")

    # Check vehicle capacity constraints
    total_capacity = float(data.vehicles[:, 1].sum())
    if total_capacity <= EPSILON:
        report.error("Fleet has no usable capacity.")
    else:
        # No single station/product demand should exceed fleet capacity
        # (LP permits at most one visit per vehicle for each station/product pair)
        for station in data.stations:
            station_id = int(station[0])
            for product_idx, demand in enumerate(station[3:], start=1):
                if demand > total_capacity + EPSILON:
                    report.error(
                        f"Station {station_id}, product {product_idx}: demand {demand:.2f} exceeds "
                        f"total fleet capacity {total_capacity:.2f}. lp.py permits at most one visit "
                        "per vehicle for a station/product pair."
                    )

        # Check feasibility conditions specific to the LP model's trip bound
        _check_default_trip_bound_scenario(data, report)

    # Warn about geographic locations that are too close together
    _check_geographic_overlap(data, report)

    return report


def validate_parsed_instance(instance: ParsedInstance) -> VerificationReport:
    """Validate a loaded file and confirm compatibility with the LP parser.

    Extends instance_data validation with:
    - File-level header information (UUID, dimensions)
    - Compatibility with the canonical instance parser
    """
    report = validate_instance_data(instance)

    # Add header information to the report
    report.infos.insert(0, f"UUID: {instance.uuid}")
    report.infos.insert(
        1,
        "Dimensions: "
        f"products={instance.nb_products}, depots={instance.nb_depots}, garages={instance.nb_garages}, "
        f"stations={instance.nb_stations}, vehicles={instance.nb_vehicles}.",
    )

    # Check that the LP parser can read and interpret the file
    _check_lp_parser_compatibility(instance, report)

    return report


def _check_ids(name: str, rows: np.ndarray, count: int, report: VerificationReport) -> None:
    """Check that entity IDs are integer, unique, contiguous, and one-based.

    For example, a set of 5 vehicles must have IDs [1, 2, 3, 4, 5] in any order.
    This ensures the parser can uniquely reference each entity.
    """
    ids = rows[:, 0]

    # Check if IDs are integers (or very close to integers, accounting for floating point)
    rounded = np.round(ids).astype(int)
    if not np.allclose(ids, rounded):
        report.error(f"{name} IDs must be integers.")
        return

    actual = set(rounded.tolist())
    expected = set(range(1, count + 1))

    # Check for uniqueness
    if len(rounded) != len(actual):
        report.error(f"{name} IDs must be unique.")

    # Check for contiguity starting from 1
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            report.error(f"{name} IDs missing: {missing}.")
        if extra:
            report.error(f"{name} IDs out of range: {extra}; expected [1, {count}].")


def _check_matrix(data: InstanceData, report: VerificationReport) -> None:
    """Validate transition costs and warn on unusual symmetric matrices.

    Checks that:
    - All costs are finite numbers (not NaN or infinity)
    - All costs are non-negative
    - Cost-bearing matrices have strictly positive same-product setup costs
    - Warns if matrix appears to violate triangle inequality
    """
    matrix = data.transition_costs

    # Check all values are valid numbers
    if not np.all(np.isfinite(matrix)):
        report.error("Transition costs must be finite.")

    # Check costs are non-negative
    if np.any(matrix < -EPSILON):
        report.error("Transition costs must be non-negative.")

    # A zero matrix is the explicit no-cost control scenario. In every
    # cost-bearing instance, same-product preparation must remain priced.
    if not np.allclose(matrix, 0.0) and np.any(np.diag(matrix) <= EPSILON):
        report.error("A cost-bearing transition matrix must have a strictly positive diagonal.")

    # If matrix is symmetric, check for triangle inequality violations
    # This is informational only; violations are allowed by the LP but unusual
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
                # Check if direct path is cheaper than going through intermediate
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
    """Check that an array contains no negative values.

    Used for depot stocks and station demands, which cannot be negative.
    """
    if np.any(values < -EPSILON):
        report.error(f"{name} must be non-negative.")


def _check_default_trip_bound_scenario(data: InstanceData, report: VerificationReport) -> None:
    """Simulate necessary feasibility conditions for lp.py's default trip bound.

    The LP model uses a uniform per-vehicle trip bound calculated as:
    max(ceil(total_demand / fleet_capacity), num_products)

    This function checks:
    1. The bound is at least the number of demanded products (each product needs mini-routes)
    2. Enough trip slots exist for all demanded products
    3. Product-level capacity lower bounds can be satisfied
    4. Greedy assignment simulations succeed
    """
    total_capacity = float(data.vehicles[:, 1].sum())
    product_demands = data.stations[:, 3:].sum(axis=0)
    total_demand = float(product_demands.sum())

    # Calculate the trip bound that lp.py will use
    min_trips = _minimum_uniform_trip_bound(total_demand, total_capacity)
    report.info(f"Minimum uniform trip bound used by lp.py default: {min_trips}.")

    # Check 1: bound must accommodate all demanded products
    active_products = int(np.count_nonzero(product_demands > EPSILON))
    if min_trips < active_products:
        report.error(
            "Default LP trip bound is lower than the number of demanded products: "
            f"bound={min_trips}, demanded_products={active_products}. Each mini-route carries exactly one product."
        )

    # Check 2: enough trip slots exist across the entire fleet
    total_slots = data.nb_vehicles * min_trips
    if total_slots < active_products:
        report.error(
            "Default LP trip slots cannot assign at least one mini-route to each demanded product: "
            f"vehicles * bound = {data.nb_vehicles} * {min_trips} = {total_slots}, "
            f"demanded_products={active_products}."
        )

    # Check 3: product-level capacity lower bounds can be met
    required_slots = _minimum_product_slots(data, product_demands)
    if required_slots > total_slots:
        report.error(
            "Default LP trip slots are insufficient for product-level capacity lower bounds: "
            f"required_slots={required_slots}, available_slots={total_slots}."
        )

    # Check 4: greedy simulation to ensure demand can actually be assigned
    _simulate_product_capacity_scenarios(data, min_trips, report)


def _minimum_uniform_trip_bound(total_demand: float, total_capacity: float) -> int:
    """Return the same uniform per-vehicle trip bound used by the MILP solver.

    This is the key feasibility calculation: how many trips does each vehicle need
    to make to handle all product demands?
    """
    if total_demand <= EPSILON:
        return 0
    return ceil(total_demand / total_capacity)


def _minimum_product_slots(data: InstanceData, product_demands: np.ndarray) -> int:
    """Estimate the minimum number of single-product trip slots needed.

    Calculates how many vehicle trips are needed considering both:
    - Total demand per product (aggregate constraint)
    - Individual station demands (locality constraint - each station needs multiple vehicles)
    """
    max_vehicle_capacity = float(data.vehicles[:, 1].max())
    required = 0

    for product_idx, product_demand in enumerate(product_demands):
        if product_demand <= EPSILON:
            continue  # No demand for this product

        # Aggregate trips: how many large vehicles needed to cover all demand?
        aggregate_slots = ceil(product_demand / max_vehicle_capacity)

        # Locality trips: different stations may need multiple different vehicles
        # Find the maximum number of vehicles needed for any single station
        station_slots = max(
            _minimum_distinct_vehicle_slots(float(demand), data.vehicles[:, 1])
            for demand in data.stations[:, 3 + product_idx]
            if demand > EPSILON
        )

        # Use the maximum of both constraints (both must be satisfied)
        required += max(1, aggregate_slots, station_slots)

    return required


def _minimum_distinct_vehicle_slots(demand: float, capacities: np.ndarray) -> int:
    """Find how many different vehicles are needed for one station/product demand.

    Greedy algorithm: use the largest available vehicles first.
    This gives the minimum number of vehicles needed.
    """
    remaining = demand
    for slots, capacity in enumerate(sorted(capacities, reverse=True), start=1):
        remaining -= float(capacity)
        if remaining <= EPSILON:
            return slots
    return len(capacities) + 1


def _simulate_product_capacity_scenarios(data: InstanceData, min_trips: int, report: VerificationReport) -> None:
    """Greedily test whether each product can fit into default trip capacity.

    For each product, simulates a greedy assignment of station demands to vehicle trips.
    Warns if any station/product combination cannot be feasibly assigned.
    This is a practical feasibility check beyond the mathematical lower bounds.
    """
    if min_trips < 1:
        return

    capacities = data.vehicles[:, 1].astype(float)

    # Test each product independently
    for product_idx in range(data.nb_products):
        # Collect all demands for this product
        demands = [
            (int(station[0]), float(station[3 + product_idx]))
            for station in data.stations
            if station[3 + product_idx] > EPSILON
        ]
        if not demands:
            continue  # No demand for this product

        # Create a capacity tracking structure: for each vehicle, track available capacity in each trip
        remaining_by_vehicle = [[float(capacity)] * min_trips for capacity in capacities]

        # Try to greedily assign demands (sorted largest first for better packing)
        for station_id, demand in sorted(demands, key=lambda item: item[1], reverse=True):
            if not _assign_station_product_demand(demand, remaining_by_vehicle):
                report.warning(
                    f"Product {product_idx + 1}, station {station_id}: demand {demand:.2f} cannot be assigned "
                    f"by the greedy scenario within {min_trips} default trip(s) per vehicle without visiting the same "
                    "station/product twice with one vehicle."
                )
                break


def _assign_station_product_demand(demand: float, remaining_by_vehicle: list[list[float]]) -> bool:
    """Assign one station/product demand across distinct vehicles if possible.

    This function tries to split the demand among different vehicles such that
    no single vehicle visits the same station/product combination twice.
    Uses a greedy approach: pick the vehicle with the most available capacity.
    """
    remaining = demand
    used_vehicles: set[int] = set()

    while remaining > EPSILON:
        best_vehicle = None
        best_trip = None
        best_capacity = 0.0

        # Find the best available vehicle/trip combination
        for vehicle_idx, trip_capacities in enumerate(remaining_by_vehicle):
            if vehicle_idx in used_vehicles:
                continue  # Already used this vehicle for this station/product
            for trip_idx, capacity in enumerate(trip_capacities):
                if capacity > best_capacity + EPSILON:
                    best_vehicle = vehicle_idx
                    best_trip = trip_idx
                    best_capacity = capacity

        if best_vehicle is None or best_trip is None:
            return False  # Cannot assign remaining demand

        # Assign as much demand as possible to this vehicle's trip
        delivered = min(remaining, best_capacity)
        remaining_by_vehicle[best_vehicle][best_trip] -= delivered
        used_vehicles.add(best_vehicle)  # Mark vehicle as used for this product
        remaining -= delivered

    return True  # Successfully assigned all demand


def _check_geographic_overlap(data: InstanceData, report: VerificationReport) -> None:
    """Warn when generated physical locations are almost identical.

    Collects all depots, garages, and stations and checks for very close pairs.
    This can indicate a problem with the spatial generation strategy or an attempt
    to place too many entities in a small area.
    """
    # Collect all geographic points with their entity type and ID
    points: list[tuple[str, int, float, float]] = []
    for row in data.depots:
        points.append(("Depot", int(row[0]), float(row[1]), float(row[2])))
    for row in data.garages:
        points.append(("Garage", int(row[0]), float(row[1]), float(row[2])))
    for row in data.stations:
        points.append(("Station", int(row[0]), float(row[1]), float(row[2])))

    # Find all pairs that are very close (distance < 0.1)
    overlaps: list[str] = []
    for idx, first in enumerate(points):
        for second in points[idx + 1 :]:
            distance = float(np.hypot(first[2] - second[2], first[3] - second[3]))
            if distance < 0.1:
                overlaps.append(f"{first[0]} {first[1]} and {second[0]} {second[1]} (distance={distance:.3f})")

    if overlaps:
        report.warning(f"Geographic overlap detected: {len(overlaps)} pair(s). First cases: {overlaps[:5]}.")


def _check_lp_parser_compatibility(instance: ParsedInstance, report: VerificationReport) -> None:
    """Load the file through the canonical parser to catch format mismatches.

    This is the final compatibility check: attempt to actually parse the file
    using the LP model's parser. Catches file format issues that aren't caught
    by the numpy-based validation.
    """
    try:
        # Try to load using the actual LP parser
        lp_instance = MPVRPInstance.read(instance.filepath)
    except Exception as exc:
        report.error(f"MPVRPInstance.read() cannot parse this file: {exc}")
        return

    # Check that every vehicle has a valid garage reference
    if any(vehicle.start_g is None for vehicle in lp_instance.vehicles):
        report.error("MPVRPInstance.read() parsed at least one vehicle with no linked garage.")
        return

    # Check that dimensions match between what we generated and what the parser read
    parsed_dimensions = (
        lp_instance.n_prods,
        lp_instance.n_depots,
        lp_instance.n_garages,
        lp_instance.n_stations,
        lp_instance.n_vehicles,
    )
    expected_dimensions = tuple(int(value) for value in instance.params)
    if parsed_dimensions != expected_dimensions:
        report.error(
            "MPVRPInstance.read() dimensions differ from file header: "
            f"{parsed_dimensions} != {expected_dimensions}."
        )
    else:
        report.info("LP parser compatibility: ok.")
