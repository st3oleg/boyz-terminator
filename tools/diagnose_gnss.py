"""Raccoglie diagnostica GNSS con RTCM attivo, senza avviare la telemetria Rover."""

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
from statistics import median
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.gps import GPSReader
from modules.rtcm_client import RTCMClient


def msm4_observations(payload, satellites):
    """Return active MSM4 cells as satellite, signal, C/N0 and phase flags."""
    bit_count = len(payload) * 8
    if bit_count < 169:
        return
    value = int.from_bytes(payload, "big")

    def bits(offset, width):
        return (value >> (bit_count - offset - width)) & ((1 << width) - 1)

    signals = [signal for signal in range(1, 33) if bits(136 + signal, 1)]
    cell_start = 169
    cell_end = cell_start + len(satellites) * len(signals)
    if bit_count < cell_end:
        return
    candidates = ((satellite, signal) for satellite in satellites for signal in signals)
    cells = [
        pair for index, pair in enumerate(candidates)
        if bits(cell_start + index, 1)
    ]

    # MSM4 stores 18 bits per satellite, then one array per observation field.
    start = cell_end + 18 * len(satellites)
    count = len(cells)
    if bit_count < start + 48 * count:
        return
    phase_start = start + 15 * count
    lock_start = phase_start + 22 * count
    half_cycle_start = lock_start + 4 * count
    cn0_start = half_cycle_start + count
    for index, (satellite, signal) in enumerate(cells):
        yield (
            satellite, signal,
            bits(cn0_start + 6 * index, 6),
            bits(phase_start + 22 * index, 22) != (1 << 21),
            bits(lock_start + 4 * index, 4),
            bits(half_cycle_start + index, 1),
        )


class GNSSReport:
    def __init__(self):
        self.sentences = Counter()
        self.gga_quality = Counter()
        self.gga_diff_age = Counter()
        self.gga_diff_station = Counter()
        self.satellites = []
        self.hdop = []
        self.used_satellites = {}
        self.signals = {}
        self.rtcm_types = Counter()
        self.rtcm_station_ids = {}
        self.rtcm_satellites = {}
        self.msm4_signals = {}
        self.buffer = bytearray()

    def read_nmea(self, line):
        fields = line.split("*", 1)[0].split(",")
        identifier = fields[0]
        if not identifier.startswith("$") or len(identifier) != 6:
            return
        kind = identifier[-3:]
        self.sentences[identifier[1:]] += 1
        if kind == "GGA" and len(fields) > 8:
            self.gga_quality[fields[6] or "assente"] += 1
            diff_age = fields[13] if len(fields) > 13 else ""
            diff_station = fields[14] if len(fields) > 14 else ""
            self.gga_diff_age[diff_age or "assente"] += 1
            self.gga_diff_station[diff_station or "assente"] += 1
            try:
                self.satellites.append(int(fields[7]))
                self.hdop.append(float(fields[8]))
            except ValueError:
                pass
        elif kind == "GSA" and len(fields) >= 18:
            system = fields[18] if len(fields) > 18 else ""
            key = identifier[1:] + (f"/{system}" if system else "")
            self.used_satellites[key] = [value for value in fields[3:15] if value]
        elif kind == "GSV" and len(fields) >= 4:
            groups = fields[4:]
            signal = groups.pop() if len(groups) % 4 == 1 else ""
            key = identifier[1:] + (f"/{signal}" if signal else "")
            satellites = self.signals.setdefault(key, {})
            for satellite, snr in zip(groups[::4], groups[3::4]):
                if satellite and snr.isdigit() and int(snr) > 0:
                    satellites.setdefault(satellite, []).append(int(snr))

    def read_rtcm(self, chunk):
        self.buffer.extend(chunk)
        while len(self.buffer) >= 3:
            if self.buffer[0] != 0xD3 or self.buffer[1] & 0xFC:
                del self.buffer[0]
                continue
            size = ((self.buffer[1] & 3) << 8) | self.buffer[2]
            end = size + 6
            if len(self.buffer) < end:
                break
            payload = self.buffer[3:3 + size]
            del self.buffer[:end]
            if size < 2:
                continue
            kind = (payload[0] << 4) | (payload[1] >> 4)
            self.rtcm_types[kind] += 1
            if size >= 3 and (kind in (1005, 1006) or 107 <= kind // 10 <= 113 and 1 <= kind % 10 <= 7):
                station_id = ((payload[1] & 0x0F) << 8) | payload[2]
                self.rtcm_station_ids.setdefault(kind, Counter())[station_id] += 1
            if size >= 18 and 107 <= kind // 10 <= 113 and 1 <= kind % 10 <= 7:
                # RTCM MSM: maschera satelliti di 64 bit dall'offset 73.
                mask = (int.from_bytes(payload[9:18], "big") >> 7) & ((1 << 64) - 1)
                satellites = [sat for sat in range(1, 65) if mask & (1 << (64 - sat))]
                self.rtcm_satellites[kind] = satellites
                if kind % 10 == 4:
                    self.read_msm4(kind, payload, satellites)

    def read_msm4(self, kind, payload, satellites):
        for satellite, signal, cn0, phase_valid, lock, half_cycle in msm4_observations(payload, satellites):
            key = f"{kind}/{signal}"
            stats = self.msm4_signals.setdefault(key, {
                "cn0": [], "phase_satellite_slots": set(), "missing_phase": 0,
                "lock_indicator_zero": 0, "half_cycle_flag": 0,
            })
            stats["cn0"].append(cn0)
            if phase_valid:
                stats["phase_satellite_slots"].add(satellite)
                stats["lock_indicator_zero"] += lock == 0
                stats["half_cycle_flag"] += half_cycle
            else:
                stats["missing_phase"] += 1

    def summary(self, rtcm):
        return {
            "nmea": dict(sorted(self.sentences.items())),
            "gga_quality_4_fix_5_float": dict(self.gga_quality),
            "gga_differential_age_reported": dict(self.gga_diff_age),
            "gga_differential_station_reported": dict(self.gga_diff_station),
            "gga_satellites_median": median(self.satellites) if self.satellites else None,
            "gga_hdop_median": median(self.hdop) if self.hdop else None,
            "gsa_used_latest": self.used_satellites,
            "gsv_cn0_dbhz": {
                name: {satellite: median(values) for satellite, values in sorted(satellites.items())}
                for name, satellites in self.signals.items() if satellites
            },
            "rtcm_transport": rtcm,
            "rtcm_message_counts": dict(sorted(self.rtcm_types.items())),
            "rtcm_station_ids": {
                kind: dict(counts) for kind, counts in sorted(self.rtcm_station_ids.items())
            },
            "rtcm_msm_satellite_slots_latest": self.rtcm_satellites,
            "rtcm_msm4_by_message_and_signal_id": {
                key: {
                    "observations": len(stats["cn0"]),
                    "cn0_dbhz_median": median(stats["cn0"]),
                    "phase_satellite_slots": sorted(stats["phase_satellite_slots"]),
                    "missing_phase": stats["missing_phase"],
                    "lock_indicator_zero": stats["lock_indicator_zero"],
                    "half_cycle_flag": stats["half_cycle_flag"],
                }
                for key, stats in sorted(self.msm4_signals.items())
            },
        }


async def capture(args):
    report = GNSSReport()
    gps = GPSReader(port=args.serial, on_nmea=report.read_nmea)

    def write_and_inspect(chunk):
        if not gps.write_rtcm(chunk):
            return False
        report.read_rtcm(chunk)
        return True

    rtcm = RTCMClient(args.base, args.port, write_and_inspect)
    gps.start()
    task = asyncio.create_task(rtcm.run())
    try:
        await asyncio.sleep(args.seconds)
        snapshot = rtcm.snapshot()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        gps.stop()
        gps.thread.join()
    print(json.dumps(report.summary(snapshot), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Indirizzo della Base RTCM")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--serial", default="/dev/ttyS0")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds deve essere positivo")

    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "terminator-rover.socket", "terminator-rover.service"],
        check=False,
    )
    if active.returncode == 0:
        parser.error("Ferma il socket e il servizio Rover prima di usare la seriale.")
    if subprocess.run(["fuser", "-s", args.serial], check=False).returncode == 0:
        parser.error(f"La seriale {args.serial} è già in uso.")
    asyncio.run(capture(args))


if __name__ == "__main__":
    main()
