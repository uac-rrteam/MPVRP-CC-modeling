# MPVRP-CC

Python tools for generating, validating, and solving the **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Costs**.

The project studies how product-transition costs influence route planning for a heterogeneous fleet serving multiple products, depots, and customers. Off-diagonal costs represent product changes; positive low-cost diagonal entries represent preparation and loading when a vehicle retains the same product.

## Project layout

```text
.
├── src/mpvrp_cc/
│   ├── cli/                 # Command-line validation
│   ├── experiments/         # Benchmark generation, pairing, and solving
│   ├── generation/          # Instance generation, schemas, I/O, and validation
│   ├── io/                  # Instance parsing and solution serialization
│   ├── optimization/        # Canonical Gurobi MILP solver
│   └── paths.py             # Central project paths
├── data/
│   ├── instances/
│   │   ├── with_changeover_costs/     # Generated benchmark instances
│   │   ├── without_changeover_costs/  # Paired zero-cost instances
│   └── solutions/
│       ├── with_changeover_costs/
│       └── without_changeover_costs/
├── docs/                    # Problem and file-format documentation
├── results/article_figures/ # Generated analysis figures
└── pyproject.toml
```

## Installation

Python 3.12 or later and a valid Gurobi installation/license are required.

```bash
uv sync
```

After installation, the project exposes dedicated commands. During local development, the equivalent modules can also be run with `PYTHONPATH=src python -m ...`.

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
mpvrp-validate data/instances/with_changeover_costs/MPVRP_003_s37_d2_p2.dat
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
  data/solutions/without_changeover_costs/Sol_003_s37_d2_p2.dat
```

This does not rerun the solver or alter the source solution. It writes a copy
under `data/solutions/without_changeover_costs/reevaluated_with_changeover_costs/`
and updates only the cumulative costs on product lines, the number of genuine
product changes, and the total transition cost.

Each scenario writes solutions and its `benchmark_report.csv` to the corresponding directory under `data/solutions/`.

## Paired experimental design

Files with the same name in the two instance directories form a pair. The zero-cost version preserves every other field and replaces only the product-transition matrix with zeros. This makes it possible to attribute route differences specifically to the presence or absence of transition and preparation costs.

See [docs/problem.md](docs/problem.md), [docs/instance_format.md](docs/instance_format.md), and [docs/solution_format.md](docs/solution_format.md) for the complete specifications.
