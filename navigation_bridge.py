"""Serve a local navigation bridge without exposing the application's APIs."""

from pathlib import Path

from nomadpl import Response
from nomadpl.gateway import Handler


class NavigationHandler(Handler):
    def _handle(self):
        """Handle bridge assets separately before applying normal gateway checks."""
        if self.path == self.server.bridge_path:
            if not self._valid_host():
                return self._send(Response.text(421, "Invalid gateway host"))
            if self.command != "GET":
                return self._send(Response.text(405, "Method not supported"))
            body = getattr(
                self.server,
                "bridge_script",
                Path(__file__).parent / "ui" / "nomadpl-bridge.js",
            ).read_bytes()
            return self._send(
                Response(
                    200,
                    [
                        ("Content-Type", "text/javascript; charset=utf-8"),
                        ("Cache-Control", "no-store"),
                    ],
                    body,
                )
            )
        return super()._handle()
