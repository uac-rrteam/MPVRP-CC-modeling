from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common.paths import LP2_SOLUTIONS_DIR, PROJECT_ROOT, WITH_CHANGEOVER_INSTANCES_DIR


TIME_LIMIT = 300.0
DIRECT_COLOR = "#0072B2"
REEVALUATED_COLOR = "#D55E00"
STATUS_SOLVED_COLOR = "#009E73"
STATUS_UNSOLVED_COLOR = "#CC79A7"
PRODUCT_COLORS = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7"]
SOLUTION_RE = re.compile(
    r"^Sol_(?P<id>\d+)_s(?P<stations>\d+)_d(?P<depots>\d+)_p(?P<products>\d+)\.dat$"
)


@dataclass(frozen=True)
class SolutionMetrics:
    instance_id: str
    stations: int
    products: int
    vehicles_used: int
    changes: int
    changeover_cost: float
    distance: float
    runtime: float

    @property
    def objective(self) -> float:
        return self.changeover_cost + self.distance


def read_solution_metrics(path: Path) -> SolutionMetrics:
    match = SOLUTION_RE.match(path.name)
    if match is None:
        raise ValueError(f"Unexpected solution filename: {path.name}")
    metrics = path.read_text(encoding="utf-8").splitlines()[-6:]
    if len(metrics) != 6:
        raise ValueError(f"Incomplete solution metrics: {path}")
    return SolutionMetrics(
        instance_id=match.group("id"),
        stations=int(match.group("stations")),
        products=int(match.group("products")),
        vehicles_used=int(metrics[0]),
        changes=int(metrics[1]),
        changeover_cost=float(metrics[2]),
        distance=float(metrics[3]),
        runtime=float(metrics[5]),
    )


def load_solution_directory(directory: Path) -> dict[str, SolutionMetrics]:
    return {
        metrics.instance_id: metrics
        for path in sorted(directory.glob("Sol_*.dat"))
        for metrics in [read_solution_metrics(path)]
    }


def manifest_ids(manifest: Path) -> list[str]:
    with manifest.open(newline="", encoding="utf-8") as handle:
        return [row["id"] for row in csv.DictReader(handle)]


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linewidth": 0.6,
        }
    )


def save_figure(figure: plt.Figure, output_dir: Path, stem: str) -> None:
    figure.savefig(output_dir / f"{stem}.png", bbox_inches="tight")
    figure.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(figure)


def log_linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Fit log10(y) = intercept + slope*x and return a 95% mean CI."""
    if len(x) < 3 or len(np.unique(x)) < 2 or np.any(y <= 0):
        raise ValueError("A log-linear fit requires positive values and at least two x values.")
    design = np.column_stack((np.ones(len(x)), x))
    coefficients, _, _, _ = np.linalg.lstsq(design, np.log10(y), rcond=None)
    fitted = design @ coefficients
    residuals = np.log10(y) - fitted
    degrees_of_freedom = max(len(x) - 2, 1)
    residual_variance = float(residuals @ residuals) / degrees_of_freedom
    covariance = np.linalg.pinv(design.T @ design)

    grid = np.linspace(float(np.min(x)), float(np.max(x)), 160)
    grid_design = np.column_stack((np.ones(len(grid)), grid))
    prediction = grid_design @ coefficients
    standard_error = np.sqrt(
        np.maximum(0.0, residual_variance * np.einsum("ij,jk,ik->i", grid_design, covariance, grid_design))
    )
    total_variation = float(np.sum((np.log10(y) - np.mean(np.log10(y))) ** 2))
    r_squared = 1.0 - float(residuals @ residuals) / total_variation if total_variation > 0 else 0.0
    return (
        grid,
        10 ** prediction,
        10 ** (prediction - 1.96 * standard_error),
        10 ** (prediction + 1.96 * standard_error),
        r_squared,
    )


def add_regression(
    axis: plt.Axes,
    x: np.ndarray,
    y: np.ndarray,
    color: str,
    label: str,
) -> None:
    grid, prediction, lower, upper, r_squared = log_linear_fit(x, y)
    axis.plot(grid, prediction, color=color, linewidth=2.0, label=f"{label} fit ($R^2$={r_squared:.2f})")
    axis.fill_between(grid, lower, upper, color=color, alpha=0.13, linewidth=0)


def plot_solution_outcomes(
    all_ids: list[str],
    direct: dict[str, SolutionMetrics],
    zero_cost: dict[str, SolutionMetrics],
    output_dir: Path,
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.25), sharex=True, sharey=True)
    scenarios = [
        ("LP2 optimized with changeover costs", direct),
        ("LP2 optimized without changeover costs", zero_cost),
    ]
    timeline = np.linspace(0.0, TIME_LIMIT, 301)
    total = len(all_ids)
    for axis, (title, solutions) in zip(axes, scenarios, strict=True):
        completion_times = np.array([min(item.runtime, TIME_LIMIT) for item in solutions.values()])
        solved = np.array([np.count_nonzero(completion_times <= second) for second in timeline])
        unresolved = total - solved
        axis.step(
            timeline,
            solved,
            where="post",
            color=STATUS_SOLVED_COLOR,
            linewidth=2,
            label="Run ended with a solution by $t$",
        )
        axis.step(
            timeline,
            unresolved,
            where="post",
            color=STATUS_UNSOLVED_COLOR,
            linewidth=2,
            label="No completed solution by $t$",
        )
        axis.axvline(TIME_LIMIT, color="0.35", linestyle="--", linewidth=0.9)
        axis.annotate(
            f"{len(solutions)} solved\n{total - len(solutions)} unsolved",
            xy=(TIME_LIMIT, len(solutions)),
            xytext=(-8, -34),
            textcoords="offset points",
            ha="right",
            va="top",
            fontsize=8,
        )
        axis.set_title(title)
        axis.set_xlabel("Elapsed solver time (seconds)")
        axis.set_xlim(0, TIME_LIMIT)
        axis.set_ylim(0, total)
    axes[0].set_ylabel("Number of benchmark instances")
    axes[0].legend(loc="center left", frameon=False)
    figure.suptitle("LP2 benchmark outcomes by recorded run time", y=1.02, fontsize=11)
    figure.tight_layout()
    save_figure(figure, output_dir, "fig1_lp2_outcomes_over_time")


def paired_arrays(
    direct: dict[str, SolutionMetrics],
    reevaluated: dict[str, SolutionMetrics],
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ids = sorted(set(direct) & set(reevaluated))
    stations = np.array([direct[item].stations for item in ids], dtype=float)
    products = np.array([direct[item].products for item in ids], dtype=float)
    direct_objective = np.array([direct[item].objective for item in ids])
    reevaluated_objective = np.array([reevaluated[item].objective for item in ids])
    return ids, stations, products, direct_objective, reevaluated_objective


def plot_objective_by_stations(
    stations: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
    output_dir: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(6.4, 4.1))
    axis.scatter(stations, direct_objective, s=25, alpha=0.58, color=DIRECT_COLOR, edgecolors="none", label="Cost-aware LP2")
    axis.scatter(
        stations,
        reevaluated_objective,
        s=25,
        alpha=0.58,
        color=REEVALUATED_COLOR,
        marker="^",
        edgecolors="none",
        label="Zero-cost LP2, reevaluated",
    )
    add_regression(axis, stations, direct_objective, DIRECT_COLOR, "Cost-aware")
    add_regression(axis, stations, reevaluated_objective, REEVALUATED_COLOR, "Reevaluated")
    axis.set_yscale("log")
    axis.set_xlabel("Number of customers (stations)")
    axis.set_ylabel("Objective value (log scale)")
    axis.set_title(f"Objective value versus customer count ({len(stations)} paired instances)")
    axis.legend(frameon=False, ncol=2)
    figure.tight_layout()
    save_figure(figure, output_dir, "fig2_objective_by_stations")


def plot_objective_by_products(
    products: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
    output_dir: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(6.4, 4.1))
    axis.scatter(products - 0.07, direct_objective, s=25, alpha=0.58, color=DIRECT_COLOR, edgecolors="none", label="Cost-aware LP2")
    axis.scatter(
        products + 0.07,
        reevaluated_objective,
        s=25,
        alpha=0.58,
        color=REEVALUATED_COLOR,
        marker="^",
        edgecolors="none",
        label="Zero-cost LP2, reevaluated",
    )
    add_regression(axis, products, direct_objective, DIRECT_COLOR, "Cost-aware")
    add_regression(axis, products, reevaluated_objective, REEVALUATED_COLOR, "Reevaluated")
    axis.set_yscale("log")
    axis.set_xticks(range(2, 7))
    axis.set_xlabel("Number of products")
    axis.set_ylabel("Objective value (log scale)")
    axis.set_title("Objective value versus product count")
    axis.legend(frameon=False, ncol=2)
    figure.tight_layout()
    save_figure(figure, output_dir, "fig3_objective_by_products")


def plot_station_facets_by_product(
    stations: np.ndarray,
    products: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
    output_dir: Path,
) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(8.2, 5.5), sharex=True, sharey=True)
    flat_axes = list(axes.flat)
    for index, product_count in enumerate(range(2, 7)):
        axis = flat_axes[index]
        selected = products == product_count
        x = stations[selected]
        y_direct = direct_objective[selected]
        y_reevaluated = reevaluated_objective[selected]
        axis.scatter(x, y_direct, s=20, alpha=0.62, color=DIRECT_COLOR, edgecolors="none")
        axis.scatter(x, y_reevaluated, s=20, alpha=0.62, color=REEVALUATED_COLOR, marker="^", edgecolors="none")
        if len(x) >= 3 and len(np.unique(x)) >= 2:
            add_regression(axis, x, y_direct, DIRECT_COLOR, "Cost-aware")
            add_regression(axis, x, y_reevaluated, REEVALUATED_COLOR, "Reevaluated")
        axis.set_yscale("log")
        axis.set_title(f"{product_count} products ($n$={len(x)})")
        axis.set_xlabel("Customers")
        if index % 3 == 0:
            axis.set_ylabel("Objective (log scale)")
    flat_axes[-1].axis("off")
    handles = [
        plt.Line2D([], [], color=DIRECT_COLOR, marker="o", linestyle="-", label="Cost-aware LP2"),
        plt.Line2D([], [], color=REEVALUATED_COLOR, marker="^", linestyle="-", label="Zero-cost LP2, reevaluated"),
    ]
    flat_axes[-1].legend(handles=handles, loc="center", frameon=False)
    figure.suptitle("Customer-count regressions stratified by number of products", fontsize=11)
    figure.tight_layout()
    save_figure(figure, output_dir, "fig4_station_regressions_by_product")


def plot_paired_objectives(
    products: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
    output_dir: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(5.2, 4.5))
    limits = [
        min(float(np.min(direct_objective)), float(np.min(reevaluated_objective))) * 0.78,
        max(float(np.max(direct_objective)), float(np.max(reevaluated_objective))) * 1.28,
    ]
    for product_count, color in zip(range(2, 7), PRODUCT_COLORS, strict=True):
        selected = products == product_count
        axis.scatter(
            direct_objective[selected],
            reevaluated_objective[selected],
            s=30,
            alpha=0.72,
            color=color,
            edgecolors="none",
            label=f"{product_count} products ($n$={np.count_nonzero(selected)})",
        )
    axis.plot(limits, limits, color="0.3", linestyle="--", linewidth=1.1, label="Equal objective")
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlim(limits)
    axis.set_ylim(limits)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Cost-aware LP2 objective")
    axis.set_ylabel("Reevaluated zero-cost LP2 objective")
    axis.set_title("Paired objective comparison")
    axis.legend(frameon=False, loc="upper left")
    figure.tight_layout()
    save_figure(figure, output_dir, "fig5_paired_objective_comparison")


def plot_objective_by_station_range(
    stations: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
    output_dir: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(7.0, 4.2))
    ranges = [(1, 10), (11, 20), (21, 30), (31, 40), (41, 50)]
    centers = np.arange(1, len(ranges) + 1, dtype=float)
    direct_groups = [direct_objective[(stations >= low) & (stations <= high)] for low, high in ranges]
    reevaluated_groups = [
        reevaluated_objective[(stations >= low) & (stations <= high)] for low, high in ranges
    ]

    for groups, positions, color in (
        (direct_groups, centers - 0.18, DIRECT_COLOR),
        (reevaluated_groups, centers + 0.18, REEVALUATED_COLOR),
    ):
        artists = axis.boxplot(
            groups,
            positions=positions,
            widths=0.28,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "black", "linewidth": 1.2},
            whiskerprops={"color": color},
            capprops={"color": color},
            boxprops={"edgecolor": color},
        )
        for box in artists["boxes"]:
            box.set_facecolor(color)
            box.set_alpha(0.28)

    for group_index, (direct_group, reevaluated_group) in enumerate(
        zip(direct_groups, reevaluated_groups, strict=True),
        start=1,
    ):
        direct_jitter = np.linspace(-0.08, 0.08, len(direct_group)) if len(direct_group) > 1 else np.zeros(1)
        reevaluated_jitter = (
            np.linspace(-0.08, 0.08, len(reevaluated_group)) if len(reevaluated_group) > 1 else np.zeros(1)
        )
        axis.scatter(
            group_index - 0.18 + direct_jitter,
            direct_group,
            s=15,
            alpha=0.48,
            color=DIRECT_COLOR,
            edgecolors="none",
        )
        axis.scatter(
            group_index + 0.18 + reevaluated_jitter,
            reevaluated_group,
            s=15,
            alpha=0.48,
            color=REEVALUATED_COLOR,
            marker="^",
            edgecolors="none",
        )

    counts = [len(group) for group in direct_groups]
    axis.set_xticks(centers, [f"{low}–{high}\n($n$={count})" for (low, high), count in zip(ranges, counts, strict=True)])
    axis.set_yscale("log")
    axis.set_xlabel("Customer-count range")
    axis.set_ylabel("Objective value (log scale)")
    axis.set_title("Objective distributions by customer-count range")
    axis.legend(
        handles=[
            plt.Line2D([], [], color=DIRECT_COLOR, marker="o", linestyle="none", label="Cost-aware LP2"),
            plt.Line2D(
                [],
                [],
                color=REEVALUATED_COLOR,
                marker="^",
                linestyle="none",
                label="Zero-cost LP2, reevaluated",
            ),
        ],
        frameon=False,
        ncol=2,
    )
    figure.tight_layout()
    save_figure(figure, output_dir, "fig6_objective_by_station_range")


def write_analysis_csv(
    output_dir: Path,
    ids: list[str],
    stations: np.ndarray,
    products: np.ndarray,
    direct_objective: np.ndarray,
    reevaluated_objective: np.ndarray,
) -> None:
    with (output_dir / "lp2_paired_objectives.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "stations",
                "products",
                "cost_aware_objective",
                "reevaluated_objective",
                "reevaluated_minus_cost_aware",
                "relative_difference_percent",
            ]
        )
        for index, instance_id in enumerate(ids):
            difference = reevaluated_objective[index] - direct_objective[index]
            writer.writerow(
                [
                    instance_id,
                    int(stations[index]),
                    int(products[index]),
                    f"{direct_objective[index]:.2f}",
                    f"{reevaluated_objective[index]:.2f}",
                    f"{difference:.2f}",
                    f"{100.0 * difference / direct_objective[index]:.4f}",
                ]
            )


def generate_figures(output_dir: Path) -> None:
    direct_dir = LP2_SOLUTIONS_DIR / "with_changeover_costs"
    zero_cost_dir = LP2_SOLUTIONS_DIR / "without_changeover_costs"
    reevaluated_dir = zero_cost_dir / "reevaluated_with_changeover_costs"
    direct = load_solution_directory(direct_dir)
    zero_cost = load_solution_directory(zero_cost_dir)
    reevaluated = load_solution_directory(reevaluated_dir)
    all_ids = manifest_ids(WITH_CHANGEOVER_INSTANCES_DIR / "manifest.csv")

    if not direct or not zero_cost or not reevaluated:
        raise ValueError("LP2 direct, zero-cost, and reevaluated solution directories must all contain solutions.")

    output_dir.mkdir(parents=True, exist_ok=True)
    _style()
    ids, stations, products, direct_objective, reevaluated_objective = paired_arrays(direct, reevaluated)
    plot_solution_outcomes(all_ids, direct, zero_cost, output_dir)
    plot_objective_by_stations(stations, direct_objective, reevaluated_objective, output_dir)
    plot_objective_by_products(products, direct_objective, reevaluated_objective, output_dir)
    plot_station_facets_by_product(stations, products, direct_objective, reevaluated_objective, output_dir)
    plot_paired_objectives(products, direct_objective, reevaluated_objective, output_dir)
    plot_objective_by_station_range(stations, direct_objective, reevaluated_objective, output_dir)
    write_analysis_csv(output_dir, ids, stations, products, direct_objective, reevaluated_objective)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create publication-ready plots for the LP2 experiments.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "article_figures" / "lp2",
        help="Directory for PNG, PDF, and analysis CSV outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        generate_figures(args.output_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"LP2 figures written to: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
