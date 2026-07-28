from __future__ import annotations

import time
from dataclasses import dataclass
from math import ceil, inf
from pathlib import Path

from gurobipy import GRB, Model, quicksum

from src.utils.parser import write_solution
from src.utils.parser2 import MPVRPInstance

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TIME_LIMIT = 60
EPSILON = 1e-6


@dataclass(frozen=True)
class LPSolution:
    objective: float
    status: int
    routes: list[dict]


def _minimum_uniform_trip_bound(instance: MPVRPInstance) -> int:
    total_demand = sum(r.demand for r in instance.requests)
    fleet_capacity = sum(v.capacity for v in instance.vehicles)
    if total_demand <= EPSILON:
        return 0
    if fleet_capacity <= EPSILON:
        raise ValueError("The fleet has no usable capacity.")
    return max(ceil(total_demand / fleet_capacity) + 1, instance.n_prods)


def _validate_trip_bound(instance: MPVRPInstance, max_trips_per_vehicle: int) -> None:
    if max_trips_per_vehicle < 1:
        raise ValueError("max_trips_per_vehicle must be at least 1.")

    total_demand = sum(r.demand for r in instance.requests)
    total_capacity = max_trips_per_vehicle * sum(v.capacity for v in instance.vehicles)
    if total_capacity + EPSILON < total_demand:
        minimum = _minimum_uniform_trip_bound(instance)
        raise ValueError(
            "max_trips_per_vehicle is too small to satisfy total demand: "
            f"capacity={total_capacity:.1f}, demand={total_demand:.1f}. "
            f"Use at least {minimum} trips per vehicle."
        )


def solve_lp(
        instance: MPVRPInstance,
        max_trips_per_vehicle: int | None = None,
        time_limit: int = TIME_LIMIT,
        output: bool = True,
) -> LPSolution | None:
    """
    Solve a bounded-trip MILP for MPVRP-CC on the dynamically typed execution graph.
    """
    if max_trips_per_vehicle is None:
        max_trips_per_vehicle = _minimum_uniform_trip_bound(instance)

    _validate_trip_bound(instance, max_trips_per_vehicle)

    model_name = f"{instance.uuid}_bounded_trip_mip"
    m = Model(model_name)
    m.setParam("OutputFlag", 1 if output else 0)
    m.setParam("TimeLimit", time_limit)

    # Entity Lists (typed nodes from the parser)
    vehicles = instance.vehicles
    depots = instance.depots
    requests = instance.requests
    trips = range(max_trips_per_vehicle)

    # --- 1. PRE-COMPUTE VALID TOPOLOGY ---
    # inner_arcs: (type_source, i_idx, j_idx). Valid moves WITHIN a trip (same product)
    inner_arcs = []
    arcs_from_D = {d: [] for d in range(len(depots))}
    arcs_to_R = {r: [] for r in range(len(requests))}
    arcs_from_R = {r: [] for r in range(len(requests))}

    # Depot -> Request
    for d_idx, d in enumerate(depots):
        for r_idx, r in enumerate(requests):
            if instance.arc_cost[d.global_id][r.global_id] != inf:
                inner_arcs.append(('D', d_idx, r_idx))
                arcs_from_D[d_idx].append(r_idx)
                arcs_to_R[r_idx].append(('D', d_idx))

    # Request -> Request
    for r1_idx, r1 in enumerate(requests):
        for r2_idx, r2 in enumerate(requests):
            if r1_idx != r2_idx and instance.arc_cost[r1.global_id][r2.global_id] != inf:
                inner_arcs.append(('R', r1_idx, r2_idx))
                arcs_from_R[r1_idx].append(r2_idx)
                arcs_to_R[r2_idx].append(('R', r1_idx))

    # --- 2. VARIABLES ---
    # Trip activation and boundaries
    active = m.addVars(len(vehicles), max_trips_per_vehicle, vtype=GRB.BINARY, name="active")
    start_d = m.addVars(len(vehicles), max_trips_per_vehicle, len(depots), vtype=GRB.BINARY, name="start_d")
    end_r = m.addVars(len(vehicles), max_trips_per_vehicle, len(requests), vtype=GRB.BINARY, name="end_r")
    visit = m.addVars(len(vehicles), max_trips_per_vehicle, len(requests), vtype=GRB.BINARY, name="visit")

    # Routing flow
    start_g = m.addVars(len(vehicles), len(depots), vtype=GRB.BINARY, name="start_g")
    x = m.addVars(len(vehicles), trips, inner_arcs, vtype=GRB.BINARY, name="x")
    trans = m.addVars(len(vehicles), range(1, max_trips_per_vehicle), len(requests), len(depots), vtype=GRB.BINARY,
                      name="trans")
    ret_g = m.addVars(len(vehicles), trips, len(requests), vtype=GRB.BINARY, name="ret_g")

    # Quantities
    q = m.addVars(len(vehicles), trips, inner_arcs, vtype=GRB.CONTINUOUS, lb=0.0, name="q")
    load = m.addVars(len(vehicles), trips, len(depots), vtype=GRB.CONTINUOUS, lb=0.0, name="load")
    deliv = m.addVars(len(vehicles), trips, len(requests), vtype=GRB.CONTINUOUS, lb=0.0, name="deliv")

    # MTZ for intra-trip subtour elimination
    u = m.addVars(len(vehicles), trips, len(requests), vtype=GRB.CONTINUOUS, lb=0.0, name="u")

    # --- 3. OBJECTIVE FUNCTION ---
    # The costs fetched below intrinsically include product changeover costs.
    obj = 0.0

    # Garage -> First Depot
    for k, v in enumerate(vehicles):
        for d_idx, d in enumerate(depots):
            cost = instance.vehicle_arc_cost(v, v.init_g, d)
            if cost != inf:
                obj += start_g[k, d_idx] * cost
            else:
                m.addConstr(start_g[k, d_idx] == 0)

    # Inner Trip Travel (Depot->Req, Req->Req)
    for k in range(len(vehicles)):
        for t in trips:
            for (type_i, i_idx, j_idx) in inner_arcs:
                i_global = depots[i_idx].global_id if type_i == 'D' else requests[i_idx].global_id
                obj += x[k, t, type_i, i_idx, j_idx] * instance.arc_cost[i_global][requests[j_idx].global_id]

    # Inter-trip Transition (Request -> Depot)
    for k in range(len(vehicles)):
        for t in range(1, max_trips_per_vehicle):
            for r_idx, r in enumerate(requests):
                for d_idx, d in enumerate(depots):
                    cost = instance.arc_cost[r.global_id][d.global_id]
                    if cost != inf:
                        obj += trans[k, t, r_idx, d_idx] * cost
                    else:
                        m.addConstr(trans[k, t, r_idx, d_idx] == 0)

    # Return to Garage
    for k, v in enumerate(vehicles):
        for t in trips:
            for r_idx, r in enumerate(requests):
                cost = instance.arc_cost[r.global_id][v.init_g.global_id]
                if cost != inf:
                    obj += ret_g[k, t, r_idx] * cost
                else:
                    m.addConstr(ret_g[k, t, r_idx] == 0)

    m.setObjective(obj, GRB.MINIMIZE)

    # --- 4. CONSTRAINTS ---

    # Trip sequence logic
    for k in range(len(vehicles)):
        for t in range(1, max_trips_per_vehicle):
            m.addConstr(active[k, t] <= active[k, t - 1], name=f"order_trips_{k}_{t}")

    for k in range(len(vehicles)):
        for t in trips:
            m.addConstr(quicksum(start_d[k, t, d] for d in range(len(depots))) == active[k, t],
                        name=f"one_start_{k}_{t}")
            m.addConstr(quicksum(end_r[k, t, r] for r in range(len(requests))) == active[k, t], name=f"one_end_{k}_{t}")

    # Start, Transition, and Return logic
    for k in range(len(vehicles)):
        m.addConstr(quicksum(start_g[k, d] for d in range(len(depots))) == active[k, 0])
        for d in range(len(depots)):
            m.addConstr(start_g[k, d] <= start_d[k, 0, d])

        for t in range(1, max_trips_per_vehicle):
            m.addConstr(
                quicksum(trans[k, t, r, d] for r in range(len(requests)) for d in range(len(depots))) == active[k, t])
            for r in range(len(requests)):
                m.addConstr(quicksum(trans[k, t, r, d] for d in range(len(depots))) == end_r[k, t - 1, r])
            for d in range(len(depots)):
                m.addConstr(quicksum(trans[k, t, r, d] for r in range(len(requests))) == start_d[k, t, d])

        for t in trips:
            is_last_trip = active[k, t] - active[k, t + 1] if t + 1 < max_trips_per_vehicle else active[k, t]
            m.addConstr(quicksum(ret_g[k, t, r] for r in range(len(requests))) == is_last_trip)
            for r in range(len(requests)):
                m.addConstr(ret_g[k, t, r] <= end_r[k, t, r])

    # Flow Conservation (Routing & Quantities)
    for k, v in enumerate(vehicles):
        for t in trips:
            # Depots
            for d in range(len(depots)):
                m.addConstr(quicksum(x[k, t, 'D', d, j] for j in arcs_from_D[d]) == start_d[k, t, d])
                m.addConstr(load[k, t, d] <= v.capacity * start_d[k, t, d])
                m.addConstr(quicksum(q[k, t, 'D', d, j] for j in arcs_from_D[d]) == load[k, t, d])

            # Requests
            for r, req in enumerate(requests):
                inflow = quicksum(x[k, t, type_i, i, r] for (type_i, i) in arcs_to_R[r])
                outflow = quicksum(x[k, t, 'R', r, j] for j in arcs_from_R[r])
                m.addConstr(inflow == visit[k, t, r])
                m.addConstr(outflow + end_r[k, t, r] == visit[k, t, r])

                # Deliveries
                m.addConstr(deliv[k, t, r] <= req.demand * visit[k, t, r])
                qin = quicksum(q[k, t, type_i, i, r] for (type_i, i) in arcs_to_R[r])
                qout = quicksum(q[k, t, 'R', r, j] for j in arcs_from_R[r])
                m.addConstr(qin - qout == deliv[k, t, r])

            # Arc capacities
            for (type_i, i, j) in inner_arcs:
                m.addConstr(q[k, t, type_i, i, j] <= v.capacity * x[k, t, type_i, i, j])

    # Global Demand and Stock
    for r, req in enumerate(requests):
        m.addConstr(quicksum(deliv[k, t, r] for k in range(len(vehicles)) for t in trips) == req.demand)

    for d, depot in enumerate(depots):
        m.addConstr(quicksum(load[k, t, d] for k in range(len(vehicles)) for t in trips) <= depot.stock)

    # MTZ for Requests
    for k in range(len(vehicles)):
        for t in trips:
            for (_, i, j) in inner_arcs:
                if _ == 'R':
                    m.addConstr(u[k, t, j] >= u[k, t, i] + 1 - len(requests) * (1 - x[k, t, 'R', i, j]))

    # --- 5. OPTIMIZATION & OUTPUT ---
    m.optimize()

    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or m.solCount == 0:
        print(f"No feasible solution found. Gurobi status: {m.status}")
        return None

    routes = []
    for k, v in enumerate(vehicles):
        for t in trips:
            if active[k, t].X < 0.5:
                continue

            d_start_idx = next(d for d in range(len(depots)) if start_d[k, t, d].X > 0.5)
            d_node = depots[d_start_idx]

            path_labels = []
            deliveries = []

            # Format match avec l'ancien `selected_route_nodes` qui s'attendait
            # à commencer par le dépôt. L'affichage complet de la chaine
            # `Garage - Depot - ...` pour le rapport .dat se fera via `write_solution`.
            path_labels.append(f"D{d_node.id}")

            current_r = next(r for r in range(len(requests)) if x[k, t, 'D', d_start_idx, r].X > 0.5)

            while True:
                r_node = requests[current_r]
                path_labels.append(f"S{r_node.id}")
                qty = deliv[k, t, current_r].X

                if qty > EPSILON:
                    deliveries.append({
                        "station": r_node.id,
                        "product": r_node.product,
                        "quantity": qty
                    })

                if end_r[k, t, current_r].X > 0.5:
                    break
                current_r = next(r for r in range(len(requests)) if x[k, t, 'R', current_r, r].X > 0.5)

            # Identification du Depot/Garage de terminaison pour ce mini-route
            if t < max_trips_per_vehicle - 1 and active[k, t + 1].X > 0.5:
                d_next = next(d for d in range(len(depots)) if trans[k, t + 1, current_r, d].X > 0.5)
                end_depot_id = depots[d_next].id
                path_labels.append(f"D{end_depot_id}")
            else:
                end_depot_id = v.init_g.id
                # path_labels.append(f"G{v.init_g.id}") # Omis si l'ancien write_solution l'ajoute

            routes.append({
                "vehicle": v.id,
                "trip": t + 1,
                "product": d_node.product,
                "start_depot": d_node.id,
                "end_depot": end_depot_id,
                "path": path_labels,
                "deliveries": deliveries,
            })

    print(f"Solution found with objective value: {m.objVal:.2f}")
    return LPSolution(objective=m.objVal, status=m.status, routes=routes)


if __name__ == "__main__":
    filename = PROJECT_ROOT / "inst" / "MPVRP_003_s3_d7_p5.dat"
    instance = MPVRPInstance.read(filename)
    start_time = time.perf_counter()
    sol = solve_lp(instance=instance, time_limit=190)
    end_time = time.perf_counter()

    if sol:
        write_solution(
            instance=instance,
            routes=sol.routes,
            resolution_time=end_time - start_time
        )