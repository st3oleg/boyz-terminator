#!/usr/bin/env python3
"""
Modulo Lettura IMU WT61 - Terminator Rover
Interfaccia seriale: /dev/ttyAMA4 (UART4) @ 115200 baud
Pacchetto angoli: header 0x55, flag 0x53.
"""

import threading
import time
import serial


class IMUReader:
    def __init__(self, port="/dev/ttyAMA4", baudrate=115200, timeout=0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.running = False
        self.thread = None
        self.ser = None

        self.lock = threading.Lock()
        self.data = {
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
            "last_update": 0.0
        }

    def _worker(self):
        while self.running:
            try:
                if not self.ser or not self.ser.is_open:
                    self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

                header = self.ser.read(1)
                if header == b'\x55':
                    type_byte = self.ser.read(1)
                    if type_byte == b'\x53':
                        payload = self.ser.read(9)
                        if len(payload) == 9:
                            roll = int.from_bytes(payload[0:2], byteorder='little', signed=True) / 32768.0 * 180.0
                            pitch = int.from_bytes(payload[2:4], byteorder='little', signed=True) / 32768.0 * 180.0
                            yaw = int.from_bytes(payload[4:6], byteorder='little', signed=True) / 32768.0 * 180.0

                            with self.lock:
                                self.data["roll"] = round(roll, 2)
                                self.data["pitch"] = round(pitch, 2)
                                self.data["yaw"] = round(yaw, 2)
                                self.data["last_update"] = time.time()
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
    print("Test lettura IMU da /dev/ttyAMA4 (Ctrl+C per uscire)...")
    reader = IMUReader()
    reader.start()
    try:
        while True:
            d = reader.get_data()
            print(f"\rRoll: {d['roll']:+6.1f}° | Pitch: {d['pitch']:+6.1f}° | Yaw: {d['yaw']:+6.1f}°", end="")
            time.sleep(0.1)
    except KeyboardInterrupt:
        reader.stop()
        print("\nTest terminato.")