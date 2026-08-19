# Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Costs

## 1. Context and motivation

Efficient supply-chain management relies on coordinated transportation strategies that ensure timely product distribution while minimizing operational costs. In industries such as petroleum distribution, chemical manufacturing, food distribution, agriculture, pharmaceuticals, and waste collection, a shared fleet may transport several product types from multiple depots to geographically dispersed customers.

Using the same vehicle for successive products can improve fleet utilization, but it may also require product-specific preparation before the next trip. These operations consume money, labor, equipment, and time. Route planning must therefore account for both geographical efficiency and the operational consequences of changing the product assigned to a vehicle.

The **Multi-Product Vehicle Routing Problem with Split Deliveries and Changeover Costs (MPVRP-CC)** determines vehicle routes, delivered quantities, depot assignments, and product sequences that satisfy all customer demands at minimum total cost.

The problem is industry-independent. Petroleum distribution is one relevant application, but it is only one example of the broader planning setting.

## 2. Logistics network

The problem is defined by the following sets:

- **K**: heterogeneous vehicles, each with a capacity, a home garage, and an initial product configuration;
- **P**: products to distribute;
- **G**: garages from which vehicles depart and to which they return;
- **D**: depots where products are stocked and loaded;
- **S**: customer locations with a demand for one or more products.

Every depot, garage, and customer has a geographical position. Transportation costs are based on the distance between locations. Each depot holds a finite stock of every product, and each vehicle can carry at most its stated capacity.

## 3. Vehicle operations

A vehicle route starts at its assigned garage, contains one or more delivery trips, and ends at the same garage:

```text
Garage → [Depot → Customers → Depot] ... → Garage
```

Each depot-to-customer cycle is called a **mini-route** or **trip**. During one trip, a vehicle:

1. travels to a depot;
2. is prepared and loaded with exactly one product;
3. visits one or more customers requiring that product;
4. returns to a depot, either to begin another trip or to return to its garage.

A vehicle carries only one product during a trip. It may nevertheless carry different products on successive trips.

## 4. Changeover costs

A **product transition** occurs before each active trip. A transition between
different products is a changeover; retaining the same product still incurs a
smaller preparation and loading cost. The transition cost is an aggregate
operational cost, not merely a tank-cleaning cost.

Depending on the application, it may represent:

- cleaning, purging, washing, drying, or decontamination;
- loading-related preparation and product-handling operations;
- equipment, tank, compartment, hose, or temperature reconfiguration;
- quality-control, safety, inspection, and certification procedures;
- labor and consumable materials;
- setup delays, vehicle downtime, and the associated loss of availability;
- administrative or coordination activities required before the next trip.

These costs are represented by a directed product-to-product matrix. A transition from product `p` to product `q` may have a different cost from the reverse transition. Diagonal entries are positive and sampled from the `low` range to represent preparation when the same product is retained. Off-diagonal entries use the selected normal, high, or mixed regime.

The initial configuration of each vehicle is also considered. Its first active
trip incurs the corresponding matrix cost whether it retains or changes the
initial product.

## 5. Split deliveries

A customer’s demand for a product may exceed one vehicle’s capacity or may be more efficiently distributed among several vehicles. The model therefore permits **split deliveries**: the demand of a customer-product pair can be divided among multiple vehicles.

The complete demand must still be delivered exactly. In the implemented formulation, a given vehicle can serve the same customer-product pair at most once over its trips, so a split is performed across distinct vehicles.

## 6. Objective

The objective is to minimize the sum of:

- travel distance within delivery trips;
- initial and inter-trip changeover costs.

This objective captures the trade-off at the center of the problem. A geographically shorter plan may require expensive product changes, while a longer route may preserve a vehicle’s current configuration and reduce preparation costs.

## 7. Main constraints

A feasible solution must satisfy the following requirements:

- every customer demand is delivered exactly;
- every vehicle load respects its capacity;
- the quantity loaded from a depot does not exceed its available stock;
- each active trip selects exactly one product and begins and ends at a depot;
- a station is visited during a trip only when it demands the product carried;
- every used vehicle starts and ends at its assigned garage;
- active trips are consecutive and form connected routes without isolated subtours.

The current problem does not include delivery time windows, explicit service durations, or depot replenishment. Distances are Euclidean, and every location is assumed to be accessible.

## 8. Comparative experiment

The repository provides two paired benchmark scenarios:

- **with changeover costs**: the original product-transition matrices are retained;
- **without changeover costs**: the same instances are used, but every transition cost is set to zero.

Within each pair, the UUID, fleet, locations, stocks, demands, capacities, and initial vehicle products are identical. Comparing the resulting solutions isolates the influence of changeover costs on vehicle utilization, product sequences, depot choices, route geometry, and total distance.
