"""Identity lock policy and signed Windows Hello assertion regression tests."""

import base64
import hashlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protection import IdentityProtection


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.protection = IdentityProtection(self.temp.name)
        self.owner = "12" * 16

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_locks_and_other_identity_is_independent(self):
        self.protection.records[self.owner] = "public credential"
        self.protection._save()
        self.protection.unlocked.add(self.owner)
        restored = IdentityProtection(self.temp.name)
        with self.assertRaises(ValueError):
            restored.require_unlocked(self.owner)
        restored.require_unlocked("34" * 16)

    def test_lock_cancels_pending_verification(self):
        job = dict(owner=self.owner, state="pending", cancel=threading.Event())
        self.protection.jobs["request"] = job
        self.protection.unlocked.add(self.owner)
        self.protection.close(self.owner)
        self.assertTrue(job["cancel"].is_set())
        self.assertNotIn(self.owner, self.protection.unlocked)
        with self.assertRaises(ValueError):
            self.protection.result("other owner", "request")

    def test_private_routes_block_while_receiver_can_store(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from http_api import Application
        from messaging import Messaging

        self.protection.records[self.owner] = "public credential"
        app = Application.__new__(Application)
        app.protection = self.protection
        for route in [
            "messaging/history",
            "messaging/search",
            "messaging/block",
            "messaging/send",
            "messaging/attachment",
            "browser/open",
            "browser/external",
            "browser/source",
            "browser/bookmarks",
            "messaging/sync",
            "dns/list",
        ]:
            with (
                self.subTest(route=route),
                self.assertRaisesRegex(ValueError, "Unlock"),
            ):
                app.post("/api/" + route, {"owner": self.owner})
        for route in ["identity/export", "identity/update", "identity/rename"]:
            with (
                self.subTest(route=route),
                self.assertRaisesRegex(ValueError, "Unlock"),
            ):
                app.post("/api/" + route, {"id": self.owner})
        receiver = Messaging(Path(self.temp.name))
        try:
            receiver.store(
                "incoming",
                self.owner,
                "peer",
                "in",
                "received while locked",
                "received",
            )
            self.assertEqual(
                receiver.history(self.owner)[0]["content"], "received while locked"
            )
        finally:
            receiver.db.close()

    def test_signed_assertions_and_tampering(self):
        try:
            import fido2.client.windows  # noqa: F401 - ensure the native adapter imports
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
            from fido2.cose import ES256
            from fido2.webauthn import (
                Aaguid,
                AttestedCredentialData,
                AuthenticationResponse,
                AuthenticatorAssertionResponse,
                AuthenticatorData,
                CollectedClientData,
            )
        except ImportError:
            self.skipTest(
                "Run with the desktop build environment for FIDO2 verification"
            )
        private = ec.generate_private_key(ec.SECP256R1())
        credential = AttestedCredentialData.create(
            Aaguid.NONE,
            b"credential-id",
            ES256.from_cryptography_key(private.public_key()),
        )
        self.protection.records[self.owner] = base64.b64encode(credential).decode()
        for tampered, verified in [
            ("valid", True),
            ("signature", False),
            ("uv", False),
            ("challenge", False),
        ]:
            self.protection.close(self.owner)

            def assertion(options, event=None):
                client_data = CollectedClientData.create(
                    "webauthn.get",
                    (
                        b"wrong challenge"
                        if tampered == "challenge"
                        else options.challenge
                    ),
                    "http://localhost",
                )
                flags = AuthenticatorData.FLAG.UP
                if tampered != "uv":
                    flags |= AuthenticatorData.FLAG.UV
                auth_data = AuthenticatorData.create(
                    hashlib.sha256(b"localhost").digest(), flags, 1
                )
                signature = private.sign(
                    auth_data + client_data.hash, ec.ECDSA(hashes.SHA256())
                )
                if tampered == "signature":
                    signature = b"invalid signature"
                response = AuthenticationResponse(
                    raw_id=b"credential-id",
                    response=AuthenticatorAssertionResponse(
                        client_data=client_data,
                        authenticator_data=auth_data,
                        signature=signature,
                    ),
                )

                class Selection:
                    def get_response(self, index):
                        return response

                return Selection()

            job = dict(state="pending", error="", cancel=threading.Event())
            with patch("fido2.client.windows.WindowsClient") as client:
                client.return_value.get_assertion.side_effect = assertion
                self.protection._verify(
                    dict(id=self.owner, nickname="Test"),
                    "unlock",
                    job,
                    self.protection.epochs[self.owner],
                )
            self.assertEqual(job["state"], "complete" if verified else "failed")
            self.assertEqual(self.owner in self.protection.unlocked, verified)


if __name__ == "__main__":
    unittest.main()
