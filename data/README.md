# Data layout

| Directory | Contents |
| --- | --- |
| `instances/generated/` | Instances made with `mpvrp-generate`. Created on first use. |
| `instances/in/` | Benchmark instances with changeover costs and `manifest.csv`. |
| `instances/out/` | Matching benchmark instances with zero changeover costs and a copied manifest. |
| `solutions/milp/in/` | Solutions and `benchmark_report.csv` for the cost-bearing scenario. |
| `solutions/milp/out/` | Solutions and `benchmark_report.csv` for the zero-cost scenario. |
| `solutions/milp/out/recomputed/` | Copies of zero-cost solutions repriced with the original changeover matrix. |
| `solutions/cp/in/` | CP solutions for the cost-bearing scenario. |
| `solutions/cp/out/` | CP solutions for the zero-cost scenario. |

Files with the same instance name in `instances/in/` and `instances/out/` form a pair. The `out/` instance changes only the transition-cost matrix. Regenerate the pairs with `mpvrp-prepare-scenarios --force`.

Benchmark reports record `OPTIMAL` (Gurobi proved the model optimum), `SOLVED` (feasible solution), or `UNSOLVED` (no solution recorded in that run). The generation manifest includes the accepted seed and any rejected attempts.

For MILP reports, `objective` is recalculated from the saved route as travel distance plus changeover cost. `solver_objective`, `best_bound`, and MIP gap describe the Gurobi model run; the gap is relative to `solver_objective`. A saved route may have a different objective when its serialized path differs from the model's internal path.
