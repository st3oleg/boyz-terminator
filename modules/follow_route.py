"""Follow a forward route on the Raspberry Pi under local supervision."""

from __future__ import annotations

import argparse
import asyncio
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


class RouteStop(Exception):
    """The active run must end and both motors must return to neutral."""


class RoverFollower:
    def __init__(self, route, profile):
        if not isinstance(profile, dict):
            raise ValueError("Profilo di guida non valido")
        if profile.get("wheels_verified") is not True:
            raise ValueError("Trazione non abilitata: ruote e copertoni da verificare")
        if profile.get("physical_estop_verified") is not True:
            raise ValueError("Trazione non abilitata: arresto fisico da verificare")
        self.route = route
        self.yaw_sign = _finite(profile.get("imu_yaw_sign"), "verso IMU")
        if self.yaw_sign not in (-1, 1):
            raise ValueError("imu_yaw_sign deve essere -1 oppure +1")
        self.cruise = _finite(profile.get("cruise_mps"), "velocita di crociera")
        self.max_speed = _finite(profile.get("max_speed_mps"), "velocita massima")
        self.clearance = _finite(profile.get("clearance_m"), "margine di arresto")
        if not (0 < self.cruise < self.max_speed <= 0.7 and self.clearance >= route.margin_m):
            raise ValueError("Velocita o margine di arresto fuori dai limiti della prova")

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
        if math.dist(self._position(gps), start) > 0.5:
            raise RouteStop("Posiziona il rover entro 0,5 m dalla partenza")
        ahead = next((point for point in self.route.path[1:] if math.dist(start, point) >= 0.5), None)
        if ahead is None or self.route.length_m < 2.0 or math.dist(start, self.route.path[-1]) < 2.0:
            raise RouteStop("La prima prova richiede un percorso aperto in avanti")
        heading = math.degrees(math.atan2(ahead[1] - start[1], ahead[0] - start[0]))
        offset = heading - self.yaw_sign * _finite(imu.get("yaw"), "yaw iniziale")
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
        result = self._guidance(gps, imu, rtcm, now, self.yaw_offset)
        if not (0 < elapsed <= 0.5):
            raise RouteStop("Ritardo nel ciclo di controllo")

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

        speed = self.cruise * min(1.0, result["goal_distance_m"] / 1.5)
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
    deadline = clock() + 120.0
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
                last_step = tick - PERIOD_S

            if last_step is not None:
                if tick - last_hold > HOLD_TIMEOUT_S:
                    raise RouteStop("Comando di presenza operatore scaduto")
                state = snapshot()
                command, plan = follower.step(*state, tick, tick - last_step)
                driver.set_motors(*command)
                last_step = tick
                log({"timestamp": state[-1], "left_pct": command[0], "right_pct": command[1], **plan})
            await asyncio.sleep(PERIOD_S)
        raise RouteStop("Tempo massimo della prova raggiunto")
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
    parser.add_argument("--profile", type=Path, help="Profilo locale misurato. Senza profilo verifica soltanto la geometria.")
    parser.add_argument("--log", type=Path, default=Path("replay_run.jsonl"))
    args = parser.parse_args()
    try:
        mission = load_mission(ROOT / "missions", MISSION)
        fence = load_geofence(ROOT / "Geofencing", GEOFENCE)
        route = RouteReplay(mission, fence)
        print(f"{MISSION}: {len(route.path)} punti, {route.length_m:.2f} m nel geofence")
        if args.profile is None:
            return 0
        profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
        follower = RoverFollower(route, profile)
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
