"""Desktop process ownership, shutdown and restart without a GUI dependency."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import InstanceLock, Receiver  # noqa: E402


class DesktopTests(unittest.TestCase):
    def test_only_lan_port_conflict_retries_without_discovery(self):
        """
        Retry a local discovery bind conflict without masking other startup failures.
        """
        with tempfile.TemporaryDirectory() as directory:
            receiver = Receiver(Path(directory))

            def start():
                """
                Simulate one receiver launch while recording the attempted startup
                options.
                """
                if not receiver.no_local:
                    receiver.recent_output.extend(
                        [
                            'The interface "Local network" could not be created',
                            "[WinError 10048] Address already in use",
                        ]
                    )
                    raise RuntimeError("Receiver stopped")
                return "http://127.0.0.1:1234"

            with patch.object(receiver, "_start_once", side_effect=start):
                self.assertEqual(receiver.start(), "http://127.0.0.1:1234")
            self.assertTrue(receiver.lan_unavailable)
            self.assertIn("--lan-unavailable", receiver.command())

    def test_other_startup_errors_are_not_silently_retried(self):
        """
        Keep unrelated receiver failures visible instead of retrying with changed
        settings.
        """
        with tempfile.TemporaryDirectory() as directory:
            receiver = Receiver(Path(directory))
            with patch.object(
                receiver, "_start_once", side_effect=RuntimeError("Different failure")
            ) as start:
                with self.assertRaisesRegex(RuntimeError, "Different failure"):
                    receiver.start()
                start.assert_called_once()
            self.assertFalse(receiver.no_local)

    def test_data_folder_lock_releases_and_blocks_a_second_window(self):
        """
        Prevent competing desktop windows from using the same persistent data folder.
        """
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            with InstanceLock(directory):
                with self.assertRaises(RuntimeError):
                    with InstanceLock(directory):
                        self.fail("Duplicate instance acquired the same folder")
            with InstanceLock(directory):
                pass

    def test_receiver_restarts_on_same_port_with_saved_identity_and_exits_cleanly(self):
        # Uses installed dependencies, as the packaged application will.
        """
        Recover the receiver while preserving its address, data and shutdown behavior.
        """
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            receiver = Receiver(directory, no_local=True)
            try:
                url = receiver.start()
                with urlopen(url + "/api/state", timeout=5) as response:
                    state = json.load(response)
                request = Request(
                    url + "/api/identity/create",
                    data=json.dumps({"nickname": "Desktop restart test"}).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "X-Cixnet-Token": state["token"],
                    },
                )
                with urlopen(request, timeout=5) as response:
                    profile = json.load(response)
                receiver.stop()
                self.assertEqual(receiver.process.returncode, 0)
                restarted = receiver.start()
                self.assertEqual(restarted, url)
                with urlopen(url + "/api/state", timeout=5) as response:
                    state = json.load(response)
                self.assertTrue(
                    any(item["id"] == profile["id"] for item in state["profiles"])
                )
            finally:
                receiver.stop()
            self.assertEqual(receiver.process.returncode, 0)
            self.assertFalse(list(directory.glob("receiver-*.json")))
