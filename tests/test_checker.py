from __future__ import annotations

from mpvrp.checker import check_solution_text
from mpvrp.io.solution import format_solution
from mpvrp.models import Depot, GarageNode, MPVRPInstance, Station, Vehicle


def example() -> tuple[MPVRPInstance, str]:
    instance = MPVRPInstance()
    instance.instance_id = "001"
    instance.n_prods = 2
    instance.n_stations = 1
    instance.n_depots = 1
    instance.changeover_cost = [[25, 1001], [1001, 30]]
    garage = GarageNode(1, 0, 0, 0)
    instance.garages = [garage]
    instance.vehicles = [Vehicle(1, 1000, garage, 1)]
    instance.depots = [Depot(1, 1, 1, [500, 500])]
    instance.stations = [Station(1, 2, 2, [100, 100])]
    routes = [
        {"vehicle": 1, "trip": 0, "product": 1, "start_depot": 1,
         "path": ["S1"], "deliveries": [{"station": 1, "quantity": 100}]},
        {"vehicle": 1, "trip": 1, "product": 2, "start_depot": 1,
         "path": ["S1"], "deliveries": [{"station": 1, "quantity": 100}]},
    ]
    return instance, format_solution(instance, routes, 0.1, processor="Test CPU")


def test_valid_solution_passes_every_check() -> None:
    instance, text = example()
    report = check_solution_text(instance, text)
    assert report.is_valid, report.to_dict()
    assert report.calculated == {
        "vehicles_used": 1, "product_changes": 1,
        "changeover_cost": 1026.0, "distance": 7,
    }


def test_checker_reports_independent_constraint_failures() -> None:
    instance, text = example()
    mutations = [
        (text.replace("1 [100]", "1 [1100]", 1), "trips"),
        (text.replace("1 [100]", "1 [501]", 1), "stock"),
        (text.replace("1 (100)", "1 (99)", 1), "demand"),
        (text.replace("1: 0(0.00)", "1: 1(0.00)", 1), "products"),
        (text.replace("0(25.00)", "0(26.00)", 1), "metrics"),
    ]
    for changed, expected_check in mutations:
        report = check_solution_text(instance, changed)
        assert not report.is_valid
        assert report.checks[expected_check].status == "FAIL", report.to_dict()


def test_checker_catches_duplicate_vehicle_and_repeated_service() -> None:
    instance, text = example()
    lines = text.splitlines()
    duplicated = "\n".join([*lines[:2], "", *lines]) + "\n"
    assert check_solution_text(instance, duplicated).checks["vehicles"].status == "FAIL"

    repeated = text.replace("1 (100)", "1 (50) - 1 (50)", 1)
    repeated = repeated.replace("0(25.00) - 1(1026.00)", "0(25.00) - 0(25.00) - 1(1026.00)", 1)
    assert check_solution_text(instance, repeated).checks["service"].status == "FAIL"


def test_malformed_solution_skips_dependent_checks() -> None:
    instance, text = example()
    report = check_solution_text(instance, text.replace("1 [100]", "invalid stop", 1))
    assert report.checks["format"].status == "FAIL"
    assert report.checks["demand"].status == "SKIPPED"


def test_checker_recalculates_distance() -> None:
    instance, text = example()
    lines = text.splitlines()
    lines[-3] = "999.00"
    report = check_solution_text(instance, "\n".join(lines) + "\n")
    assert report.checks["metrics"].status == "FAIL"
    assert any("distance" in detail for detail in report.checks["metrics"].details)
