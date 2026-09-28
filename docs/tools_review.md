# Review of `src/tools` — implementation update

The requested changes below were made in the current tools. This review leaves the worktree's pre-existing staged deletions and unrelated edits alone.

## Completed

1. **Recoverable generation.** A single instance is written and verified in a temporary directory before it replaces the destination. Benchmark generation stages every instance and its manifest, checks destination conflicts, then publishes them together; if publishing fails, it restores replaced files. This prevents a failed validation or a mid-batch generation error from leaving a partly updated dataset. A process or machine crash during the final multi-file publish can still leave a partial batch, because a filesystem cannot atomically replace several files at once.

2. **Three benchmark result statuses.** The CSV `status` field is now `OPTIMAL` for a proven optimum, `SOLVED` for an incumbent without proof of optimality, and `UNSOLVED` when the attempt ends without an incumbent or errors. Every attempted instance gets a row, including a time-limited run without a solution. `--resume` continues to skip all reported IDs, including `UNSOLVED`, because those attempts have finished; this follows the requested experiment workflow. The separate `solver_status` field still distinguishes optimal and time-limit incumbents.

3. **Structured repricing checks.** Re-evaluation parses matching route and product lines, checks vehicle IDs, token counts, home garages, depot loads, station deliveries, and product changes only at loads. It then recomputes cumulative changeover costs and summary metrics. It rejects malformed schedules instead of rewriting them silently. It is a repricer, not a full feasibility checker for stock, capacity, or demand.

4. **Simpler instance validation.** The strict instance file parser and the semantic validator remain; validation no longer reparses every file with the MILP reader. Redundant integer and finite checks after `int()` parsing were removed. A focused test checks that a validated fixture is also read by `MPVRPInstance.read()`.

5. **Smaller generator entry point.** The unused 17-argument convenience wrapper was removed. `GenerationConfig` and `generate(config)` are the programmatic interface. Coordinate generation is now in `instances/geometry.py`; feasibility and demand repair stay in the generator because they encode model constraints.

Focused tests cover repricing and malformed schedules, MILP reader compatibility, preservation of an existing instance after failed verification, and no published files after batch generation fails. They do not run a Gurobi optimization.

## Logging and follow-up work

All six tool commands now configure Loguru with a console sink and a distinct timestamped `.log` file for each invocation. The default directory is `results/logs/`; `--log-dir` overrides it. The file records debug entries regardless of console verbosity. Tool CLI output and solver progress messages use the logger; the solver's native Gurobi console trace is still controlled by `--verbose` and is not copied into the Loguru file.

The benchmark manifest now stores `instance_seed`, `attempts`, and `rejections`. Each rejected draw includes its seed, parameter levels, and reason, and the run log summarizes retry counts. This makes the accepted sample and its rejection history auditable. The solver now builds each CSV row through a `BenchmarkResult` record, with the status set only after solution writing succeeds. Additional focused tests cover invalid instance input, completed `UNSOLVED` resume behavior, retry provenance, and distinct run logs.

## Pairing question (previous item 3)

`changeovers/pair.py` currently finds every `MPVRP_*.dat` in the source directory and copies the manifest separately. For example, if the directory contains an old instance absent from `manifest.csv`, the paired directory will still receive that old instance. Also, a manifest that stores a path rather than a filename could point a solver back to the original scenario. The current generated manifest stores bare filenames, so that second case does not affect the standard dataset. No pairing change was made here; it is only worth addressing if you intend to support edited or externally supplied manifests.

## Remaining scope

The pairing behavior explained above is unchanged. A licensed Gurobi optimization run was not part of these focused tests. The README's `uv run pytest` command needs a writable uv cache in this sandbox; `PYTHONPATH=src pytest -q` runs the checked-in tests directly.
