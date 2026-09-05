from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from common.paths import LP2_SOLUTIONS_DIR
from lp1.io.sol import format_solution
from lp2.schemas import MPVRPInstance


def write_solution(
    instance: MPVRPInstance,
    routes: Sequence[Mapping[str, Any]],
    filename: str | Path | None = None,
    resolution_time: float = 0.0,
    processor: str | None = None,
) -> Path:
    """Write an LP2 solution using the repository's canonical format."""
    if filename is None:
        filename = LP2_SOLUTIONS_DIR / (
            f"Sol_{instance.instance_id}"
            f"_s{instance.n_stations}_d{instance.n_depots}_p{instance.n_prods}.dat"
        )

    filepath = Path(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        format_solution(instance, routes, resolution_time, processor),
        encoding="utf-8",
    )
    return filepath
