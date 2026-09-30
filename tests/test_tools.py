from __future__ import annotations

import argparse
import csv
import json
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from mpvrp.models import MPVRPInstance
from milp import solve as benchmark_solve
from tools.benchmarks import generate as benchmark_generate
from tools.changeovers.reevaluate import reevaluate_solution_text
from tools.instances import generate as instance_generate
from tools.instances.io import write_instance
from tools.instances.models import GenerationConfig, InstanceData, VerificationReport
from tools.instances.validate import verify_instance
from tools.run_logging import configure_run_logging
from loguru import logger


def _instance(path: Path) -> MPVRPInstance:
    data = InstanceData(
        uuid=str(uuid4()),
        params=np.array([2, 1, 1, 1, 1]),
        transition_costs=np.array([[25, 1001], [1001, 30]]),
        vehicles=np.array([[1, 1000, 1, 1]]),
        depots=np.array([[1, 1, 1, 500, 500]]),
        garages=np.array([[1, 0, 0]]),
        stations=np.array([[1, 2, 2, 100, 100]]),
    )
    write_instance(data, path)
    assert verify_instance(path).is_valid
    return MPVRPInstance.read(path)


def test_reevaluation_validates_schedule_and_prices_each_load(tmp_path: Path) -> None:
    instance = _instance(tmp_path / "MPVRP_001_s1_d1_p2.dat")
    solution = (
        "1: 1 - 1 [100] - 1 (100) - 1 [100] - 1 (100) - 1\n"
        "1: 0(0.00) - 0(0.00) - 0(0.00) - 1(0.00) - 1(0.00)\n\n"
        "1\n0\n0.00\n10.00\nCPU\n1.000\n"
    )
    updated, changes, cost = reevaluate_solution_text(solution, instance)
    assert (changes, cost) == (1, 1026.0)
    assert "0(25.00) - 0(25.00) - 1(1026.00)" in updated
    assert updated.splitlines()[-5:-3] == ["1", "1026.00"]

    with pytest.raises(ValueError, match="does not match"):
        reevaluate_solution_text(solution.replace("1: 0(0.00)", "2: 0(0.00)"), instance)
    with pytest.raises(ValueError, match="mismatched"):
        reevaluate_solution_text(solution.replace(" - 1(0.00)\n\n", "\n\n"), instance)


def test_failed_verification_preserves_existing_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = GenerationConfig("001", 1, 1, 1, 1, 1, output_dir=tmp_path, seed=1, force=True)
    config.filepath.write_text("previous valid file")
    monkeypatch.setattr(instance_generate, "generate_instance_data", lambda _: object())
    monkeypatch.setattr(instance_generate, "validate_instance_data", lambda _: VerificationReport())
    monkeypatch.setattr(instance_generate, "write_instance", lambda _, path: path.write_text("invalid"))
    monkeypatch.setattr(
        instance_generate,
        "verify_instance",
        lambda *_: VerificationReport(errors=["invalid staged file"]),
    )
    with pytest.raises(ValueError, match="file-level verification"):
        instance_generate.generate(config)
    assert config.filepath.read_text() == "previous valid file"


def test_batch_failure_does_not_publish_partial_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(
        seed=1, output_dir=tmp_path, manifest="manifest.csv", count=2,
        start_id=1, min_products=2, max_products=2,
        min_demand_probability=0.4, max_demand_probability=0.9,
        grid=100, force=False,
    )
    calls = 0

    def fail_second(_, staged_args, instance_id, levels):
        nonlocal calls
        calls += 1
        staged_path = staged_args.output_dir / f"MPVRP_{instance_id}_s1_d1_p2.dat"
        staged_path.write_text("staged")
        if calls == 2:
            raise ValueError("generation failed")
        return staged_path, {"id": instance_id, "file": staged_path.name}

    monkeypatch.setattr(benchmark_generate, "_generate_instance_with_backtracking", fail_second)
    with pytest.raises(ValueError, match="generation failed"):
        benchmark_generate.generate_dataset(args)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("solver_result", "expected_status"),
    [(None, "UNSOLVED"), ("optimal", "OPTIMAL"), ("incumbent", "SOLVED")],
)
def test_benchmark_records_finished_attempt_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, solver_result: str | None, expected_status: str
) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("id,file\n001,MPVRP_001_s1_d1_p2.dat\n")
    args = argparse.Namespace(
        manifest=manifest, report=tmp_path / "report.csv", solutions_dir=tmp_path / "solutions",
        time_limit=1, verbose=False, resume=False,
    )
    monkeypatch.setattr(benchmark_solve.MPVRPInstance, "read", lambda _: SimpleNamespace(
        instance_id="001", n_stations=1, n_depots=1, n_prods=2,
    ))
    def solve(*_, **__):
        if solver_result is None:
            return None
        return SimpleNamespace(
            status=benchmark_solve.GRB.OPTIMAL if solver_result == "optimal" else benchmark_solve.GRB.TIME_LIMIT,
            objective=1.0, best_bound=1.0, mip_gap=0.0, node_count=1,
            solver_runtime=0.1, routes=[],
        )
    monkeypatch.setattr(benchmark_solve, "solve_milp", solve)
    monkeypatch.setattr(benchmark_solve, "write_solution", lambda **_: None)
    monkeypatch.setattr(benchmark_solve, "_validated_route_objective", lambda *_: 2.0)
    benchmark_solve.solve_dataset(args)
    with args.report.open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["status"] == expected_status
    if solver_result is not None:
        assert rows[0]["objective"] == "2.000000"
        assert rows[0]["solver_objective"] == "1.000000"


def test_generation_retry_manifest_records_rejected_draw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(
        seed=3, output_dir=tmp_path, manifest="manifest.csv", count=1, start_id=1,
        min_products=2, max_products=2, min_demand_probability=0.4,
        max_demand_probability=0.4, grid=100, force=False,
    )
    calls = 0

    def generate(config):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("rejected draw")
        config.filepath.write_text("accepted")
        return config.filepath

    monkeypatch.setattr(benchmark_generate, "generate", generate)
    manifest = benchmark_generate.generate_dataset(args)
    with manifest.open(newline="") as file:
        row = next(csv.DictReader(file))
    assert row["attempts"] == "2"
    assert int(row["instance_seed"]) >= 0
    rejected = json.loads(row["rejections"])
    assert rejected[0]["reason"] == "rejected draw"
    assert isinstance(rejected[0]["seed"], int)


def test_invalid_instance_and_resume_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "MPVRP_001_s1_d1_p2.dat"
    _instance(path)
    text = path.read_text()
    path.write_text(text + "unexpected trailing row\n")
    assert not verify_instance(path).is_valid

    manifest = tmp_path / "manifest.csv"
    manifest.write_text(f"id,file\n001,{path.name}\n")
    report = tmp_path / "report.csv"
    args = argparse.Namespace(
        manifest=manifest, report=report, solutions_dir=tmp_path / "solutions",
        time_limit=1, verbose=False, resume=False,
    )
    monkeypatch.setattr(benchmark_solve.MPVRPInstance, "read", lambda _: (_ for _ in ()).throw(ValueError("bad instance")))
    benchmark_solve.solve_dataset(args)
    with report.open(newline="") as file:
        assert next(csv.DictReader(file))["status"] == "UNSOLVED"
    args.resume = True
    monkeypatch.setattr(benchmark_solve.MPVRPInstance, "read", lambda _: pytest.fail("resumed completed attempt"))
    benchmark_solve.solve_dataset(args)


def test_run_logging_creates_distinct_files(tmp_path: Path) -> None:
    first = configure_run_logging("validate", log_dir=tmp_path)
    logger.info("first run marker")
    second = configure_run_logging("validate", log_dir=tmp_path)
    logger.info("second run marker")
    assert first != second
    assert "first run marker" in first.read_text()
    assert "second run marker" in second.read_text()
    assert "second run marker" not in first.read_text()
