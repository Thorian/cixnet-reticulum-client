"""Persistent discovery, untrusted imports and strict publication filters."""

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stations import Stations

spec = importlib.util.spec_from_file_location(
    "compile_stations",
    Path(__file__).resolve().parents[1] / "deployment/gateway/compile_stations.py",
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def station(**changes):
    now = time.time()
    return dict(
        identity="ab" * 16,
        name="Demo radio",
        latitude=44.0,
        longitude=-63.0,
        frequency=914875000,
        bandwidth=125000,
        sf=8,
        cr=5,
        first_seen=now - 60 * 86400,
        last_seen=now - 100,
        **changes,
    )


class StationTests(unittest.TestCase):
    def test_merge_keeps_local_observations_when_directory_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Stations(directory)
            store.learn(
                dict(
                    type="RNodeInterface",
                    transport_id="ab" * 16,
                    name="Demo radio",
                    latitude=44.0,
                    longitude=-63.0,
                    frequency=914875000,
                    bandwidth=125000,
                    sf=8,
                    cr=5,
                )
            )
            document = dict(version=1, compiled_at=time.time(), stations=[station()])
            store.import_list(json.dumps(document).encode())
            result = store.list(45.0, -63.0)
            self.assertEqual(len(result["stations"]), 1)
            self.assertEqual(
                set(result["stations"][0]["sources"]), {"learned", "directory"}
            )
            self.assertAlmostEqual(
                result["stations"][0]["distance_km"], 111.2, places=1
            )
            document.update(compiled_at=time.time(), stations=[])
            store.import_list(json.dumps(document).encode())
            self.assertEqual(store.list()["stations"][0]["sources"], ["learned"])
            with self.assertRaises(ValueError):
                store.list(None, 0)
            store.db.close()

    def test_learn_persists_and_does_not_save_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Stations(directory)
            info = dict(
                type="RNodeInterface",
                transport_id="ab" * 16,
                name="Demo radio",
                latitude=44.0,
                longitude=-63.0,
                frequency=914875000,
                bandwidth=125000,
                sf=8,
                cr=5,
                ifac_netkey="never-save-me",
            )
            store.learn(info)
            first = store.list()["stations"][0]["first_seen"]
            store.learn(info)
            info["sf"] = 10
            store.learn(info)
            store.db.close()
            reopened = Stations(directory)
            rows = reopened.list(44.0, -63.0)["stations"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(reopened.list()["profiles"]), 2)
            self.assertTrue(all(row["reception"] == "advertised" for row in rows))
            self.assertEqual(rows[0]["distance_km"], 0)
            self.assertIn(first, [r["first_seen"] for r in rows])
            self.assertNotIn("never-save-me", json.dumps(rows))
            reopened.db.close()

    def test_bad_import_is_atomic_and_keeps_learned_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Stations(directory)
            document = dict(version=1, compiled_at=time.time(), stations=[station()])
            store.import_list(json.dumps(document).encode())
            for invalid in [
                dict(station(), latitude=float("nan")),
                dict(station(), sf=7.5),
                None,
            ]:
                document["stations"] = [invalid]
                with self.assertRaises(ValueError):
                    store.import_list(json.dumps(document).encode())
                self.assertEqual(len(store.list()["stations"]), 1)
            document["stations"] = [station()]
            document["compiled_at"] -= 100
            with self.assertRaises(ValueError):
                store.import_list(json.dumps(document).encode())
            store.db.close()

    def test_compiler_strict_month_and_day_boundaries_and_profile_fields(self):
        now = time.time()
        base = dict(
            iface_type="RNodeInterface",
            hash="ab" * 16,
            display_name="Demo radio",
            lat=44.0,
            lon=-63.0,
            frequency="914.875 MHz",
            bandwidth="125.0 kHz",
            spreading_factor=8,
            coding_rate=5,
            first_seen_ts=compiler.month_before(now) - 1,
            last_seen_ts=now - 1,
        )
        rows = [
            base,
            dict(
                base, display_name="too young", first_seen_ts=compiler.month_before(now)
            ),
            dict(base, display_name="too old", last_seen_ts=now - 86400),
            dict(base, display_name="missing position", lat=None),
            dict(base, display_name="future", last_seen_ts=now + 1),
        ]
        result = compiler.compile_list(
            "const allNodes = " + json.dumps(rows) + ";", now
        )
        self.assertEqual(len(result["stations"]), 1)
        self.assertEqual(result["stations"][0]["frequency"], 914875000)
        with self.assertRaises(ValueError):
            compiler.compile_list("const allNodes = [];", now)


if __name__ == "__main__":
    unittest.main()
