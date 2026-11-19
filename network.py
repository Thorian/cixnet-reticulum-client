"""Reticulum lifecycle and live observations; no simulated connection state."""

import threading
import time
from pathlib import Path

import LXMF
import RNS

from interface_config import definitions, write_config


def readable_announce(data):
    """Never interpret binary metadata as lossy UTF-8 display text."""
    if not data:
        return ""
    try:
        text = data[:4096].decode("utf-8")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            raise ValueError("Binary controls")
        return text
    except (UnicodeError, ValueError):
        import json

        import RNS.vendor.umsgpack as msgpack

        try:
            decoded = msgpack.unpackb(data[:4096])
            if not isinstance(decoded, (dict, list, tuple)):
                raise ValueError("Unstructured binary data")
            return json.dumps(
                decoded,
                ensure_ascii=True,
                default=lambda value: (
                    value.hex() if isinstance(value, bytes) else str(value)
                ),
            )[:4096]
        except Exception:
            return f"Binary announce ({len(data)} bytes): " + data[:64].hex()


class Network:
    """Own an isolated Reticulum core and publish bounded observation snapshots."""

    def __init__(self, data, test_listen=None, test_connect=None):
        """Initialize managed interfaces and bounded network-discovery state."""
        self.data = Path(data)
        self._stations = None
        self.core = None
        self.phase = "not_started"
        self.error = None
        self.announces = {}
        self.lock = threading.RLock()
        self.local_enabled = False
        self.started = None
        self.snapshot = {"interfaces": [], "peers": 0, "rx": 0, "tx": 0}
        self.test_listen, self.test_connect = test_listen, test_connect
        self.managed = {}
        self.config_path = self.data / "network" / "config"

    @property
    def stations(self):
        """Open storage only when learning or browsing stations is requested."""
        from stations import Stations

        with self.lock:
            if self._stations is None:
                self._stations = Stations(self.data)
            return self._stations

    def start(self, local=True, interfaces=None):
        """
        Start networking while keeping startup failures visible to the application.
        """
        with self.lock:
            if self.phase in ("starting", "running"):
                return
            if self.phase == "error":
                raise ValueError(
                    "Restart the development client before retrying network startup"
                )
            self.phase = "starting"
            self.local_enabled = local
            self.managed = definitions(local, interfaces or [])
            self._start()

    def _start(self):
        # This private configuration never overwrites ~/.reticulum/config.
        """Create the Reticulum instance and attach its configured interfaces."""
        try:
            configdir = self.data / "network"
            configdir.mkdir(exist_ok=True)
            write_config(
                self.config_path, self.managed, self.test_listen, self.test_connect
            )
            self.core = RNS.Reticulum(configdir=str(configdir), loglevel=3)
            RNS.Transport.register_announce_handler(self)
            # Use upstream validation, including discovery stamps and encryption.
            # Learning never enables automatic connections or publishes location.
            from RNS.Discovery import InterfaceAnnounceHandler

            self.station_handler = InterfaceAnnounceHandler(
                callback=self.stations.learn
            )
            RNS.Transport.register_announce_handler(self.station_handler)
            with self.lock:
                self.phase = "running"
                self.started = time.time()
            threading.Thread(target=self._observe, daemon=True).start()
        except Exception as error:
            with self.lock:
                self.error = str(error)
                self.phase = "error"

    def apply_interfaces(self, local, interfaces):
        """Reconcile only our managed interfaces; preserve test links and routers.

        This executes on the main HTTP thread, using Reticulum's supported
        attach/detach API. Unreachable TCP peers reconnect in Reticulum itself.
        """
        wanted = definitions(local, interfaces)
        previous = self.managed
        removed = [name for name in previous if previous[name] != wanted.get(name)]
        added = [name for name in wanted if wanted[name] != previous.get(name)]
        write_config(self.config_path, wanted, self.test_listen, self.test_connect)
        detached, attached = [], []
        try:
            for name in removed:
                if not self.core.detach_interface(name):
                    raise ValueError(f"Could not disable interface {name}")
                detached.append(name)
            for name in added:
                if not self.core.attach_interface(name):
                    raise ValueError(f"Could not enable interface {name}")
                attached.append(name)
        except Exception:
            write_config(
                self.config_path, previous, self.test_listen, self.test_connect
            )
            for name in attached:
                self.core.detach_interface(name)
            for name in detached:
                self.core.attach_interface(name)
            raise
        self.managed = wanted
        self.local_enabled = local

    def _observe(self):
        """Read counters off the UI thread; observations never imply a server role."""
        try:
            while True:
                stats = self.core.get_interface_stats() or {}
                interfaces = []
                for item in stats.get("interfaces", []):
                    interfaces.append(
                        {
                            "name": str(item.get("name", "Interface")),
                            "type": str(item.get("type", "")),
                            "online": bool(item.get("status")),
                            # An online TCP client has exactly one remote endpoint.
                            "peers": (
                                int(bool(item.get("status")))
                                if item.get("type") == "TCPClientInterface"
                                else item.get("peers") or 0
                            ),
                            "rx": item.get("rxb", 0),
                            "tx": item.get("txb", 0),
                        }
                    )
                with self.lock:
                    self.snapshot = {
                        "interfaces": interfaces,
                        "peers": sum(i["peers"] for i in interfaces),
                        "rx": stats.get("rxb", 0),
                        "tx": stats.get("txb", 0),
                    }
                time.sleep(2)
        except Exception as error:
            with self.lock:
                self.error = str(error)
                self.phase = "error"

    aspect_filter = None
    receive_path_responses = False

    def received_announce(self, destination_hash, announced_identity, app_data):
        """Retain bounded public discovery data, not private identity key material."""
        with self.lock:
            address = destination_hash.hex()
            is_lxmf = (
                RNS.Destination.hash_from_name_and_identity(
                    "lxmf.delivery", announced_identity
                )
                == destination_hash
            )
            name = LXMF.display_name_from_app_data(app_data) if is_lxmf else None
            is_node = (
                RNS.Destination.hash_from_name_and_identity(
                    "nomadnetwork.node", announced_identity
                )
                == destination_hash
            )
            is_html = (
                RNS.Destination.hash_from_name_and_identity(
                    "nomadpl.node", announced_identity
                )
                == destination_hash
            )
            if is_node or is_html:
                name = (app_data or b"")[:256].decode("utf-8", errors="replace")
            is_dns = (
                RNS.Destination.hash_from_name_and_identity(
                    "retdns.server", announced_identity
                )
                == destination_hash
            )
            is_relay = (
                RNS.Destination.hash_from_name_and_identity(
                    "lxmf.propagation", announced_identity
                )
                == destination_hash
            )
            is_transport = (
                RNS.Destination.hash_from_name_and_identity(
                    "rnstransport.discovery.interface", announced_identity
                )
                == destination_hash
            )
            decoded = readable_announce(app_data)
            dns_info = None
            if is_dns:
                # Match the retdns discovery format before offering its add action.
                try:
                    import RNS.vendor.umsgpack as msgpack

                    if not isinstance(app_data, bytes) or len(app_data) > 256:
                        return
                    info = msgpack.unpackb(app_data)
                    name = info["name"]
                    if (
                        type(info["version"]) is not int
                        or info["version"] != 1
                        or not isinstance(name, str)
                        or not 1 <= len(name.encode("utf-8")) <= 128
                        or any(ord(char) < 32 for char in name)
                    ):
                        return
                    dns_info = {"version": info["version"], "name": name}
                except Exception:
                    return
            if is_relay:
                name = "LXMF relay"
            self.announces[address] = {
                "address": address,
                "identity": announced_identity.hash.hex(),
                "received": time.time(),
                "display_name": name,
                "kind": next(
                    (
                        kind
                        for matches, kind in (
                            (is_lxmf, "lxmf"),
                            (is_node, "node"),
                            (is_html, "nomadpl"),
                            (is_dns, "dns"),
                            (is_relay, "relay"),
                            (is_transport, "transport"),
                        )
                        if matches
                    ),
                    "unknown",
                ),
                "data": decoded,
                "dns": dns_info,
            }
            if len(self.announces) > 500:
                oldest = min(
                    self.announces, key=lambda key: self.announces[key]["received"]
                )
                del self.announces[oldest]

        callback = getattr(self, "on_destination", None)
        if callback:
            callback(address)

    def status(self):
        """Build the client-visible snapshot of connectivity, peers and announces."""
        with self.lock:
            return {
                "phase": self.phase,
                "error": self.error,
                "localEnabled": self.local_enabled,
                "started": self.started,
                "gateway": self.fallback.snapshot()
                if hasattr(self, "fallback")
                else None,
                **self.snapshot,
                "announces": sorted(
                    self.announces.values(), key=lambda a: a["received"], reverse=True
                ),
            }
