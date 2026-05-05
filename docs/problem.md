# Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Cost (MPVRP-CC)

*MPVRP-CC Team — January 25, 2026*

---

## 1. Introduction

The **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Cost (MPVRP-CC)** is a complex logistics optimization challenge. It aims to organize the efficient distribution of multiple product types (e.g., different fuels) from a set of depots to a network of service stations.

This documentation presents the MPVRP-CC, a variant of the classic vehicle routing problem applied to the distribution of petroleum products. It involves optimizing tanker truck routes that must deliver different types of fuels, taking into account the cleaning cost when a vehicle changes products.

---

## 2. Mathematical Notation

The problem is modeled on the following sets:

- **K**: Set of available trucks, K = {1, . . . , |K|}
- **P**: Set of products to distribute, P = {1, . . . , |P|}
- **G**: Set of garages (truck departure/arrival points), G = {1, . . . , |G|}
- **D**: Set of depots (loading points), D = {1, . . . , |D|}
- **S**: Set of service stations (customers), S = {1, . . . , |S|}

The logistics network connects these different sites. A distance matrix defines the separation between each pair of locations. Each service station expresses a specific demand for each product type. To meet this demand, a heterogeneous fleet of tanker trucks is deployed. Each vehicle has a defined loading capacity and is attached to a specific garage.

---

## 3. Operational Framework

Truck operations follow a rigorous structure:

> **Garage → [Depot → Customers]... → Garage**

### 3.1 Route Structure

A complete route must start and end at the vehicle's assigned garage. It consists of a succession of **mini-routes**.

A mini-route corresponds to a delivery cycle composed of three phases:

- **Loading**: The truck goes to a depot to load one (and only one) product type.
- **Delivery**: It then serves one or more service stations to deliver this product.
- **Return**: Once empty or the route is complete, it returns to a depot to reload or goes back to its garage.

### 3.2 Multi-Product Management

The particularity of this problem lies in product management:

- A truck can only transport **one product type at a time** (single or dedicated compartment).
- Each truck is **initially configured** for a given product.
- **Changeover cost**: It is possible to change products during a visit to the depot. However, this operation requires tank cleaning which incurs a specific cost. The optimization must therefore balance between making detours to keep the same product or paying this cost to change products on site.

---

## 4. Objectives and Constraints

### 4.1 Objective Function

The objective of MPVRP-CC is to determine the routes for the entire fleet in order to **minimize the total cost**, composed of:

- **Transportation cost** (proportional to the total distance traveled).
- **Total product changeover cost** (tank cleaning).

### 4.2 Constraints

A valid solution must strictly respect the following constraints:

- **Demand satisfaction**: All station demands, for all products, must be fully delivered.
- **Capacity**: The loaded quantity must never exceed the truck's maximum capacity.
- **Flow**: Each truck must end its day at its home garage.
- **Uniqueness**: A truck does not serve the same station multiple times for the same product during a single mini-route.

### Assumptions

> We assume that all depots have sufficient stock to satisfy all demands and that all sites are accessible without time constraints.