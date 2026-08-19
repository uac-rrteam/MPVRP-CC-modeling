# Experimental data

## Instances

- `instances/with_changeover_costs/` contains 100 cost-bearing benchmark instances.
- `instances/without_changeover_costs/` contains their 100 paired counterparts with zero-valued transition matrices.

The cost-bearing set contains 34 `normal`, 33 `high`, and 33 `mixed`
transition-cost regimes. The product-count distribution is 22 instances with
2 products, 30 with 3, 12 with 4, 22 with 5, and 14 with 6 products. All
numeric values stored in the instance files are integers.

Cost-bearing diagonals use the positive `low` range `[25, 150]`. Off-diagonal
entries use `[1001, 3500]` for `normal`, `[4501, 15000]` for `high`, or values
from both ranges for `mixed`.

Files with the same name in the two benchmark directories describe the same underlying instance. Only the `NbProducts × NbProducts` transition-cost matrix differs. After generation and scenario preparation, both directories contain the same `manifest.csv` so benchmark rows can be matched directly by instance ID.

The manifest records the instance ID, file name, dimensions, changeover-cost
level, capacity/demand/stock levels, demand probability, and coordinate
strategy. The committed benchmark was generated with the default seed
`20260507`.

Regenerate the zero-cost dataset with:

```bash
mpvrp-prepare-scenarios --force
```

## Solutions

Solutions and reports are separated by experimental scenario:

- `solutions/with_changeover_costs/`
- `solutions/without_changeover_costs/`

This separation prevents one experiment from overwriting the results of the other.

`solutions/without_changeover_costs/reevaluated_with_changeover_costs/` contains
optional copies of zero-cost solutions repriced afterward with the original
transition matrix. Routes and delivered quantities remain unchanged.
