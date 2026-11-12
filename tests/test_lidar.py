#!/usr/bin/env python3
import serial
import struct
import math
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

PORTA_SERIALE = "/dev/ttyUSB0"
BAUD_RATE = 230400
PORTA_WEB = 8085

# Parametri Filtri
CONFIDENZA_MIN = 18          # Soglia minima qualità raggio laser (0-255)
N_SWEEPS_MEMORIA = 4        # Finestra mobile (4 giri = ~400ms)
MIN_COINCIDENZE = 2         # Giri minimi in cui il punto deve ricomparire
TOLLERANZA_DIST_M = 0.03    # Tolleranza stabilità da fermo (3 cm)
ROR_RADIUS_M = 0.18         # Raggio di ricerca vicini (18 cm)
ROR_MIN_NEIGHBORS = 2       # Minimo numero di punti adiacenti per non essere scartato

mappa_filtrata = {}
lock_dati = threading.Lock()

HTML_PAGE = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Terminator Rover - LiDAR COIN-D6 (Radar Filtrato)</title>
    <style>
        body {
            margin: 0;
            background: #0b0f19;
            color: #f1f5f9;
            font-family: system-ui, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            height: 100vh;
            overflow: hidden;
        }
        .bar {
            display: flex;
            gap: 18px;
            align-items: center;
            background: #1e293b;
            padding: 10px 20px;
            border-radius: 0 0 12px 12px;
            z-index: 10;
            font-size: 14px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
        }
        .bar label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
        button {
            background: #ef4444;
            color: white;
            border: none;
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            transition: background 0.2s;
        }
        button:hover { background: #dc2626; }
        .stat { color: #38bdf8; font-family: monospace; font-weight: bold; }
        canvas { flex: 1; cursor: crosshair; }
        #tooltip {
            position: fixed;
            background: rgba(15,23,42,0.95);
            border: 1px solid #38bdf8;
            padding: 6px 10px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 13px;
            pointer-events: none;
            display: none;
        }
    </style>
</head>
<body>
    <div class="bar">
        <span>🎯 <b>LiDAR COIN-D6 [Porta 8085]</b></span>
        <label>Scala: <input type="range" id="zoom" min="1" max="12" step="0.5" value="5"> <span id="zoomTxt" class="stat">5.0 m</span></label>
        <label><input type="checkbox" id="chkMuri" checked> Disegna Muri</label>
        <button onclick="punti={};fetch('/reset');">Reset</button>
        <span>Punti Filtrati: <span id="cnt" class="stat">0</span>/720</span>
    </div>
    <canvas id="cv"></canvas>
    <div id="tooltip"></div>

    <script>
        const cv = document.getElementById('cv');
        const ctx = cv.getContext('2d');
        const tooltip = document.getElementById('tooltip');
        let punti = {};

        function resize() {
            cv.width = window.innerWidth;
            cv.height = window.innerHeight - 50;
        }
        window.addEventListener('resize', resize);
        resize();

        document.getElementById('zoom').addEventListener('input', (e) => {
            document.getElementById('zoomTxt').innerText = parseFloat(e.target.value).toFixed(1) + ' m';
        });

        cv.addEventListener('mousemove', (e) => {
            const rect = cv.getBoundingClientRect();
            const cx = cv.width / 2;
            const cy = cv.height / 2;
            const maxR = parseFloat(document.getElementById('zoom').value);
            const scale = (Math.min(cx, cy) - 40) / maxR;
            const dx = (e.clientX - rect.left - cx) / scale;
            const dy = (cy - (e.clientY - rect.top)) / scale;
            const dist = Math.hypot(dx, dy);
            let ang = Math.atan2(dx, dy) * 180 / Math.PI;
            if (ang < 0) ang += 360;

            tooltip.style.display = 'block';
            tooltip.style.left = (e.clientX + 15) + 'px';
            tooltip.style.top = (e.clientY + 15) + 'px';
            tooltip.innerHTML = `Distanza: <b>${dist.toFixed(2)} m</b><br>Angolo: <b>${ang.toFixed(1)}°</b>`;
        });
        cv.addEventListener('mouseleave', () => tooltip.style.display = 'none');

        async function fetchDati() {
            try {
                const res = await fetch('/data');
                const json = await res.json();
                punti = json;
                document.getElementById('cnt').innerText = Object.keys(punti).length;
            } catch (e) {}
        }
        setInterval(fetchDati, 80);

        function draw() {
            ctx.clearRect(0, 0, cv.width, cv.height);
            const cx = cv.width / 2;
            const cy = cv.height / 2;
            const maxR = parseFloat(document.getElementById('zoom').value);
            const rPx = Math.min(cx, cy) - 40;
            const scale = rPx / maxR;

            // Cerchi metrici
            ctx.strokeStyle = '#1e293b';
            ctx.fillStyle = '#64748b';
            ctx.font = '12px monospace';
            const step = maxR <= 3 ? 0.5 : 1.0;
            for (let r = step; r <= maxR; r += step) {
                const p = r * scale;
                ctx.beginPath();
                ctx.arc(cx, cy, p, 0, Math.PI * 2);
                ctx.stroke();
                ctx.fillText(r.toFixed(1) + 'm', cx + 6, cy - p + 13);
            }

            // Assi
            ctx.strokeStyle = '#334155';
            ctx.beginPath();
            ctx.moveTo(cx - rPx, cy); ctx.lineTo(cx + rPx, cy);
            ctx.moveTo(cx, cy - rPx); ctx.lineTo(cx, cy + rPx);
            ctx.stroke();

            ctx.fillStyle = '#94a3b8';
            ctx.fillText('0° (AVANTI)', cx - 35, cy - rPx - 8);
            ctx.fillText('90° (DX)', cx + rPx + 8, cy + 4);
            ctx.fillText('180° (DIETRO)', cx - 40, cy + rPx + 18);
            ctx.fillText('270° (SX)', cx - rPx - 65, cy + 4);

            const sortedKeys = Object.keys(punti).map(Number).sort((a,b) => a - b);
            const coords = [];

            for (const ang of sortedKeys) {
                const dist = punti[ang.toFixed(1)];
                if (dist > 0.08 && dist <= maxR) {
                    const rad = ang * Math.PI / 180.0;
                    coords.push({
                        x: cx + Math.sin(rad) * (dist * scale),
                        y: cy - Math.cos(rad) * (dist * scale)
                    });
                }
            }

            // Muri perimetrali
            if (document.getElementById('chkMuri').checked && coords.length > 2) {
                ctx.strokeStyle = '#10b981';
                ctx.lineWidth = 2.5;
                ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
                ctx.beginPath();
                for (let i = 0; i < coords.length; i++) {
                    const p = coords[i];
                    if (i === 0) ctx.moveTo(p.x, p.y);
                    else {
                        const prev = coords[i - 1];
                        if (Math.hypot(p.x - prev.x, p.y - prev.y) < 0.5 * scale) {
                            ctx.lineTo(p.x, p.y);
                        } else {
                            ctx.moveTo(p.x, p.y);
                        }
                    }
                }
                ctx.stroke();
            }

            // Punti laser filtrati
            ctx.fillStyle = '#38bdf8';
            for (const p of coords) {
                ctx.beginPath();
                ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
                ctx.fill();
            }

            // Centro Rover
            ctx.fillStyle = '#ef4444';
            ctx.beginPath();
            ctx.arc(cx, cy, 6, 0, Math.PI * 2);
            ctx.fill();

            requestAnimationFrame(draw);
        }
        requestAnimationFrame(draw);
    </script>
</body>
</html>
"""

class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        global mappa_filtrata
        if self.path.startswith("/data"):
            with lock_dati:
                payload = json.dumps(mappa_filtrata)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
        elif self.path.startswith("/reset"):
            with lock_dati:
                mappa_filtrata.clear()
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def applica_filtri_avanzati(sweeps_buffer):
    """
    Applica:
    1. Finestra temporale mobile multi-giro con tolleranza di 3 cm.
    2. Shadow Point Filter (scarto rimbalzi radenti).
    3. Radius Outlier Removal (ROR).
    """
    # 1. Finestra mobile: estrazione candidati stabili presenti in >= MIN_COINCIDENZE giri
    angoli_tutti = set()
    for sw in sweeps_buffer:
        angoli_tutti.update(sw.keys())

    candidati = {}
    for ang in angoli_tutti:
        dists = [sw[ang] for sw in sweeps_buffer if ang in sw]
        if len(dists) >= MIN_COINCIDENZE:
            d_med = sorted(dists)[len(dists)//2]
            if all(abs(d - d_med) <= TOLLERANZA_DIST_M for d in dists):
                candidati[ang] = d_med

    if not candidati:
        return {}

    # 2. Shadow Point Filter sui raggi adiacenti
    angoli_ord = sorted(candidati.keys())
    dopo_shadow = {}
    for i, a in enumerate(angoli_ord):
        d = candidati[a]
        scarta = False
        # Confronta con angolo precedente e successivo se a passo ravvicinato (<= 1.0 deg)
        for offset in (-1, 1):
            idx_vicino = (i + offset) % len(angoli_ord)
            a_vic = angoli_ord[idx_vicino]
            diff_ang = abs(a - a_vic)
            if diff_ang > 180:
                diff_ang = 360 - diff_ang
            if diff_ang <= 1.0:
                diff_dist = candidati[a_vic] - d
                # Se il punto è più lontano di oltre 40 cm su un gradino angolare minimo, è rimbalzo/bordo
                if diff_dist > 0.40:
                    scarta = True
                    break
        if not scarta:
            dopo_shadow[a] = d

    # 3. Radius Outlier Removal (ROR): conversione in (x, y) e conteggio vicini entro 18 cm
    punti_xy = []
    chiavi = []
    for a, d in dopo_shadow.items():
        rad = math.radians(a)
        punti_xy.append((d * math.sin(rad), d * math.cos(rad)))
        chiavi.append(a)

    risultato_finale = {}
    r2_soglia = ROR_RADIUS_M ** 2
    n_punti = len(punti_xy)

    for i in range(n_punti):
        x0, y0 = punti_xy[i]
        vicini = 0
        for j in range(n_punti):
            if i == j:
                continue
            dx = x0 - punti_xy[j][0]
            dy = y0 - punti_xy[j][1]
            if (dx * dx + dy * dy) <= r2_soglia:
                vicini += 1
                if vicini >= ROR_MIN_NEIGHBORS:
                    break
        if vicini >= ROR_MIN_NEIGHBORS:
            ang_str = f"{chiavi[i]:.1f}"
            risultato_finale[ang_str] = dopo_shadow[chiavi[i]]

    return risultato_finale

def decodifica_lidar(stop_event):
    global mappa_filtrata
    try:
        ser = serial.Serial(PORTA_SERIALE, BAUD_RATE, timeout=0.1)
        ser.reset_input_buffer()
        print(f"[LIDAR] Connesso su {PORTA_SERIALE} @ {BAUD_RATE}")
    except Exception as e:
        print(f"[ERRORE FATALE] Impossibile aprire {PORTA_SERIALE}: {e}")
        return

    buf = bytearray()
    sweeps_buffer = deque(maxlen=N_SWEEPS_MEMORIA)
    giro_corrente = {}
    ultimo_angolo = 0.0

    while not stop_event.is_set():
        try:
            available = ser.in_waiting
            chunk = ser.read(available if available > 0 else 64)
            if not chunk:
                continue
            buf.extend(chunk)

            while len(buf) >= 10:
                idx = buf.find(b'\xaa\x55')
                if idx == -1:
                    if buf.endswith(b'\xaa'):
                        buf = buf[-1:]
                    else:
                        buf.clear()
                    break

                if idx > 0:
                    del buf[:idx]
                    idx = 0

                if len(buf) < 10:
                    break

                lsn = buf[3]
                pkt_len = 10 + lsn * 3  # Protocollo COIN-D6: 3 byte per campione
                if len(buf) < pkt_len:
                    break

                pkt = buf[:pkt_len]
                del buf[:pkt_len]

                fsa = struct.unpack("<H", pkt[4:6])[0]
                lsa = struct.unpack("<H", pkt[6:8])[0]
                start_ang = (fsa >> 1) / 64.0
                end_ang = (lsa >> 1) / 64.0
                step = ((end_ang - start_ang) % 360.0) / (lsn - 1) if lsn > 1 else 0

                # Rilevamento fine giro completo
                if start_ang < ultimo_angolo and (ultimo_angolo - start_ang) > 180.0:
                    if giro_corrente:
                        sweeps_buffer.append(giro_corrente)
                        if len(sweeps_buffer) >= 2:
                            puliti = applica_filtri_avanzati(sweeps_buffer)
                            with lock_dati:
                                mappa_filtrata = puliti
                        giro_corrente = {}
                ultimo_angolo = start_ang

                for i in range(lsn):
                    off = 10 + (i * 3)
                    conf = pkt[off]
                    raw_dist = struct.unpack("<H", pkt[off+1:off+3])[0]
                    dist_mm = raw_dist / 4.0

                    if 80 <= dist_mm <= 10000 and conf >= CONFIDENZA_MIN:
                        # NOTA DI MONTAGGIO:
                        # Il sensore LiDAR COIN-D6 è installato ruotato fisicamente di 180° rispetto al telaio.
                        # Per riallineare il fronte rover (0° Avanti, 90° DX, 270° SX), applichiamo un offset
                        # fisso di +180° a ogni raggio acquisito prima di memorizzarlo nei bin di scansione.
                        ang = (start_ang + step * i + 180.0) % 360.0
                        ang_bin = round(ang * 2) / 2.0
                        giro_corrente[ang_bin] = dist_mm / 1000.0

        except Exception:
            time.sleep(0.005)

    ser.close()

def main():
    print("=== AVVIO SERVER LIDAR COIN-D6 CON FILTRI AVANZATI ===")
    stop_event = threading.Event()
    th = threading.Thread(target=decodifica_lidar, args=(stop_event,), daemon=True)
    th.start()

    print(f"Server LiDAR attivo sulla porta {PORTA_WEB}")
    print(f"  👉 http://100.104.63.34:{PORTA_WEB} (Tailscale)")
    print(f"  👉 http://terminator.local:{PORTA_WEB} (LAN)\n")

    srv = ThreadedHTTPServer(("0.0.0.0", PORTA_WEB), WebHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiusura Server LiDAR...")
    finally:
        stop_event.set()
        srv.server_close()

if __name__ == "__main__":
    main()

