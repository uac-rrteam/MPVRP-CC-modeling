# Instance Format Specification

## 1. Filename

Use:

```text
MPVRP_A_B_sC_dD_pE.dat
```

| Field | Meaning |
| --- | --- |
| `A` | Size category: `S`, `M`, or `L` |
| `B` | Instance number, usually three digits such as `001` |
| `C` | Number of service stations |
| `D` | Number of depots |
| `E` | Number of products |

Example:

```text
MPVRP_S_001_s9_d1_p2.dat
```

## 2. Parser Rules

The LP parser tokenizes the complete file. To stay compatible:

- The first non-empty line must be the UUID comment line.
- Do not add any other comment line anywhere in the file.
- Blank lines should be avoided.
- Values may be separated by spaces or tabs.
- Every numeric value stored in an instance must be an integer. Decimal tokens
  are rejected by the parser.
- Entity IDs are one-based and contiguous: `1, ..., n`.
- Product IDs are one-based: `1, ..., NbProducts`.

## 3. File Blocks

The block order is fixed:

```text
# <uuid>
NbProducts NbDepots NbGarages NbStations NbVehicles
<NbProducts rows of transition costs>
<NbVehicles rows of vehicles>
<NbDepots rows of depots>
<NbGarages rows of garages>
<NbStations rows of stations>
```

The expected number of data lines after the UUID line is:

```text
1 + NbProducts + NbVehicles + NbDepots + NbGarages + NbStations
```

## 4. UUID

Line 1 contains a UUID comment:

```text
# c01ab718-9a2c-4a7d-bb95-f37e2a389409
```

This line is mandatory for compatibility with `MPVRPInstance.read()`.

## 5. Global Parameters

Line 2 contains five positive integers:

```text
NbProducts NbDepots NbGarages NbStations NbVehicles
```

Example:

```text
3 2 1 20 5
```

## 6. Transition Cost Matrix

Next come `NbProducts` rows, each with `NbProducts` integer values:

```text
Cost_P1_to_P1 Cost_P1_to_P2 ...
Cost_P2_to_P1 Cost_P2_to_P2 ...
...
```

Requirements:

- Costs must be non-negative integers.
- Diagonal entries represent same-product preparation and use the `low` range.
- In the explicit no-cost control scenario, the complete matrix is zeroed.
- The matrix may be asymmetric. The solver uses
  `cost[previous_product - 1][next_product - 1]`.

## 7. Vehicles

Next come `NbVehicles` rows:

```text
ID Capacity HomeGarage InitialProduct
```

Requirements:

- `ID` must be unique and contiguous in `[1, NbVehicles]`.
- `Capacity` must be strictly positive.
- `HomeGarage` must reference an existing garage ID.
- `InitialProduct` must be in `[1, NbProducts]`.

## 8. Depots

Next come `NbDepots` rows:

```text
ID X Y Stock_P1 Stock_P2 ... Stock_Pn
```

Requirements:

- `ID` must be unique and contiguous in `[1, NbDepots]`.
- Coordinates must be integers.
- Stocks must be non-negative integers.
- For each product, total depot stock must be at least total station demand.

## 9. Garages

Next come `NbGarages` rows:

```text
ID X Y
```

Requirements:

- `ID` must be unique and contiguous in `[1, NbGarages]`.
- Coordinates must be integers.

## 10. Service Stations

Next come `NbStations` rows:

```text
ID X Y Demand_P1 Demand_P2 ... Demand_Pn
```

Requirements:

- `ID` must be unique and contiguous in `[1, NbStations]`.
- Coordinates must be integers.
- Demands must be non-negative integers.
- Each station must have at least one positive demand.
- For LP compatibility, each station/product demand must not exceed the sum of all vehicle capacities. The LP allows split delivery across vehicles, but it limits a vehicle to at most one visit for the same station/product pair.

## 11. Complete Example

```text
# c01ab718-9a2c-4a7d-bb95-f37e2a389409
2 1 2 3 2
42 1018
1562 87
1 20000 1 1
2 20000 1 2
1 82 64 57914 82626
1 98 50
2 57 26
1 24 42 0 4278
2 4 38 1344 2350
3 57 31 0 2319
```

This instance has 2 products, 1 depot, 2 garages, 3 stations, and 2 vehicles.

`MPVRPInstance.dist_matrix` rounds Euclidean distances to the nearest integer
for direct use in an integer constraint-programming model. The MILP formulation
continues to compute exact Euclidean distances from the integer coordinates.
