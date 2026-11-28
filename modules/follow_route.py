"""Follow a forward route on the Raspberry Pi under local supervision."""

from __future__ import annotations

import argparse
import asyncio
from copy import copy
from itertools import product
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

from modules.geofence_store import load_geofence
from modules.pure_pursuit import latlon_to_local_xy
from modules.route_replay import MotorCalibration, RouteReplay, _finite, load_mission


ROOT = Path(__file__).resolve().parents[1]
MISSION = "avantiDritto1_sola_andata_1795443165.json"
GEOFENCE = "GeofenceTOTALEprove.geojson"
PERIOD_S = 0.2
HOLD_TIMEOUT_S = 0.8
READY_TIMEOUT_S = 120.0
MAX_RUN_S = 240.0
MAX_APPROACH_M = 25.0
MAX_APPROACH_RUN_S = 360.0


class RouteStop(Exception):
    """The active run must end and both motors must return to neutral."""


def angle_delta(degrees):
    return (degrees + 180) % 360 - 180


def heading_reference(mission):
    """Estimate ENU yaw offset from sustained forward motion in a saved FIX trace."""
    points = mission.get("points")
    if not isinstance(points, list) or len(points) < 5 or any(not isinstance(p, dict) for p in points):
        raise ValueError("Traccia di riferimento priva di campioni validi")
    offsets = []
    for a, b, c, d, e in zip(points, points[1:], points[2:], points[3:], points[4:]):
        pwm = c.get("motor_left_output_pct", 0)
        if pwm < 30 or any(p.get("rtk_status") != "FIX" or p.get("dry_run")
                           or p.get("motor_left_output_pct") != pwm
                           or p.get("motor_right_output_pct") != pwm for p in (a, b, c, d, e)):
            continue
        if not 0 <= _finite(c.get("imu_age_seconds"), "eta IMU registrata") <= 0.5:
            continue
        dx, dy = latlon_to_local_xy(e["lat"], e["lon"], a["lat"], a["lon"])
        if math.hypot(dx, dy) >= 0.6:
            offsets.append((math.degrees(math.atan2(dy, dx)), _finite(c["imu_yaw_deg"], "yaw registrato")))
    last = points[-1]
    if (len(offsets) < 4 or last.get("rtk_status") != "FIX"
            or last.get("motor_left_output_pct") != 0 or last.get("motor_right_output_pct") != 0
            or not 0 <= _finite(last.get("imu_age_seconds"), "eta IMU finale") <= 0.5):
        raise ValueError("La traccia di riferimento richiede marcia avanti stabile e un punto finale fermo con FIX")
    return offsets, last


def approach_path(start, yaw, goal, goal_yaw, clearance, margin):
    """Find a bounded forward connector with the requested departure and arrival tangents."""
    distance = math.dist(start, goal)
    departure = math.cos(yaw), math.sin(yaw)
    arrival = math.cos(goal_yaw), math.sin(goal_yaw)
    distances = [max(1.25, distance * factor) for factor in (.3, .45, .6, .8, 1, 1.15, 1.35, 1.6, 2)]
    best = None
    for lead, tail in product(distances, repeat=2):
        b = tuple(p + lead * h for p, h in zip(start, departure))
        c = tuple(p - tail * h for p, h in zip(goal, arrival))
        segments = math.ceil((lead + distance + tail) / 0.12)
        points = []
        for index in range(segments + 1):
            t = index / segments
            s = 1 - t
            points.append(tuple(s**3 * a + 3*s*s*t * p + 3*s*t*t * q + t**3 * d
                                for a, p, q, d in zip(start, b, c, goal)))
        lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
        length = sum(lengths)
        if length > 35 or best is not None and length >= best[0] or min(lengths) < 0.01:
            continue
        for i, (a, b, c) in enumerate(zip(points, points[1:], points[2:])):
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            chord = math.dist(a, c)
            if chord < 0.01 or 2 * abs(cross) > 0.50 * lengths[i] * lengths[i + 1] * chord:
                break
        else:
            required_clearance = margin + max(lengths) / 2
            if all(clearance(p) >= required_clearance for p in points):
                best = length, points
    if best is None:
        raise RouteStop("Nessun raccordo in avanti compatibile con geofence e curvatura")
    return best


class RoverFollower:
    def __init__(self, route, profile, *, approach_reference=None):
        if not isinstance(profile, dict):
            raise ValueError("Profilo di guida non valido")
        if profile.get("wheels_verified") is not True:
            raise ValueError("Trazione non abilitata: ruote e copertoni da verificare")
        if profile.get("physical_estop_verified") is not True:
            raise ValueError("Trazione non abilitata: arresto fisico da verificare")
        self.route = route
        self.mission_route = route
        self.approach_reference = approach_reference
        self.approaching = False
        self.approach_heading_fix = None
        self.yaw_sign = _finite(profile.get("imu_yaw_sign"), "verso IMU")
        if self.yaw_sign not in (-1, 1):
            raise ValueError("imu_yaw_sign deve essere -1 oppure +1")
        self.cruise = _finite(profile.get("cruise_mps"), "velocita di crociera")
        self.max_speed = _finite(profile.get("max_speed_mps"), "velocita massima")
        self.clearance = _finite(profile.get("clearance_m"), "margine di arresto")
        if not (0 < self.cruise < self.max_speed <= 0.7 and self.clearance >= route.margin_m):
            raise ValueError("Velocita o margine di arresto fuori dai limiti della prova")
        self.run_seconds = max(120.0, 30.0 + 1.25 * route.length_m / self.cruise)
        if self.run_seconds > MAX_RUN_S:
            raise ValueError("Il percorso supera la durata massima della prova supervisionata")

        motor_profile = profile.get("motor_calibration")
        if not isinstance(motor_profile, dict):
            raise ValueError("Manca la calibrazione SX/DX")
        self.motors = MotorCalibration(**motor_profile)
        if self.motors.max_pct > 50 or self.motors.ramp_pct_per_s < 5:
            raise ValueError("La prova richiede limite PWM al massimo 50% e rampa di almeno 5%/s")
        self.yaw_offset = None
        self.previous = (0, 0)
        self.progress_pose = None
        self.progress_at = None
        self.last_fix = None

    def _position(self, gps):
        return latlon_to_local_xy(gps["lat"], gps["lon"], self.route.origin_lat, self.route.origin_lon)

    def align(self, gps, imu, rtcm, now):
        """Anchor live IMU yaw to the departure direction after manual alignment."""
        start = self.route.path[0]
        pose = self._position(gps)
        distance = math.dist(pose, start)
        ahead = next((point for point in self.route.path[1:] if math.dist(start, point) >= 0.5), None)
        if ahead is None or self.route.length_m < 2.0 or math.dist(start, self.route.path[-1]) < 2.0:
            raise RouteStop("La prima prova richiede un percorso aperto in avanti")
        heading = math.degrees(math.atan2(ahead[1] - start[1], ahead[0] - start[0]))
        yaw = _finite(imu.get("yaw"), "yaw iniziale")
        offset = heading - self.yaw_sign * yaw
        if self.approach_reference is not None:
            samples, last = self.approach_reference
            if (math.dist(pose, self._position(last)) > 0.5
                    or abs(angle_delta(yaw - last["imu_yaw_deg"])) > 8):
                raise RouteStop("Posa attuale diversa dalla fine della registrazione di riferimento")
            offsets = [math.radians(course - self.yaw_sign * raw_yaw) for course, raw_yaw in samples]
            offset = math.degrees(math.atan2(sum(map(math.sin, offsets)), sum(map(math.cos, offsets))))
            if any(abs(angle_delta(math.degrees(item) - offset)) > 10 for item in offsets):
                raise RouteStop("Direzione GNSS e yaw incoerenti nella registrazione di riferimento")
            actual_heading = self.yaw_sign * yaw + offset
            if distance > 0.5:
                if distance > MAX_APPROACH_M:
                    raise RouteStop(f"Partenza a oltre {MAX_APPROACH_M:g} m dal rover")
                length, path = approach_path(
                    pose, math.radians(actual_heading), start, math.radians(heading),
                    self.route.boundary_clearance, self.clearance,
                )
                deadline = self.run_seconds + 20 + 1.25 * length / self.cruise
                if deadline > MAX_APPROACH_RUN_S:
                    raise RouteStop("Raccordo e missione superano il tempo massimo")
                self.route = copy(self.mission_route)
                self.route.path = path
                self.route.length_m = length
                self.approaching = True
                self.run_seconds = deadline
            elif abs(angle_delta(actual_heading - heading)) > 35:
                raise RouteStop("Rover vicino alla partenza ma orientato fuori dalla traccia")
        elif distance > 0.5:
            raise RouteStop("Posiziona il rover entro 0,5 m dalla partenza")
        self._guidance(gps, imu, rtcm, now, offset)
        self.yaw_offset = offset

    def _guidance(self, gps, imu, rtcm, now, offset):
        result = self.route.guidance(
            lat=gps["lat"], lon=gps["lon"], rtk_status=gps["rtk_status"],
            fix_timestamp=gps["last_update"], now=now,
            imu_yaw_deg=imu["yaw"], imu_age_seconds=now - imu["last_update"],
            imu_yaw_offset_deg=offset, imu_yaw_sign=self.yaw_sign,
            rtcm_age_seconds=rtcm["age_seconds"], rtcm_connected=rtcm["connected"],
        )
        if not result["ready"]:
            raise RouteStop(result["reason"])
        if result["boundary_clearance_m"] < self.clearance:
            raise RouteStop("Margine di arresto dal geofence insufficiente")
        return result

    def step(self, gps, imu, rtcm, now, tick, elapsed):
        if self.yaw_offset is None:
            raise RouteStop("Orientamento iniziale non acquisito")
        if not (0 < elapsed <= 0.5):
            raise RouteStop("Ritardo nel ciclo di controllo")
        try:
            result = self._guidance(gps, imu, rtcm, now, self.yaw_offset)
        except RouteStop as exc:
            if not self.approaching or str(exc) != "Meta raggiunta":
                raise
            self.route = self.mission_route
            self.approaching = False
            result = self._guidance(gps, imu, rtcm, now, self.yaw_offset)
        result["phase"] = "raccordo" if self.approaching else "traccia"

        course_time = gps.get("course_update", 0.0)
        if 0 <= now - course_time <= 1.5:
            ground_speed = _finite(gps.get("speed_kmh"), "velocita GNSS") / 3.6
            if ground_speed > self.max_speed:
                raise RouteStop("Velocita GNSS oltre il limite")
            if ground_speed >= 0.5:
                gps_yaw = 90 - _finite(gps.get("heading"), "direzione GNSS")
                imu_yaw = self.yaw_offset + self.yaw_sign * imu["yaw"]
                disagreement = abs((gps_yaw - imu_yaw + 180) % 360 - 180)
                if disagreement > 45:
                    raise RouteStop("Direzione GNSS e IMU incoerenti")

        pose = self._position(gps)
        if self.approaching:
            yaw = self.yaw_offset + self.yaw_sign * imu["yaw"]
            if self.approach_heading_fix is None:
                self.approach_heading_fix = (*pose, yaw)
            elif math.dist(pose, self.approach_heading_fix[:2]) >= 0.6:
                x, y, old_yaw = self.approach_heading_fix
                direction = math.degrees(math.atan2(pose[1] - y, pose[0] - x))
                mean_yaw = old_yaw + 0.5 * angle_delta(yaw - old_yaw)
                if abs(angle_delta(direction - mean_yaw)) > 45:
                    raise RouteStop("Spostamento GNSS incoerente con il muso nel raccordo")
                self.approach_heading_fix = (*pose, yaw)
        fix_time = gps["last_update"]
        if self.last_fix is not None and fix_time != self.last_fix[0]:
            fix_interval = fix_time - self.last_fix[0]
            if fix_interval <= 0 or math.dist(pose, self.last_fix[1]) > self.max_speed * fix_interval:
                raise RouteStop("Spostamento GNSS incompatibile con il limite di velocita")
        self.last_fix = (fix_time, pose)
        if self.progress_pose is None or math.dist(pose, self.progress_pose) >= 0.2:
            self.progress_pose, self.progress_at = pose, tick
        elif tick - self.progress_at > 4:
            raise RouteStop("Rover fermo nonostante il comando di trazione")

        speed = self.cruise * (1.0 if self.approaching
                               else min(1.0, result["goal_distance_m"] / 1.5))
        command = self.motors.commands(
            speed_mps=speed, curvature_1pm=result["curvature_1pm"], elapsed_s=elapsed,
            previous_left_pct=self.previous[0], previous_right_pct=self.previous[1],
        )
        self.previous = command
        return command, result


async def supervise(follower, driver, snapshot, read_operator, *, log, ready=None, clock=time.monotonic):
    """One run per invocation. A lost hold or any failed check ends the run."""
    last_hold = None
    last_step = None
    last_status = None
    deadline = clock() + READY_TIMEOUT_S
    try:
        while clock() < deadline:
            tick = clock()
            keys = read_operator()
            if keys is None or b"q" in keys.lower():
                raise RouteStop("Stop operatore")
            if b" " in keys:
                last_hold = tick

            if last_step is None and ready is not None:
                state = snapshot()
                status = (state[0]["rtk_status"], state[2]["connected"],
                          0 <= state[-1] - state[1]["last_update"] <= 0.5)
                if status != last_status:
                    ready(*status)
                    last_status = status

            if last_step is None and last_hold is not None:
                follower.align(*snapshot())
                tick = clock()
                if tick - last_hold > HOLD_TIMEOUT_S:
                    raise RouteStop("Comando di presenza scaduto durante il calcolo del raccordo")
                last_step = tick - PERIOD_S
                deadline = tick + follower.run_seconds

            if last_step is not None:
                if tick - last_hold > HOLD_TIMEOUT_S:
                    raise RouteStop("Comando di presenza operatore scaduto")
                state = snapshot()
                command, plan = follower.step(*state, tick, tick - last_step)
                driver.set_motors(*command)
                last_step = tick
                log({"timestamp": state[-1], "left_pct": command[0], "right_pct": command[1], **plan})
            await asyncio.sleep(PERIOD_S)
        reason = ("Tempo massimo della prova raggiunto" if last_step is not None
                  else "Attesa avvio scaduta")
        raise RouteStop(reason)
    finally:
        driver.stop()


async def run_on_pi(follower, log):
    import select
    import termios
    import tty

    from modules.gps import GPSReader
    from modules.imu import IMUReader
    from modules.motor import MotorDriver
    from modules.rtcm_client import RTCMClient

    host = os.environ.get("BASE_TAILSCALE_HOST", "").strip()
    if not host:
        raise ValueError("BASE_TAILSCALE_HOST mancante")
    if not sys.stdin.isatty():
        raise ValueError("Serve un terminale supervisionato")
    gps, imu = GPSReader(), IMUReader()
    rtcm = RTCMClient(host, os.environ.get("BASE_RTCM_PORT", "5000"), gps.write_rtcm)
    fd = sys.stdin.fileno()
    original_tty = termios.tcgetattr(fd)
    loop = asyncio.get_running_loop()
    controller_task = asyncio.current_task()
    for sig in (signal.SIGHUP, signal.SIGTERM):
        loop.add_signal_handler(sig, controller_task.cancel)

    def read_operator():
        if not select.select([fd], [], [], 0)[0]:
            return b""
        return os.read(fd, 256) or None

    def snapshot():
        gnss_data = gps.get_data()
        imu_data = imu.get_data()
        corrections = rtcm.snapshot()
        return gnss_data, imu_data, corrections, time.time()

    def ready(fix, corrections, imu_fresh):
        print(f"Sensori: GNSS {fix}, RTCM {'connesso' if corrections else 'assente'}, "
              f"IMU {'attiva' if imu_fresh else 'in attesa'}", flush=True)

    with MotorDriver() as driver:
        gps.start()
        imu.start()
        correction_task = asyncio.create_task(rtcm.run())
        try:
            tty.setcbreak(fd)
            print("Dopo RTK FIX, tieni premuto Spazio per partire. Rilascia o premi Q per terminare.", flush=True)
            await supervise(follower, driver, snapshot, read_operator, log=log, ready=ready)
        finally:
            correction_task.cancel()
            gps.stop()
            imu.stop()
            termios.tcsetattr(fd, termios.TCSADRAIN, original_tty)
            await asyncio.gather(correction_task, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", default=MISSION, help="Nome del JSON nella cartella missions.")
    parser.add_argument("--until-sample", type=int, help="Termina il percorso al sample_index indicato.")
    parser.add_argument("--approach-reference", help="Traccia FIX con marcia avanti e posa finale ancora attuale.")
    parser.add_argument("--profile", type=Path, help="Profilo locale misurato. Senza profilo verifica soltanto la geometria.")
    parser.add_argument("--log", type=Path, default=Path("replay_run.jsonl"))
    args = parser.parse_args()
    try:
        mission = load_mission(ROOT / "missions", args.mission)
        if args.until_sample is not None:
            points = mission.get("points")
            if not isinstance(points, list):
                raise ValueError("La missione non contiene una lista di punti")
            matching = [i for i, point in enumerate(points)
                        if isinstance(point, dict) and point.get("sample_index") == args.until_sample]
            if len(matching) != 1 or matching[0] < 1:
                raise ValueError("Punto di arrivo non valido o ambiguo")
            mission["points"] = points[:matching[0] + 1]
        fence = load_geofence(ROOT / "Geofencing", GEOFENCE)
        route = RouteReplay(mission, fence)
        print(f"{args.mission}: {len(route.path)} punti, {route.length_m:.2f} m nel geofence")
        reference = None
        if args.approach_reference:
            reference = heading_reference(load_mission(ROOT / "missions", args.approach_reference))
        if args.profile is None:
            return 0
        profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
        follower = RoverFollower(route, profile, approach_reference=reference)
        # Keep the browser server and this process from sharing serial/GPIO ownership.
        # Stop the server first. GPIO claim failure also aborts before issuing motion.
        with args.log.open("x", encoding="utf-8", buffering=1) as stream:
            def log(event):
                print(json.dumps(event, ensure_ascii=False), file=stream)

            try:
                asyncio.run(run_on_pi(follower, log))
            except (RouteStop, KeyboardInterrupt, asyncio.CancelledError) as exc:
                reason = str(exc) or "Interrotto"
                log({"stop": reason})
                print(f"STOP: {reason}")
                return 0 if reason == "Meta raggiunta" else 1
            except Exception as exc:
                log({"stop": str(exc)})
                raise
    except (OSError, ValueError, TypeError, ImportError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
