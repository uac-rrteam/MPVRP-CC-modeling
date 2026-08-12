# MPVRP-CC

Python tools for generating, validating, and solving the **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Costs**.

The project studies how product-transition costs influence route planning for a heterogeneous fleet serving multiple products, depots, and customers. Changeover costs represent the operational preparation required when a vehicle switches products, including cleaning, handling, reconfiguration, labor, controls, and downtime.

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
│   │   ├── with_changeover_costs/     # 150 original instances
│   │   ├── without_changeover_costs/  # 150 paired zero-cost instances
│   │   └── generated/                 # Ad hoc generated instances
│   └── solutions/
│       ├── with_changeover_costs/
│       └── without_changeover_costs/
├── docs/                    # Problem and file-format documentation
├── results/figures/         # Existing analysis figures
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

Validate an instance:

```bash
mpvrp-validate data/instances/with_changeover_costs/MPVRP_003_s3_d7_p5.dat
```

Recreate the paired zero-changeover dataset:

```bash
mpvrp-prepare-scenarios --force
```

Solve the benchmark with the original costs:

```bash
mpvrp-solve-benchmark --scenario with_changeover_costs --time-limit 190
```

Solve the paired benchmark with zero costs:

```bash
mpvrp-solve-benchmark --scenario without_changeover_costs --time-limit 190
```

Each scenario writes solutions and its `benchmark_report.csv` to the corresponding directory under `data/solutions/`.

## Paired experimental design

Files with the same name in the two instance directories form a pair. The zero-cost version preserves every original field and replaces only the product changeover matrix with zeros. This makes it possible to attribute route differences specifically to the presence or absence of changeover costs.

See [docs/problem.md](docs/problem.md), [docs/instance_format.md](docs/instance_format.md), and [docs/solution_format.md](docs/solution_format.md) for the complete specifications.
