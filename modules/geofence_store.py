"""Validate and store simple GeoJSON geofences in the Geofencing directory."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from modules.pure_pursuit import latlon_to_local_xy
from modules.route_replay import RouteReplay


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    return ((ab_c * ab_d < 0 and cd_a * cd_b < 0) or
            (abs(ab_c) < 1e-9 and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
             and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])) or
            (abs(ab_d) < 1e-9 and min(a[0], b[0]) <= d[0] <= max(a[0], b[0])
             and min(a[1], b[1]) <= d[1] <= max(a[1], b[1])) or
            (abs(cd_a) < 1e-9 and min(c[0], d[0]) <= a[0] <= max(c[0], d[0])
             and min(c[1], d[1]) <= a[1] <= max(c[1], d[1])) or
            (abs(cd_b) < 1e-9 and min(c[0], d[0]) <= b[0] <= max(c[0], d[0])
             and min(c[1], d[1]) <= b[1] <= max(c[1], d[1])))


def normalize_geofence(value, name="Geofence"):
    """Return one validated Feature with a closed Polygon ring."""
    polygon = RouteReplay._polygon(value)
    origin_lon, origin_lat = polygon[0]
    xy = [latlon_to_local_xy(lat, lon, origin_lat, origin_lon) for lon, lat in polygon]
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(xy, xy[1:]))) / 2.0
    if not math.isfinite(area) or area < 1.0:
        raise ValueError("Geofence troppo piccolo o degenerato")
    edges = list(zip(xy, xy[1:]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue
            if _intersects(a, b, *edges[j]):
                raise ValueError("Geofence auto-intersecante")
    label = str(name).strip() or "Geofence"
    if len(label) > 64:
        raise ValueError("Nome geofence troppo lungo")
    return {
        "type": "Feature",
        "properties": {"name": label},
        "geometry": {"type": "Polygon", "coordinates": [[list(point) for point in polygon]]},
    }


def _safe_filename(filename):
    if (not isinstance(filename, str) or not filename.endswith(".geojson")
            or Path(filename).name != filename or "\\" in filename):
        raise ValueError("Nome file geofence non valido")
    return filename


def load_geofence(directory, filename):
    path = Path(directory) / _safe_filename(filename)
    if path.resolve().parent != Path(directory).resolve():
        raise ValueError("Geofence fuori dalla cartella")
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("Geofence assente o troppo grande")
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    properties = value.get("properties") if isinstance(value, dict) else None
    name = properties.get("name", "Geofence") if isinstance(properties, dict) else "Geofence"
    return normalize_geofence(value, name)


def save_geofence(directory, name, value):
    feature = normalize_geofence(value, name)
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", feature["properties"]["name"]).strip("_")[:48] or "Geofence"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{stamp}_{uuid4().hex[:8]}.geojson"
    with (folder / filename).open("x", encoding="utf-8") as stream:
        json.dump(feature, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return filename


def list_geofences(directory, limit=200):
    files = []
    for path in Path(directory).glob("*.geojson"):
        try:
            if path.is_file():
                files.append((path.stat().st_mtime, path.name))
        except OSError:
            continue
    return [{"filename": name, "modified_at": modified} for modified, name in sorted(files, reverse=True)[:limit]]
