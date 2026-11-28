import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


URL = "http://127.0.0.1:8090"


def call(path, event=None, token=None):
    headers = {}
    body = None
    if event is not None:
        body = json.dumps(event).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = urlopen(Request(URL + path, data=body, headers=headers), timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.code, json.load(response)


def expect(condition, message):
    if not condition:
        raise SystemExit(f"Collaudo fallito: {message}")


def main():
    config = Path(__file__).resolve().with_name(".env").read_text(encoding="utf-8")
    devices = json.loads(next(line.split("=", 1)[1] for line in config.splitlines()
                              if line.startswith("HUB_DEVICES_JSON=")))
    expect(call("/healthz")[0] == 200, "database non disponibile")
    events = {}
    for device_id, kind in (("demo-rover", "rover"), ("demo-base", "base")):
        token = devices[device_id]["token"]
        event = {
            "schema_version": 1,
            "device_id": device_id,
            "device_type": kind,
            "boot_id": str(uuid4()),
            "sequence": 0,
            "event_type": "status",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "monotonic_ms": 0,
            "payload": {"simulated": True, "gnss": {"rtk_status": "NO FIX"}},
        }
        path = "/api/v1/events"
        expect(call(path, event)[0] == 401, "richiesta anonima accettata")
        expect(call(path, {**event, "device_id": "wrong-device"}, token)[0] == 403,
               "identità errata accettata")
        expect(call(path, {**event, "observed_at": "ieri"}, token)[0] == 400,
               "timestamp errato accettato")
        status, stored = call(path, event, token)
        expect(status == 201, "evento non registrato")
        status, duplicate = call(path, event, token)
        expect(status == 200 and duplicate["status"] == "duplicate"
               and duplicate["received_at"] == stored["received_at"], "retry non deduplicato")
        expect(call(path, {**event, "payload": {}}, token)[0] == 409,
               "conflitto di sequenza non rilevato")
        events[device_id] = event
    status, report = call("/api/v1/devices")
    expect(status == 200, "elenco dispositivi non disponibile")
    for device_id, event in events.items():
        expect(any(row["device_id"] == device_id and row["online"] and row["event"] == event
                   for row in report["devices"]), f"stato non trovato per {device_id}")
    print("OK: Rover e Base simulati, autorizzazione, validazione, deduplicazione e lettura.")


if __name__ == "__main__":
    main()
