# Exact methods for VRPs related to MPVRP-CC

*Research report — 29 September 2026*

## Scope and the target problem

This report reviews exact methods that could inform a solver for the [MPVRP-CC problem](problem.md) and the existing [trip-indexed MILP](../src/milp/solver.py). “Exact” means that, given enough time and memory, the method can prove optimality or infeasibility for the model it actually solves. A time-limited run with a feasible solution and an open MIP gap has **not** proved optimality.

Your variant combines rules that the cited papers usually treat separately: heterogeneous vehicles with home garages and initial product configurations; loading at any stocked depot; one product per trip; several trips per vehicle; directed, positive loading-transition costs; integer split quantities across vehicles; and no second service of the same station-product request by the same vehicle. There are no time windows or trip-duration limits. A cited model is therefore a **starting point**, not a drop-in formulation.

The distinction most relevant to model design is the level of a decision variable:

| Representation | What one binary variable selects | How repeated loading is represented |
| --- | --- | --- |
| Trip-indexed arc MILP | An arc or visit in vehicle `k`'s trip slot `t` | Explicit `t` dimension and links between consecutive slots |
| Depot-return arc-flow MILP | An arc in a whole vehicle walk, possibly marked as a depot-return arc | Depot copies or special return arcs; connectivity/state need care |
| Trip-column model | One feasible loading trip | Separate assignment or linking model orders trips into vehicle schedules |
| Complete-schedule column model | One garage-to-garage vehicle workday | Trip sequence, products, and costs are already inside the column |

The [schedule-column explainer](schedule_columns.md) gives a worked example of the last row.

## 1. Compact trip-indexed MILPs: the closest path from your code

The present solver has binary trip activation, depot-product start, request visit, and arc variables indexed by `(vehicle, trip)`, plus integer delivery quantities and load variables. This is a standard style for multi-trip MILPs. Cueto and coauthors formulate a multi-trip, multi-depot VRP with time windows using vehicle/trip decisions and then develop a branch-and-cut procedure with valid inequalities. Their time constraints and one-service-per-customer assumption differ from yours, but the indexed-trip structure is relevant. [Cueto et al., *Networks* (2021)](https://onlinelibrary.wiley.com/doi/full/10.1002/net.22028).

Wang, Kinable, and van Woensel study a fuel replenishment problem that simultaneously has multiple trips, split deliveries, multiple products, and an exact MILP benchmark. It is perhaps the closest **application mix**. Their vehicles have compartments that can carry different products together, their loading is at a central depot, and their main computational method is a heuristic; these differences matter for transferring constraints or performance claims. [Wang et al., *Computers & Operations Research* (2020)](https://research.tue.nl/files/148678018/1_s2.0_S0305054820300216_main.pdf).

### A complete horizon for your model

Let `R` be the set of positive-demand station-product requests. If each active trip delivers a **positive integer quantity** to at least one request, and each vehicle may serve a request at most once over its schedule, then one vehicle can use no more than `|R|` trips. This is a safe finite horizon even when the current demand/fleet-capacity heuristic is too short. It may be much larger than the number of trips in a good solution.

For this proof to hold, enforce `quantity[k,t,r] ≥ visit[k,t,r]` (currently commented out), or otherwise forbid a zero-delivery visit/trip. Aggregate capacity alone is not enough to certify a smaller horizon because fleet capacities, products, requests, stocks, and the one-visit rule interact.

### MILP strengthening worth investigating

The following are **proposed adaptations**, not claims that one paper has proved them for MPVRP-CC:

1. **Break trip-slot symmetry.** Your active-prefix constraints are useful. Additional ordering of otherwise interchangeable trips may help, but must not exclude a cheaper product sequence because transition costs are directed.
2. **Tighten quantity links.** Enforce positive delivery on a visit and use `min(demand[r], capacity[k])` as the upper coefficient in `quantity ≤ M·visit`. Keep exact demand and depot-product stock balance.
3. **Strengthen connectivity.** Compare your MTZ constraints with single-commodity flow or lazy subtour cuts on each `(k,t)` route. A branch-and-cut separation procedure may improve LP bounds without adding all connectivity inequalities initially. Cueto et al. add routing-specific inequalities to their indexed model, while Archetti, Bianchessi, and Speranza use branch-and-cut for split deliveries in a different, single-trip setting. [Cueto et al.](https://onlinelibrary.wiley.com/doi/full/10.1002/net.22028), [Archetti et al. (2014)](https://research.vu.nl/en/publications/branch-and-cut-algorithms-for-the-split-delivery-vehicle-routing-/).
4. **Use valid demand-covering bounds carefully.** For a product `p`, at least `ceil(total demand of p / maximum vehicle capacity)` loading trips are required if all trips carry only `p`; stronger inequalities may account for heterogeneous capacities and stock. Such counts are valid as global lower bounds, but do not by themselves decide which vehicle or depot supplies a request.
5. **Feed feasible incumbents to Gurobi.** A constructive schedule can set `active`, `start`, `visit`, `quantity`, `arc`, `change`, and return variables. The solver can then focus on improving the bound and solution.

The advantage of this family is that it remains a single MILP and is closest to the working code. The main costs are many indexed arc variables, weak relaxations from big-M links and subtour constraints, and an explicit horizon even when it is mathematically safe.

## 2. Arc-flow MILPs that encode depot returns without trip slots

Neira, Aguayo, De la Fuente, and Klapp propose two compact integer programming models for a multi-trip VRP with time windows. One uses **multiple depot copies**; the other uses a **parallel arc between customer nodes** to represent an intermediate depot return. Their reported experiments favor these compact formulations over earlier formulations for their specific setting. [Neira et al., *Computers & Industrial Engineering* (2020)](https://www.sciencedirect.com/science/article/pii/S0360835220301339).

The parallel-arc idea is easy to visualize. For successive visits `i` and `j`, choose either:

```text
i ───────────────→ j                 continue the current trip
i → loading depot → j                end one trip, load, begin another
```

For your problem, a return arc would need to identify the **actual destination depot, the product loaded for the next trip, the stock consumed there, and the previous product configuration**. A single unlabeled return arc cannot calculate depot-specific travel or directed transition cost. Depot copies can carry that state more explicitly, but repeated visits to one physical depot still require a way to distinguish occurrences or a flow formulation that permits them without creating disconnected cycles.

Split quantities also complicate a customer-level arc-flow model: a station may have multiple products and may be visited by several vehicles, while a particular vehicle can serve each station-product only once. A request-node expansion and vehicle-indexed visit/quantity variables are natural adaptations. Ozbaygin, Karasan, and Yaman show why aggregating vehicle-indexed flow can admit undesirable exchanges of load between vehicles in split-delivery models; their exact approach repairs this through local vehicle-indexed extensions or node splitting. [Ozbaygin et al., *EURO Journal on Computational Optimization* (2018)](https://optimization-online.org/wp-content/uploads/2014/12/4687.pdf).

**Assessment:** promising if eliminating a `trip` dimension is essential, but it needs a new proof of vehicle-path connectivity, product-state consistency, capacity reset at every load, and no same-vehicle repeat service. It is not a small edit to the present MILP.

## 3. Route and schedule formulations: huge MILPs solved by column generation

A set-partitioning or set-covering formulation has one variable per feasible route or schedule. Because there are too many variables to enumerate, **column generation** solves an LP over a subset and uses a pricing problem to find improving routes. For an exact integer solution, pricing must be integrated into branch-and-bound, often with cuts: branch-and-price or branch-price-and-cut. These remain integer-programming methods, even though the master MILP is not written out explicitly in full.

Hernandez, Feillet, Giroudeau, and Naud compare two exact branch-and-price frameworks for a multi-trip VRP with time windows: columns can represent **complete consecutive-trip schedules** or **single trips**. Their experiments show that the single-trip approach was more effective on their small benchmark instances; this is evidence about their time-window problem, not a guarantee for MPVRP-CC. The comparison is directly relevant to deciding whether a column should be one trip or an entire workday. [Hernandez et al., *European Journal of Operational Research* (2016)](https://pure.etsmtl.ca/en/publications/branch-and-price-algorithms-for-the-solution-of-the-multi-trip-ve/).

Azi, Gendreau, and Potvin also use branch-and-price for multiple use of vehicles with time windows and revenue-based customer selection. Their set-packing objective and optional customer selection differ from your mandatory exact-demand constraints, but their use of resource-constrained pricing is relevant. [Azi et al., *European Journal of Operational Research* (2010)](https://ideas.repec.org/a/eee/ejores/v202y2010i3p756-763.html).

For **split deliveries**, Archetti, Bianchessi, and Speranza generate columns containing both routes and delivery quantities; their method is exact for the SDVRP they define. Desaulniers develops branch-price-and-cut for split deliveries with time windows. Both indicate that a route column may need quantity information, rather than just a binary indicator of visited customers. [Archetti et al., *Networks* (2011)](https://air.unimi.it/handle/2434/609837), [Desaulniers, *Operations Research* (2010)](https://ideas.repec.org/a/inm/oropre/v58y2010i1p179-192.html).

For your problem, complete-schedule columns automatically price the initial configuration, every subsequent loading, and the garage return. A trip-column master is potentially smaller in pricing state, but needs constraints or a second network to chain trips, track product transitions, and ensure that the same vehicle never repeats a request. The absence of time windows removes the scheduling conflict central to Hernandez et al., but it does **not** remove product state, stock, and split-quantity coupling.

**Assessment:** powerful for bounds and optimality proofs, but exact pricing for your combined rules is a substantial research implementation. A finite pool of generated schedules followed by a binary master is a practical heuristic and gives an upper bound; without exact pricing it does not certify a global lower bound.

## 4. Split-delivery branch-and-cut without multi-trip schedules

Archetti, Bianchessi, and Speranza present exact branch-and-cut methods for the classical split-delivery VRP using relaxations and cuts, with procedures to recover feasible solutions. Ozbaygin, Karasan, and Yaman present a vehicle-indexed flow formulation and exact approaches based on an aggregated relaxation plus repair of invalid vehicle-load exchanges. These are especially useful for understanding **quantity flow, vehicle identity, and cuts**. [Archetti et al. (2014)](https://research.vu.nl/en/publications/branch-and-cut-algorithms-for-the-split-delivery-vehicle-routing-/), [Ozbaygin et al. (2018)](https://optimization-online.org/wp-content/uploads/2014/12/4687.pdf).

Their classical SDVRP assumptions do not include your multiple loading trips, product-dependent depot stocks, or changeover matrix. In particular, a no-split simplification is not generally valid for the benchmark: one request may exceed every individual vehicle capacity. A split-delivery formulation adapted to your setting must preserve exact delivered quantities and the rule that the *same vehicle* can serve a request at most once.

## 5. A research direction map for this repository

| Direction | Exactness route | Main adaptation for MPVRP-CC | Likely implementation burden |
| --- | --- | --- | --- |
| Strengthen current trip-indexed MILP | Valid `|R|` horizon + Gurobi branch-and-bound/cut | Positive deliveries, robust connectivity, better bounds/incumbents | Lowest |
| New depot-return arc-flow MILP | Integer vehicle flow + state/route cuts | Product state, depot choice, stock, load resets, repeated visits | Medium to high |
| Complete-schedule branch-and-price | Exact pricing at every branch node | Multi-trip pricing with quantities and no repeated vehicle-request | Very high |
| Trip-column branch-and-price | Exact trip pricing plus exact chaining | Vehicle assignment, order, transitions, no repeat across trips | Very high |

### Recommended sequence

1. **Establish a correct MILP baseline.** Enforce positive delivery, use the provable `|R|` trip horizon when checking exactness, and compare objective values against the benchmark validator. Preserve solver lower bounds and MIP gaps. The current heuristic horizon can still be used for fast feasible searches, but not as a general optimality certificate.
2. **Measure the bottleneck.** Record model size, root LP bound, time to first feasible solution, final MIP gap, and whether the search is slowed mainly by weak bounds or by finding feasible solutions. This determines whether cuts, route generation, or stronger incumbents are the next useful step.
3. **Prototype depot-return arcs on a reduced case.** Start with one product, one depot, no split; then add product state, multi-depot loading, and split quantities. At each step, compare with the baseline on tiny instances where both can prove optimality.
4. **Prototype a schedule-pool master before exact pricing.** It tests whether whole-schedule decomposition improves incumbents or gives useful restricted-master structure. Only then tackle exact pricing and branching if proof quality is the research objective.

## 6. Reading list, ordered by usefulness here

1. [Wang, Kinable, and van Woensel (2020): fuel replenishment, MILP and column-generation bounds](https://research.tue.nl/files/148678018/1_s2.0_S0305054820300216_main.pdf). Closest combination of multi-trip, multi-product, and split delivery; note the compartment and central-depot differences.
2. [Neira et al. (2020): compact multi-trip integer formulations](https://www.sciencedirect.com/science/article/pii/S0360835220301339). Main source for depot-copy and parallel depot-return arc designs.
3. [Hernandez et al. (2016): complete-schedule versus single-trip columns](https://pure.etsmtl.ca/en/publications/branch-and-price-algorithms-for-the-solution-of-the-multi-trip-ve/). Direct comparison of the two decomposition choices.
4. [Cueto et al. (2021): multi-trip MILP and branch-and-cut](https://onlinelibrary.wiley.com/doi/full/10.1002/net.22028). Useful when improving an indexed MILP.
5. [Archetti, Bianchessi, and Speranza (2011): split-delivery columns with quantities](https://air.unimi.it/handle/2434/609837). Useful for delivery-amount pricing.
6. [Archetti, Bianchessi, and Speranza (2014): split-delivery branch-and-cut](https://research.vu.nl/en/publications/branch-and-cut-algorithms-for-the-split-delivery-vehicle-routing-/). Useful for cut-based exact methods.
7. [Ozbaygin, Karasan, and Yaman (2018): vehicle-indexed split-delivery flow](https://optimization-online.org/wp-content/uploads/2014/12/4687.pdf). Useful caution about aggregation and vehicle load identity.
8. [Desaulniers (2010): split-delivery branch-price-and-cut](https://ideas.repec.org/a/inm/oropre/v58y2010i1p179-192.html). Useful for exact decomposition with split quantities.
9. [Azi, Gendreau, and Potvin (2010): exact multiple-use vehicle routing](https://ideas.repec.org/a/eee/ejores/v202y2010i3p756-763.html). Useful historical multi-trip branch-and-price approach, with different service objective.

The comparisons and implementation recommendations above are **inferences from the cited formulations and this repository's rules**. None of the cited computational results should be assumed to carry over to the MPVRP-CC benchmark without experiments.
