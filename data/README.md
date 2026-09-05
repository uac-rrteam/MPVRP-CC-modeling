# Experimental data

## Instances

- `instances/with_changeover_costs/` contains 100 cost-bearing benchmark instances.
- `instances/without_changeover_costs/` contains their 100 paired counterparts with zero-valued transition matrices.

Regenerate the zero-cost dataset with:

```bash
mpvrp-prepare-scenarios --force
```

## Solutions

Depending on the LP model used, the solutions may be in `solutions/lp*` with the same subfolder structure as the instances. The `with_changeover_costs/` and `without_changeover_costs/` folders are kept separate.

This separation prevents one experiment from overwriting the results of the other.

`without_changeover_costs/reevaluated_with_changeover_costs/` contains
optional copies of zero-cost solutions repriced afterward with the original
transition matrix. Routes and delivered quantities remain unchanged.
