from __future__ import annotations

import argparse
import logging
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


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _instance_code(category: str | None, number: str | None, instance_id: str | None) -> str:
    if instance_id:
        return instance_id
    category = (category or "S").upper()
    raw_number = number or "001"
    if not raw_number.isdigit():
        raise ValueError("--number must contain digits only.")
    return f"{category}_{int(raw_number):03d}"


def generate_instance_data(config: GenerationConfig) -> InstanceData:
    report = validate_generation_config(config)
    if not report.is_valid:
        raise ValueError("; ".join(report.errors))

    rng = np.random.default_rng(config.seed)
    params = np.array([config.products, config.depots, config.garages, config.stations, config.vehicles], dtype=int)
    transition_costs = _generate_metric_transition_costs(rng, config)

    vehicles = _generate_vehicles(rng, config)
    total_fleet_capacity = int(vehicles[:, 1].sum())
    stations, total_demands, points = _generate_stations(rng, config, total_fleet_capacity)
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


def _generate_metric_transition_costs(rng: np.random.Generator, config: GenerationConfig) -> np.ndarray:
    if config.products == 1:
        return np.zeros((1, 1), dtype=float)

    positions = rng.permutation(np.linspace(0.0, 1.0, config.products))
    distances = np.abs(positions[:, None] - positions[None, :])
    max_distance = float(distances.max())
    if max_distance <= EPSILON:
        costs = np.full((config.products, config.products), config.min_transition_cost, dtype=float)
    else:
        costs = config.min_transition_cost + (
            (config.max_transition_cost - config.min_transition_cost) * distances / max_distance
        )
    np.fill_diagonal(costs, 0.0)
    return costs.round(1)


def _generate_vehicles(rng: np.random.Generator, config: GenerationConfig) -> np.ndarray:
    rows = []
    for vehicle_id in range(1, config.vehicles + 1):
        rows.append(
            [
                vehicle_id,
                int(rng.integers(config.min_capacity, config.max_capacity + 1)),
                int(rng.integers(1, config.garages + 1)),
                int(rng.integers(1, config.products + 1)),
            ]
        )
    return np.array(rows, dtype=float)


def _generate_stations(
    rng: np.random.Generator,
    config: GenerationConfig,
    total_fleet_capacity: int,
) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
    points: list[tuple[float, float]] = []
    centers = _station_centers(rng, config)
    rows: list[list[float]] = []
    total_demands = np.zeros(config.products, dtype=float)
    max_cell_demand = min(config.max_demand, total_fleet_capacity)

    for station_id in range(1, config.stations + 1):
        x, y = _station_point(rng, config, points, centers, station_id)
        demands = np.zeros(config.products, dtype=int)
        active_products = rng.random(config.products) <= config.demand_probability
        if not active_products.any():
            active_products[int(rng.integers(0, config.products))] = True
        for product_idx, is_active in enumerate(active_products):
            if is_active:
                demands[product_idx] = int(rng.integers(config.min_demand, max_cell_demand + 1))
        rows.append([station_id, x, y, *demands.tolist()])
        total_demands += demands

    station_array = np.array(rows, dtype=float)
    for product_idx in range(config.products):
        if total_demands[product_idx] > EPSILON:
            continue
        station_idx = int(rng.integers(0, config.stations))
        demand = int(rng.integers(config.min_demand, max_cell_demand + 1))
        station_array[station_idx, 3 + product_idx] = demand
        total_demands[product_idx] += demand

    return station_array, total_demands, points


def _generate_depots(
    rng: np.random.Generator,
    config: GenerationConfig,
    total_demands: np.ndarray,
    points: list[tuple[float, float]],
) -> np.ndarray:
    target_stocks = np.ceil(total_demands * (1.0 + config.stock_surplus_ratio)).astype(int)
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


def _generate_garages(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[float, float]],
    depots: np.ndarray,
) -> np.ndarray:
    rows = []
    for garage_id in range(1, config.garages + 1):
        x, y = _garage_point(rng, config, points, garage_id, depots)
        rows.append([garage_id, x, y])
    return np.array(rows, dtype=float)


def _station_centers(rng: np.random.Generator, config: GenerationConfig) -> list[tuple[float, float]]:
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
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    depot = depots[(garage_id - 1) % len(depots)]
    return _unique_point_near(rng, config, points, float(depot[1]), float(depot[2]), 0.07 * config.grid_size)


def _unique_point(rng: np.random.Generator, config: GenerationConfig, points: list[tuple[float, float]]) -> tuple[float, float]:
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
    for _ in range(1_000):
        x = round(float(np.clip(rng.normal(center_x, spread), 0, config.grid_size)), 1)
        y = round(float(np.clip(rng.normal(center_y, spread), 0, config.grid_size)), 1)
        if _is_far_enough(x, y, points, config.min_point_distance):
            points.append((x, y))
            return x, y
    return _unique_point(rng, config, points)


def _is_far_enough(x: float, y: float, points: list[tuple[float, float]], minimum_distance: float) -> bool:
    return all(np.hypot(x - px, y - py) >= minimum_distance for px, py in points)


def _append_clipped_point(points: list[tuple[float, float]], x: float, y: float, grid_size: float) -> tuple[float, float]:
    point = (round(float(np.clip(x, 0, grid_size)), 1), round(float(np.clip(y, 0, grid_size)), 1))
    points.append(point)
    return point


def generate(config: GenerationConfig) -> Path:
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
    min_capacite: int = 4_000,
    max_capacite: int = 10_000,
    min_transition_cost: float = 10.0,
    max_transition_cost: float = 80.0,
    min_demand: int = 500,
    max_demand: int = 5_000,
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
        min_capacity=min_capacite,
        max_capacity=max_capacite,
        min_transition_cost=min_transition_cost,
        max_transition_cost=max_transition_cost,
        min_demand=min_demand,
        max_demand=max_demand,
        seed=seed,
        force=force_overwrite,
    )
    try:
        return str(generate(config))
    except (FileExistsError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return None


def parse_args() -> argparse.Namespace:
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

    ranges = parser.add_argument_group("generation ranges")
    ranges.add_argument("--grid", type=float, default=100.0, help="Coordinate grid size.")
    ranges.add_argument("--min-capacity", type=int, default=4_000, help="Minimum vehicle capacity.")
    ranges.add_argument("--max-capacity", type=int, default=10_000, help="Maximum vehicle capacity.")
    ranges.add_argument("--min-transition-cost", type=float, default=10.0, help="Minimum non-diagonal transition cost.")
    ranges.add_argument("--max-transition-cost", type=float, default=80.0, help="Maximum non-diagonal transition cost.")
    ranges.add_argument("--min-demand", type=int, default=500, help="Minimum positive station/product demand.")
    ranges.add_argument("--max-demand", type=int, default=5_000, help="Maximum positive station/product demand.")
    ranges.add_argument("--demand-probability", type=float, default=0.45, help="Probability that a station needs a product.")
    ranges.add_argument("--stock-surplus-ratio", type=float, default=0.20, help="Stock surplus above demand by product.")
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
            min_capacity=args.min_capacity,
            max_capacity=args.max_capacity,
            min_transition_cost=args.min_transition_cost,
            max_transition_cost=args.max_transition_cost,
            min_demand=args.min_demand,
            max_demand=args.max_demand,
            demand_probability=args.demand_probability,
            stock_surplus_ratio=args.stock_surplus_ratio,
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
