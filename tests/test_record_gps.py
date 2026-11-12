#!/usr/bin/env python3
"""
Registratore Traiettoria GPS RTK su File JSON:
- Connessione automatica al ponte RTK (100.85.248.82:5000)
- Lettura NMEA su /dev/ttyS0 e IMU su /dev/ttyAMA4
- Campionamento per soglia di distanza metrica (es. 25-50 cm)
- Filtro qualità: registra solo su RTK FIX (o FLOAT)
- Salvataggio automatico in /home/terminator/Documents/core/missions/
- Guida manuale opzionale integrata (W/A/S/D) o passiva in ascolto
"""

import os
import sys
import time
import json
import math
import serial
import socket
import select
import termios
import tty
import threading
from datetime import datetime, timezone

# --- CONFIGURAZIONE HARDWARE & RETE ---
PORTA_GPS   = "/dev/ttyS0"
BAUD_GPS    = 115200
PORTA_IMU   = "/dev/ttyAMA4"
BAUD_IMU    = 115200
BASE_IP     = "100.85.248.82"
BASE_PORT   = 5000
MISSIONS_DIR = "/home/terminator/Documents/core/missions"

# Costante WGS84 per la proiezione metrica locale
EARTH_RADIUS = 6378137.0

# Pinout Motori (per guida integrata opzionale)
PIN_SX = 23
PIN_DX = 19
START_PCT = 20
STEP_PCT  = 10
NEUTRO_US = 1500

# --- STATO GLOBALE ---
gps_state = {
    "lat": 0.0,
    "lon": 0.0,
    "alt": 0.0,
    "sats": 0,
    "rtk_status": "NO FIX",
    "last_update": 0.0
}
imu_heading = 0.0

mission_data = {
    "mission_name": "",
    "created_at": "",
    "step_distance_m": 0.30,
    "require_fix": True,
    "origin": None,
    "points_count": 0,
    "total_distance_m": 0.0,
    "centerline_geo": [],
    "centerline_xy": []
}

lock_gps = threading.Lock()
stop_event = threading.Event()
ser_gps = None
chip = None
drive_enabled = False

# --- FUNZIONI GEOMETRICHE ---
def geo_to_xy(lat, lon, lat0, lon0):
    """Converte coordinate geografiche in metri locali X (Est) e Y (Nord)"""
    d_lat = math.radians(lat - lat0)
    d_lon = math.radians(lon - lon0)
    lat_rad = math.radians(lat0)
    x = d_lon * EARTH_RADIUS * math.cos(lat_rad)
    y = d_lat * EARTH_RADIUS
    return round(x, 4), round(y, 4)

def parse_gga(line):
    """Parsing NMEA standard per stringhe $GNGGA / $GPGGA senza dipendenze esterne"""
    try:
        parts = line.split(',')
        if len(parts) < 10 or not parts[2] or not parts[4]:
            return None
       
        # Latitudine
        raw_lat = float(parts[2])
        lat_deg = int(raw_lat / 100)
        lat_min = raw_lat - (lat_deg * 100)
        lat = lat_deg + (lat_min / 60.0)
        if parts[3].upper() == 'S':
            lat = -lat

        # Longitudine
        raw_lon = float(parts[4])
        lon_deg = int(raw_lon / 100)
        lon_min = raw_lon - (lon_deg * 100)
        lon = lon_deg + (lon_min / 60.0)
        if parts[5].upper() == 'W':
            lon = -lon

        qual = int(parts[6]) if parts[6] else 0
        sats = int(parts[7]) if parts[7] else 0
        alt = float(parts[9]) if parts[9] else 0.0

        if qual == 4:
            rtk = "FIX"
        elif qual == 5:
            rtk = "FLOAT"
        elif qual in (1, 2):
            rtk = "SINGLE"
        else:
            rtk = "NO FIX"

        return lat, lon, alt, sats, rtk
    except Exception:
        return None

# --- THREAD BRIDGE RTK & SERIALE GPS ---
def loop_rtk_bridge():
    global ser_gps
    while not stop_event.is_set():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((BASE_IP, BASE_PORT))
            while not stop_event.is_set():
                data = sock.recv(1024)
                if not data:
                    break
                if ser_gps and ser_gps.is_open:
                    ser_gps.write(data)
            sock.close()
        except Exception:
            time.sleep(2)

def loop_gps_reader():
    global ser_gps, gps_state
    while not stop_event.is_set():
        try:
            line = ser_gps.readline().decode('ascii', errors='ignore').strip()
            if line.startswith(("$GNGGA", "$GPGGA")):
                res = parse_gga(line)
                if res:
                    lat, lon, alt, sats, rtk = res
                    with lock_gps:
                        gps_state["lat"] = lat
                        gps_state["lon"] = lon
                        gps_state["alt"] = alt
                        gps_state["sats"] = sats
                        gps_state["rtk_status"] = rtk
                        gps_state["last_update"] = time.time()
        except Exception:
            time.sleep(0.05)

def loop_imu_reader():
    global imu_heading
    try:
        ser_imu = serial.Serial(PORTA_IMU, BAUD_IMU, timeout=0.1)
    except Exception:
        return
    while not stop_event.is_set():
        try:
            if ser_imu.in_waiting > 0:
                if ser_imu.read(1) == b'\x55':
                    if ser_imu.read(1) == b'\x53':
                        d = ser_imu.read(9)
                        if len(d) == 9:
                            yaw_raw = (d[5] << 8) | d[4]
                            if yaw_raw > 32767:
                                yaw_raw -= 65536
                            imu_heading = round(((yaw_raw / 32768.0) * 180.0 + 360) % 360, 1)
        except Exception:
            time.sleep(0.05)
    ser_imu.close()

# --- MOTORE DI CAMPIONAMENTO METRICO ---
def check_and_sample_point(step_dist, require_fix):
    with lock_gps:
        lat = gps_state["lat"]
        lon = gps_state["lon"]
        alt = gps_state["alt"]
        rtk = gps_state["rtk_status"]

    if lat == 0.0 or lon == 0.0:
        return False, "Attesa coordinate GPS valide..."

    if require_fix and rtk != "FIX":
        return False, f"In attesa di FIX (Attuale: {rtk})"

    if not require_fix and rtk not in ("FIX", "FLOAT"):
        return False, f"Qualita insufficiente (Attuale: {rtk})"

    # Primo punto: definisce l'origine della missione
    if mission_data["origin"] is None:
        mission_data["origin"] = {"lat": lat, "lon": lon, "alt": alt}
        pt_geo = {"index": 0, "lat": lat, "lon": lon, "alt": alt, "heading": imu_heading, "rtk": rtk}
        pt_xy = {"index": 0, "x": 0.0, "y": 0.0}
        mission_data["centerline_geo"].append(pt_geo)
        mission_data["centerline_xy"].append(pt_xy)
        mission_data["points_count"] = 1
        return True, "PRIMO PUNTO AGGANCIATO (Origine 0,0)"

    # Punti successivi: calcola distanza euclidea dall'ultimo registrato
    lat0 = mission_data["origin"]["lat"]
    lon0 = mission_data["origin"]["lon"]
    curr_x, curr_y = geo_to_xy(lat, lon, lat0, lon0)
   
    last_xy = mission_data["centerline_xy"][-1]
    dist = math.hypot(curr_x - last_xy["x"], curr_y - last_xy["y"])

    if dist >= step_dist:
        idx = len(mission_data["centerline_xy"])
        mission_data["centerline_geo"].append({
            "index": idx,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "heading": imu_heading,
            "rtk": rtk
        })
        mission_data["centerline_xy"].append({
            "index": idx,
            "x": curr_x,
            "y": curr_y
        })
        mission_data["points_count"] += 1
        mission_data["total_distance_m"] = round(mission_data["total_distance_m"] + dist, 2)
        return True, f"PUNTO #{idx} REGISTRATO (+{dist:.2f}m)"

    return False, f"In movimento (Distanza dall'ultimo: {dist:.2f}m / {step_dist:.2f}m)"

# --- GUIDA OPZIONALE TRAMITE LGPIO ---
def setup_lgpio():
    global chip
    try:
        import lgpio
        for c in [0, 4]:
            try:
                chip = lgpio.gpiochip_open(c)
                break
            except Exception:
                pass
        if chip is not None:
            lgpio.gpio_claim_output(chip, PIN_SX, 0)
            lgpio.gpio_claim_output(chip, PIN_DX, 0)
            return True
    except Exception:
        pass
    return False

def send_motors(pct_sx, pct_dx):
    if chip is None:
        return
    import lgpio
    us_sx = int(NEUTRO_US + (pct_sx * 5))
    us_dx = int(NEUTRO_US + (pct_dx * 5))
    lgpio.tx_servo(chip, PIN_SX, us_sx, 50)
    lgpio.tx_servo(chip, PIN_DX, us_dx, 50)

def step_up(val):
    if val == 0: return START_PCT
    elif val == -START_PCT: return 0
    elif val < 0: return val + STEP_PCT
    else: return min(100, val + STEP_PCT)

def step_down(val):
    if val == 0: return -START_PCT
    elif val == START_PCT: return 0
    elif val > 0: return val - STEP_PCT
    else: return max(-100, val - STEP_PCT)

# --- MAIN RUNNER ---
def main():
    global ser_gps, drive_enabled
    os.makedirs(MISSIONS_DIR, exist_ok=True)

    print("=" * 68)
    print("  TERMINATOR RTK - REGISTRATORE TRAIETTORIA GPS (JSON)")
    print("=" * 68)

    # 1. Configurazione Parametri
    nome_input = input("Nome della missione/filare [INVIO per auto]: ").strip()
    if not nome_input:
        nome_input = f"traccia_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not nome_input.endswith(".json"):
        nome_input += ".json"

    step_input = input("Distanza di campionamento in metri [default: 0.30 m]: ").strip()
    try:
        step_dist = float(step_input) if step_input else 0.30
    except ValueError:
        step_dist = 0.30

    fix_input = input("Richiedere obbligatoriamente RTK FIX (S/n) [S = solo FIX, n = anche FLOAT]: ").strip().lower()
    require_fix = False if fix_input == 'n' else True

    drive_input = input("Vuoi abilitare la GUIDA MANUALE (W/A/S/D) da questa finestra? (s/N): ").strip().lower()
    if drive_input == 's':
        if setup_lgpio():
            drive_enabled = True
            send_motors(0, 0)
            print("[MOTORI] Guida manuale W/A/S/D abilitata direttamente qui.")
        else:
            print("[AVVISO] lgpio non disponibile o occupato. Modalità solo registrazione attiva.")

    # Inizializza seriale GPS
    try:
        ser_gps = serial.Serial(PORTA_GPS, BAUD_GPS, timeout=1)
        print(f"[GPS] Porta seriale {PORTA_GPS} aperta.")
    except Exception as e:
        print(f"[ERRORE] Impossibile aprire {PORTA_GPS}: {e}")
        return

    # Avvio thread di supporto
    threading.Thread(target=loop_rtk_bridge, daemon=True).start()
    threading.Thread(target=loop_gps_reader, daemon=True).start()
    threading.Thread(target=loop_imu_reader, daemon=True).start()

    mission_data["mission_name"] = nome_input
    mission_data["created_at"] = datetime.now(timezone.utc).isoformat()
    mission_data["step_distance_m"] = step_dist
    mission_data["require_fix"] = require_fix

    print("\n" + "-" * 68)
    print(f" Destinazione: {os.path.join(MISSIONS_DIR, nome_input)}")
    print(f" Passo di registrazione: {step_dist} m | Requisito: {'RTK FIX' if require_fix else 'FIX o FLOAT'}")
    print(" Controlli: [SPAZIO] Stop Motori | [Q] Salva ed Esci")
    print("-" * 68 + "\n")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    pct_sx = 0
    pct_dx = 0
    last_msg = "Avvio campionamento..."

    try:
        while True:
            # Controllo Tastiera non-bloccante
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    r2, _, _ = select.select([sys.stdin], [], [], 0.01)
                    if r2:
                        seq = sys.stdin.read(2)
                        if seq == '[A': ch = 'w'
                        elif seq == '[B': ch = 's'
                        elif seq == '[D': ch = 'a'
                        elif seq == '[C': ch = 'd'

                ch = ch.lower()
                if ch == 'q':
                    break
                elif ch == ' ':
                    pct_sx, pct_dx = 0, 0
                    if drive_enabled: send_motors(0, 0)
                elif drive_enabled:
                    if ch == 'w':
                        pct_sx = step_up(pct_sx)
                        pct_dx = step_up(pct_dx)
                    elif ch == 's':
                        pct_sx = step_down(pct_sx)
                        pct_dx = step_down(pct_dx)
                    elif ch == 'a':
                        pct_sx = step_down(pct_sx)
                        pct_dx = step_up(pct_dx)
                    elif ch == 'd':
                        pct_sx = step_up(pct_sx)
                        pct_dx = step_down(pct_dx)
                    send_motors(pct_sx, pct_dx)

            # Esecuzione del campionamento metrico
            saved, status_str = check_and_sample_point(step_dist, require_fix)
            if saved:
                last_msg = f"\033[92m{status_str}\033[0m"
            elif "attesa" in status_str.lower():
                last_msg = f"\033[93m{status_str}\033[0m"

            with lock_gps:
                sats = gps_state["sats"]
                rtk = gps_state["rtk_status"]

            # Visualizzazione HUD dinamico a terminale
            pts = mission_data["points_count"]
            tot_d = mission_data["total_distance_m"]
            drv_str = f"SX:{pct_sx:+3d}% DX:{pct_dx:+3d}% | " if drive_enabled else ""
            sys.stdout.write(
                f"\r[{rtk:<6}] Sats:{sats:2d} | Yaw:{imu_heading:5.1f}° | {drv_str}Pts:{pts:3d} | Dist:{tot_d:5.1f}m | {last_msg:<40} "
            )
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        stop_event.set()
        if drive_enabled:
            send_motors(0, 0)
            time.sleep(0.1)
            try:
                import lgpio
                lgpio.gpiochip_close(chip)
            except Exception:
                pass
        if ser_gps and ser_gps.is_open:
            ser_gps.close()

    # Salvataggio del file JSON
    filepath = os.path.join(MISSIONS_DIR, nome_input)
    print("\n\n" + "=" * 68)
    if mission_data["points_count"] > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(mission_data, f, indent=2)
        print(f" [OK] TRAIETTORIA SALVATA CON SUCCESSO!")
        print(f" File: {filepath}")
        print(f" Punti registrati: {mission_data['points_count']}")
        print(f" Lunghezza totale: {mission_data['total_distance_m']} metri")
        print(f" Origine (0,0): Lat {mission_data['origin']['lat']:.7f}, Lon {mission_data['origin']['lon']:.7f}")
    else:
        print(" [AVVISO] Nessun punto campionato. Nessun file scritto.")
    print("=" * 68 + "\n")

if __name__ == "__main__":
    main()

