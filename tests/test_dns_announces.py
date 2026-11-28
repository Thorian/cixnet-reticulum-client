"""Decode genuine retdns announces and reject malformed discovery metadata."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import RNS
import RNS.vendor.umsgpack as msgpack
import test_core  # noqa: F401

from network import Network


class DNSAnnounceTests(unittest.TestCase):
    def test_other_announces_expire_after_five_minutes_since_last_heard(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(directory)
            identity = RNS.Identity()
            unknown = bytes.fromhex("01" * 16)
            node = RNS.Destination.hash_from_name_and_identity(
                "nomadnetwork.node", identity
            )
            with patch("network.time.time", return_value=1000):
                network.received_announce(unknown, identity, b"Other")
                network.received_announce(node, identity, b"Site")
            with patch("network.time.time", return_value=1300):
                self.assertEqual(2, len(network.status()["announces"]))
                network.received_announce(unknown, identity, b"Other refreshed")
            with patch("network.time.time", return_value=1600):
                self.assertEqual(2, len(network.status()["announces"]))
            with patch("network.time.time", return_value=1601):
                entries = network.status()["announces"]
            self.assertEqual([node.hex()], [entry["address"] for entry in entries])

    def test_discovery_retains_more_than_500_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(directory)
            identity = RNS.Identity()
            for number in range(600):
                network.received_announce(number.to_bytes(16, "big"), identity, b"Node")
            self.assertEqual(600, len(network.status()["announces"]))

    def test_retention_evicts_least_recently_heard_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(directory)
            identity = RNS.Identity()
            addresses = [number.to_bytes(16, "big") for number in range(4)]
            with patch("network.MAX_DISCOVERED_DESTINATIONS", 3):
                for address in addresses[:3]:
                    network.received_announce(address, identity, b"Node")
                network.received_announce(addresses[0], identity, b"Updated")
                network.received_announce(addresses[3], identity, b"New")
            self.assertEqual(3, len(network.announces))
            self.assertIn(addresses[0].hex(), network.announces)
            self.assertNotIn(addresses[1].hex(), network.announces)

    def test_dns_namespace_name_and_destination_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(directory)
            identity = RNS.Identity()
            destination = RNS.Destination.hash_from_name_and_identity(
                "retdns.server", identity
            )
            network.received_announce(
                destination,
                identity,
                msgpack.packb({"version": 1, "name": "ciXnet DNS"}),
            )
            entry = network.status()["announces"][0]
            self.assertEqual(entry["kind"], "dns")
            self.assertEqual(entry["address"], destination.hex())
            self.assertEqual(entry["display_name"], "ciXnet DNS")
            self.assertEqual(entry["dns"], {"version": 1, "name": "ciXnet DNS"})

    def test_malformed_or_unsupported_dns_metadata_is_not_offered(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Network(directory)
            identity = RNS.Identity()
            destination = RNS.Destination.hash_from_name_and_identity(
                "retdns.server", identity
            )
            for info in [
                {"version": 2, "name": "Future"},
                {"version": True, "name": "Wrong type"},
                {"version": 1, "name": "bad\nname"},
                {"version": 1, "name": "x" * 129},
                {"name": "Missing version"},
                ["wrong"],
            ]:
                network.received_announce(destination, identity, msgpack.packb(info))
            self.assertEqual(network.status()["announces"], [])
