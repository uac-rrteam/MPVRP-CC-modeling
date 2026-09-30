"""Independent feasibility and accounting checks for canonical MPVRP solutions."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from mpvrp.models import MPVRPInstance

AMOUNT_RE = re.compile(r"^(\d+)\s*(?:\[([-+]?\d+(?:\.\d+)?)\]|\(([-+]?\d+(?:\.\d+)?)\))?$")
PRODUCT_RE = re.compile(r"^(\d+)\(([-+]?\d+(?:\.\d+)?)\)$")
EPSILON = 1e-6
METRIC_TOLERANCE = 0.011


@dataclass
class Check:
    name: str
    status: Literal["PASS", "FAIL", "SKIPPED"] = "PASS"
    details: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.status = "FAIL"
        self.details.append(message)

    def skip(self, reason: str) -> None:
        if self.status == "PASS":
            self.status = "SKIPPED"
            self.details.append(reason)


@dataclass
class VerificationReport:
    checks: dict[str, Check]
    calculated: dict[str, float | int] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return all(check.status == "PASS" for check in self.checks.values())

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "checks": [asdict(check) for check in self.checks.values()],
            "calculated": self.calculated,
        }


@dataclass(frozen=True)
class Stop:
    kind: Literal["garage", "depot", "station"]
    id: int
    quantity: float | None
    product: int | None = None  # Zero-based, as in the solution file.
    cumulative_cost: float | None = None


@dataclass(frozen=True)
class Schedule:
    vehicle_id: int
    stops: list[Stop]


def _checks() -> dict[str, Check]:
    labels = (
        ("format", "File format"),
        ("vehicles", "Known vehicles and unique schedules"),
        ("garages", "Home garage departure and return"),
        ("continuity", "Connected schedule and valid stop order"),
        ("products", "Product states and changeovers"),
        ("trips", "Positive, balanced trips and vehicle capacity"),
        ("stock", "Depot stock"),
        ("demand", "Station-product demand"),
        ("service", "At most one service per vehicle and station-product"),
        ("metrics", "Cumulative costs and summary metrics"),
    )
    return {key: Check(label) for key, label in labels}


def _number(token: str, description: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"{description} must be finite.")
    return value


def _parse_schedule(route_line: str, product_line: str) -> Schedule:
    vehicle_text, colon, route_text = route_line.partition(":")
    product_vehicle_text, product_colon, product_text = product_line.partition(":")
    if not colon or not product_colon or not vehicle_text.strip().isdigit():
        raise ValueError(f"Invalid vehicle schedule header: {route_line[:100]}")
    vehicle_id = int(vehicle_text.strip())
    if product_vehicle_text.strip() != vehicle_text.strip():
        raise ValueError(f"Vehicle {vehicle_id}: route and product line IDs differ.")
    visit_tokens = route_text.strip().split(" - ")
    product_tokens = product_text.strip().split(" - ")
    if len(visit_tokens) < 4 or len(product_tokens) != len(visit_tokens) - 1:
        raise ValueError(f"Vehicle {vehicle_id}: route and product token counts differ.")
    stops: list[Stop] = []
    for position, token in enumerate(visit_tokens):
        match = AMOUNT_RE.fullmatch(token.strip())
        if match is None:
            raise ValueError(f"Vehicle {vehicle_id}: invalid stop {token!r}.")
        node_id = int(match.group(1))
        if match.group(2) is not None:
            kind = "depot"
            quantity = _number(match.group(2), "Load")
        elif match.group(3) is not None:
            kind = "station"
            quantity = _number(match.group(3), "Delivery")
        else:
            kind = "garage"
            quantity = None
        if position < len(product_tokens):
            product_match = PRODUCT_RE.fullmatch(product_tokens[position].strip())
            if product_match is None:
                raise ValueError(f"Vehicle {vehicle_id}: invalid product token {product_tokens[position]!r}.")
            product = int(product_match.group(1))
            cost = _number(product_match.group(2), "Cumulative cost")
        else:
            product = cost = None
        stops.append(Stop(kind, node_id, quantity, product, cost))
    return Schedule(vehicle_id, stops)


def _parse(text: str) -> tuple[list[Schedule], dict[str, float | int]]:
    lines = text.splitlines()
    if len(lines) < 6:
        raise ValueError("Solution must end with six summary lines.")
    entries = [line for line in lines[:-6] if line.strip()]
    if not entries or len(entries) % 2:
        raise ValueError("Vehicle route and product lines must occur in pairs.")
    schedules = [_parse_schedule(route, products) for route, products in zip(entries[::2], entries[1::2])]
    try:
        metrics = {
            "vehicles_used": int(lines[-6]),
            "product_changes": int(lines[-5]),
            "changeover_cost": _number(lines[-4], "Changeover cost"),
            "distance": _number(lines[-3], "Distance"),
            "resolution_time": _number(lines[-1], "Resolution time"),
        }
    except ValueError as exc:
        raise ValueError(f"Invalid summary metric: {exc}") from exc
    if not lines[-2].strip():
        raise ValueError("Processor summary line is empty.")
    if metrics["vehicles_used"] < 0 or metrics["product_changes"] < 0 or metrics["resolution_time"] < 0:
        raise ValueError("Count and resolution-time metrics must be non-negative.")
    return schedules, metrics


def check_solution_text(instance: MPVRPInstance, text: str) -> VerificationReport:
    """Check one solution against the full instance, collecting all observable failures."""
    checks = _checks()
    report = VerificationReport(checks)
    try:
        schedules, recorded = _parse(text)
    except ValueError as exc:
        checks["format"].fail(str(exc))
        for name, check in checks.items():
            if name != "format":
                check.skip("Cannot evaluate until the file format is repaired.")
        return report

    vehicles = {item.id: item for item in instance.vehicles}
    depots = {item.id: item for item in instance.depots}
    stations = {item.id: item for item in instance.stations}
    garages = {item.id: item for item in instance.garages}
    used: set[int] = set()
    loaded: dict[tuple[int, int], float] = {}
    delivered: dict[tuple[int, int], float] = {}
    serviced: set[tuple[int, int, int]] = set()
    total_distance = 0
    total_cost = 0.0
    changes = 0
    calculations_complete = True

    for schedule in schedules:
        vid = schedule.vehicle_id
        if vid in used:
            checks["vehicles"].fail(f"Vehicle {vid} appears more than once.")
        used.add(vid)
        vehicle = vehicles.get(vid)
        if vehicle is None:
            checks["vehicles"].fail(f"Unknown vehicle {vid}.")
            calculations_complete = False
            continue
        stops = schedule.stops
        home = vehicle.start_g
        if home is None:
            checks["garages"].fail(f"Vehicle {vid} has no home garage in the instance.")
            calculations_complete = False
            continue
        if stops[0].kind != "garage" or stops[0].id != home.id:
            checks["garages"].fail(f"Vehicle {vid} does not depart from home garage {home.id}.")
        if stops[-1].kind != "garage" or stops[-1].id != home.id:
            checks["garages"].fail(f"Vehicle {vid} does not return to home garage {home.id}.")
        if any(stop.kind == "garage" for stop in stops[1:-1]):
            checks["continuity"].fail(f"Vehicle {vid} has an intermediate garage or disconnected trip block.")
        if stops[1].kind != "depot":
            checks["continuity"].fail(f"Vehicle {vid} must load at a depot before any delivery.")

        previous_node = None
        current_product = vehicle.init_prod - 1
        cumulative = 0.0
        trip_load = 0.0
        trip_delivered = 0.0
        trip_visits = 0
        trip_number = 0
        active_trip = False
        for position, stop in enumerate(stops):
            location = (garages if stop.kind == "garage" else depots if stop.kind == "depot" else stations).get(stop.id)
            if location is None:
                checks["continuity"].fail(f"Vehicle {vid}: unknown {stop.kind} {stop.id} at stop {position + 1}.")
                calculations_complete = False
            if previous_node is not None and location is not None:
                total_distance += round(previous_node.distance(location))
            previous_node = location

            if position == len(stops) - 1:
                if active_trip:
                    _finish_trip(checks["trips"], vid, trip_number, trip_load, trip_delivered, trip_visits)
                continue
            if stop.product is None or not 0 <= stop.product < instance.n_prods:
                checks["products"].fail(f"Vehicle {vid}, stop {position + 1}: product outside 0..{instance.n_prods - 1}.")
                calculations_complete = False
                continue
            if position == 0:
                if stop.product != current_product:
                    checks["products"].fail(f"Vehicle {vid}: initial product is {stop.product}, expected {current_product}.")
                if not _close(stop.cumulative_cost, 0):
                    checks["metrics"].fail(f"Vehicle {vid}: initial cumulative cost must be 0.")
                continue
            if stop.kind == "depot":
                if active_trip:
                    _finish_trip(checks["trips"], vid, trip_number, trip_load, trip_delivered, trip_visits)
                trip_number += 1
                active_trip = True
                trip_load = stop.quantity or 0.0
                trip_delivered = 0.0
                trip_visits = 0
                if trip_load <= EPSILON:
                    checks["trips"].fail(f"Vehicle {vid}, trip {trip_number}: depot load must be positive.")
                if trip_load > vehicle.capacity + EPSILON:
                    checks["trips"].fail(f"Vehicle {vid}, trip {trip_number}: load {trip_load:g} exceeds capacity {vehicle.capacity:g}.")
                loaded[(stop.id, stop.product)] = loaded.get((stop.id, stop.product), 0.0) + trip_load
                if stop.product != current_product:
                    changes += 1
                cumulative += instance.changeover_cost[current_product][stop.product]
                total_cost += instance.changeover_cost[current_product][stop.product]
                current_product = stop.product
            elif stop.kind == "station":
                if not active_trip:
                    checks["continuity"].fail(f"Vehicle {vid}, stop {position + 1}: delivery before a depot load.")
                quantity = stop.quantity or 0.0
                if quantity <= EPSILON:
                    checks["trips"].fail(f"Vehicle {vid}, stop {position + 1}: delivery must be positive.")
                trip_delivered += quantity
                trip_visits += 1
                key = (vid, stop.id, current_product)
                if key in serviced:
                    checks["service"].fail(f"Vehicle {vid} serves station {stop.id}, product {current_product + 1} more than once.")
                serviced.add(key)
                delivered[(stop.id, current_product)] = delivered.get((stop.id, current_product), 0.0) + quantity
                if stop.product != current_product:
                    checks["products"].fail(f"Vehicle {vid}, stop {position + 1}: product changes without loading.")
            else:
                checks["continuity"].fail(f"Vehicle {vid}, stop {position + 1}: garage inside the schedule.")
            if not _close(stop.cumulative_cost, cumulative):
                checks["metrics"].fail(f"Vehicle {vid}, stop {position + 1}: cumulative cost {stop.cumulative_cost:g}, expected {cumulative:g}.")

    if not used:
        checks["vehicles"].fail("No vehicle schedule was found.")
    if not calculations_complete:
        for name in ("garages", "continuity", "products", "trips", "stock", "demand", "service", "metrics"):
            checks[name].skip("Unknown vehicle, location, or product prevents a complete check.")
    else:
        for depot in instance.depots:
            for product in range(instance.n_prods):
                quantity = loaded.get((depot.id, product), 0.0)
                if quantity > depot.stocks[product] + EPSILON:
                    checks["stock"].fail(f"Depot {depot.id}, product {product + 1}: loaded {quantity:g}, stock {depot.stocks[product]:g}.")
        for station in instance.stations:
            for product in range(instance.n_prods):
                quantity = delivered.get((station.id, product), 0.0)
                demand = station.demand[product]
                if not _close(quantity, demand, EPSILON):
                    checks["demand"].fail(f"Station {station.id}, product {product + 1}: delivered {quantity:g}, demand {demand:g}.")
        report.calculated = {
            "vehicles_used": len(used),
            "product_changes": changes,
            "changeover_cost": total_cost,
            "distance": total_distance,
        }
        for name, expected in report.calculated.items():
            tolerance = METRIC_TOLERANCE if name in ("changeover_cost", "distance") else 0
            if not _close(recorded[name], expected, tolerance):
                checks["metrics"].fail(f"Summary {name}: recorded {recorded[name]:g}, calculated {expected:g}.")
    return report


def _finish_trip(check: Check, vehicle_id: int, trip: int, load: float, delivered: float, visits: int) -> None:
    if visits == 0:
        check.fail(f"Vehicle {vehicle_id}, trip {trip}: no delivery.")
    if not _close(load, delivered, EPSILON):
        check.fail(f"Vehicle {vehicle_id}, trip {trip}: loaded {load:g}, delivered {delivered:g}.")


def _close(actual: float | int | None, expected: float | int, tolerance: float = METRIC_TOLERANCE) -> bool:
    return actual is not None and abs(actual - expected) <= tolerance
