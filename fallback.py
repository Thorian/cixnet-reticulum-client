"""Automatic Internet uplink; ordinary LAN peers never suppress the fallback."""

import ipaddress
import queue
import re
import socket
import threading
import time

import RNS
from RNS.Interfaces.TCPInterface import TCPClientInterface

NAME = "ciXnet automatic gateway"


class ConnectedTCPInterface(TCPClientInterface):
    """Start a reader for the socket already opened on the selected network."""

    def final_init(self):
        # Reticulum calls this during registration. The normal TCP initializer
        # opens another socket; this interface must retain the supplied one.
        # A public Internet uplink routinely exceeds the default new-interface
        # limit of three announces/second. Keep ingress control active, with a
        # bounded queue and a rate suited to this connection rather than radio.
        self.ic_burst_freq_new = 50
        self.ic_burst_freq = 50
        self.ic_max_held_announces = 256
        threading.Thread(target=self.read_loop, daemon=True).start()


def validate_gateway(host, port):
    if not isinstance(host, str) or not 1 <= len(host.strip()) <= 253:
        raise ValueError("Enter a gateway hostname or IP address")
    host = host.strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?",
            host,
        ):
            raise ValueError(
                "Gateway must be a hostname or IP without a URL or port"
            ) from None
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Gateway port must be 1–65535")
    return host, port


class Internet:
    """Desktop routing uses the OS. Android supplies a cellular-aware adapter."""

    def prepare(self, needed):
        return "default" if needed else "idle"

    def open_socket(self, host, port):
        return socket.create_connection((host, port), timeout=8)


class FallbackGateway:
    STARTUP_GRACE = 15
    HANDOVER_DELAY = 60

    def __init__(self, network, internet=None, clock=time.monotonic):
        self.network = network
        self.internet = internet or Internet()
        self.clock = clock
        self.enabled = True
        self.host, self.port = "gw.cixnet.org", 4242
        self.suspended = False
        self.interface = None
        self.probes = {}
        self.next_probe = 0
        self.server_since = None
        self.started = clock()
        self.next_attempt = self.started + self.STARTUP_GRACE
        self.failures = 0
        self.generation = 0
        self.worker = False
        self.results = queue.Queue(maxsize=1)
        self.route = "idle"
        self.phase = "discovering"
        self.error = None
        self.last_tick = 0
        self.available_server = None
        self.on_connected = None
        network.fallback = self

    def configure(self, settings):
        host, port = validate_gateway(
            settings.get("fallbackHost", "gw.cixnet.org"),
            settings.get("fallbackPort", 4242),
        )
        enabled = settings.get("fallback", True)
        if (enabled, host, port) != (self.enabled, self.host, self.port):
            self.generation += 1
            self._detach()
            self.enabled, self.host, self.port = enabled, host, port
            self.failures = 0
            self.next_attempt = self.clock()
            self.last_tick = -10
        if not enabled:
            self.internet.prepare(False)
            self.phase = "disabled"

    def snapshot(self):
        return {
            "enabled": self.enabled and not self.suspended,
            "host": self.host,
            "port": self.port,
            "phase": self.phase,
            "error": self.error,
            "connected": bool(self.interface and self.interface.online),
            "route": self.route,
            "serverAvailable": bool(self.available_server),
            "server": self.available_server,
        }

    def _detach(self):
        if self.interface:
            self.network.core.detach_interface(NAME)
            self.interface = None

    def _via_fallback(self, interface):
        seen = set()
        while interface is not None and id(interface) not in seen:
            seen.add(id(interface))
            if interface is self.interface or getattr(interface, "name", None) == NAME:
                return True
            interface = getattr(interface, "parent_interface", None)
        return False

    def _server(self, now):
        """Require a live Link to a role-specific signed relay/transport announce.

        A TCP socket, peer count, or a cached announce alone is insufficient.
        Paths through our own fallback cannot switch that fallback off.
        """
        with self.network.lock:
            entries = list(self.network.announces.values())
        candidates = {
            item["address"]: item
            for item in entries
            if item["kind"] in ("relay", "transport")
            and time.time() - item["received"] < 2700
        }
        available = None
        for address, (link, created) in list(self.probes.items()):
            iface = getattr(link, "attached_interface", None)
            if (
                address not in candidates
                or link.status == RNS.Link.CLOSED
                or (iface is not None and not getattr(iface, "online", True))
                or self._via_fallback(iface)
                or (link.status != RNS.Link.ACTIVE and now - created > 30)
            ):
                link.teardown()
                self.probes.pop(address, None)
            elif link.status == RNS.Link.ACTIVE:
                available = {"address": address, "kind": candidates[address]["kind"]}
        if available or now < self.next_probe:
            return available
        self.next_probe = now + 15
        for address in candidates:
            if address in self.probes or len(self.probes) >= 4:
                continue
            destination_hash = bytes.fromhex(address)
            if not RNS.Transport.has_path(destination_hash) or self._via_fallback(
                RNS.Transport.next_hop_interface(destination_hash)
            ):
                continue
            identity = RNS.Identity.recall(destination_hash)
            if identity is None:
                continue
            aspects = (
                ("lxmf", "propagation")
                if candidates[address]["kind"] == "relay"
                else ("rnstransport", "discovery", "interface")
            )
            destination = RNS.Destination(
                identity, RNS.Destination.OUT, RNS.Destination.SINGLE, *aspects
            )
            if destination.hash != destination_hash:
                continue
            self.probes[address] = (RNS.Link(destination), now)
            break
        return None

    def _connect(self, generation, host, port):
        connection = None
        error = None
        try:
            connection = self.internet.open_socket(host, port)
            connection.settimeout(None)
        except OSError as failure:
            error = str(failure)[:160]
        self.results.put((generation, connection, error))

    def _collect(self, now):
        try:
            generation, connection, error = self.results.get_nowait()
        except queue.Empty:
            return
        self.worker = False
        if generation != self.generation or not self.enabled or self.suspended:
            if connection:
                connection.close()
            return
        if connection is None:
            self.failures += 1
            self.next_attempt = now + min(900, 15 * 2 ** min(self.failures - 1, 6))
            self.error = error
            self.phase = "retrying"
            return
        try:
            interface = ConnectedTCPInterface(
                RNS.Transport, {"name": NAME}, connected_socket=connection
            )
            # Less aggressive TCP keepalives than a continuously probed 5-second
            # link. Android battery endurance still needs physical measurement.
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in (
                ("TCP_KEEPIDLE", 180),
                ("TCP_KEEPINTVL", 30),
                ("TCP_KEEPCNT", 3),
            ):
                if hasattr(socket, name):
                    try:
                        connection.setsockopt(
                            socket.IPPROTO_TCP, getattr(socket, name), value
                        )
                    except OSError:
                        pass
            interface.target_ip = self.host
            interface.target_port = self.port
            interface.online = True
            interface.never_connected = False
            self.network.core._add_interface(interface)
            self.interface = interface
            interface.wants_tunnel = True
            self.failures = 0
            self.error = None
            self.phase = "connected"
            if self.on_connected:
                self.on_connected()
        except Exception as failure:
            connection.close()
            self.error = str(failure)[:160]
            self.phase = "retrying"
            self.next_attempt = now + 30

    def tick(self):
        now = self.clock()
        self._collect(now)
        if now - self.last_tick < 3:
            return
        self.last_tick = now
        if not self.enabled or self.suspended:
            self.generation += 1
            self._detach()
            self.internet.prepare(False)
            self.phase = "disabled"
            return
        self.available_server = self._server(now)
        if self.available_server:
            if self.server_since is None:
                self.server_since = now
            if not self.interface or now - self.server_since >= self.HANDOVER_DELAY:
                self.generation += 1
                self._detach()
                self.internet.prepare(False)
                self.phase = "local_server"
                return
        else:
            self.server_since = None
        if now - self.started < self.STARTUP_GRACE:
            return
        route = self.internet.prepare(True)
        if route in ("waiting", "offline", "vpn_waiting"):
            self.generation += 1
            self._detach()
            self.phase = "waiting_internet"
            self.route = route
            return
        if self.route != route:
            self.generation += 1
            self._detach()
            self.route = route
            self.next_attempt = now
        if self.interface and self.interface.online:
            self.phase = "connected"
            return
        if self.interface:
            self._detach()
            self.next_attempt = now + 15
        if not self.worker and now >= self.next_attempt:
            self.phase = "connecting"
            self.worker = True
            threading.Thread(
                target=self._connect,
                args=(self.generation, self.host, self.port),
                daemon=True,
            ).start()

    def close(self):
        self.enabled = False
        self.generation += 1
        self._detach()
        self.internet.prepare(False)
        for link, _ in self.probes.values():
            link.teardown()
        self.probes.clear()
