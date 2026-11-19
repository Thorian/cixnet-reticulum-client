"""Safe interface definitions and rollback of failed live updates."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_core  # noqa: F401 - configures supplied dependency sources.
from RNS.vendor.configobj import ConfigObj

from interface_config import definitions, validate_interfaces, write_config
from network import Network


class InterfaceTests(unittest.TestCase):
    def test_config_quotes_values_and_keeps_lan_and_tcp_separate(self):
        """Generate safe interface configuration with distinct LAN and TCP entries."""
        item = {
            "name": "Gateway",
            "type": "TCPClientInterface",
            "host": "::1",
            "port": 4242,
            "enabled": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            write_config(path, definitions(True, [item]), test_listen=4243)
            parsed = ConfigObj(str(path))
            self.assertEqual(
                parsed["interfaces"]["ciXnet Gateway"]["target_host"], "::1"
            )
            self.assertEqual(
                parsed["interfaces"]["Local network"]["type"], "AutoInterface"
            )
            self.assertEqual(
                parsed["interfaces"]["Local test listener"]["listen_ip"], "127.0.0.1"
            )
        self.assertEqual(definitions(False, [{**item, "enabled": False}]), {})

    def test_rejects_injection_duplicate_names_and_invalid_ports(self):
        """Reject unsafe interface text, duplicate entries and invalid port values."""
        item = {
            "name": "Gateway",
            "type": "TCPClientInterface",
            "host": "localhost",
            "port": 4242,
            "enabled": True,
        }
        for changed in (
            {"name": "[bad]"},
            {"host": "a\nb"},
            {"host": "http://example.com"},
            {"port": True},
            {"port": 65536},
            {"enabled": "true"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_interfaces([{**item, **changed}])
        with self.assertRaises(ValueError):
            validate_interfaces([item, {**item, "name": "gateway"}])

    def test_failed_attach_restores_previous_configuration(self):
        """Roll back managed interface changes when attachment fails."""
        with tempfile.TemporaryDirectory() as directory:
            network = Network(Path(directory))
            network.config_path.parent.mkdir()
            network.managed = {}
            network.core = Mock()
            network.core.attach_interface.return_value = False
            write_config(network.config_path, {})
            item = {
                "name": "Gateway",
                "type": "TCPClientInterface",
                "host": "localhost",
                "port": 4242,
                "enabled": True,
            }
            with self.assertRaises(ValueError):
                network.apply_interfaces(False, [item])
            self.assertEqual(network.managed, {})
            self.assertEqual(
                dict(ConfigObj(str(network.config_path))["interfaces"]), {}
            )

    def test_tcp_peer_snapshot_tracks_actual_online_state(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(Path(directory))
            network.core = Mock()
            network.core.get_interface_stats.return_value = {
                "interfaces": [
                    {"type": "TCPClientInterface", "status": True},
                    {"type": "TCPClientInterface", "status": False},
                    {"type": "TCPServerInterface", "status": True},
                    {"type": "AutoInterface", "status": True, "peers": 2},
                ]
            }
            with patch(
                "network.time.sleep", side_effect=RuntimeError("end observation")
            ):
                network._observe()
            self.assertEqual(network.snapshot["peers"], 3)
            self.assertEqual(
                [x["peers"] for x in network.snapshot["interfaces"]], [1, 0, 0, 2]
            )
