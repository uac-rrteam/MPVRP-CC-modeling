from __future__ import annotations

import argparse
from math import ceil
from pathlib import Path

import numpy as np
from loguru import logger

from .models import (
    EPSILON, GenerationConfig, InstanceData, ParsedInstance, VerificationReport
)
from .io import load_instance_file
from tools.run_logging import configure_run_logging


LOGGER = logger



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
        # A station/product demand must be coverable by distinct vehicles, with
        # each vehicle loading its contribution at one depot.  Total fleet
        # capacity alone is not sufficient when product stock is fragmented.
        maximum_delivery_by_product = [
            maximum_station_product_delivery(data.vehicles[:, 1], data.depots[:, 3 + product_idx])
            for product_idx in range(nb_p)
        ]
        for station in data.stations:
            station_id = int(station[0])
            for product_idx, demand in enumerate(station[3:], start=1):
                if demand <= EPSILON:
                    continue
                maximum_delivery = maximum_delivery_by_product[product_idx - 1]
                if demand > maximum_delivery + EPSILON:
                    report.error(
                        f"Station {station_id}, product {product_idx}: demand {demand:.2f} exceeds "
                        f"the maximum deliverable quantity {maximum_delivery:.2f} from compatible "
                        f"depot stocks using distinct vehicles (shortage {demand - maximum_delivery:.2f})."
                    )

        # Report the safe horizon used by the MILP model.
        _check_default_trip_bound_scenario(data, report)

    # Warn about geographic locations that are too close together
    _check_geographic_overlap(data, report)

    return report


def maximum_station_product_delivery(capacities: np.ndarray, depot_stocks: np.ndarray) -> float:
    """Return the most one station/product pair can receive under the route rules.

    Each vehicle may contribute at most once and that contribution must be loaded
    at one depot.  Several vehicles may use the same depot, but their combined load
    cannot exceed its stock.  A subset dynamic program considers every assignment
    of vehicles to depots; benchmark instances contain at most ten vehicles.

    For unusually large externally supplied fleets, a safe upper bound is returned.
    It can still prove infeasibility without making validation exponential or
    incorrectly rejecting a feasible instance.
    """
    usable_capacities = [float(value) for value in capacities if value > EPSILON]
    usable_stocks = [float(value) for value in depot_stocks if value > EPSILON]
    if not usable_capacities or not usable_stocks:
        return 0.0

    # The benchmark generator is capped at ten vehicles.  Keep validation of
    # arbitrary third-party instances predictable while retaining a sound check.
    if len(usable_capacities) > 12:
        largest_stock = max(usable_stocks)
        return min(
            sum(usable_capacities),
            sum(usable_stocks),
            sum(min(capacity, largest_stock) for capacity in usable_capacities),
        )

    state_count = 1 << len(usable_capacities)
    subset_capacity = [0.0] * state_count
    for mask in range(1, state_count):
        bit = mask & -mask
        vehicle_idx = bit.bit_length() - 1
        subset_capacity[mask] = subset_capacity[mask ^ bit] + usable_capacities[vehicle_idx]

    unreachable = float("-inf")
    best = [unreachable] * state_count
    best[0] = 0.0
    full_mask = state_count - 1

    for stock in usable_stocks:
        updated = best.copy()
        for used_mask, delivered_before in enumerate(best):
            if delivered_before == unreachable:
                continue
            available = full_mask ^ used_mask
            assigned = available
            while assigned:
                new_mask = used_mask | assigned
                delivered = delivered_before + min(stock, subset_capacity[assigned])
                if delivered > updated[new_mask]:
                    updated[new_mask] = delivered
                assigned = (assigned - 1) & available
        best = updated

    return max(best)


def validate_parsed_instance(instance: ParsedInstance) -> VerificationReport:
    """Validate parsed instance data and report its file header."""
    report = validate_instance_data(instance)

    # Add header information to the report
    report.infos.insert(0, f"UUID: {instance.uuid}")
    report.infos.insert(
        1,
        "Dimensions: "
        f"products={instance.nb_products}, depots={instance.nb_depots}, garages={instance.nb_garages}, "
        f"stations={instance.nb_stations}, vehicles={instance.nb_vehicles}.",
    )

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
            "this is allowed by the MPVRP-CC definition and may affect changeover incentives."
        )


def _check_nonnegative(name: str, values: np.ndarray, report: VerificationReport) -> None:
    """Check that an array contains no negative values.

    Used for depot stocks and station demands, which cannot be negative.
    """
    if np.any(values < -EPSILON):
        report.error(f"{name} must be non-negative.")


def _check_default_trip_bound_scenario(data: InstanceData, report: VerificationReport) -> None:
    """Report the solver's configured default per-vehicle trip horizon."""
    total_demand = float(data.stations[:, 3:].sum())
    fleet_capacity = float(data.vehicles[:, 1].sum())
    trip_bound = _maximum_uniform_trip_bound(total_demand, fleet_capacity, data.nb_products)
    report.info(f"Maximum uniform trip bound used by the MILP solver: {trip_bound}.")


def _maximum_uniform_trip_bound(
    total_demand: float,
    fleet_capacity: float,
    product_count: int,
) -> int:
    """Return the same aggregate-capacity trip bound as the MILP solver."""
    if total_demand <= EPSILON:
        return 0
    if fleet_capacity <= EPSILON:
        raise ValueError("The fleet has no usable capacity.")
    return max(ceil(total_demand / fleet_capacity) + 1, product_count)


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


def log_report(report: VerificationReport, logger=LOGGER) -> None:
    for message in report.infos:
        logger.info(message)
    for message in report.warnings:
        logger.warning(message)
    for message in report.errors:
        logger.error(message)
    if report.errors:
        logger.error(
            "Status: INVALID ({} error(s), {} warning(s)).",
            len(report.errors),
            len(report.warnings),
        )
    else:
        logger.info("Status: VALID ({} warning(s)).", len(report.warnings))


def verify_instance(
    filepath: str | Path,
    logger=LOGGER,
) -> VerificationReport:
    path = Path(filepath)
    report = VerificationReport()
    logger.info("Verifying instance: {}", path)
    instance = load_instance_file(path, report)
    if instance is not None:
        parsed_report = validate_parsed_instance(instance)
        report.errors.extend(parsed_report.errors)
        report.warnings.extend(parsed_report.warnings)
        report.infos.extend(parsed_report.infos)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an MPVRP-CC instance file for solver compatibility."
    )
    parser.add_argument("filepath", type=Path, help="Path to the .dat instance file.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    configure_run_logging("validate", verbose=args.verbose, quiet=args.quiet, log_dir=args.log_dir)
    report = verify_instance(args.filepath)
    log_report(report)
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
