from __future__ import annotations

import time
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from gurobipy import GRB, Model, quicksum

from src.utils.parser2 import MPVRPInstance
from src.utils.schemas import DepotNode, RequestNode
from src.utils.sol_writer import write_solution

TIME_LIMIT = 60
EPSILON = 1e-6
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LPSolution:
    objective: float
    status: int
    routes: list[dict]


# =========================================================================
# Bornes sur le nombre de mini-routes (trips) par véhicule
# =========================================================================

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


# =========================================================================
# Modèle
# =========================================================================

def solve_lp(
        instance: MPVRPInstance,
        max_trips_per_vehicle: int | None = None,
        time_limit: int = TIME_LIMIT,
        output: bool = True,
) -> LPSolution | None:
    """
    Résout un MILP MPVRP-CC borné en nombre de mini-routes par véhicule,
    en s'appuyant directement sur `instance.arc_cost` / `instance.vehicle_arc_cost`
    (le coût de changeover est déjà intégré dans le coût de chaque arc autorisé,
    donc aucun terme de changeover séparé n'apparaît dans l'objectif).

    Chaque mini-route (trip) démarre à un DepotNode (produit fixé par le nœud),
    livre une ou plusieurs requêtes du même produit, puis se termine soit par
    un arc direct vers le DepotNode du trip suivant (variable `exit`), soit
    par un retour au garage du véhicule (variable `final`) si c'est son
    dernier trip actif.
    """
    if max_trips_per_vehicle is None:
        max_trips_per_vehicle = _minimum_uniform_trip_bound(instance)

    _validate_trip_bound(instance, max_trips_per_vehicle)

    vehicles = range(instance.n_vehicles)
    trips = range(max_trips_per_vehicle)
    depots = range(len(instance.depots))      # index dans instance.depots (déjà par produit)
    requests = range(len(instance.requests))  # index dans instance.requests (déjà par produit)

    # n_depot_nodes = len(instance.depots)
    n_request_nodes = len(instance.requests)

    def depot_of(d: int) -> DepotNode:
        return instance.depots[d]

    def request_of(r: int) -> RequestNode:
        return instance.requests[r]

    def cost(a, b) -> float:
        """Coût d'arc statique (distance + changeover déjà intégré) entre deux noeuds."""
        return instance.arc_cost[a.global_id][b.global_id]

    # Arcs autorisés à l'intérieur d'un même trip : Depot(d) -> Request(r) et
    # Request(r) -> Request(r'), tous deux restreints au même produit par
    # construction de arc_cost (INF sinon).
    depot_to_request_arcs = [
        (d, r) for d in depots for r in requests
        if cost(depot_of(d), request_of(r)) < float("inf")
    ]
    request_to_request_arcs = [
        (r1, r2) for r1 in requests for r2 in requests
        if r1 != r2 and cost(request_of(r1), request_of(r2)) < float("inf")
    ]

    model_name = f"{instance.uuid}_bounded_trip_mip"
    m = Model(model_name)
    m.setParam("OutputFlag", 1 if output else 0)
    m.setParam("TimeLimit", time_limit)

    # ---------------------------------------------------------------
    # Variables
    # ---------------------------------------------------------------

    active = m.addVars(vehicles, trips, vtype=GRB.BINARY, name="active")
    start_depot = m.addVars(vehicles, trips, depots, vtype=GRB.BINARY, name="start_depot")
    visit = m.addVars(vehicles, trips, requests, vtype=GRB.BINARY, name="visit")
    quantity = m.addVars(vehicles, trips, requests, lb=0, vtype=GRB.INTEGER, name="quantity")
    depot_load = m.addVars(vehicles, trips, depots, lb=0, vtype=GRB.INTEGER, name="depot_load")

    arc_dr = m.addVars(
        ((k, t, d, r) for k in vehicles for t in trips for d, r in depot_to_request_arcs),
        vtype=GRB.BINARY, name="arc_dr",
    )
    arc_rr = m.addVars(
        ((k, t, r1, r2) for k in vehicles for t in trips for r1, r2 in request_to_request_arcs),
        vtype=GRB.BINARY, name="arc_rr",
    )

    exit_rd = m.addVars(
        ((k, t, r, d) for k in vehicles for t in range(max_trips_per_vehicle - 1)
         for r in requests for d in depots),
        vtype=GRB.BINARY, name="exit_rd",
    )

    final = m.addVars(vehicles, trips, requests, vtype=GRB.BINARY, name="final")

    order = m.addVars(vehicles, trips, requests, lb=0.0, ub=n_request_nodes,
                       vtype=GRB.CONTINUOUS, name="order")
    last_trip = m.addVars(vehicles, trips, vtype=GRB.BINARY, name="last_trip")

    # ---------------------------------------------------------------
    # Contraintes
    # ---------------------------------------------------------------

    for k in vehicles:
        for t in trips:
            m.addConstr(quicksum(start_depot[k, t, d] for d in depots) == active[k, t],
                        name=f"one_start_depot[{k},{t}]")
            if t > 0:
                m.addConstr(active[k, t] <= active[k, t - 1], name=f"ordered_trips[{k},{t}]")

    # Flux entrant dans un dépôt de départ : depuis le garage pour t=0 (implicite,
    # pris en compte uniquement dans le coût via vehicle_arc_cost), depuis la
    # dernière requête du trip précédent sinon.
    for k in vehicles:
        for t in trips:
            if t > 0:
                for d in depots:
                    m.addConstr(
                        quicksum(exit_rd[k, t - 1, r, d] for r in requests) == start_depot[k, t, d],
                        name=f"depot_inflow[{k},{t},{d}]",
                    )

    # Flux sortant d'un dépôt de départ vers la première requête du trip.
    for k in vehicles:
        for t in trips:
            for d in depots:
                out_r = [r for (dd, r) in depot_to_request_arcs if dd == d]
                m.addConstr(
                    quicksum(arc_dr[k, t, d, r] for r in out_r) == start_depot[k, t, d],
                    name=f"depot_outflow[{k},{t},{d}]",
                )

    # Flux entrant / sortant de chaque requête visitée dans un trip.
    for k in vehicles:
        for t in trips:
            for r in requests:
                in_d = [d for (d, rr) in depot_to_request_arcs if rr == r]
                in_r = [r1 for (r1, r2) in request_to_request_arcs if r2 == r]
                m.addConstr(
                    quicksum(arc_dr[k, t, d, r] for d in in_d)
                    + quicksum(arc_rr[k, t, r1, r] for r1 in in_r)
                    == visit[k, t, r],
                    name=f"request_in[{k},{t},{r}]",
                )

                out_r = [r2 for (r1, r2) in request_to_request_arcs if r1 == r]
                exit_terms = (
                    quicksum(exit_rd[k, t, r, d] for d in depots)
                    if t < max_trips_per_vehicle - 1 else 0
                )
                m.addConstr(
                    quicksum(arc_rr[k, t, r, r2] for r2 in out_r) + exit_terms + final[k, t, r]
                    == visit[k, t, r],
                    name=f"request_out[{k},{t},{r}]",
                )

    # Exactement une transition de sortie par trip non terminal actif, vers le trip suivant.
    for k in vehicles:
        for t in range(max_trips_per_vehicle - 1):
            m.addConstr(
                quicksum(exit_rd[k, t, r, d] for r in requests for d in depots) == active[k, t + 1],
                name=f"exit_total[{k},{t}]",
            )

    # Dernier trip actif -> identification + exactement un retour au garage.
    for k in vehicles:
        for t in trips:
            if t < max_trips_per_vehicle - 1:
                m.addConstr(last_trip[k, t] == active[k, t] - active[k, t + 1], name=f"last_trip[{k},{t}]")
            else:
                m.addConstr(last_trip[k, t] == active[k, t], name=f"last_trip[{k},{t}]")

            m.addConstr(
                quicksum(final[k, t, r] for r in requests) == last_trip[k, t],
                name=f"final_total[{k},{t}]",
            )

    # Un véhicule ne visite jamais deux fois la même requête (station/produit),
    # tous trips confondus (la demande peut néanmoins être répartie entre véhicules).
    for k in vehicles:
        for r in requests:
            m.addConstr(quicksum(visit[k, t, r] for t in trips) <= 1,
                        name=f"one_visit_per_vehicle_request[{k},{r}]")

    # Quantités, satisfaction de la demande, capacité véhicule.
    for r in requests:
        demand = int(request_of(r).demand)
        if demand <= 0:
            for k in vehicles:
                for t in trips:
                    m.addConstr(quantity[k, t, r] == 0, name=f"zero_quantity[{k},{t},{r}]")
            continue

        m.addConstr(
            quicksum(quantity[k, t, r] for k in vehicles for t in trips) == demand,
            name=f"demand[{r}]",
        )
        for k in vehicles:
            for t in trips:
                m.addConstr(quantity[k, t, r] <= demand * visit[k, t, r],
                            name=f"quantity_visit[{k},{t},{r}]")

    for k in vehicles:
        capacity = int(instance.vehicles[k].capacity)
        for t in trips:
            m.addConstr(
                quicksum(quantity[k, t, r] for r in requests) <= capacity * active[k, t],
                name=f"capacity[{k},{t}]",
            )

    # Volume chargé par dépôt (linéarisation), puis contrainte de stock.
    for k in vehicles:
        max_load = int(instance.vehicles[k].capacity)
        for t in trips:
            trip_load = quicksum(quantity[k, t, r] for r in requests)
            for d in depots:
                m.addConstr(depot_load[k, t, d] <= max_load * start_depot[k, t, d],
                            name=f"depot_load_start[{k},{t},{d}]")
                m.addConstr(depot_load[k, t, d] <= trip_load,
                            name=f"depot_load_trip_ub[{k},{t},{d}]")
                m.addConstr(depot_load[k, t, d] >= trip_load - max_load * (1 - start_depot[k, t, d]),
                            name=f"depot_load_trip_lb[{k},{t},{d}]")

    for d in depots:
        m.addConstr(
            quicksum(depot_load[k, t, d] for k in vehicles for t in trips) <= int(depot_of(d).stock),
            name=f"stock[{d}]",
        )

    # Élimination de sous-tours (MTZ) parmi les requêtes visitées au sein d'un même trip.
    for k in vehicles:
        for t in trips:
            for r in requests:
                m.addConstr(order[k, t, r] <= n_request_nodes * visit[k, t, r], name=f"order_ub[{k},{t},{r}]")
                m.addConstr(order[k, t, r] >= visit[k, t, r], name=f"order_lb[{k},{t},{r}]")
            for r1, r2 in request_to_request_arcs:
                m.addConstr(
                    order[k, t, r1] - order[k, t, r2] + n_request_nodes * arc_rr[k, t, r1, r2]
                    <= n_request_nodes - 1,
                    name=f"mtz[{k},{t},{r1},{r2}]",
                )

    # ---------------------------------------------------------------
    # Objectif : tous les coûts (distance + changeover) sont déjà intégrés
    # dans arc_cost / vehicle_arc_cost, aucun terme de changeover séparé.
    # ---------------------------------------------------------------

    travel_cost_dr = quicksum(
        cost(depot_of(d), request_of(r)) * arc_dr[k, t, d, r]
        for k in vehicles
        for t in trips
        for d, r in depot_to_request_arcs
    )
    travel_cost_rr = quicksum(
        cost(request_of(r1), request_of(r2)) * arc_rr[k, t, r1, r2]
        for k in vehicles
        for t in trips
        for r1, r2 in request_to_request_arcs
    )
    exit_cost = quicksum(
        cost(request_of(r), depot_of(d)) * exit_rd[k, t, r, d]
        for k in vehicles
        for t in range(max_trips_per_vehicle - 1)
        for r in requests for d in depots
    )
    final_cost = quicksum(
        cost(request_of(r), instance.vehicles[k].init_g) * final[k, t, r]
        for k in vehicles
        for t in trips
        for r in requests
    )
    garage_start_cost = quicksum(
        instance.vehicle_arc_cost(instance.vehicles[k], instance.vehicles[k].init_g, depot_of(d))
        * start_depot[k, 0, d]
        for k in vehicles
        for d in depots
    )

    m.setObjective(
        travel_cost_dr
        + travel_cost_rr
        + exit_cost
        + final_cost
        + garage_start_cost,
        GRB.MINIMIZE,
    )

    m.optimize()

    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        print(f"No feasible solution found. Gurobi status: {m.status}")
        return None

    if m.solCount == 0:
        print(f"No incumbent solution found. Gurobi status: {m.status}")
        return None

    # ---------------------------------------------------------------
    # Extraction de la solution
    # ---------------------------------------------------------------

    routes = []
    for k in vehicles:
        for t in trips:
            if active[k, t].X <= 0.5:
                continue

            selected_d = next(d for d in depots if start_depot[k, t, d].X > 0.5)
            visited_r = [r for r in requests if visit[k, t, r].X > 0.5]
            visited_r.sort(key=lambda r: order[k, t, r].X)

            depot_node = depot_of(selected_d)
            deliveries = [
                {
                    "station": request_of(r).id,
                    "product": depot_node.product + 1,
                    "quantity": quantity[k, t, r].X,
                }
                for r in visited_r
                if quantity[k, t, r].X > EPSILON
            ]

            routes.append(
                {
                    "vehicle": instance.vehicles[k].id,
                    "trip": t + 1,
                    "product": depot_node.product + 1,
                    "start_depot": depot_node.id,
                    "path": [f"S{request_of(r).id}" for r in visited_r],
                    "deliveries": deliveries,
                }
            )

    print(f"Solution found with objective value: {m.objVal}")
    return LPSolution(objective=m.objVal, status=m.status, routes=routes)


if __name__ == "__main__":
    filename = PROJECT_ROOT / "inst" / "MPVRP_145_s36_d7_p5.dat"
    instance = MPVRPInstance.read(filename)
    start_time = time.perf_counter()
    sol = solve_lp(instance=instance, time_limit=190)
    end_time = time.perf_counter()
    if sol:
        write_solution(instance=instance, routes=sol.routes, resolution_time=end_time - start_time)