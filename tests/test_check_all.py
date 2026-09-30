from __future__ import annotations

import json
import sys
from pathlib import Path

from mpvrp.io.solution import format_solution
from mpvrp.models import MPVRPInstance
from tools import check_solution


INSTANCE = """# test-uuid
1 1 1 1 1
25
1 100 1 1
1 1 1 100
1 0 0
1 2 2 100
"""


def test_all_reports_valid_invalid_and_missing(tmp_path: Path) -> None:
    instances = tmp_path / "instances"
    solutions = tmp_path / "solutions"
    reports = tmp_path / "reports"
    instances.mkdir()
    solutions.mkdir()
    for number in (1, 2, 3):
        path = instances / f"MPVRP_{number:03d}_s1_d1_p1.dat"
        path.write_text(INSTANCE)
        if number < 3:
            instance = MPVRPInstance.read(path)
            route = [{"vehicle": 1, "trip": 0, "product": 1, "start_depot": 1,
                      "path": ["S1"], "deliveries": [{"station": 1, "quantity": 100}]}]
            text = format_solution(instance, route, 0.1, processor="Test CPU")
            if number == 2:
                text = text.replace("1 (100)", "1 (99)")
            (solutions / f"Sol_{number:03d}_s1_d1_p1.dat").write_text(text)

    aggregate = check_solution.check_all(instances, solutions, reports)
    assert aggregate["counts"] == {"VALID": 1, "INVALID": 1, "MISSING": 1, "ERROR": 0}
    assert [entry["status"] for entry in aggregate["results"]] == ["VALID", "INVALID", "MISSING"]
    assert len(list(reports.glob("*.json"))) == 3
    assert json.loads((reports / "instance_002.json").read_text())["valid"] is False
    assert json.loads((reports / "instance_003.json").read_text())["status"] == "MISSING"


def test_all_cli_saves_aggregate_report(tmp_path: Path, monkeypatch, capsys) -> None:
    instances = tmp_path / "instances"
    solutions = tmp_path / "solutions" / "cp" / "in"
    instances.mkdir()
    solutions.mkdir(parents=True)
    path = instances / "MPVRP_001_s1_d1_p1.dat"
    path.write_text(INSTANCE)
    instance = MPVRPInstance.read(path)
    route = [{"vehicle": 1, "trip": 0, "product": 1, "start_depot": 1,
              "path": ["S1"], "deliveries": [{"station": 1, "quantity": 100}]}]
    (solutions / "Sol_001_s1_d1_p1.dat").write_text(format_solution(instance, route, 0.1, processor="Test CPU"))
    monkeypatch.setattr(check_solution, "SCENARIOS", {"1": (instances, "in")})
    monkeypatch.setattr(check_solution, "SOLUTIONS_DIR", tmp_path / "solutions")
    output = tmp_path / "all.json"
    monkeypatch.setattr(sys, "argv", ["mpvrp-check-solution", "--scenario", "1", "--inst", "all", "--method", "cp", "--json", str(output)])
    assert check_solution.main() == 0
    assert "1 valid" in capsys.readouterr().out
    assert json.loads(output.read_text())["counts"]["VALID"] == 1
