#!/usr/bin/env python3
"""
Telemetry & Control Server - Terminator Rover
- Hub centralizzato hardware: GPS (/dev/ttyS0), IMU (/dev/ttyAMA4), Motori MDDS30 (GPIO 23/19)
- Streaming video ustreamer autopilota su porte 8081/8082 con rilevamento webcam USB (/dev/v4l/by-id)
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
sys.path.append(BASE_DIR)

from modules.gps import GPSReader
from modules.rtcm_client import RTCMClient
from modules.imu import IMUReader
from modules.motor import MotorDriver

# Inizializzazione Hardware
gps = GPSReader(port="/dev/ttyS0", baudrate=115200)
imu = IMUReader(port="/dev/ttyAMA4", baudrate=115200)
motors = None
video_processes = {}
usb_camera_devices = []

# Valori iniziali per le EMEET C960 UVC; bilanciato corrisponde al settaggio
# già provato dall'utente (8 ms, gain 0). Night/day sono preset regolabili.
CAMERA_IMAGE_PRESETS = {
    "night": {"exposure": 250, "gain": 15, "label": "Notturno"},
    "balanced": {"exposure": 80, "gain": 0, "label": "Bilanciato"},
    "daylight": {"exposure": 40, "gain": 0, "label": "Diurno"},
}

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

pwr_sx = 0
pwr_dx = 0
is_dry_run = False
last_heartbeat = time.time()
WATCHDOG_TIMEOUT = 1.0  # Arresto se nessun segnale per oltre 1.0 secondo

# Stato Registrazione Filari GPS
is_recording = False
has_unsaved_record = False
current_mission_name = "Filare_1"
recorded_points = []
last_recorded_lat = None
last_recorded_lon = None

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

    # Fallback per sistemi senza link stabili /dev/v4l/by-id.
    if not devices:
        for dev in sorted(glob.glob("/dev/video[0-9]*")):
            if os.path.exists(dev) and dev not in devices:
                devices.append(dev)
    return devices[:2]


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
    controls = (
        "auto_exposure=1,"
        f"exposure_time_absolute={settings['exposure']},"
        f"gain={settings['gain']},backlight_compensation=0"
    )
    for device in camera_devices[:2]:
        try:
            result = subprocess.run(
                [v4l2_ctl, f"--device={device}", f"--set-ctrl={controls}"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if result.returncode == 0:
                applied += 1
            else:
                errors.append(f"{device}: {(result.stderr or result.stdout).strip()}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{device}: {exc}")

    return {
        "ok": applied == min(2, len(camera_devices)),
        "preset": preset,
        "label": settings["label"],
        "applied": applied,
        "detail": "; ".join(errors) if errors else f"Preset {settings['label']} applicato a {applied} webcam.",
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
    """Invia i valori di potenza al driver MDDS30 e aggiorna il watchdog."""
    global pwr_sx, pwr_dx, last_heartbeat
    pwr_sx = max(-100, min(100, int(sx)))
    pwr_dx = max(-100, min(100, int(dx)))
    last_heartbeat = time.time()

    if motors and not is_dry_run:
        motors.set_motors(pwr_sx, pwr_dx)


def stop_all_motors():
    """Arresto immediato e azzeramento al neutro (1500 us)."""
    global pwr_sx, pwr_dx
    pwr_sx = 0
    pwr_dx = 0
    if motors:
        motors.stop()


# --- GESTIONE FILE E ROTTE HTTP ---

async def handle_index(request):
    file_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(file_path):
        return web.FileResponse(file_path)
    return web.Response(text="File static/index.html non trovato!", status=404)


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
    global current_mission_name, recorded_points, last_recorded_lat, last_recorded_lon
    global pwr_sx, pwr_dx

    ws = web.WebSocketResponse()
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
                        command_id = cmd_data.get("command_id")
                        if command_id is not None:
                            await ws.send_str(json.dumps({
                                "type": "command_ack",
                                "command_id": command_id,
                                "server_process_ms": (time.perf_counter_ns() - received_at_ns) / 1_000_000,
                                "actuator_active": bool(motors)
                            }))

                    elif msg_type == "start_record":
                        current_mission_name = cmd_data.get("mission_name", "Filare").strip() or "Filare"
                        recorded_points = []
                        last_recorded_lat = None
                        last_recorded_lon = None
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
                                    "mission": current_mission_name,
                                    "timestamp": time.time(),
                                    "points_count": len(recorded_points),
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
    global last_heartbeat
    while True:
        await asyncio.sleep(0.1)
        if (time.time() - last_heartbeat) > WATCHDOG_TIMEOUT:
            if pwr_sx != 0 or pwr_dx != 0:
                stop_all_motors()


async def telemetry_broadcaster():
    """Invia a 5 Hz il payload unificato per la Mappa e per la dashboard FPV."""
    global last_recorded_lat, last_recorded_lon
    while True:
        await asyncio.sleep(0.2)

        g_data = gps.get_data()
        i_data = imu.get_data()

        # Campionamento filare se REC attivo (distanza minima 25 cm)
        if is_recording and g_data["lat"] != 0.0 and g_data["lon"] != 0.0:
            should_add = False
            if last_recorded_lat is None:
                should_add = True
            else:
                dist = calc_distance_m(last_recorded_lat, last_recorded_lon, g_data["lat"], g_data["lon"])
                if dist >= 0.25:
                    should_add = True

            if should_add:
                last_recorded_lat = g_data["lat"]
                last_recorded_lon = g_data["lon"]
                recorded_points.append({
                    "lat": g_data["lat"],
                    "lon": g_data["lon"],
                    "alt": g_data["alt"],
                    "rtk_status": g_data["rtk_status"],
                    "timestamp": time.time()
                })

        if not ws_clients:
            continue

        us_sx = int(1500 + (pwr_sx * 5))
        us_dx = int(1500 + (pwr_dx * 5))

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
                "left_pct": pwr_sx,
                "right_pct": pwr_dx,
                "left_us": us_sx,
                "right_us": us_dx,
                "dry_run": is_dry_run
            },
            "recorder": {
                "is_recording": is_recording,
                "can_save": has_unsaved_record,
                "points_count": len(recorded_points)
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
app.router.add_get('/impostazioni_widgets.html', handle_widgets)
app.router.add_get('/autopilota.html', handle_autopilota)
app.router.add_get('/automatico.html', handle_autopilota)
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
    print("   👉 Watchdog:     1.0s Fail-Safe")
    print("=" * 60 + "\n")
    web.run_app(app, host='0.0.0.0', port=8080)
