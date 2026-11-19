"""Authority selection is explicit, persistent, and scoped to an identity."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401

from profiles import ProfileStore
from web_services import WebServices


class WebServicesTests(unittest.TestCase):
    def test_default_dns_is_added_once_and_custom_authority_is_preserved(self):
        """Seed .cix without undoing a user's replacement or removal on restart."""
        from web_services import DEFAULT_DNS_SERVER

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
        ):
            profiles = ProfileStore(directory)
            owner = profiles.create("Test")["id"]
            web = WebServices(profiles)
            self.assertEqual(
                web.servers(owner)["saved"],
                [{"suffix": "cix", "address": DEFAULT_DNS_SERVER}],
            )
            web.save(owner, "cix", "c" * 32)
            # Simulate an upgrade from the previous schema with a custom mapping.
            web.db.execute("DELETE FROM dns_migrations WHERE version=2")
            web.db.commit()
            web.db.close()
            reopened = WebServices(profiles)
            self.assertEqual(reopened.servers(owner)["saved"][0]["address"], "c" * 32)
            reopened.save(owner, "cix", None, remove=True)
            reopened.db.close()
            after_removal = WebServices(profiles)
            self.assertEqual(after_removal.servers(owner)["saved"], [])
            after_removal.db.close()

    def test_suffix_persistence_owner_isolation_and_resolution(self):
        """Persist explicit DNS suffix choices and use them for the intended lookup."""
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
        ):
            profiles = ProfileStore(directory)
            first = profiles.create("First")["id"]
            second = profiles.create("Second")["id"]
            web = WebServices(profiles)
            web.save(first, ".CIX", "a" * 32)
            self.assertEqual(web.servers(second)["saved"], web.servers(first)["saved"])
            reopened = WebServices(profiles)
            self.assertEqual(reopened.servers(first)["saved"][0]["suffix"], "cix")
            with patch("web_services.Resolver") as resolver:
                resolver.return_value.__enter__.return_value.resolve.return_value = (
                    "b" * 32
                )
                result = web.canonical(
                    first, "nomadpl://home.ret.cix/guide/?a=1&a=2#part"
                )
                self.assertEqual(
                    result, "nomadpl://" + "b" * 32 + "/guide/?a=1&a=2#part"
                )
                resolver.return_value.__enter__.return_value.resolve.assert_called_once_with(
                    "home.ret"
                )
            web.save(first, ".cix", None, remove=True)
            self.assertEqual(web.servers(first)["saved"], [])
            after_removal = WebServices(profiles)
            self.assertEqual(after_removal.servers(second)["saved"], [])
            after_removal.db.close()
            web.db.close()
            reopened.db.close()

    def test_invalid_authorities_are_rejected(self):
        """Reject malformed authority choices before modifying saved DNS settings."""
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
        ):
            profiles = ProfileStore(directory)
            owner = profiles.create("Test")["id"]
            web = WebServices(profiles)
            for suffix, address in [
                ("../bad", "a" * 32),
                ("foo.bar", "a" * 32),
                (".cix", "not-a-destination"),
            ]:
                with self.assertRaises(ValueError):
                    web.save(owner, suffix, address)
            self.assertEqual(
                web.canonical(owner, "a" * 32 + ":/file/test.txt"),
                "a" * 32 + ":/file/test.txt",
            )
            web.db.close()


class SourceRecordingTests(unittest.TestCase):
    def test_close_revokes_requests_and_releases_transport_once(self):
        """Locking blocks new requests and closes the retained transport link."""
        import threading
        from unittest.mock import Mock

        from nomadpl import Request

        from web_services import SourceRecordingClient

        released = threading.Event()
        transport = Mock()
        transport.close.side_effect = released.set
        recorder = SourceRecordingClient(transport)
        recorder.close()
        recorder.close()
        self.assertTrue(released.wait(2))
        transport.close.assert_called_once_with()
        with self.assertRaises(ConnectionError):
            recorder.request(Request("GET", "/"))
        transport.request.assert_not_called()

    def test_source_never_requests_the_page_again(self):
        """Show saved HTML source without triggering a second remote fetch."""
        from unittest.mock import Mock

        from nomadpl import Request, Response

        from web_services import SourceRecordingClient

        transport = Mock()
        transport.request.return_value = Response(
            200, [("Content-Type", "text/html")], b"<html>original</html>"
        )
        recorder = SourceRecordingClient(transport)
        recorder.request(Request("GET", "/?a=1"))
        transport.request.side_effect = AssertionError("Source must not transmit")
        self.assertEqual(recorder.source("/?a=1"), "<html>original</html>")
        self.assertEqual(recorder.source("/?a=1"), "<html>original</html>")
        with self.assertRaises(ValueError):
            recorder.source("/missing")
        self.assertEqual(transport.request.call_count, 1)


class NavigationInjectionTests(unittest.TestCase):
    def test_bridge_changes_display_response_but_not_saved_source(self):
        """
        Inject browser navigation support without changing the retained original HTML.
        """
        from unittest.mock import Mock

        from nomadpl import Request, Response

        from web_services import SourceRecordingClient

        transport = Mock()
        original = b"<html><head></head><body>Page</body></html>"
        transport.request.return_value = Response(
            200,
            [("Content-Type", "text/html"), ("Content-Length", str(len(original)))],
            original,
        )
        client = SourceRecordingClient(transport)
        client.bridge_markup = b'<script src="/local-bridge.js"></script>'
        result = client.request(Request("GET", "/guide/?a=1"))
        self.assertIn(client.bridge_markup, result.body)
        self.assertNotIn(
            "content-length", [key.lower() for key, value in result.headers]
        )
        self.assertEqual(client.source("/guide/?a=1"), original.decode())
        self.assertEqual(transport.request.call_count, 1)

    def test_source_versions_distinguish_get_and_post_at_the_same_url(self):
        """
        Keep form-response source distinct from a previous GET at the same address.
        """
        from unittest.mock import Mock

        from nomadpl import Request, Response

        from web_services import SourceRecordingClient

        transport = Mock()
        transport.request.side_effect = [
            Response(200, [("Content-Type", "text/html")], b"GET document"),
            Response(200, [("Content-Type", "text/html")], b"POST document"),
        ]
        client = SourceRecordingClient(transport)
        client.request(Request("GET", "/form/"))
        first = next(iter(client.source_versions))
        client.request(Request("POST", "/form/", [], b"name=test"))
        second = list(client.source_versions)[-1]
        self.assertEqual(client.source("/form/", first), "GET document")
        self.assertEqual(client.source("/form/", second), "POST document")
        self.assertEqual(transport.request.call_count, 2)
