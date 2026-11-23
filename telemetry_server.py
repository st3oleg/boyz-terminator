#!/usr/bin/env python3
"""
Telemetry & Control Server - Terminator Rover
- Hub centralizzato hardware: GPS (/dev/ttyS0), IMU (/dev/ttyAMA4), Motori MDDS30 (GPIO 23/19)
- Streaming video USB su porte 8081/8082 e CSI su /camera/csi/stream
- Logica di trazione progressiva: START_PCT 20%, STEP_PCT 10%
- Watchdog di sicurezza a 1.0 secondo per arresto motori
- Registrazione tracce GPS su /home/terminator/Documents/missions/
- Serve Mappa Live (index.html), Widget (impostazioni_widgets.html) e Autopilota FPV (autopilota.html)
"""

import sys
import os
import glob
import math
import json
import asyncio
import time
import subprocess
import shutil
import aiohttp
from aiohttp import web

BASE_DIR = "/home/terminator/Documents"
STATIC_DIR = os.path.join(BASE_DIR, "static")
MISSIONS_DIR = os.path.join(BASE_DIR, "missions")
os.makedirs(MISSIONS_DIR, exist_ok=True)
GEOFENCING_DIR = os.path.join(BASE_DIR, "Geofencing")
os.makedirs(GEOFENCING_DIR, exist_ok=True)
sys.path.append(BASE_DIR)

from modules.gps import GPSReader
from modules.rtcm_client import RTCMClient
from modules.imu import IMUReader
from modules.motor import MotorDriver
from modules.route_replay import RouteReplay, load_mission, list_mission_history
from modules.geofence_store import save_geofence, load_geofence, list_geofences, normalize_geofence
from modules.csi_camera import CSICamera
from modules.camera_presets import CAMERA_IMAGE_PRESETS, fit_control_to_range, current_control_value

# Inizializzazione Hardware
gps = GPSReader(port="/dev/ttyS0", baudrate=115200)
imu = IMUReader(port="/dev/ttyAMA4", baudrate=115200)
motors = None
video_processes = {}
usb_camera_devices = []
csi_camera = CSICamera()

BASE_TAILSCALE_HOST = os.environ.get("BASE_TAILSCALE_HOST", "").strip()
BASE_RTCM_PORT = int(os.environ.get("BASE_RTCM_PORT", "5000"))
BASE_API_URL = os.environ.get("BASE_API_URL", "").strip()
if not BASE_API_URL and BASE_TAILSCALE_HOST:
    BASE_API_URL = f"http://{BASE_TAILSCALE_HOST}:8080/api/rover"
BASE_API_TOKEN = os.environ.get("BASE_API_TOKEN", "").strip()
rtcm_client = RTCMClient(BASE_TAILSCALE_HOST, BASE_RTCM_PORT, gps.write_rtcm)
base_uplink_task_handle = None
rtcm_task_handle = None

# =========================================================================
# PARAMETRI E STATO TRAZIONE (LOGICA TEST_MOTORI.PY)
# =========================================================================
START_PCT = 20  # Primo gradino da fermo per vincere l'attrito (20%)
STEP_PCT  = 10  # Incremento/decremento a ogni pressione tasto (10%)
MOTOR_TRIM_LIMIT_PCT = 20
MOTOR_TRIM_CONFIG_PATH = os.environ.get(
    "MOTOR_TRIM_CONFIG_PATH", os.path.join(BASE_DIR, "motor_calibration.json")
)


def _clamp_motor_pct(value):
    return max(-100, min(100, int(round(float(value)))))


def _clamp_motor_trim(value):
    return max(-MOTOR_TRIM_LIMIT_PCT, min(MOTOR_TRIM_LIMIT_PCT, int(round(float(value)))))


def _load_motor_trim():
    try:
        trim = _clamp_motor_trim(os.environ.get("MOTOR_TRIM_PCT", "0"))
    except (TypeError, ValueError):
        trim = 0
    try:
        with open(MOTOR_TRIM_CONFIG_PATH, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        trim = _clamp_motor_trim(config.get("differential_trim_pct", trim))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return trim


def _save_motor_trim(trim_pct):
    config_dir = os.path.dirname(MOTOR_TRIM_CONFIG_PATH) or "."
    os.makedirs(config_dir, exist_ok=True)
    temp_path = f"{MOTOR_TRIM_CONFIG_PATH}.{os.getpid()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as config_file:
        json.dump({
            "schema_version": 1,
            "differential_trim_pct": trim_pct,
            "sign": "positive boosts right and reduces left",
        }, config_file, indent=2)
        config_file.write("\n")
    os.replace(temp_path, MOTOR_TRIM_CONFIG_PATH)


def _trimmed_motor_outputs(left_pct, right_pct, trim_pct):
    """Apply relative bias; positive trim speeds up right to correct right drift."""
    left = _clamp_motor_pct(left_pct * (1.0 - trim_pct / 100.0))
    right = _clamp_motor_pct(right_pct * (1.0 + trim_pct / 100.0))
    return left, right


def _motor_us(pct):
    return int(1500 + _clamp_motor_pct(pct) * 5)


def _motor_diagnostics():
    return {
        "command_left_pct": pwr_sx,
        "command_right_pct": pwr_dx,
        "trim_pct": motor_trim_pct,
        "driver_left_pct": driver_pwr_sx,
        "driver_right_pct": driver_pwr_dx,
        "driver_left_us": _motor_us(driver_pwr_sx),
        "driver_right_us": _motor_us(driver_pwr_dx),
        "dry_run": is_dry_run,
    }


def _record_motor_event(event_type, command=None):
    if not is_recording:
        return
    recorded_events.append({
        "timestamp": time.time(),
        "event": event_type,
        "command": command,
        **_motor_diagnostics(),
    })

pwr_sx = 0
pwr_dx = 0
motor_trim_pct = _load_motor_trim()
driver_pwr_sx = 0
driver_pwr_dx = 0
last_motor_command = "startup"
last_motor_command_timestamp = time.time()
is_dry_run = False
last_heartbeat = time.time()
WATCHDOG_TIMEOUT = 1.0  # Arresto se nessun segnale per oltre 1.0 secondo

# Stato Registrazione Filari GPS
is_recording = False
has_unsaved_record = False
current_mission_name = "Filare_1"
recorded_points = []
recorded_events = []
last_recorded_fix_timestamp = 0.0

# La riproduzione e' per ora una diagnosi a motori fermi. Il controllo fisico
# richiede calibrazione e monitor ostacoli; nessun messaggio WS puo' abilitarlo.
replay_route = None
replay_mission = None
replay_preview = None

# Coordinate Antenna Base (configurabili sul Raspberry tramite environment).
def _base_coordinate(name):
    try:
        value = float(os.environ.get(name, ""))
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


BASE_COORDS = {
    "lat": _base_coordinate("BASE_LAT"),
    "lon": _base_coordinate("BASE_LON"),
}
if not (-90 <= BASE_COORDS["lat"] <= 90 and -180 <= BASE_COORDS["lon"] <= 180):
    BASE_COORDS = {"lat": 0.0, "lon": 0.0}
BASE_COORDS["available"] = (
    "BASE_LAT" in os.environ and "BASE_LON" in os.environ
    and -90 <= BASE_COORDS["lat"] <= 90
    and -180 <= BASE_COORDS["lon"] <= 180
    and (BASE_COORDS["lat"] != 0.0 or BASE_COORDS["lon"] != 0.0)
)

ws_clients = set()


def calc_distance_m(lat1, lon1, lat2, lon2):
    """Calcola la distanza geodetica in metri tra due coordinate."""
    R = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def rileva_webcam_usb():
    """Trova i nodi video USB, escludendo duplicati e nodi metadata."""
    devices = []
    paths = sorted(glob.glob("/dev/v4l/by-id/*index0*"))
    for p in paths:
        reale = os.path.realpath(p)
        if os.path.exists(reale) and reale not in devices:
            devices.append(reale)

    # Fallback: solo nodi USB di acquisizione. La CSI espone anche nodi V4L2.
    if not devices:
        for path in sorted(glob.glob("/dev/v4l/by-path/*usb*index0*")):
            device = os.path.realpath(path)
            if os.path.exists(device) and device not in devices:
                devices.append(device)
    if not devices:
        for dev in sorted(glob.glob("/dev/video[0-9]*")):
            sysfs_device = os.path.realpath(
                f"/sys/class/video4linux/{os.path.basename(dev)}/device"
            )
            index_path = f"/sys/class/video4linux/{os.path.basename(dev)}/index"
            try:
                with open(index_path, encoding="ascii") as index_file:
                    is_capture_node = index_file.read().strip() == "0"
            except OSError:
                is_capture_node = False
            if is_capture_node and "/usb" in sysfs_device and os.path.exists(dev) and dev not in devices:
                devices.append(dev)
    return devices[:2]


async def handle_csi_snapshot(request):
    _, frame = csi_camera.latest()
    if frame is None:
        return web.Response(text="Camera CSI non disponibile", status=503)
    return web.Response(body=frame, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def handle_csi_stream(request):
    if csi_camera.latest()[1] is None:
        return web.Response(text="Camera CSI non disponibile", status=503)
    response = web.StreamResponse(
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-store",
        }
    )
    await response.prepare(request)
    last_sequence = -1
    last_frame_time = time.monotonic()
    try:
        while True:
            sequence, frame = csi_camera.latest()
            if frame is not None and sequence != last_sequence:
                last_sequence = sequence
                last_frame_time = time.monotonic()
                await response.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n"
                )
            elif time.monotonic() - last_frame_time > 3:
                break
            await asyncio.sleep(0.07)
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    return response


def apply_camera_image_preset(preset: str, devices=None) -> dict:
    """Apply an allow-listed V4L2 image preset to both USB cameras."""
    settings = CAMERA_IMAGE_PRESETS.get(preset)
    if not settings:
        return {"ok": False, "preset": preset, "detail": "Preset non valido."}

    camera_devices = list(usb_camera_devices if devices is None else devices)
    if not camera_devices:
        return {"ok": False, "preset": preset, "detail": "Nessuna webcam USB rilevata."}

    v4l2_ctl = shutil.which("v4l2-ctl")
    if not v4l2_ctl:
        return {"ok": False, "preset": preset, "detail": "v4l2-ctl non installato."}

    errors = []
    applied = 0
    applied_values = []
    for index, device in enumerate(camera_devices[:2], start=1):
        try:
            limits = subprocess.run(
                [v4l2_ctl, f"--device={device}", "--list-ctrls"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            if limits.returncode != 0:
                errors.append(f"{device}: {(limits.stderr or limits.stdout).strip()}")
                continue
            exposure = fit_control_to_range(
                limits.stdout, "exposure_time_absolute", settings["exposure"]
            )
            gain = fit_control_to_range(limits.stdout, "gain", settings["gain"])
            controls = (
                "auto_exposure=1,"
                f"exposure_time_absolute={exposure},"
                f"gain={gain},backlight_compensation=0"
            )
            result = subprocess.run(
                [v4l2_ctl, f"--device={device}", f"--set-ctrl={controls}"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if result.returncode == 0:
                applied += 1
                try:
                    actual = subprocess.run(
                        [v4l2_ctl, f"--device={device}",
                         "--get-ctrl=exposure_time_absolute,gain"],
                        capture_output=True, text=True, timeout=4, check=False,
                    )
                    actual_exposure = current_control_value(actual.stdout, "exposure_time_absolute")
                    actual_gain = current_control_value(actual.stdout, "gain")
                except (OSError, subprocess.TimeoutExpired):
                    actual_exposure = actual_gain = None
                if actual_exposure is not None and actual_gain is not None:
                    applied_values.append(f"USB {index}: exp {actual_exposure}, gain {actual_gain}")
                else:
                    applied_values.append(f"USB {index}: exp {exposure}, gain {gain} (lettura non disponibile)")
            else:
                errors.append(f"{device}: {(result.stderr or result.stdout).strip()}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{device}: {exc}")

    return {
        "ok": applied == min(2, len(camera_devices)),
        "preset": preset,
        "label": settings["label"],
        "applied": applied,
        "detail": (
            "; ".join(errors) if errors else
            f"Preset {settings['label']} applicato a {applied} webcam: " + "; ".join(applied_values)
        ),
    }


# --- FUNZIONI DI SCALATA SIMMETRICHE (TEST_MOTORI.PY) ---

def step_up(val: int) -> int:
    """Aumenta la percentuale verso +100% passando per i multipli di 10."""
    if val == 0:
        return START_PCT
    elif val == -START_PCT:
        return 0
    elif val < 0:
        return val + STEP_PCT
    else:
        return min(100, val + STEP_PCT)


def step_down(val: int) -> int:
    """Diminuisce la percentuale verso -100% passando per i multipli di 10."""
    if val == 0:
        return -START_PCT
    elif val == START_PCT:
        return 0
    elif val > 0:
        return val - STEP_PCT
    else:
        return max(-100, val - STEP_PCT)


def apply_motor_speeds(sx: int, dx: int):
    """Keep nominal dashboard commands clean; apply trim only at the driver boundary."""
    global pwr_sx, pwr_dx, driver_pwr_sx, driver_pwr_dx, last_heartbeat
    pwr_sx = _clamp_motor_pct(sx)
    pwr_dx = _clamp_motor_pct(dx)
    driver_pwr_sx, driver_pwr_dx = _trimmed_motor_outputs(pwr_sx, pwr_dx, motor_trim_pct)
    last_heartbeat = time.time()

    if motors and not is_dry_run:
        motors.set_motors(driver_pwr_sx, driver_pwr_dx)


def stop_all_motors():
    """Arresto immediato e azzeramento al neutro (1500 us)."""
    global pwr_sx, pwr_dx, driver_pwr_sx, driver_pwr_dx
    pwr_sx = 0
    pwr_dx = 0
    driver_pwr_sx = 0
    driver_pwr_dx = 0
    if motors:
        motors.stop()


# --- GESTIONE FILE E ROTTE HTTP ---

async def handle_index(request):
    file_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/index.html non trovato!", status=404)


async def handle_registrazioni(request):
    file_path = os.path.join(STATIC_DIR, "registrazioni.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/registrazioni.html non trovato!", status=404)


async def handle_widgets(request):
    file_path = os.path.join(STATIC_DIR, "impostazioni_widgets.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/impostazioni_widgets.html non trovato!", status=404)


async def handle_autopilota(request):
    file_path = os.path.join(STATIC_DIR, "autopilota.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/autopilota.html non trovato!", status=404)


async def handle_riproduzione(request):
    file_path = os.path.join(STATIC_DIR, "riproduzione.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/riproduzione.html non trovato!", status=404)


async def handle_riproduzione_js(request):
    file_path = os.path.join(STATIC_DIR, "riproduzione.js")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/riproduzione.js non trovato!", status=404)


async def handle_replay_missions(request):
    names = sorted(
        name for name in os.listdir(MISSIONS_DIR)
        if name.endswith(".json") and os.path.isfile(os.path.join(MISSIONS_DIR, name))
    )
    return web.json_response({"missions": names})


async def handle_scatter_analysis(request):
    file_path = os.path.join(STATIC_DIR, "scatter_analysis.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/scatter_analysis.html non trovato!", status=404)


async def handle_runtime_config(request):
    """Expose the non-secret runtime API URL config to the locally hosted UI."""
    config_path = os.path.join(STATIC_DIR, "runtime-config.js")
    if os.path.isfile(config_path):
        return web.FileResponse(config_path, headers={"Cache-Control": "no-store"})
    return web.Response(text="window.TERMINATOR_CONFIG = { apiBaseUrl: '' };", content_type="application/javascript")


# --- GESTIONE COMANDI WEBSOCKET ---

async def ws_handler(request):
    global last_heartbeat, is_dry_run, is_recording, has_unsaved_record
    global current_mission_name, recorded_points, last_recorded_fix_timestamp
    global recorded_events, pwr_sx, pwr_dx, motor_trim_pct
    global last_motor_command, last_motor_command_timestamp
    global replay_route, replay_mission, replay_preview

    ws = web.WebSocketResponse(max_msg_size=8_000_000)
    await ws.prepare(request)
    ws_clients.add(ws)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                received_at_ns = time.perf_counter_ns()
                msg_type = "unknown"
                try:
                    cmd_data = json.loads(msg.data)
                    msg_type = cmd_data.get("type")

                    if msg_type == "heartbeat":
                        last_heartbeat = time.time()

                    elif msg_type == "replay_history":
                        history = await asyncio.to_thread(list_mission_history, MISSIONS_DIR)
                        await ws.send_str(json.dumps({"type": "replay_history_result", "history": history}))

                    elif msg_type == "replay_read":
                        filename = cmd_data.get("filename")
                        try:
                            mission = await asyncio.to_thread(load_mission, MISSIONS_DIR, filename)
                            response = {"type": "replay_trace_result", "ok": True,
                                        "filename": filename, "mission": mission,
                                        "request_id": cmd_data.get("request_id")}
                        except (ValueError, OSError, json.JSONDecodeError, TypeError) as exc:
                            response = {"type": "replay_trace_result", "ok": False,
                                        "detail": str(exc), "request_id": cmd_data.get("request_id")}
                        await ws.send_str(json.dumps(response))

                    elif msg_type == "geofence_list":
                        entries = await asyncio.to_thread(list_geofences, GEOFENCING_DIR)
                        await ws.send_str(json.dumps({"type": "geofence_list_result", "geofences": entries}))

                    elif msg_type == "geofence_read":
                        try:
                            feature = await asyncio.to_thread(load_geofence, GEOFENCING_DIR, cmd_data.get("filename"))
                            response = {"type": "geofence_read_result", "ok": True,
                                        "filename": cmd_data.get("filename"), "geofence": feature}
                        except (ValueError, OSError, json.JSONDecodeError, TypeError) as exc:
                            response = {"type": "geofence_read_result", "ok": False, "detail": str(exc)}
                        await ws.send_str(json.dumps(response))

                    elif msg_type == "geofence_save":
                        try:
                            filename = await asyncio.to_thread(
                                save_geofence, GEOFENCING_DIR, cmd_data.get("name", "Geofence"), cmd_data.get("geofence"))
                            response = {"type": "geofence_save_result", "ok": True,
                                        "filename": filename, "folder": GEOFENCING_DIR}
                        except (ValueError, OSError, TypeError) as exc:
                            response = {"type": "geofence_save_result", "ok": False, "detail": str(exc)}
                        await ws.send_str(json.dumps(response))

                    elif msg_type == "replay_load":
                        replay_route = None
                        replay_mission = None
                        replay_preview = None
                        try:
                            filename = cmd_data.get("filename")
                            mission = cmd_data.get("mission")
                            if mission is None:
                                mission = load_mission(MISSIONS_DIR, filename)
                            elif not isinstance(mission, dict):
                                raise ValueError("JSON missione non valido")
                            candidate = RouteReplay(mission, normalize_geofence(cmd_data.get("geofence")))
                        except (ValueError, OSError, json.JSONDecodeError, TypeError) as exc:
                            await ws.send_str(json.dumps({"type": "replay_load_result", "ok": False, "detail": str(exc)}))
                        else:
                            replay_route = candidate
                            replay_mission = filename
                            replay_preview = None
                            await ws.send_str(json.dumps({
                                "type": "replay_load_result", "ok": True,
                                "detail": "Traccia validata. Anteprima attiva; motori disabilitati.",
                                "mission": filename, "points_count": len(candidate.path),
                                "length_m": round(candidate.length_m, 2),
                            }))

                    elif msg_type == "replay_unload":
                        replay_route = None
                        replay_mission = None
                        replay_preview = None
                        await ws.send_str(json.dumps({"type": "replay_load_result", "ok": True, "detail": "Anteprima chiusa."}))

                    elif msg_type == "camera_image_preset":
                        preset = str(cmd_data.get("preset", ""))
                        result = await asyncio.to_thread(apply_camera_image_preset, preset)
                        await ws.send_str(json.dumps({
                            "type": "camera_image_preset_result",
                            **result,
                        }))

                    elif msg_type == "set_dry_run":
                        is_dry_run = bool(cmd_data.get("enabled", False))
                        if is_dry_run:
                            stop_all_motors()
                            last_motor_command = "dry_run_stop"
                            last_motor_command_timestamp = time.time()
                            _record_motor_event("dry_run_stop")

                    elif msg_type == "set_motor_trim":
                        old_trim = motor_trim_pct
                        try:
                            new_trim = _clamp_motor_trim(cmd_data.get("trim_pct", 0))
                        except (TypeError, ValueError):
                            saved = False
                            detail = f"Valore non valido; trim attuale {motor_trim_pct:+d}%."
                        else:
                            motor_trim_pct = new_trim
                            apply_motor_speeds(pwr_sx, pwr_dx)
                            try:
                                _save_motor_trim(motor_trim_pct)
                                saved = True
                                detail = "Trim applicato e salvato."
                            except OSError as exc:
                                saved = False
                                detail = f"Trim attivo, ma salvataggio non riuscito: {exc}"
                        last_motor_command = "motor_trim"
                        last_motor_command_timestamp = time.time()
                        _record_motor_event("motor_trim_changed", {
                            "previous_trim_pct": old_trim,
                            "applied_trim_pct": motor_trim_pct,
                            "requested_trim_pct": cmd_data.get("trim_pct"),
                        })
                        await ws.send_str(json.dumps({
                            "type": "motor_trim_result",
                            "trim_pct": motor_trim_pct,
                            "saved": saved,
                            "detail": detail,
                        }))

                    elif msg_type == "motor_step":
                        cmd = cmd_data.get("cmd", "").lower()

                        if cmd in ('w', 'arrowup'):
                            pwr_sx = step_up(pwr_sx)
                            pwr_dx = step_up(pwr_dx)
                        elif cmd in ('s', 'arrowdown'):
                            pwr_sx = step_down(pwr_sx)
                            pwr_dx = step_down(pwr_dx)
                        elif cmd in ('a', 'arrowleft'):
                            pwr_sx = step_down(pwr_sx)
                            pwr_dx = step_up(pwr_dx)
                        elif cmd in ('d', 'arrowright'):
                            pwr_sx = step_up(pwr_sx)
                            pwr_dx = step_down(pwr_dx)
                        elif cmd == '1':
                            pwr_sx = step_up(pwr_sx)
                        elif cmd == '2':
                            pwr_dx = step_up(pwr_dx)
                        elif cmd in (' ', 'stop', 'estop'):
                            pwr_sx = 0
                            pwr_dx = 0

                        apply_motor_speeds(pwr_sx, pwr_dx)
                        last_motor_command = cmd or "unknown"
                        last_motor_command_timestamp = time.time()
                        _record_motor_event("motor_step", cmd)

                        command_id = cmd_data.get("command_id")
                        if command_id is not None:
                            await ws.send_str(json.dumps({
                                "type": "command_ack",
                                "command_id": command_id,
                                "server_process_ms": (time.perf_counter_ns() - received_at_ns) / 1_000_000,
                                "actuator_active": bool(motors and not is_dry_run)
                            }))

                    elif msg_type in ("stop", "estop"):
                        stop_all_motors()
                        last_motor_command = msg_type
                        last_motor_command_timestamp = time.time()
                        _record_motor_event(msg_type)
                        command_id = cmd_data.get("command_id")
                        if command_id is not None:
                            await ws.send_str(json.dumps({
                                "type": "command_ack",
                                "command_id": command_id,
                                "server_process_ms": (time.perf_counter_ns() - received_at_ns) / 1_000_000,
                                "actuator_active": bool(motors)
                            }))

                    elif msg_type == "start_record":
                        requested_name = cmd_data.get("mission_name", "Filare")
                        if not isinstance(requested_name, str):
                            requested_name = ""
                        requested_name = requested_name.strip() or "Filare"
                        if (len(requested_name) > 64 or
                                any(not (char.isalnum() or char in " _-") for char in requested_name)):
                            await ws.send_str(json.dumps({
                                "type": "record_save_error",
                                "message": "Nome missione non valido: usa lettere, numeri, spazi, _ o - (massimo 64 caratteri).",
                            }))
                            continue
                        current_mission_name = requested_name
                        recorded_points = []
                        recorded_events = []
                        last_recorded_fix_timestamp = 0.0
                        is_recording = True
                        has_unsaved_record = True
                        print(f"[REC] Avvio '{current_mission_name}'")

                    elif msg_type == "stop_record":
                        is_recording = False
                        if not has_unsaved_record:
                            await ws.send_str(json.dumps({
                                "type": "record_save_error",
                                "message": "Non ci sono punti in attesa di salvataggio.",
                            }))
                            continue

                        filename = f"{current_mission_name}_{int(time.time())}.json"
                        out_path = os.path.join(MISSIONS_DIR, filename)
                        try:
                            os.makedirs(MISSIONS_DIR, exist_ok=True)
                            with open(out_path, "w", encoding="utf-8") as f:
                                json.dump({
                                    "schema_version": 3,
                                    "mission": current_mission_name,
                                    "timestamp": time.time(),
                                    "points_count": len(recorded_points),
                                    "sampling": "one sample per new GNSS GGA update",
                                    "motor_calibration": {
                                        "differential_trim_pct": motor_trim_pct,
                                        "trim_sign": "positive boosts right and reduces left",
                                        "nominal_percentages_are_dashboard_commands": True,
                                        "driver_percentages_are_pwm_command_setpoints": True,
                                    },
                                    "diagnostic_events": recorded_events,
                                    "points": recorded_points
                                }, f, indent=2)
                        except Exception as exc:
                            print(f"[REC] Errore salvataggio '{out_path}': {exc}")
                            await ws.send_str(json.dumps({
                                "type": "record_save_error",
                                "message": str(exc),
                            }))
                            continue

                        has_unsaved_record = False
                        print(f"[REC] Salvata '{out_path}' punti={len(recorded_points)}")

                        resp = json.dumps({
                            "type": "record_completed",
                            "mission": current_mission_name,
                            "points_count": len(recorded_points),
                            "filename": filename,
                            "file_path": out_path,
                            "diagnostic_events_count": len(recorded_events),
                            "centerline": recorded_points
                        })
                        for c in list(ws_clients):
                            try:
                                await c.send_str(resp)
                            except Exception:
                                ws_clients.discard(c)

                except Exception as exc:
                    print(f"[WS] Errore comando {msg_type!r}: {exc}")
    finally:
        ws_clients.discard(ws)
    return ws


# --- TASKS DI BACKGROUND ---

async def watchdog_task():
    """Arresta i motori se non arrivano heartbeat o comandi per oltre 1.0 secondo."""
    global last_heartbeat, last_motor_command, last_motor_command_timestamp
    while True:
        await asyncio.sleep(0.1)
        if (time.time() - last_heartbeat) > WATCHDOG_TIMEOUT:
            if pwr_sx != 0 or pwr_dx != 0:
                stop_all_motors()
                last_motor_command = "watchdog_stop"
                last_motor_command_timestamp = time.time()
                _record_motor_event("watchdog_stop")


async def telemetry_broadcaster():
    """Invia a 5 Hz il payload unificato per la Mappa e per la dashboard FPV."""
    global last_recorded_fix_timestamp, replay_preview
    while True:
        await asyncio.sleep(0.2)

        g_data = gps.get_data()
        i_data = imu.get_data()
        if replay_route is not None:
            rtcm_state = rtcm_client.snapshot()
            replay_preview = replay_route.preview(
                lat=g_data["lat"], lon=g_data["lon"],
                rtk_status=g_data["rtk_status"],
                fix_timestamp=g_data["last_update"], now=time.time(),
                imu_yaw_deg=i_data["yaw"],
                imu_age_seconds=(time.time() - i_data["last_update"] if i_data["last_update"] else None),
                rtcm_age_seconds=rtcm_state.get("age_seconds"),
                rtcm_connected=rtcm_state.get("connected", False),
                obstacle_clear=False,
                speed_kmh=g_data.get("speed_kmh"),
                course_over_ground_deg=g_data.get("heading"),
                course_age_seconds=(time.time() - g_data["course_update"] if g_data.get("course_update") else None),
            )

        # Registra una sola volta ogni nuovo GGA, normalmente a 1 Hz.
        fix_timestamp = float(g_data.get("last_update") or 0.0)
        now = time.time()
        fix_age = max(0.0, now - fix_timestamp) if fix_timestamp else None
        valid_quality = g_data.get("rtk_status") in ("FIX", "FLOAT", "DGPS", "SINGLE")
        if (
            is_recording
            and g_data["lat"] != 0.0
            and g_data["lon"] != 0.0
            and valid_quality
            and fix_timestamp > last_recorded_fix_timestamp
            and fix_timestamp - last_recorded_fix_timestamp >= 0.9
            and fix_age is not None
            and fix_age <= 3.0
        ):
            rtcm_data = rtcm_client.snapshot()
            recorded_points.append({
                "sample_index": len(recorded_points) + 1,
                "lat": g_data["lat"],
                "lon": g_data["lon"],
                "alt": g_data["alt"],
                "rtk_status": g_data["rtk_status"],
                "satellites": g_data.get("satellites"),
                "fix_timestamp": fix_timestamp,
                "fix_age_seconds": round(fix_age, 3),
                "speed_kmh": g_data.get("speed_kmh", 0.0),
                "course_over_ground_deg": g_data.get("heading", 0.0),
                "imu_yaw_deg": i_data.get("yaw", 0.0),
                "imu_pitch_deg": i_data.get("pitch", 0.0),
                "imu_roll_deg": i_data.get("roll", 0.0),
                "motor_last_command": last_motor_command,
                "motor_command_age_seconds": round(max(0.0, now - last_motor_command_timestamp), 3),
                "motor_trim_pct": motor_trim_pct,
                "motor_left_output_pct": driver_pwr_sx,
                "motor_right_output_pct": driver_pwr_dx,
                "motor_left_pct": pwr_sx,
                "motor_right_pct": pwr_dx,
                "motor_left_us": _motor_us(driver_pwr_sx),
                "motor_right_us": _motor_us(driver_pwr_dx),
                "dry_run": is_dry_run,
                "imu_age_seconds": round(max(0.0, now - i_data["last_update"]), 3) if i_data.get("last_update") else None,
                "rtcm_connected": rtcm_data.get("connected", False),
                "rtcm_bytes_received": rtcm_data.get("bytes_received", 0),
                "rtcm_age_seconds": rtcm_data.get("age_seconds"),
                "timestamp": now
            })
            last_recorded_fix_timestamp = fix_timestamp

        if not ws_clients:
            continue

        us_sx = _motor_us(driver_pwr_sx)
        us_dx = _motor_us(driver_pwr_dx)

        payload = {
            "type": "telemetry",
            "timestamp": int(time.time() * 1000),

            # Dati per autopilota.html
            "gps": {
                "lat": g_data["lat"],
                "lon": g_data["lon"],
                "alt": g_data["alt"],
                "satellites": g_data["satellites"],
                "rtk_status": g_data["rtk_status"],
                "fix_timestamp": g_data["last_update"],
                "speed_kmh": g_data.get("speed_kmh", 0.0),
                "heading": g_data.get("heading", 0.0)
            },
            "imu": {
                "pitch": i_data["pitch"],
                "roll": i_data["roll"],
                "yaw": i_data["yaw"]
            },
            "motors": {
                # left/right_pct restano i comandi nominali mostrati nel front end.
                "left_pct": pwr_sx,
                "right_pct": pwr_dx,
                "trim_pct": motor_trim_pct,
                "driver_left_pct": driver_pwr_sx,
                "driver_right_pct": driver_pwr_dx,
                "left_us": us_sx,
                "right_us": us_dx,
                "dry_run": is_dry_run,
                "last_command": last_motor_command,
                "command_age_seconds": round(max(0.0, now - last_motor_command_timestamp), 3)
            },
            "recorder": {
                "is_recording": is_recording,
                "can_save": has_unsaved_record,
                "points_count": len(recorded_points)
            },
            "replay": {
                "mission": replay_mission,
                "actuation_enabled": False,
                "preview": replay_preview,
            },

            # Compatibilita' per index.html
            "rover": {
                "lat": g_data["lat"],
                "lon": g_data["lon"],
                "alt": g_data["alt"],
                "satellites": g_data["satellites"],
                "rtk_status": g_data["rtk_status"],
                "fix_timestamp": g_data["last_update"],
                "pitch": i_data["pitch"],
                "roll": i_data["roll"],
                "yaw": i_data["yaw"]
            },
            "base": {
                "lat": BASE_COORDS["lat"],
                "lon": BASE_COORDS["lon"],
                "available": BASE_COORDS["available"]
            },
            "rtcm": rtcm_client.snapshot()
        }

        raw_json = json.dumps(payload)
        for client in list(ws_clients):
            try:
                await client.send_str(raw_json)
            except Exception:
                pass


async def rover_uplink_task(app):
    """Send the latest Rover state to the Base for live/offline map display."""
    if not BASE_API_URL:
        print("[BASE] Uplink disattivato: configura BASE_API_URL o BASE_TAILSCALE_HOST.")
        return

    session = app["base_http_session"]
    headers = {"Content-Type": "application/json"}
    if BASE_API_TOKEN:
        headers["Authorization"] = f"Bearer {BASE_API_TOKEN}"

    while True:
        g_data = gps.get_data()
        i_data = imu.get_data()
        payload = {
            "lat": g_data["lat"] if g_data["last_update"] else None,
            "lon": g_data["lon"] if g_data["last_update"] else None,
            "alt": g_data["alt"] if g_data["last_update"] else None,
            "satellites": g_data["satellites"],
            "rtk_status": g_data["rtk_status"],
            "fix_timestamp": g_data["last_update"] or None,
            "speed_kmh": g_data.get("speed_kmh", 0.0),
            "heading": g_data.get("heading", 0.0),
            "pitch": i_data.get("pitch", 0.0),
            "roll": i_data.get("roll", 0.0),
            "yaw": i_data.get("yaw", 0.0),
            "rtcm": rtcm_client.snapshot(),
        }
        try:
            async with session.post(BASE_API_URL, json=payload, headers=headers) as response:
                if response.status >= 400:
                    print(f"[BASE] Uplink HTTP {response.status}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[BASE] Uplink non disponibile: {exc}")
        await asyncio.sleep(1.0)


# --- LIFECYCLE APPLICAZIONE ---

async def on_startup(app):
    global motors, video_processes, usb_camera_devices, base_uplink_task_handle, rtcm_task_handle

    app["base_http_session"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))

    # 1. Rilevamento dinamico ed avvio dei due stream USB su porte 8081/8082
    try:
        subprocess.run(["pkill", "-9", "-f", "ustreamer"], stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        usb_camera_devices = rileva_webcam_usb()
        if not usb_camera_devices:
            print("[WARN] Nessuna webcam USB rilevata per ustreamer.")
        for index, cam_dev in enumerate(usb_camera_devices, start=1):
            port = 8080 + index
            cmd = [
                "ustreamer",
                f"--device={cam_dev}",
                "--host=0.0.0.0",
                f"--port={port}",
                "--resolution=640x480",
                "--desired-fps=15",
                "--format=mjpeg"
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            video_processes[port] = process
            time.sleep(0.2)
            if process.poll() is None:
                print(f"[INFO] Camera USB {index}: stream ustreamer su porta {port} ({cam_dev})")
            else:
                print(f"[WARN] ustreamer camera USB {index} terminato all'avvio ({cam_dev})")
        if usb_camera_devices:
            result = await asyncio.to_thread(apply_camera_image_preset, "balanced")
            level = "INFO" if result["ok"] else "WARN"
            print(f"[{level}] Preset videocamere: {result['detail']}")
    except Exception as e:
        print(f"[WARN] Impossibile avviare ustreamer: {e}")
        video_processes = {}

    csi_camera.start()

    # 2. Inizializzazione Driver Motori MDDS30
    try:
        motors = MotorDriver()
    except Exception as e:
        print(f"[WARN] Impossibile avviare MotorDriver: {e}")
        motors = None

    # 3. Avvio Sensori & Tasks asincroni
    gps.start()
    imu.start()
    if BASE_TAILSCALE_HOST:
        rtcm_task_handle = asyncio.create_task(rtcm_client.run())
    base_uplink_task_handle = asyncio.create_task(rover_uplink_task(app))
    asyncio.create_task(watchdog_task())
    asyncio.create_task(telemetry_broadcaster())


async def on_cleanup(app):
    global motors, video_processes, base_uplink_task_handle, rtcm_task_handle

    for task in (base_uplink_task_handle, rtcm_task_handle):
        if task:
            task.cancel()
    await asyncio.gather(
        *(task for task in (base_uplink_task_handle, rtcm_task_handle) if task),
        return_exceptions=True,
    )
    base_uplink_task_handle = None
    rtcm_task_handle = None

    for process in video_processes.values():
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            process.kill()
    video_processes = {}

    await asyncio.to_thread(csi_camera.stop)

    gps.stop()
    imu.stop()
    await app["base_http_session"].close()
    if motors:
        motors.close()
    for client in list(ws_clients):
        await client.close()


app = web.Application()

# Rotte Pagine Web
app.router.add_get('/', handle_index)
app.router.add_get('/index.html', handle_index)
app.router.add_get('/registrazioni.html', handle_registrazioni)
app.router.add_get('/impostazioni_widgets.html', handle_widgets)
app.router.add_get('/autopilota.html', handle_autopilota)
app.router.add_get('/riproduzione.html', handle_riproduzione)
app.router.add_get('/riproduzione.js', handle_riproduzione_js)
app.router.add_get('/api/replay/missions', handle_replay_missions)
app.router.add_get('/automatico.html', handle_autopilota)
app.router.add_get('/camera/csi/stream', handle_csi_stream)
app.router.add_get('/camera/csi/snapshot', handle_csi_snapshot)
app.router.add_get('/scatter_analysis.html', handle_scatter_analysis)
app.router.add_get('/runtime-config.js', handle_runtime_config)

# Rotta WebSocket
app.router.add_get('/ws', ws_handler)

# File statici
if os.path.exists(STATIC_DIR):
    app.router.add_static('/static/', path=STATIC_DIR, name='static')

app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("   SERVER TELEMETRIA, VIDEO E CONTROLLO TERMINATOR ATTIVO")
    print("   👉 Mappa Live:   http://100.73.187.83:8080")
    print("   👉 Autopilota:   http://100.73.187.83:8080/autopilota.html")
    print("   👉 Video Stream USB 1: http://100.73.187.83:8081/stream")
    print("   👉 Video Stream USB 2: http://100.73.187.83:8082/stream")
    print("   👉 Video Stream CSI:   http://100.73.187.83:8080/camera/csi/stream")
    print("   👉 Watchdog:     1.0s Fail-Safe")
    print("=" * 60 + "\n")
    web.run_app(app, host='0.0.0.0', port=8080)
