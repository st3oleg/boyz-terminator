import json
import os
from pathlib import Path
from secrets import token_urlsafe


def main():
    devices = {
        "demo-rover": {"device_type": "rover", "token": token_urlsafe(32)},
        "demo-base": {"device_type": "base", "token": token_urlsafe(32)},
    }
    path = Path(__file__).resolve().with_name(".env")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Configurazione .env già presente.")
        return
    with os.fdopen(fd, "w", encoding="utf-8") as env:
        env.write(f"HUB_DB_PASSWORD={token_urlsafe(32)}\n")
        env.write(f"HUB_INGEST_PASSWORD={token_urlsafe(32)}\n")
        env.write(f"HUB_DEVICES_JSON={json.dumps(devices, separators=(',', ':'))}\n")
    print("Configurazione di prova creata per demo-rover e demo-base.")


if __name__ == "__main__":
    main()
