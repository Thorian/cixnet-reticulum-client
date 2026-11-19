"""Android loopback access requires an app-private capability and mutation token."""

import http.client
import sys
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import test_web_services  # noqa: F401 - companion dependency paths

from http_api import Handler


class PrivateApiTests(unittest.TestCase):
    def test_private_reads_and_writes_reject_other_local_apps(self):
        server = HTTPServer(("127.0.0.1", 0), Handler)
        host = "127.0.0.1:" + str(server.server_port)
        server.application = SimpleNamespace(
            host=host,
            origin="http://" + host,
            access_key="private-test-key",
            token="mutation-test-token",
            ui_root=Path(__file__).parent,
            get=lambda path: {"token": "mutation-test-token"},
            post=lambda path, body: {"accepted": True},
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port)

        def request(method, headers=None):
            connection.request(
                method,
                "/api/state",
                body="{}" if method == "POST" else None,
                headers=headers or {},
            )
            response = connection.getresponse()
            response.read()
            return response.status

        try:
            self.assertEqual(request("GET"), 403)
            self.assertEqual(request("GET", {"Authorization": "Bearer wrong"}), 403)
            private = {"Authorization": "Bearer private-test-key"}
            self.assertEqual(request("GET", private), 200)
            self.assertEqual(request("POST", private), 403)
            mutation = {**private, "X-Cixnet-Token": "mutation-test-token"}
            self.assertEqual(request("POST", mutation), 200)
            self.assertEqual(
                request("POST", {**mutation, "Origin": "https://other.example"}), 403
            )
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join()
