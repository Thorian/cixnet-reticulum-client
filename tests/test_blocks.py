"""Contact blocks survive restarts and stop notifications before message decoding."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401

from messaging import Messaging


class BlockTests(unittest.TestCase):
    def test_persistent_identity_scoped_block_and_unblock(self):
        peer = "ab" * 16
        with tempfile.TemporaryDirectory() as directory:
            app = Messaging(Path(directory))
            app.store("old", "owner", peer, "in", "saved history", "received")
            app.store("queued", "owner", peer, "out", "pending", "queued")
            app.db.execute(
                "INSERT INTO outbox(id,owner) VALUES (?,?)", ("queued", "owner")
            )
            app.set_blocked("owner", peer.upper(), True)
            self.assertIsNone(
                app.db.execute("SELECT 1 FROM outbox WHERE id='queued'").fetchone()
            )
            self.assertEqual(
                app.db.execute(
                    "SELECT status FROM messages WHERE id='queued'"
                ).fetchone()[0],
                "cancelled",
            )
            self.assertEqual(app.blocked_contacts("owner"), [peer])
            self.assertEqual(app.blocked_contacts("other"), [])
            alerts = []
            app.on_message = lambda *args: alerts.append(args)
            # No content or attachments are accessed for a blocked sender.
            app.receive(
                "owner",
                SimpleNamespace(
                    signature_validated=True, source_hash=bytes.fromhex(peer)
                ),
            )
            self.assertEqual(alerts, [])
            self.assertEqual(len(app.history("owner")), 2)
            with self.assertRaisesRegex(ValueError, "Unblock"):
                app.send("owner", peer, "hello")
            app.db.close()
            app = Messaging(Path(directory))
            self.assertEqual(app.blocked_contacts("owner"), [peer])
            app.set_blocked("owner", peer, False)
            self.assertEqual(app.blocked_contacts("owner"), [])
            self.assertEqual(len(app.history("owner")), 2)
            for invalid in ("bad", "z" * 32):
                with self.assertRaises(ValueError):
                    app.set_blocked("owner", invalid, True)
            with self.assertRaises(ValueError):
                app.set_blocked("owner", peer, "false")
            app.db.close()
