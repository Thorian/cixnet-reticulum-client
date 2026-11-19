"""Pairing authorization and durable mutation replay protections."""

import json
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401, I001 - bootstrap local upstream paths first

import RNS

from pairing import Pairing, load_pairing_identity, validate_invite


class PairingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.pairing = Pairing.__new__(Pairing)
        self.pairing.lock = threading.RLock()
        self.pairing.remote = None
        self.pairing.db = sqlite3.connect(":memory:")
        self.pairing.db.executescript(
            "CREATE TABLE devices(hash TEXT,public TEXT,name TEXT,owners TEXT,role TEXT,endpoint TEXT); CREATE TABLE requests(device TEXT,id TEXT,digest TEXT,created REAL,result BLOB,PRIMARY KEY(device,id));"
        )
        self.pairing.db.execute(
            "INSERT INTO devices VALUES (?,?,?,?,?,?)",
            ("desktop", "", "Desktop", '["owner"]', "desktop", "{}"),
        )
        self.pairing.db.commit()
        self.pairing.app = SimpleNamespace(
            protection=SimpleNamespace(require_unlocked=Mock()),
            post=Mock(return_value={"id": "accepted"}),
            get=Mock(
                return_value={
                    "token": "NEVER SHARE",
                    "profiles": [{"id": "owner"}, {"id": "private"}],
                }
            ),
        )

    def tearDown(self):
        self.pairing.db.close()

    def request(self, path="/api/messaging/send", **changes):
        return {
            "id": "ab" * 16,
            "created": time.time(),
            "path": path,
            "body": {"owner": "owner", "content": "hello"},
            **changes,
        }

    def test_mutations_are_deduplicated_and_changed_payload_rejected(self):
        request = self.request()
        first = self.pairing._dispatch("desktop", request)
        self.assertEqual(self.pairing._dispatch("desktop", request), first)
        self.pairing.app.post.assert_called_once()
        with self.assertRaisesRegex(ValueError, "different content"):
            self.pairing._dispatch(
                "desktop",
                {**request, "body": {"owner": "owner", "content": "different"}},
            )
        self.pairing.db.execute("UPDATE requests SET result=NULL")
        with self.assertRaisesRegex(ValueError, "interrupted"):
            self.pairing._dispatch("desktop", request)
        self.pairing.app.post.assert_called_once()

    def test_private_identities_keys_and_revoked_devices_are_denied(self):
        for request in (
            self.request(body={"owner": "private"}),
            self.request("/api/identity/export"),
            self.request("/api/identity/protection/unlock"),
        ):
            with self.assertRaises(ValueError):
                self.pairing._dispatch("desktop", request)
        result = self.pairing._dispatch("desktop", self.request("/api/state"))["result"]
        self.assertNotIn("token", result)
        self.assertEqual(result["profiles"], [{"id": "owner"}])
        self.pairing.db.execute("DELETE FROM devices")
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.pairing._dispatch("desktop", self.request())

    def test_locked_identity_and_stale_mutation_are_denied(self):
        self.pairing.app.protection.require_unlocked.side_effect = ValueError("locked")
        with self.assertRaisesRegex(ValueError, "locked"):
            self.pairing._dispatch("desktop", self.request())
        self.pairing.app.protection.require_unlocked.side_effect = None
        with self.assertRaisesRegex(ValueError, "expired"):
            self.pairing._dispatch("desktop", self.request(created=0))
        self.pairing.app.post.assert_not_called()

    def test_invitation_expiry_public_identity_and_lan_validation(self):
        identity = RNS.Identity()
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "cixnet", "pairing"
        )
        invite = {
            "cixnet": 1,
            "host": "192.168.50.12",
            "port": 4242,
            "public": identity.get_public_key().hex(),
            "destination": destination.hash.hex(),
            "expires": time.time() + 200,
            "secret": "ab" * 32,
        }
        self.assertEqual(
            validate_invite(json.dumps(invite))["destination"], invite["destination"]
        )
        for changes in (
            {"expires": 0},
            {"host": "8.8.8.8"},
            {"host": "127.0.0.1"},
            {"destination": "ab" * 16},
            {"secret": "bad"},
            {"port": True},
        ):
            with self.assertRaises((ValueError, KeyError)):
                validate_invite(json.dumps({**invite, **changes}))

    def test_wrong_secret_expiry_and_replay_never_approve(self):
        pairing = self.pairing
        peer = RNS.Identity()
        pairing.links = {b"link": SimpleNamespace(status=RNS.Link.ACTIVE)}
        pairing.paused = False
        pairing.invite = {
            "secret": "ab" * 32,
            "expires": time.time() + 20,
            "host": "192.168.50.12",
            "port": 4242,
        }
        self.assertIn(
            "error",
            pairing._receive(
                "/hello", {"secret": "wrong"}, b"req", b"link", peer, time.time()
            ),
        )
        self.assertEqual(
            pairing.db.execute("SELECT count(*) FROM devices").fetchone()[0], 1
        )
        result = pairing._receive(
            "/hello",
            {"secret": "ab" * 32, "name": "Phone"},
            b"req",
            b"link",
            peer,
            time.time(),
        )
        self.assertTrue(result["ok"])
        self.assertIn(
            "error",
            pairing._receive(
                "/hello", {"secret": "ab" * 32}, b"req", b"link", peer, time.time()
            ),
        )


class PairingIdentityTests(unittest.TestCase):
    def test_new_key_is_created_once_and_survives_restart(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            with patch(
                "pairing.RNS.Identity.from_file", wraps=RNS.Identity.from_file
            ) as load:
                identity = load_pairing_identity(directory)
                load.assert_not_called()
                saved = (directory / "pairing.identity").read_bytes()
                reopened = load_pairing_identity(directory)
            self.assertEqual(identity.hash, reopened.hash)
            self.assertEqual((directory / "pairing.identity").read_bytes(), saved)

    def test_damaged_pairing_identity_is_not_overwritten(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / "pairing.identity"
            path.write_bytes(b"damaged-key")
            with patch("pairing.RNS.Identity.from_file", return_value=None):
                with self.assertRaisesRegex(ValueError, "saved pairing identity"):
                    load_pairing_identity(directory)
            self.assertEqual(path.read_bytes(), b"damaged-key")
