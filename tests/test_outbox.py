"""Store-and-forward guarantees, independent relay receipts, and receipt authentication."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401 - load external source dependencies before imports.

import LXMF  # isort: skip
from messaging import Messaging
from outbox import RECEIPT_TYPE


class OutboxTests(unittest.TestCase):
    def setUp(self):
        """Create isolated temporary state for this test's assertions."""
        self.temp = tempfile.TemporaryDirectory()
        self.app = Messaging(Path(self.temp.name))
        self.owner = "a" * 32
        self.peer = "b" * 32
        self.ident = "c" * 64
        self.servers = ["d" * 32, "e" * 32, "f" * 32]
        self.app.outbox.servers = self.servers
        self.app.store(
            self.ident, self.owner, self.peer, "out", "Durable message", "queued"
        )
        self.app.db.execute(
            "INSERT INTO outbox(id,owner,packed,fields,attempts,due,last_error) VALUES (?,?,NULL,?,0,0,'')",
            (self.ident, self.owner, b""),
        )
        self.app.db.execute(
            "INSERT INTO sent_messages VALUES (?,?,?,?)",
            (self.ident, self.owner, self.ident, self.peer),
        )
        self.app.db.commit()

    def tearDown(self):
        """Close test resources and remove their temporary storage."""
        self.app.db.close()
        self.temp.cleanup()

    def batch(self, count):
        """Create a queued delivery batch with the fixture's chosen relay conditions."""
        routes = {
            server: (
                Mock(),
                Mock(
                    hash=bytes.fromhex(self.ident),
                    desired_method=LXMF.LXMessage.PROPAGATED,
                ),
            )
            for server in self.servers[:count]
        }
        batch = dict(routes=routes, done=False, started=True, finished=set())
        self.app.pending[self.ident] = batch
        self.app.outbox.active.add(self.owner)
        return routes

    def test_one_relay_receipt_does_not_cancel_other_copies(self):
        """
        Complete only the acknowledged relay copy while retaining other deliveries.
        """
        routes = self.batch(3)
        first = self.servers[0]
        self.app.outbox.finish_route(
            self.ident, self.owner, first, routes[first][1], True
        )
        for router, message in routes.values():
            router.cancel_outbound.assert_not_called()
        self.assertIsNotNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        self.assertEqual(
            self.app.db.execute("SELECT count(*) FROM relay_copies").fetchone()[0], 1
        )
        for server in self.servers[1:]:
            self.app.outbox.finish_route(
                self.ident, self.owner, server, routes[server][1], True
            )
        self.assertIsNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        self.assertEqual(self.app.history(self.owner)[0]["status"], "stored_on_relays")

    def test_unreachable_relay_remains_pending_after_restart(self):
        """Restore pending work for a relay that was unavailable at shutdown."""
        routes = self.batch(2)
        for server, (router, message) in routes.items():
            self.app.outbox.finish_route(self.ident, self.owner, server, message, True)
        self.app.db.close()
        self.app = Messaging(Path(self.temp.name))
        self.assertIsNotNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        self.assertEqual(
            self.app.db.execute("SELECT count(*) FROM relay_copies").fetchone()[0], 2
        )
        self.assertEqual(self.app.history(self.owner)[0]["status"], "queued")

    def test_only_signed_receipt_from_expected_recipient_completes_all_copies(self):
        """
        Require an authenticated recipient receipt before clearing every pending copy.
        """
        routes = self.batch(2)
        receipt = Mock(
            signature_validated=True,
            source_hash=bytes.fromhex("1" * 32),
            fields={
                LXMF.FIELD_CUSTOM_TYPE: RECEIPT_TYPE,
                LXMF.FIELD_CUSTOM_DATA: self.ident,
            },
        )
        self.app.receive(self.owner, receipt)
        self.assertIsNotNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        receipt.source_hash = bytes.fromhex(self.peer)
        receipt.signature_validated = False
        self.app.receive(self.owner, receipt)
        self.assertIsNotNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        receipt.signature_validated = True
        self.app.receive(self.owner, receipt)
        self.assertIsNone(self.app.db.execute("SELECT 1 FROM outbox").fetchone())
        self.assertEqual(self.app.history(self.owner)[0]["status"], "delivered")
        for router, message in routes.values():
            router.cancel_outbound.assert_called_once_with(message.hash)

    def test_unknown_recipient_and_attachment_are_saved_before_any_delivery(self):
        """
        Persist outgoing content before resolving or attempting an unknown destination.
        """
        self.app.profiles[self.owner] = dict(icon="account", color="green")
        self.app.routers[self.owner] = (Mock(), Mock())
        with patch.object(self.app.outbox, "prepare", return_value=None):
            saved = self.app.outbox.enqueue(
                self.owner,
                "2" * 32,
                "Offline",
                [dict(name="note.txt", data=b"kept", image=False)],
            )
        self.assertEqual(self.app.attachment(self.owner, saved["id"], 0)[1], b"kept")
        self.assertTrue(
            any(
                item["id"] == saved["id"] and item["queued"]
                for item in self.app.history(self.owner)
            )
        )

    def test_newly_reachable_relay_joins_an_existing_transfer(self):
        """Add a newly reachable relay without discarding an ongoing transfer."""
        routes = self.batch(1)
        server = self.servers[1]
        router, message = Mock(), Mock()
        self.app.outbox.relay_routers[(self.owner, server)] = router
        with (
            patch("outbox.RNS.Transport.has_path", return_value=True),
            patch.object(self.app.outbox, "prepare", return_value=message),
            patch("outbox.threading.Thread") as thread,
        ):
            self.app.outbox.join_relay(server)
            self.assertIs(routes[server][1], message)
            self.assertTrue(thread.called)
        first = self.servers[0]
        self.app.outbox.finish_route(
            self.ident, self.owner, first, routes[first][1], True
        )
        self.assertIn(self.ident, self.app.pending)

    def mailbox_router(self):
        """Build a controlled router for testing mailbox scheduling decisions."""
        router, destination = Mock(propagation_transfer_state=0), Mock()
        self.app.routers[self.owner] = (router, destination)
        return router

    def test_configured_interval_schedules_next_mailbox_round(self):
        """Honor the selected interval when scheduling the next mailbox check."""
        outbox = self.app.outbox
        outbox.configure(
            {"propagationServers": self.servers[:1], "mailboxCheckMinutes": 2}
        )
        self.mailbox_router()
        with (
            patch("outbox.time.monotonic", return_value=100),
            patch("outbox.RNS.Transport.has_path", return_value=True),
        ):
            outbox.sync(self.owner)
        self.assertEqual(outbox.sync_next[self.owner], 220)

    def test_announce_checks_that_mailbox_first_and_suppresses_recent_repeats(self):
        """
        Prioritize an announced mailbox without repeatedly scheduling the same check.
        """
        router = self.mailbox_router()
        outbox = self.app.outbox
        server = self.servers[2]
        with (
            patch("outbox.time.monotonic", return_value=100),
            patch("outbox.RNS.Transport.has_path", return_value=True),
            patch.object(outbox, "join_relay"),
        ):
            outbox.path_available(server)
            outbox.path_available(server)
            self.assertEqual(outbox.sync_priority[self.owner], [server])
            outbox.sync_due()
            router.set_outbound_propagation_node.assert_called_once_with(
                bytes.fromhex(server)
            )
            self.assertEqual(
                router.request_messages_from_propagation_node.call_count, 1
            )
            due = outbox.sync_next[self.owner]
            outbox.path_available(server)
            self.assertEqual(outbox.sync_next[self.owner], due)
            self.assertEqual(outbox.sync_priority[self.owner], [])
        with (
            patch("outbox.time.monotonic", return_value=161),
            patch.object(outbox, "join_relay"),
        ):
            outbox.path_available(server)
            self.assertEqual(outbox.sync_priority[self.owner], [server])
            self.assertEqual(outbox.sync_next[self.owner], 0)

    def test_busy_transfer_preserves_announced_mailbox_for_next_check(self):
        """
        Retain a pending mailbox announcement while another transfer occupies the link.
        """
        router = self.mailbox_router()
        outbox = self.app.outbox
        server = self.servers[1]
        outbox.active.add(self.owner)
        with (
            patch("outbox.RNS.Transport.has_path", return_value=True),
            patch.object(outbox, "join_relay"),
        ):
            outbox.path_available(server)
            outbox.sync_due()
            router.request_messages_from_propagation_node.assert_not_called()
            self.assertEqual(outbox.sync_priority[self.owner], [server])
            outbox.active.clear()
            outbox.sync_next[self.owner] = 0
            outbox.sync_due()
            router.set_outbound_propagation_node.assert_called_once_with(
                bytes.fromhex(server)
            )

    def test_unknown_relay_announce_does_not_schedule_mailbox_checks(self):
        """Ignore mailbox scheduling hints from relays the user has not configured."""
        self.mailbox_router()
        self.app.outbox.path_available("9" * 32)
        self.assertEqual(self.app.outbox.sync_priority, {})
