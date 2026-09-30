from __future__ import annotations

import argparse
from math import ceil
import uuid
import tempfile
import os
from pathlib import Path
import numpy as np
from loguru import logger

from .io import existing_instance_codes, write_instance
from .geometry import _station_centers, _station_point, _depot_point, _garage_point
from .models import DEFAULT_OUTPUT_DIR, EPSILON, GenerationConfig, InstanceData
from .validate import (
    log_report,
    maximum_station_product_delivery,
    validate_generation_config,
    validate_instance_data,
    verify_instance,
)
from tools.run_logging import configure_run_logging

LOGGER = logger

# Define cost ranges for product changeover operations.
CHANGEOVER_COST_RANGES = {
    "low": (25, 150),        # Cheap changeovers (minor setup required)
    "normal": (1_001, 3_500),    # Regular changeovers (standard setup)
    "high": (4_501, 15_000),     # Expensive changeovers (major equipment reconfiguration)
}

# Define vehicle capacity ranges in units
# Different capacity levels simulate diverse fleet compositions
CAPACITY_RANGES = {
    "low": (1_000, 3_999),           # Small vehicles (pickup trucks, vans)
    "medium": (4_000, 10_000),       # Medium vehicles (standard trucks)
    "large": (10_001, 25_000),       # Large vehicles (heavy trucks, cargo vehicles)
}

# Define demand ranges per station/product in units
# Larger demands require more vehicle trips
DEMAND_RANGES = {
    "low": (100, 1_000),        # Small customer demands
    "medium": (1_000, 4_000),   # Regular customer demands
    "high": (4_000, 9_000),     # Large customer demands
}

# Define surplus stock ratios as multipliers of demand
# For example, a ratio of 0.2 means 20% extra stock beyond demand
STOCK_SURPLUS_RATIOS = {
    "low": (0.02, 0.10),        # Tight inventory (just-in-time style)
    "medium": (0.15, 0.30),     # Balanced inventory
    "high": (0.40, 0.80),       # High safety stock (more flexibility)
}


def _instance_code(category: str | None, number: str | None, instance_id: str | None) -> str:
    """Build the public instance code from CLI naming options.

    The instance code is used to uniquely identify and name generated instances.
    For example: 'S_001', 'M_042', or a custom ID like 'TEST_INSTANCE'.
    """
    if instance_id:
        return instance_id
    category = (category or "S").upper()
    raw_number = number or "001"
    if not raw_number.isdigit():
        raise ValueError("--number must contain digits only.")
    return f"{category}_{int(raw_number):03d}"


def generate_instance_data(config: GenerationConfig) -> InstanceData:
    """Generate one in-memory MPVRP-CC instance and validate its inputs.

    This is the main generation pipeline that orchestrates all components:
    - Validates the configuration parameters
    - Generates transition costs between products
    - Creates vehicle fleet with capacities and initial locations
    - Generates service stations with customer demands
    - Sets up depot locations and initial stock levels
    - Creates garage locations for vehicle parking
    """
    report = validate_generation_config(config)
    if not report.is_valid:
        raise ValueError("; ".join(report.errors))

    # Initialize random number generator with seed for reproducibility
    rng = np.random.default_rng(config.seed)

    # Pack problem dimensions into a single array for easy reference
    params = np.array([config.products, config.depots, config.garages, config.stations, config.vehicles], dtype=int)

    # Generate the cost matrix for switching between products
    transition_costs = _generate_transition_costs(rng, config)

    # Build vehicle fleet with their properties (capacity, home garage, initial product)
    vehicles = _generate_vehicles(rng, config)
    vehicle_capacities = vehicles[:, 1].astype(float)

    # Generate service stations and compute total demand per product across all stations
    stations, total_demands, points = _generate_stations(rng, config, vehicle_capacities)

    # Create depots with sufficient stock to cover all demands
    depots = _generate_depots(rng, config, total_demands, points)
    _repair_fragmented_depot_stocks(depots, stations, vehicle_capacities)

    # Create garages (vehicle parking/maintenance facilities) near depots for efficiency
    garages = _generate_garages(rng, config, points, depots)

    return InstanceData(
        uuid=str(uuid.uuid4()),
        params=params,
        transition_costs=transition_costs,
        vehicles=vehicles,
        depots=depots,
        garages=garages,
        stations=stations,
    )


def _generate_transition_costs(rng: np.random.Generator, config: GenerationConfig) -> np.ndarray:
    """Generate product transition costs with a low-cost diagonal.

    Keeping the same product still requires loading and preparation, represented
    by a low diagonal cost. If the level is ``mixed``, off-diagonal arcs use
    normal or high costs.
    """
    if config.products == 1:
        low, high = CHANGEOVER_COST_RANGES["low"]
        return rng.integers(low, high + 1, size=(1, 1))

    if config.changeover_cost_level == "mixed":
        # Heterogeneous costs: each product pair gets assigned a random difficulty level
        return _generate_mixed_transition_costs(rng, config.products)

    # Uniform level: all product pairs use the same cost range
    min_cost, max_cost = _changeover_cost_bounds(config)
    costs = rng.integers(min_cost, max_cost + 1, size=(config.products, config.products))
    _fill_low_diagonal(rng, costs)
    return costs


def _generate_mixed_transition_costs(rng: np.random.Generator, products: int) -> np.ndarray:
    """Generate heterogeneous changeover costs by sampling a level per arc.

    The research benchmark is intended to expose the routing/changeover
    trade-off, so mixed matrices contain only material (normal or high) costs.
    Low costs remain available through the explicit ``low`` level for control
    and sensitivity experiments.
    """
    costs = np.zeros((products, products), dtype=int)
    low_min, low_max = CHANGEOVER_COST_RANGES["low"]
    for from_product in range(products):
        for to_product in range(products):
            if from_product == to_product:
                costs[from_product, to_product] = int(rng.integers(low_min, low_max + 1))
                continue
            # Randomly assign each arc a difficulty level
            level = str(rng.choice(["normal", "high"]))
            min_cost, max_cost = CHANGEOVER_COST_RANGES[level]
            costs[from_product, to_product] = int(rng.integers(min_cost, max_cost + 1))
    return costs


def _fill_low_diagonal(rng: np.random.Generator, costs: np.ndarray) -> None:
    """Fill same-product transitions with low preparation costs."""
    low, high = CHANGEOVER_COST_RANGES["low"]
    diagonal = rng.integers(low, high + 1, size=len(costs))
    costs[np.diag_indices_from(costs)] = diagonal


def _changeover_cost_bounds(config: GenerationConfig) -> tuple[int, int]:
    """Return the numeric cost range for the configured changeover level."""
    return CHANGEOVER_COST_RANGES[config.changeover_cost_level]


def _generate_vehicles(rng: np.random.Generator, config: GenerationConfig) -> np.ndarray:
    """Generate vehicle IDs, capacities, home garages, and initial products.

    Each vehicle has:
    - Unique ID (1 to config.vehicles)
    - Random capacity within the configured level's range
    - Home garage where it's initially parked
    - Initial product loaded when the day starts
    """
    rows = []
    for vehicle_id in range(1, config.vehicles + 1):
        low, high = _capacity_bounds(rng, config.capacity_level)
        rows.append(
            [
                vehicle_id,                              # Vehicle identifier
                int(rng.integers(low, high + 1)),        # Vehicle capacity (units)
                int(rng.integers(1, config.garages + 1)), # Home garage location
                int(rng.integers(1, config.products + 1)), # Starting product loaded
            ]
        )
    return np.array(rows, dtype=int)


def _capacity_bounds(rng: np.random.Generator, level: str) -> tuple[int, int]:
    """Return a capacity range, resolving mixed levels randomly.

    If the level is 'mixed', we randomly pick from low/medium/large for each vehicle.
    This creates a heterogeneous fleet like in real-world scenarios.
    """
    if level == "mixed":
        level = str(rng.choice(["low", "medium", "large"]))
    return CAPACITY_RANGES[level]


def _generate_stations(
    rng: np.random.Generator,
    config: GenerationConfig,
    vehicle_capacities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Generate station locations and product demands that fit LP bounds.

    This function creates service locations with customer demands for each product.
    Key constraints:
    - Each station must have demands for at least one product
    - Total demands must be feasible given the vehicle fleet capacity
    - Demands are sampled from configured ranges
    - Stations are placed using the configured spatial strategy
    """
    total_fleet_capacity = int(vehicle_capacities.sum())
    points: list[tuple[int, int]] = []
    centers = _station_centers(rng, config)  # Get cluster centers if using clustered layout
    rows: list[list[int]] = []
    total_demands = np.zeros(config.products, dtype=int)  # Track total demand per product

    # Generate each station
    for station_id in range(1, config.stations + 1):
        x, y = _station_point(rng, config, points, centers, station_id)

        # Initialize demands for all products as zero
        demands = np.zeros(config.products, dtype=int)

        # Randomly decide which products this station needs
        # Each product has config.demand_probability chance of being needed
        active_products = rng.random(config.products) <= config.demand_probability
        if not active_products.any():
            # Ensure at least one product is demanded (no empty stations)
            active_products[int(rng.integers(0, config.products))] = True

        # Sample demand quantities for active products
        for product_idx, is_active in enumerate(active_products):
            if is_active:
                low, high = _demand_bounds(rng, config.demand_level, total_fleet_capacity)
                demands[product_idx] = int(rng.integers(low, high + 1))

        rows.append([station_id, x, y, *demands.tolist()])
        total_demands += demands

    station_array = np.array(rows, dtype=int)

    # Ensure every product has at least some demand (avoid zero-demand products)
    for product_idx in range(config.products):
        if total_demands[product_idx] > EPSILON:
            continue  # This product already has demand somewhere

        # Force at least one station to demand this product
        station_idx = int(rng.integers(0, config.stations))
        low, high = _demand_bounds(rng, config.demand_level, total_fleet_capacity)
        demand = int(rng.integers(low, high + 1))
        station_array[station_idx, 3 + product_idx] = demand
        total_demands[product_idx] += demand

    # Increase demands if needed to ensure LP trip bound constraints are satisfied
    _enforce_trip_bound_floor(rng, config, station_array, total_demands, vehicle_capacities)
    return station_array, total_demands, points


def _demand_bounds(rng: np.random.Generator, level: str, total_fleet_capacity: int) -> tuple[int, int]:
    """Return a demand range capped by the total fleet capacity.

    No single demand should exceed what the entire fleet can carry in one trip,
    otherwise the instance would be infeasible.
    """
    if level == "mixed":
        # For mixed level, randomly pick low/medium/high for variety
        level = str(rng.choice(["low", "medium", "high"]))
    low, high = DEMAND_RANGES[level]
    # Cap the upper bound by fleet capacity to ensure feasibility
    high = min(high, max(1, total_fleet_capacity))
    low = min(low, high)  # Ensure low doesn't exceed high
    return low, high


def _enforce_trip_bound_floor(
    rng: np.random.Generator,
    config: GenerationConfig,
    stations: np.ndarray,
    total_demands: np.ndarray,
    vehicle_capacities: np.ndarray,
) -> None:
    """Raise demand so the default LP trip bound can cover all products.

    The LP solver computes a trip bound as
    max(ceil(demand/capacity) + 1, num_products). This function raises demand
    only when that bound would not provide enough product-trip slots.
    """
    total_fleet_capacity = int(vehicle_capacities.sum())
    if config.products <= 1 or total_fleet_capacity <= 0:
        return  # No constraints for single-product or zero-capacity scenarios

    # Attempt up to 20 iterations to reach feasibility
    for _ in range(20):
        current_total = int(round(float(total_demands.sum())))
        current_bound = max(
            ceil(current_total / total_fleet_capacity) + 1,
            config.products,
        )

        # Calculate the minimum trip slots needed based on current demands
        required_slots = _minimum_generated_product_slots(stations, vehicle_capacities, config.products)
        required_bound = max(config.products, ceil(required_slots / len(vehicle_capacities)))

        if current_bound >= required_bound:
            return  # Constraints satisfied, we're done

        # Need more demand: calculate how much to add
        target_total = max(1, (required_bound - 2) * total_fleet_capacity + 1)
        _increase_station_demands(rng, config, stations, total_demands, total_fleet_capacity, target_total - current_total)

    raise ValueError("Cannot make generated station demands compatible with the LP default trip bound.")


def _increase_station_demands(
    rng: np.random.Generator,
    config: GenerationConfig,
    stations: np.ndarray,
    total_demands: np.ndarray,
    total_fleet_capacity: int,
    remaining: int,
) -> None:
    """Increase station/product demands without exceeding fleet capacity per cell.

    This function carefully adds demand to reach the trip bound floor while respecting
    the constraint that no single station/product demand can exceed vehicle capacity.
    """
    if remaining <= 0:
        return

    max_cell_demand = total_fleet_capacity

    # Find all stations and products that can still accept more demand
    candidates = [
        (station_idx, product_idx)
        for station_idx in range(config.stations)
        for product_idx in range(config.products)
        if stations[station_idx, 3 + product_idx] < max_cell_demand - EPSILON
    ]
    rng.shuffle(candidates)  # Randomize to spread demand evenly

    while remaining > 0 and candidates:
        station_idx, product_idx = candidates.pop(0)
        column = 3 + product_idx

        # Calculate how much more this cell can accept
        spare = int(max_cell_demand - stations[station_idx, column])
        if spare <= 0:
            continue

        # Add demand (capped by both remaining needed and cell capacity)
        increment = min(remaining, spare)
        stations[station_idx, column] += increment
        total_demands[product_idx] += increment
        remaining -= increment

        # Requeue cells that can still absorb more demand to spread large increases evenly
        if stations[station_idx, column] < max_cell_demand - EPSILON:
            candidates.append((station_idx, product_idx))

    if remaining > 0:
        raise ValueError(
            "Cannot raise generated demand enough to make the LP trip bound "
            "at least the number of products without exceeding fleet capacity "
            "on a station/product demand."
        )


def _minimum_generated_product_slots(
    stations: np.ndarray,
    vehicle_capacities: np.ndarray,
    products: int,
) -> int:
    """Estimate product trip slots needed by generated demand.

    This calculates how many vehicle trips are needed to cover all generated demands,
    considering both the total demand per product and the constraint that each
    station needs its demand served by different vehicles.
    """
    max_vehicle_capacity = float(vehicle_capacities.max())
    required = 0

    for product_idx in range(products):
        product_demands = stations[:, 3 + product_idx]
        product_total = float(product_demands.sum())
        if product_total <= EPSILON:
            continue  # No demand for this product

        # Calculate aggregate trips needed to cover total demand
        aggregate_slots = ceil(product_total / max_vehicle_capacity)

        # Calculate trips needed for each station to be served once
        station_slots = max(
            _minimum_distinct_vehicle_slots(float(demand), vehicle_capacities)
            for demand in product_demands
            if demand > EPSILON
        )

        # Use the maximum of both constraints
        required += max(1, aggregate_slots, station_slots)

    return required


def _minimum_distinct_vehicle_slots(demand: float, vehicle_capacities: np.ndarray) -> int:
    """Count vehicles needed to cover one station/product demand once each.

    Greedily assigns the largest available vehicles until the demand is covered.
    This ensures we don't overestimate the vehicles needed.
    """
    remaining = demand
    for slots, capacity in enumerate(sorted(vehicle_capacities, reverse=True), start=1):
        remaining -= float(capacity)
        if remaining <= EPSILON:
            return slots
    return len(vehicle_capacities) + 1


def _generate_depots(
    rng: np.random.Generator,
    config: GenerationConfig,
    total_demands: np.ndarray,
    points: list[tuple[int, int]],
) -> np.ndarray:
    """Generate depot locations and stock totals covering all product demand.

    Depots are the supply sources with initial inventory. Each depot stores
    some amount of each product. The total stock across all depots must exceed
    total demand by the configured surplus ratio to allow for flexible routing.
    """
    # Calculate target stock levels with safety margin
    surplus_ratio = _stock_surplus_ratio(rng, config.stock_level)
    target_stocks = np.ceil(total_demands * (1.0 + surplus_ratio)).astype(int)
    rows: list[list[int]] = []

    for depot_id in range(1, config.depots + 1):
        x, y = _depot_point(rng, config, points, depot_id)
        stocks = []

        for product_idx in range(config.products):
            if depot_id == config.depots:
                # Last depot: assign remaining stock to ensure targets are met
                allocated_before = sum(row[3 + product_idx] for row in rows)
                stock = max(0, target_stocks[product_idx] - int(allocated_before))
            else:
                # Earlier depots: randomly distribute stock around their fair share
                remaining_depots = config.depots - depot_id + 1
                average_share = target_stocks[product_idx] / remaining_depots
                low = max(0, int(0.6 * average_share))
                high = max(low + 1, int(1.4 * average_share) + 1)
                stock = int(rng.integers(low, high))
            stocks.append(stock)
        rows.append([depot_id, x, y, *stocks])

    return np.array(rows, dtype=int)


def _stock_surplus_ratio(rng: np.random.Generator, level: str) -> float:
    """Return the stock surplus ratio for a configured stock level.

    Determines how much extra inventory depots should hold beyond demand.
    This creates realistic scenarios with varying inventory management policies.
    """
    if level == "mixed":
        # For mixed, each generation gets a random level for variety
        level = str(rng.choice(["low", "medium", "high"]))
    low, high = STOCK_SURPLUS_RATIOS[level]
    return float(rng.uniform(low, high))


def _repair_fragmented_depot_stocks(
    depots: np.ndarray,
    stations: np.ndarray,
    vehicle_capacities: np.ndarray,
) -> None:
    """Rebalance stock so every station/product demand is locally coverable.

    Total product stock and fleet capacity do not imply this condition: stock can
    be split into depot quantities that distinct vehicles cannot combine.  When
    that happens, stock is moved from the smallest donor depots to the largest
    depot until the exact assignment bound covers the largest station demand.
    Total stock is unchanged.
    """
    for product_idx in range(stations.shape[1] - 3):
        stock_column = 3 + product_idx
        stocks = depots[:, stock_column]
        maximum_demand = float(stations[:, stock_column].max())
        maximum_delivery = maximum_station_product_delivery(vehicle_capacities, stocks)
        if maximum_delivery + EPSILON >= maximum_demand:
            continue

        receiver_idx = int(np.argmax(stocks))
        donor_indices = sorted(
            (idx for idx in range(len(stocks)) if idx != receiver_idx),
            key=lambda idx: int(stocks[idx]),
        )

        for donor_idx in donor_indices:
            while stocks[donor_idx] > 0 and maximum_delivery + EPSILON < maximum_demand:
                shortage = int(ceil(maximum_demand - maximum_delivery))
                transfer = min(shortage, int(stocks[donor_idx]))
                stocks[donor_idx] -= transfer
                stocks[receiver_idx] += transfer
                maximum_delivery = maximum_station_product_delivery(vehicle_capacities, stocks)

        if maximum_delivery + EPSILON < maximum_demand:
            raise ValueError(
                f"Product {product_idx + 1} stock cannot cover station demand {maximum_demand:.0f} "
                "using distinct vehicles and one loading depot per vehicle."
            )


def _generate_garages(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
    depots: np.ndarray,
) -> np.ndarray:
    """Generate garage locations near depots for clustered layouts.

    Garages are where vehicles are parked overnight or between shifts.
    Placing them near depots reflects realistic logistics networks where
    vehicle maintenance and storage happen close to supply sources.
    """
    rows = []
    for garage_id in range(1, config.garages + 1):
        x, y = _garage_point(rng, config, points, garage_id, depots)
        rows.append([garage_id, x, y])
    return np.array(rows, dtype=int)




def generate(config: GenerationConfig) -> Path:
    """Generate, validate, write, and verify one instance file.

    This is the main orchestration function that:
    1. Validates the configuration
    2. Checks for existing instances with the same code
    3. Generates the instance in memory
    4. Writes it to file
    5. Performs file-level verification

    Returns the path to the generated instance file.
    """
    LOGGER.info("Generating {}", config.filename)

    config_report = validate_generation_config(config)
    _log_generation_report(config_report)
    if not config_report.is_valid:
        raise ValueError("Invalid generation configuration.")

    # Check if instance code already exists (unless force overwrite is enabled)
    existing_codes = existing_instance_codes(config.output_dir)
    if config.instance_code in existing_codes and not config.force:
        raise FileExistsError(
            f"Instance code {config.instance_code!r} already exists in {config.output_dir}. "
            "Use --force or choose another code."
        )

    # Generate the instance in memory
    data = generate_instance_data(config)
    data_report = validate_instance_data(data)
    _log_generation_report(data_report)
    if not data_report.is_valid:
        raise ValueError("Generated instance failed in-memory validation.")

    # Verify a staged file before replacing a possibly valid existing instance.
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mpvrp-instance-", dir=config.output_dir) as temporary_dir:
        staged_path = Path(temporary_dir) / config.filename
        write_instance(data, staged_path)
        verify_report = verify_instance(staged_path, LOGGER)
        log_report(verify_report, LOGGER)
        if not verify_report.is_valid:
            raise ValueError("Generated instance failed file-level verification.")
        if config.filepath.exists() and not config.force:
            raise FileExistsError(f"{config.filepath} already exists. Use --force to overwrite it.")
        os.replace(staged_path, config.filepath)

    LOGGER.info("Generated valid LP instance: {}", config.filepath)
    return config.filepath


def _log_generation_report(report) -> None:
    """Log warnings and errors from a verification report."""
    for warning in report.warnings:
        LOGGER.warning(warning)
    for error in report.errors:
        LOGGER.error(error)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for single-instance generation."""
    parser = argparse.ArgumentParser(description="Generate solver-compatible MPVRP-CC instances.")

    # Naming options: choose between explicit ID or category+number format
    naming = parser.add_argument_group("naming")
    naming.add_argument("-i", "--id", dest="instance_id", help="Full instance code, for example S_001.")
    naming.add_argument("--category", choices=("S", "M", "L"), default="S", help="Instance category.")
    naming.add_argument("--number", default="001", help="Instance number used when --id is omitted.")

    # Problem dimensions: vehicles, depots, garages, stations, products
    dimensions = parser.add_argument_group("dimensions")
    dimensions.add_argument("-v", "--vehicles", type=int, required=True, help="Number of vehicles.")
    dimensions.add_argument("-d", "--depots", type=int, required=True, help="Number of depots.")
    dimensions.add_argument("-g", "--garages", type=int, required=True, help="Number of garages.")
    dimensions.add_argument("-s", "--stations", type=int, required=True, help="Number of service stations.")
    dimensions.add_argument("-p", "--products", type=int, required=True, help="Number of products.")

    # Parameter levels: control difficulty and diversity of generated instances
    ranges = parser.add_argument_group("generation levels")
    ranges.add_argument("--grid", type=int, default=100, help="Integer coordinate grid size.")
    ranges.add_argument(
        "--changeover-cost-level",
        choices=("low", "normal", "high", "mixed"),
        default="normal",
        help="Transition cost level between products.",
    )
    ranges.add_argument(
        "--capacity-level",
        choices=("low", "medium", "large", "mixed"),
        default="medium",
        help="Vehicle capacity level: low under 4000, medium 4000-10000, large above 10000, mixed heterogeneous.",
    )
    ranges.add_argument(
        "--demand-level",
        choices=("low", "medium", "high", "mixed"),
        default="medium",
        help="Station demand level.",
    )
    ranges.add_argument(
        "--stock-level",
        choices=("low", "medium", "high", "mixed"),
        default="medium",
        help="Depot stock surplus level above generated demand.",
    )
    ranges.add_argument("--demand-probability", type=float, default=0.45, help="Probability that a station needs a product.")
    ranges.add_argument(
        "--coordinate-strategy",
        choices=("uniform", "clustered", "corridor"),
        default="clustered",
        help="Spatial layout strategy for depots, garages, and stations.",
    )

    # Output and execution options
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--seed", type=int, help="Random seed.")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite an existing file/code.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
    return parser.parse_args()


def main() -> int:
    """Run the generator CLI.

    Parses command-line arguments, creates a generation configuration,
    and orchestrates the instance generation pipeline.
    """
    args = parse_args()
    configure_run_logging("generate", verbose=args.verbose, quiet=args.quiet, log_dir=args.log_dir)
    try:
        config = GenerationConfig(
            instance_code=_instance_code(args.category, args.number, args.instance_id),
            vehicles=args.vehicles,
            depots=args.depots,
            garages=args.garages,
            stations=args.stations,
            products=args.products,
            output_dir=args.output_dir,
            grid_size=args.grid,
            changeover_cost_level=args.changeover_cost_level,
            capacity_level=args.capacity_level,
            demand_level=args.demand_level,
            stock_level=args.stock_level,
            demand_probability=args.demand_probability,
            coordinate_strategy=args.coordinate_strategy,
            seed=args.seed,
            force=args.force,
        )
        generate(config)
        return 0
    except (FileExistsError, ValueError) as exc:
        LOGGER.error("{}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
