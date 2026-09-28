# MPVRP-CC

Tools to generate, validate, and solve multi-product vehicle routing instances with split deliveries and product changeover costs. The MILP solver uses Gurobi.

## Setup

Requires Python 3.12+ and a working Gurobi license.

```bash
uv sync
uv run pytest
```

Run commands below with `uv run` if the environment is not activated, for example `uv run mpvrp-generate --help`.

## Workflow

Generate and validate one instance:

```bash
mpvrp-generate -v 5 -d 2 -g 2 -s 12 -p 3 --id S_001
mpvrp-validate data/instances/generated/MPVRP_S_001_s12_d2_p3.dat
```

Generate a benchmark and its zero-cost pairs:

```bash
mpvrp-generate-benchmark --count 100
mpvrp-prepare-scenarios --force
```

Use `--force` with benchmark generation when replacing existing instance files.

Solve either scenario, or resume a run from its report:

```bash
mpvrp-solve-benchmark --scenario with_changeover_costs --time-limit 190
mpvrp-solve-benchmark --scenario without_changeover_costs --time-limit 190
mpvrp-solve-benchmark --scenario with_changeover_costs --resume
```

Reprice a fixed zero-cost solution using the original cost matrix:

```bash
mpvrp-reevaluate-changeovers data/solutions/milp/out/Sol_003_s37_d2_p2.dat
```

This writes a copy under `data/solutions/milp/out/recomputed/` and leaves the source solution unchanged.

## Outputs

See [data/README.md](data/README.md) for directory meanings. Each benchmark solve writes a `benchmark_report.csv` with `OPTIMAL`, `SOLVED`, or `UNSOLVED` for every attempted instance. `--resume` skips every reported attempt, including `UNSOLVED`. The generation manifest records each accepted seed, attempt count, and rejected draws.

Every command writes a separate log under `results/logs/`. Use `--log-dir PATH` to change its location. `--quiet` reduces console output; the log still includes debug entries.

For the problem and file formats, see [docs/problem.md](docs/problem.md), [docs/instance_format.md](docs/instance_format.md), and [docs/solution_format.md](docs/solution_format.md).
