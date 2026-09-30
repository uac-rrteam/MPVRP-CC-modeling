from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from loguru import logger

from paths import CHANGEOVER_INSTANCES_DIR, ZERO_CHANGEOVER_INSTANCES_DIR
from tools.run_logging import configure_run_logging


def zero_changeover_costs(source: Path, destination: Path, force: bool = False) -> Path:
    """Copy an instance while replacing only its changeover-cost matrix by zeros."""
    if destination.exists() and not force:
        raise FileExistsError(f"Destination already exists: {destination}")

    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"Invalid instance file: {source}")

    try:
        product_count = int(lines[1].split()[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Cannot read the product count from {source}") from exc

    matrix_start = 2
    matrix_end = matrix_start + product_count
    if len(lines) < matrix_end:
        raise ValueError(f"Incomplete changeover-cost matrix in {source}")

    newline = "\r\n" if lines[1].endswith("\r\n") else "\n"
    zero_row = "\t".join("0" for _ in range(product_count)) + newline
    paired_lines = lines[:matrix_start] + [zero_row] * product_count + lines[matrix_end:]

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(paired_lines), encoding="utf-8", newline="")
    return destination


def create_paired_dataset(
    source_dir: Path = CHANGEOVER_INSTANCES_DIR,
    destination_dir: Path = ZERO_CHANGEOVER_INSTANCES_DIR,
    force: bool = False,
) -> int:
    """Create a zero-changeover counterpart for every benchmark instance."""
    source_files = sorted(source_dir.glob("MPVRP_*.dat"))
    if not source_files:
        raise FileNotFoundError(f"No benchmark instances found in {source_dir}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in source_files:
        zero_changeover_costs(source, destination_dir / source.name, force=force)
        logger.debug("Paired {}", source.name)

    manifest = source_dir / "manifest.csv"
    if manifest.exists():
        target_manifest = destination_dir / manifest.name
        if target_manifest.exists() and not force:
            raise FileExistsError(f"Destination already exists: {target_manifest}")
        shutil.copy2(manifest, target_manifest)

    return len(source_files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create paired MPVRP-CC instances whose changeover costs are all zero."
    )
    parser.add_argument("--source-dir", type=Path, default=CHANGEOVER_INSTANCES_DIR)
    parser.add_argument("--destination-dir", type=Path, default=ZERO_CHANGEOVER_INSTANCES_DIR)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing paired dataset.")
    parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_run_logging("prepare_scenarios", log_dir=args.log_dir)
    try:
        count = create_paired_dataset(args.source_dir, args.destination_dir, args.force)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        logger.error("{}", exc)
        return 1
    logger.info("Created {} paired instances in {}", count, args.destination_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
