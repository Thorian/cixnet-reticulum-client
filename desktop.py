"""Desktop window and supervised receiver; each keeps its own main thread."""

import argparse
import json
import logging
import logging.handlers
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path


def data_directory():
    """Choose a persistent user-data folder without writing into the app bundle."""
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "ciXnet"
        )
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "cixnet"
    )


class InstanceLock:
    """An OS lock releases on a crash, unlike an easily stale PID file."""

    def __init__(self, directory, name="desktop.lock"):
        """Prepare the per-data-folder lock used to prevent duplicate windows."""
        self.path = directory / name
        self.file = None

    def __enter__(self):
        """Acquire the instance lock before starting a receiver or opening its data."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = self.path.open("a+b")
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError("ciXnet is already using this data folder") from error
        return self

    def __exit__(self, *exc):
        """Release the operating-system lock when the desktop session closes."""
        self.file.close()


class Receiver:
    def __init__(self, directory, no_local=False):
        """Track the local receiver process and the paths needed to restart it."""
        self.directory = directory
        self.no_local = no_local
        self.ready_file = directory / ("receiver-" + uuid.uuid4().hex + ".json")
        self.process = None
        self.log_thread = None
        self.logger = logging.getLogger("cixnet.receiver")
        self.recent_output = deque(maxlen=40)
        self.lan_unavailable = False

    def command(self):
        """Build the receiver command for source and frozen desktop launches."""
        port = 0
        try:
            saved = json.loads((self.directory / "desktop-port.json").read_text())
            if type(saved) is int and 0 < saved < 65536:
                port = saved
        except (OSError, ValueError):
            pass
        if getattr(sys, "frozen", False):
            suffix = ".exe" if sys.platform == "win32" else ""
            command = [str(Path(sys.executable).with_name("ciXnet-service" + suffix))]
        else:
            command = [sys.executable, str(Path(__file__).resolve())]
        command += [
            "--service",
            "--port",
            str(port),
            "--data",
            str(self.directory),
            "--ready-file",
            str(self.ready_file),
            "--desktop-parent",
        ]
        if getattr(sys, "frozen", False):
            # A packaged release must use its bundled dependencies, even on a
            # developer's machine that happens to have external source trees.
            for flag in (
                "--reticulum-source",
                "--lxmf-path",
                "--retdns-source",
                "--nomadpl-source",
            ):
                command += [flag, ""]
        if self.no_local:
            command.append("--no-local")
        if self.lan_unavailable:
            command.append("--lan-unavailable")
        return command

    def start(self):
        """Start the receiver, retrying only the supported local discovery conflict."""
        try:
            return self._start_once()
        except RuntimeError:
            # AutoInterface aborts the process on a Windows UDP bind conflict.
            # Retry only that specific failure, retaining TCP and saved settings.
            if self.log_thread:
                self.log_thread.join(timeout=2)
            output = "\n".join(self.recent_output)
            if (
                self.no_local
                or "WinError 10048" not in output
                or 'interface "Local network" could not be created' not in output
            ):
                raise
            self.stop()
            self.no_local = True
            self.lan_unavailable = True
            self.logger.warning(
                "LAN discovery port is occupied; restarting receiver with TCP available and LAN discovery disabled for this session"
            )
            return self._start_once()

    def _start_once(self):
        """Launch one receiver attempt and wait for its local HTTP service."""
        self.recent_output.clear()
        self.process = subprocess.Popen(
            self.command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        def capture_log():
            """Collect child-process output for startup diagnostics."""
            for line in self.process.stdout:
                self.recent_output.append(line.rstrip())
                self.logger.info(line.rstrip())

        self.log_thread = threading.Thread(target=capture_log, daemon=True)
        self.log_thread.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"The receiver stopped during startup (exit {self.process.returncode}). "
                    f"See {self.directory / 'receiver.log'}."
                )
            if self.ready_file.exists():
                ready = json.loads(self.ready_file.read_text())
                if (
                    type(ready.get("pid")) is not int
                    or not 0 < ready.get("port", 0) < 65536
                ):
                    raise RuntimeError("Invalid receiver startup information")
                self.ready_file.unlink()
                (self.directory / "desktop-port.json").write_text(
                    json.dumps(ready["port"])
                )
                return f"http://127.0.0.1:{ready['port']}"
            time.sleep(0.1)
        raise RuntimeError(
            "Receiver startup timed out. See receiver.log in the data folder."
        )

    def stop(self):
        """Stop the managed receiver and wait for its process to exit."""
        if self.process is None:
            return
        if self.process.poll() is None:
            # Closing the lifetime pipe asks HTTPServer to finish and lets
            # Reticulum save state. Force termination is a bounded fallback.
            self.process.stdin.close()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.log_thread:
            self.log_thread.join(timeout=2)
        self.process.stdout.close()
        self.ready_file.unlink(missing_ok=True)


def run_window(directory, url, receiver):
    """Open the native window around the receiver's loopback web interface."""
    receiver.logger.info("Loading desktop window runtime")
    import webview

    receiver.logger.info("Desktop window runtime imported")

    # Keep the existing token-protected HTTP boundary. No filesystem or private
    # key methods are exposed through pywebview's optional Python bridge.
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(
        "ciXnet",
        url,
        width=1160,
        height=800,
        min_size=(420, 560),
        background_color="#101914",
        text_select=True,
        confirm_close=True,
    )
    finished = threading.Event()
    receiver.logger.info("Desktop window created; starting Windows event loop")
    window.events.closed += finished.set
    window.events.shown += lambda: receiver.logger.info("Desktop window shown")
    window.events.loaded += lambda: receiver.logger.info("Desktop window loaded")

    def watch_receiver():
        """Keep the local receiver available while the desktop window is open."""
        receiver.process.wait()
        if not finished.is_set():
            # A dead receiver must not leave the UI claiming it is connected.
            window.load_html(
                "<html><body style='background:#101914;color:#eee;font:18px sans-serif;padding:40px'><h1>Receiver stopped</h1><p>Restart ciXnet to reconnect. Your saved messages remain in the data folder.</p></body></html>"
            )

    threading.Thread(target=watch_receiver, daemon=True).start()
    webview.start(
        gui="edgechromium" if sys.platform == "win32" else "gtk",
        private_mode=False,
        storage_path=str(directory / "webview"),
        debug=False,
        localization={
            "global.quitConfirmation": "Quit ciXnet? Message reception stops until you open it again. Minimize the window to keep receiving."
        },
    )


def main(argv=None):
    """Load desktop options, own the data-folder lock and launch the window."""
    parser = argparse.ArgumentParser(description="ciXnet desktop client")
    parser.add_argument("--data", type=Path, default=data_directory())
    parser.add_argument("--no-local", action="store_true", help="Disable LAN discovery")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start and stop the receiver without opening a window",
    )
    args = parser.parse_args(argv)
    directory = args.data.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    handler = logging.handlers.RotatingFileHandler(
        directory / "receiver.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    logger = logging.getLogger("cixnet.receiver")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    window_logger = logging.getLogger("pywebview")
    window_logger.addHandler(handler)
    diagnostic_file = None
    if os.environ.get("CIXNET_DESKTOP_DIAGNOSTICS") == "1":
        import faulthandler

        diagnostic_file = (directory / "desktop-diagnostics.log").open("w")
        faulthandler.dump_traceback_later(20, file=diagnostic_file)
    try:
        with InstanceLock(directory):
            receiver = Receiver(directory, args.no_local)
            try:
                url = receiver.start()
                if args.smoke_test:
                    from urllib.request import urlopen

                    with urlopen(url + "/api/state", timeout=5) as response:
                        state = json.load(response)
                    if state.get("transport") != "running":
                        raise RuntimeError("Receiver did not become ready")
                else:
                    run_window(directory, url, receiver)
            finally:
                receiver.stop()
    finally:
        logger.removeHandler(handler)
        window_logger.removeHandler(handler)
        if diagnostic_file:
            faulthandler.cancel_dump_traceback_later()
            diagnostic_file.close()
        handler.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--service" in sys.argv:
        # Reticulum can deliberately abort on an interface startup failure.
        # Flush diagnostics immediately so the parent retains the actual cause.
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(line_buffering=True, write_through=True)
        from server import main as service_main
        from server import parse_arguments

        service_args = [arg for arg in sys.argv[1:] if arg != "--service"]
        with InstanceLock(Path(parse_arguments(service_args).data), "receiver.lock"):
            service_main(service_args)
    else:
        try:
            main()
        except Exception as error:
            if "--smoke-test" in sys.argv:
                import traceback

                traceback.print_exc()
            if sys.platform == "win32" and "--smoke-test" not in sys.argv:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    None, str(error), "ciXnet could not start", 0x10
                )
            else:
                print(str(error), file=sys.stderr)
            raise SystemExit(1) from error
