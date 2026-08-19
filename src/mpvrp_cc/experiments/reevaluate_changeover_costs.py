from __future__ import annotations

import argparse
import re
from pathlib import Path

from mpvrp_cc.io.instance_solution_io import MPVRPInstance
from mpvrp_cc.paths import (
    REEVALUATED_CHANGEOVER_SOLUTIONS_DIR,
    WITH_CHANGEOVER_INSTANCES_DIR,
)


SOLUTION_FILENAME_RE = re.compile(r"^Sol_(?P<suffix>.+\.dat)$")
PRODUCT_TOKEN_RE = re.compile(r"(?P<product>\d+)\((?P<cost>[-+]?\d+(?:\.\d+)?)\)")


def infer_instance_path(solution_path: Path, instances_dir: Path) -> Path:
    """Find the original-cost instance paired with a solution filename."""
    match = SOLUTION_FILENAME_RE.match(solution_path.name)
    if not match:
        raise ValueError(f"Unexpected solution filename: {solution_path.name}")
    instance_path = instances_dir / f"MPVRP_{match.group('suffix')}"
    if not instance_path.exists():
        raise FileNotFoundError(f"Paired original-cost instance not found: {instance_path}")
    return instance_path


def _reevaluate_product_line(
    line: str,
    instance: MPVRPInstance,
    expected_initial_product: int,
    trip_start_positions: set[int],
) -> tuple[str, int, float]:
    """Replace displayed cumulative costs while preserving the product sequence."""
    prefix, separator, sequence = line.partition(":")
    if not separator or not prefix.strip().isdigit():
        raise ValueError(f"Invalid product line: {line}")

    matches = list(PRODUCT_TOKEN_RE.finditer(sequence))
    if not matches:
        raise ValueError(f"Product line contains no product token: {line}")

    products = [int(match.group("product")) for match in matches]
    if products[0] != expected_initial_product:
        raise ValueError(
            f"Vehicle {prefix.strip()} starts with product {products[0]}, "
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

    cost_iterator = iter(replacement_costs)

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('product')}({next(cost_iterator):.2f})"

    return PRODUCT_TOKEN_RE.sub(replace, line), number_of_changes, cumulative_cost


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
    product_line_count = 0
    previous_visit_line: str | None = None

    for index in range(metrics_start):
        line = lines[index]
        prefix, separator, sequence = line.partition(":")
        if not separator or not prefix.strip().isdigit():
            continue
        # Visit lines contain loads in square brackets. Product lines do not.
        if "[" in sequence:
            previous_visit_line = line
            continue

        vehicle_id = int(prefix.strip())
        if vehicle_id not in vehicles:
            raise ValueError(f"Unknown vehicle {vehicle_id} in solution.")
        if previous_visit_line is None:
            raise ValueError(f"Missing visit line before product line for vehicle {vehicle_id}.")
        visit_parts = previous_visit_line.partition(":")[2].split(" - ")
        trip_start_positions = {
            position for position, part in enumerate(visit_parts) if "[" in part
        }
        updated_line, changes, cost = _reevaluate_product_line(
            line,
            instance,
            vehicles[vehicle_id].init_prod - 1,
            trip_start_positions,
        )
        lines[index] = updated_line
        total_changes += changes
        total_cost += cost
        product_line_count += 1
        previous_visit_line = None

    if product_line_count == 0:
        raise ValueError("No vehicle product line was found in the solution.")

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
    instance_path = instance_path or infer_instance_path(solution_path, WITH_CHANGEOVER_INSTANCES_DIR)
    instance = MPVRPInstance.read(instance_path)
    updated_text, changes, cost = reevaluate_solution_text(
        solution_path.read_text(encoding="utf-8"),
        instance,
    )

    output_path = output_path or REEVALUATED_CHANGEOVER_SOLUTIONS_DIR / solution_path.name
    if output_path.resolve() == solution_path.resolve():
        raise ValueError("The output must differ from the source solution; the source is intentionally preserved.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(updated_text, encoding="utf-8")
    return output_path, changes, cost


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reprice a fixed zero-changeover solution using its paired original cost matrix."
    )
    parser.add_argument("solution", type=Path, help="Zero-changeover solution file to reprice.")
    parser.add_argument("--instance", type=Path, help="Original-cost instance; inferred from the filename by default.")
    parser.add_argument("--output", type=Path, help="Output copy; a dedicated subdirectory is used by default.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output, changes, cost = reevaluate_solution_file(args.solution, args.instance, args.output)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Repriced copy: {output}")
    print(f"Product changes: {changes}")
    print(f"Total changeover cost: {cost:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
