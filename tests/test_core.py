"""Fast regression tests for identities, preferences, and message storage.

Run from the client directory: python -m unittest discover -s tests -v
Source locations can be overridden with RETICULUM_SOURCE and LXMF_SOURCE.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT),
    os.environ.get("RETICULUM_SOURCE", ""),
    os.environ.get("LXMF_SOURCE", ""),
    os.environ.get("RETDNS_SOURCE", ""),
    os.environ.get("NOMADPL_SOURCE", ""),
]

from appearance import decode, encode
from messaging import Messaging
from profiles import ProfileStore


class ProfileTests(unittest.TestCase):
    def setUp(self):
        """Create isolated temporary state for this test's assertions."""
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ProfileStore(Path(self.temporary.name) / "first")

    def tearDown(self):
        """Close test resources and remove their temporary storage."""
        self.temporary.cleanup()

    def test_export_import_preserves_identity(self):
        """Restore the same cryptographic identity from an explicit key backup."""
        profile = self.store.create("Local name")
        private_key = self.store.export(profile["id"])
        second = ProfileStore(Path(self.temporary.name) / "second")
        imported = second.create("Imported name", private_key)
        self.assertEqual(len(private_key), 64)
        self.assertEqual(profile["id"], imported["id"])
        self.assertEqual(private_key, second.export(imported["id"]))
        # Public API metadata must not contain key bytes or key material fields.
        self.assertNotIn("private", str(self.store.read()).lower())

    def test_edit_preserves_key_and_separates_names(self):
        """Allow profile name changes without regenerating keys or mixing name roles."""
        profile = self.store.create("Local name")
        private_key = self.store.export(profile["id"])
        self.store.update(
            profile["id"],
            {
                "nickname": "Private nickname",
                "display_name": "Public name",
                "icon": "pine-tree",
                "color": "teal",
            },
        )
        reopened = ProfileStore(self.store.directory)
        updated = reopened.get(profile["id"])
        self.assertEqual(updated["nickname"], "Private nickname")
        self.assertEqual(updated["display_name"], "Public name")
        self.assertEqual(reopened.export(profile["id"]), private_key)
        renamed = reopened.rename(profile["id"], "Another local name")
        self.assertEqual(renamed["display_name"], "Public name")

    def test_bad_imports_and_profile_updates_are_rejected(self):
        """Reject invalid key files and malformed profile edits before saving them."""
        profile = self.store.create("Test")
        with self.assertRaises(ValueError):
            self.store.create("Duplicate", self.store.export(profile["id"]))
        with self.assertRaises(ValueError):
            self.store.create("Invalid", b"too short")
        for fields in (
            {**profile, "icon": "<script>"},
            {**profile, "color": []},
            {**profile, "nickname": "hidden\ncontrol"},
            {**profile, "display_name": ""},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.update(profile["id"], fields)
        self.assertEqual(self.store.get(profile["id"])["nickname"], "Test")
        with self.assertRaises(ValueError):
            self.store.export("../../outside")

    def test_settings_validation_is_atomic(self):
        """Leave saved settings unchanged when any submitted option is invalid."""
        settings = {
            "announceMinutes": 15,
            "media": "text",
            "localDiscovery": False,
            "fallback": True,
            "interfaces": [{"name": "Radio draft", "type": "RNodeInterface"}],
        }
        self.store.save_settings(settings)
        for value in (0, -1, 1441, True, 1.5, "15"):
            with self.assertRaises(ValueError):
                self.store.save_settings({**settings, "announceMinutes": value})
        for value in (0, -1, 61, True, 1.5, "5"):
            with self.assertRaises(ValueError):
                self.store.save_settings({**settings, "mailboxCheckMinutes": value})
        with self.assertRaises(ValueError):
            self.store.save_settings({**settings, "localDiscovery": "false"})
        self.assertEqual(
            self.store.read()["settings"],
            {
                **settings,
                "fallbackHost": "gw.cixnet.org",
                "fallbackPort": 4242,
                "propagationServers": [],
                "deliveryMode": "auto",
                "mailboxCheckMinutes": 5,
            },
        )
        self.store.save_settings({**settings, "mailboxCheckMinutes": 2})
        self.assertEqual(
            ProfileStore(self.store.directory).read()["settings"][
                "mailboxCheckMinutes"
            ],
            2,
        )


class AppearanceTests(unittest.TestCase):
    def test_wire_format_roundtrip(self):
        """Round-trip the supported LXMF icon and color representation."""
        wire = encode({"icon": "pine-tree", "color": "green"})
        self.assertEqual(
            decode(wire),
            {
                "icon": "pine-tree",
                "foreground": "70e7a3",
                "background": "2e503c",
            },
        )

    def test_untrusted_appearance_is_validated(self):
        """Reject peer-supplied icons and colors outside the supported format."""
        for value in (
            None,
            [],
            ["bad-icon", b"123", b"456"],
            ["account", "123", "456"],
            ["account", b"1", b"456"],
        ):
            with self.subTest(value=value):
                self.assertIsNone(decode(value))


class MessageStorageTests(unittest.TestCase):
    def test_saved_names_and_message_counts_survive_reopening(self):
        """Restore public peer names and identity-owned history counts from storage."""
        with tempfile.TemporaryDirectory() as directory:
            messaging = Messaging(Path(directory))
            messaging.store("message", "owner", "peer", "in", "saved", "received")
            messaging.remember_peer_names(
                [{"address": "peer", "display_name": "Known station", "kind": "lxmf"}]
            )
            messaging.db.close()
            reopened = Messaging(Path(directory))
            self.assertEqual(reopened.message_counts(), {"owner": 1})
            self.assertEqual(reopened.names("owner"), {"peer": "Known station"})
            self.assertEqual(reopened.names("other identity"), {})
            reopened.db.close()

    def test_announce_schedule_obeys_interval_without_replaying_missed_ticks(self):
        """Announce when due without replaying every interval missed during sleep."""
        with tempfile.TemporaryDirectory() as directory:
            messaging = Messaging(Path(directory))
            router = Mock()
            destination = Mock(hash=b"destination")
            messaging.routers["owner"] = (router, destination)
            messaging.announce_minutes = 2
            with patch("messaging.time.monotonic", return_value=100):
                messaging.announce_due()
            router.announce.assert_called_once_with(b"destination")
            with patch("messaging.time.monotonic", return_value=219):
                messaging.announce_due()
            self.assertEqual(router.announce.call_count, 1)
            with patch("messaging.time.monotonic", return_value=220):
                messaging.announce_due()
            self.assertEqual(router.announce.call_count, 2)
            with patch("messaging.time.monotonic", return_value=10000):
                messaging.announce_due()
                messaging.announce_due()
            self.assertEqual(router.announce.call_count, 3)
            messaging.db.close()

    def test_duplicate_delivery_and_restart_state(self):
        """
        Deduplicate received messages and restore a truthful outgoing state on restart.
        """
        with tempfile.TemporaryDirectory() as directory:
            messaging = Messaging(Path(directory))
            messaging.store("incoming", "owner", "peer", "in", "hello", "received")
            messaging.store("incoming", "owner", "peer", "in", "hello", "received")
            messaging.store("pending", "owner", "peer", "out", "unsent", "sending")
            self.assertEqual(len(messaging.history("owner")), 2)
            self.assertEqual(messaging.history("another owner"), [])
            messaging.db.close()
            reopened = Messaging(Path(directory))
            statuses = {
                message["id"]: message["status"]
                for message in reopened.history("owner")
            }
            self.assertEqual(
                statuses, {"incoming": "received", "pending": "interrupted"}
            )
            reopened.db.close()


if __name__ == "__main__":
    unittest.main()
