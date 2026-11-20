"""Incoming messages wait for a public key without exposing unverified content."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import LXMF
import RNS

from messaging import Messaging


class IncomingVerificationTests(unittest.TestCase):
    def test_unknown_sender_survives_restart_then_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = SimpleNamespace(
                signature_validated=False,
                unverified_reason=LXMF.LXMessage.SOURCE_UNKNOWN,
                packed=b"original signed message",
                source_hash=bytes.fromhex("ab" * 16),
                hash=bytes.fromhex("cd" * 32),
            )
            messaging = Messaging(root)
            messaging.on_message = Mock()
            messaging.receive("owner", pending)
            messaging.on_message.assert_not_called()
            self.assertEqual(messaging.history("owner"), [])
            messaging.db.close()
            messaging = Messaging(root)
            try:
                with (
                    patch.object(RNS.Identity, "recall", return_value=None),
                    patch.object(messaging.outbox, "request_path") as request,
                ):
                    messaging.verify_pending()
                    request.assert_called_once_with("ab" * 16)
                verified = SimpleNamespace(signature_validated=True)
                messaging.next_verification = 0
                with (
                    patch.object(RNS.Identity, "recall", return_value=object()),
                    patch.object(
                        LXMF.LXMessage, "unpack_from_bytes", return_value=verified
                    ) as unpack,
                    patch.object(messaging, "receive") as receive,
                ):
                    messaging.verify_pending()
                    unpack.assert_called_once_with(pending.packed)
                    receive.assert_called_once_with("owner", verified)
                self.assertEqual(
                    messaging.db.execute(
                        "SELECT COUNT(*) FROM unverified_messages"
                    ).fetchone()[0],
                    0,
                )
            finally:
                messaging.db.close()

    def test_invalid_signature_is_not_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            messaging = Messaging(Path(directory))
            try:
                messaging.receive(
                    "owner",
                    SimpleNamespace(
                        signature_validated=False,
                        unverified_reason=LXMF.LXMessage.SIGNATURE_INVALID,
                    ),
                )
                self.assertEqual(
                    messaging.db.execute(
                        "SELECT COUNT(*) FROM unverified_messages"
                    ).fetchone()[0],
                    0,
                )
            finally:
                messaging.db.close()
