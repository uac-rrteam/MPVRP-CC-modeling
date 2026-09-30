from __future__ import annotations

import numpy as np

from .models import GenerationConfig

def _station_centers(rng: np.random.Generator, config: GenerationConfig) -> list[tuple[int, int]]:
    """Return cluster centers used for non-uniform station layouts.

    For clustered and corridor strategies, we define center points around which
    stations are concentrated. This creates realistic networks where demand
    is geographically clustered rather than uniformly scattered.
    """
    if config.coordinate_strategy == "uniform":
        return []  # No clusters for uniform distribution

    if config.coordinate_strategy == "corridor":
        # Two clusters forming a corridor/line pattern
        return [
            (round(0.2 * config.grid_size), round(0.35 * config.grid_size)),
            (round(0.8 * config.grid_size), round(0.65 * config.grid_size)),
        ]

    # Clustered strategy: 2-4 clusters depending on station density
    center_count = min(4, max(2, int(np.sqrt(config.stations))))
    margin = 0.18 * config.grid_size  # Keep clusters away from boundaries
    return [
        (
            int(round(rng.uniform(margin, config.grid_size - margin))),
            int(round(rng.uniform(margin, config.grid_size - margin))),
        )
        for _ in range(center_count)
    ]


def _station_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
    centers: list[tuple[int, int]],
    station_id: int,
) -> tuple[int, int]:
    """Generate one station coordinate according to the spatial strategy.

    Strategies:
    - 'uniform': random locations across the entire grid
    - 'corridor': stations lined up along a diagonal path
    - 'clustered': stations grouped around randomly placed centers
    """
    if config.coordinate_strategy == "uniform":
        # Completely random placement with minimum distance constraint
        return _unique_point(rng, config, points)

    if config.coordinate_strategy == "corridor":
        # Place station along a diagonal line with slight randomness
        t = (station_id - 1) / max(1, config.stations - 1)  # Position along corridor (0 to 1)
        base_x = (0.1 + 0.8 * t) * config.grid_size
        base_y = (0.25 + 0.5 * t) * config.grid_size
        spread = 0.08 * config.grid_size  # Jitter around the line
        return _unique_point_near(rng, config, points, base_x, base_y, spread)

    # Clustered: pick a random cluster center and place nearby
    center_x, center_y = centers[int(rng.integers(0, len(centers)))]
    spread = 0.12 * config.grid_size  # Spread around the center
    return _unique_point_near(rng, config, points, center_x, center_y, spread)


def _depot_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
    depot_id: int,
) -> tuple[int, int]:
    """Generate one depot coordinate according to the spatial strategy.

    Depots are typically placed in corners or edges for realistic logistics scenarios.
    """
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    # Define anchor points in the four corners with small margins
    anchors = [
        (0.08 * config.grid_size, 0.10 * config.grid_size),  # Bottom-left
        (0.92 * config.grid_size, 0.12 * config.grid_size),  # Bottom-right
        (0.10 * config.grid_size, 0.90 * config.grid_size),  # Top-left
        (0.90 * config.grid_size, 0.88 * config.grid_size),  # Top-right
    ]
    # Cycle through anchors: depot 1 at anchor 0, depot 2 at anchor 1, etc.
    anchor_x, anchor_y = anchors[(depot_id - 1) % len(anchors)]
    return _unique_point_near(rng, config, points, anchor_x, anchor_y, 0.04 * config.grid_size)


def _garage_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
    garage_id: int,
    depots: np.ndarray,
) -> tuple[int, int]:
    """Generate one garage coordinate, usually close to a depot.

    Garages are placed near depots to minimize travel time for vehicle positioning.
    """
    if config.coordinate_strategy == "uniform":
        return _unique_point(rng, config, points)

    # Assign garage to a nearby depot, cycling through depots if there are more garages
    depot = depots[(garage_id - 1) % len(depots)]
    return _unique_point_near(rng, config, points, int(depot[1]), int(depot[2]), 0.07 * config.grid_size)


def _unique_point(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
) -> tuple[int, int]:
    """Draw a point that respects the configured minimum distance when possible.

    Attempts up to 1000 times to find a point that's far enough from existing points.
    If unsuccessful, falls back to clipping to nearest valid position.
    This prevents overcrowding of locations while ensuring coverage across the grid.
    """
    for _ in range(1_000):
        x = int(rng.integers(0, config.grid_size + 1))
        y = int(rng.integers(0, config.grid_size + 1))
        if _is_far_enough(x, y, points, config.min_point_distance):
            points.append((x, y))
            return x, y
    # Fallback: accept a clipped point if we can't find a far enough one
    return _append_clipped_point(points, x, y, config.grid_size)


def _unique_point_near(
    rng: np.random.Generator,
    config: GenerationConfig,
    points: list[tuple[int, int]],
    center_x: float,
    center_y: float,
    spread: float,
) -> tuple[int, int]:
    """Draw a unique point near a center, falling back to uniform sampling.

    Uses normal distribution centered at (center_x, center_y) with given spread.
    If unable to find a unique point near the center after 1000 tries, falls back
    to completely random uniform sampling.
    """
    for _ in range(1_000):
        # Sample from normal distribution and clip to grid bounds
        x = int(round(np.clip(rng.normal(center_x, spread), 0, config.grid_size)))
        y = int(round(np.clip(rng.normal(center_y, spread), 0, config.grid_size)))
        if _is_far_enough(x, y, points, config.min_point_distance):
            points.append((x, y))
            return x, y
    # Fall back to uniform random if we can't maintain spacing near the center
    return _unique_point(rng, config, points)


def _is_far_enough(x: int, y: int, points: list[tuple[int, int]], minimum_distance: int) -> bool:
    """Check whether a candidate point is separated from existing points.

    Uses Euclidean distance to ensure minimum spacing between locations.
    """
    return all(np.hypot(x - px, y - py) >= minimum_distance for px, py in points)


def _append_clipped_point(
    points: list[tuple[int, int]],
    x: int,
    y: int,
    grid_size: int,
) -> tuple[int, int]:
    """Append a final clipped point after coordinate retries are exhausted.

    When we've tried many times and still can't find a unique point, we give up and
    place it at the clipped boundary. This ensures we can always generate locations.
    """
    point = (int(np.clip(x, 0, grid_size)), int(np.clip(y, 0, grid_size)))
    points.append(point)
    return point

