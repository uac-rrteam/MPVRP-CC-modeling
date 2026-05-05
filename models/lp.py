#################################
#
# Linear programming model of Multi-Product
# Vehicule Routing Problem with Split-Delivery and Change-Over Costs
#
# @Author : Rosas Behoundja
# May 2026
#
#################################

from gurobipy import GRB, quicksum, Model

from utils.parser import DEFAULT_INSTANCE_PATH, MPVRPInstance

TIME_LIMIT = 600  # 1 minute


def solve_lp(instance: MPVRPInstance):
    model = instance.uuid + "_lp"
    m = Model(model)
    m.setParam('OutputFlag', 0)
    m.setParam('TimeLimit', TIME_LIMIT)

    # Create variables
    x = m.addVars(instance.n_vehicules, instance.n_stations, vtype=GRB.BINARY, name="x")
    q = m.addVars(instance.n_vehicules, instance.n_stations, instance.n_prods, vtype=GRB.CONTINUOUS, name="q")

    # Objective function
    m.setObjective(quicksum(instance.changeover_cost[p][p2] * x[v, s] for v in range(instance.n_vehicules) for s in
                            range(instance.n_stations) for p in range(instance.n_prods) for p2 in
                            range(instance.n_prods)), GRB.MINIMIZE)

    # Constraints
    for s in range(instance.n_stations):
        m.addConstr(quicksum(x[v, s] for v in range(instance.n_vehicules)) == 1)

    for v in range(instance.n_vehicules):
        for p in range(instance.n_prods):
            m.addConstr(quicksum(q[v, s, p] for s in range(instance.n_stations)) <= instance.vehicules[v].capacity)

    for v in range(instance.n_vehicules):
        for s in range(instance.n_stations):
            for p in range(instance.n_prods):
                m.addConstr(q[v, s, p] <= instance.stations[s].demand[p] * x[v, s])

    m.optimize()

    if m.status == GRB.OPTIMAL:
        print(f"Optimal solution found with objective value: {m.objVal}")
        return m.objVal
    else:
        print("No optimal solution found.")
        return None


if __name__ == "__main__":
    instance = MPVRPInstance.read(DEFAULT_INSTANCE_PATH)
    solve_lp(instance)
