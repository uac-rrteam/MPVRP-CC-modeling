from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .models import EPSILON, InstanceData, ParsedInstance, VerificationReport

INSTANCE_NAME_RE = re.compile(r"^MPVRP_(.+?)_s\d+_d\d+_p\d+\.dat$")
UUID_RE = re.compile(
    r"^#\s*([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def existing_instance_codes(instances_dir: Path) -> set[str]:
    if not instances_dir.exists():
        return set()
    return {
        match.group(1)
        for path in instances_dir.iterdir()
        if path.is_file() and (match := INSTANCE_NAME_RE.match(path.name))
    }


def _format_number(value: int | float) -> str:
    """Format one instance datum and reject non-integral values."""
    numeric = float(value)
    if not np.isfinite(numeric) or abs(numeric - round(numeric)) > EPSILON:
        raise ValueError(f"Instance values must be integers; found {value!r}.")
    return str(int(round(numeric)))


def _format_row(values: np.ndarray | list[int | float]) -> str:
    return "\t".join(_format_number(value) for value in values)


def write_instance(data: InstanceData, filepath: Path, force: bool = False) -> Path:
    if filepath.exists() and not force:
        raise FileExistsError(f"{filepath} already exists. Use --force to overwrite it.")

    filepath.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {data.uuid}", _format_row(data.params)]
    lines.extend(_format_row(row) for row in data.transition_costs)
    lines.extend(_format_row(row) for row in data.vehicles)
    lines.extend(_format_row(row) for row in data.depots)
    lines.extend(_format_row(row) for row in data.garages)
    lines.extend(_format_row(row) for row in data.stations)
    filepath.write_text("\n".join(lines) + "\n")
    return filepath


def _parse_numeric_row(
    line: str,
    expected: int,
    line_number: int,
    report: VerificationReport,
) -> list[int] | None:
    parts = line.split()
    if len(parts) != expected:
        report.error(f"Line {line_number}: expected {expected} values, found {len(parts)}.")
        return None
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        report.error(f"Line {line_number}: non-numeric value ({exc}).")
        return None
    return values


def load_instance_file(filepath: Path, report: VerificationReport) -> ParsedInstance | None:
    if not filepath.exists():
        report.error(f"File not found: {filepath}")
        return None
    if not filepath.is_file():
        report.error(f"Path is not a file: {filepath}")
        return None

    raw_lines = filepath.read_text().splitlines()
    lines = [(idx + 1, line.strip()) for idx, line in enumerate(raw_lines) if line.strip()]
    if not lines:
        report.error("File is empty.")
        return None

    _, first_line = lines[0]
    uuid_match = UUID_RE.match(first_line)
    if not uuid_match:
        report.error("Line 1 must be exactly '# <uuid-v4>' for MPVRPInstance.read().")
        return None

    extra_comments = [line_number for line_number, line in lines[1:] if line.startswith("#")]
    if extra_comments:
        report.error(
            "Only the first UUID line may be a comment because MPVRPInstance.read() tokenizes the file. "
            f"Extra comment lines: {extra_comments}."
        )
        return None

    data_lines = lines[1:]
    if not data_lines:
        report.error("Missing global parameter line.")
        return None

    params_line_number, params_line = data_lines[0]
    params_values = _parse_numeric_row(params_line, 5, params_line_number, report)
    if params_values is None:
        return None
    params = np.array(params_values, dtype=int)
    nb_products, nb_depots, nb_garages, nb_stations, nb_vehicles = params.tolist()
    for name, count in {
        "products": nb_products,
        "depots": nb_depots,
        "garages": nb_garages,
        "stations": nb_stations,
        "vehicles": nb_vehicles,
    }.items():
        if count < 1:
            report.error(f"Nb{name.capitalize()} must be at least 1; found {count}.")
    if report.errors:
        return None

    expected_line_count = 1 + nb_products + nb_vehicles + nb_depots + nb_garages + nb_stations
    if len(data_lines) != expected_line_count:
        report.error(
            "Incorrect number of data lines: "
            f"expected {expected_line_count}, found {len(data_lines)} "
            f"(1 params + {nb_products} transition + {nb_vehicles} vehicles + "
            f"{nb_depots} depots + {nb_garages} garages + {nb_stations} stations)."
        )
        return None

    cursor = 1

    def read_block(rows: int, width: int, label: str) -> np.ndarray | None:
        nonlocal cursor
        parsed_rows: list[list[int]] = []
        for _ in range(rows):
            line_number, line = data_lines[cursor]
            cursor += 1
            values = _parse_numeric_row(line, width, line_number, report)
            if values is None:
                return None
            parsed_rows.append(values)
        report.info(f"{label}: {rows} row(s), width {width}.")
        return np.array(parsed_rows, dtype=int)

    transition_costs = read_block(nb_products, nb_products, "transition_costs")
    vehicles = read_block(nb_vehicles, 4, "vehicles")
    depots = read_block(nb_depots, 3 + nb_products, "depots")
    garages = read_block(nb_garages, 3, "garages")
    stations = read_block(nb_stations, 3 + nb_products, "stations")

    if any(block is None for block in (transition_costs, vehicles, depots, garages, stations)):
        return None

    return ParsedInstance(
        filepath=filepath,
        uuid=uuid_match.group(1),
        params=params,
        transition_costs=transition_costs,
        vehicles=vehicles,
        depots=depots,
        garages=garages,
        stations=stations,
    )
