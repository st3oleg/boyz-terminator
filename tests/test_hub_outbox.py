import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from modules.hub_outbox import HubOutbox, OutboxFull


class HubOutboxTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "outbox.sqlite3"
        self.boot_id = str(uuid4())

    def event(self, sequence):
        return {
            "schema_version": 1,
            "device_id": "rover-01",
            "device_type": "rover",
            "boot_id": self.boot_id,
            "sequence": sequence,
            "event_type": "mission_index",
            "observed_at": None,
            "monotonic_ms": 0,
            "payload": {},
        }

    def test_retries_same_body_after_restart_and_lost_ack(self):
        queue = HubOutbox(self.path)
        queue.enqueue(self.event(0))
        queue.enqueue(self.event(1))
        attempts = []

        def lost_reply(body):
            attempts.append(body)
            raise TimeoutError

        with self.assertRaises(TimeoutError):
            queue.deliver_one(lost_reply)

        restarted = HubOutbox(self.path)

        def retry(body):
            attempts.append(body)
            return 200, "duplicate"

        self.assertTrue(restarted.deliver_one(retry))
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(json.loads(attempts[1]), self.event(0))
        self.assertTrue(restarted.deliver_one(lambda body: (201, "stored")
                                             if json.loads(body) == self.event(1) else (400, "invalid")))
        self.assertFalse(restarted.deliver_one(lambda _: self.fail("Coda non vuota")))

    def test_invalid_ack_and_full_queue_preserve_pending_event(self):
        queue = HubOutbox(self.path, max_pending=1)
        queue.enqueue(self.event(0))
        queue.enqueue(self.event(0))
        with self.assertRaises(OutboxFull):
            queue.enqueue(self.event(1))
        with self.assertRaises(ValueError):
            queue.enqueue({**self.event(0), "payload": {"changed": True}})
        self.assertFalse(queue.deliver_one(lambda _: (200, "not_an_ack")))
        self.assertTrue(queue.deliver_one(lambda body: (201, "stored")
                                          if json.loads(body) == self.event(0) else (400, "invalid")))
