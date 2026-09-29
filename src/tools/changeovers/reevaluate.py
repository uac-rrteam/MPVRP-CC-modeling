from __future__ import annotations

import argparse
import re
from pathlib import Path
from loguru import logger

from mpvrp.models import MPVRPInstance
from paths import (
    CHANGEOVER_INSTANCES_DIR,
    REPRICED_SOLUTIONS_DIR,
)
from tools.run_logging import configure_run_logging


SOLUTION_FILENAME_RE = re.compile(r"^Sol_(?P<suffix>.+\.dat)$")
PRODUCT_TOKEN_RE = re.compile(r"(?P<product>\d+)\((?P<cost>[-+]?\d+(?:\.\d+)?)\)")
VISIT_RE = re.compile(r"(?P<id>\d+)(?: (?P<load>\[\d+(?:\.\d+)?\]|\(\d+(?:\.\d+)?\)))?")


def infer_instance_path(solution_path: Path, instances_dir: Path) -> Path:
    """Find the original-cost instance paired with a solution filename."""
    match = SOLUTION_FILENAME_RE.match(solution_path.name)
    if not match:
        raise ValueError(f"Unexpected solution filename: {solution_path.name}")
    instance_path = instances_dir / f"MPVRP_{match.group('suffix')}"
    if not instance_path.exists():
        raise FileNotFoundError(f"Paired original-cost instance not found: {instance_path}")
    return instance_path


def _parse_schedule_line(line: str, label: str) -> tuple[int, list[str]]:
    prefix, separator, sequence = line.partition(":")
    if not separator or not prefix.strip().isdigit():
        raise ValueError(f"Invalid {label} line: {line}")
    tokens = sequence.strip().split(" - ")
    if not tokens or any(not token for token in tokens):
        raise ValueError(f"Empty token in {label} line: {line}")
    return int(prefix.strip()), tokens


def _reevaluate_product_line(
    line: str,
    products: list[int],
    instance: MPVRPInstance,
    expected_initial_product: int,
    trip_start_positions: set[int],
) -> tuple[str, int, float]:
    """Replace cumulative costs after the schedule has been validated."""
    if products[0] != expected_initial_product:
        raise ValueError(
            f"Product line starts with product {products[0]}, "
            f"but the paired instance specifies {expected_initial_product}."
        )
    if any(product < 0 or product >= instance.n_prods for product in products):
        raise ValueError(f"Product outside the instance range in line: {line}")

    cumulative_cost = 0.0
    number_of_changes = 0
    previous_product = products[0]
    replacement_costs = [0.0]
    for position, product in enumerate(products[1:], start=1):
        if position in trip_start_positions:
            cumulative_cost += instance.changeover_cost[previous_product][product]
            if product != previous_product:
                number_of_changes += 1
        replacement_costs.append(cumulative_cost)
        previous_product = product

    vehicle_id, _ = _parse_schedule_line(line, "product")
    formatted = " - ".join(
        f"{product}({cost:.2f})" for product, cost in zip(products, replacement_costs)
    )
    return f"{vehicle_id}: {formatted}", number_of_changes, cumulative_cost


def reevaluate_solution_text(solution_text: str, instance: MPVRPInstance) -> tuple[str, int, float]:
    """Reprice a fixed solution with the instance's original changeover matrix."""
    had_trailing_newline = solution_text.endswith("\n")
    lines = solution_text.splitlines()
    if len(lines) < 6:
        raise ValueError("A solution must end with the six documented metric lines.")

    metrics_start = len(lines) - 6
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    total_changes = 0
    total_cost = 0.0
    seen_vehicles: set[int] = set()
    index = 0
    while index < metrics_start:
        if not lines[index].strip():
            index += 1
            continue
        if index + 1 >= metrics_start:
            raise ValueError("A vehicle visit line has no matching product line.")
        vehicle_id, visit_tokens = _parse_schedule_line(lines[index], "visit")
        product_id, product_tokens = _parse_schedule_line(lines[index + 1], "product")
        if vehicle_id != product_id:
            raise ValueError(f"Visit vehicle {vehicle_id} does not match product vehicle {product_id}.")
        if vehicle_id in seen_vehicles:
            raise ValueError(f"Duplicate vehicle {vehicle_id} in solution.")
        if vehicle_id not in vehicles:
            raise ValueError(f"Unknown vehicle {vehicle_id} in solution.")
        seen_vehicles.add(vehicle_id)
        if len(visit_tokens) < 4 or len(product_tokens) != len(visit_tokens) - 1:
            raise ValueError(f"Vehicle {vehicle_id} has mismatched visit and product token counts.")
        visits = [VISIT_RE.fullmatch(token) for token in visit_tokens]
        products = [PRODUCT_TOKEN_RE.fullmatch(token) for token in product_tokens]
        if any(match is None for match in visits) or any(match is None for match in products):
            raise ValueError(f"Vehicle {vehicle_id} has an invalid visit or product token.")
        home_garage = vehicles[vehicle_id].start_g.id
        if visits[0].group("load") is not None or visits[-1].group("load") is not None:
            raise ValueError(f"Vehicle {vehicle_id} must start and end at a garage.")
        if int(visits[0].group("id")) != home_garage or int(visits[-1].group("id")) != home_garage:
            raise ValueError(f"Vehicle {vehicle_id} does not return to its home garage.")
        trip_start_positions = set()
        trip_has_delivery = False
        depot_ids = {depot.id for depot in instance.depots}
        station_ids = {station.id for station in instance.stations}
        for position, visit in enumerate(visits[1:-1], start=1):
            annotation = visit.group("load")
            if annotation is None:
                raise ValueError(f"Vehicle {vehicle_id} has an untyped intermediate visit.")
            if annotation.startswith("["):
                if int(visit.group("id")) not in depot_ids or float(annotation[1:-1]) <= 0:
                    raise ValueError(f"Vehicle {vehicle_id} has an invalid depot load.")
                if position > 1 and not trip_has_delivery:
                    raise ValueError(f"Vehicle {vehicle_id} has a trip without a delivery.")
                trip_start_positions.add(position)
                trip_has_delivery = False
            else:
                if int(visit.group("id")) not in station_ids or float(annotation[1:-1]) <= 0:
                    raise ValueError(f"Vehicle {vehicle_id} has an invalid station delivery.")
                if not trip_start_positions:
                    raise ValueError(f"Vehicle {vehicle_id} delivers before loading.")
                trip_has_delivery = True
        if not trip_has_delivery:
            raise ValueError(f"Vehicle {vehicle_id} has a trip without a delivery.")
        product_ids = [int(match.group("product")) for match in products]
        for position in range(1, len(product_ids)):
            if position not in trip_start_positions and product_ids[position] != product_ids[position - 1]:
                raise ValueError(f"Vehicle {vehicle_id} changes product without loading.")
        updated_line, changes, cost = _reevaluate_product_line(
            lines[index + 1],
            product_ids,
            instance,
            vehicles[vehicle_id].init_prod - 1,
            trip_start_positions,
        )
        lines[index + 1] = updated_line
        total_changes += changes
        total_cost += cost
        index += 2

    if not seen_vehicles:
        raise ValueError("No vehicle product line was found in the solution.")
    if int(lines[metrics_start]) != len(seen_vehicles):
        raise ValueError("The vehicle count metric does not match the schedules.")

    # Metrics 2 and 3 are respectively the number and total cost of changes.
    lines[metrics_start + 1] = str(total_changes)
    lines[metrics_start + 2] = f"{total_cost:.2f}"

    result = "\n".join(lines)
    if had_trailing_newline:
        result += "\n"
    return result, total_changes, total_cost


def reevaluate_solution_file(
    solution_path: Path,
    instance_path: Path | None = None,
    output_path: Path | None = None,
) -> tuple[Path, int, float]:
    """Write a repriced copy of a zero-changeover solution."""
    if not solution_path.is_file():
        raise FileNotFoundError(f"Solution not found: {solution_path}")
    instance_path = instance_path or infer_instance_path(solution_path, CHANGEOVER_INSTANCES_DIR)
    instance = MPVRPInstance.read(instance_path)
    updated_text, changes, cost = reevaluate_solution_text(
        solution_path.read_text(encoding="utf-8"),
        instance,
    )

    output_path = output_path or REPRICED_SOLUTIONS_DIR / solution_path.name
    if output_path.resolve() == solution_path.resolve():
        raise ValueError("The output must differ from the source solution; the source is intentionally preserved.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(updated_text, encoding="utf-8")
    logger.info("Repriced {} using {}", solution_path, instance_path)
    return output_path, changes, cost


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reprice a fixed zero-changeover solution using its paired original cost matrix."
    )
    parser.add_argument("solution", type=Path, help="Zero-changeover solution file to reprice.")
    parser.add_argument("--instance", type=Path, help="Original-cost instance; inferred from the filename by default.")
    parser.add_argument("--output", type=Path, help="Output copy; a dedicated subdirectory is used by default.")
    parser.add_argument("--log-dir", type=Path, help="Directory for the per-run .log file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_run_logging("reevaluate_changeovers", log_dir=args.log_dir)
    try:
        output, changes, cost = reevaluate_solution_file(args.solution, args.instance, args.output)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("{}", exc)
        return 1
    logger.info("Repriced copy: {}", output)
    logger.info("Product changes: {}", changes)
    logger.info("Total changeover cost: {:.2f}", cost)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
