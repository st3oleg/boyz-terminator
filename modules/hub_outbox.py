"""Coda SQLite per gli eventi dell'hub, con un solo processo di invio."""

import json
import sqlite3
from contextlib import closing, contextmanager


MAX_EVENT_BYTES = 65536


class OutboxFull(RuntimeError):
    """La coda ha raggiunto il limite e conserva ancora gli eventi pendenti."""


class HubOutbox:
    def __init__(self, path, *, max_pending=10000):
        if type(max_pending) is not int or max_pending < 1:
            raise ValueError("Limite coda non valido")
        self.path = str(path)
        self.max_pending = max_pending
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    body BLOB NOT NULL,
                    UNIQUE (device_id, boot_id, sequence)
                )
            """)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=2)) as conn, conn:
            conn.execute("PRAGMA synchronous = FULL")
            yield conn

    def enqueue(self, event):
        """Salva l'evento prima di renderlo disponibile per l'invio."""
        key = (event["device_id"], event["boot_id"], event["sequence"])
        body = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(body) > MAX_EVENT_BYTES:
            raise ValueError("Evento oltre il limite dell'hub")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT body FROM outbox WHERE device_id = ? AND boot_id = ? AND sequence = ?",
                key,
            ).fetchone()
            if row:
                if row[0] != body:
                    raise ValueError("La stessa chiave identifica un evento diverso")
                return
            count = conn.execute("SELECT count(*) FROM outbox").fetchone()[0]
            if count >= self.max_pending:
                raise OutboxFull("Coda dell'hub piena")
            conn.execute(
                "INSERT INTO outbox (device_id, boot_id, sequence, body) VALUES (?, ?, ?, ?)",
                (*key, body),
            )

    def deliver_one(self, post):
        """Invia il più vecchio. Conserva l'evento se l'API non conferma."""
        with self._connect() as conn:
            row = conn.execute("SELECT id, body FROM outbox ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return False
        event_id, body = row
        status, response = post(body)
        if (status, response) not in ((201, "stored"), (200, "duplicate")):
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM outbox WHERE id = ?", (event_id,))
        return True
