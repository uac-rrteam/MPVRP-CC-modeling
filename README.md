# MPVRP-CC

Python tools for generating, validating, and solving the **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Costs**.

The project studies how product-transition costs influence route planning for a heterogeneous fleet serving multiple products, depots, and customers. Off-diagonal costs represent product changes; positive low-cost diagonal entries represent preparation and loading when a vehicle retains the same product.

## Project layout

```text
.
├── code/
│   ├── common/
│   │   └── paths.py         # Central project paths
│   ├── lp1/                 # First LP formulation
│   │   ├── io/
│   │   │   ├── inst.py      # Instance parser
│   │   │   └── sol.py       # Solution formatter and writer
│   │   ├── model.py         # Gurobi model
│   │   └── schemas.py       # LP1 data structures
│   └── tools/               # Generation and experiment commands
├── data/
│   ├── instances/
│   │   ├── in/     # Generated benchmark instances
│   │   ├── out/  # Paired zero-cost instances
│   └── solutions/
│       ├── in/
│       └── out/
├── docs/                    # Problem and file-format documentation
└── pyproject.toml
```

## Installation

Python 3.12 or later and a valid Gurobi installation/license are required.

```bash
uv sync
```

After installation, the project exposes dedicated commands. `uv run` also
discovers the packages directly from `code/`, so no manual `PYTHONPATH` setup
is needed.

Run the test suite with:

```bash
uv run pytest
```

## Common commands

Generate one instance:

```bash
mpvrp-generate -v 5 -d 2 -g 2 -s 12 -p 3 --id S_001
```

Generate the main experimental benchmark:

```bash
mpvrp-generate-benchmark --count 100
```

The main benchmark always contains at least two products and samples `normal`,
`high`, and `mixed` changeover regimes. Mixed matrices contain normal and high
off-diagonal arcs, while every diagonal uses the `low` range. The
single-instance generator still exposes the `low` level and
accepts one product for separate control or sensitivity experiments. All
numeric values stored in newly generated instance files are integers. The
parser also exposes an integer distance matrix, rounded to the nearest unit for
constraint programming; the MILP continues to use exact Euclidean distances.

The inclusive integer ranges are `25–150` for `low`, `1001–3500` for
`normal`, and `4501–15000` for `high`. In the main benchmark, `low` is used
only on the diagonal; `normal`, `high`, or both are used off the diagonal.

The current benchmark contains 100 paired instances. Its transition-cost
regimes are balanced as follows: 34 `normal`, 33 `high`, and 33 `mixed`.
The product-count distribution is 22 instances with 2 products, 30 with 3,
12 with 4, 22 with 5, and 14 with 6.

Validate an instance:

```bash
mpvrp-validate data/instances/in/MPVRP_003_s37_d2_p2.dat
```

Recreate the paired zero-changeover dataset:

```bash
mpvrp-prepare-scenarios --force
```

Solve the benchmark with transition costs:

```bash
mpvrp-solve-benchmark --scenario with_changeover_costs --time-limit 190
```

Solve the paired benchmark with zero costs:

```bash
mpvrp-solve-benchmark --scenario without_changeover_costs --time-limit 190
```

Re-evaluate a fixed zero-cost solution with the cost-bearing transition matrix:

```bash
mpvrp-reevaluate-changeovers \
  data/solutions/lp2/without_changeover_costs/Sol_003_s37_d2_p2.dat \
  --output data/solutions/lp2/without_changeover_costs/reevaluated_with_changeover_costs/Sol_003_s37_d2_p2.dat
```

This does not rerun the solver or alter the source solution. It writes a copy
under the selected method's
`without_changeover_costs/reevaluated_with_changeover_costs/` directory and
updates only the cumulative costs on product lines, the number of genuine
product changes, and the total transition cost.

Reevaluate every available LP2 zero-cost solution with:

```bash
./scripts/reevaluate_all_changeovers.sh
```

If an LP2 benchmark run was interrupted, resume it without discarding report
rows that were already checkpointed:

```bash
mpvrp-solve-benchmark --method 2 --scenario with_changeover_costs --resume
```

Each scenario writes solutions and its `benchmark_report.csv` to the corresponding directory under `data/solutions/`.

Create the LP2 paper figures (PNG and vector PDF) plus the paired analysis CSV:

```bash
mpvrp-plot-lp2-results
```

The outputs are written to `results/article_figures/lp2/`. Objective plots use
only instances solved in both compared scenarios, so every plotted observation
is a matched instance.

## Paired experimental design

Files with the same name in the two instance directories form a pair. The zero-cost version preserves every other field and replaces only the product-transition matrix with zeros. This makes it possible to attribute route differences specifically to the presence or absence of transition and preparation costs.

See [docs/problem.md](docs/problem.md), [docs/instance_format.md](docs/instance_format.md), and [docs/solution_format.md](docs/solution_format.md) for the complete specifications.
