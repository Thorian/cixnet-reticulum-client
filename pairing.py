"""Explicitly approved full-client access over authenticated Reticulum Links.

The HTTP API stays on loopback. Dedicated device keys identify paired devices;
message identity keys and Android bearer credentials never cross the Link.
Network callbacks enqueue application work for the receiver's main thread.
"""

import hashlib
import http.client
import ipaddress
import json
import queue
import secrets
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import RNS

MAX_BYTES = 16 * 1024 * 1024
CHUNK = 48 * 1024
READS = {
    "/api/stations/list",
    "/api/state",
    "/api/network",
    "/api/messaging/history",
    "/api/messaging/search",
    "/api/messaging/attachment",
    "/api/browser/bookmarks",
    "/api/browser/source",
    "/api/browser/status",
    "/api/browser/download",
    "/api/dns/list",
    "/api/identity/protection/status",
}
WRITES = {
    "/api/stations/import",
    "/api/stations/refresh",
    "/api/stations/from-download",
    "/api/messaging/activate",
    "/api/messaging/send",
    "/api/messaging/block",
    "/api/messaging/cancel",
    "/api/messaging/sync",
    "/api/browser/open",
    "/api/browser/identify",
    "/api/browser/cancel",
    "/api/browser/bookmark",
    "/api/browser/external",
    "/api/dns/save",
    "/api/settings",
    "/api/identity/update",
    "/api/identity/rename",
    "/api/identity/lock",
}


def encode(value):
    import RNS.vendor.umsgpack as msgpack

    return msgpack.packb(value)


def decode(value):
    import RNS.vendor.umsgpack as msgpack

    return msgpack.unpackb(value)


def local_addresses():
    """Offer explicit private IPv4 choices; never expose an all-address listener."""
    values = set()
    candidates = []
    try:
        from RNS.Interfaces import netinfo

        for interface in netinfo.interfaces():
            candidates.extend(
                item["addr"]
                for item in netinfo.ifaddresses(interface).get(netinfo.AF_INET, [])
            )
    except (OSError, ValueError, KeyError):
        pass
    try:
        candidates.extend(
            item[4][0]
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
    except OSError:
        pass
    for value in candidates:
        address = ipaddress.ip_address(value)
        if address.is_private and not address.is_loopback and not address.is_link_local:
            values.add(str(address))
    return sorted(values)


def validate_invite(text):
    """Validate before making any connection to a scanned LAN address."""
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError("Invalid pairing code")
    value = json.loads(text)
    if not isinstance(value, dict) or value.get("cixnet") != 1:
        raise ValueError("This is not a ciXnet pairing code")
    host = ipaddress.ip_address(value["host"])
    if (
        host.version != 4
        or not host.is_private
        or host.is_loopback
        or host.is_link_local
    ):
        raise ValueError("Pairing requires a private LAN IPv4 address")
    if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise ValueError("Invalid pairing port")
    if not time.time() < value["expires"] <= time.time() + 310:
        raise ValueError("Pairing code expired; generate a new code")
    if len(bytes.fromhex(value["secret"])) != 32:
        raise ValueError("Invalid invitation secret")
    identity = RNS.Identity(create_keys=False)
    identity.load_public_key(bytes.fromhex(value["public"]))
    expected = RNS.Destination(
        identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "cixnet", "pairing"
    )
    if expected.hash.hex() != value["destination"]:
        raise ValueError("Pairing identity does not match the invitation")
    return value


def load_pairing_identity(directory):
    """Create a device key once; never replace a damaged saved identity silently."""
    path = directory / "pairing.identity"
    if path.exists():
        identity = RNS.Identity.from_file(str(path))
        if identity is None:
            raise ValueError("Could not read the saved pairing identity")
        return identity
    identity = RNS.Identity()
    if not identity.to_file(str(path)):
        raise OSError("Could not save the pairing identity")
    path.chmod(0o600)
    return identity


class Pairing:
    def __init__(self, application):
        self.app = application
        self.directory = application.profiles.directory
        self.lock = threading.RLock()
        self.rpc_lock = threading.Lock()
        self.work = queue.Queue(maxsize=8)
        self.identity = load_pairing_identity(self.directory)
        self.db = sqlite3.connect(
            str(self.directory / "pairing.sqlite"), check_same_thread=False
        )
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS devices (hash TEXT PRIMARY KEY, public TEXT, name TEXT, owners TEXT, role TEXT, endpoint TEXT);
          CREATE TABLE IF NOT EXISTS requests (device TEXT, id TEXT, digest TEXT, created REAL, result BLOB, PRIMARY KEY(device,id));
        """)
        self.db.commit()
        self.destination = RNS.Destination(
            self.identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "cixnet",
            "pairing",
        )
        self._handlers(self.destination)
        self.destination.set_link_established_callback(self._incoming)
        self.links = {}
        self.link = None
        self.remote = None
        self.invite = None
        self.listener = None
        self.connector = None
        self.busy = False
        self.error = ""
        self.uploads = {}
        self.downloads = {}
        self.gateways = {}
        self.reconnect_at = 0
        self.paused = False
        saved = self.db.execute(
            "SELECT endpoint FROM devices WHERE role='phone' LIMIT 1"
        ).fetchone()
        if saved:
            try:
                endpoint = json.loads(saved[0])
                if endpoint.get("host") in local_addresses():
                    self._listen(endpoint["host"], endpoint["port"])
                    if (self.directory / "pairing-firewall-enabled").exists():
                        from pairing_firewall import allow_listener

                        self.error = allow_listener(endpoint["host"], endpoint["port"])
            except (OSError, ValueError, KeyError) as error:
                self.error = f"Pairing listener needs a new code: {error}"

    def _handlers(self, destination):
        for path in ("/hello", "/rpc"):
            destination.register_request_handler(
                path, response_generator=self._receive, allow=RNS.Destination.ALLOW_ALL
            )

    def _incoming(self, link):
        with self.lock:
            if len(self.links) >= 8:
                link.teardown()
                return
            self.links[link.link_id] = link
        link.set_link_closed_callback(lambda item: self.links.pop(item.link_id, None))

    def _device(self, identity):
        if identity is None:
            return None
        return self.db.execute(
            "SELECT hash,public,name,owners,role,endpoint FROM devices WHERE hash=?",
            (identity.hash.hex(),),
        ).fetchone()

    def status(self):
        with self.lock:
            devices = [
                {
                    "id": row[0],
                    "name": row[1],
                    "role": row[2],
                    "owners": json.loads(row[3]),
                }
                for row in self.db.execute("SELECT hash,name,role,owners FROM devices")
            ]
            active = self.remote and self.link and self.link.status == RNS.Link.ACTIVE
            serving = any(
                link.status == RNS.Link.ACTIVE
                and self._device(link.get_remote_identity())
                for link in self.links.values()
            )
            return {
                "serving": bool(serving),
                "devices": devices,
                "remote": self.remote,
                "busy": self.busy,
                "error": self.error,
                "addresses": local_addresses(),
                "connected": bool(active),
                "listening": bool(self.listener),
            }

    def invitation(self, host, name):
        if host not in local_addresses():
            raise ValueError("Choose one of this computer's LAN addresses")
        with self.lock:
            self.disconnect()
            self.paused = False
            if self.listener:
                self.listener.detach()
            self._listen(host, 0)
            self.invite = {
                "cixnet": 1,
                "host": host,
                "port": self.listener.server.server_address[1],
                "public": self.identity.get_public_key().hex(),
                "destination": self.destination.hash.hex(),
                "secret": secrets.token_hex(32),
                "expires": int(time.time()) + 300,
                "name": str(name or "ciXnet desktop")[:64],
            }
            self.destination.announce()
            return {
                "code": json.dumps(self.invite, separators=(",", ":")),
                "expires": self.invite["expires"],
                "port": self.invite["port"],
            }

    def _listen(self, host, port):
        from RNS.Interfaces.TCPInterface import TCPServerInterface

        self.listener = TCPServerInterface(
            RNS.Transport,
            {"name": "ciXnet phone pairing", "listen_ip": host, "listen_port": port},
        )
        self.app.network.core._add_interface(self.listener)

    def connect(self, text, owners, name):
        invite = validate_invite(text)
        if not isinstance(owners, list) or not owners or len(owners) > 32:
            raise ValueError("Select at least one phone identity to share")
        for owner in owners:
            self.app.profiles.get(owner)
            self.app.protection.require_unlocked(owner)
        with self.lock:
            if self.busy:
                raise ValueError("A connection is already in progress")
            self.busy = True
            self.error = ""
        threading.Thread(
            target=self._connect,
            args=(invite, owners, str(name or "ciXnet phone")[:64], False),
            daemon=True,
        ).start()
        return {"ok": True}

    @staticmethod
    def request(link, path, data):
        done = threading.Event()
        result = []

        def received(receipt):
            result.append(receipt.response)
            done.set()

        receipt = link.request(
            path,
            data=data,
            response_callback=received,
            failed_callback=lambda _: done.set(),
            timeout=45,
            max_response_size=CHUNK + 4096,
        )
        if not receipt or not done.wait(50) or not result:
            raise ValueError(
                "Phone connection interrupted; check message history before sending again"
            )
        response = result[0]
        if not isinstance(response, dict):
            raise ValueError("Invalid paired-device response")
        if response.get("error"):
            raise ValueError(response["error"])
        return response

    def _connect(self, invite, owners, name, resume):
        link = None
        try:
            from RNS.Interfaces.TCPInterface import TCPClientInterface

            if self.connector:
                self.connector.detach()
            self.connector = TCPClientInterface(
                RNS.Transport,
                {
                    "name": "ciXnet paired desktop",
                    "target_host": invite["host"],
                    "target_port": invite["port"],
                    "connect_timeout": 5,
                    "max_reconnect_tries": 3,
                },
            )
            self.app.network.core._add_interface(self.connector)
            public = RNS.Identity(create_keys=False)
            public.load_public_key(bytes.fromhex(invite["public"]))
            dest = RNS.Destination(
                public, RNS.Destination.OUT, RNS.Destination.SINGLE, "cixnet", "pairing"
            )
            self._handlers(dest)
            RNS.Transport.request_path(dest.hash)
            limit = time.monotonic() + 15
            while not RNS.Transport.has_path(dest.hash) and time.monotonic() < limit:
                time.sleep(0.1)
            link = RNS.Link(dest)
            while link.status != RNS.Link.ACTIVE and time.monotonic() < limit:
                time.sleep(0.1)
            if link.status != RNS.Link.ACTIVE:
                raise ValueError(
                    "Could not reach desktop. Check Wi-Fi and allow the pairing TCP port through its LAN firewall."
                )
            link.identify(self.identity)
            with self.lock:
                # The scan-and-approve action is the phone's authorization.
                self.db.execute(
                    "INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,?)",
                    (
                        public.hash.hex(),
                        invite["public"],
                        invite.get("name", "Desktop"),
                        json.dumps(owners),
                        "desktop",
                        json.dumps(
                            {
                                k: v
                                for k, v in invite.items()
                                if k not in ("secret", "expires")
                            }
                        ),
                    ),
                )
                self.db.commit()
                self.links[link.link_id] = link
            link.set_link_closed_callback(
                lambda item: self.links.pop(item.link_id, None)
            )
            self.request(
                link,
                "/hello",
                {
                    "secret": None if resume else invite["secret"],
                    "name": name,
                    "resume": resume,
                },
            )
        except Exception as error:
            if link:
                link.teardown()
            self.error = str(error)[:240]
            if not resume and "public" in invite:
                with self.lock:
                    self.db.execute(
                        "DELETE FROM devices WHERE public=? AND role='desktop'",
                        (invite["public"],),
                    )
                    self.db.commit()
        finally:
            self.busy = False
            self.reconnect_at = time.monotonic() + 20

    def _receive(self, path, data, request_id, link_id, remote_identity, requested_at):
        """Unauthenticated callers never enter the application dispatch queue."""
        try:
            if (
                remote_identity is None
                or not isinstance(data, dict)
                or len(encode(data)) > CHUNK + 4096
            ):
                raise ValueError("Pairing authentication required")
            with self.lock:
                device = self._device(remote_identity)
                if path == "/hello":
                    valid = (
                        self.invite
                        and time.time() < self.invite["expires"]
                        and isinstance(data.get("secret"), str)
                        and secrets.compare_digest(
                            data["secret"], self.invite["secret"]
                        )
                    )
                    if not valid and not (
                        not self.paused
                        and data.get("resume") is True
                        and device
                        and device[4] == "phone"
                    ):
                        raise ValueError("Invitation expired, already used, or revoked")
                    if (
                        self.remote
                        and self.remote["id"] != remote_identity.hash.hex()
                        and self.link
                        and self.link.status == RNS.Link.ACTIVE
                        and not valid
                    ):
                        raise ValueError("Desktop is currently using another phone")
                    link = self.links.get(link_id)
                    if not link or link.status != RNS.Link.ACTIVE:
                        raise ValueError("Pairing link unavailable")
                    if valid:
                        endpoint = {k: self.invite[k] for k in ("host", "port")}
                        self.invite = None
                        self.db.execute(
                            "INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,?)",
                            (
                                remote_identity.hash.hex(),
                                remote_identity.get_public_key().hex(),
                                str(data.get("name", "Phone"))[:64],
                                "[]",
                                "phone",
                                json.dumps(endpoint),
                            ),
                        )
                        self.db.commit()
                    self.link = link
                    self.remote = {
                        "id": remote_identity.hash.hex(),
                        "name": str(data.get("name", "Phone"))[:64],
                    }
                    return {"ok": True}
                if not device or device[4] != "desktop":
                    raise ValueError("This device is not authorized")
                device_hash = remote_identity.hash.hex()
                self._expire_buffers()
                operation = data.get("op")
                if operation == "upload":
                    key = (device_hash, data.get("id"))
                    part = data.get("data")
                    if (
                        not isinstance(key[1], str)
                        or len(key[1]) != 32
                        or not isinstance(part, bytes)
                        or len(part) > CHUNK
                    ):
                        raise ValueError("Invalid transfer chunk")
                    if key not in self.uploads:
                        if len(self.uploads) >= 4:
                            raise ValueError("Too many pending transfers")
                        self.uploads[key] = [time.monotonic(), bytearray()]
                    target = self.uploads[key][1]
                    if (
                        data.get("offset") != len(target)
                        or len(target) + len(part) > MAX_BYTES
                    ):
                        raise ValueError("Invalid transfer offset or size")
                    target.extend(part)
                    return {"ok": True}
                if operation == "chunk":
                    entry = self.downloads.get((device_hash, data.get("id")))
                    offset = data.get("offset")
                    if (
                        not entry
                        or type(offset) is not int
                        or not 0 <= offset < len(entry[1])
                    ):
                        raise ValueError("Transfer expired")
                    if entry[2]:
                        self.app.protection.require_unlocked(entry[2])
                    return {"data": entry[1][offset : offset + CHUNK]}
                if operation != "call":
                    raise ValueError("Unknown pairing operation")
                payload = data.get("payload")
                if data.get("upload"):
                    entry = self.uploads.pop((device_hash, data["upload"]), None)
                    if not entry:
                        raise ValueError("Transfer expired")
                    payload = bytes(entry[1])
                if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
                    raise ValueError("Invalid request")
            event = threading.Event()
            output = []
            self.work.put_nowait((device_hash, payload, event, output))
            if not event.wait(40):
                raise ValueError("Phone is busy; check history before retrying")
            packed = output[0]
            if len(packed) <= CHUNK:
                return {"data": packed}
            with self.lock:
                if len(self.downloads) >= 4:
                    raise ValueError("Too many pending downloads")
                key = secrets.token_hex(16)
                request_body = decode(payload).get("body") or {}
                owner = request_body.get("owner", request_body.get("id"))
                self.downloads[(device_hash, key)] = (time.monotonic(), packed, owner)
            return {"download": key, "size": len(packed)}
        except Exception as error:
            return {"error": str(error)[:240]}

    def _expire_buffers(self):
        now = time.monotonic()
        for buffers in (self.uploads, self.downloads):
            for key in list(buffers):
                if now - buffers[key][0] > 120:
                    buffers.pop(key, None)

    def tick(self):
        """Execute remote API operations on the same main thread as local HTTP."""
        if self.invite and time.time() > self.invite["expires"]:
            self.invite = None
            if (
                self.listener
                and not self.db.execute(
                    "SELECT 1 FROM devices WHERE role='phone'"
                ).fetchone()
            ):
                self.listener.detach()
                self.listener = None
        for _ in range(2):
            try:
                device, payload, event, output = self.work.get_nowait()
            except queue.Empty:
                break
            try:
                result = self._dispatch(device, decode(payload))
            except Exception as error:
                result = {"error": str(error)[:240]}
            packed = encode(result)
            if len(packed) > MAX_BYTES:
                packed = encode({"error": "Paired response exceeds 16 MiB"})
            output.append(packed)
            event.set()
        if not self.busy and time.monotonic() >= self.reconnect_at:
            with self.lock:
                rows = self.db.execute(
                    "SELECT endpoint,owners FROM devices WHERE role='desktop'"
                ).fetchall()
                connected = any(
                    link.status == RNS.Link.ACTIVE for link in self.links.values()
                )
            if rows and not connected:
                self.busy = True
                invite, owners = rows[0]
                threading.Thread(
                    target=self._connect,
                    args=(json.loads(invite), json.loads(owners), "ciXnet phone", True),
                    daemon=True,
                ).start()

    def _dispatch(self, device_hash, request):
        with self.lock:
            device = self.db.execute(
                "SELECT owners FROM devices WHERE hash=? AND role='desktop'",
                (device_hash,),
            ).fetchone()
        if not device or not isinstance(request, dict):
            raise ValueError("Paired access revoked")
        owners = json.loads(device[0])
        path, body = request.get("path"), request.get("body")
        if path not in READS | WRITES | {"/paired/asset"}:
            raise ValueError("This operation requires using the phone directly")
        if path in ("/api/state", "/api/network"):
            result = self.app.get(path)
            if path == "/api/state":
                result = {
                    **result,
                    "profiles": [p for p in result["profiles"] if p["id"] in owners],
                }
                result.pop("token", None)
            return {"result": result}
        if not isinstance(body, dict):
            raise ValueError("Invalid paired request body")
        if path != "/api/settings":
            owner = body.get("owner", body.get("id"))
            if owner not in owners:
                raise ValueError("This identity was not shared with the desktop")
            if path not in ("/api/identity/protection/status", "/api/identity/lock"):
                self.app.protection.require_unlocked(owner)
        if path == "/paired/asset":
            return {"asset": self._asset(body)}
        mutation = path in WRITES
        request_id = request.get("id")
        digest = hashlib.sha256(encode([path, body])).hexdigest()
        if mutation:
            if (
                not isinstance(request_id, str)
                or len(request_id) != 32
                or abs(time.time() - request.get("created", 0)) > 86400
            ):
                raise ValueError("Invalid or expired paired operation")
            with self.lock:
                row = self.db.execute(
                    "SELECT digest,result FROM requests WHERE device=? AND id=?",
                    (device_hash, request_id),
                ).fetchone()
                if row:
                    if row[0] != digest:
                        raise ValueError(
                            "Operation identifier reused with different content"
                        )
                    if row[1] is None:
                        raise ValueError(
                            "Earlier operation was interrupted; check history before repeating it"
                        )
                    return decode(row[1])
                self.db.execute(
                    "DELETE FROM requests WHERE created<?", (time.time() - 172800,)
                )
                if (
                    self.db.execute("SELECT count(*) FROM requests").fetchone()[0]
                    >= 10000
                ):
                    raise ValueError("Paired operation journal is full")
                self.db.execute(
                    "INSERT INTO requests VALUES (?,?,?,?,NULL)",
                    (device_hash, request_id, digest, time.time()),
                )
                self.db.commit()
        try:
            if path == "/api/browser/external":
                body = {**body, "launch": False}
            result = self.app.post(path, body)
            from http_api import IdentityDownload

            if isinstance(result, IdentityDownload):
                response = {
                    "download": [result.filename, result.data, result.content_type]
                }
            else:
                response = {"result": result}
        except Exception as error:
            response = {"error": str(error)[:240]}
        if mutation:
            with self.lock:
                self.db.execute(
                    "UPDATE requests SET result=? WHERE device=? AND id=?",
                    (encode(response), device_hash, request_id),
                )
                self.db.commit()
        return response

    def _asset(self, body):
        """Read only a gateway that this phone already owns, never arbitrary URLs."""
        origin = body.get("origin")
        found = None
        with self.app.web.lock:
            for key, (gateway, host) in self.app.web.gateways.items():
                if (
                    key[0] == body["owner"]
                    and origin == f"http://{host}:{gateway.server_address[1]}"
                ):
                    found = (gateway, host)
                    break
        if not found:
            raise ValueError("Phone browser session expired")
        target = body.get("target", "/")
        if (
            not isinstance(target, str)
            or not target.startswith("/")
            or target.startswith("//")
            or any(ord(c) < 32 for c in target)
        ):
            raise ValueError("Invalid page target")
        method = body.get("method")
        if method not in ("GET", "POST", "HEAD"):
            raise ValueError("Unsupported browser method")
        gateway, host = found
        headers = {
            k: v
            for k, v in body.get("headers", {}).items()
            if k.lower() in ("content-type", "cookie", "accept", "range")
        }
        headers["Host"] = f"{host}:{gateway.server_address[1]}"
        connection = http.client.HTTPConnection(
            "127.0.0.1", gateway.server_address[1], timeout=30
        )
        try:
            connection.request(method, target, body=body.get("data"), headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Page resource exceeds paired transfer limit")
            return {
                "status": response.status,
                "headers": response.getheaders(),
                "data": raw,
                "parent": self.app.origin,
            }
        finally:
            connection.close()

    def call(self, path, body=None):
        """Serialize requests; chunk attachments with bounded transient storage."""
        with self.rpc_lock:
            link = self.link
            if not link or link.status != RNS.Link.ACTIVE:
                raise ValueError("Paired phone is disconnected")
            packed = encode(
                {
                    "path": path,
                    "body": body,
                    "id": secrets.token_hex(16),
                    "created": time.time(),
                }
            )
            if len(packed) > MAX_BYTES:
                raise ValueError("Paired request exceeds 16 MiB")
            envelope = {"op": "call", "payload": packed}
            if len(packed) > CHUNK:
                transfer = secrets.token_hex(16)
                for offset in range(0, len(packed), CHUNK):
                    self.request(
                        link,
                        "/rpc",
                        {
                            "op": "upload",
                            "id": transfer,
                            "offset": offset,
                            "data": packed[offset : offset + CHUNK],
                        },
                    )
                envelope = {"op": "call", "upload": transfer}
            response = self.request(link, "/rpc", envelope)
            if "download" in response:
                size = response.get("size")
                if type(size) is not int or not 0 < size <= MAX_BYTES:
                    raise ValueError("Invalid transfer size")
                result = bytearray()
                while len(result) < size:
                    part = self.request(
                        link,
                        "/rpc",
                        {
                            "op": "chunk",
                            "id": response["download"],
                            "offset": len(result),
                        },
                    )["data"]
                    if (
                        not isinstance(part, bytes)
                        or not part
                        or len(part) > CHUNK
                        or len(result) + len(part) > size
                    ):
                        raise ValueError("Invalid response chunk")
                    result.extend(part)
                response = {"data": bytes(result)}
            answer = decode(response["data"])
            if answer.get("error"):
                raise ValueError(answer["error"])
            return answer

    def proxy(self, path, body=None):
        answer = self.call(path, body)
        if "download" in answer:
            from http_api import IdentityDownload

            return IdentityDownload(*answer["download"])
        result = answer["result"]
        if path == "/api/state":
            result["token"] = self.app.token
            result["paired_phone"] = self.remote
        if path in ("/api/browser/status", "/api/browser/external"):
            field = "frame" if path.endswith("status") else "url"
            if result.get(field):
                result[field] = self._bridge(body["owner"], result[field])
                if field == "url" and body.get("launch"):
                    result["launched"] = bool(self.app.open_browser(result[field]))
        return result

    def _bridge(self, owner, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or not parsed.hostname.endswith(".localhost")
            or not parsed.port
        ):
            raise ValueError("Invalid phone page origin")
        origin = f"http://{parsed.netloc}"
        key = (owner, origin)
        if key not in self.gateways:
            if len(self.gateways) >= 16:
                raise ValueError("Close paired session to release browser pages")
            server = ThreadingHTTPServer(("127.0.0.1", 0), PairedPage)
            server.daemon_threads = True
            server.pairing, server.owner, server.remote_origin, server.host = (
                self,
                owner,
                origin,
                parsed.hostname,
            )
            self.gateways[key] = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
        server = self.gateways[key]
        return f"http://{parsed.hostname}:{server.server_address[1]}{parsed.path}" + (
            "?" + parsed.query if parsed.query else ""
        )

    def disconnect(self):
        with self.lock:
            if self.link:
                self.link.teardown()
            self.link = None
            self.remote = None
            self.paused = True
            for gateway in self.gateways.values():
                gateway.shutdown()
                gateway.server_close()
            self.gateways.clear()

    def revoke(self, device):
        with self.lock:
            self.db.execute("DELETE FROM devices WHERE hash=?", (device,))
            self.db.execute("DELETE FROM requests WHERE device=?", (device,))
            self.db.commit()
            for link in list(self.links.values()):
                identity = link.get_remote_identity()
                if identity and identity.hash.hex() == device:
                    link.teardown()
                    self.links.pop(link.link_id, None)
            if self.remote and self.remote["id"] == device:
                self.disconnect()
        return {"ok": True}


class PairedPage(BaseHTTPRequestHandler):
    """Isolated loopback page origin; all traffic still goes through the phone."""

    def do_GET(self):
        self.forward()

    def do_HEAD(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        server = self.server
        expected = f"{server.host}:{server.server_address[1]}"
        if self.headers.get_all("Host", []) != [expected]:
            self.send_error(403)
            return
        self.connection.settimeout(40)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
                raise ValueError("Invalid framing")
            length = int(lengths[0]) if lengths else 0
            if not 0 <= length <= 1024 * 1024:
                raise ValueError("Browser request too large")
            origin = self.headers.get("Origin")
            if self.command == "POST" and origin != "http://" + expected:
                raise ValueError("Page origin rejected")
            data = self.rfile.read(length) if length else None
            answer = server.pairing.call(
                "/paired/asset",
                {
                    "owner": server.owner,
                    "origin": server.remote_origin,
                    "target": self.path,
                    "method": self.command,
                    "headers": dict(self.headers),
                    "data": data,
                },
            )["asset"]
            raw = answer["data"]
            headers = answer["headers"]
            content_type = next(
                (v for k, v in headers if k.lower() == "content-type"), ""
            )
            local = "http://" + expected
            if "html" in content_type:
                raw = raw.replace(
                    answer["parent"].encode(), server.pairing.app.origin.encode()
                ).replace(server.remote_origin.encode(), local.encode())
            self.send_response(answer["status"])
            for key, value in headers:
                if key.lower() not in (
                    "content-length",
                    "connection",
                    "transfer-encoding",
                ):
                    self.send_header(key, value.replace(server.remote_origin, local))
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
        except Exception:
            self.send_error(502, "Phone page unavailable")

    def log_message(self, *args):
        pass
