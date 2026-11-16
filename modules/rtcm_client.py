"""Reconnectable TCP client for RTCM corrections from the Base station."""

import asyncio
import time


class RTCMClient:
    """Receive RTCM bytes and pass them to the single GPS serial owner."""

    def __init__(self, host, port, write_callback, reconnect_delay=3.0):
        self.host = host
        self.port = int(port)
        self.write_callback = write_callback
        self.reconnect_delay = reconnect_delay
        self.connected = False
        self.bytes_received = 0
        self.last_data_at = None
        self.last_error = None

    def snapshot(self):
        age = None if self.last_data_at is None else max(0.0, time.time() - self.last_data_at)
        return {
            "enabled": bool(self.host),
            "connected": self.connected,
            "bytes_received": self.bytes_received,
            "last_data_at": self.last_data_at,
            "age_seconds": age,
            "last_error": self.last_error,
        }

    async def run(self):
        if not self.host:
            return
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True
                self.last_error = None
                while True:
                    data = await reader.read(4096)
                    if not data:
                        raise ConnectionError("La Base ha chiuso lo stream RTCM")
                    written = await asyncio.to_thread(self.write_callback, data)
                    if written is False:
                        raise OSError("La seriale GNSS non è disponibile per scrivere RTCM")
                    self.bytes_received += len(data)
                    self.last_data_at = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                await asyncio.sleep(self.reconnect_delay)
            finally:
                self.connected = False
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
