"""Capture MJPEG frames from a Raspberry Pi CSI camera for HTTP clients."""

import shutil
import subprocess
import threading


def extract_jpegs(buffer, chunk):
    """Append an MJPEG chunk and return complete JPEGs, retaining split markers."""
    buffer.extend(chunk)
    frames = []
    while True:
        start = buffer.find(b"\xff\xd8")
        if start < 0:
            buffer[:] = buffer[-1:] if buffer.endswith(b"\xff") else b""
            break
        end = buffer.find(b"\xff\xd9", start + 2)
        if end < 0:
            if start:
                del buffer[:start]
            if len(buffer) > 4 * 1024 * 1024:
                buffer.clear()
            break
        frames.append(bytes(buffer[start:end + 2]))
        del buffer[:end + 2]
    return frames


class CSICamera:
    def __init__(self):
        self.command = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        self._frame = None
        self._sequence = 0
        self._reported_unavailable = False

    def start(self):
        if not self.command:
            print("[WARN] CSI: rpicam-vid/libcamera-vid non trovato.")
            return
        self._thread = threading.Thread(target=self._capture, name="csi-camera", daemon=True)
        self._thread.start()

    def latest(self):
        with self._lock:
            return self._sequence, self._frame

    def _capture(self):
        while not self._stop.is_set():
            command = [
                self.command, "--camera", "0", "-t", "0", "--codec", "mjpeg",
                "--width", "1280", "--height", "720", "--framerate", "15",
                "-n", "-o", "-",
            ]
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                )
                self._process = process
                buffer = bytearray()
                while not self._stop.is_set():
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    for frame in extract_jpegs(buffer, chunk):
                        if self._reported_unavailable:
                            print("[INFO] Camera CSI: stream ripristinato.")
                            self._reported_unavailable = False
                        with self._lock:
                            self._frame = frame
                            self._sequence += 1
            except OSError as exc:
                print(f"[WARN] CSI: acquisizione non disponibile: {exc}")
            finally:
                process = self._process
                self._process = None
                if process is not None:
                    if process.poll() is None:
                        try:
                            process.terminate()
                        except ProcessLookupError:
                            pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                with self._lock:
                    self._frame = None
                if not self._stop.is_set() and not self._reported_unavailable:
                    print("[WARN] CSI: nessun video; controllo camera e riavvio acquisizione.")
                    self._reported_unavailable = True
            self._stop.wait(2)

    def stop(self):
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
