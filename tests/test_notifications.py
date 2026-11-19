"""Notifications follow committed, authenticated, nonduplicate deliveries."""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401 - configure upstream imports

from messaging import Messaging


class NotificationTests(unittest.TestCase):
    def test_new_delivery_is_committed_before_notification_and_duplicates_are_silent(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            receiver = Messaging(Path(directory))
            event = Mock(
                signature_validated=True,
                fields={},
                hash=b"m" * 32,
                source_hash=b"p" * 16,
            )
            event.content_as_string.return_value = "Saved before notification"

            def notify(owner, peer, ident):
                with closing(
                    sqlite3.connect(str(Path(directory) / "messages.sqlite"))
                ) as database:
                    self.assertEqual(
                        database.execute(
                            "SELECT content FROM messages WHERE id=?", (ident,)
                        ).fetchone()[0],
                        "Saved before notification",
                    )

            receiver.on_message = Mock(side_effect=notify)
            receiver.receive("owner", event)
            receiver.receive("owner", event)
            receiver.on_message.assert_called_once_with(
                "owner", (b"p" * 16).hex(), (b"m" * 32).hex()
            )
            event.signature_validated = False
            event.hash = b"x" * 32
            receiver.receive("owner", event)
            self.assertEqual(len(receiver.history("owner")), 1)
            receiver.db.close()

    def test_notification_failure_does_not_lose_a_message(self):
        with tempfile.TemporaryDirectory() as directory:
            receiver = Messaging(Path(directory))
            event = Mock(
                signature_validated=True,
                fields={},
                hash=b"m" * 32,
                source_hash=b"p" * 16,
            )
            event.content_as_string.return_value = "Still saved"
            receiver.on_message = Mock(
                side_effect=RuntimeError("permission unavailable")
            )
            with self.assertLogs(level="ERROR"):
                receiver.receive("owner", event)
            self.assertEqual(receiver.history("owner")[0]["content"], "Still saved")
            receiver.db.close()


if __name__ == "__main__":
    unittest.main()
