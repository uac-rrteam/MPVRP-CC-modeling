from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from loguru import logger

from tools.instances.generate import generate
from tools.instances.models import GenerationConfig
from tools.run_logging import configure_run_logging
from paths import CHANGEOVER_INSTANCES_DIR

LOGGER = logger
MAX_GENERATION_ATTEMPTS = 50

# Low changeover costs are reserved for separate sensitivity experiments.  The
# main benchmark samples only regimes where changeovers can affect routing.
CHANGEOVER_LEVELS = ("normal", "high", "mixed")
CAPACITY_LEVELS = ("low", "medium", "large", "mixed")
DEMAND_LEVELS = ("low", "medium", "high", "mixed")
STOCK_LEVELS = ("low", "medium", "high", "mixed")
COORDINATE_STRATEGIES = ("clustered", "corridor", "uniform")


def _level_combinations(rng: np.random.Generator, count: int) -> list[tuple[str, str, str, str]]:
    """Return combinations stratified by material changeover-cost level.

    Changeover levels differ by at most one occurrence for any requested
    dataset size.  The other generation dimensions remain shuffled and cycle
    independently within each changeover stratum when necessary.
    """
    other_levels = list(itertools.product(CAPACITY_LEVELS, DEMAND_LEVELS, STOCK_LEVELS))
    pools = {level: other_levels.copy() for level in CHANGEOVER_LEVELS}
    positions = dict.fromkeys(CHANGEOVER_LEVELS, 0)
    for pool in pools.values():
        rng.shuffle(pool)

    changeover_levels = list(itertools.islice(itertools.cycle(CHANGEOVER_LEVELS), count))
    rng.shuffle(changeover_levels)

    selected: list[tuple[str, str, str, str]] = []
    for changeover in changeover_levels:
        position = positions[changeover]
        if position == len(other_levels):
            rng.shuffle(pools[changeover])
            position = 0
        capacity, demand, stock = pools[changeover][position]
        positions[changeover] = position + 1
        selected.append((changeover, capacity, demand, stock))
    return selected


def _draw_dimension(rng: np.random.Generator, low: int, high: int) -> int:
    """Draw one inclusive integer dimension."""
    return int(rng.integers(low, high + 1))


def _random_level_combination(
    rng: np.random.Generator,
    changeover: str,
) -> tuple[str, str, str, str]:
    """Redraw secondary levels for a retry without changing its stratum."""
    return (
        changeover,
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
        "instance_seed": config.seed,
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
    rejections: list[dict[str, object]] = []

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if attempt > 1:
            levels = _random_level_combination(rng, initial_levels[0])

        config, row = _build_generation_config(rng, args, instance_id, levels)
        LOGGER.debug("Generation attempt {} for {}: seed={} levels={}", attempt, instance_id, config.seed, levels)
        try:
            path = generate(config)
            row["attempts"] = attempt
            row["rejections"] = json.dumps(rejections, separators=(",", ":"))
            return path, row
        except FileExistsError:
            raise
        except ValueError as exc:
            last_error = exc
            rejections.append({"seed": config.seed, "levels": levels, "reason": str(exc)})
            if attempt < MAX_GENERATION_ATTEMPTS:
                LOGGER.warning(
                    "Backtracking {} after failed attempt {}/{}: {}",
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
    manifest_name = Path(args.manifest)
    if manifest_name.name != args.manifest:
        raise ValueError("--manifest must be a filename within --output-dir.")
    manifest_path = output_dir / manifest_name
    level_combinations = _level_combinations(rng, args.count)
    with tempfile.TemporaryDirectory(prefix=".mpvrp-batch-", dir=output_dir) as temporary_dir:
        stage_dir = Path(temporary_dir)
        staged_args = argparse.Namespace(**vars(args))
        staged_args.output_dir = stage_dir
        rows: list[dict[str, str | int | float]] = []
        for offset, levels in enumerate(level_combinations):
            instance_id = f"{args.start_id + offset:03d}"
            path, row = _generate_instance_with_backtracking(rng, staged_args, instance_id, levels)
            row["file"] = path.name
            rows.append(row)
            LOGGER.info("Staged {}/{}: {} (attempts={})", offset + 1, args.count, path.name, row.get("attempts", 1))

        staged_manifest = stage_dir / manifest_name
        with staged_manifest.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        targets = [(stage_dir / row["file"], output_dir / row["file"]) for row in rows]
        targets.append((staged_manifest, manifest_path))
        if not args.force:
            existing = [str(target) for _, target in targets if target.exists()]
            if existing:
                raise FileExistsError(f"Output already exists: {', '.join(existing)}")

        # Keep replaced files recoverable until the whole batch is committed.
        backup_dir = stage_dir / "backup"
        backup_dir.mkdir()
        committed: list[Path] = []
        backups: list[tuple[Path, Path]] = []
        try:
            for index, (staged, target) in enumerate(targets):
                if target.exists():
                    backup = backup_dir / str(index)
                    os.replace(target, backup)
                    backups.append((backup, target))
                os.replace(staged, target)
                committed.append(target)
        except OSError:
            for target in reversed(committed):
                target.unlink()
            for backup, target in reversed(backups):
                os.replace(backup, target)
            raise

    LOGGER.info("Wrote manifest: {}", manifest_path)
    LOGGER.info("Generation retries: {} across {} instances", sum(int(row.get("attempts", 1)) - 1 for row in rows), len(rows))
    return manifest_path


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the benchmark generator."""
    parser = argparse.ArgumentParser(
        description="Generate a balanced dataset of MPVRP-CC instances with numeric IDs only."
    )
    parser.add_argument("--count", type=int, default=100, help="Number of instances to generate.")
    parser.add_argument("--start-id", type=int, default=1, help="First numeric instance ID.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=CHANGEOVER_INSTANCES_DIR,
        help="Output directory for generated .dat files.",
    )
    parser.add_argument("--manifest", default="manifest.csv", help="Manifest CSV filename written in output-dir.")
    parser.add_argument("--seed", type=int, default=20260507, help="Dataset seed.")
    parser.add_argument("--grid", type=int, default=100, help="Integer coordinate grid size.")
    parser.add_argument(
        "--min-products",
        type=int,
        default=2,
        help="Minimum number of products (at least 2 for a changeover benchmark).",
    )
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
    parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
    return parser.parse_args()


def main() -> int:
    """Run the benchmark dataset generation CLI."""
    args = parse_args()
    configure_run_logging("generate_benchmark", verbose=args.verbose, quiet=args.quiet, log_dir=args.log_dir)

    if args.count < 1:
        LOGGER.error("--count must be at least 1.")
        return 1
    if args.start_id < 0:
        LOGGER.error("--start-id must be non-negative.")
        return 1
    if args.min_products < 2 or args.max_products < args.min_products:
        LOGGER.error("Product bounds must satisfy 2 <= min-products <= max-products.")
        return 1
    if not 0 < args.min_demand_probability <= args.max_demand_probability <= 1:
        LOGGER.error("Demand probability bounds must satisfy 0 < min <= max <= 1.")
        return 1

    try:
        generate_dataset(args)
    except (FileExistsError, ValueError) as exc:
        LOGGER.error("{}", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
