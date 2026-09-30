# A MILP approach to solve the Multi-product Vehicle Routing Problem with Changeover Costs (MPVRP-CC)

The Multi-Product Vehicle Routing Problem with Changeover Costs concerns deliveries of several products from depots with stock to stations with specified demands, using capacitated vehicles. A vehicle may make several trips during the planning period. On each trip, it loads one product at a depot, visits stations requiring that product, and delivers its entire load before loading again. The next trip may start at another depot. Each used vehicle leaves its home garage and returns there after its final delivery.

![instance example](docs/instance_example.png)

Successive loads may require preparation. The changeover cost depends on the previous and next products, while the vehicle's initial product state determines the preparation before its first load. The model chooses delivery quantities, loading depots, vehicle assignments, and operation order to satisfy all demand while minimizing travel and changeover costs. The shortest route is therefore not always the least expensive plan.

## Methods, design and evaluation

```mermaid
flowchart LR
    A[Generate and validate instances] --> B[Create paired scenarios]
    B --> C[With changeover costs]
    B --> D[Without changeover costs]
    C --> E[Solve MILP with Gurobi]
    D --> E
    E --> F[Check solutions and compare costs]
```

The paired instances share demands, depots, vehicles, and travel data; the second scenario sets changeover costs to zero. Benchmark reports record solution status and objective values. Zero-cost solutions can also be repriced using the original changeover matrix.

## Tools

- Python 3.12.3 (the project requires Python 3.12 or newer)
- Gurobi 13.0.1 solver and a working Gurobi license
- 100 benchmark instances with varied configurations

## Files

| Path | Purpose |
| --- | --- |
| `src/mpvrp/` | Shared instance model, instance/solution I/O, and solution checker |
| `src/milp/` | MILP result type, formulation, and benchmark solve command |
| `src/tools/` | Instance generation, validation, scenario pairing, repricing, and plotting |
| `data/instances/` | Generated and paired benchmark instances |
| `data/solutions/milp/` | Solver solutions and benchmark reports |
| `docs/` | Problem description and file format documentation |
| `results/logs/` | Command logs |
| `results/plots/` | Generated instance and solution plots |
| `tests/` | Automated checks |

See [data/README.md](data/README.md) for the detailed data layout.

## Setup instructions

Install Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and configure a Gurobi license. From the project directory, install dependencies and run the checks:

```bash
uv sync
uv run pytest
```

Generate and validate an example instance:

```bash
uv run mpvrp-generate -v 5 -d 2 -g 2 -s 12 -p 3 --id S_001
uv run mpvrp-validate data/instances/generated/MPVRP_S_001_s12_d2_p3.dat
```

Generate the 100-instance benchmark and paired zero-cost scenarios, then solve both:

```bash
uv run mpvrp-generate-benchmark --count 100
uv run mpvrp-prepare-scenarios --force
uv run mpvrp-solve-benchmark --scenario 1 --time-limit 190
uv run mpvrp-solve-benchmark --scenario 2 --time-limit 190
```

Use `--force` with benchmark generation to replace existing instance files. To resume a reported solve run, add `--resume`; reported attempts, including unsolved ones, are skipped. To reprice a zero-cost solution with the original changeover costs, run:

```bash
uv run mpvrp-reevaluate-changeovers data/solutions/milp/out/Sol_003_s37_d2_p2.dat
```

The repriced copy is written to `data/solutions/milp/out/recomputed/`. Commands write logs under `results/logs/`.

Plot an instance's locations, or overlay the routes from its saved solution:

```bash
uv run mpvrp-plot --scenario 1 --inst 01
uv run mpvrp-plot --scenario 1 --inst 02 --solution --method milp
uv run mpvrp-plot --scenario 1 --inst 02 --solution --method cp
uv run mpvrp-plot --scenario 1 --all --solution --method cp
```

Scenario `1` uses changeover costs; scenario `2` uses the paired zero-cost instance and solution. `--method` chooses the MILP or CP solution directory and defaults to `milp`. `--all` (or `--inst all`) plots every instance in the scenario, skipping missing solution files and reporting how many were skipped. Plots use a light illustrated landscape by default; `--background plain` selects a plain plot. Axes remain visible in both styles. Plots are saved under `results/plots/scenario_1/` or `results/plots/scenario_2/`. Use `--output PATH` for one PNG, or `--output DIRECTORY` with `--all`.

Check a saved solution against its instance:

```bash
uv run mpvrp-check-solution --scenario 1 --inst 02 --method cp
uv run mpvrp-check-solution --scenario 1 --inst 02 --method milp --json results/check_002.json
uv run mpvrp-check-solution --scenario 1 --all --method cp --json results/cp_checks.json
uv run mpvrp-check-solution --scenario 1 --all --method milp --report-dir results/milp_checks
```

The checker reports PASS, FAIL, or SKIPPED for file format, vehicle schedules, trip continuity, product states, capacity, stock, demand, repeat service, and recalculated costs and distance. `--all` (or `--inst all`) checks every instance in the selected scenario and includes missing solutions in its summary. With `--all`, `--json PATH` saves one aggregate report and `--report-dir DIRECTORY` saves one JSON report per instance; both options can be combined. It exits with status `0` only when every checked solution is valid, or `1` if any is invalid or missing. Use `--instance-path` and `--solution-path` to check files outside the benchmark directories.

## Build another solving approach

Use `MPVRPInstance.read(path)` from `mpvrp.models` to load the same instances used by the MILP. The shared data types and file readers are in `src/mpvrp/`; solver-specific models and algorithms belong in their own package, like `src/milp/`. The existing MILP entry point in `src/milp/solve.py` shows how to iterate over a benchmark manifest and write a report.

To produce a solution in the repository format, pass your vehicle trips to `write_solution` from `mpvrp.io.solution` with an explicit destination path. Each trip records `vehicle`, `trip`, `product`, `start_depot`, and `deliveries` (station ID and quantity); an optional `path` records station visit order. See [the solution format](docs/solution_format.md) for the resulting file layout. Keep outputs for a new method under its own `data/solutions/<method>/in/` and `out/` directories.

## Useful links

- [Problem definition](docs/problem.md)
- [Instance format](docs/instance_format.md)
- [Solution format](docs/solution_format.md)
- [Data layout](data/README.md)
- [Gurobi Python documentation](https://docs.gurobi.com/projects/optimizer/en/current/reference/python.html)

## Team

-  [**Rosas Behoundja**](https://rosasbehoundja.github.io/)
- [Vinasétan Ratheil Houndji](mailto:vratheilhoundji@gmail.com)
- [Godright Adohounblessi](mailto:adohounblessirobert@gmail.com)
- [Jean-Eudes Codo](mailto:eudescodo00@gmail.com)
- [Fédel Folly](mailto:follyfedel@gmail.com)
- [Marc-André Akouete](mailto:christnam29@gmail.com)
