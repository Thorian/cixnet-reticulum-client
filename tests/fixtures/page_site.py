"""NomadNet static Micron pages; never executes page files."""

from pathlib import Path


class PageSite:
    def __init__(self, identity, name: str, root: Path):
        """Register the site's static Micron pages under its persistent identity."""
        import RNS

        self.name = name
        self.root = root.resolve(strict=True)
        self.destination = RNS.Destination(
            identity, RNS.Destination.IN, RNS.Destination.SINGLE, "nomadnetwork", "node"
        )
        for page in self.root.rglob("*.mu"):
            relative = page.relative_to(self.root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            self.destination.register_request_handler(
                "/page/" + relative.as_posix(),
                response_generator=self.serve,
                allow=RNS.Destination.ALLOW_ALL,
            )

    def serve(self, path, data, request_id, link_id, remote_identity, requested_at):
        """Read a public Micron page only after validating its resolved path."""
        if not path.startswith("/page/"):
            return None
        page = (self.root / path[len("/page/") :]).resolve()
        if not page.is_relative_to(self.root) or page.suffix != ".mu":
            return None
        if any(part.startswith(".") for part in page.relative_to(self.root).parts):
            return None
        # Private-page sidecars are not supported: refuse rather than expose them.
        if Path(str(page) + ".allowed").exists():
            return None
        try:
            return page.read_bytes()
        except OSError:
            return None

    def announce(self):
        """Advertise this site's name on its NomadNet destination."""
        self.destination.announce(app_data=self.name.encode("utf-8"))
