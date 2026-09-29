"""Plot benchmark locations and, optionally, their saved vehicle schedules."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap

from mpvrp.io.instance import read_instance
from mpvrp.models import MPVRPInstance
from paths import (
    CHANGEOVER_INSTANCES_DIR,
    RESULTS_DIR,
    ZERO_CHANGEOVER_INSTANCES_DIR,
    SOLUTIONS_DIR,
)

SCENARIOS = {
    "1": (CHANGEOVER_INSTANCES_DIR, "in"),
    "2": (ZERO_CHANGEOVER_INSTANCES_DIR, "out"),
}
VISIT_RE = re.compile(r"^(?P<id>\d+)(?:\s*(?P<load>\[[^]]+\]|\([^)]*\)))?$")


def find_instance(instances_dir: Path, instance_number: str) -> Path:
    """Resolve a numeric benchmark ID without relying on its dimensions."""
    if not instance_number.isdigit() or int(instance_number) < 1:
        raise ValueError("--inst must be a positive instance number.")
    instance_id = f"{int(instance_number):03d}"
    matches = sorted(instances_dir.glob(f"MPVRP_{instance_id}_s*_d*_p*.dat"))
    if not matches:
        raise FileNotFoundError(f"Instance {instance_id} not found in {instances_dir}")
    if len(matches) > 1:
        raise ValueError(f"Multiple files match instance {instance_id} in {instances_dir}")
    return matches[0]


def read_solution_paths(path: Path, instance: MPVRPInstance) -> dict[int, list[tuple[int, int]]]:
    """Return vehicle paths as coordinates, resolving IDs by stop notation."""
    if not path.exists():
        raise FileNotFoundError(f"Solution not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 6:
        raise ValueError(f"Incomplete solution: {path}")
    schedule = lines[:-6]
    depots = {node.id: node for node in instance.depots}
    stations = {node.id: node for node in instance.stations}
    vehicles = {vehicle.id: vehicle for vehicle in instance.vehicles}
    paths: dict[int, list[tuple[int, int]]] = {}
    entries = [line for line in schedule if line.strip()]
    if len(entries) % 2:
        raise ValueError(f"Unpaired schedule line in {path}")
    for route_line, product_line in zip(entries[::2], entries[1::2]):
        prefix, separator, route = route_line.partition(":")
        product_prefix, product_separator, _ = product_line.partition(":")
        if not separator or not product_separator or not prefix.strip().isdigit():
            raise ValueError(f"Invalid vehicle schedule in {path}")
        vehicle_id = int(prefix.strip())
        if product_prefix.strip() != prefix.strip() or vehicle_id not in vehicles:
            raise ValueError(f"Invalid vehicle ID in {path}: {prefix.strip()}")
        if vehicle_id in paths:
            raise ValueError(f"Duplicate vehicle {vehicle_id} in {path}")
        tokens = [VISIT_RE.fullmatch(token.strip()) for token in route.split(" - ")]
        if len(tokens) < 4 or any(token is None for token in tokens):
            raise ValueError(f"Invalid route for vehicle {vehicle_id} in {path}")
        if len(product_line.partition(":")[2].strip().split(" - ")) != len(tokens) - 1:
            raise ValueError(f"Mismatched route and product entries for vehicle {vehicle_id} in {path}")
        garage = vehicles[vehicle_id].start_g
        assert garage is not None
        if any(tokens[index].group("load") is not None or int(tokens[index].group("id")) != garage.id for index in (0, -1)):
            raise ValueError(f"Vehicle {vehicle_id} must start and finish at its home garage.")
        coordinates = [(garage.x, garage.y)]
        for token in tokens[1:-1]:
            node_id = int(token.group("id"))
            load = token.group("load")
            if load is None:
                raise ValueError(f"Unmarked stop {node_id} for vehicle {vehicle_id}")
            nodes = depots if load.startswith("[") else stations
            if node_id not in nodes:
                raise ValueError(f"Unknown stop {node_id} for vehicle {vehicle_id}")
            node = nodes[node_id]
            coordinates.append((node.x, node.y))
        coordinates.append((garage.x, garage.y))
        paths[vehicle_id] = coordinates
    return paths


def plot_instance(
    instance: MPVRPInstance,
    output: Path,
    routes: dict[int, list[tuple[int, int]]] | None = None,
    background: str = "landscape",
    method: str | None = None,
) -> Path:
    """Save a map of locations and optional vehicle routes."""
    fig, ax = plt.subplots(figsize=(11, 8))
    try:
        if background == "landscape":
            _plot_landscape(ax, instance)
        elif background != "plain":
            raise ValueError(f"Unknown background: {background}")
        if routes:
            colors = plt.get_cmap("tab20")
            for index, (vehicle_id, coordinates) in enumerate(sorted(routes.items())):
                color = colors(index % 20)
                xs, ys = zip(*coordinates)
                ax.plot(xs, ys, color=color, alpha=0.75, linewidth=1.7, label=f"Vehicle {vehicle_id}", zorder=1)
                for start, end in zip(coordinates, coordinates[1:]):
                    if start != end:
                        ax.annotate("", xy=(start[0] + 0.62 * (end[0] - start[0]), start[1] + 0.62 * (end[1] - start[1])), xytext=(start[0] + 0.42 * (end[0] - start[0]), start[1] + 0.42 * (end[1] - start[1])), arrowprops={"arrowstyle": "->", "color": color, "lw": 1.2}, zorder=2)
        _plot_locations(ax, instance)
        title = f"MPVRP-CC instance {instance.instance_id}"
        if routes is not None:
            title += f" — {method.upper()} solution" if method else " — solution"
        ax.set(title=title, xlabel="X", ylabel="Y")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(alpha=0.25, color="#5c665b")
        ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize="small")
        fig.tight_layout()
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=160, bbox_inches="tight")
        return output
    finally:
        plt.close(fig)


def _plot_landscape(ax: Axes, instance: MPVRPInstance) -> None:
    """Draw a light, synthetic terrain texture behind the coordinate plot."""
    locations = [*instance.garages, *instance.depots, *instance.stations]
    xs = [node.x for node in locations]
    ys = [node.y for node in locations]
    padding = max(max(xs) - min(xs), max(ys) - min(ys), 10) * 0.06
    bounds = (min(xs) - padding, max(xs) + padding, min(ys) - padding, max(ys) + padding)
    x = np.linspace(bounds[0], bounds[1], 300)
    y = np.linspace(bounds[2], bounds[3], 300)
    xx, yy = np.meshgrid(x, y)
    xn = (xx - bounds[0]) / (bounds[1] - bounds[0])
    yn = (yy - bounds[2]) / (bounds[3] - bounds[2])
    terrain = (
        0.52
        + 0.18 * np.sin(2.2 * np.pi * xn + 0.8 * np.sin(2.4 * np.pi * yn))
        + 0.12 * np.cos(2.5 * np.pi * yn - 1.3 * np.pi * xn)
        + 0.06 * np.sin(7 * np.pi * (xn + yn))
    )
    palette = LinearSegmentedColormap.from_list(
        "soft_landscape", ["#d8e8d0", "#edf1d7", "#f4ecd6", "#e6dcc8"]
    )
    ax.imshow(terrain, extent=bounds, origin="lower", cmap=palette, vmin=0, vmax=1, alpha=0.9, zorder=0)
    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])


def _plot_locations(ax: Axes, instance: MPVRPInstance) -> None:
    for nodes, marker, color, label, prefix in (
        (instance.garages, "s", "#1f77b4", "Garages", "G"),
        (instance.depots, "^", "#d62728", "Depots", "D"),
        (instance.stations, "o", "#444444", "Stations", "S"),
    ):
        if not nodes:
            continue
        ax.scatter([node.x for node in nodes], [node.y for node in nodes], s=75 if prefix != "S" else 30, marker=marker, color=color, edgecolors="white", linewidths=0.5, label=label, zorder=3)
        for node in nodes:
            ax.annotate(f"{prefix}{node.id}", (node.x, node.y), xytext=(4, 4), textcoords="offset points", fontsize=7, color=color, zorder=4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot a benchmark instance and optionally its saved solution.")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), required=True, help="1: changeover costs; 2: zero changeover costs.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--inst", help="Instance number (e.g. 01) or 'all'.")
    selection.add_argument("--all", action="store_true", help="Plot all instances for this configuration.")
    parser.add_argument("--solution", action="store_true", help="Overlay vehicle routes from the matching solution file.")
    parser.add_argument("--method", choices=("milp", "cp"), default="milp", help="Solution method (default: milp).")
    parser.add_argument("--background", choices=("landscape", "plain"), default="landscape", help="Plot background (default: landscape).")
    parser.add_argument("--output", type=Path, help="Output PNG path, or output directory with --all/--inst all.")
    args = parser.parse_args()
    try:
        instances_dir, scenario_dir = SCENARIOS[args.scenario]
        solutions_dir = SOLUTIONS_DIR / args.method / scenario_dir
        all_instances = args.all or args.inst == "all"
        instance_paths = sorted(instances_dir.glob("MPVRP_*.dat")) if all_instances else [find_instance(instances_dir, args.inst)]
        if not instance_paths:
            raise FileNotFoundError(f"No instances found in {instances_dir}")
        output_dir = args.output or RESULTS_DIR / "plots" / f"scenario_{args.scenario}"
        created = 0
        skipped = 0
        for instance_path in instance_paths:
            instance = read_instance(instance_path)
            routes = None
            if args.solution:
                solution_path = solutions_dir / instance_path.name.replace("MPVRP_", "Sol_", 1)
                if all_instances and not solution_path.exists():
                    print(f"Skipping {instance.instance_id}: solution not found in {solutions_dir}")
                    skipped += 1
                    continue
                routes = read_solution_paths(solution_path, instance)
            suffix = f"_{args.method}_solution" if args.solution else ""
            filename = f"instance_{instance.instance_id}{suffix}_{args.background}.png"
            output = output_dir / filename if all_instances or args.output is None else args.output
            print(plot_instance(instance, output, routes, args.background, args.method))
            created += 1
        if all_instances:
            print(f"Created {created} plot(s); skipped {skipped} missing solution(s).")
        if created == 0:
            raise ValueError("No plots were created.")
    except (FileNotFoundError, ValueError, OSError) as exc:
        parser.exit(1, f"mpvrp-plot: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
