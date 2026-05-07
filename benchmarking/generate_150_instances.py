from __future__ import annotations

import argparse
import csv
import itertools
import logging
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.generator import configure_logging, generate
from tools.instance_schema import GenerationConfig

LOGGER = logging.getLogger("mpvrp.generate_150")
MAX_GENERATION_ATTEMPTS = 50

CHANGEOVER_LEVELS = ("low", "normal", "high", "mixed")
CAPACITY_LEVELS = ("low", "medium", "large", "mixed")
DEMAND_LEVELS = ("low", "medium", "high", "mixed")
STOCK_LEVELS = ("low", "medium", "high", "mixed")
COORDINATE_STRATEGIES = ("clustered", "corridor", "uniform")


def _level_combinations(rng: np.random.Generator, count: int) -> list[tuple[str, str, str, str]]:
    """Return shuffled generation-level combinations, cycling if needed."""
    combinations = list(itertools.product(CHANGEOVER_LEVELS, CAPACITY_LEVELS, DEMAND_LEVELS, STOCK_LEVELS))
    rng.shuffle(combinations)
    if count <= len(combinations):
        return combinations[:count]

    selected = combinations[:]
    while len(selected) < count:
        rng.shuffle(combinations)
        selected.extend(combinations[: count - len(selected)])
    return selected


def _draw_dimension(rng: np.random.Generator, low: int, high: int) -> int:
    """Draw one inclusive integer dimension."""
    return int(rng.integers(low, high + 1))


def _random_level_combination(rng: np.random.Generator) -> tuple[str, str, str, str]:
    """Draw one random level combination for a retry attempt."""
    return (
        str(rng.choice(CHANGEOVER_LEVELS)),
        str(rng.choice(CAPACITY_LEVELS)),
        str(rng.choice(DEMAND_LEVELS)),
        str(rng.choice(STOCK_LEVELS)),
    )


def _build_generation_config(
    rng: np.random.Generator,
    args: argparse.Namespace,
    instance_id: str,
    levels: tuple[str, str, str, str],
) -> tuple[GenerationConfig, dict[str, str | int | float]]:
    """Create one randomized generation config and its manifest row data."""
    changeover, capacity, demand, stock = levels
    vehicles = _draw_dimension(rng, 1, 10)
    depots = _draw_dimension(rng, 1, 8)
    garages = _draw_dimension(rng, 1, 5)
    stations = _draw_dimension(rng, 3, 50)
    products = _draw_dimension(rng, args.min_products, args.max_products)
    demand_probability = round(float(rng.uniform(args.min_demand_probability, args.max_demand_probability)), 3)
    coordinate_strategy = str(rng.choice(COORDINATE_STRATEGIES))

    config = GenerationConfig(
        instance_code=instance_id,
        vehicles=vehicles,
        depots=depots,
        garages=garages,
        stations=stations,
        products=products,
        output_dir=args.output_dir,
        grid_size=args.grid,
        changeover_cost_level=changeover,
        capacity_level=capacity,
        demand_level=demand,
        stock_level=stock,
        demand_probability=demand_probability,
        coordinate_strategy=coordinate_strategy,
        seed=int(rng.integers(0, 2**32 - 1)),
        force=args.force,
    )

    row = {
        "id": instance_id,
        "file": config.filename,
        "vehicles": vehicles,
        "depots": depots,
        "garages": garages,
        "stations": stations,
        "products": products,
        "changeover_cost_level": changeover,
        "capacity_level": capacity,
        "demand_level": demand,
        "stock_level": stock,
        "demand_probability": demand_probability,
        "coordinate_strategy": coordinate_strategy,
    }
    return config, row


def _generate_instance_with_backtracking(
    rng: np.random.Generator,
    args: argparse.Namespace,
    instance_id: str,
    initial_levels: tuple[str, str, str, str],
) -> tuple[Path, dict[str, str | int | float]]:
    """Generate one instance, retrying with fresh parameters when validation fails."""
    levels = initial_levels
    last_error: Exception | None = None

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if attempt > 1:
            levels = _random_level_combination(rng)

        config, row = _build_generation_config(rng, args, instance_id, levels)
        preexisting_file = config.filepath.exists()
        try:
            return generate(config), row
        except FileExistsError:
            raise
        except ValueError as exc:
            last_error = exc
            if not preexisting_file and config.filepath.exists():
                config.filepath.unlink()

            if attempt < MAX_GENERATION_ATTEMPTS:
                LOGGER.warning(
                    "Backtracking %s after failed attempt %s/%s: %s",
                    instance_id,
                    attempt,
                    MAX_GENERATION_ATTEMPTS,
                    exc,
                )
                continue
            break

    raise ValueError(
        f"Unable to generate instance {instance_id} after {MAX_GENERATION_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def generate_dataset(args: argparse.Namespace) -> Path:
    """Generate a batch of validated instances and write a manifest CSV."""
    rng = np.random.default_rng(args.seed)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / args.manifest
    level_combinations = _level_combinations(rng, args.count)

    rows: list[dict[str, str | int | float]] = []
    for offset, (changeover, capacity, demand, stock) in enumerate(level_combinations):
        number = args.start_id + offset
        instance_id = f"{number:03d}"
        # The generator will adjust demand so lp.py's default trip bound is at
        # least the product count; these ranges keep the batch diverse without
        # forcing obviously oversized fleets for tiny product sets.
        path, row = _generate_instance_with_backtracking(rng, args, instance_id, (changeover, capacity, demand, stock))
        row["file"] = path.name
        rows.append(row)
        LOGGER.info("Generated %s/%s: %s", offset + 1, args.count, path.name)

    with manifest_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    LOGGER.info("Wrote manifest: %s", manifest_path)
    return manifest_path


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the 150-instance benchmark generator."""
    parser = argparse.ArgumentParser(
        description="Generate a balanced dataset of MPVRP-CC instances with numeric IDs only."
    )
    parser.add_argument("--count", type=int, default=150, help="Number of instances to generate.")
    parser.add_argument("--start-id", type=int, default=1, help="First numeric instance ID.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "inst",
        help="Output directory for generated .dat files.",
    )
    parser.add_argument("--manifest", default="manifest.csv", help="Manifest CSV filename written in output-dir.")
    parser.add_argument("--seed", type=int, default=20260507, help="Dataset seed.")
    parser.add_argument("--grid", type=float, default=100.0, help="Coordinate grid size.")
    parser.add_argument("--min-products", type=int, default=1, help="Minimum number of products.")
    parser.add_argument("--max-products", type=int, default=6, help="Maximum number of products.")
    parser.add_argument(
        "--min-demand-probability",
        type=float,
        default=0.4,
        help="Minimum probability that a station needs a given product.",
    )
    parser.add_argument(
        "--max-demand-probability",
        type=float,
        default=0.9,
        help="Maximum probability that a station needs a given product.",
    )
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing instance files.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    """Run the benchmark dataset generation CLI."""
    args = parse_args()
    configure_logging(verbose=args.verbose, quiet=args.quiet)

    if args.count < 1:
        LOGGER.error("--count must be at least 1.")
        return 1
    if args.start_id < 0:
        LOGGER.error("--start-id must be non-negative.")
        return 1
    if args.min_products < 1 or args.max_products < args.min_products:
        LOGGER.error("Product bounds must satisfy 1 <= min-products <= max-products.")
        return 1
    if not 0 < args.min_demand_probability <= args.max_demand_probability <= 1:
        LOGGER.error("Demand probability bounds must satisfy 0 < min <= max <= 1.")
        return 1

    try:
        generate_dataset(args)
    except (FileExistsError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
