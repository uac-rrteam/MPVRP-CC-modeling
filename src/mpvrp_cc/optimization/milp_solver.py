from __future__ import annotations

import time
from dataclasses import dataclass
from math import ceil

from gurobipy import GRB, Model, quicksum

from mpvrp_cc.io.instance_solution_io import MPVRPInstance, MPVRPNode, write_solution
from mpvrp_cc.paths import WITH_CHANGEOVER_INSTANCES_DIR

TIME_LIMIT = 190
EPSILON = 1e-6


@dataclass(frozen=True)
class MilpSolution:
    objective: float
    best_bound: float
    mip_gap: float
    node_count: int
    solver_runtime: float
    status: int
    routes: list[dict]


def _distance(a: MPVRPNode, b: MPVRPNode) -> float:
    """Return the integer distance prescribed by the instance format."""
    return float(round(a.distance(b)))


def _maximum_uniform_trip_bound(instance: MPVRPInstance) -> int:
    total_demand = sum(sum(station.demand) for station in instance.stations)
    fleet_capacity = sum(vehicle.capacity for vehicle in instance.vehicles)
    if total_demand <= EPSILON:
        return 0
    if fleet_capacity <= EPSILON:
        raise ValueError("The fleet has no usable capacity.")
    return max(ceil(total_demand / fleet_capacity) + 1, instance.n_prods)


def _validate_trip_bound(instance: MPVRPInstance, max_trips_per_vehicle: int) -> None:
    if max_trips_per_vehicle < 1:
        raise ValueError("max_trips_per_vehicle must be at least 1.")

    total_demand = sum(sum(station.demand) for station in instance.stations)
    total_capacity = max_trips_per_vehicle * sum(vehicle.capacity for vehicle in instance.vehicles)
    if total_capacity + EPSILON < total_demand:
        configured_bound = _maximum_uniform_trip_bound(instance)
        raise ValueError(
            "max_trips_per_vehicle is too small to satisfy total demand: "
            f"capacity={total_capacity:.1f}, demand={total_demand:.1f}. "
            f"The default horizon is {configured_bound} trips per vehicle."
        )


def solve_milp(
        instance: MPVRPInstance,
        max_trips_per_vehicle: int | None = None,
        time_limit: int = TIME_LIMIT,
        output: bool = True,
) -> MilpSolution | None:
    """
    Solve a bounded-trip MILP for MPVRP-CC.

    Parameters
    ----------
    instance : MPVRPInstance
        The MPVRP-CC instance to solve.
    max_trips_per_vehicle : int | None, optional
        The maximum number of trips allowed per vehicle. If None, the default
        maximum uniform trip bound is used.
    time_limit : int, optional
        The time limit for the solver in seconds. Default is 190 seconds.
    output : bool, optional
        If True, enables Gurobi output. Default is True.

    Returns
    -------
    MilpSolution | None
        The solution of the MILP, or None if no feasible solution is found.
    """
    if max_trips_per_vehicle is None:
        max_trips_per_vehicle = _maximum_uniform_trip_bound(instance)

    _validate_trip_bound(instance, max_trips_per_vehicle)

    vehicles = range(instance.n_vehicles)
    trips = range(max_trips_per_vehicle)
    products = range(instance.n_prods)
    depots = range(instance.n_depots)
    stations = range(instance.n_stations)

    n_depot_nodes = instance.n_depots
    n_station_nodes = instance.n_stations
    station_offset = n_depot_nodes
    route_nodes = range(n_depot_nodes + n_station_nodes)
    station_nodes = range(station_offset, station_offset + n_station_nodes)

    def station_node(station_idx: int) -> int:
        return station_offset + station_idx

    def route_node(node_idx: int) -> MPVRPNode:
        if node_idx < n_depot_nodes:
            return instance.depots[node_idx]
        return instance.stations[node_idx - station_offset]

    allowed_arcs = [
        (i, j)
        for i in route_nodes
        for j in route_nodes
        if i != j and (i >= station_offset or j >= station_offset)
    ]

    model_name = f"{instance.uuid}_bounded_trip_mip"
    m = Model(model_name)
    m.setParam("OutputFlag", 1 if output else 0)
    m.setParam("TimeLimit", time_limit)

    active = m.addVars(vehicles, trips, vtype=GRB.BINARY, name="active")
    product = m.addVars(vehicles, trips, products, vtype=GRB.BINARY, name="product")
    start_depot = m.addVars(vehicles, trips, depots, vtype=GRB.BINARY, name="start_depot")
    visit = m.addVars(vehicles, trips, stations, vtype=GRB.BINARY, name="visit")
    visit_product = m.addVars(vehicles, trips, stations, products, vtype=GRB.BINARY, name="visit_product")
    quantity = m.addVars(vehicles, trips, stations, products, lb=0, vtype=GRB.INTEGER, name="quantity")
    depot_load = m.addVars(vehicles, trips, depots, products, lb=0, vtype=GRB.INTEGER, name="depot_load")
    arc = m.addVars(
        ((k, t, i, j) for k in vehicles for t in trips for i, j in allowed_arcs),
        vtype=GRB.BINARY,
        name="arc",
    )
    order = m.addVars(vehicles, trips, stations, lb=0.0, ub=n_station_nodes, vtype=GRB.CONTINUOUS, name="order")

    last_trip = m.addVars(vehicles, trips, vtype=GRB.BINARY, name="last_trip")
    garage_return = m.addVars(vehicles, trips, stations, vtype=GRB.BINARY, name="garage_return")

    if max_trips_per_vehicle > 1:
        change = m.addVars(vehicles, range(max_trips_per_vehicle - 1), products, products, vtype=GRB.BINARY,
                           name="change")
    else:
        change = {}

    # Trip activation and sequencing.
    for k in vehicles:
        for t in trips:
            # Each trip must have exactly one product and one start depot if it is active.
            m.addConstr(quicksum(product[k, t, p] for p in products) == active[k, t], name=f"one_product[{k},{t}]")
            m.addConstr(quicksum(start_depot[k, t, d] for d in depots) == active[k, t],
                        name=f"one_start_depot[{k},{t}]")
            if t > 0:
                # Enforce that trips are ordered: if trip t is active, then trip t-1 must also be active.
                m.addConstr(active[k, t] <= active[k, t - 1], name=f"ordered_trips[{k},{t}]")

            if t < max_trips_per_vehicle - 1:
                # if trip t is active and trip t+1 is not active, then trip t is the last trip for vehicle k.
                m.addConstr(last_trip[k, t] == active[k, t] - active[k, t + 1], name=f"last_trip[{k},{t}]")
            else:
                # the last trip for vehicle k is the last trip in the horizon if it is active.
                m.addConstr(last_trip[k, t] == active[k, t], name=f"last_trip[{k},{t}]")

    # Route flow for each mini-route.
    for k in vehicles:
        for t in trips:
            for d in depots:
                # If trip t starts at depot d, then the vehicle must leave depot d and enter the next trip's start depot (if any).
                m.addConstr(quicksum(arc[k, t, d, j] for j in station_nodes) == start_depot[k, t, d],
                            name=f"leave_start_depot[{k},{t},{d}]")
                next_start = start_depot[k, t + 1, d] if t < max_trips_per_vehicle - 1 else 0
                m.addConstr(quicksum(arc[k, t, i, d] for i in station_nodes) == next_start,
                            name=f"enter_next_start_depot[{k},{t},{d}]")
            # Each trip must return to the garage from exactly one station if it is the last trip for vehicle k.
            m.addConstr(
                quicksum(garage_return[k, t, s] for s in stations) == last_trip[k, t],
                name=f"return_to_garage[{k},{t}]",
            )

            for s in stations:
                node = station_node(s)
                m.addConstr(quicksum(arc[k, t, i, node] for i in route_nodes if i != node) == visit[k, t, s],
                            name=f"station_in[{k},{t},{s}]")
                m.addConstr(
                    quicksum(arc[k, t, node, j] for j in route_nodes if j != node)
                    + garage_return[k, t, s]
                    == visit[k, t, s],
                    name=f"station_out[{k},{t},{s}]",
                )

                demanded_products = [p for p in products if instance.stations[s].demand[p] > EPSILON]
                if demanded_products:
                    m.addConstr(visit[k, t, s] <= quicksum(product[k, t, p] for p in demanded_products),
                                name=f"visit_product_match[{k},{t},{s}]")
                else:
                    m.addConstr(visit[k, t, s] == 0, name=f"no_demand_visit[{k},{t},{s}]")

                for p in products:
                    m.addConstr(visit_product[k, t, s, p] <= visit[k, t, s],
                                name=f"visit_product_visit[{k},{t},{s},{p}]")
                    m.addConstr(visit_product[k, t, s, p] <= product[k, t, p],
                                name=f"visit_product_product[{k},{t},{s},{p}]")
                    m.addConstr(visit_product[k, t, s, p] >= visit[k, t, s] + product[k, t, p] - 1,
                                name=f"visit_product_and[{k},{t},{s},{p}]")
                    # Instance quantities use integer units.  Requiring at least
                    # one unit prevents zero-load visits and artificial trips
                    # inserted solely to alter the changeover sequence.
                    # m.addConstr(quantity[k, t, s, p] >= visit_product[k, t, s, p],
                    #             name=f"positive_delivery[{k},{t},{s},{p}]")

    for k in vehicles:
        for s in stations:
            for p in products:
                m.addConstr(
                    quicksum(visit_product[k, t, s, p] for t in trips) <= 1,
                    name=f"one_visit_per_vehicle_station_product[{k},{s},{p}]",
                )

    # Quantity, demand satisfaction, and truck capacity.
    for s in stations:
        for p in products:
            demand = instance.stations[s].demand[p]
            if demand <= EPSILON:
                for k in vehicles:
                    for t in trips:
                        m.addConstr(quantity[k, t, s, p] == 0, name=f"zero_quantity[{k},{t},{s},{p}]")
                continue

            m.addConstr(
                quicksum(quantity[k, t, s, p] for k in vehicles for t in trips) == demand,
                name=f"demand[{s},{p}]",
            )
            for k in vehicles:
                for t in trips:
                    m.addConstr(quantity[k, t, s, p] <= demand * product[k, t, p],
                                name=f"quantity_product[{k},{t},{s},{p}]")
                    m.addConstr(quantity[k, t, s, p] <= demand * visit[k, t, s],
                                name=f"quantity_visit[{k},{t},{s},{p}]")

    for k in vehicles:
        for t in trips:
            m.addConstr(
                quicksum(quantity[k, t, s, p] for s in stations for p in products)
                <= instance.vehicles[k].capacity * active[k, t],
                name=f"capacity[{k},{t}]",
            )

    # Account for the product volume loaded from each selected start depot.
    for k in vehicles:
        max_load = instance.vehicles[k].capacity
        for t in trips:
            for p in products:
                trip_product_load = quicksum(quantity[k, t, s, p] for s in stations)
                for d in depots:
                    m.addConstr(depot_load[k, t, d, p] <= max_load * start_depot[k, t, d],
                                name=f"depot_load_start[{k},{t},{d},{p}]")
                    m.addConstr(depot_load[k, t, d, p] <= trip_product_load,
                                name=f"depot_load_trip_ub[{k},{t},{d},{p}]")
                    m.addConstr(depot_load[k, t, d, p] >= trip_product_load - max_load * (1 - start_depot[k, t, d]),
                                name=f"depot_load_trip_lb[{k},{t},{d},{p}]")

    for d in depots:
        for p in products:
            m.addConstr(
                quicksum(depot_load[k, t, d, p] for k in vehicles for t in trips)
                <= instance.depots[d].stocks[p],
                name=f"stock[{d},{p}]",
            )

    # MTZ station ordering removes disconnected station subtours.
    for k in vehicles:
        for t in trips:
            for s in stations:
                m.addConstr(order[k, t, s] <= n_station_nodes * visit[k, t, s], name=f"order_ub[{k},{t},{s}]")
                m.addConstr(order[k, t, s] >= visit[k, t, s], name=f"order_lb[{k},{t},{s}]")
            for i in stations:
                for j in stations:
                    if i == j:
                        continue
                    m.addConstr(
                        order[k, t, i] - order[k, t, j]
                        + n_station_nodes * arc[k, t, station_node(i), station_node(j)]
                        <= n_station_nodes - 1,
                        name=f"mtz[{k},{t},{i},{j}]",
                    )

    # Consecutive trip changeovers.  The route of trip t already terminates at
    # the loading depot selected for trip t+1, so no empty depot transfer exists.
    for k in vehicles:
        for t in range(max_trips_per_vehicle - 1):
            for p in products:
                for p2 in products:
                    m.addConstr(change[k, t, p, p2] <= product[k, t, p], name=f"change_prev[{k},{t},{p},{p2}]")
                    m.addConstr(change[k, t, p, p2] <= product[k, t + 1, p2],
                                name=f"change_next[{k},{t},{p},{p2}]")
                    m.addConstr(change[k, t, p, p2] >= product[k, t, p] + product[k, t + 1, p2] - 1,
                                name=f"change_and[{k},{t},{p},{p2}]")

    travel_cost = quicksum(
        _distance(route_node(i), route_node(j)) * arc[k, t, i, j]
        for k in vehicles
        for t in trips
        for i, j in allowed_arcs
    )

    garage_start_cost = quicksum(
        _distance(instance.vehicles[k].start_g, instance.depots[d]) * start_depot[k, 0, d]
        for k in vehicles
        for d in depots
    )

    garage_return_cost = quicksum(
        _distance(instance.stations[s], instance.vehicles[k].start_g) * garage_return[k, t, s]
        for k in vehicles
        for t in trips
        for s in stations
    )

    initial_changeover_cost = quicksum(
        instance.changeover_cost[instance.vehicles[k].init_prod - 1][p] * product[k, 0, p]
        for k in vehicles
        for p in products
    )

    trip_changeover_cost = quicksum(
        instance.changeover_cost[p][p2] * change[k, t, p, p2]
        for k in vehicles
        for t in range(max_trips_per_vehicle - 1)
        for p in products
        for p2 in products
    )

    m.setObjective(
        travel_cost
        + garage_start_cost
        + garage_return_cost
        + initial_changeover_cost
        + trip_changeover_cost,
        GRB.MINIMIZE,
    )

    m.optimize()

    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        print(f"No feasible solution found. Gurobi status: {m.status}")
        return None

    if m.solCount == 0:
        print(f"No incumbent solution found. Gurobi status: {m.status}")
        return None

    routes = []

    def node_label(node_idx: int) -> str:
        if node_idx < n_depot_nodes:
            return f"D{instance.depots[node_idx].id}"
        return f"S{instance.stations[node_idx - station_offset].id}"

    def selected_route_nodes(k: int, t: int, start: int) -> list[str]:
        sequence = [node_label(start)]
        current = start
        used = set()
        while True:
            next_nodes = [
                j for i, j in allowed_arcs
                if i == current and arc[k, t, i, j].X > 0.5 and (i, j) not in used
            ]
            if not next_nodes:
                break
            next_node = next_nodes[0]
            used.add((current, next_node))
            sequence.append(node_label(next_node))
            if next_node < n_depot_nodes:
                break
            current = next_node
        return sequence

    for k in vehicles:
        for t in trips:
            if active[k, t].X <= 0.5:
                continue
            selected_product = next(p for p in products if product[k, t, p].X > 0.5)
            selected_start = next(d for d in depots if start_depot[k, t, d].X > 0.5)
            delivered = [
                {
                    "station": instance.stations[s].id,
                    "product": selected_product + 1,
                    "quantity": quantity[k, t, s, selected_product].X,
                }
                for s in stations
                if quantity[k, t, s, selected_product].X > EPSILON
            ]
            routes.append(
                {
                    "vehicle": instance.vehicles[k].id,
                    "trip": t + 1,
                    "product": selected_product + 1,
                    "start_depot": instance.depots[selected_start].id,
                    "path": selected_route_nodes(k, t, selected_start),
                    "deliveries": delivered,
                }
            )

    print(f"Solution found with objective value: {m.ObjVal}")
    return MilpSolution(
        objective=float(m.ObjVal),
        best_bound=float(m.ObjBound),
        mip_gap=float(m.MIPGap),
        node_count=float(m.NodeCount),
        solver_runtime=float(m.Runtime),
        status=m.Status,
        routes=routes,
    )


if __name__ == "__main__":
    filename = WITH_CHANGEOVER_INSTANCES_DIR / "MPVRP_003_s37_d2_p2.dat"
    instance = MPVRPInstance.read(filename)
    start_time = time.perf_counter()
    sol = solve_milp(
        instance= instance,
        time_limit=300
    )
    end_time = time.perf_counter()
    if sol:
        write_solution(
            instance=instance,
            routes=sol.routes,
            resolution_time=end_time - start_time
        )
