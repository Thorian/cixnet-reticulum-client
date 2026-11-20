"""Real emulator receiver/notification tests. Never selects a physical phone.

Run with --adb PATH --apk PATH. Temporary sender keys are not printed or exported.
"""

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "net.cixnet.client"


def wait_for(check, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError) as error:
            last = error
        time.sleep(1)
    raise AssertionError("Timed out waiting for emulator test condition") from last


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Api:
    def __init__(self, port, host_port=None, access_key=None):
        self.authorization = (
            {"Authorization": "Bearer " + access_key} if access_key else {}
        )
        self.port = port
        self.host_port = host_port or port
        self.token = self.get("state")["token"]

    def get(self, path):
        with urlopen(
            Request(
                f"http://127.0.0.1:{self.port}/api/{path}",
                headers={"Host": f"127.0.0.1:{self.host_port}", **self.authorization},
            ),
            timeout=10,
        ) as response:
            return json.load(response)

    def post(self, path, body):
        headers = {
            **self.authorization,
            "Host": f"127.0.0.1:{self.host_port}",
            "Origin": f"http://127.0.0.1:{self.host_port}",
            "Content-Type": "application/json",
            "X-Cixnet-Token": self.token,
        }
        with urlopen(
            Request(
                f"http://127.0.0.1:{self.port}/api/{path}",
                data=json.dumps(body).encode(),
                headers=headers,
            ),
            timeout=20,
        ) as response:
            return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Verify final APK startup and a real message",
    )
    args = parser.parse_args()
    if not args.device.startswith("emulator-"):
        parser.error("This test is restricted to an emulator; test your phone manually")
    # Process termination needs the disposable AOSP emulator's debug shell.
    subprocess.run(
        [str(args.adb), "-s", args.device, "root"], check=True, capture_output=True
    )
    subprocess.run([str(args.adb), "-s", args.device, "wait-for-device"], check=True)
    results = []

    def adb(*command, check=True):
        result = subprocess.run(
            [str(args.adb), "-s", args.device, *command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if check and result.returncode:
            raise AssertionError("ADB test operation failed: " + result.stderr.strip())
        return result.stdout.strip()

    def passed(name, **details):
        results.append(dict(test=name, status="passed", **details))
        print("PASS: " + name, flush=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, indent=2), encoding="utf-8")

    if adb("shell", "getprop", "sys.boot_completed") != "1":
        raise AssertionError("Boot the emulator before starting these tests")
    adb("shell", "am", "force-stop", PACKAGE)
    adb("install", "-r", str(args.apk.resolve()))
    adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    forwards = []
    restore_deep_idle = False

    def mobile_api():
        value = adb(
            "shell", "run-as", PACKAGE, "cat", "files/receiver-ready.json", check=False
        )
        if not value:
            error = adb(
                "shell",
                "run-as",
                PACKAGE,
                "cat",
                "files/receiver-error.txt",
                check=False,
            )
            if error:
                return None  # A previous process may leave an error until startup clears it.
            return None
        ready = json.loads(value)
        port = ready["port"]
        local = available_port()
        adb("forward", f"tcp:{local}", f"tcp:{port}")
        forwards.append(local)
        return Api(local, port, ready["accessKey"])

    process = None
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        try:
            mobile = wait_for(mobile_api, 120)
            # A surviving receiver alone must not hide an activity startup crash.
            activity = adb("shell", "dumpsys", "activity", "activities")
            assert any(
                PACKAGE + "/.MainActivity" in line
                and ("topResumedActivity" in line or "mResumedActivity" in line)
                for line in activity.splitlines()
            ), "Client activity did not stay open"
            passed(
                "Android receiver starts",
                api_level=adb("shell", "getprop", "ro.build.version.sdk"),
            )
            original = mobile.get("state")["settings"]
            existing = next(
                (
                    p
                    for p in mobile.get("state")["profiles"]
                    if p["nickname"] == "Android emulator test"
                ),
                None,
            )
            owner = (
                existing
                or mobile.post("identity/create", {"nickname": "Android emulator test"})
            )["id"]
            mobile_address = mobile.post("messaging/activate", {"owner": owner})[
                "address"
            ]
            transport = available_port()
            # Forward the isolated test link explicitly; Windows firewall policy
            # must not decide whether an emulator protocol test can reach its host.
            adb("reverse", f"tcp:{transport}", f"tcp:{transport}")
            sender_port = available_port()
            log = (directory / "sender.log").open("w", encoding="utf-8")

            def start_sender():
                nonlocal process
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "server.py"),
                        "--no-local",
                        "--no-fallback",
                        "--desktop-parent",
                        "--port",
                        str(sender_port),
                        "--data",
                        str(directory / "sender"),
                        "--test-listen",
                        str(transport),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=log,
                )
                return wait_for(lambda: Api(sender_port), 45)

            sender = start_sender()
            sender_owner = sender.post(
                "identity/create", {"nickname": "Emulator test sender"}
            )["id"]
            sender_address = sender.post("messaging/activate", {"owner": sender_owner})[
                "address"
            ]
            mobile.post(
                "settings",
                {
                    **original,
                    "localDiscovery": False,
                    "fallback": False,
                    "interfaces": [
                        {
                            "name": "Emulator test link",
                            "type": "TCPClientInterface",
                            "host": "127.0.0.1",
                            "port": transport,
                            "enabled": True,
                        }
                    ],
                },
            )
            wait_for(
                lambda: any(
                    item["online"] and "Emulator test link" in item["name"]
                    for item in mobile.get("network")["interfaces"]
                )
            )
            sender.post("identities/announce", {})
            mobile.post("identities/announce", {})
            wait_for(
                lambda: any(
                    x["address"] == mobile_address
                    for x in sender.get("network")["announces"]
                ),
                timeout=900,  # First production-strength destination stamp is cached.
            )

            def deliver(text):
                sender.post(
                    "messaging/send",
                    {"owner": sender_owner, "peer": mobile_address, "content": text},
                )
                wait_for(
                    lambda: any(
                        x["content"] == text
                        for x in mobile.post("messaging/history", {"owner": owner})[
                            "messages"
                        ]
                    )
                )

            def notification():
                return any(
                    PACKAGE in line and owner + ":" + sender_address in line
                    for line in adb("shell", "cmd", "notification", "list").splitlines()
                )

            deliver("Android notification check")
            wait_for(notification, 15)
            dump = adb("shell", "dumpsys", "notification", "--noredact")
            assert "Android notification check" not in dump, (
                "Notification leaked message body"
            )
            passed(
                "Incoming message saved and notification posted without message body"
            )
            if args.quick:
                passed("Final APK startup and real delivery verified")
                return
            adb(
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.HOME",
            )
            ui_pid = adb("shell", "pidof", PACKAGE, check=False)
            if ui_pid:
                adb("shell", "kill", "-9", ui_pid)
                wait_for(lambda: not adb("shell", "pidof", PACKAGE, check=False), 15)
            assert adb("shell", "pidof", PACKAGE + ":receiver"), (
                "Receiver died with activity"
            )
            deliver("Received after UI process closes")
            passed("Background reception survives UI process termination")
            old_pid = adb("shell", "pidof", PACKAGE + ":receiver")
            adb("shell", "kill", "-9", old_pid)
            wait_for(
                lambda: (
                    (pid := adb("shell", "pidof", PACKAGE + ":receiver", check=False))
                    and pid != old_pid
                ),
                120,
            )
            mobile = wait_for(mobile_api, 120)
            assert any(
                x["content"] == "Android notification check"
                for x in mobile.post("messaging/history", {"owner": owner})["messages"]
            )
            deliver("Received after receiver restarts")
            passed("Receiver process recovers with saved identities and messages")
            process.stdin.close()
            process.wait(timeout=15)
            mobile.post(
                "messaging/send",
                {
                    "owner": owner,
                    "peer": sender_address,
                    "content": "Queued through network interruption",
                },
            )
            sender = start_sender()
            wait_for(
                lambda: any(
                    x["content"] == "Queued through network interruption"
                    for x in sender.post("messaging/history", {"owner": sender_owner})[
                        "messages"
                    ]
                ),
                120,
            )
            passed("Queued message delivered after network reconnect")
            adb(
                "shell",
                "pm",
                "revoke",
                PACKAGE,
                "android.permission.POST_NOTIFICATIONS",
            )
            adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
            mobile = wait_for(mobile_api, 120)
            # Android can retain an earlier notification after revocation. A new
            # sender gives this check a fresh notification tag.
            sender_owner = sender.post(
                "identity/create", {"nickname": "Permission test sender"}
            )["id"]
            sender_address = sender.post("messaging/activate", {"owner": sender_owner})[
                "address"
            ]
            deliver("Saved with notifications denied")
            assert not notification(), "Denied notification was still posted"
            passed("Denied notifications do not prevent message reception")
            adb(
                "shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS"
            )
            deliver("Notifications restored")
            wait_for(notification, 15)
            passed("Notifications resume after permission is granted")
            restore_deep_idle = "mDeepEnabled=false" in adb(
                "shell", "dumpsys", "deviceidle"
            )
            adb("shell", "dumpsys", "deviceidle", "enable", "deep")
            adb("shell", "dumpsys", "battery", "unplug")
            idle = adb("shell", "dumpsys", "deviceidle", "force-idle", check=False)
            if "Now forced" in idle:
                sender.post(
                    "messaging/send",
                    {
                        "owner": sender_owner,
                        "peer": mobile_address,
                        "content": "Doze recovery check",
                    },
                )
                time.sleep(5)
                adb("shell", "dumpsys", "deviceidle", "unforce")
                adb("shell", "dumpsys", "battery", "reset")
                wait_for(
                    lambda: any(
                        x["content"] == "Doze recovery check"
                        for x in mobile.post("messaging/history", {"owner": owner})[
                            "messages"
                        ]
                    ),
                    120,
                )
                passed(
                    "Message recovery after Doze", immediate_delivery_not_assumed=True
                )
            else:
                results.append(
                    dict(test="Doze recovery", status="not exercised", reason=idle)
                )
            passed("Smoke suite completed")
        finally:
            adb("shell", "dumpsys", "deviceidle", "unforce", check=False)
            adb("shell", "dumpsys", "battery", "reset", check=False)
            if restore_deep_idle:
                adb("shell", "dumpsys", "deviceidle", "disable", "deep", check=False)
            if process and process.poll() is None:
                process.stdin.close()
                process.wait(timeout=15)
            if "log" in locals():
                log.close()
            if "transport" in locals():
                adb("reverse", "--remove", f"tcp:{transport}", check=False)
            for port in forwards:
                adb("forward", "--remove", f"tcp:{port}", check=False)


if __name__ == "__main__":
    main()
