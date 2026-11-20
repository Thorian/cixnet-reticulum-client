"""Real messages over an automatically attached fallback TCP interface."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from android_smoke import Api
from test_integration import ROOT, available_port, wait_for


class FallbackIntegrationTests(unittest.TestCase):
    def test_automatic_gateway_delivers_and_disable_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            processes = []
            logs = []
            ports = [available_port(), available_port()]
            transport = available_port()

            def start(index):
                command = [
                    sys.executable,
                    str(ROOT / "tests" / "client_fixture.py"),
                    "--no-local",
                    "--desktop-parent",
                    "--port",
                    str(ports[index]),
                    "--data",
                    str(Path(directory) / str(index)),
                ]
                if index == 0:
                    command += ["--test-listen", str(transport), "--no-fallback"]
                log = open(
                    Path(directory) / f"{index}-{len(logs)}.log", "w", encoding="utf-8"
                )
                logs.append(log)
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=log, stderr=log
                )
                processes.append(process)

                def ready():
                    if process.poll() is not None:
                        raise AssertionError("Client did not start")
                    try:
                        return Api(ports[index])
                    except Exception:
                        return None

                return process, wait_for(ready)

            try:
                _, gateway = start(0)
                client_process, client = start(1)
                recipient = gateway.post(
                    "identity/create", {"nickname": "Fallback recipient"}
                )
                sender = client.post("identity/create", {"nickname": "Fallback sender"})
                target = gateway.post("messaging/activate", {"owner": recipient["id"]})[
                    "address"
                ]
                settings = client.get("state")["settings"]
                self.assertTrue(settings["fallback"])
                self.assertEqual(settings["fallbackHost"], "gw.cixnet.org")
                client.post(
                    "settings",
                    {
                        **settings,
                        "fallbackHost": "127.0.0.1",
                        "fallbackPort": transport,
                    },
                )
                wait_for(
                    lambda: client.get("network")["gateway"]["connected"], timeout=40
                )
                gateway.post("identities/announce", {})
                wait_for(
                    lambda: any(
                        item["address"] == target
                        for item in client.get("network")["announces"]
                    )
                )
                sent = client.post(
                    "messaging/send",
                    {
                        "owner": sender["id"],
                        "peer": target,
                        "content": "Delivered through automatic gateway",
                    },
                )
                wait_for(
                    lambda: any(
                        item["id"] == sent["id"]
                        for item in gateway.post(
                            "messaging/history", {"owner": recipient["id"]}
                        )["messages"]
                    )
                )
                observed = client.get("network")["gateway"]
                self.assertTrue(observed["connected"])
                self.assertFalse(
                    observed["serverAvailable"]
                )  # Ordinary LXMF peer does not suppress fallback.
                settings = client.get("state")["settings"]
                client.post("settings", {**settings, "fallback": False})
                wait_for(lambda: not client.get("network")["gateway"]["connected"])
                client_process.stdin.close()
                client_process.wait(timeout=15)
                _, client = start(1)
                self.assertFalse(client.get("state")["settings"]["fallback"])
                self.assertEqual(
                    client.get("state")["settings"]["fallbackPort"], transport
                )
                time.sleep(3)
                self.assertEqual(client.get("network")["gateway"]["phase"], "disabled")
            finally:
                if sys.exc_info()[0]:
                    for index, port in enumerate(ports):
                        try:
                            api = Api(port)
                            print("CLIENT", index, api.get("network"))
                            for profile in api.get("state")["profiles"]:
                                print(
                                    "HISTORY",
                                    index,
                                    api.post(
                                        "messaging/history", {"owner": profile["id"]}
                                    ),
                                )
                        except Exception:
                            pass
                    for path in Path(directory).glob("*.log"):
                        print(
                            path.name,
                            path.read_text(encoding="utf-8", errors="replace")[-3500:],
                        )
                for process in processes:
                    if process.poll() is None:
                        process.stdin.close()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                for log in logs:
                    log.close()
