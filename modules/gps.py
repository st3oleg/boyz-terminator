#!/usr/bin/env python3
"""
Modulo Lettura GPS RTK - Terminator Rover
Interfaccia seriale: /dev/ttyS0
Supporta parsing NMEA GGA/RMC con rilevamento stato RTK e coordinate decimali.
"""

import threading
import time
import serial


class GPSReader:
    def __init__(self, port="/dev/ttyS0", baudrate=115200, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.running = False
        self.thread = None
        self.ser = None

        self.lock = threading.Lock()
        self.data = {
            "lat": 0.0,
            "lon": 0.0,
            "alt": 0.0,
            "satellites": 0,
            "rtk_status": "NO FIX",
            "speed_kmh": 0.0,
            "heading": 0.0,
            "last_update": 0.0
        }

    def _convert_nmea_coord(self, raw_val: str, direction: str) -> float:
        if not raw_val or len(raw_val) < 4:
            return 0.0
        try:
            dot = raw_val.find('.')
            if dot == -1:
                return 0.0
            deg_digits = dot - 2
            deg = float(raw_val[:deg_digits])
            minutes = float(raw_val[deg_digits:])
            coord = deg + (minutes / 60.0)
            if direction in ('S', 'W'):
                coord = -coord
            return round(coord, 7)
        except Exception:
            return 0.0

    def _parse_gga(self, line: str):
        parts = line.split(',')
        if len(parts) >= 10:
            lat = self._convert_nmea_coord(parts[2], parts[3])
            lon = self._convert_nmea_coord(parts[4], parts[5])
            quality = parts[6]
            sats = int(parts[7]) if parts[7].isdigit() else 0
            alt = float(parts[9]) if parts[9] else 0.0

            rtk_map = {
                "4": "FIX",
                "5": "FLOAT",
                "1": "SINGLE",
                "2": "DGPS"
            }
            rtk_status = rtk_map.get(quality, "NO FIX")

            with self.lock:
                if lat != 0.0 and lon != 0.0:
                    self.data["lat"] = lat
                    self.data["lon"] = lon
                self.data["alt"] = round(alt, 2)
                self.data["satellites"] = sats
                self.data["rtk_status"] = rtk_status
                self.data["last_update"] = time.time()

    def _parse_rmc(self, line: str):
        parts = line.split(',')
        if len(parts) >= 9 and parts[2] == 'A':
            speed_knots = float(parts[7]) if parts[7] else 0.0
            heading = float(parts[8]) if parts[8] else 0.0
            with self.lock:
                self.data["speed_kmh"] = round(speed_knots * 1.852, 2)
                self.data["heading"] = round(heading, 1)

    def _worker(self):
        while self.running:
            try:
                if not self.ser or not self.ser.is_open:
                    self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

                raw_bytes = self.ser.readline()
                if not raw_bytes:
                    continue

                line = raw_bytes.decode('ascii', errors='replace').strip()
                if line.startswith(('$GNGGA', '$GPGGA')):
                    self._parse_gga(line)
                elif line.startswith(('$GNRMC', '$GPRMC')):
                    self._parse_rmc(line)

            except Exception:
                time.sleep(0.5)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass

    def get_data(self) -> dict:
        with self.lock:
            return dict(self.data)


if __name__ == "__main__":
    print("Test lettura GPS da /dev/ttyS0 (Ctrl+C per uscire)...")
    reader = GPSReader()
    reader.start()
    try:
        while True:
            d = reader.get_data()
            print(f"\rRTK: {d['rtk_status']:<7} | SAT: {d['satellites']:2d} | LAT: {d['lat']:.7f} | LON: {d['lon']:.7f} | ALT: {d['alt']:.1f}m", end="")
            time.sleep(0.5)
    except KeyboardInterrupt:
        reader.stop()
        print("\nTest terminato.")