from __future__ import annotations

import argparse
import logging
from math import ceil
import uuid
from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.instance_io import existing_instance_codes, write_instance
from tools.instance_schema import DEFAULT_OUTPUT_DIR, EPSILON, GenerationConfig, InstanceData
from tools.instance_validation import validate_generation_config, validate_instance_data
from tools.verificator import log_report, verify_instance

LOGGER = logging.getLogger("mpvrp.generator")

CHANGEOVER_COST_RANGES = {
    "low": (25.0, 150.0),
    "normal": (150.1, 500.0),
    "high": (500.1, 2500.0),
}
CAPACITY_RANGES = {
    "low": (1_000, 3_999),
    "medium": (4_000, 10_000),
    "large": (10_001, 25_000),
}
DEMAND_RANGES = {
    "low": (100, 1_000),
    "medium": (1_000, 4_000),
    "high": (4_000, 9_000),
}
STOCK_SURPLUS_RATIOS = {
    "low": (0.02, 0.10),
    "medium": (0.15, 0.30),
    "high": (0.40, 0.80),
}


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure command-line logging for generator scripts."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _instance_code(category: str | None, number: str | None, instance_id: str | None) -> str:
    """Build the public instance code from CLI naming options."""
    if instance_id:
        return instance_id
    category = (category or "S").upper()
    raw_number = number or "001"
    if not raw_number.isdigit():
        raise ValueError("--number must contain digits only.")
    return f"{category}_{int(raw_number):03d}"


def generate_instance_data(config: GenerationConfig) -> InstanceData:
    """Generate one in-memory MPVRP-CC instance and validate its inputs."""
    report = validate_generation_config(config)
    if not report.is_valid:
        raise ValueError("; ".join(report.errors))

    rng = np.random.default_rng(config.seed)
    params = np.array([config.products, config.depots, config.garages, config.stations, config.vehicles], dtype=int)
    transition_costs = _generate_transition_costs(rng, config)

    vehicles = _generate_vehicles(rng, config)
    vehicle_capacities = vehicles[:, 1].astype(float)
    stations, total_demands, points = _generate_stations(rng, config, vehicle_capacities)
    depots = _generate_depots(rng, config, total_demands, points)
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
    """Generate product changeover costs with a zero self-transition diagonal."""
    if config.products == 1:
        return np.zeros((1, 1), dtype=float)

    if config.changeover_cost_level == "mixed":
        return _generate_mixed_transition_costs(rng, config.products)

    min_cost, max_cost = _changeover_cost_bounds(config)
    costs = rng.uniform(min_cost, max_cost, size=(config.products, config.products))
    np.fill_diagonal(costs, 0.0)
    return costs.round(1)


def _generate_mixed_transition_costs(rng: np.random.Generator, products: int) -> np.ndarray:
    """Generate heterogeneous changeover costs by sampling a level per arc."""
    costs = np.zeros((products, products), dtype=float)
    for from_product in range(products):
        for to_product in range(products):
            if from_product == to_product:
                continue
            level = str(rng.choice(["low", "normal", "high"]))
            min_cost, max_cost = CHANGEOVER_COST_RANGES[level]
            costs[from_product, to_product] = float(rng.uniform(min_cost, max_cost))
    np.fill_diagonal(costs, 0.0)
    return costs.round(1)


def _changeover_cost_bounds(config: GenerationConfig) -> tuple[float, float]:
    """Return the numeric cost range for the configured changeover level."""
    return CHANGEOVER_COST_RANGES[config.changeover_cost_level]


def _generate_vehicles(rng: np.random.Generator, config: GenerationConfig) -> np.ndarray:
    """Generate vehicle IDs, capacities, home garages, and initial products."""
    rows = []
    for vehicle_id in range(1, config.vehicles + 1):
        low, high = _capacity_bounds(rng, config.capacity_level)
        rows.append(
            [
                vehicle_id,
                int(rng.integers(low, high + 1)),
                int(rng.integers(1, config.garages + 1)),
                int(rng.integers(1, config.products + 1)),
            ]
        )
    return np.array(rows, dtype=float)


def _capacity_bounds(rng: np.random.Generator, level: str) -> tuple[int, int]:
    """Return a capacity range, resolving mixed levels randomly."""
    if level == "mixed":
        level = str(rng.choice(["low", "medium", "large"]))
    return CAPACITY_RANGES[level]


def _generate_stations(
    rng: np.random.Generator,
    config: GenerationConfig,
    vehicle_capacities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
    """Generate station locations and product demands that fit LP bounds."""
    total_fleet_capacity = int(vehicle_capacities.sum())
    points: list[tuple[float, float]] = []
    centers = _station_centers(rng, config)
    rows: list[list[float]] = []
    total_demands = np.zeros(config.products, dtype=float)

    for station_id in range(1, config.stations + 1):
        x, y = _station_point(rng, config, points, centers, station_id)
        demands = np.zeros(config.products, dtype=int)
        active_products = rng.random(config.products) <= config.demand_probability
        if not active_products.any():
            active_products[int(rng.integers(0, config.products))] = True
        for product_idx, is_active in enumerate(active_products):
            if is_active:
                low, high = _demand_bounds(rng, config.demand_level, total_fleet_capacity)
                demands[product_idx] = int(rng.integers(low, high + 1))
        rows.append([station_id, x, y, *demands.tolist()])
        total_demands += demands

    station_array = np.array(rows, dtype=float)
    for product_idx in range(config.products):
        if total_demands[product_idx] > EPSILON:
            continue
        station_idx = int(rng.integers(0, config.stations))
        low, high = _demand_bounds(rng, config.demand_level, total_fleet_capacity)
        demand = int(rng.integers(low, high + 1))
        station_array[station_idx, 3 + product_idx] = demand
        total_demands[product_idx] += demand

    _enforce_trip_bound_floor(rng, config, station_array, total_demands, vehicle_capacities)
    return station_array, total_demands, points


def _demand_bounds(rng: np.random.Generator, level: str, total_fleet_capacity: int) -> tuple[int, int]:
    """Return a demand range capped by the total fleet capacity."""
    if level == "mixed":
        level = str(rng.choice(["low", "medium", "high"]))
    low, high = DEMAND_RANGES[level]
    high = min(high, max(1, total_fleet_capacity))
    low = min(low, high)
    return low, high


def _enforce_trip_bound_floor(
    rng: np.random.Generator,
    config: GenerationConfig,
    stations: np.ndarray,
    total_demands: np.ndarray,
    vehicle_capacities: np.ndarray,
) -> None:
    """Raise demand so the default LP trip bound can cover all products.

    The LP computes a uniform per-vehicle bound as
    ceil(total_demand / fleet_capacity). Because each mini-route carries only
    one product, generated instances should not have fewer default trips per
    vehicle than products or product-level capacity lower bounds.
    """
    total_fleet_capacity = int(vehicle_capacities.sum())
    if config.products <= 1 or total_fleet_capacity <= 0:
        return

    for _ in range(20):
        current_total = int(round(float(total_demands.sum())))
        current_bound = ceil(current_total / total_fleet_capacity)
        required_slots = _minimum_generated_product_slots(stations, vehicle_capacities, config.products)
        required_bound = max(config.products, ceil(required_slots / len(vehicle_capacities)))
        if current_bound >= required_bound:
            return

        target_total = (required_bound - 1) * total_fleet_capacity + 1
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
    """Increase station/product demands without exceeding fleet capacity per cell."""
    if remaining <= 0:
        return

    max_cell_demand = float(total_fleet_capacity)
    candidates = [
        (station_idx, product_idx)
        for station_idx in range(config.stations)
        for product_idx in range(config.products)
        if stations[station_idx, 3 + product_idx] < max_cell_demand - EPSILON
    ]
    rng.shuffle(candidates)

    while remaining > 0 and candidates:
        station_idx, product_idx = candidates.pop(0)
        column = 3 + product_idx
        spare = int(max_cell_demand - stations[station_idx, column])
        if spare <= 0:
            continue
        increment = min(remaining, spare)
        stations[station_idx, column] += increment
        total_demands[product_idx] += increment
        remaining -= increment

        # Requeue cells that can still absorb demand to spread large increases.
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
    """Estimate product trip slots needed by generated demand."""
    max_vehicle_capacity = float(vehicle_capacities.max())
    required = 0
    for product_idx in range(products):
        product_demands = stations[:, 3 + product_idx]
        product_total = float(product_demands.sum())
        if product_total <= EPSILON:
            continue

        aggregate_slots = ceil(product_total / max_vehicle_capacity)
        station_slots = max(
            _minimum_distinct_vehicle_slots(float(demand), vehicle_capacities)
            for demand in product_demands
            if demand > EPSILON
        )
        required += max(1, aggregate_slots, station_slots)
    return required


def _minimum_distinct_vehicle_slots(demand: float, vehicle_capacities: np.ndarray) -> int:
    """Count vehicles needed to cover one station/product demand once each."""
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
    points: list[tuple[float, float]],
) -> np.ndarray:
    """Generate depot locations and stock totals covering all product demand."""
    surplus_ratio = _stock_surplus_ratio(rng, config.stock_level)
    target_stocks = np.ceil(total_demands * (1.0 + surplus_ratio)).astype(int)
    rows: list[list[float]] = []

    for depot_id in range(1, config.depots + 1):
        x, y = _depot_point(rng, config, points, depot_id)
        stocks = []
        for product_idx in range(config.products):
            if depot_id == config.depots:
                allocated_before = sum(row[3 + product_idx] for row in rows)
                stock = max(0, target_stocks[product_idx] - int(allocated_before))
            else:
                remaining_depots = config.depots - depot_id + 1
                average_share = target_stocks[product_idx] / remaining_depots
                low = max(0, int(0.6 * average_share))
                high = max(low + 1, int(1.4 * average_share) + 1)
                stock = int(rng.integers(low, high))
            stocks.append(stock)
        rows.append([depot_id, x, y, *stocks])

    return np.array(rows, dtype=float)


def _stock_surplus_ratio(rng: np.random.Generator, level: str) -> float:
    """Return the stock surplus ratio for a configured stock level."""
    if level == "mixed":
        level = str(rng.choice(["low", "medium", "high"]))
    low, high = STOCK_SURPLUS_RATIOS[level]
    return float(rng.uniform(low, high))


def _generate_garages(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    depots: np.ndarray,
) -> np.ndarray:
    """Generate garage locations near depots for clustered layouts."""
    rows = []
    for garage_id in range(1, config.garages + 1):
        x, y = _garage_point(rng, config, points, garage_id, depots)
        rows.append([garage_id, x, y])
    return np.array(rows, dtype=float)


def _station_centers(rng: np.random.Generator, config: GenerationConfig) -> list[tuple[float, float]]:
    """Return cluster centers used for non-uniform station layouts."""
    if config.coordinate_strategy == "uniform":
        return []
    if config.coordinate_strategy == "corridor":
        return [(0.2 * config.grid_size, 0.35 * config.grid_size), (0.8 * config.grid_size, 0.65 * config.grid_size)]

    center_count = min(4, max(2, int(np.sqrt(config.stations))))
    margin = 0.18 * config.grid_size
    return [
        (
            float(rng.uniform(margin, config.grid_size - margin)),
            float(rng.uniform(margin, config.grid_size - margin)),
        )
        for _ in range(center_count)
    ]


def _station_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    centers: list[tuple[float, float]],
    station_id: int,
) -> tuple[float, float]:
    """Generate one station coordinate according to the spatial strategy."""
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    if config.coordinate_strategy == "corridor":
        t = (station_id - 1) / max(1, config.stations - 1)
        base_x = (0.1 + 0.8 * t) * config.grid_size
        base_y = (0.25 + 0.5 * t) * config.grid_size
        spread = 0.08 * config.grid_size
        return _unique_point_near(rng, config, points, base_x, base_y, spread)

    center_x, center_y = centers[int(rng.integers(0, len(centers)))]
    spread = 0.12 * config.grid_size
    return _unique_point_near(rng, config, points, center_x, center_y, spread)


def _depot_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    depot_id: int,
) -> tuple[float, float]:
    """Generate one depot coordinate according to the spatial strategy."""
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    anchors = [
        (0.08 * config.grid_size, 0.10 * config.grid_size),
        (0.92 * config.grid_size, 0.12 * config.grid_size),
        (0.10 * config.grid_size, 0.90 * config.grid_size),
        (0.90 * config.grid_size, 0.88 * config.grid_size),
    ]
    anchor_x, anchor_y = anchors[(depot_id - 1) % len(anchors)]
    return _unique_point_near(rng, config, points, anchor_x, anchor_y, 0.04 * config.grid_size)


def _garage_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    garage_id: int,
    depots: np.ndarray,
) -> tuple[float, float]:
    """Generate one garage coordinate, usually close to a depot."""
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    depot = depots[(garage_id - 1) % len(depots)]
    return _unique_point_near(rng, config, points, float(depot[1]), float(depot[2]), 0.07 * config.grid_size)


def _unique_point(rng: np.random.Generator, config: GenerationConfig, points: list[tuple[float, float]]) -> tuple[float, float]:
    """Draw a point that respects the configured minimum distance when possible."""
    for _ in range(1_000):
        x = round(float(rng.uniform(0, config.grid_size)), 1)
        y = round(float(rng.uniform(0, config.grid_size)), 1)
        if _is_far_enough(x, y, points, config.min_point_distance):
            points.append((x, y))
            return x, y
    return _append_clipped_point(points, x, y, config.grid_size)


def _unique_point_near(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    center_x: float,
    center_y: float,
    spread: float,
) -> tuple[float, float]:
    """Draw a unique point near a center, falling back to uniform sampling."""
    for _ in range(1_000):
        x = round(float(np.clip(rng.normal(center_x, spread), 0, config.grid_size)), 1)
        y = round(float(np.clip(rng.normal(center_y, spread), 0, config.grid_size)), 1)
        if _is_far_enough(x, y, points, config.min_point_distance):
            points.append((x, y))
            return x, y
    return _unique_point(rng, config, points)


def _is_far_enough(x: float, y: float, points: list[tuple[float, float]], minimum_distance: float) -> bool:
    """Check whether a candidate point is separated from existing points."""
    return all(np.hypot(x - px, y - py) >= minimum_distance for px, py in points)


def _append_clipped_point(points: list[tuple[float, float]], x: float, y: float, grid_size: float) -> tuple[float, float]:
    """Append a final clipped point after coordinate retries are exhausted."""
    point = (round(float(np.clip(x, 0, grid_size)), 1), round(float(np.clip(y, 0, grid_size)), 1))
    points.append(point)
    return point


def generate(config: GenerationConfig) -> Path:
    """Generate, validate, write, and verify one instance file."""
    LOGGER.info("Generating %s", config.filename)

    config_report = validate_generation_config(config)
    _log_generation_report(config_report)
    if not config_report.is_valid:
        raise ValueError("Invalid generation configuration.")

    existing_codes = existing_instance_codes(config.output_dir)
    if config.instance_code in existing_codes and not config.force:
        raise FileExistsError(
            f"Instance code {config.instance_code!r} already exists in {config.output_dir}. "
            "Use --force or choose another code."
        )

    data = generate_instance_data(config)
    data_report = validate_instance_data(data)
    _log_generation_report(data_report)
    if not data_report.is_valid:
        raise ValueError("Generated instance failed in-memory validation.")

    path = write_instance(data, config.filepath, force=config.force)
    verify_report = verify_instance(path, LOGGER)
    log_report(verify_report, LOGGER)
    if not verify_report.is_valid:
        raise ValueError("Generated instance failed file-level verification.")

    LOGGER.info("Generated valid LP instance: %s", path)
    return path


def _log_generation_report(report) -> None:
    """Log warnings and errors from a verification report."""
    for warning in report.warnings:
        LOGGER.warning(warning)
    for error in report.errors:
        LOGGER.error(error)


def generer_instance(
    id_inst: str | None = None,
    nb_v: int | None = None,
    nb_d: int | None = None,
    nb_g: int | None = None,
    nb_s: int | None = None,
    nb_p: int | None = None,
    max_coord: float = 100.0,
    changeover_cost_level: str = "normal",
    capacity_level: str = "medium",
    demand_level: str = "medium",
    stock_level: str = "medium",
    seed: int | None = None,
    force_overwrite: bool = False,
    output_dir: str | Path | None = None,
    silent: bool = False,
) -> str | None:
    """Backward-compatible wrapper around the structured generator."""
    configure_logging(quiet=silent)
    missing = [nb_v, nb_d, nb_g, nb_s, nb_p]
    if id_inst is None or any(value is None for value in missing):
        LOGGER.error("Interactive generation is not supported. Provide all dimensions explicitly.")
        return None

    config = GenerationConfig(
        instance_code=id_inst,
        vehicles=nb_v,
        depots=nb_d,
        garages=nb_g,
        stations=nb_s,
        products=nb_p,
        output_dir=Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR,
        grid_size=max_coord,
        changeover_cost_level=changeover_cost_level,
        capacity_level=capacity_level,
        demand_level=demand_level,
        stock_level=stock_level,
        seed=seed,
        force=force_overwrite,
    )
    try:
        return str(generate(config))
    except (FileExistsError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return None


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for single-instance generation."""
    parser = argparse.ArgumentParser(description="Generate MPVRP-CC instances compatible with models/lp.py.")
    naming = parser.add_argument_group("naming")
    naming.add_argument("-i", "--id", dest="instance_id", help="Full instance code, for example S_001.")
    naming.add_argument("--category", choices=("S", "M", "L"), default="S", help="Instance category.")
    naming.add_argument("--number", default="001", help="Instance number used when --id is omitted.")

    dimensions = parser.add_argument_group("dimensions")
    dimensions.add_argument("-v", "--vehicles", type=int, required=True, help="Number of vehicles.")
    dimensions.add_argument("-d", "--depots", type=int, required=True, help="Number of depots.")
    dimensions.add_argument("-g", "--garages", type=int, required=True, help="Number of garages.")
    dimensions.add_argument("-s", "--stations", type=int, required=True, help="Number of service stations.")
    dimensions.add_argument("-p", "--products", type=int, required=True, help="Number of products.")

    ranges = parser.add_argument_group("generation levels")
    ranges.add_argument("--grid", type=float, default=100.0, help="Coordinate grid size.")
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

    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--seed", type=int, help="Random seed.")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite an existing file/code.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    """Run the generator CLI."""
    args = parse_args()
    configure_logging(verbose=args.verbose, quiet=args.quiet)
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
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
