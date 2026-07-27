from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional



@dataclass(frozen=True)
class MPVRPNode:
    """Base node interface for nodes in the execution graph."""
    id: int         # 1-based entity ID from instance file
    global_id: int  # 0-based unique index in the arc cost matrix
    x: float
    y: float

    @property
    def type(self) -> int:
        """0 = Request, 1 = Garage, 2 = Depot-Product"""
        raise NotImplementedError

    def distance(self, other: MPVRPNode) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class GarageNode(MPVRPNode):
    """Garage node representing vehicle departure and arrival location."""
    @property
    def type(self) -> int:
        return 1  # Garage node type


@dataclass(frozen=True)
class DepotNode(MPVRPNode):
    """Depot node representing product storage and pickup location."""
    product: int  # 0-based product index
    stock: int

    @property
    def type(self) -> int:
        return 2  # Depot node type


@dataclass(frozen=True)
class RequestNode(MPVRPNode):
    """Request node representing a customer request for a product."""
    product: int  # 0-based product index
    demand: int

    @property
    def type(self) -> int:
        return 0  # Request node type


@dataclass(frozen=True)
class Vehicle:
    """Vehicle entity representing a vehicle in the fleet."""
    id: int
    capacity: int
    init_g: Optional[GarageNode]
    init_prod: int  # 0-based product index