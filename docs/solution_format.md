# Solution File Format

## 1. Naming the files

Solutions are plain-text files with the `.dat` extension. For the instance:

```text
MPVRP_001_s36_d8_p3.dat
```

the preferred solution name is:

```text
Sol_001_s36_d8_p3.dat
```

This is the canonical name generated and recognized by the repository tools. A submission archive may organize files in folders and may contain any subset of the instances from `001` to `100`. The platform identifies every recognized solution and evaluates it independently.

Submitting all 100 solutions at once is not required. For the final score, an absent solution, an unresolved solution, and an invalid solution are treated in the same way: the corresponding instance receives a penalty of `100000`.

## 2. Describing a vehicle schedule

Every used vehicle is represented by two matching lines. Leave an empty line before the next vehicle.

### Route line

```text
ID: Garage - Depot [Load] - Station (Delivery) - ... - Garage
```

This line follows the vehicle from departure to return:

- a **garage** is written with its identifier;
- a **depot** is followed by the quantity loaded in square brackets;
- a **station** is followed by the quantity delivered in parentheses.

Identifiers are local to their category. Depot 1, garage 1, and station 1 are therefore three different locations.

### Product and cost line

```text
ID: Product(CumulativeCost) - Product(CumulativeCost) - ...
```

This second line gives the vehicle's product configuration and cumulative transition cost at every step of the route. Product identifiers start at `0` in solution files and range from `0` to `NbProducts - 1`.

The cumulative cost annotation is part of the canonical repository format. Every product must be followed by the cumulative transition cost at that point, as in `0(42.00)`. The re-evaluation command uses these annotated entries when it rewrites a zero-cost solution with the cost-bearing matrix.

The first value is the vehicle's initial product configuration. At every depot, the next value is the product being loaded. This is also where a preparation and loading-related transition cost is added. The amount comes from the directed matrix using the previous configuration and the newly loaded product. It therefore applies before the first delivery trip as well as between later trips. Loading the same product again incurs the positive low cost on the matrix diagonal.

The route line contains the terminal return garage, while the product line omits that final garage entry. The last product configuration and cumulative cost are implicitly carried through to the return garage. Consequently, the product line has exactly one fewer element than the route line.

## 3. Example

```text
1: 1 - 1 [1344] - 2 (1344) - 1
1: 0(0.00) - 0(42.00) - 0(42.00)

2: 1 - 1 [8947] - 1 (4278) - 2 (2350) - 3 (2319) - 1
2: 1(0.00) - 1(87.00) - 1(87.00) - 1(87.00) - 1(87.00)
```

Here, vehicle 1 leaves garage 1, loads 1344 units of product 0 at depot 1, delivers them to station 2, and returns home. Vehicle 2 loads 8947 units of product 1, serves stations 1, 2, and 3, then returns to garage 1. Neither vehicle genuinely changes product, but their initial loading operations incur diagonal costs of `42` and `87`, for a total transition cost of `129`.

## 4. Summary metrics

After the last vehicle block, the canonical file ends with six summary lines:

```text
2
0
129.00
1385.07
Intel Core i7-10700K
0.245
```

They contain, in this order:

1. **Vehicles used** — the number of vehicles that perform at least one delivery.
2. **Product transitions** — the number of genuine product changes, excluding same-product loading operations.
3. **Total transition cost** — the sum of all preparation and loading-related transition costs.
4. **Total distance** — the Euclidean distance traveled by the complete fleet.
5. **Processor** — the processor used to produce the solution.
6. **Resolution time** — the computation time in seconds.

All six lines are required by the repository's solution reader and re-evaluation tools. The transition count records only changes between different products, whereas the total transition cost includes every charged loading operation, including a same-product diagonal cost.

## 5. Feasibility requirements

A valid solution must respect all of the following conditions:

- each vehicle appears at most once;
- every route starts and ends at that vehicle's home garage;
- each trip begins with a positive depot load and includes at least one delivery;
- a vehicle carries one product throughout a trip, with a new product selected only when loading at a depot;
- the quantity loaded for a trip equals the quantity delivered and does not exceed vehicle capacity;
- depot stocks remain non-negative;
- every station-product demand is met exactly;
- one vehicle serves a given station-product pair at most once across all its trips; it may revisit the same station only to deliver another product;
- the route itself respects all structural and operational constraints; cumulative costs and final metrics are recalculated by the platform.
