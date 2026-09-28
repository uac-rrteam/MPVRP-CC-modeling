from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import pandas as pd
import seaborn as sns

from common.paths import PROJECT_ROOT, WITH_CHANGEOVER_INSTANCES_DIR
from lp2.io.inst import read_instance


TIME_LIMIT = 300.0
OUTPUT_DIR = PROJECT_ROOT / "results" / "conference_figures" / "presentation_modele"
WITH_COSTS_DIR = PROJECT_ROOT / "data" / "solutions" / "lp2" / "with_changeover_costs"
REEVALUATED_DIR = (
    PROJECT_ROOT
    / "data"
    / "solutions"
    / "lp2"
    / "without_changeover_costs"
    / "reevaluated_with_changeover_costs"
)
REPORT_PATH = WITH_COSTS_DIR / "benchmark_report_from_048.csv"
SAMPLE_IDS = ["094", "098", "067", "058", "090", "068", "056", "064", "086", "087"]
SOLUTION_RE = re.compile(r"^Sol_(?P<id>\d+)_s\d+_d\d+_p\d+\.dat$")
ROUTE_RE = re.compile(r"^\d+:\s.*\[[-\d.]+\]")
TRIP_RE = re.compile(r"\[[-\d.]+\]")

# Palette sobre, commune aux quatre figures.
BLUE = "#4477AA"
ORANGE = "#CC8844"
GRAY = "#999999"
LIGHT_GRAY = "#E5E5E5"
DARK = "#333333"


@dataclass(frozen=True)
class SolutionMetrics:
    instance_id: str
    changes: int
    preparation_cost: float
    distance: float
    trips: int
    runtime: float


def read_solution(path: Path) -> SolutionMetrics:
    match = SOLUTION_RE.match(path.name)
    if match is None:
        raise ValueError(f"Nom de solution inattendu : {path.name}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = lines[-6:]
    trips = sum(len(TRIP_RE.findall(line)) for line in lines[:-6] if ROUTE_RE.match(line))
    if trips < int(metrics[0]):
        raise ValueError(f"Nombre de voyages incohérent : {path}")
    return SolutionMetrics(
        instance_id=match.group("id"),
        changes=int(metrics[1]),
        preparation_cost=float(metrics[2]),
        distance=float(metrics[3]),
        trips=trips,
        runtime=float(metrics[5]),
    )


def load_solutions(directory: Path) -> dict[str, SolutionMetrics]:
    return {
        solution.instance_id: solution
        for path in directory.glob("Sol_*.dat")
        for solution in [read_solution(path)]
    }


def load_run_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    solutions = load_solutions(WITH_COSTS_DIR)
    with REPORT_PATH.open(newline="", encoding="utf-8") as handle:
        report_rows = {row["id"]: row for row in csv.DictReader(handle)}

    records: list[dict[str, object]] = []
    for path in sorted(WITH_CHANGEOVER_INSTANCES_DIR.glob("MPVRP_*.dat")):
        instance_id = path.name[6:9]
        instance = read_instance(path)
        solution = solutions.get(instance_id)
        runtime = solution.runtime if solution else TIME_LIMIT
        if solution is None:
            status = "Non résolue"
        elif runtime < 299.0:
            status = "Optimale"
        else:
            status = "Résolue"
        records.append(
            {
                "instance": instance_id,
                "requêtes": instance.n_requests,
                "temps_s": min(runtime, TIME_LIMIT),
                "statut": status,
            }
        )

    by_id = {str(row["instance"]): row for row in records}
    gap_records: list[dict[str, object]] = []
    for instance_id, report in report_rows.items():
        if report["status"] == "SOLVED" and report["mip_gap_percent"]:
            gap_records.append(
                {
                    **by_id[instance_id],
                    "écart_optimalité_pct": float(report["mip_gap_percent"]),
                }
            )
    return pd.DataFrame(records), pd.DataFrame(gap_records)


def configure_style() -> None:
    sns.set_theme(context="paper", style="ticks", font="DejaVu Sans", font_scale=1.1)
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": DARK,
            "axes.labelcolor": DARK,
            "axes.labelsize": 12,
            "axes.linewidth": 0.8,
            "axes.axisbelow": True,
            "xtick.color": DARK,
            "ytick.color": DARK,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 11,
            "grid.color": LIGHT_GRAY,
            "grid.linewidth": 0.6,
            "grid.alpha": 0.55,
            "savefig.dpi": 300,
        }
    )


def save_figure(figure: plt.Figure, stem: str) -> None:
    figure.savefig(OUTPUT_DIR / f"{stem}.png", bbox_inches="tight", facecolor="white")
    figure.savefig(OUTPUT_DIR / f"{stem}.pdf", bbox_inches="tight", facecolor="white")
    figure.savefig(OUTPUT_DIR / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_status_bars(data: pd.DataFrame) -> None:
    order = ["Optimale", "Résolue", "Non résolue"]
    labels = ["Optimales", "Réalisables\n(non prouvées optimales)", "Non résolues"]
    counts = data["statut"].value_counts().reindex(order).fillna(0).astype(int)
    figure, axis = plt.subplots(figsize=(7.2, 4.2))
    bars = axis.barh(labels, counts, color=[BLUE, GRAY, ORANGE], height=0.5)
    axis.bar_label(bars, padding=7, fontsize=12, color=DARK)
    axis.invert_yaxis()
    axis.set(xlabel="Nombre d’instances", xlim=(0, counts.max() * 1.18))
    axis.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    axis.grid(axis="x")
    axis.tick_params(axis="y", length=0)
    sns.despine(ax=axis, left=True)
    figure.tight_layout(pad=1.4)
    save_figure(figure, "1_statut_instances")


def plot_time_and_gap_sample(gaps: pd.DataFrame) -> pd.DataFrame:
    sample = gaps[gaps["instance"].isin(SAMPLE_IDS)].copy().sort_values("requêtes")
    if len(sample) != 10:
        raise ValueError(f"Dix instances étaient attendues, {len(sample)} ont été trouvées.")

    figure, axes = plt.subplots(1, 2, figsize=(10.4, 4.1), sharex=True)
    sns.scatterplot(
        data=sample,
        x="requêtes",
        y="temps_s",
        color=BLUE,
        s=58,
        edgecolor="white",
        linewidth=0.7,
        ax=axes[0],
        zorder=3,
    )
    axes[0].axhline(TIME_LIMIT, color=GRAY, linestyle=(0, (4, 3)), linewidth=1)
    axes[0].set(
        xlabel="Nombre de requêtes",
        ylabel="Temps de résolution (s)",
        xlim=(0, 116),
        ylim=(-10, 320),
    )

    sns.scatterplot(
        data=sample,
        x="requêtes",
        y="écart_optimalité_pct",
        color=BLUE,
        s=58,
        edgecolor="white",
        linewidth=0.7,
        ax=axes[1],
        zorder=3,
    )
    axes[1].set(
        xlabel="Nombre de requêtes",
        ylabel="Écart d’optimalité (%)",
        xlim=(0, 116),
        ylim=(-4, 104),
    )
    for axis in axes:
        axis.grid(axis="y")
        axis.grid(axis="x", visible=False)
        sns.despine(ax=axis)
    axes[0].set_yticks([0, 100, 200, 300])
    axes[1].set_yticks([0, 25, 50, 75, 100])
    figure.tight_layout(pad=1.4, w_pad=2.5)
    save_figure(figure, "2_temps_gap_requetes")
    return sample


def paired_comparison_data() -> pd.DataFrame:
    with_costs = load_solutions(WITH_COSTS_DIR)
    without_costs = load_solutions(REEVALUATED_DIR)
    rows = []
    for instance_id in sorted(with_costs.keys() & without_costs.keys()):
        cost_aware = with_costs[instance_id]
        cost_unaware = without_costs[instance_id]
        rows.append(
            {
                "instance": instance_id,
                "coût_avec_prise_en_compte": cost_aware.preparation_cost,
                "coût_sans_prise_en_compte": cost_unaware.preparation_cost,
                "changements_avec_prise_en_compte": cost_aware.changes,
                "changements_sans_prise_en_compte": cost_unaware.changes,
            }
        )
    return pd.DataFrame(rows)


def summarize_changeover_cost_impact(paired: pd.DataFrame) -> pd.DataFrame:
    lower = int((paired["coût_avec_prise_en_compte"] < paired["coût_sans_prise_en_compte"]).sum())
    equal = int((paired["coût_avec_prise_en_compte"] == paired["coût_sans_prise_en_compte"]).sum())
    higher = int((paired["coût_avec_prise_en_compte"] > paired["coût_sans_prise_en_compte"]).sum())
    comparison = pd.DataFrame(
        {
            "résultat": ["Coût plus bas", "Coût non réduit"],
            "instances": [lower, equal + higher],
            "détail": ["", f"{equal} identiques ; {higher} plus hauts"],
        }
    )

    return comparison


def summarize_product_change_impact(paired: pd.DataFrame) -> pd.DataFrame:
    x_column = "changements_sans_prise_en_compte"
    y_column = "changements_avec_prise_en_compte"
    categories = pd.Series("Identique", index=paired.index)
    categories.loc[paired[y_column] < paired[x_column]] = "Moins de changements"
    categories.loc[paired[y_column] > paired[x_column]] = "Plus de changements"
    plotted = paired.assign(résultat=categories)
    return plotted


def plot_grouped_impacts(paired: pd.DataFrame) -> pd.DataFrame:
    """Compare les deux impacts sur les mêmes instances appariées."""
    categories = ["Diminution", "Identique", "Augmentation"]
    summary = pd.DataFrame({"résultat": categories})
    figure, axis = plt.subplots(figsize=(8, 4.5))
    width = 0.32
    for offset, metric, label, color in [
        (-width / 2, "coût", "Changeover cost", BLUE),
        (width / 2, "changements", "Nombre de changements", GRAY),
    ]:
        before = paired[f"{metric}_sans_prise_en_compte"]
        after = paired[f"{metric}_avec_prise_en_compte"]
        counts = [int((after < before).sum()), int((after == before).sum()), int((after > before).sum())]
        summary[label] = counts
        bars = axis.bar([i + offset for i in range(3)], counts, width=width, color=color, label=label)
        axis.bar_label(bars, padding=5, fontsize=12, color=DARK)
    axis.set_xticks(range(3), categories)
    axis.set_ylabel("Nombre d’instances")
    axis.set_ylim(0, summary.iloc[:, 1:].to_numpy().max() * 1.18)
    axis.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    axis.grid(axis="y")
    axis.tick_params(axis="x", length=0)
    axis.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2)
    sns.despine(ax=axis)
    figure.tight_layout(pad=1.4)
    save_figure(figure, "5_impacts_groupes")
    return summary


def plot_metrics_by_requests(runs: pd.DataFrame) -> pd.DataFrame:
    """Compare les deux scénarios uniquement sur les instances appariées."""
    with_costs = load_solutions(WITH_COSTS_DIR)
    without_costs = load_solutions(REEVALUATED_DIR)
    request_counts = runs.set_index("instance")["requêtes"]
    bins = [0, 25, 50, 100, float("inf")]
    labels = ["1–25", "26–50", "51–100", ">100"]
    records = []
    for instance_id in sorted(with_costs.keys() & without_costs.keys()):
        requests = int(request_counts.loc[instance_id])
        request_range = pd.cut([requests], bins=bins, labels=labels)[0]
        for scenario, solution in [("Avec", with_costs[instance_id]), ("Sans", without_costs[instance_id])]:
            records.append({
                "instance": instance_id,
                "requêtes": requests,
                "classe": str(request_range),
                "scénario": scenario,
                "distance": solution.distance,
                "changeover_cost": solution.preparation_cost,
                "voyages": solution.trips,
            })
    data = pd.DataFrame(records)
    paired_counts = data[data["scénario"] == "Avec"]["classe"].value_counts()
    tick_labels = [f"{label}\n(n={paired_counts.get(label, 0)})" for label in labels]
    for metric, ylabel, stem in [
        ("distance", "Distance totale", "6_distance_par_requetes"),
        ("changeover_cost", "Changeover cost total", "7_changeover_cost_par_requetes"),
        ("voyages", "Nombre de voyages", "8_voyages_par_requetes"),
    ]:
        figure, axis = plt.subplots(figsize=(8.2, 4.7))
        sns.boxplot(
            data=data, x="classe", y=metric, hue="scénario", order=labels,
            hue_order=["Avec", "Sans"], palette=[BLUE, GRAY], width=0.6,
            linewidth=1, fliersize=3, ax=axis,
        )
        axis.set(xlabel="Nombre de requêtes", ylabel=ylabel)
        axis.set_xticks(range(len(labels)), tick_labels)
        axis.grid(axis="y")
        axis.legend(title="Changeover costs", frameon=False, loc="lower center",
                    bbox_to_anchor=(0.5, 1.02), ncol=2)
        sns.despine(ax=axis)
        figure.tight_layout(pad=1.4)
        save_figure(figure, stem)
    return data


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_style()
    runs, gaps = load_run_data()
    paired = paired_comparison_data()

    plot_status_bars(runs)
    sample = plot_time_and_gap_sample(gaps)
    cost_comparison = summarize_changeover_cost_impact(paired)
    change_comparison = summarize_product_change_impact(paired)
    grouped_comparison = plot_grouped_impacts(paired)
    metric_comparison = plot_metrics_by_requests(runs)

    runs.to_csv(OUTPUT_DIR / "donnees_statuts.csv", index=False)
    sample.to_csv(OUTPUT_DIR / "echantillon_temps_gap.csv", index=False)
    cost_comparison.to_csv(OUTPUT_DIR / "comparaison_couts_changement.csv", index=False)
    change_comparison.to_csv(OUTPUT_DIR / "comparaison_nombre_changements.csv", index=False)
    grouped_comparison.to_csv(OUTPUT_DIR / "comparaison_impacts_groupes.csv", index=False)
    metric_comparison.to_csv(OUTPUT_DIR / "comparaison_indicateurs_par_requetes.csv", index=False)


if __name__ == "__main__":
    main()
