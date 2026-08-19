# Experimental data

## Instances

- `instances/with_changeover_costs/` contains 100 cost-bearing benchmark instances.
- `instances/without_changeover_costs/` contains their 100 paired counterparts with zero-valued transition matrices.

The cost-bearing set contains 34 `normal`, 33 `high`, and 33 `mixed`
transition-cost regimes. Every instance has between two and six products.

Files with the same name in the two benchmark directories describe the same underlying instance. Only the `NbProducts × NbProducts` transition-cost matrix differs. After generation and scenario preparation, both directories contain the same `manifest.csv` so benchmark rows can be matched directly by instance ID.

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
