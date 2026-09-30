"""Types specific to the MILP solver."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MilpSolution:
    objective: float
    best_bound: float
    mip_gap: float
    node_count: float
    solver_runtime: float
    status: int
    routes: list[dict]
