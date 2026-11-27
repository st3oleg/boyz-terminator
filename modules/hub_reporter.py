"""Invio opzionale di stato e indici missione dal Rover all'hub."""

import asyncio
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from modules.hub_outbox import HubOutbox, OutboxFull


LOG = logging.getLogger(__name__)
SAMPLE_SECONDS = 10


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HubReporter:
    def __init__(self, endpoint, device_id, token, path):
        url = urlsplit(endpoint)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path != "/api/v1/events" or url.query or url.fragment):
            raise ValueError("L'endpoint hub deve essere HTTPS e terminare con /api/v1/events")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", device_id):
            raise ValueError("Identità Rover non valida")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise ValueError("Token hub non valido")
        self.endpoint = endpoint
        self.device_id = device_id
        self.token = token
        self.outbox = HubOutbox(path)
        self.opener = build_opener(NoRedirect())
        self.boot_id = str(uuid4())
        self.started = time.monotonic()
        self.sequence = 0

    async def enqueue(self, event_type, payload):
        event = {
            "schema_version": 1,
            "device_id": self.device_id,
            "device_type": "rover",
            "boot_id": self.boot_id,
            "sequence": self.sequence,
            "event_type": event_type,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "monotonic_ms": int((time.monotonic() - self.started) * 1000),
            "payload": payload,
        }
        self.sequence += 1
        await asyncio.to_thread(self.outbox.enqueue, event)

    def _post(self, body):
        request = Request(
            self.endpoint, data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with self.opener.open(request, timeout=3) as response:
            result = json.loads(response.read(4097))
            return response.status, result.get("status") if isinstance(result, dict) else None

    async def run(self, sample):
        next_sample = 0
        delay = 1
        next_send = 0
        while True:
            now = time.monotonic()
            if now >= next_sample:
                next_sample = now + SAMPLE_SECONDS
                try:
                    await self.enqueue("status", sample())
                except (sqlite3.Error, OutboxFull, ValueError) as exc:
                    LOG.warning("Accodamento stato Rover fallito (%s)", type(exc).__name__)
            if now >= next_send:
                try:
                    delivered = await asyncio.to_thread(self.outbox.deliver_one, self._post)
                except (OSError, ValueError, sqlite3.Error) as exc:
                    if delay == 1:
                        LOG.warning("Invio hub sospeso (%s)", type(exc).__name__)
                    next_send = time.monotonic() + delay
                    delay = min(30, delay * 2)
                else:
                    delay = 1
                    next_send = time.monotonic() + (0.25 if delivered else 1)
            await asyncio.sleep(0.25)
