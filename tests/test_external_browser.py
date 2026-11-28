"""External browser origins stay local, isolated, restartable and revocable."""

import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_web_services  # noqa: F401 - configure companion package paths
from nomadpl.http import Response

from profiles import ProfileStore
from web_services import WebServices


class ExternalBrowserTests(unittest.TestCase):
    def test_binary_download_exceeding_old_16mb_limit_completes(self):
        from urllib.parse import urlsplit

        body = b"x" * (17 * 1024 * 1024)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
            patch("web_services.Client") as factory,
        ):
            factory.return_value.request.return_value = Response(
                200,
                [
                    ("Content-Type", "application/octet-stream"),
                    ("Content-Disposition", 'attachment; filename="large.bin"'),
                ],
                body,
            )
            profiles = ProfileStore(directory)
            owner = profiles.create("Download test")["id"]
            web = WebServices(profiles)
            url = web.gateway(owner, "nomadpl://" + "a" * 32 + "/large.bin")
            parts = urlsplit(url)
            connection = http.client.HTTPConnection("127.0.0.1", parts.port, timeout=10)
            try:
                connection.request("GET", "/large.bin", headers={"Host": parts.netloc})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), body)
                self.assertEqual(
                    factory.call_args.kwargs["limits"].response_body, 64 * 1024 * 1024
                )
            finally:
                connection.close()
                for gateway, _ in web.gateways.values():
                    gateway.shutdown()
                    gateway.server_close()
                web.db.close()

    def test_named_gateway_boundaries_and_saved_port(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
            patch("web_services.Client") as factory,
        ):
            factory.return_value.request.return_value = Response(
                200, [("Content-Type", "text/html")], b"<h1>Local bridge</h1>"
            )
            profiles = ProfileStore(directory)
            owner = profiles.create("First")["id"]
            other = profiles.create("Second")["id"]
            web = WebServices(profiles)
            canonical = "nomadpl://" + "a" * 32 + "/guide/"
            with patch.object(web, "canonical", return_value=canonical):
                url = web.external(owner, "nomadpl://home.cix/guide/")["url"]
                second = web.external(other, "nomadpl://home.cix/guide/")["url"]
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            self.assertEqual(parts.hostname, "home.cix.localhost")
            self.assertNotEqual(parts.port, urlsplit(second).port)
            connection = http.client.HTTPConnection("127.0.0.1", parts.port, timeout=5)

            def request(headers):
                connection.request(
                    "GET", "/guide/", headers={"Host": parts.netloc, **headers}
                )
                result = connection.getresponse()
                return result.status, result.read()

            self.assertEqual(request({}), (200, b"<h1>Local bridge</h1>"))
            self.assertEqual(request({"Origin": "https://unrelated.example"})[0], 403)
            self.assertEqual(
                request({"Host": "wrong.localhost:" + str(parts.port)})[0], 421
            )
            self.assertEqual(request({})[0], 200)
            web.close_identity(owner)
            self.assertEqual(request({})[0], 502)
            connection.close()
            restored = WebServices(profiles)
            with patch.object(restored, "canonical", return_value=canonical):
                reopened = restored.external(owner, "nomadpl://home.cix/guide/")["url"]
            self.assertEqual(urlsplit(reopened).port, parts.port)
            restored.close_identity(owner)
            web.close_identity(other)
            restored.db.close()
            web.db.close()

    def test_bridge_rejects_non_network_and_invalid_hostnames(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("web_services.Discovery.start"),
        ):
            profiles = ProfileStore(directory)
            owner = profiles.create("First")["id"]
            web = WebServices(profiles)
            for value in [
                "https://example.com",
                "file:///secret",
                "nomadpl://user@home.cix/",
                "nomadpl://-home.cix/",
                "nomadpl://home..cix/",
                "nomadpl://home.cix:80/",
            ]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    web.external(owner, value)
            web.db.close()


if __name__ == "__main__":
    unittest.main()
