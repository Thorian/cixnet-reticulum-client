"""Service-owned Python receiver; Android owns process lifetime and notifications."""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "cixnet"))
_stop = threading.Event()


def stop():
    _stop.set()


class AndroidInternet:
    """Bind only the gateway socket to cellular, never the process's LAN sockets."""

    def __init__(self, service):
        self.native = service.fallbackInternet()

    def prepare(self, needed):
        return str(self.native.prepare(needed))

    def open_socket(self, host, port):
        import socket

        network = self.native.cellularNetwork()
        if network is None:
            return socket.create_connection((host, port), timeout=8)
        from java import jclass

        descriptor_type = jclass("android.os.ParcelFileDescriptor")
        connection = None
        try:
            addresses = network.getAllByName(host)
            for address in addresses:
                text = str(address.getHostAddress())
                family = socket.AF_INET6 if ":" in text else socket.AF_INET
                connection = socket.socket(family, socket.SOCK_STREAM)
                descriptor = descriptor_type.fromFd(connection.fileno())
                try:
                    network.bindSocket(descriptor.getFileDescriptor())
                finally:
                    descriptor.close()
                connection.settimeout(8)
                try:
                    connection.connect((text, port))
                    return connection
                except OSError:
                    connection.close()
            raise OSError("No reachable cellular gateway address")
        except Exception as error:
            if connection:
                connection.close()
            raise OSError("Cellular gateway connection failed") from error


def run(service, directory, ui):
    import RNS.Stamps

    # Chaquopy cannot fork Python workers. Use Reticulum's own portable worker;
    # the stamp format, difficulty and verification remain unchanged.
    RNS.Stamps.job_android = RNS.Stamps.job_simple
    from server import main

    _stop.clear()

    def ready(server):
        service.receiverReady(server.server_address[1], server.application.access_key)

    def received(owner, peer, ident):
        service.messageReceived(owner, peer, ident)

    main(
        ["--data", directory, "--port", "0", "--ui-root", ui],
        on_ready=ready,
        on_message=received,
        stop_event=_stop,
        on_open_url=service.openBrowser,
        private_api=True,
        internet=AndroidInternet(service),
    )
