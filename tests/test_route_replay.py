"""Hardware-free checks for route validation and replay stop conditions."""

import json
import tempfile
import unittest
from pathlib import Path

from modules.route_replay import MotorCalibration, RouteReplay, list_mission_history, load_mission


ORIGIN_LAT = 45.0
ORIGIN_LON = 12.0


def mission():
    return {"points": [
        {"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "rtk_status": "FIX", "timestamp": 1},
        {"lat": ORIGIN_LAT, "lon": ORIGIN_LON + 0.00004, "rtk_status": "FIX", "timestamp": 2},
    ]}


def fence():
    return {"type": "Polygon", "coordinates": [[
        [ORIGIN_LON - 0.00005, ORIGIN_LAT - 0.00005],
        [ORIGIN_LON + 0.00010, ORIGIN_LAT - 0.00005],
        [ORIGIN_LON + 0.00010, ORIGIN_LAT + 0.00005],
        [ORIGIN_LON - 0.00005, ORIGIN_LAT + 0.00005],
        [ORIGIN_LON - 0.00005, ORIGIN_LAT - 0.00005],
    ]]}


class RouteReplayTests(unittest.TestCase):
    def setUp(self):
        self.route = RouteReplay(mission(), fence())
        self.live = dict(lat=ORIGIN_LAT, lon=ORIGIN_LON,
                         rtk_status="FIX", fix_timestamp=9.8, now=10,
                         imu_yaw_deg=0, imu_age_seconds=0.1,
                         imu_yaw_sign=1, imu_yaw_offset_deg=0,
                         rtcm_age_seconds=0.2, rtcm_connected=True)

    def test_valid_route_produces_target_but_no_motor_command(self):
        result = self.route.preview(**self.live)
        self.assertEqual(result["reason"], "Monitor ostacoli non disponibile")
        self.assertIsNotNone(result["target"])
        self.assertEqual(result["curvature_1pm"], 0.0)
        self.assertNotIn("motor_left_pct", result)

    def test_bad_fix_and_stale_fix_block(self):
        self.assertIn("FIX", self.route.preview(**(self.live | {"rtk_status": "FLOAT"}))["reason"])
        self.assertIn("obsolete", self.route.preview(**(self.live | {"fix_timestamp": 7}))["reason"])
        self.assertIn("RTCM", self.route.preview(**(self.live | {"rtcm_connected": False}))["reason"])

    def test_heading_and_boundary_are_required(self):
        no_heading = self.live | {"imu_yaw_offset_deg": None}
        self.assertIn("Orientamento", self.route.preview(**no_heading)["reason"])
        outside = self.live | {"lon": ORIGIN_LON + 0.00020}
        self.assertIn("geofence", self.route.preview(**outside)["reason"])

    def test_fresh_course_can_supply_heading_but_stale_course_cannot(self):
        moving = self.live | {"imu_yaw_offset_deg": None, "speed_kmh": 2.0,
                              "course_over_ground_deg": 90, "course_age_seconds": 0.2}
        self.assertEqual(self.route.preview(**moving)["heading_source"], "GNSS course over ground")
        self.assertIn("Orientamento", self.route.preview(**(moving | {"course_age_seconds": 2.0}))["reason"])

    def test_goal_stops_before_motor_plan(self):
        at_goal = self.live | {"lon": ORIGIN_LON + 0.00004}
        self.assertEqual(self.route.preview(**at_goal)["reason"], "Meta raggiunta")

    def test_trace_with_nonfix_or_jump_is_rejected(self):
        bad = mission()
        bad["points"][1]["rtk_status"] = "FLOAT"
        with self.assertRaisesRegex(ValueError, "FIX"):
            RouteReplay(bad, fence())
        bad = mission()
        bad["points"][1]["lon"] += 0.001
        with self.assertRaisesRegex(ValueError, "Salto"):
            RouteReplay(bad, fence())

    def test_route_outside_geofence_is_rejected(self):
        narrow = fence()
        for coordinate in narrow["coordinates"][0]:
            if coordinate[0] > ORIGIN_LON:
                coordinate[0] = ORIGIN_LON + 0.00001
        with self.assertRaisesRegex(ValueError, "geofence"):
            RouteReplay(mission(), narrow)

    def test_measured_motor_curves_and_ramp(self):
        calibration = MotorCalibration(
            track_width_m=0.68,
            left_curve=[[0, 0], [0.5, 20], [1.0, 40]],
            right_curve=[[0, 0], [0.5, 22], [1.0, 44]],
            max_pct=40, ramp_pct_per_s=20,
        )
        self.assertEqual(calibration.commands(speed_mps=0.5, curvature_1pm=0,
                                               elapsed_s=0.5), (10, 10))
        self.assertEqual(calibration.commands(speed_mps=0.5, curvature_1pm=0,
                                               elapsed_s=0.5,
                                               previous_left_pct=10,
                                               previous_right_pct=10), (20, 20))
        with self.assertRaisesRegex(ValueError, "oltre la curva"):
            calibration.commands(speed_mps=1.2, curvature_1pm=0, elapsed_s=0.2)

    def test_mission_loader_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "valid.json").write_text('{"points": []}', encoding="utf-8")
            self.assertEqual(load_mission(directory, "valid.json"), {"points": []})
            with self.assertRaisesRegex(ValueError, "Nome file"):
                load_mission(directory, "../valid.json")

    def test_history_reads_old_and_new_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            older = mission()
            newer = mission()
            newer["points"][0]["motor_left_pct"] = 20
            Path(directory, "old.json").write_text(json.dumps(older), encoding="utf-8")
            Path(directory, "new.json").write_text(json.dumps(newer), encoding="utf-8")
            Path(directory, "bad.json").write_text("{", encoding="utf-8")
            history = {item["filename"]: item for item in list_mission_history(directory)}
            self.assertEqual(history["old.json"]["fix_count"], 2)
            self.assertEqual(history["old.json"]["motor_samples"], 0)
            self.assertEqual(history["new.json"]["motor_samples"], 1)
            self.assertIn("error", history["bad.json"])


if __name__ == "__main__":
    unittest.main()
