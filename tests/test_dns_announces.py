"""Decode genuine retdns announces and reject malformed discovery metadata."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import RNS
import RNS.vendor.umsgpack as msgpack
import test_core  # noqa: F401

from network import Network


class DNSAnnounceTests(unittest.TestCase):
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
