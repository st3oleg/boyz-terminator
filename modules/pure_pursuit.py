"""Pure Pursuit geometry for a path in a local metric coordinate frame.

This module only computes a lookahead target and path curvature. It does not
read hardware or issue motor commands; actuator calibration and safety gating
belong to the rover control layer.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


Point = tuple[float, float]
EARTH_RADIUS_M = 6_371_000.0


def latlon_to_local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float) -> Point:
    """Convert WGS84 latitude/longitude to a local east/north approximation."""
    values = (lat, lon, origin_lat, origin_lon)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("coordinate non finite")
    mean_lat = math.radians((lat + origin_lat) / 2.0)
    east = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(mean_lat)
    north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return east, north


class PurePursuitController:
    """Geometric Pure Pursuit calculation for a differential-drive rover.

    ``lookahead_m`` must be selected from the measured vehicle behavior and
    operating speed; there is deliberately no assumed vehicle-specific value.
    Yaw is radians counter-clockwise from local east (ENU convention).
    """

    def __init__(self, lookahead_m: float):
        if not math.isfinite(lookahead_m) or lookahead_m <= 0:
            raise ValueError("lookahead_m deve essere positivo e finito")
        self.lookahead_m = float(lookahead_m)

    @staticmethod
    def _path(path: Iterable[Sequence[float]]) -> list[Point]:
        points = []
        for item in path:
            if len(item) != 2:
                raise ValueError("ogni waypoint deve contenere x ed y")
            point = (float(item[0]), float(item[1]))
            if not all(math.isfinite(value) for value in point):
                raise ValueError("waypoint non finito")
            if not points or math.dist(points[-1], point) > 1e-6:
                points.append(point)
        if len(points) < 2:
            raise ValueError("il percorso deve contenere almeno due punti distinti")
        return points

    def target(self, path: Iterable[Sequence[float]], x: float, y: float) -> Point:
        """Return a point lookahead distance along the path from its nearest projection."""
        points = self._path(path)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("posizione non finita")

        # Project the rover position onto each segment and retain the nearest.
        best_distance_sq = math.inf
        best_segment = 0
        best_t = 0.0
        for index, (start, end) in enumerate(zip(points, points[1:])):
            vx, vy = end[0] - start[0], end[1] - start[1]
            length_sq = vx * vx + vy * vy
            t = max(0.0, min(1.0, ((x - start[0]) * vx + (y - start[1]) * vy) / length_sq))
            projection = (start[0] + t * vx, start[1] + t * vy)
            distance_sq = (x - projection[0]) ** 2 + (y - projection[1]) ** 2
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                best_segment = index
                best_t = t

        start = points[best_segment]
        end = points[best_segment + 1]
        vx, vy = end[0] - start[0], end[1] - start[1]
        segment_length = math.hypot(vx, vy)
        remaining = (1.0 - best_t) * segment_length
        if self.lookahead_m <= remaining:
            fraction = best_t + self.lookahead_m / segment_length
            return start[0] + fraction * vx, start[1] + fraction * vy

        distance_left = self.lookahead_m - remaining
        for start, end in zip(points[best_segment + 1:], points[best_segment + 2:]):
            vx, vy = end[0] - start[0], end[1] - start[1]
            segment_length = math.hypot(vx, vy)
            if distance_left <= segment_length:
                fraction = distance_left / segment_length
                return start[0] + fraction * vx, start[1] + fraction * vy
            distance_left -= segment_length

        # A target beyond the path lies at its endpoint; mission completion
        # detection and stopping are handled by the calling control layer.
        return points[-1]

    @staticmethod
    def curvature(x: float, y: float, yaw_rad: float, target: Sequence[float]) -> float:
        """Compute signed curvature (1/m) toward a target in local ENU coordinates."""
        values = (x, y, yaw_rad, float(target[0]), float(target[1]))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("posa, orientamento o target non finito")
        dx, dy = values[3] - x, values[4] - y
        forward = math.cos(yaw_rad) * dx + math.sin(yaw_rad) * dy
        left = -math.sin(yaw_rad) * dx + math.cos(yaw_rad) * dy
        distance_sq = dx * dx + dy * dy
        if distance_sq <= 1e-12:
            return 0.0
        if forward <= 0:
            raise ValueError("target dietro al rover: percorso/orientamento da verificare")
        return 2.0 * left / distance_sq
