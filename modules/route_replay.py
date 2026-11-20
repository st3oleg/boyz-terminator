"""Validated GNSS route preview for the Rover.

This module has no hardware side effects. Motor actuation needs measured
calibration, an obstacle monitor and an independent safety chain.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from modules.pure_pursuit import PurePursuitController, latlon_to_local_xy


def _finite(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} non numerico") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} non finito")
    return number


def _distance_to_segment(point, start, end):
    vx, vy = end[0] - start[0], end[1] - start[1]
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-12:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((point[0] - start[0]) * vx + (point[1] - start[1]) * vy) / length_sq))
    return math.dist(point, (start[0] + t * vx, start[1] + t * vy))


def _inside(point, polygon):
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:]):
        if (ay > y) != (by > y):
            crossing = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < crossing:
                inside = not inside
    return inside


class RouteReplay:
    """Geometry and fail-closed checks for a single route and geofence."""

    def __init__(self, mission, geofence, lookahead_m=2.2, margin_m=0.75):
        points = mission.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= 10_000:
            raise ValueError("La traccia richiede da 2 a 10000 punti")
        self.origin_lat = _finite(points[0].get("lat"), "latitudine")
        self.origin_lon = _finite(points[0].get("lon"), "longitudine")
        if not (-90 <= self.origin_lat <= 90 and -180 <= self.origin_lon <= 180):
            raise ValueError("Coordinate fuori intervallo")
        self.path = []
        previous_time = None
        for index, item in enumerate(points):
            lat = _finite(item.get("lat"), f"latitudine punto {index + 1}")
            lon = _finite(item.get("lon"), f"longitudine punto {index + 1}")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"Coordinate fuori intervallo al punto {index + 1}")
            if item.get("rtk_status") != "FIX":
                raise ValueError(f"Il punto {index + 1} non ha RTK FIX")
            timestamp = item.get("fix_timestamp", item.get("timestamp"))
            if timestamp is not None:
                timestamp = _finite(timestamp, "timestamp")
                if previous_time is not None and timestamp <= previous_time:
                    raise ValueError("Timestamp della traccia non crescenti")
                previous_time = timestamp
            xy = latlon_to_local_xy(lat, lon, self.origin_lat, self.origin_lon)
            if self.path:
                gap = math.dist(self.path[-1], xy)
                if gap > 5.0:
                    raise ValueError(f"Salto di {gap:.1f} m fra i punti {index} e {index + 1}")
                if gap < 0.01:
                    continue
            self.path.append(xy)
        if len(self.path) < 2:
            raise ValueError("La traccia non contiene due posizioni distinte")

        polygon = self._polygon(geofence)
        self.polygon = [latlon_to_local_xy(lat, lon, self.origin_lat, self.origin_lon) for lon, lat in polygon]
        if math.dist(self.polygon[0], self.polygon[-1]) > 1e-6:
            self.polygon.append(self.polygon[0])
        self.margin_m = _finite(margin_m, "margine")
        if self.margin_m <= 0:
            raise ValueError("Margine geofence non valido")
        self.controller = PurePursuitController(_finite(lookahead_m, "lookahead"))
        for start, end in zip(self.path, self.path[1:]):
            count = max(1, math.ceil(math.dist(start, end) / 0.25))
            for i in range(count + 1):
                t = i / count
                sample = (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
                if self.boundary_clearance(sample) < self.margin_m:
                    raise ValueError("La traccia esce dal geofence o passa troppo vicina al bordo")
        self.length_m = sum(math.dist(a, b) for a, b in zip(self.path, self.path[1:]))

    @staticmethod
    def _polygon(value):
        if not isinstance(value, dict):
            raise ValueError("Geofence GeoJSON mancante")
        if value.get("type") == "FeatureCollection":
            features = value.get("features", [])
            if len(features) != 1:
                raise ValueError("Serve un solo poligono geofence")
            value = features[0]
        if value.get("type") == "Feature":
            value = value.get("geometry")
        if not isinstance(value, dict) or value.get("type") != "Polygon":
            raise ValueError("Serve un Polygon GeoJSON")
        rings = value.get("coordinates")
        if not isinstance(rings, list) or len(rings) != 1 or not 4 <= len(rings[0]) <= 1001:
            raise ValueError("Serve un poligono semplice senza fori")
        polygon = []
        for coordinate in rings[0]:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                raise ValueError("Vertice geofence non valido")
            lon, lat = _finite(coordinate[0], "longitudine geofence"), _finite(coordinate[1], "latitudine geofence")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Vertice geofence fuori intervallo")
            polygon.append((lon, lat))
        if polygon[0] != polygon[-1]:
            polygon.append(polygon[0])
        if len(set(polygon[:-1])) < 3:
            raise ValueError("Geofence degenerato")
        return polygon

    def boundary_clearance(self, point):
        distance = min(_distance_to_segment(point, a, b) for a, b in zip(self.polygon, self.polygon[1:]))
        return distance if _inside(point, self.polygon) else -distance

    def preview(self, *, lat, lon, rtk_status, fix_timestamp, now, imu_yaw_deg=None,
                imu_age_seconds=None, imu_yaw_sign=None, imu_yaw_offset_deg=None,
                rtcm_age_seconds=None, rtcm_connected=False, obstacle_clear=False,
                speed_kmh=None, course_over_ground_deg=None, course_age_seconds=None):
        """Return a diagnostic target; never a motor command."""
        result = {"ready": False, "reason": "", "target": None, "curvature_1pm": None,
                  "cross_track_error_m": None, "boundary_clearance_m": None,
                  "goal_distance_m": None, "obstacle_clear": bool(obstacle_clear),
                  "heading_source": None}
        if rtk_status != "FIX":
            result["reason"] = "RTK FIX assente"
            return result
        if not rtcm_connected:
            result["reason"] = "Correzioni RTCM non connesse"
            return result
        try:
            age = _finite(now, "ora") - _finite(fix_timestamp, "fix timestamp")
            correction_age = _finite(rtcm_age_seconds, "eta RTCM")
            x, y = latlon_to_local_xy(_finite(lat, "lat"), _finite(lon, "lon"), self.origin_lat, self.origin_lon)
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
        if not (0 <= age <= 1.5) or not (0 <= correction_age <= 3.0):
            result["reason"] = "Posizione o correzioni RTCM obsolete"
            return result
        try:
            if (speed_kmh is not None and _finite(speed_kmh, "velocita GNSS") >= 1.8
                    and course_age_seconds is not None
                    and 0 <= _finite(course_age_seconds, "eta course GNSS") <= 1.5):
                yaw = math.radians(90.0 - _finite(course_over_ground_deg, "course GNSS"))
                result["heading_source"] = "GNSS course over ground"
            elif imu_yaw_sign in (-1, 1) and imu_yaw_offset_deg is not None:
                imu_age = _finite(imu_age_seconds, "eta IMU")
                if not (0 <= imu_age <= 0.5):
                    result["reason"] = "IMU obsoleta"
                    return result
                yaw = math.radians(_finite(imu_yaw_offset_deg, "offset IMU") + imu_yaw_sign * _finite(imu_yaw_deg, "yaw IMU"))
                result["heading_source"] = "IMU calibrata"
            else:
                result["reason"] = "Orientamento indisponibile: serve movimento GNSS o IMU calibrata"
                return result
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
        pose = (x, y)
        clearance = self.boundary_clearance(pose)
        result["boundary_clearance_m"] = round(clearance, 3)
        if clearance < self.margin_m:
            result["reason"] = "Rover fuori geofence o troppo vicino al bordo"
            return result
        cross = min(_distance_to_segment(pose, a, b) for a, b in zip(self.path, self.path[1:]))
        result["cross_track_error_m"] = round(cross, 3)
        if cross > 0.8:
            result["reason"] = "Errore laterale oltre 0,8 m"
            return result
        goal = math.dist(pose, self.path[-1])
        result["goal_distance_m"] = round(goal, 3)
        if goal <= 0.5:
            result["reason"] = "Meta raggiunta"
            return result
        try:
            target = self.controller.target(self.path, x, y)
            curvature = self.controller.curvature(x, y, yaw, target)
        except ValueError as exc:
            result["reason"] = str(exc)
            return result
        result["target"] = {"x_east_m": round(target[0], 3), "y_north_m": round(target[1], 3)}
        result["curvature_1pm"] = round(curvature, 5)
        if not obstacle_clear:
            result["reason"] = "Monitor ostacoli non disponibile"
            return result
        result["ready"] = True
        result["reason"] = "Geometria e sensori validi; attuazione non abilitata"
        return result


def load_mission(missions_dir, filename):
    """Read only a JSON file directly inside missions_dir."""
    if not isinstance(filename, str) or not filename.endswith(".json") or Path(filename).name != filename:
        raise ValueError("Nome file missione non valido")
    path = Path(missions_dir) / filename
    if path.resolve().parent != Path(missions_dir).resolve():
        raise ValueError("Missione fuori dalla cartella missions")
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("Missione assente o troppo grande")
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


class MotorCalibration:
    """Convert requested differential wheel speeds to measured PWM percentages.

    The curves must come from physical trials. This class does not send commands.
    """

    def __init__(self, *, track_width_m, left_curve, right_curve,
                 max_pct=40, ramp_pct_per_s=20):
        self.track_width_m = _finite(track_width_m, "carreggiata")
        self.max_pct = _finite(max_pct, "limite motori")
        self.ramp_pct_per_s = _finite(ramp_pct_per_s, "rampa")
        if not (0.1 <= self.track_width_m <= 3.0 and 0 < self.max_pct <= 100
                and 0 < self.ramp_pct_per_s <= 100):
            raise ValueError("Parametri motore fuori intervallo")
        self.left_curve = self._curve(left_curve)
        self.right_curve = self._curve(right_curve)

    @staticmethod
    def _curve(rows):
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValueError("Servono almeno due misure velocita/comando")
        curve = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError("Misura motore non valida")
            speed, pct = _finite(row[0], "velocita"), _finite(row[1], "percentuale")
            if not (0 <= pct <= 100 and speed >= 0):
                raise ValueError("Misura motore fuori intervallo")
            if curve and (speed <= curve[-1][0] or pct <= curve[-1][1]):
                raise ValueError("La curva motore deve crescere strettamente")
            curve.append((speed, pct))
        if curve[0] != (0.0, 0.0):
            raise ValueError("La curva motore deve iniziare da [0, 0]")
        return curve

    @staticmethod
    def _interpolate(curve, speed):
        if speed > curve[-1][0]:
            raise ValueError("Velocita richiesta oltre la curva misurata")
        for (v0, p0), (v1, p1) in zip(curve, curve[1:]):
            if speed <= v1:
                return p0 + (speed - v0) * (p1 - p0) / (v1 - v0)
        return curve[-1][1]

    def commands(self, *, speed_mps, curvature_1pm, elapsed_s,
                 previous_left_pct=0, previous_right_pct=0):
        speed = _finite(speed_mps, "velocita richiesta")
        curvature = _finite(curvature_1pm, "curvatura")
        elapsed = _finite(elapsed_s, "intervallo controllo")
        if speed < 0 or not (0 < elapsed <= 1.0):
            raise ValueError("Velocita o intervallo controllo non validi")
        half_turn = curvature * self.track_width_m / 2.0
        if abs(half_turn) > 1.0:
            raise ValueError("Curvatura incompatibile con marcia avanti")
        left_speed = speed * (1.0 - half_turn)
        right_speed = speed * (1.0 + half_turn)
        left = min(self.max_pct, self._interpolate(self.left_curve, left_speed))
        right = min(self.max_pct, self._interpolate(self.right_curve, right_speed))
        max_step = self.ramp_pct_per_s * elapsed
        left = max(_finite(previous_left_pct, "comando precedente SX") - max_step,
                   min(_finite(previous_left_pct, "comando precedente SX") + max_step, left))
        right = max(_finite(previous_right_pct, "comando precedente DX") - max_step,
                    min(_finite(previous_right_pct, "comando precedente DX") + max_step, right))
        return round(left), round(right)
