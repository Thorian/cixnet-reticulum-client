"""Local DNS authority choices and isolated NomadPL browser origins."""

import re
import secrets
import sqlite3
import threading
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

from nomadpl import Client
from nomadpl.gateway import Gateway
from nomadpl.urls import URL
from retdns import Cache, Resolver
from retdns.discovery import Discovery
from retdns.models import normalize_address, normalize_name

DEFAULT_DNS_SERVER = "48a1ab73497b08453287f12630883de6"


class SourceRecordingClient:
    """Retain bounded original HTML bytes while the gateway serves the page."""

    def __init__(self, client):
        """Keep a bounded source snapshot alongside the wrapped web client."""
        self.client = client
        self.sources = {}
        self.source_versions = {}
        self.bridge_markup = None
        self.closed = threading.Event()
        self.lock = threading.Lock()

    def close(self):
        """Revoke keep-alive requests as well as new gateway connections."""
        with self.lock:
            if self.closed.is_set():
                return
            self.closed.set()
        # The transport waits for its current request. Revoke access immediately
        # while releasing that link in the background so locking stays responsive.
        threading.Thread(target=self.client.close, daemon=True).start()

    def request(self, request):
        """Record the original HTML response before browser-only transformations."""
        if self.closed.is_set():
            raise ConnectionError("This browser bridge was closed")
        response = self.client.request(request)
        if self.closed.is_set():
            raise ConnectionError("This browser bridge was closed")
        content_type = next(
            (v for k, v in response.headers if k.lower() == "content-type"), ""
        )
        source_id = None
        if (
            request.method != "HEAD"
            and 200 <= response.status < 300
            and "html" in content_type.lower()
        ):
            with self.lock:
                self.sources.pop(request.target, None)
                self.sources[request.target] = (
                    response.body if len(response.body) <= 1024 * 1024 else None
                )
                source_id = secrets.token_hex(16)
                self.source_versions[source_id] = (
                    request.target,
                    self.sources[request.target],
                )
                while len(self.source_versions) > 8:
                    self.source_versions.pop(next(iter(self.source_versions)))
                while len(self.sources) > 8:
                    self.sources.pop(next(iter(self.sources)))
        if (
            self.bridge_markup
            and request.method != "HEAD"
            and 200 <= response.status < 300
            and "html" in content_type.lower()
        ):
            encoded = any(
                k.lower() == "content-encoding" and v.lower() != "identity"
                for k, v in response.headers
            )
            if not encoded:
                body = response.body
                closing = body.lower().find(b"</head>")
                if closing < 0:
                    closing = 0
                body = (
                    body[:closing]
                    + self.bridge_markup.replace(
                        b"__CIXNET_SOURCE__", (source_id or "").encode()
                    )
                    + body[closing:]
                )
                response = replace(
                    response,
                    body=body,
                    headers=[
                        (k, v)
                        for k, v in response.headers
                        if k.lower() != "content-length"
                    ],
                )
        return response

    def source(self, target, source_id=None):
        """Return saved source bytes without making another network request."""
        with self.lock:
            if source_id is not None:
                entry = self.source_versions.get(source_id)
                if entry is None or entry[0] != target:
                    raise ValueError(
                        "The saved source for this document is no longer available"
                    )
                body = entry[1]
                if body is None:
                    raise ValueError("Source view is limited to 1 MiB")
                return body.decode("utf-8", errors="replace")
            if target not in self.sources:
                raise ValueError(
                    "No saved source for this page. Open the page first; source view will not fetch it."
                )
            body = self.sources[target]
            if body is None:
                raise ValueError("Source view is limited to 1 MiB")
            return body.decode("utf-8", errors="replace")


class WebServices:
    def __init__(self, profiles, parent_origin=None, ui_root=None):
        """Restore DNS authority choices and initialize isolated browser gateways."""
        self.parent_origin = parent_origin
        from pathlib import Path

        self.ui_root = Path(ui_root) if ui_root else Path(__file__).parent / "ui"
        self.profiles = profiles
        self.lock = threading.RLock()
        self.external_hosts = {}
        self.db = sqlite3.connect(
            str(profiles.directory / "dns.sqlite"), check_same_thread=False
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS servers (
                owner TEXT, suffix TEXT, address TEXT,
                PRIMARY KEY(owner, suffix)
            )
            """
        )
        # DNS authorities are device settings, independent of chat identity.
        # Keep the old table intact as a migration backup; first migration wins.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS device_servers (suffix TEXT PRIMARY KEY, address TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS dns_migrations (version INTEGER PRIMARY KEY)"
        )
        if not self.db.execute(
            "SELECT 1 FROM dns_migrations WHERE version=1"
        ).fetchone():
            for suffix, address in self.db.execute(
                "SELECT suffix,address FROM servers ORDER BY rowid"
            ):
                self.db.execute(
                    """
                    INSERT INTO device_servers VALUES (?, ?)
                    ON CONFLICT(suffix) DO UPDATE SET address = excluded.address
                    """,
                    (suffix, address),
                )
            self.db.execute("INSERT INTO dns_migrations VALUES (1)")
        # Seed the official authority once. Keep custom mappings and later removals.
        if not self.db.execute(
            "SELECT 1 FROM dns_migrations WHERE version=2"
        ).fetchone():
            self.db.execute(
                "INSERT OR IGNORE INTO device_servers (suffix,address) VALUES (?,?)",
                ("cix", DEFAULT_DNS_SERVER),
            )
            self.db.execute("INSERT INTO dns_migrations VALUES (2)")
        self.db.commit()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS external_ports (owner TEXT, destination TEXT, identify INTEGER, host TEXT, port INTEGER, PRIMARY KEY(owner,destination,identify,host))"
        )
        self.db.commit()
        self.cache = Cache(profiles.directory / "dns-cache.sqlite")
        self.discovery = Discovery().start()
        self.gateways = {}

    def servers(self, owner):
        """Return configured authority suffixes and current discovery candidates."""
        self.profiles.get(owner)
        with self.lock:
            saved = [
                dict(suffix=s, address=a)
                for s, a in self.db.execute(
                    "SELECT suffix,address FROM device_servers ORDER BY suffix",
                )
            ]
        return {
            "saved": saved,
            "discovered": [
                dict(address=s.address, name=s.name) for s in self.discovery.services()
            ],
        }

    def save(self, owner, suffix, address, remove=False):
        """Persist or remove an explicitly chosen DNS suffix-to-authority mapping."""
        self.profiles.get(owner)
        if not isinstance(suffix, str) or not re.fullmatch(
            r"\.?[a-zA-Z][a-zA-Z0-9-]{0,31}", suffix
        ):
            raise ValueError("Use a suffix such as .cix")
        suffix = suffix.lower().lstrip(".")
        if type(remove) is not bool:
            raise ValueError("Remove must be true or false")
        with self.lock:
            if remove:
                self.db.execute("DELETE FROM device_servers WHERE suffix=?", (suffix,))
            else:
                address = normalize_address(address)
                if (
                    len(self.servers(owner)["saved"]) >= 32
                    and not self.db.execute(
                        "SELECT 1 FROM device_servers WHERE suffix=?",
                        (suffix,),
                    ).fetchone()
                ):
                    raise ValueError("At most 32 DNS suffixes per client")
                self.db.execute(
                    """
                    INSERT INTO device_servers VALUES (?, ?)
                    ON CONFLICT(suffix) DO UPDATE SET address = excluded.address
                    """,
                    (suffix, address),
                )
            self.db.commit()
        return self.servers(owner)

    def canonical(self, owner, value):
        """Resolve only explicitly pinned suffixes; discovery is never trust."""
        if re.fullmatch(r"[0-9a-fA-F]{32}:/.*", value):
            return value
        is_html = value.startswith("nomadpl://")
        parts = urlsplit(
            value if is_html else "nomadpl://" + value.replace(":/page/", "/page/", 1)
        )
        host = parts.netloc
        try:
            address = normalize_address(host)
        except ValueError:
            name, separator, suffix = host.lower().rstrip(".").rpartition(".")
            if not separator:
                raise ValueError(
                    "Use a name with a configured DNS suffix, such as home.cix"
                )
            authority = next(
                (s for s in self.servers(owner)["saved"] if s["suffix"] == suffix), None
            )
            if authority is None:
                raise ValueError("Add a DNS server for ." + suffix + " first")
            with Resolver(authority["address"], self.cache) as resolver:
                address = resolver.resolve(normalize_name(name))
        if is_html:
            return str(
                URL.parse(
                    urlunsplit(
                        (
                            "nomadpl",
                            address,
                            parts.path or "/",
                            parts.query,
                            parts.fragment,
                        )
                    )
                )
            )
        return address + ":" + (parts.path or "/page/index.mu")

    def close_identity(self, owner):
        """Revoke existing site gateways when the identity interface locks."""
        with self.lock:
            entries = [
                self.gateways.pop(key) for key in list(self.gateways) if key[0] == owner
            ]
        for gateway, _ in entries:
            gateway.client.close()
            gateway.shutdown()
            gateway.server_close()

    def external(self, owner, value, identify=False):
        """Expose a NomadPL site through a loopback-only, named browser origin."""
        self.profiles.get(owner)
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError("Enter a NomadPL address")
        if not value.startswith("nomadpl://"):
            raise ValueError("External browsing currently supports NomadPL HTML sites")
        parts = urlsplit(value)
        name = (parts.hostname or "").lower()
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,241}[a-z0-9])?", name)
            or any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                for label in name.split(".")
            )
            or parts.username
            or parts.password
            or parts.port
        ):
            raise ValueError("Invalid browser bridge hostname")
        canonical = self.canonical(owner, value)
        with self.lock:
            host = name + ".localhost"
            if identify:
                # A session capability isolates identified sites from other local apps.
                host = self.external_hosts.setdefault(
                    (owner, name), name + "." + secrets.token_hex(16) + ".localhost"
                )
            return {"url": self.gateway(owner, canonical, identify, external_host=host)}

    def gateway(self, owner, value, identify=False, *, external_host=None):
        """Create or reuse the selected identity's isolated destination gateway."""
        if type(identify) is not bool:
            raise ValueError("Identify must be true or false")
        url = URL.parse(value)
        key = (owner, url.destination, identify)
        if external_host:
            key += (external_host,)
        with self.lock:
            if key not in self.gateways:
                if len(self.gateways) >= 16:
                    raise ValueError(
                        "Maximum 16 open NomadPL sites; restart the client to release them"
                    )
                # Separate host per identity AND destination isolates cookies/storage.
                host = (
                    external_host
                    or url.destination
                    + "."
                    + owner
                    + "."
                    + secrets.token_hex(16)
                    + ".localhost"
                )
                import RNS

                identity = (
                    RNS.Identity.from_file(
                        str(self.profiles.directory / f"{owner}.identity")
                    )
                    if identify
                    else None
                )
                saved = (
                    self.db.execute(
                        "SELECT port FROM external_ports WHERE owner=? AND destination=? AND identify=? AND host=?",
                        (owner, url.destination, int(identify), host),
                    ).fetchone()
                    if external_host
                    else None
                )
                port = saved[0] if saved else 0
                client = SourceRecordingClient(
                    Client(url.destination, identity=identity)
                )
                try:
                    gateway = Gateway(("127.0.0.1", port), client, canonical_host=host)
                except OSError as error:
                    import errno

                    if (
                        not port
                        or error.errno != errno.EADDRINUSE
                        and getattr(error, "winerror", None) != 10048
                    ):
                        raise
                    gateway = Gateway(("127.0.0.1", 0), client, canonical_host=host)
                if external_host:
                    self.db.execute(
                        "INSERT OR REPLACE INTO external_ports VALUES (?,?,?,?,?)",
                        (
                            owner,
                            url.destination,
                            int(identify),
                            host,
                            gateway.server_address[1],
                        ),
                    )
                    self.db.commit()
                if self.parent_origin and not external_host:
                    from navigation_bridge import NavigationHandler

                    gateway.RequestHandlerClass = NavigationHandler
                    gateway.bridge_script = self.ui_root / "nomadpl-bridge.js"
                    gateway.bridge_path = (
                        "/.cixnet-navigation-" + secrets.token_hex(16) + ".js"
                    )
                    gateway.client.bridge_markup = (
                        f'<script src="{gateway.bridge_path}" data-parent="{self.parent_origin}" data-channel="{gateway.bridge_path}" data-source="__CIXNET_SOURCE__" defer></script>'
                    ).encode("ascii")
                threading.Thread(target=gateway.serve_forever, daemon=True).start()
                self.gateways[key] = (gateway, host)
            gateway, host = self.gateways[key]
            return f"http://{host}:{gateway.server_address[1]}{url.target}" + (
                "#" + url.fragment if url.fragment else ""
            )

    def source(self, owner, value, identify=False, source_id=None):
        """Read captured source only. This path never sends a network request."""
        self.profiles.get(owner)
        if type(identify) is not bool:
            raise ValueError("Identify must be true or false")
        url = URL.parse(value)
        with self.lock:
            entry = self.gateways.get((owner, url.destination, identify))
        if entry is None:
            raise ValueError("Open the page first; no saved source is available")
        gateway, _ = entry
        return gateway.client.source(url.target, source_id)
