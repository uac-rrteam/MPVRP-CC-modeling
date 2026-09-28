from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from paths import GENERATED_INSTANCES_DIR

DEFAULT_OUTPUT_DIR = GENERATED_INSTANCES_DIR
EPSILON = 1e-6


@dataclass(frozen=True)
class GenerationConfig:
    instance_code: str
    vehicles: int
    depots: int
    garages: int
    stations: int
    products: int
    output_dir: Path = DEFAULT_OUTPUT_DIR
    grid_size: int = 100
    changeover_cost_level: str = "normal"
    capacity_level: str = "medium"
    demand_level: str = "medium"
    stock_level: str = "medium"
    demand_probability: float = 0.45
    min_point_distance: int = 1
    coordinate_strategy: str = "clustered"
    seed: int | None = None
    force: bool = False

    @property
    def filename(self) -> str:
        return f"MPVRP_{self.instance_code}_s{self.stations}_d{self.depots}_p{self.products}.dat"

    @property
    def filepath(self) -> Path:
        return self.output_dir / self.filename


@dataclass(frozen=True)
class InstanceData:
    uuid: str
    params: np.ndarray
    transition_costs: np.ndarray
    vehicles: np.ndarray
    depots: np.ndarray
    garages: np.ndarray
    stations: np.ndarray

    @property
    def nb_products(self) -> int:
        return int(self.params[0])

    @property
    def nb_depots(self) -> int:
        return int(self.params[1])

    @property
    def nb_garages(self) -> int:
        return int(self.params[2])

    @property
    def nb_stations(self) -> int:
        return int(self.params[3])

    @property
    def nb_vehicles(self) -> int:
        return int(self.params[4])


@dataclass(frozen=True)
class ParsedInstance(InstanceData):
    filepath: Path


@dataclass
class VerificationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)
