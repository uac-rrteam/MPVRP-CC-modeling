from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from mpvrp_cc.paths import PROJECT_ROOT, REEVALUATED_CHANGEOVER_SOLUTIONS_DIR


WITH_SOLUTIONS_DIR = PROJECT_ROOT / "data" / "solutions" / "with_changeover_costs"
WITHOUT_SOLUTIONS_DIR = PROJECT_ROOT / "data" / "solutions" / "without_changeover_costs"
MANIFEST_PATH = PROJECT_ROOT / "data" / "instances" / "with_changeover_costs" / "manifest.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results" / "article_figures"

COLORS = {
    "with": "#0072B2",
    "without": "#D55E00",
    "optimal": "#009E73",
    "time_limit": "#E69F00",
    "unsolved": "#999999",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _solution_name(instance_name: str) -> str:
    if not instance_name.startswith("MPVRP_"):
        raise ValueError(f"Unexpected instance filename: {instance_name}")
    return "Sol_" + instance_name.removeprefix("MPVRP_")


def _read_solution_metrics(path: Path) -> dict[str, float]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 6:
        raise ValueError(f"Solution has fewer than six metric lines: {path}")
    metrics = lines[-6:]
    return {
        "vehicles": float(metrics[0]),
        "changes": float(metrics[1]),
        "changeover_cost": float(metrics[2]),
        "distance": float(metrics[3]),
        "runtime": float(metrics[5]),
    }


def _load_data() -> tuple[list[dict[str, object]], dict[str, list[dict[str, str]]], list[str]]:
    manifest = {row["id"]: row for row in _read_csv(MANIFEST_PATH)}
    reports = {
        "with": _read_csv(WITH_SOLUTIONS_DIR / "benchmark_report.csv"),
        "without": _read_csv(WITHOUT_SOLUTIONS_DIR / "benchmark_report.csv"),
    }
    report_by_id = {scenario: {row["id"]: row for row in rows} for scenario, rows in reports.items()}

    records: list[dict[str, object]] = []
    exclusions: list[str] = []
    for instance_id in sorted(set(report_by_id["with"]) & set(report_by_id["without"])):
        with_report = report_by_id["with"][instance_id]
        without_report = report_by_id["without"][instance_id]
        instance = manifest.get(instance_id)
        if instance is None:
            exclusions.append(f"{instance_id}: missing manifest row")
            continue
        if with_report["status"] != "SOLVED" or without_report["status"] != "SOLVED":
            exclusions.append(f"{instance_id}: at least one scenario is unsolved")
            continue

        name = _solution_name(instance["file"])
        paths = {
            "with": WITH_SOLUTIONS_DIR / name,
            "without": WITHOUT_SOLUTIONS_DIR / name,
            "reevaluated": REEVALUATED_CHANGEOVER_SOLUTIONS_DIR / name,
        }
        missing = [label for label, path in paths.items() if not path.is_file()]
        if missing:
            exclusions.append(f"{instance_id}: missing {', '.join(missing)} solution file(s)")
            continue

        with_metrics = _read_solution_metrics(paths["with"])
        without_metrics = _read_solution_metrics(paths["without"])
        reevaluated_metrics = _read_solution_metrics(paths["reevaluated"])
        cost_aware_total = with_metrics["distance"] + with_metrics["changeover_cost"]
        ignored_total = reevaluated_metrics["distance"] + reevaluated_metrics["changeover_cost"]
        records.append(
            {
                "id": instance_id,
                "file": instance["file"],
                "stations": int(instance["stations"]),
                "products": int(instance["products"]),
                "vehicles_available": int(instance["vehicles"]),
                "coordinate_strategy": instance["coordinate_strategy"],
                "with_solver_status": with_report["solver_status"],
                "without_solver_status": without_report["solver_status"],
                "with_distance": with_metrics["distance"],
                "without_distance": without_metrics["distance"],
                "with_changeover_cost": with_metrics["changeover_cost"],
                "ignored_changeover_cost": reevaluated_metrics["changeover_cost"],
                "with_changes": with_metrics["changes"],
                "ignored_changes": reevaluated_metrics["changes"],
                "with_vehicles": with_metrics["vehicles"],
                "without_vehicles": without_metrics["vehicles"],
                "with_runtime": with_metrics["runtime"],
                "without_runtime": without_metrics["runtime"],
                "cost_aware_total": cost_aware_total,
                "ignored_total": ignored_total,
                "distance_increase": with_metrics["distance"] - without_metrics["distance"],
                "changeover_saving": reevaluated_metrics["changeover_cost"] - with_metrics["changeover_cost"],
                "net_saving": ignored_total - cost_aware_total,
                "net_saving_percent": 100.0 * (ignored_total - cost_aware_total) / ignored_total,
                "change_reduction": reevaluated_metrics["changes"] - with_metrics["changes"],
            }
        )
    return records, reports, exclusions


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linewidth": 0.6,
        }
    )


def _save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf")
    fig.savefig(output_dir / f"{stem}.png")
    plt.close(fig)


def _paired_total_cost(records: list[dict[str, object]], output_dir: Path) -> None:
    ignored = np.array([float(row["ignored_total"]) for row in records])
    aware = np.array([float(row["cost_aware_total"]) for row in records])
    products = np.array([int(row["products"]) for row in records])

    fig, ax = plt.subplots(figsize=(5.4, 4.5))
    scatter = ax.scatter(ignored, aware, c=products, cmap="viridis", s=28, alpha=0.8, edgecolors="none")
    lower = min(ignored.min(), aware.min()) * 0.92
    upper = max(ignored.max(), aware.max()) * 1.08
    ax.plot([lower, upper], [lower, upper], linestyle="--", color="0.35", linewidth=1, label="Equal cost")
    ax.set(xscale="log", yscale="log", xlim=(lower, upper), ylim=(lower, upper))
    ax.set_xlabel("Cost when changeover costs are ignored, evaluated ex post")
    ax.set_ylabel("Cost of the changeover-aware solution")
    ax.set_title("Paired comparison of operational cost")
    ax.legend(loc="upper left", frameon=False)
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    colorbar.set_label("Number of products")
    ax.text(0.98, 0.03, f"n = {len(records)} paired instances", transform=ax.transAxes, ha="right")
    _save(fig, output_dir, "01_paired_operational_cost")


def _tradeoff(records: list[dict[str, object]], output_dir: Path) -> None:
    distance = np.array([float(row["distance_increase"]) for row in records])
    savings = np.array([float(row["changeover_saving"]) for row in records])
    products = np.array([int(row["products"]) for row in records])

    fig, ax = plt.subplots(figsize=(5.6, 4.5))
    scatter = ax.scatter(distance, savings, c=products, cmap="viridis", s=30, alpha=0.8, edgecolors="none")
    lo = min(distance.min(), savings.min(), 0.0)
    hi = max(distance.max(), savings.max(), 0.0)
    ax.plot([lo, hi], [lo, hi], linestyle="--", color="0.3", linewidth=1, label="Break-even line")
    ax.axhline(0, color="0.65", linewidth=0.7)
    ax.axvline(0, color="0.65", linewidth=0.7)
    ax.set_xlabel("Additional distance of the changeover-aware solution")
    ax.set_ylabel("Changeover-cost saving")
    ax.set_title("Distance–changeover trade-off")
    ax.legend(frameon=False)
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    colorbar.set_label("Number of products")
    _save(fig, output_dir, "02_distance_changeover_tradeoff")


def _effects_by_products(records: list[dict[str, object]], output_dir: Path) -> None:
    product_counts = sorted({int(row["products"]) for row in records})
    savings = [[float(row["net_saving_percent"]) for row in records if row["products"] == p] for p in product_counts]
    reductions = [[float(row["change_reduction"]) for row in records if row["products"] == p] for p in product_counts]

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.7), sharex=True)
    for ax, values, ylabel, title in (
        (axes[0], savings, "Net cost saving (%)", "Economic benefit"),
        (axes[1], reductions, "Reduction in product changes", "Operational benefit"),
    ):
        boxes = ax.boxplot(values, tick_labels=product_counts, patch_artist=True, showfliers=False)
        for patch in boxes["boxes"]:
            patch.set_facecolor(COLORS["with"])
            patch.set_alpha(0.55)
        for position, group in enumerate(values, start=1):
            jitter = np.linspace(-0.12, 0.12, len(group)) if len(group) > 1 else np.array([0.0])
            ax.scatter(position + jitter, group, color="0.2", alpha=0.45, s=9, zorder=3)
        ax.axhline(0, color="0.4", linestyle="--", linewidth=0.8)
        ax.set_xlabel("Number of products")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
    fig.suptitle("Effect of explicitly modelling changeover costs", y=1.02, fontsize=11)
    fig.tight_layout()
    _save(fig, output_dir, "03_effect_by_number_of_products")


def _solver_outcomes(reports: dict[str, list[dict[str, str]]], output_dir: Path) -> None:
    labels = ["Changeover-aware", "Changeover ignored"]
    scenarios = ["with", "without"]
    categories = ["OPTIMAL", "TIME_LIMIT", "UNSOLVED"]
    display = {"OPTIMAL": "Proven optimal", "TIME_LIMIT": "Time limit (incumbent)", "UNSOLVED": "Unsolved"}
    colors = [COLORS["optimal"], COLORS["time_limit"], COLORS["unsolved"]]

    counts: dict[str, list[int]] = {category: [] for category in categories}
    for scenario in scenarios:
        outcomes = Counter(
            row["solver_status"] if row["status"] == "SOLVED" else "UNSOLVED" for row in reports[scenario]
        )
        for category in categories:
            counts[category].append(outcomes[category])

    fig, ax = plt.subplots(figsize=(5.3, 3.7))
    bottom = np.zeros(len(labels))
    for category, color in zip(categories, colors):
        values = np.array(counts[category])
        bars = ax.bar(labels, values, bottom=bottom, color=color, label=display[category], width=0.58)
        for bar, value, base in zip(bars, values, bottom):
            if value:
                ax.text(bar.get_x() + bar.get_width() / 2, base + value / 2, str(value), ha="center", va="center", fontsize=8)
        bottom += values
    ax.set_ylabel("Number of benchmark instances")
    ax.set_title("Solver outcomes under the time limit")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    fig.subplots_adjust(bottom=0.25)
    _save(fig, output_dir, "04_solver_outcomes")


def _runtime_scaling(records: list[dict[str, object]], output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.7), sharex=True, sharey=True)
    panels = [
        ("with_runtime", "with_solver_status", "Changeover-aware model", COLORS["with"]),
        ("without_runtime", "without_solver_status", "Changeover ignored", COLORS["without"]),
    ]
    for ax, (runtime_key, status_key, title, color) in zip(axes, panels):
        for status, marker, label in (("OPTIMAL", "o", "Proven optimal"), ("TIME_LIMIT", "x", "Time limit")):
            subset = [row for row in records if row[status_key] == status]
            ax.scatter(
                [int(row["stations"]) for row in subset],
                [max(float(row[runtime_key]), 0.01) for row in subset],
                c=color,
                marker=marker,
                alpha=0.7,
                s=24,
                label=label,
            )
        ax.set_yscale("log")
        ax.set_xlabel("Number of stations")
        ax.set_title(title)
        ax.legend(frameon=False)
    axes[0].set_ylabel("Runtime (seconds, logarithmic scale)")
    fig.suptitle("Computational effort and instance size", y=1.02, fontsize=11)
    fig.tight_layout()
    _save(fig, output_dir, "05_runtime_scaling")


def _write_paired_csv(records: list[dict[str, object]], output_dir: Path) -> None:
    path = output_dir / "paired_results.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _write_summary(
    records: list[dict[str, object]],
    reports: dict[str, list[dict[str, str]]],
    exclusions: list[str],
    output_dir: Path,
) -> None:
    net = [float(row["net_saving_percent"]) for row in records]
    changes = [float(row["change_reduction"]) for row in records]
    better = sum(float(row["net_saving"]) > 0 for row in records)
    both_optimal = sum(
        row["with_solver_status"] == "OPTIMAL" and row["without_solver_status"] == "OPTIMAL" for row in records
    )
    lines = [
        "MPVRP-CC article figure summary",
        "================================",
        f"Paired instances included: {len(records)}",
        f"Excluded instances: {len(exclusions)}",
        f"Pairs proven optimal in both scenarios: {both_optimal}",
        f"Pairs where the changeover-aware incumbent has lower evaluated cost: {better}/{len(records)}",
        f"Median net cost saving: {median(net):.2f}%",
        f"Median reduction in product changes: {median(changes):.2f}",
        "",
        "Solver outcomes:",
    ]
    for scenario, label in (("with", "Changeover-aware"), ("without", "Changeover ignored")):
        counts = Counter(
            row["solver_status"] if row["status"] == "SOLVED" else "UNSOLVED" for row in reports[scenario]
        )
        lines.append(
            f"- {label}: {counts['OPTIMAL']} optimal, {counts['TIME_LIMIT']} time-limit incumbents, "
            f"{counts['UNSOLVED']} unsolved"
        )
    lines.extend(
        [
            "",
            "Interpretation warning:",
            "Most paired observations are time-limit incumbents. Cost differences must not be described as",
            "optimality improvements unless both runs for an instance are proven optimal.",
            "Operational cost in these figures is reported distance plus reported changeover cost.",
            "",
            "Exclusions:",
            *[f"- {reason}" for reason in exclusions],
        ]
    )
    (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate publication-ready figures for the MPVRP-CC experiments.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records, reports, exclusions = _load_data()
    if not records:
        raise SystemExit("No complete paired solutions were found. Run both benchmarks and the reevaluation first.")

    _configure_style()
    _paired_total_cost(records, output_dir)
    _tradeoff(records, output_dir)
    _effects_by_products(records, output_dir)
    _solver_outcomes(reports, output_dir)
    _runtime_scaling(records, output_dir)
    _write_paired_csv(records, output_dir)
    _write_summary(records, reports, exclusions, output_dir)
    print(f"Generated 5 figures in PDF and PNG format in {output_dir}")
    print(f"Paired instances included: {len(records)}; excluded: {len(exclusions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
