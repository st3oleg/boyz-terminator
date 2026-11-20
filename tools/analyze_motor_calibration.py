#!/usr/bin/env python3
"""Build a passive speed-versus-command table from a recorded straight run.

Only FIX samples with motors armed, zero differential trim, and equal left/right
driver commands are included.  The result is diagnostic; it does not change
the rover's motor commands or install a calibration automatically.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def _eligible_sample(point: dict) -> tuple[float, float, str, int, float] | None:
    if point.get("rtk_status") != "FIX" or point.get("dry_run", False):
        return None
    try:
        trim = int(point.get("motor_trim_pct", 0))
        left = int(point.get("motor_left_output_pct", point.get("motor_left_pct")))
        right = int(point.get("motor_right_output_pct", point.get("motor_right_pct")))
        command_age = float(point.get("motor_command_age_seconds", 0.0))
        lat = float(point["lat"])
        lon = float(point["lon"])
        timestamp = float(point.get("fix_timestamp") or point["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    values = (command_age, lat, lon, timestamp)
    if (trim != 0 or left != right or left == 0 or command_age < 2.0
            or not all(math.isfinite(value) for value in values)):
        return None
    direction = "forward" if left > 0 else "reverse"
    return lat, lon, direction, abs(left), timestamp


def _distance_m(a: tuple, b: tuple) -> float:
    lat_a, lon_a = map(math.radians, a)
    lat_b, lon_b = map(math.radians, b)
    d_lat = lat_b - lat_a
    d_lon = lon_b - lon_a
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def calibration_rows(mission: dict) -> list[dict]:
    buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    previous = None
    for point in mission.get("points", []):
        current = _eligible_sample(point)
        if current is None:
            previous = None
            continue
        if previous is not None:
            lat_a, lon_a, direction_a, command_a, time_a = previous
            lat_b, lon_b, direction_b, command_b, time_b = current
            delta_t = time_b - time_a
            if direction_a == direction_b and command_a == command_b and 0 < delta_t <= 2.5:
                speed = _distance_m((lat_a, lon_a), (lat_b, lon_b)) / delta_t
                if math.isfinite(speed) and speed > 0:
                    buckets[(direction_b, command_b)].append(speed)
        previous = current

    rows = []
    for (direction, command_pct), speeds in sorted(buckets.items()):
        rows.append({
            "direction": direction,
            "driver_command_pct": command_pct,
            "samples": len(speeds),
            "speed_mps_median": round(statistics.median(speeds), 4),
            "speed_mps_min": round(min(speeds), 4),
            "speed_mps_max": round(max(speeds), 4),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mission", type=Path, help="Traccia JSON salvata dal rover")
    parser.add_argument("--output", type=Path, help="CSV destinazione (default: <traccia>.calibration.csv)")
    args = parser.parse_args()

    try:
        mission = json.loads(args.mission.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"impossibile leggere la traccia: {exc}")

    rows = calibration_rows(mission)
    output = args.output or args.mission.with_name(f"{args.mission.stem}.calibration.csv")
    columns = (
        "direction", "driver_command_pct", "samples",
        "speed_mps_median", "speed_mps_min", "speed_mps_max",
    )
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    if not rows:
        print("Nessun intervallo valido. Servono posizioni consecutive FIX, dry-run disattivato, "
              "trim 0%, comandi uguali sui due lati e almeno 2 s dall'ultimo comando.")
    else:
        print(f"Curva diagnostica: {len(rows)} livelli motore salvati in {output}")
        for row in rows:
            print(
                f"{row['direction']:7} {row['driver_command_pct']:3}% -> "
                f"mediana {row['speed_mps_median']:.3f} m/s "
                f"({row['samples']} campioni)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
