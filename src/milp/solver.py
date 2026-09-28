from __future__ import annotations

import time
from math import ceil

from gurobipy import GRB, Model, quicksum

from paths import CHANGEOVER_INSTANCES_DIR
from milp.io.solution import write_solution
from milp.models import MPVRPInstance, MPVRPNode, MilpSolution

TIME_LIMIT = 190
EPSILON = 1e-6


def _distance(origin: MPVRPNode, destination: MPVRPNode) -> int:
    return int(round(origin.distance(destination)))


def _maximum_uniform_trip_bound(instance: MPVRPInstance) -> int:
    total_demand = sum(request.demand for request in instance.requests)
    fleet_capacity = sum(vehicle.capacity for vehicle in instance.vehicles)
    if total_demand <= EPSILON:
        return 0
    if fleet_capacity <= EPSILON:
        raise ValueError("The fleet has no usable capacity.")
    return max(ceil(total_demand / fleet_capacity) + 1, instance.n_prods)


def _validate_trip_bound(instance: MPVRPInstance, max_trips_per_vehicle: int) -> None:
    if max_trips_per_vehicle < 1:
        raise ValueError("max_trips_per_vehicle must be at least 1.")

    total_demand = sum(request.demand for request in instance.requests)
    total_capacity = max_trips_per_vehicle * sum(
        vehicle.capacity for vehicle in instance.vehicles
    )
    if total_capacity + EPSILON < total_demand:
        default_bound = _maximum_uniform_trip_bound(instance)
        raise ValueError(
            "max_trips_per_vehicle is too small to satisfy total demand: "
            f"capacity={total_capacity:.1f}, demand={total_demand:.1f}. "
            f"The default horizon is {default_bound} trips per vehicle."
        )


def solve_milp(
    instance: MPVRPInstance,
    max_trips_per_vehicle: int | None = None,
    time_limit: int = TIME_LIMIT,
    output: bool = True,
) -> MilpSolution | None:
    """
    Solve the bounded trip MILP for MPVRP-CC.

    Parameters
    ----------
    instance : MPVRPInstance
        The instance to solve.
    max_trips_per_vehicle : int, optional
        The maximum number of trips allowed per vehicle. If None, a default
        bound is computed based on total demand and fleet capacity.
    time_limit : int, optional
        The time limit for the solver in seconds. Default is 190 seconds.
    output : bool, optional
        If True, enables solver output. Default is True.

    Returns
    -------
    MilpSolution or None
        The solution object containing the objective value, best bound, MIP gap,
        node count, solver runtime, status, and routes. Returns None if no feasible
        solution is found within the time limit.    
    """
   
    if not instance.requests:
        raise ValueError("The instance has no positive-demand requests.")
    if not instance.depot_products:
        raise ValueError("The instance has no positive-stock depot-product nodes.")

    if max_trips_per_vehicle is None:
        max_trips_per_vehicle = _maximum_uniform_trip_bound(instance)
    _validate_trip_bound(instance, max_trips_per_vehicle)

    vehicles = range(instance.n_vehicles)
    trips = range(max_trips_per_vehicle)
    products = range(1, instance.n_prods + 1)
    depot_products = range(instance.n_depot_products)
    requests = range(instance.n_requests)

    n_request_nodes = instance.n_requests
    depot_node_ids = [node.global_id for node in instance.depot_products]
    request_node_ids = [node.global_id for node in instance.requests]
    route_nodes = [*depot_node_ids, *request_node_ids]
    nodes_by_global_id = {node.global_id: node for node in instance.nodes}
    request_indices_by_global_id = {
        node.global_id: index for index, node in enumerate(instance.requests)
    }

    def request_node(request_index: int) -> int:
        return instance.requests[request_index].global_id

    def route_node(node_index: int) -> MPVRPNode:
        return nodes_by_global_id[node_index]

    def request_index(node_index: int) -> int:
        return request_indices_by_global_id[node_index]

    # A trip leaves a depot-product node for a compatible request, follows
    # requests of that product, then reaches the next trip's depot-product.
    depot_request_arcs = [
        (instance.depot_products[d].global_id, request_node(r))
        for d in depot_products
        for r in requests
        if instance.depot_products[d].product_id == instance.requests[r].product_id
    ]
    request_request_arcs = [
        (request_node(i), request_node(j))
        for i in requests
        for j in requests
        if i != j
        and instance.requests[i].product_id == instance.requests[j].product_id
    ]
    request_depot_arcs = [
        (request_node(r), instance.depot_products[d].global_id)
        for r in requests
        for d in depot_products
    ]
    allowed_arcs = depot_request_arcs + request_request_arcs + request_depot_arcs

    outgoing: dict[int, list[int]] = {node: [] for node in route_nodes}
    incoming: dict[int, list[int]] = {node: [] for node in route_nodes}
    for origin, destination in allowed_arcs:
        outgoing[origin].append(destination)
        incoming[destination].append(origin)

    model = Model(f"{instance.uuid}_expanded_graph_mip")
    model.setParam("OutputFlag", 1 if output else 0)
    model.setParam("TimeLimit", time_limit)

    active = model.addVars(vehicles, trips, vtype=GRB.BINARY, name="active")
    product = model.addVars(vehicles, trips, products, vtype=GRB.BINARY, name="product")
    start = model.addVars(vehicles, trips, depot_products, vtype=GRB.BINARY, name="start")
    visit = model.addVars(vehicles, trips, requests, vtype=GRB.BINARY, name="visit")
    quantity = model.addVars(vehicles, trips, requests, lb=0, vtype=GRB.INTEGER, name="quantity")
    load = model.addVars(vehicles, trips, depot_products, lb=0, vtype=GRB.INTEGER, name="load")
    arc = model.addVars(
        ((k, t, i, j) for k in vehicles for t in trips for i, j in allowed_arcs),
        vtype=GRB.BINARY,
        name="arc",
    )
    order = model.addVars(vehicles, trips, requests, lb=0, ub=n_request_nodes, vtype=GRB.CONTINUOUS, name="order")
    last_trip = model.addVars(vehicles, trips, vtype=GRB.BINARY, name="last_trip")
    garage_return = model.addVars(vehicles, trips, requests, vtype=GRB.BINARY, name="garage_return")
    transition_trips = range(max_trips_per_vehicle - 1)
    change = model.addVars(vehicles, transition_trips, products, products,
                           vtype=GRB.BINARY, name="change")

    # Active trips form a prefix. Selecting one depot-product node fixes the
    # trip product, so no separate loading-depot/product compatibility is needed.
    for k in vehicles:
        for t in trips:
            selected_starts = quicksum(start[k, t, d] for d in depot_products)
            model.addConstr(selected_starts == active[k, t], name=f"one_start[{k},{t}]")

            for p in products:
                matching_starts = quicksum(
                    start[k, t, d] for d in depot_products
                    if instance.depot_products[d].product_id == p
                )
                model.addConstr(product[k, t, p] == matching_starts, name=f"selected_product[{k},{t},{p}]")

            if t > 0:
                model.addConstr(active[k, t] <= active[k, t - 1], name=f"ordered_trips[{k},{t}]")

            if t < max_trips_per_vehicle - 1:
                model.addConstr(
                    last_trip[k, t] == active[k, t] - active[k, t + 1],
                    name=f"last_trip[{k},{t}]",
                )
            else:
                model.addConstr(last_trip[k, t] == active[k, t], name=f"last_trip[{k},{t}]")

    # Each active mini-route begins at its selected depot-product node and
    # either enters the next selected node or returns home after its last request.
    for k in vehicles:
        for t in trips:
            for d in depot_products:
                depot_node = instance.depot_products[d].global_id
                departures = quicksum(arc[k, t, depot_node, j] for j in outgoing[depot_node])
                model.addConstr(departures == start[k, t, d], name=f"leave_start[{k},{t},{d}]")

                next_start = start[k, t + 1, d] if t + 1 < max_trips_per_vehicle else 0
                arrivals = quicksum(arc[k, t, i, depot_node] for i in incoming[depot_node])
                model.addConstr(arrivals == next_start, name=f"enter_next_start[{k},{t},{d}]")

            returns_home = quicksum(garage_return[k, t, r] for r in requests)
            model.addConstr(returns_home == last_trip[k, t], name=f"return_home[{k},{t}]")

            for r in requests:
                node = request_node(r)
                arrivals = quicksum(arc[k, t, i, node] for i in incoming[node])
                departures = quicksum(arc[k, t, node, j] for j in outgoing[node])
                model.addConstr(arrivals == visit[k, t, r], name=f"request_in[{k},{t},{r}]")
                model.addConstr(
                    departures + garage_return[k, t, r] == visit[k, t, r],
                    name=f"request_out[{k},{t},{r}]",
                )
                model.addConstr(
                    visit[k, t, r] <= product[k, t, instance.requests[r].product_id],
                    name=f"request_product[{k},{t},{r}]",
                )

    # Demand is exact, every selected visit delivers a positive integer amount,
    # and a vehicle can serve a request at most once over its complete schedule.
    for r in requests:
        demand = instance.requests[r].demand
        delivered = quicksum(quantity[k, t, r] for k in vehicles for t in trips)
        model.addConstr(delivered == demand, name=f"demand[{r}]")

        for k in vehicles:
            vehicle_visits = quicksum(visit[k, t, r] for t in trips)
            model.addConstr(vehicle_visits <= 1, name=f"one_visit_per_vehicle_request[{k},{r}]")

            for t in trips:
                # model.addConstr(quantity[k, t, r] >= visit[k, t, r],
                #                 name=f"positive_delivery[{k},{t},{r}]")
                model.addConstr(quantity[k, t, r] <= demand * visit[k, t, r],
                                name=f"quantity_visit[{k},{t},{r}]")

    for k in vehicles:
        capacity = instance.vehicles[k].capacity
        for t in trips:
            trip_quantity = quicksum(quantity[k, t, r] for r in requests)
            model.addConstr(trip_quantity <= capacity * active[k, t], name=f"capacity[{k},{t}]")

            for d in depot_products:
                model.addConstr(load[k, t, d] <= capacity * start[k, t, d],
                                name=f"load_start[{k},{t},{d}]")
                model.addConstr(load[k, t, d] <= trip_quantity,
                                name=f"load_quantity_ub[{k},{t},{d}]")
                model.addConstr(
                    load[k, t, d] >= trip_quantity - capacity * (1 - start[k, t, d]),
                    name=f"load_quantity_lb[{k},{t},{d}]",
                )

    for d in depot_products:
        total_load = quicksum(load[k, t, d] for k in vehicles for t in trips)
        model.addConstr(
            total_load <= instance.depot_products[d].stock,
            name=f"stock[{d}]",
        )

    # MTZ ordering excludes disconnected cycles among request nodes.
    for k in vehicles:
        for t in trips:
            for r in requests:
                model.addConstr(order[k, t, r] <= n_request_nodes * visit[k, t, r],
                                name=f"order_ub[{k},{t},{r}]")
                model.addConstr(order[k, t, r] >= visit[k, t, r], name=f"order_lb[{k},{t},{r}]")

            for i, j in request_request_arcs:
                r_i = request_index(i)
                r_j = request_index(j)
                model.addConstr(
                    order[k, t, r_i] - order[k, t, r_j]
                    + n_request_nodes * arc[k, t, i, j] <= n_request_nodes - 1,
                    name=f"mtz[{k},{t},{r_i},{r_j}]",
                )

    for k in vehicles:
        for t in transition_trips:
            for previous_product in products:
                for next_product in products:
                    transition = change[k, t, previous_product, next_product]
                    suffix = f"[{k},{t},{previous_product},{next_product}]"
                    model.addConstr(transition <= product[k, t, previous_product],
                                    name=f"change_previous{suffix}")
                    model.addConstr(transition <= product[k, t + 1, next_product],
                                    name=f"change_next{suffix}")
                    model.addConstr(
                        transition >= product[k, t, previous_product]
                        + product[k, t + 1, next_product] - 1,
                        name=f"change_and{suffix}",
                    )

    travel_cost = quicksum(
        _distance(route_node(i), route_node(j)) * arc[k, t, i, j]
        for k in vehicles
        for t in trips
        for i, j in allowed_arcs
    )
    garage_start_cost = quicksum(
        _distance(instance.vehicles[k].start_g, instance.depot_products[d])
        * start[k, 0, d]
        for k in vehicles
        for d in depot_products
    )
    garage_return_cost = quicksum(
        _distance(instance.requests[r], instance.vehicles[k].start_g)
        * garage_return[k, t, r]
        for k in vehicles
        for t in trips
        for r in requests
    )
    initial_changeover_cost = quicksum(
        instance.changeover_cost[instance.vehicles[k].init_prod - 1][p - 1]
        * product[k, 0, p]
        for k in vehicles
        for p in products
    )
    trip_changeover_cost = quicksum(
        instance.changeover_cost[p1 - 1][p2 - 1]
        * change[k, t, p1, p2]
        for k in vehicles
        for t in transition_trips
        for p1 in products
        for p2 in products
    )
    model.setObjective(
        travel_cost
        + garage_start_cost
        + garage_return_cost
        + initial_changeover_cost
        + trip_changeover_cost,
        GRB.MINIMIZE,
    )

    model.optimize()
    if model.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or model.solCount == 0:
        print(f"No feasible solution found. Gurobi status: {model.status}")
        return None

    def node_label(node_index: int) -> str:
        node = nodes_by_global_id[node_index]
        if node_index in depot_node_ids:
            return f"D{node.id}"
        return f"S{node.id}"

    def selected_route_nodes(k: int, t: int, selected_start: int) -> list[str]:
        sequence = [node_label(selected_start)]
        current = selected_start
        used: set[tuple[int, int]] = set()
        while True:
            next_nodes = [
                destination
                for destination in outgoing[current]
                if arc[k, t, current, destination].X > 0.5
                and (current, destination) not in used
            ]
            if not next_nodes:
                break
            destination = next_nodes[0]
            used.add((current, destination))
            sequence.append(node_label(destination))
            if destination in depot_node_ids:
                break
            current = destination
        return sequence

    routes: list[dict] = []
    for k in vehicles:
        for t in trips:
            if active[k, t].X <= 0.5:
                continue
            selected_start = next(
                d for d in depot_products if start[k, t, d].X > 0.5
            )
            selected_product = instance.depot_products[selected_start].product_id
            selected_start_node = instance.depot_products[selected_start].global_id
            routes.append(
                {
                    "vehicle": instance.vehicles[k].id,
                    "trip": t + 1,
                    "product": selected_product,
                    "start_depot": instance.depot_products[selected_start].id,
                    "path": selected_route_nodes(k, t, selected_start_node),
                    "deliveries": [
                        {
                            "station": instance.requests[r].id,
                            "product": selected_product,
                            "quantity": quantity[k, t, r].X,
                        }
                        for r in requests
                        if quantity[k, t, r].X > EPSILON
                    ],
                }
            )

    print(f"Solution found with objective value: {model.ObjVal}")
    return MilpSolution(
        objective=float(model.ObjVal),
        best_bound=float(model.ObjBound),
        mip_gap=float(model.MIPGap),
        node_count=float(model.NodeCount),
        solver_runtime=float(model.Runtime),
        status=model.Status,
        routes=routes,
    )


if __name__ == "__main__":
    filename = CHANGEOVER_INSTANCES_DIR / "MPVRP_003_s37_d2_p2.dat"
    parsed_instance = MPVRPInstance.read(filename)
    start_time = time.perf_counter()
    solution = solve_milp(parsed_instance, time_limit=300)
    if solution:
        write_solution(
            instance=parsed_instance,
            routes=solution.routes,
            resolution_time=solution.solver_runtime,
        )
    print(f"Elapsed time: {time.perf_counter() - start_time:.3f}s")
