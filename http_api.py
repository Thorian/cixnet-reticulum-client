"""Loopback development API. HTTP concerns stay separate from domain services."""

import base64
import json
import logging
import secrets
import webbrowser
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote

from attachments import from_upload, image_type
from nomad_browser import NomadBrowser
from protection import IdentityProtection
from web_services import WebServices


@dataclass
class IdentityDownload:
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


class Application:
    """Explicit routing makes supported operations easy to audit and test."""

    def __init__(self, profiles, network, messaging, ui_root, port, no_local=False):
        """Connect the HTTP boundary to identity, messaging and browser services."""
        self.profiles = profiles
        self.network = network
        self.messaging = messaging
        self.ui_root = ui_root
        self.host = f"127.0.0.1:{port}"
        self.origin = f"http://{self.host}"
        self.token = secrets.token_urlsafe(32)
        self.no_local = no_local
        self.open_browser = webbrowser.open
        self.access_key = None
        self.protection = IdentityProtection(profiles.directory)
        self.web = WebServices(profiles, parent_origin=self.origin, ui_root=ui_root)
        self.browser = NomadBrowser(profiles, self.web)
        self.network.on_destination = self.messaging.outbox.path_available
        from fallback import FallbackGateway

        self.fallback = FallbackGateway(network)
        self.fallback.configure(profiles.read()["settings"])
        from pairing import Pairing

        self.pairing = Pairing(self)

    def get(self, path):
        """Return the requested read-only API view for the local client."""
        if path == "/api/pairing/status":
            return self.pairing.status()
        if getattr(self, "pairing", None) and self.pairing.remote is not None:
            return self.pairing.proxy(path)
        if path == "/api/state":
            state = self.profiles.read()
            counts = self.messaging.message_counts()
            return {
                **state,
                "profiles": [
                    {
                        **profile,
                        **self.protection.status(profile["id"]),
                        "message_count": counts.get(profile["id"], 0)
                        if not self.protection.status(profile["id"])["locked"]
                        else 0,
                    }
                    for profile in state["profiles"]
                ],
                "token": self.token,
                "core": "available",
                "transport": self.network.status()["phase"],
                "messaging": "available",
            }
        if path == "/api/network":
            return self.network.status()
        raise KeyError(path)

    def post(self, path, body):
        """Apply local UI operations, enforcing identity locks before private access."""
        if path.startswith("/api/pairing/"):
            if path == "/api/pairing/invite":
                if type(body.get("allowFirewall", False)) is not bool:
                    raise ValueError("Firewall choice must be true or false")
                result = self.pairing.invitation(body.get("host"), body.get("name"))
                if body.get("allowFirewall"):
                    from pairing_firewall import allow_listener

                    result["firewall"] = allow_listener(body["host"], result["port"])
                    (self.profiles.directory / "pairing-firewall-enabled").touch()
                return result
            if path == "/api/pairing/connect":
                return self.pairing.connect(
                    body.get("code"), body.get("owners"), body.get("name")
                )
            if path == "/api/pairing/revoke":
                return self.pairing.revoke(body.get("id"))
            if path == "/api/pairing/disconnect":
                self.pairing.disconnect()
                return {"ok": True}
            raise KeyError(path)
        if getattr(self, "pairing", None) and self.pairing.remote is not None:
            return self.pairing.proxy(path, body)
        if path.startswith("/api/identity/protection/"):
            profile = self.profiles.get(body.get("owner"))
            action = path.rsplit("/", 1)[1]
            if action == "status":
                return self.protection.status(profile["id"])
            if action == "result":
                return self.protection.result(profile["id"], body.get("job"))
            return self.protection.begin(profile, action)
        if path == "/api/identity/lock":
            profile = self.profiles.get(body.get("owner"))
            self.protection.close(profile["id"])
            self.web.close_identity(profile["id"])
            return {"ok": True}
        owner = body.get("owner")
        if isinstance(owner, str):
            self.protection.require_unlocked(owner)
        if path == "/api/stations/list":
            return self.network.stations.list(
                body.get("latitude"), body.get("longitude")
            )
        if path == "/api/stations/refresh":
            return self.network.stations.refresh()
        if path == "/api/stations/import":
            text = body.get("document")
            if not isinstance(text, str):
                raise ValueError("Choose a station JSON file")
            return self.network.stations.import_list(text.encode("utf-8"))
        if path == "/api/stations/from-download":
            # Native /file/ transfer uses existing bounded, owner-scoped jobs.
            name, data = self.browser.download(body.get("owner"), body.get("id"))
            return self.network.stations.import_list(data)
        if path in (
            "/api/identity/export",
            "/api/identity/update",
            "/api/identity/rename",
        ):
            self.protection.require_unlocked(body.get("id"))
        if path == "/api/messaging/sync":
            profile = self.profiles.get(body.get("owner"))
            self.messaging.activate(profile)
            return self.messaging.outbox.request_sync(profile["id"])
        if path == "/api/messaging/cancel":
            profile = self.profiles.get(body.get("owner"))
            return self.messaging.outbox.cancel(profile["id"], body.get("id"))
        if path == "/api/dns/list":
            return self.web.servers(body.get("owner"))
        if path == "/api/dns/save":
            return self.web.save(
                body.get("owner"),
                body.get("suffix"),
                body.get("address"),
                body.get("remove", False),
            )
        if path == "/api/browser/external":
            if type(body.get("launch", False)) is not bool:
                raise ValueError("Launch must be true or false")
            result = self.web.external(
                body.get("owner"), body.get("url"), body.get("identify", False)
            )
            result["launched"] = (
                bool(self.open_browser(result["url"])) if body.get("launch") else False
            )
            return result
        if path == "/api/browser/source":
            return {
                "source": self.web.source(
                    body.get("owner"),
                    body.get("url"),
                    body.get("identify", False),
                    body.get("source_id"),
                )
            }
        if path == "/api/browser/identify":
            return self.browser.page_identity(
                body.get("owner"),
                body.get("url"),
                body.get("identify"),
                body.get("base"),
            )
        if path == "/api/browser/open":
            return self.browser.open(
                body.get("owner"),
                body.get("url"),
                body.get("base"),
                body.get("data"),
                body.get("identify", False),
                body.get("source", False),
                body.get("max_bytes"),
            )
        if path == "/api/browser/status":
            return self.browser.status(body.get("owner"), body.get("id"))
        if path == "/api/browser/cancel":
            return self.browser.cancel(body.get("owner"), body.get("id"))
        if path == "/api/browser/download":
            name, data = self.browser.download(body.get("owner"), body.get("id"))
            return IdentityDownload(name, data)
        if path == "/api/browser/bookmarks":
            return {"bookmarks": self.browser.bookmarks(body.get("owner"))}
        if path == "/api/browser/bookmark":
            return {
                "bookmarks": self.browser.bookmark(
                    body.get("owner"),
                    body.get("url"),
                    body.get("name"),
                    body.get("remove", False),
                )
            }
        if path == "/api/identity/create":
            profile = self.profiles.create(body.get("nickname"))
            self.messaging.activate(profile)
            self.messaging.announce(profile["id"])
            return profile
        if path == "/api/identity/import":
            encoded = body.get("file")
            if not isinstance(encoded, str):
                raise ValueError("Choose a private identity file")
            private_bytes = base64.b64decode(encoded, validate=True)
            profile = self.profiles.create(body.get("nickname"), private_bytes)
            self.messaging.activate(profile)
            self.messaging.announce(profile["id"])
            return profile
        if path == "/api/identity/export":
            profile = self.profiles.get(body.get("id"))
            return IdentityDownload(
                f"cixnet-{profile['id']}.identity", self.profiles.export(profile["id"])
            )
        if path == "/api/identity/update":
            profile = self.profiles.update(body.get("id"), body)
            if profile["id"] in self.messaging.routers:
                self.messaging.activate(profile)
                self.messaging.announce(profile["id"])
            return profile
        if path == "/api/identity/rename":
            return self.profiles.rename(body.get("id"), body.get("nickname"))
        if path == "/api/settings":
            previous = self.profiles.read()["settings"]
            self.profiles.save_settings(body)
            try:
                self.network.apply_interfaces(
                    body["localDiscovery"] and not self.no_local,
                    body.get("interfaces", []),
                )
            except Exception:
                self.profiles.save_settings(previous)
                raise
            self.fallback.configure(self.profiles.read()["settings"])
            self.messaging.outbox.configure(self.profiles.read()["settings"])
            self.messaging.announce_minutes = self.profiles.read()["settings"][
                "announceMinutes"
            ]
            return {"ok": True}
        if path == "/api/identities/announce":
            for profile in self.profiles.read()["profiles"]:
                self.messaging.activate(profile)
                self.messaging.announce(profile["id"])
            return {"ok": True}
        if path == "/api/messaging/attachment":
            profile = self.profiles.get(body.get("owner"))
            name, data, image = self.messaging.attachment(
                profile["id"], body.get("message"), body.get("position")
            )
            kind = image_type(data) if image else None
            return IdentityDownload(
                name, data, kind[1] if kind else "application/octet-stream"
            )
        if path == "/api/network/start":
            self.network.start(
                self.profiles.read()["settings"]["localDiscovery"] and not self.no_local
            )
            return self.network.status()
        if path == "/api/messaging/block":
            profile = self.profiles.get(body.get("owner"))
            return self.messaging.set_blocked(
                profile["id"], body.get("peer"), body.get("blocked")
            )
        if path == "/api/messaging/search":
            profile = self.profiles.get(body.get("owner"))
            self.messaging.remember_peer_names(self.network.status()["announces"])
            return {"matches": self.messaging.search(profile["id"], body.get("query"))}
        messaging_routes = {
            "/api/messaging/activate",
            "/api/messaging/history",
            "/api/messaging/send",
        }
        if path in messaging_routes:
            profile = self.profiles.get(body.get("owner"))
            identity = self.messaging.activate(profile)
            if path.endswith("/activate"):
                if profile["id"] not in self.messaging.last_announced:
                    self.messaging.announce(profile["id"])
                return identity
            if path.endswith("/history"):
                self.messaging.remember_peer_names(self.network.status()["announces"])
                return {
                    "messages": self.messaging.history(
                        profile["id"], around=body.get("around")
                    ),
                    "blocked": self.messaging.blocked_contacts(profile["id"]),
                    "appearances": self.messaging.appearances(profile["id"]),
                    "propagation": {
                        "state": self.messaging.routers[profile["id"]][
                            0
                        ].propagation_transfer_state,
                        "progress": self.messaging.routers[profile["id"]][
                            0
                        ].propagation_transfer_progress,
                    },
                    "names": self.messaging.names(profile["id"]),
                }
            return self.messaging.send(
                profile["id"],
                body.get("peer"),
                body.get("content", ""),
                from_upload(body.get("attachments", [])),
            )
        raise KeyError(path)


class Handler(SimpleHTTPRequestHandler):
    @property
    def application(self):
        """Return the application instance attached to this HTTP server."""
        return self.server.application

    def __init__(self, *args, **kwargs):
        """Serve only files from the bundled UI directory."""
        server = args[2]
        super().__init__(*args, directory=str(server.application.ui_root), **kwargs)

    def setup(self):
        """Initialize the browser connection and its request timeout."""
        super().setup()
        # A stalled local request must not monopolize the single HTTP worker.
        self.connection.settimeout(10)

    def send_head(self):
        """Resolve a permitted UI asset before delegating file delivery."""
        if not self.valid_host():
            self.send_error(403, "Invalid host")
            return None
        root = Path(self.application.ui_root).resolve()
        target = Path(self.translate_path(self.path)).resolve()
        if not target.is_relative_to(root) or any(
            part.startswith(".") for part in target.relative_to(root).parts
        ):
            self.send_error(403, "File is outside the public UI")
            return None
        return super().send_head()

    def list_directory(self, path):
        """Refuse directory listings instead of exposing the server's files."""
        self.send_error(403, "Directory listing is disabled")
        return None

    def end_headers(self):
        """Attach the local client's security headers to every response."""
        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: blob:; connect-src 'self'; frame-src http://*.localhost:*; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            ),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def respond(self, result, status=200):
        """Write a JSON API response with explicit status and content length."""
        if isinstance(result, IdentityDownload):
            raw = result.data
            content_type = result.content_type
        else:
            raw = json.dumps(result).encode("utf-8")
            content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        if isinstance(result, IdentityDownload):
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(result.filename, safe='')}",
            )
        self.end_headers()
        self.wfile.write(raw)

    def valid_host(self):
        """Require the expected loopback host and port before handling a request."""
        return self.headers.get_all("Host", []) == [self.application.host]

    def api_authorized(self):
        """Android shares loopback with other apps; its private key stays in app storage."""
        expected = self.application.access_key
        if expected is None:
            return True
        values = self.headers.get_all("Authorization", [])
        return len(values) == 1 and secrets.compare_digest(
            values[0].encode(), ("Bearer " + expected).encode()
        )

    def do_GET(self):
        """Serve an authorized read request or a permitted static UI asset."""
        if not self.valid_host():
            return self.respond({"error": "Invalid host"}, 403)
        if self.path.startswith("/api/"):
            if not self.api_authorized():
                return self.respond({"error": "Private client access required"}, 403)
            try:
                return self.respond(self.application.get(self.path))
            except KeyError:
                return self.respond({"error": "Not found"}, 404)
            except (ValueError, TypeError) as error:
                return self.respond({"error": str(error)}, 400)
        super().do_GET()

    def do_POST(self):
        # Origin checks and a token prevent unrelated pages from changing local state.
        """Check origin and mutation token before dispatching an API operation."""
        origins = self.headers.get_all("Origin", [])
        allowed_origin = not origins or origins == [self.application.origin]
        token = self.headers.get("X-Cixnet-Token", "")
        if (
            not self.valid_host()
            or not self.api_authorized()
            or not allowed_origin
            or not secrets.compare_digest(
                token.encode("utf-8"), self.application.token.encode("utf-8")
            )
        ):
            return self.respond({"error": "Request rejected"}, 403)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get_all("Transfer-Encoding") or len(lengths) != 1:
                self.close_connection = True
                raise ValueError(
                    "Use one Content-Length header without Transfer-Encoding"
                )
            length = int(lengths[0])
            limit = (
                12 * 1024 * 1024
                if self.path == "/api/messaging/send"
                else 5 * 1024 * 1024
                if self.path == "/api/stations/import"
                else 65536
            )
            if not 1 <= length <= limit:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            self.respond(self.application.post(self.path, body))
        except KeyError:
            self.respond({"error": "Not found"}, 404)
        except (ValueError, TypeError) as error:
            self.respond({"error": str(error)}, 400)
        except OSError:
            logging.exception("Local file operation failed")
            self.respond({"error": "A local file operation failed"}, 500)

    def log_message(self, format, *args):
        # Routine polling should not bury meaningful transport errors in logs.
        """Keep access logging under the handler's configured logging policy."""
        if len(args) > 1 and str(args[1]) not in ("200", "304"):
            super().log_message(format, *args)
