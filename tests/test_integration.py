"""Exercise real independent Reticulum/LXMF processes over loopback TCP.

No existing user data is read or changed. All keys and databases live in a
temporary directory, and no private-key bytes are printed by these tests.
"""

import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def available_port():
    """Reserve an available loopback port number for a temporary test service."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check, timeout=30):
    """Poll a test condition until it succeeds or the bounded wait expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for the local integration test")


class Links(HTMLParser):
    def __init__(self):
        """Prepare the HTML parser's collection of local asset references."""
        super().__init__()
        self.local = []

    def handle_starttag(self, tag, attributes):
        """
        Collect local link and source attributes for the asset-boundary assertions.
        """
        for name, value in attributes:
            if (
                name in ("href", "src")
                and value
                and not urlparse(value).scheme
                and not value.startswith("#")
            ):
                self.local.append(value)


class ClientIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Start independent temporary clients for the shared integration scenarios."""
        cls.temporary = tempfile.TemporaryDirectory()
        cls.ports = [available_port(), available_port()]
        cls.transport_port = available_port()
        cls.processes = []
        cls.logs = []
        try:
            for index in (0, 1):
                cls.start_client(index)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def start_client(cls, index):
        """
        Launch one client with its own temporary identity and Reticulum configuration.
        """
        command = [
            sys.executable,
            "-u",
            str(ROOT / "server.py"),
            "--no-local",
            "--no-fallback",
            "--desktop-parent",
            "--port",
            str(cls.ports[index]),
            "--data",
            str(Path(cls.temporary.name) / str(index)),
        ]
        if os.environ.get("CIXNET_TEST_EXECUTABLE"):
            command = [os.environ["CIXNET_TEST_EXECUTABLE"], "--service", *command[3:]]
            for flag in (
                "--reticulum-source",
                "--lxmf-path",
                "--retdns-source",
                "--nomadpl-source",
            ):
                command += [flag, ""]
        for flag, variable in (
            ("--reticulum-source", "RETICULUM_SOURCE"),
            ("--lxmf-path", "LXMF_SOURCE"),
        ):
            if os.environ.get(variable):
                command += [flag, os.environ[variable]]
        command += [
            "--test-listen" if index == 0 else "--test-connect",
            str(cls.transport_port),
        ]
        log = open(
            Path(cls.temporary.name) / f"{index}-{len(cls.logs)}.log",
            "w",
            encoding="utf-8",
        )
        cls.logs.append(log)
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=log, stderr=log
        )
        if index < len(cls.processes):
            cls.processes[index] = process
        else:
            cls.processes.append(process)

        def ready():
            """
            Report when the temporary service has become available to the test client.
            """
            if process.poll() is not None:
                raise AssertionError(f"Test client {index} exited before startup")
            try:
                return cls.get(index, "state")
            except (URLError, TimeoutError):
                return None

        wait_for(ready)

    @classmethod
    def stop_client(cls, index):
        """Stop the selected fixture client and collect its process output."""
        process = cls.processes[index]
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        """Stop fixture processes and remove the shared temporary test state."""
        for index in range(len(cls.processes)):
            cls.stop_client(index)
        for log in cls.logs:
            log.close()
        cls.temporary.cleanup()

    @classmethod
    def get(cls, index, path):
        """Read a local API view through the fixture client's HTTP endpoint."""
        with urlopen(
            f"http://127.0.0.1:{cls.ports[index]}/api/{path}", timeout=2
        ) as response:
            return json.load(response)

    @classmethod
    def post(cls, index, path, body, raw=False, token=None, origin=None):
        """Submit an authenticated mutation to the fixture client's local API."""
        headers = {
            "Content-Type": "application/json",
            "X-Cixnet-Token": token
            if token is not None
            else cls.get(index, "state")["token"],
        }
        if origin:
            headers["Origin"] = origin
        request = Request(
            f"http://127.0.0.1:{cls.ports[index]}/api/{path}",
            json.dumps(body).encode(),
            headers,
        )
        with urlopen(request, timeout=5) as response:
            return response.read() if raw else json.load(response)

    def test_configured_tcp_interface_can_connect_edit_disable_and_survive_restart(
        self,
    ):
        """Apply TCP settings live and restore the configured state after a restart."""
        original = self.get(1, "state")["settings"]
        settings = {
            **original,
            "interfaces": [
                {
                    "name": "Settings test",
                    "type": "TCPClientInterface",
                    "host": "127.0.0.1",
                    "port": self.transport_port,
                    "enabled": True,
                }
            ],
        }

        def matching():
            """Find the expected interface state in the latest client snapshot."""
            return [
                item
                for item in self.get(1, "network")["interfaces"]
                if "ciXnet Settings test/" in item["name"]
            ]

        try:
            self.post(1, "settings", settings)
            wait_for(lambda: matching() and matching()[0]["online"])
            settings["interfaces"][0]["enabled"] = False
            self.post(1, "settings", settings)
            wait_for(lambda: not matching())
            settings["interfaces"][0]["enabled"] = True
            settings["interfaces"][0]["port"] = available_port()
            self.post(1, "settings", settings)
            wait_for(lambda: matching() and not matching()[0]["online"])
            settings["interfaces"][0]["port"] = self.transport_port
            self.post(1, "settings", settings)
            wait_for(lambda: matching() and matching()[0]["online"])
            self.stop_client(1)
            self.start_client(1)
            wait_for(lambda: matching() and matching()[0]["online"])
            self.assertEqual(
                self.get(1, "state")["settings"]["interfaces"], settings["interfaces"]
            )
            invalid = {
                **settings,
                "interfaces": [
                    {**settings["interfaces"][0], "host": "127.0.0.1\n[interfaces]"}
                ],
            }
            with self.assertRaises(HTTPError):
                self.post(1, "settings", invalid)
            self.assertEqual(self.get(1, "state")["settings"], settings)
        finally:
            self.post(1, "settings", original)
        wait_for(lambda: not matching())

    def test_offline_mailboxes_survive_restart_and_confirm_recipient(self):
        """
        Deliver durable relay copies and confirm completion only from the recipient.
        """
        relays = []
        original = [self.get(i, "state")["settings"] for i in (0, 1)]
        ports = [available_port(), available_port()]
        paths = [Path(self.temporary.name) / f"mailbox-{i}" for i in (0, 1)]

        def start_relay(i):
            """Start an isolated propagation node for the offline-delivery scenario."""
            log = open(paths[i].with_suffix(".log"), "a", encoding="utf-8")
            self.logs.append(log)
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tests" / "nomad_node_fixture.py"),
                    "--data",
                    str(paths[i]),
                    "--port",
                    str(ports[i]),
                    "--announce-interval",
                    "3",
                    "--with-relay",
                ],
                stdout=log,
                stderr=log,
            )
            if i < len(relays):
                relays[i] = process
            else:
                relays.append(process)
            wait_for(lambda: (paths[i] / "nodes.json").exists())
            return json.loads((paths[i] / "nodes.json").read_text())["relay"]

        def stop_relay(i):
            """Stop the temporary propagation node and wait for process cleanup."""
            relays[i].terminate()
            relays[i].wait(timeout=10)

        profiles = [
            self.post(i, "identity/create", {"nickname": f"Mailbox {i}"})
            for i in (0, 1)
        ]
        addresses = [
            self.post(i, "messaging/activate", {"owner": profiles[i]["id"]})["address"]
            for i in (0, 1)
        ]
        next_announce = 0

        def identities_known():
            """Check whether both test peers have learned the required destinations."""
            nonlocal next_announce
            # Earlier tests restart the listener; allow TCP's reconnect delay.
            if time.monotonic() >= next_announce:
                for index in (0, 1):
                    self.post(index, "identities/announce", {})
                next_announce = time.monotonic() + 3
            return all(
                any(
                    a["address"] == addresses[1 - index]
                    for a in self.get(index, "network")["announces"]
                )
                for index in (0, 1)
            )

        wait_for(identities_known, 60)
        try:
            servers = [start_relay(i) for i in (0, 1)]
            settings = []
            for i in (0, 1):
                settings.append(
                    {
                        **original[i],
                        "propagationServers": servers,
                        "deliveryMode": "relay" if i == 0 else "auto",
                        "interfaces": [
                            {
                                "name": f"Mailbox {j}",
                                "type": "TCPClientInterface",
                                "host": "127.0.0.1",
                                "port": ports[j],
                                "enabled": True,
                            }
                            for j in (0, 1)
                        ],
                    }
                )
                self.post(i, "settings", settings[i])
                wait_for(
                    lambda: all(
                        any(
                            a["address"] == server
                            for a in self.get(i, "network")["announces"]
                        )
                        for server in servers
                    ),
                    60,
                )
            self.stop_client(1)
            stop_relay(1)
            # Remove the cached live path before enqueuing; it returns later.
            settings[0]["interfaces"][1]["enabled"] = False
            self.post(0, "settings", settings[0])
            self.stop_client(0)
            self.start_client(0)
            sent = self.post(
                0,
                "messaging/send",
                {
                    "owner": profiles[0]["id"],
                    "peer": addresses[1],
                    "content": "Mail waits through disruption",
                    "attachments": [
                        {
                            "name": "mail.txt",
                            "data": base64.b64encode(b"durable cargo").decode(),
                        }
                    ],
                },
            )

            def outgoing():
                """Find the sender's stored state for the message under test."""
                return next(
                    (
                        m
                        for m in self.post(
                            0, "messaging/history", {"owner": profiles[0]["id"]}
                        )["messages"]
                        if m["id"] == sent["id"]
                    ),
                    {},
                )

            wait_for(lambda: outgoing().get("relay_copies") == 1, 120)
            self.assertTrue(outgoing()["queued"])
            self.stop_client(0)
            self.start_client(0)
            self.assertEqual(outgoing()["relay_copies"], 1)
            start_relay(1)
            settings[0]["interfaces"][1]["enabled"] = True
            self.post(0, "settings", settings[0])
            wait_for(lambda: outgoing().get("status") == "stored_on_relays", 120)
            self.assertEqual(outgoing()["relay_copies"], 2)
            self.start_client(1)

            def received():
                """Locate or capture the expected incoming message for this test."""
                return [
                    m
                    for m in self.post(
                        1, "messaging/history", {"owner": profiles[1]["id"]}
                    )["messages"]
                    if m["id"] == sent["id"]
                ]

            wait_for(received, 120)
            wait_for(lambda: outgoing().get("status") == "delivered", 120)
            self.assertEqual(len(received()), 1)
            self.assertFalse(outgoing()["queued"])
        finally:
            for i in (0, 1):
                if self.processes[i].poll() is not None:
                    self.start_client(i)
                self.post(i, "settings", original[i])
            for process in relays:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)

    def test_end_to_end_identity_and_messaging_workflow(self):
        """
        Exchange real messages across independent clients and preserve their identities.
        """
        profiles = [
            self.post(index, "identity/create", {"nickname": name})
            for index, name in enumerate(("Alpha", "Bravo"))
        ]
        first, second = profiles
        first = self.post(
            0,
            "identity/update",
            {
                **first,
                "nickname": "Alpha local",
                "display_name": "Alpha public",
                "icon": "pine-tree",
                "color": "teal",
            },
        )
        addresses = [
            self.post(index, "messaging/activate", {"owner": profile["id"]})["address"]
            for index, profile in enumerate((first, second))
        ]
        for index in (0, 1):
            self.assertTrue(self.post(index, "identities/announce", {})["ok"])
            wait_for(
                lambda: any(
                    entry["address"] == addresses[1 - index]
                    for entry in self.get(index, "network")["announces"]
                )
            )
        exported = self.post(0, "identity/export", {"id": first["id"]}, raw=True)
        imported = self.post(
            1,
            "identity/import",
            {
                "nickname": "Imported Alpha",
                "file": base64.b64encode(exported).decode(),
            },
        )
        self.assertEqual(imported["id"], first["id"])
        self.assertEqual(
            exported, self.post(1, "identity/export", {"id": imported["id"]}, raw=True)
        )
        with self.assertRaises(HTTPError) as duplicate:
            self.post(
                1,
                "identity/import",
                {"nickname": "Again", "file": base64.b64encode(exported).decode()},
            )
        self.assertEqual(duplicate.exception.code, 400)

        file_data = bytes(range(256)) * 512
        image_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg=="
        )
        sent = self.post(
            0,
            "messaging/send",
            {
                "owner": first["id"],
                "peer": addresses[1],
                "content": "Hello <script>literal text</script>",
                "attachments": [
                    {
                        "name": "../test.bin",
                        "data": base64.b64encode(file_data).decode(),
                        "image": False,
                    },
                    {
                        "name": "pixel.png",
                        "data": base64.b64encode(image_data).decode(),
                        "image": True,
                    },
                ],
            },
        )
        reply = self.post(
            1,
            "messaging/send",
            {
                "owner": second["id"],
                "peer": addresses[0],
                "content": "",
                "attachments": [
                    {
                        "name": "reply.txt",
                        "data": base64.b64encode(b"Attachment-only reply").decode(),
                    }
                ],
            },
        )
        for index, own, incoming, outgoing in (
            (0, first, reply, sent),
            (1, second, sent, reply),
        ):

            def delivered():
                """
                Report whether the intended recipient has acknowledged the test message.
                """
                history = self.post(index, "messaging/history", {"owner": own["id"]})[
                    "messages"
                ]
                return any(
                    item["id"] == incoming["id"] and item["direction"] == "in"
                    for item in history
                ) and any(
                    item["id"] == outgoing["id"] and item["status"] == "delivered"
                    for item in history
                )

            wait_for(delivered)
        received = self.post(1, "messaging/history", {"owner": second["id"]})
        received_message = next(
            item for item in received["messages"] if item["id"] == sent["id"]
        )
        self.assertEqual(len(received_message["attachments"]), 2)
        for item in received_message["attachments"]:
            result = self.post(
                1,
                "messaging/attachment",
                {
                    "owner": second["id"],
                    "message": sent["id"],
                    "position": item["position"],
                },
                raw=True,
            )
            self.assertEqual(result, image_data if item["image"] else file_data)
            self.assertNotIn("/", item["name"])
        with self.assertRaises(HTTPError):
            self.post(
                1,
                "messaging/attachment",
                {"owner": first["id"], "message": sent["id"], "position": 0},
                raw=True,
            )
        self.assertEqual(
            received["appearances"][addresses[0]],
            {
                "icon": "pine-tree",
                "foreground": "9de9de",
                "background": "204d49",
            },
        )

        # A process restart must preserve identity, history, and successful statuses.
        old_token = self.get(0, "state")["token"]
        self.stop_client(0)
        self.start_client(0)
        self.assertEqual(
            self.get(0, "state")["profiles"][0]["display_name"], "Alpha public"
        )
        self.assertEqual(
            self.post(0, "identity/export", {"id": first["id"]}, raw=True), exported
        )
        history = self.post(0, "messaging/history", {"owner": first["id"]})["messages"]
        self.assertEqual(
            self.get(0, "state")["profiles"][0]["message_count"], len(history)
        )
        self.assertEqual(
            self.post(0, "messaging/history", {"owner": first["id"]})["names"][
                addresses[1]
            ],
            "Bravo",
        )
        self.assertEqual(
            self.post(
                0,
                "messaging/attachment",
                {"owner": first["id"], "message": sent["id"], "position": 0},
                raw=True,
            ),
            file_data,
        )
        self.assertTrue(
            any(
                item["id"] == sent["id"] and item["status"] == "delivered"
                for item in history
            )
        )
        with self.assertRaises(HTTPError) as rejected:
            self.post(0, "identity/export", {"id": first["id"]}, token=old_token)
        self.assertEqual(rejected.exception.code, 403)

    def test_native_nomadnet_browser_against_actual_server_pages(self):
        """Browse actual server pages, forms and files through the native protocol."""
        fixture_data = Path(self.temporary.name) / "nomad-node"
        fixture_port = available_port()
        log = open(Path(self.temporary.name) / "nomad.log", "w", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tests" / "nomad_node_fixture.py"),
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
        original = self.get(0, "state")["settings"]
        try:

            def ready():
                """
                Report when the temporary service has become available to the test
                client.
                """
                if process.poll() is not None:
                    raise AssertionError("Native NomadNet test node failed to start")
                return (fixture_data / "nodes.json").exists()

            wait_for(ready)
            nodes = json.loads((fixture_data / "nodes.json").read_text())
            self.post(
                0,
                "settings",
                {
                    **original,
                    "interfaces": [
                        {
                            "name": "Page server",
                            "type": "TCPClientInterface",
                            "host": "127.0.0.1",
                            "port": fixture_port,
                            "enabled": True,
                        }
                    ],
                },
            )
            wait_for(
                lambda: any(
                    item["address"] == nodes["rich"] and item["kind"] == "node"
                    for item in self.get(0, "network")["announces"]
                )
            )
            owner = self.post(0, "identity/create", {"nickname": "Browser test"})["id"]
            other = self.post(0, "identity/create", {"nickname": "Other browser"})["id"]

            def load(url, **fields):
                """Start a fixture browser request and wait for its final result."""
                job = self.post(
                    0, "browser/open", {"owner": owner, "url": url, **fields}
                )

                def finished():
                    """
                    Report whether the fixture browser job has reached a terminal state.
                    """
                    status = self.post(
                        0, "browser/status", {"owner": owner, "id": job["id"]}
                    )
                    return status if status["phase"] in ("done", "error") else None

                result = wait_for(finished)
                self.assertEqual(result["phase"], "done", result.get("error"))
                return result

            for name in ("main", "community"):
                page = load(nodes[name])
                expected = (
                    ROOT / "tests" / "fixtures" / "pages" / name / "index.mu"
                ).read_text(encoding="utf-8")
                self.assertEqual(page["source"].replace("\r\n", "\n"), expected)
            discovered = wait_for(
                lambda: self.post(0, "dns/list", {"owner": owner})["discovered"]
            )
            self.assertTrue(any(item["address"] == nodes["dns"] for item in discovered))
            self.post(
                0,
                "dns/save",
                {"owner": owner, "suffix": ".cix", "address": nodes["dns"]},
            )
            self.assertEqual(
                self.post(0, "dns/list", {"owner": other})["saved"][0]["suffix"], "cix"
            )
            self.stop_client(0)
            self.start_client(0)
            self.assertEqual(
                self.post(0, "dns/list", {"owner": owner})["saved"][0]["address"],
                nodes["dns"],
            )
            native = load("native.cix")
            self.assertIn("Reticulum Host", native["source"])
            html = load("nomadpl://home.cix/")
            self.assertEqual(html["url"], "nomadpl://" + nodes["html"] + "/")
            self.assertEqual(html["requested_url"], "nomadpl://home.cix/")
            self.post(
                0,
                "browser/bookmark",
                {"owner": owner, "url": html["requested_url"], "name": "Z Home"},
            )
            external = self.post(
                0, "browser/external", {"owner": owner, "url": "nomadpl://home.cix/"}
            )
            named = urlparse(external["url"])
            self.assertEqual(named.hostname, "home.cix.localhost")
            for target, content in [("/", b"<html"), ("/assets/style.css", b"{")]:
                request = Request(
                    f"http://127.0.0.1:{named.port}{target}",
                    headers={"Host": named.netloc},
                )
                with urlopen(request, timeout=30) as response:
                    self.assertIn(content, response.read())
            self.assertFalse(external["launched"])
            frame = urlparse(html["frame"])
            req = Request(
                f"http://127.0.0.1:{frame.port}/", headers={"Host": frame.netloc}
            )
            with urlopen(req, timeout=30) as response:
                self.assertIn(b"<html", response.read())
            source = load("nomadpl://home.cix/", source=True)
            self.assertIn("<html", source["source"])
            self.assertIsNone(source["frame"])

            req = Request(
                f"http://127.0.0.1:{frame.port}/assets/style.css",
                headers={"Host": frame.netloc},
            )
            with urlopen(req, timeout=30) as response:
                self.assertIn("text/css", response.headers["Content-Type"])
            with self.assertRaises(HTTPError):
                urlopen(f"http://127.0.0.1:{frame.port}/", timeout=3)
            rich = load(nodes["rich"])
            self.assertIn("`!Bold`!", rich["source"])
            relative = load("next.mu", base=rich["url"])
            self.assertIn("Relative navigation works", relative["source"])
            result = load(
                "/page/result.mu",
                base=rich["url"],
                data={"field_name": "ciXnet", "var_mode": "test"},
                identify=True,
            )
            self.assertIn("Name: ciXnet", result["source"])
            self.assertIn("Identified: True", result["source"])
            download = load("/file/test.txt", base=rich["url"])
            self.assertEqual(download["download"]["name"], "test.txt")
            self.assertEqual(
                self.post(
                    0,
                    "browser/download",
                    {"owner": owner, "id": download["id"]},
                    raw=True,
                ),
                b"Native NomadNet file download\n",
            )
            with self.assertRaises(HTTPError):
                self.post(
                    0,
                    "browser/download",
                    {"owner": other, "id": download["id"]},
                    raw=True,
                )
            self.post(
                0,
                "browser/bookmark",
                {"owner": owner, "url": rich["url"], "name": "Native site"},
            )
            self.assertEqual(
                self.post(0, "browser/bookmarks", {"owner": other})["bookmarks"], []
            )
            pending = self.post(
                0,
                "browser/open",
                {"owner": owner, "url": nodes["rich"] + ":/page/missing.mu"},
            )
            self.assertEqual(self.get(0, "state")["core"], "available")
            with self.assertRaises(HTTPError):
                self.post(0, "browser/status", {"owner": other, "id": pending["id"]})
            self.post(0, "browser/cancel", {"owner": owner, "id": pending["id"]})
            self.assertEqual(
                self.post(0, "browser/status", {"owner": owner, "id": pending["id"]})[
                    "phase"
                ],
                "cancelled",
            )
            self.stop_client(0)
            self.start_client(0)
            self.assertEqual(
                self.post(0, "browser/bookmarks", {"owner": owner})["bookmarks"][0][
                    "name"
                ],
                "Native site",
            )
            saved = self.post(0, "browser/bookmarks", {"owner": owner})["bookmarks"]
            named = next(item for item in saved if item["name"] == "Z Home")
            self.assertEqual(named["url"], "nomadpl://home.cix/")
            self.assertIsNotNone(load(named["url"])["frame"])
        finally:
            self.post(0, "settings", original)
            process.terminate()
            process.wait(timeout=10)
            log.close()

    def test_request_boundary_and_about_assets(self):
        """
        Enforce the local HTTP boundary while keeping bundled information accessible.
        """
        for body, token, origin, expected in (
            ({}, "wrong", None, 403),
            ({}, None, "https://unrelated.example", 403),
            ([], None, None, 400),
            ({"nickname": ""}, None, None, 400),
        ):
            with (
                self.subTest(body=body, expected=expected),
                self.assertRaises(HTTPError) as rejected,
            ):
                self.post(0, "identity/create", body, token=token, origin=origin)
            self.assertEqual(rejected.exception.code, expected)
        request = Request(
            f"http://127.0.0.1:{self.ports[0]}/api/state",
            headers={"Host": "unrelated.example"},
        )
        with self.assertRaises(HTTPError) as rejected:
            urlopen(request, timeout=2)
        self.assertEqual(rejected.exception.code, 403)
        # Ambiguous request framing and duplicate authority headers are rejected.
        for headers, expected in (
            ([("Host", "untrusted.example")], 403),
            ([("Content-Length", "2")], 400),
            ([("Transfer-Encoding", "chunked")], 400),
        ):
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.ports[0], timeout=3
            )
            connection.putrequest("POST", "/api/identity/create")
            connection.putheader("Content-Length", "2")
            connection.putheader("X-Cixnet-Token", self.get(0, "state")["token"])
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders(b"{}")
            self.assertEqual(connection.getresponse().status, expected)
            connection.close()
        with self.assertRaises(HTTPError) as listing:
            urlopen(f"http://127.0.0.1:{self.ports[0]}/licenses/", timeout=3)
        self.assertEqual(listing.exception.code, 403)
        request = Request(
            f"http://127.0.0.1:{self.ports[0]}/",
            method="HEAD",
            headers={"Host": "untrusted.example"},
        )
        with self.assertRaises(HTTPError) as head:
            urlopen(request, timeout=3)
        self.assertEqual(head.exception.code, 403)
        base = f"http://127.0.0.1:{self.ports[0]}/"
        with urlopen(base + "about.html") as response:
            about = response.read().decode()
        self.assertIn("MIT License", about)
        self.assertIn("Reticulum", about)
        self.assertIn("LXMF", about)
        links = Links()
        links.feed(about)
        for link in links.local:
            with self.subTest(link=link), urlopen(base + link.lstrip("/")) as response:
                self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
