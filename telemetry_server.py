#!/usr/bin/env python3
"""
Telemetry & Control Server - Terminator Rover
- Hub centralizzato hardware: GPS (/dev/ttyS0), IMU (/dev/ttyAMA4), Motori MDDS30 (GPIO 23/19)
- Streaming video ustreamer autopilota su porta 8081 con rilevamento hardware dinamico (/dev/v4l/by-id)
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
from aiohttp import web

BASE_DIR = "/home/terminator/Documents"
STATIC_DIR = os.path.join(BASE_DIR, "static")
MISSIONS_DIR = os.path.join(BASE_DIR, "missions")
os.makedirs(MISSIONS_DIR, exist_ok=True)
sys.path.append(BASE_DIR)

from modules.gps import GPSReader
from modules.imu import IMUReader
from modules.motor import MotorDriver

# Inizializzazione Hardware
gps = GPSReader(port="/dev/ttyS0", baudrate=115200)
imu = IMUReader(port="/dev/ttyAMA4", baudrate=115200)
motors = None
video_process = None

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
current_mission_name = "Filare_1"
recorded_points = []
last_recorded_lat = None
last_recorded_lon = None

# Coordinate Antenna Base
BASE_COORDS = {"lat": 0.0, "lon": 0.0}

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
    """Trova dinamicamente il nodo video primario reale escludendo i metadati."""
    paths = sorted(glob.glob("/dev/v4l/by-id/*index0*"))
    for p in paths:
        reale = os.path.realpath(p)
        if os.path.exists(reale):
            return reale
            
    # Fallback su scansione nodi convenzionali
    for dev in ["/dev/video1", "/dev/video0", "/dev/video2"]:
        if os.path.exists(dev):
            return dev
    return None


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


# --- GESTIONE COMANDI WEBSOCKET ---

async def ws_handler(request):
    global last_heartbeat, is_dry_run, is_recording, current_mission_name, recorded_points
    global pwr_sx, pwr_dx

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    cmd_data = json.loads(msg.data)
                    msg_type = cmd_data.get("type")

                    if msg_type == "heartbeat":
                        last_heartbeat = time.time()

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

                    elif msg_type in ("stop", "estop"):
                        stop_all_motors()

                    elif msg_type == "start_record":
                        current_mission_name = cmd_data.get("mission_name", "Filare").strip() or "Filare"
                        recorded_points = []
                        is_recording = True

                    elif msg_type == "stop_record":
                        is_recording = False
                        filename = f"{current_mission_name}_{int(time.time())}.json"
                        out_path = os.path.join(MISSIONS_DIR, filename)
                        with open(out_path, "w", encoding="utf-8") as f:
                            json.dump({
                                "mission": current_mission_name,
                                "timestamp": time.time(),
                                "points_count": len(recorded_points),
                                "points": recorded_points
                            }, f, indent=2)

                        resp = json.dumps({
                            "type": "record_completed",
                            "mission": current_mission_name,
                            "points_count": len(recorded_points),
                            "centerline": recorded_points
                        })
                        for c in list(ws_clients):
                            await c.send_str(resp)

                except Exception:
                    pass
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
                "points_count": len(recorded_points)
            },

            # Compatibilita' per index.html
            "rover": {
                "lat": g_data["lat"],
                "lon": g_data["lon"],
                "alt": g_data["alt"],
                "satellites": g_data["satellites"],
                "rtk_status": g_data["rtk_status"],
                "pitch": i_data["pitch"],
                "roll": i_data["roll"],
                "yaw": i_data["yaw"]
            },
            "base": {
                "lat": BASE_COORDS["lat"],
                "lon": BASE_COORDS["lon"]
            }
        }

        raw_json = json.dumps(payload)
        for client in list(ws_clients):
            try:
                await client.send_str(raw_json)
            except Exception:
                pass


# --- LIFECYCLE APPLICAZIONE ---

async def on_startup(app):
    global motors, video_process

    # 1. Rilevamento dinamico ed avvio streaming video ustreamer su porta 8081
    try:
        subprocess.run(["pkill", "-9", "-f", "ustreamer"], stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        cam_dev = rileva_webcam_usb()
        if cam_dev:
            cmd = [
                "ustreamer",
                f"--device={cam_dev}",
                "--host=0.0.0.0",
                "--port=8081",
                "--resolution=640x480",
                "--desired-fps=15",
                "--format=mjpeg"
            ]
            video_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] Streaming video ustreamer avviato su porta 8081 ({cam_dev})")
        else:
            print("[WARN] Nessuna webcam USB rilevata per ustreamer.")
    except Exception as e:
        print(f"[WARN] Impossibile avviare ustreamer: {e}")
        video_process = None

    # 2. Inizializzazione Driver Motori MDDS30
    try:
        motors = MotorDriver()
    except Exception as e:
        print(f"[WARN] Impossibile avviare MotorDriver: {e}")
        motors = None

    # 3. Avvio Sensori & Tasks asincroni
    gps.start()
    imu.start()
    asyncio.create_task(watchdog_task())
    asyncio.create_task(telemetry_broadcaster())


async def on_cleanup(app):
    global motors, video_process

    if video_process:
        try:
            video_process.terminate()
            video_process.wait(timeout=2)
        except Exception:
            video_process.kill()

    gps.stop()
    imu.stop()
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
    print("   👉 Video Stream: http://100.73.187.83:8081/stream")
    print("   👉 Watchdog:     1.0s Fail-Safe")
    print("=" * 60 + "\n")
    web.run_app(app, host='0.0.0.0', port=8080)