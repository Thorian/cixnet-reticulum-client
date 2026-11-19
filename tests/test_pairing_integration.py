"""Real two-process pairing checks, using disposable clients and identities."""

import base64
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
import test_integration as fixtures
from test_integration import wait_for


class PairingIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ClientIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.ClientIntegrationTests.tearDownClass.__func__)
    start_client = classmethod(fixtures.ClientIntegrationTests.start_client.__func__)
    stop_client = classmethod(fixtures.ClientIntegrationTests.stop_client.__func__)
    get = classmethod(fixtures.ClientIntegrationTests.get.__func__)
    post = classmethod(fixtures.ClientIntegrationTests.post.__func__)

    def test_pairing_full_history_attachment_access_and_revocation(self):
        desktop = self.get(0, "state")
        phone = self.post(1, "identity/create", {"nickname": "Paired phone"})
        hidden = self.post(1, "identity/create", {"nickname": "Not shared"})
        owner = phone["id"]
        peer = "ab" * 16
        content = "Archived antenna rendezvous from phone"
        attachment = base64.b64encode(b"phone saved attachment" * 5000).decode()
        sent = self.post(
            1,
            "messaging/send",
            {
                "owner": owner,
                "peer": peer,
                "content": content,
                "attachments": [{"name": "saved.txt", "data": attachment}],
            },
        )
        status = self.get(0, "pairing/status")
        if not status["addresses"]:
            self.skipTest("No private LAN adapter available")
        invitation = self.post(
            0,
            "pairing/invite",
            {"host": status["addresses"][0], "name": "Test desktop"},
        )
        self.post(
            1,
            "pairing/connect",
            {"code": invitation["code"], "owners": [owner], "name": "Test phone"},
        )
        wait_for(lambda: self.get(0, "pairing/status")["connected"], timeout=30)

        def remote(path, body=None):
            if body is None:
                with urlopen(
                    f"http://127.0.0.1:{self.ports[0]}/api/{path}", timeout=60
                ) as response:
                    return json.load(response)
            request = Request(
                f"http://127.0.0.1:{self.ports[0]}/api/{path}",
                json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Cixnet-Token": desktop["token"],
                },
            )
            try:
                response = urlopen(request, timeout=60)
            except HTTPError as error:
                error.add_note(error.read().decode("utf-8", errors="replace"))
                raise
            with response:
                return (
                    response.read()
                    if path == "messaging/attachment"
                    else json.load(response)
                )

        shared = remote("state")
        self.assertEqual([p["id"] for p in shared["profiles"]], [owner])
        self.assertEqual(shared["token"], desktop["token"])
        history = remote("messaging/history", {"owner": owner})
        self.assertIn(content, [message["content"] for message in history["messages"]])
        self.assertEqual(
            remote(
                "messaging/attachment",
                {"owner": owner, "message": sent["id"], "position": 0},
            ),
            base64.b64decode(attachment),
        )
        with self.assertRaises(HTTPError):
            remote("messaging/history", {"owner": hidden["id"]})
        with self.assertRaises(HTTPError):
            remote("identity/export", {"id": owner})
        remote("messaging/block", {"owner": owner, "peer": peer, "blocked": True})
        self.assertIn(
            peer, self.post(1, "messaging/history", {"owner": owner})["blocked"]
        )
        # A larger outgoing attachment is chunked in the other direction.
        uploaded = remote(
            "messaging/send",
            {
                "owner": owner,
                "peer": "cd" * 16,
                "content": "Paired upload",
                "attachments": [{"name": "upload.txt", "data": attachment}],
            },
        )
        self.assertIn(
            uploaded["id"],
            [
                m["id"]
                for m in self.post(1, "messaging/history", {"owner": owner})["messages"]
            ],
        )
        # Resume approved access after a complete phone receiver restart.
        self.stop_client(1)
        self.start_client(1)
        wait_for(lambda: self.get(0, "pairing/status")["connected"], timeout=40)
        self.assertIn(
            content,
            [
                m["content"]
                for m in remote("messaging/history", {"owner": owner})["messages"]
            ],
        )
        # Host a real NomadPL/DNS node, then use only the paired desktop UI API.
        fixture_data = Path(self.temporary.name) / "paired-pages"
        fixture_port = fixtures.available_port()
        log = open(
            Path(self.temporary.name) / "paired-pages.log", "w", encoding="utf-8"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(fixtures.ROOT / "tests" / "nomad_node_fixture.py"),
                "--port",
                str(fixture_port),
                "--data",
                str(fixture_data),
                "--announce-interval",
                "3",
            ],
            stdout=log,
            stderr=log,
        )
        try:
            wait_for(lambda: (fixture_data / "nodes.json").exists())
            nodes = json.loads((fixture_data / "nodes.json").read_text())
            settings = self.get(1, "state")["settings"]
            self.post(
                1,
                "settings",
                {
                    **settings,
                    "interfaces": [
                        {
                            "name": "Paired page fixture",
                            "type": "TCPClientInterface",
                            "enabled": True,
                            "host": "127.0.0.1",
                            "port": fixture_port,
                        }
                    ],
                },
            )
            wait_for(
                lambda: any(
                    item["address"] == nodes["html"]
                    for item in self.get(1, "network")["announces"]
                )
            )
            remote(
                "dns/save", {"owner": owner, "suffix": "cix", "address": nodes["dns"]}
            )
            remote(
                "browser/bookmark",
                {"owner": owner, "url": "nomadpl://home.cix/", "name": "Home"},
            )
            self.assertTrue(remote("browser/bookmarks", {"owner": owner})["bookmarks"])
            job = remote("browser/open", {"owner": owner, "url": "nomadpl://home.cix/"})

            def loaded():
                result = remote("browser/status", {"owner": owner, "id": job["id"]})
                if result["phase"] == "failed":
                    raise AssertionError(result)
                return result if result["phase"] == "done" else None

            page = wait_for(loaded, timeout=45)
            from urllib.parse import urlsplit

            frame = urlsplit(page["frame"])
            request = Request(
                f"http://127.0.0.1:{frame.port}{frame.path}",
                headers={"Host": frame.netloc},
            )
            with urlopen(request, timeout=60) as response:
                html = response.read().decode()
            self.assertIn("<html", html.lower())
            self.assertIn(f'data-parent="http://127.0.0.1:{self.ports[0]}"', html)
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()
        device = self.get(1, "pairing/status")["devices"][0]
        self.post(1, "pairing/revoke", {"id": device["id"]})
        time.sleep(0.5)
        with self.assertRaises(HTTPError):
            remote("messaging/history", {"owner": owner})


if __name__ == "__main__":
    unittest.main()
