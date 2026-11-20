"""NomadNet addressing and persistent, per-identity bookmarks."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_core  # noqa: F401 - dependency source configuration

from nomad_browser import NomadBrowser, resolve_url
from profiles import ProfileStore

NODE = "a" * 32


class BrowserTests(unittest.TestCase):
    def test_native_addresses_and_relative_paths(self):
        """Resolve native page and file links while rejecting unsupported URL shapes."""
        self.assertEqual(resolve_url(NODE), NODE + ":/page/index.mu")
        self.assertEqual(
            resolve_url("nnn@" + NODE + ":/page/start.mu"), NODE + ":/page/start.mu"
        )
        self.assertEqual(
            resolve_url("../next.mu#section", NODE + ":/page/sub/start.mu"),
            NODE + ":/page/next.mu",
        )
        for value in (
            "https://example.com/",
            "javascript:alert(1)",
            "<script>",
            NODE + ":/identity",
            NODE + ":/page/../../secret.mu",
            NODE + ":/page/test\n.mu",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_url(value)

    def test_identity_choice_is_per_node_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles = ProfileStore(directory)
            first, second = profiles.create("First"), profiles.create("Second")
            browser = NomadBrowser(profiles)
            page = NODE + ":/page/start.mu"
            browser.page_identity(first["id"], page, True)
            self.assertTrue(
                browser.page_identity(first["id"], ":/page/start.mu", base=page)[
                    "identify"
                ]
            )
            self.assertTrue(
                browser.page_identity(first["id"], NODE + ":/page/other.mu")["identify"]
            )
            self.assertFalse(browser.page_identity(second["id"], page)["identify"])
            self.assertFalse(browser.page_identity(first["id"], "b" * 32)["identify"])
            browser.db.close()
            browser = NomadBrowser(profiles)
            self.assertTrue(browser.page_identity(first["id"], page)["identify"])
            browser.page_identity(first["id"], page, False)
            self.assertFalse(browser.page_identity(first["id"], page)["identify"])
            browser.db.close()

    def test_legacy_page_choice_applies_to_the_node(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles = ProfileStore(directory)
            owner = profiles.create("Legacy")["id"]
            browser = NomadBrowser(profiles)
            browser.db.execute(
                "INSERT INTO page_identity VALUES (?, ?, ?)",
                (owner, NODE + ":/page/start.mu", 1),
            )
            browser.db.commit()
            self.assertTrue(
                browser.page_identity(owner, NODE + ":/page/next.mu")["identify"]
            )
            browser.db.close()

    def test_html_node_choice_covers_paths_queries_and_dns_aliases(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            profiles = ProfileStore(directory)
            owner = profiles.create("HTML")["id"]
            web = SimpleNamespace(
                canonical=lambda owner, url: url.replace("home.cix", NODE)
            )
            browser = NomadBrowser(profiles, web)
            browser.page_identity(owner, "nomadpl://home.cix/start", True)
            self.assertTrue(
                browser.page_identity(owner, "nomadpl://" + NODE + "/next?x=2")[
                    "identify"
                ]
            )
            self.assertFalse(
                browser.page_identity(owner, "nomadpl://" + "b" * 32 + "/")["identify"]
            )
            browser.page_identity(owner, "nomadpl://" + NODE + "/next", False)
            self.assertFalse(
                browser.page_identity(owner, "nomadpl://home.cix/start")["identify"]
            )
            browser.db.close()

    def test_bookmarks_survive_restart_and_remain_per_identity(self):
        """Persist bookmarks without exposing one identity's list to another."""
        with tempfile.TemporaryDirectory() as directory:
            profiles = ProfileStore(directory)
            first, second = profiles.create("First"), profiles.create("Second")
            browser = NomadBrowser(profiles)
            browser.bookmark(first["id"], NODE, "Saved site")
            attack = "Saved'); DROP TABLE bookmarks; --"
            browser.bookmark(first["id"], NODE, attack)
            self.assertEqual(browser.bookmarks(first["id"])[0]["name"], attack)
            browser.bookmark(first["id"], NODE, "Saved site")
            browser.db.close()
            reopened = NomadBrowser(profiles)
            self.assertEqual(
                reopened.bookmarks(first["id"]),
                [{"url": NODE + ":/page/index.mu", "name": "Saved site"}],
            )
            self.assertEqual(reopened.bookmarks(second["id"]), [])
            reopened.bookmark(first["id"], NODE, "Saved site", remove=True)
            self.assertEqual(reopened.bookmarks(first["id"]), [])
            reopened.db.close()


class AnnounceDecodingTests(unittest.TestCase):
    def test_binary_metadata_is_not_lossy_utf8(self):
        """
        Decode structured announce metadata without corrupting binary data as text.
        """
        import RNS.vendor.umsgpack as msgpack

        from network import readable_announce

        self.assertEqual(readable_announce(b"Community"), "Community")
        decoded = readable_announce(msgpack.packb({"name": "DNS", "version": 1}))
        self.assertIn('"name": "DNS"', decoded)
        self.assertNotIn("\ufffd", decoded)
        self.assertIn("Binary announce", readable_announce(b"\xff\x00\x01"))
