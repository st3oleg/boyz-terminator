#!/usr/bin/env python3
"""
Regia Video Multi-Camera Terminator FPV:
- Rilevamento dinamico ed hardware-safe dei nodi V4L2 (/dev/v4l/by-id)
- Supporta presenza o assenza a caldo della CSI senza rompere le webcam USB
- USB 1 & 2: EMEET C960 via ustreamer
- CSI: Presa Diretta (OV5647) via rpicam-vid / libcamera-vid
- Main spotlight a tutto schermo + sidebar miniature cliccabili
- Selezione dinamica FPS e monitor PING real-time
"""

import os
import sys
import glob
import time
import json
import shutil
import http.client
import subprocess
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

PORTA_WEB = 8081

CAM_CONFIG = {
    "usb1": {"nome": "EMEET C960 (USB 1)", "tipo": "v4l2", "dev": None, "port": 8082, "attiva": False},
    "usb2": {"nome": "EMEET C960 (USB 2)", "tipo": "v4l2", "dev": None, "port": 8083, "attiva": False},
    "csi":  {"nome": "Presa Diretta CSI (OV5647)", "tipo": "csi", "dev": "CSI", "port": None, "attiva": False}
}

stato = {
    "main_cam": "usb1",
    "fps": 10
}

lock_stato = threading.Lock()

PLACEHOLDER_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06'
    b'\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14'
    b'\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b'
    b'\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01'
    b'\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00'
    b'\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
)

frame_buffer = {
    "usb1": PLACEHOLDER_JPEG,
    "usb2": PLACEHOLDER_JPEG,
    "csi":  PLACEHOLDER_JPEG
}
lock_buffer = threading.Lock()
subprocs = []
stop_threads = threading.Event()

HTML_PAGE = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TERMINATOR FPV TEST VIDEOCAMERE</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #070b14; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        
        .navbar { height: 52px; background: rgba(15, 23, 42, 0.95); border-bottom: 1px solid #1e293b; display: flex; justify-content: space-between; align-items: center; padding: 0 18px; z-index: 100; }
        .logo { font-size: 13px; font-weight: 800; color: #38bdf8; display: flex; align-items: center; gap: 8px; letter-spacing: 0.5px; }
        .dot { width: 8px; height: 8px; background: #22c55e; border-radius: 50%; box-shadow: 0 0 8px #22c55e; }
        
        .controls { display: flex; align-items: center; gap: 14px; font-size: 12px; }
        .fps-badge { cursor: pointer; background: #1e293b; border: 1px solid #334155; padding: 3px 8px; border-radius: 6px; font-weight: 700; transition: all 0.15s; }
        .fps-badge:hover, .fps-badge.active { background: #0284c7; color: #fff; border-color: #38bdf8; }
        
        .stat-badge { background: #052e16; border: 1px solid #22c55e; color: #4ade80; padding: 4px 10px; border-radius: 6px; font-family: monospace; font-size: 11px; font-weight: 700; }
        .ping-badge { background: #0f172a; border: 1px solid #38bdf8; color: #38bdf8; min-width: 90px; text-align: center; }

        .stage { flex: 1; display: flex; padding: 12px; gap: 12px; height: calc(100vh - 52px); }
        
        .main-view { flex: 1; background: #000; border-radius: 14px; border: 1px solid #1e293b; position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.8); }
        .main-view img { width: 100%; height: 100%; object-fit: contain; }
        .cam-label { position: absolute; bottom: 12px; left: 12px; background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(6px); padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid rgba(255,255,255,0.1); }
        
        .reticle { position: absolute; top: 50%; left: 50%; width: 44px; height: 44px; transform: translate(-50%, -50%); border: 1.5px dashed rgba(56, 189, 248, 0.6); border-radius: 50%; pointer-events: none; }
        .reticle::after { content: ''; position: absolute; top: 50%; left: 50%; width: 4px; height: 4px; transform: translate(-50%, -50%); background: #ef4444; border-radius: 50%; }

        .sidebar { width: 280px; display: flex; flex-direction: column; gap: 12px; }
        .thumb-card { flex: 1; background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; overflow: hidden; position: relative; cursor: pointer; transition: all 0.2s; display: flex; flex-direction: column; }
        .thumb-card:hover { border-color: #38bdf8; transform: translateY(-2px); box-shadow: 0 6px 16px rgba(56, 189, 248, 0.25); }
        .thumb-img-wrapper { flex: 1; background: #000; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; }
        .thumb-img-wrapper img { width: 100%; height: 100%; object-fit: cover; }
        
        .thumb-hover-overlay { position: absolute; inset: 0; background: rgba(2, 132, 199, 0.5); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 800; opacity: 0; transition: opacity 0.15s; }
        .thumb-card:hover .thumb-hover-overlay { opacity: 1; }
        
        .thumb-footer { padding: 6px 10px; background: #0f172a; font-size: 10px; font-weight: 700; color: #94a3b8; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #1e293b; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">
            <span class="dot"></span> <span>TERMINATOR FPV TEST VIDEOCAMERE</span>
        </div>
        <div class="controls">
            <span>FPS MAIN:</span>
            <div style="display: flex; gap: 4px;">
                <span class="fps-badge" onclick="setFps(2)">2</span>
                <span class="fps-badge" onclick="setFps(4)">4</span>
                <span class="fps-badge active" onclick="setFps(10)">10</span>
                <span class="fps-badge" onclick="setFps(15)">15</span>
                <span class="fps-badge" onclick="setFps(30)">30</span>
            </div>
            <div id="statBanda" class="stat-badge">Banda: Calcolo...</div>
            <div id="statPing" class="stat-badge ping-badge">PING: -- ms</div>
        </div>
    </div>

    <div class="stage">
        <div class="main-view">
            <img id="mainFeed" src="/stream" alt="Feed Principale">
            <div id="mainLabel" class="cam-label">CARICAMENTO...</div>
            <div class="reticle"></div>
        </div>
        <div class="sidebar" id="sidebar"></div>
    </div>

    <script>
        const CAMS = {
            "usb1": { nome: "EMEET C960 (USB 1)" },
            "usb2": { nome: "EMEET C960 (USB 2)" },
            "csi":  { nome: "Presa Diretta CSI (OV5647)" }
        };

        let currentMain = "usb1";
        let currentFps = 10;

        function renderUI() {
            document.getElementById('mainLabel').innerText = `${CAMS[currentMain].nome} - PRIMO PIANO`;
            
            const sidebar = document.getElementById('sidebar');
            sidebar.innerHTML = "";

            Object.keys(CAMS).forEach(key => {
                if (key !== currentMain) {
                    const card = document.createElement('div');
                    card.className = "thumb-card";
                    card.onclick = () => switchMain(key);
                    card.innerHTML = `
                        <div class="thumb-img-wrapper">
                            <img id="thumb-${key}" src="/snapshot?cam=${key}" alt="${CAMS[key].nome}">
                            <div class="thumb-hover-overlay">METTI IN PRIMO PIANO ↗</div>
                        </div>
                        <div class="thumb-footer">
                            <span>${CAMS[key].nome}</span>
                            <span style="color: #38bdf8;">1.0 FPS</span>
                        </div>
                    `;
                    sidebar.appendChild(card);
                }
            });

            calcolaRisparmio(currentFps);
        }

        async function switchMain(newKey) {
            currentMain = newKey;
            await fetch(`/api/config?main=${newKey}&fps=${currentFps}`);
            document.getElementById('mainFeed').src = `/stream?t=${Date.now()}`;
            renderUI();
        }

        async function setFps(val) {
            currentFps = val;
            document.querySelectorAll('.fps-badge').forEach(b => {
                b.classList.toggle('active', parseInt(b.innerText) === val);
            });
            await fetch(`/api/config?main=${currentMain}&fps=${currentFps}`);
            calcolaRisparmio(currentFps);
        }

        function calcolaRisparmio(fps) {
            const kbMain = fps * 40;
            const kbThumbs = 2 * 30;
            const totaleKBs = kbMain + kbThumbs;
            const mbOra = (totaleKBs * 3600) / 1024;
            const perc = Math.round((1 - (totaleKBs / (30 * 40))) * 100);

            const el = document.getElementById('statBanda');
            el.innerText = `Banda: ~${totaleKBs} KB/s (~${mbOra.toFixed(0)} MB/h) | -${perc}%`;
        }

        async function measurePing() {
            const t0 = performance.now();
            try {
                const res = await fetch(`/api/ping?t=${Date.now()}`);
                if (res.ok) {
                    const rtt = Math.round(performance.now() - t0);
                    const el = document.getElementById('statPing');
                    el.innerText = `PING: ${rtt} ms`;
                    if (rtt < 60) {
                        el.style.borderColor = '#22c55e';
                        el.style.color = '#4ade80';
                    } else if (rtt < 140) {
                        el.style.borderColor = '#eab308';
                        el.style.color = '#fde047';
                    } else {
                        el.style.borderColor = '#ef4444';
                        el.style.color = '#f87171';
                    }
                }
            } catch (e) {
                document.getElementById('statPing').innerText = 'PING: ERR';
            }
        }

        setInterval(() => {
            Object.keys(CAMS).forEach(key => {
                if (key !== currentMain) {
                    const img = document.getElementById(`thumb-${key}`);
                    if (img) img.src = `/snapshot?cam=${key}&t=${Date.now()}`;
                }
            });
        }, 1100);

        setInterval(measurePing, 1000);
        measurePing();
        renderUI();
    </script>
</body>
</html>
"""

def rileva_webcam_usb():
    """Trova in modo dinamico i nodi video reali (index0) scartando i canali metadati."""
    nodi_reali = []
    # I symlink in by-id puntano univocamente alle periferiche USB
    paths = sorted(glob.glob("/dev/v4l/by-id/*index0*"))
    for p in paths:
        reale = os.path.realpath(p)
        if reale not in nodi_reali:
            nodi_reali.append(reale)
            
    # Fallback se by-id non fosse popolato da udev
    if not nodi_reali:
        candidati = sorted(glob.glob("/dev/video[0-9]*"))
        for c in candidati:
            nodi_reali.append(c)

    return nodi_reali

def verifica_presenza_csi():
    """Rileva la CSI interrogando libcamera in modo case-insensitive."""
    cmd = shutil.which("rpicam-hello") or shutil.which("libcamera-hello")
    if not cmd:
        return False
    try:
        res = subprocess.run([cmd, "--list-cameras"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        out = (res.stdout + res.stderr).lower()
        return "ov5647" in out or "available cameras" in out
    except Exception:
        return False

def avvia_tutti_i_servizi():
    global subprocs
    subprocess.run(["pkill", "-9", "-f", "ustreamer"], stderr=subprocess.DEVNULL)
    subprocs.clear()

    # 1. Rileva USB reali
    usb_trovate = rileva_webcam_usb()
    print(f"[HW] Webcam USB rilevate: {usb_trovate}")

    if len(usb_trovate) >= 1:
        CAM_CONFIG["usb1"]["dev"] = usb_trovate[0]
        CAM_CONFIG["usb1"]["attiva"] = True
    if len(usb_trovate) >= 2:
        CAM_CONFIG["usb2"]["dev"] = usb_trovate[1]
        CAM_CONFIG["usb2"]["attiva"] = True

    # Avvia ustreamer per USB 1
    if CAM_CONFIG["usb1"]["attiva"]:
        dev1 = CAM_CONFIG["usb1"]["dev"]
        p1 = subprocess.Popen([
            "ustreamer",
            f"--device={dev1}",
            "--host=127.0.0.1",
            f"--port={CAM_CONFIG['usb1']['port']}",
            "--resolution=1280x720",
            "--desired-fps=15",
            "--format=MJPEG",
            "--workers=2"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocs.append(p1)
        threading.Thread(target=ustreamer_listener, args=("usb1", CAM_CONFIG["usb1"]["port"]), daemon=True).start()
        print(f"[CAM] Avviata USB 1 su {dev1}")

    # Avvia ustreamer per USB 2
    if CAM_CONFIG["usb2"]["attiva"]:
        dev2 = CAM_CONFIG["usb2"]["dev"]
        p2 = subprocess.Popen([
            "ustreamer",
            f"--device={dev2}",
            "--host=127.0.0.1",
            f"--port={CAM_CONFIG['usb2']['port']}",
            "--resolution=1280x720",
            "--desired-fps=15",
            "--format=MJPEG",
            "--workers=2"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocs.append(p2)
        threading.Thread(target=ustreamer_listener, args=("usb2", CAM_CONFIG["usb2"]["port"]), daemon=True).start()
        print(f"[CAM] Avviata USB 2 su {dev2}")

    # 2. Controllo e Avvio CSI
    csi_ok = verifica_presenza_csi()
    if csi_ok:
        CAM_CONFIG["csi"]["attiva"] = True
        threading.Thread(target=csi_listener, args=("csi",), daemon=True).start()
        print("[CAM] Rilevata e avviata Videocamera Presa Diretta CSI")
    else:
        print("[CAM] Nessuna telecamera CSI rilevata sul connettore Unicam. Salto avvio.")

def ustreamer_listener(cam_key, port):
    time.sleep(0.5)
    while not stop_threads.is_set():
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/stream")
            resp = conn.getresponse()
            if resp.status != 200:
                conn.close()
                time.sleep(1)
                continue

            buf = bytearray()
            while not stop_threads.is_set():
                chunk = resp.read(8192)
                if not chunk:
                    break
                buf.extend(chunk)
                while True:
                    start = buf.find(b"\xff\xd8")
                    if start == -1:
                        buf = buf[-1:]
                        break
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end == -1:
                        if start > 0:
                            del buf[:start]
                        break
                    frame = bytes(buf[start:end+2])
                    del buf[:end+2]
                    with lock_buffer:
                        frame_buffer[cam_key] = frame
            conn.close()
        except Exception:
            time.sleep(1)

def csi_listener(cam_key):
    cmd_name = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
    if not cmd_name:
        return

    while not stop_threads.is_set():
        # Usa il sensore 0 esplicito per la CSI OV5647
        cmd = [
            cmd_name,
            "--camera", "0",
            "-t", "0",
            "--codec", "mjpeg",
            "--width", "1280",
            "--height", "720",
            "--framerate", "15",
            "-n",
            "-o", "-"
        ]
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            buf = bytearray()
            while not stop_threads.is_set():
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                buf.extend(chunk)
                while True:
                    start = buf.find(b"\xff\xd8")
                    if start == -1:
                        buf = buf[-1:]
                        break
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end == -1:
                        if start > 0:
                            del buf[:start]
                        break
                    frame = bytes(buf[start:end+2])
                    del buf[:end+2]
                    with lock_buffer:
                        frame_buffer[cam_key] = frame
        except Exception:
            pass
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    pass
        time.sleep(2)

class StreamingHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        global stato
        parsed = urlparse(self.path)

        if parsed.path in ["/stream", "/stream.mjpg"]:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            ultimo = None
            try:
                while True:
                    with lock_stato:
                        main_cam = stato["main_cam"]
                        fps = stato["fps"]

                    with lock_buffer:
                        f = frame_buffer.get(main_cam, PLACEHOLDER_JPEG)

                    if f and f is not ultimo:
                        ultimo = f
                        self.wfile.write(b"--frame\r\n")
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(f)))
                        self.end_headers()
                        self.wfile.write(f)
                        self.wfile.write(b"\r\n")

                    time.sleep(1.0 / max(1, fps * 1.3))
            except (ConnectionResetError, BrokenPipeError):
                pass

        elif parsed.path == "/snapshot":
            params = parse_qs(parsed.query)
            target = params.get("cam", [stato["main_cam"]])[0]

            with lock_buffer:
                f = frame_buffer.get(target, PLACEHOLDER_JPEG)

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(f)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(f)

        elif parsed.path == "/api/ping":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(b'{"pong":true}')

        elif parsed.path == "/api/config":
            params = parse_qs(parsed.query)
            new_main = params.get("main", [stato["main_cam"]])[0]
            new_fps = int(params.get("fps", [stato["fps"]])[0])

            with lock_stato:
                if new_main in CAM_CONFIG:
                    stato["main_cam"] = new_main
                stato["fps"] = max(1, min(30, new_fps))

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "main": stato["main_cam"], "fps": stato["fps"]}).encode())

        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    print("="*65)
    print(" TERMINATOR FPV TEST VIDEOCAMERE")
    print(f" Interfaccia Web: http://100.73.187.83:{PORTA_WEB}")
    print("="*65)

    avvia_tutti_i_servizi()
    server = ThreadedHTTPServer(("0.0.0.0", PORTA_WEB), StreamingHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[CAMERA] Arresto regia video in corso...")
    finally:
        stop_threads.set()
        for p in subprocs:
            try:
                p.terminate()
                p.wait(timeout=1)
            except Exception:
                pass
        subprocess.run(["pkill", "-9", "-f", "ustreamer"], stderr=subprocess.DEVNULL)
        server.server_close()