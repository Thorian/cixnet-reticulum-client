"""Fallback policy: peer presence is not proof of a reachable connection server."""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401, I001 - bootstrap optional dependency paths first

import RNS

from fallback import NAME, FallbackGateway, validate_gateway
from profiles import ProfileStore


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.network = SimpleNamespace(
            lock=threading.RLock(), announces={}, core=Mock()
        )
        self.internet = Mock()
        self.internet.prepare.return_value = "default"
        self.gateway = FallbackGateway(self.network, self.internet, lambda: self.now)

    def test_default_migration_persistence_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(directory)
            settings = store.read()["settings"]
            self.assertTrue(settings["fallback"])
            self.assertEqual(
                settings["propagationServers"], ["49ec09143c134d6bb5d8b522c4cefa37"]
            )
            self.assertEqual(
                (settings["fallbackHost"], settings["fallbackPort"]),
                ("gw.cixnet.org", 4242),
            )
            store.save_settings(
                {
                    **settings,
                    "fallback": False,
                    "fallbackHost": "gateway.example.org",
                    "fallbackPort": 4444,
                }
            )
            saved = ProfileStore(directory).read()["settings"]
            self.assertFalse(saved["fallback"])
            self.assertEqual(saved["fallbackHost"], "gateway.example.org")
            for host, port in [
                ("https://example.org", 4242),
                ("bad host", 4242),
                ("...", 4242),
                ("example.org", True),
                ("example.org", 0),
            ]:
                with self.assertRaises(ValueError):
                    validate_gateway(host, port)
            with self.assertRaises(ValueError):
                store.save_settings({**saved, "fallbackHost": "bad/path"})
            self.assertEqual(store.read()["settings"], saved)

    def test_local_peer_alone_does_not_suppress_gateway(self):
        self.network.announces["aa" * 16] = {
            "address": "aa" * 16,
            "kind": "lxmf",
            "received": __import__("time").time(),
        }
        self.now += 16
        with patch("fallback.threading.Thread") as worker:
            self.gateway.tick()
            worker.return_value.start.assert_called_once()
        self.assertEqual(self.gateway.phase, "connecting")
        self.assertFalse(self.gateway.available_server)

    def test_local_server_handover_waits_and_releases_mobile_network(self):
        self.gateway.interface = SimpleNamespace(online=True)
        self.gateway.route = "default"
        self.now += 16
        with patch.object(
            self.gateway,
            "_server",
            return_value={"address": "ab" * 16, "kind": "relay"},
        ):
            self.gateway.tick()
            self.network.core.detach_interface.assert_not_called()
            self.now += 61
            self.gateway.tick()
        self.network.core.detach_interface.assert_called_once_with(NAME)
        self.assertEqual(self.gateway.phase, "local_server")
        self.internet.prepare.assert_called_with(False)

    def test_gateway_paths_do_not_count_as_alternative_server(self):
        import time

        address = "ab" * 16
        self.network.announces[address] = {
            "address": address,
            "kind": "relay",
            "received": time.time(),
        }
        self.gateway.interface = SimpleNamespace(name=NAME, online=True)
        with (
            patch.object(RNS.Transport, "has_path", return_value=True),
            patch.object(
                RNS.Transport, "next_hop_interface", return_value=self.gateway.interface
            ),
        ):
            self.assertIsNone(self.gateway._server(self.now))
        self.assertFalse(self.gateway.probes)

    def test_disabled_or_offline_never_connects_and_stale_socket_is_closed(self):
        self.gateway.configure({"fallback": False})
        self.now += 20
        with patch("fallback.threading.Thread") as worker:
            self.gateway.tick()
            worker.assert_not_called()
        sock = Mock()
        self.gateway.results.put((self.gateway.generation - 1, sock, None))
        self.gateway.tick()
        sock.close.assert_called_once()
        self.gateway.configure({"fallback": True})
        self.internet.prepare.return_value = "waiting"
        self.now += 5
        with patch("fallback.threading.Thread") as worker:
            self.gateway.tick()
            worker.assert_not_called()
        self.assertEqual(self.gateway.phase, "waiting_internet")

    def test_failed_connection_uses_bounded_backoff(self):
        self.gateway.results.put((self.gateway.generation, None, "unreachable"))
        self.gateway._collect(self.now)
        self.assertEqual(self.gateway.next_attempt, self.now + 15)
        self.gateway.results.put((self.gateway.generation, None, "unreachable"))
        self.gateway._collect(self.now)
        self.assertEqual(self.gateway.next_attempt, self.now + 30)
