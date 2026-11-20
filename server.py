"""Start the loopback development client; this is not a native release server."""

import argparse
import json
import os
import sys
import threading
from http.server import HTTPServer
from pathlib import Path


class ClientServer(HTTPServer):
    def service_actions(self):
        # HTTPServer invokes this on the main thread, including when idle.
        """Advance background networking and delivery between HTTP requests."""
        self.application.fallback.tick()
        self.application.pairing.tick()
        self.application.messaging.announce_due()
        self.application.messaging.outbox.tick()
        self.application.messaging.verify_pending()


def parse_arguments(argv=None):
    """Read receiver options and dependency paths without starting services."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reticulum-source",
        default=os.environ.get("RETICULUM_SOURCE", ""),
    )
    parser.add_argument(
        "--lxmf-path",
        default=os.environ.get("LXMF_SOURCE", ""),
    )
    parser.add_argument(
        "--data",
        default=str(
            Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
            / "cixnet-preview"
        ),
    )
    parser.add_argument(
        "--retdns-source",
        default=os.environ.get("RETDNS_SOURCE", ""),
    )
    parser.add_argument(
        "--nomadpl-source",
        default=os.environ.get("NOMADPL_SOURCE", ""),
    )
    parser.add_argument(
        "--ui-root",
        type=Path,
        default=Path(__file__).parent / "ui",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--desktop-parent", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--lan-unavailable", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--test-listen", type=int, help="Loopback Reticulum TCP listener port"
    )
    parser.add_argument(
        "--test-connect", type=int, help="Loopback Reticulum TCP target port"
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Disable AutoInterface for same-machine tests",
    )
    parser.add_argument("--no-fallback", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(
    argv=None,
    *,
    on_ready=None,
    on_message=None,
    stop_event=None,
    on_open_url=None,
    private_api=False,
    internet=None,
):
    """Start the local services and serve the client on its loopback address."""
    args = parse_arguments(argv)
    os.environ["CIXNET_UI_ROOT"] = str(args.ui_root)
    # Dependencies remain in their own source directories with their own licenses.
    sys.path[:0] = [
        source
        for source in (
            args.reticulum_source,
            args.lxmf_path,
            args.retdns_source,
            args.nomadpl_source,
        )
        if source and Path(source).is_dir()
    ]
    from http_api import Application, Handler
    from messaging import Messaging
    from network import Network
    from profiles import ProfileStore

    profiles = ProfileStore(args.data)
    network = Network(profiles.directory, args.test_listen, args.test_connect)
    # Reticulum and LXMF install signal handlers. Keep creation on the main thread;
    # HTTPServer (not ThreadingHTTPServer) also executes activation on this thread.
    saved_settings = profiles.read()["settings"]
    network.start(
        saved_settings["localDiscovery"] and not args.no_local,
        saved_settings["interfaces"],
    )
    if network.phase != "running":
        raise RuntimeError(f"Reticulum startup failed: {network.error}")
    if args.lan_unavailable:
        network.error = "LAN discovery is unavailable because another Reticulum client is using its port. TCP connections remain available. Close the other client and restart ciXnet to restore LAN discovery."
    messaging = Messaging(profiles.directory)
    messaging.on_message = on_message
    messaging.outbox.configure(saved_settings)
    messaging.announce_minutes = profiles.read()["settings"]["announceMinutes"]
    for profile in profiles.read()["profiles"]:
        messaging.activate(profile)
        messaging.announce(profile["id"])
    try:
        server = ClientServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if not args.desktop_parent or args.port == 0:
            raise
        server = ClientServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    application = Application(
        profiles,
        network,
        messaging,
        args.ui_root,
        port,
        args.no_local,
    )
    last_gateway_announce = [float("-inf")]

    def gateway_connected():
        # Identities announced before the TCP link existed are unknown to its
        # peers. Announce once on attachment, with a reconnect flood guard.
        import time

        now = time.monotonic()
        if now - last_gateway_announce[0] >= 60:
            for profile in profiles.read()["profiles"]:
                messaging.announce(profile["id"])
            last_gateway_announce[0] = now

    application.fallback.on_connected = gateway_connected
    if internet is not None:
        application.fallback.internet = internet
    application.fallback.suspended = args.no_fallback
    if private_api:
        import secrets

        application.access_key = secrets.token_urlsafe(32)
    if on_open_url is not None:
        application.open_browser = on_open_url
    server.application = application
    print(f"ciXnet client: http://127.0.0.1:{port}", flush=True)
    if args.ready_file:
        temporary = args.ready_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "port": port}))
        temporary.replace(args.ready_file)
    if on_ready:
        on_ready(server)
    if stop_event is not None:

        def watch_service():
            stop_event.wait()
            server.shutdown()

        threading.Thread(target=watch_service, daemon=True).start()
    if args.desktop_parent:

        def watch_parent():
            # EOF also occurs if the window process crashes. No orphan receiver.
            """Stop the receiver when its supervising desktop process disappears."""
            sys.stdin.buffer.read()
            server.shutdown()

        threading.Thread(target=watch_parent, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        application.fallback.close()
        server.server_close()
        if args.desktop_parent or stop_event is not None:
            for router, _ in messaging.routers.values():
                router.exit_handler()
            network.core.exit_handler()


if __name__ == "__main__":
    main()
