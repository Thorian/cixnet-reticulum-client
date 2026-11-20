"""Independent native node using the included PageSite test fixture.

Used only by integration tests; it listens on loopback and owns temporary keys.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    os.environ.get("RETICULUM_SOURCE", ""),
    os.environ.get("LXMF_SOURCE", ""),
    os.environ.get("NOMADPL_SOURCE", ""),
    os.environ.get("RETDNS_SOURCE", ""),
    str(ROOT / "tests" / "fixtures"),
]
import RNS
from nomadpl.transport import load_identity
from page_site import PageSite


def main():
    """Host temporary Micron and HTML destinations for browser integration tests."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--announce-interval", type=int, default=900)
    parser.add_argument("--with-relay", action="store_true")
    args = parser.parse_args()
    if args.announce_interval < 1:
        parser.error("Announce interval must be positive")
    args.data.mkdir(parents=True, exist_ok=True)
    (args.data / "config").write_text(
        f"[reticulum]\nshare_instance = No\nenable_transport = Yes\n[logging]\nloglevel = 2\n[interfaces]\n[[Test node]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = {args.port}\n"
    )
    RNS.Transport.DESTINATION_VALUE = 8
    RNS.Transport.DESTINATION_COST = 8
    RNS.Transport.PR_VALUE = 8
    RNS.Transport.PR_COST = 8
    RNS.Reticulum(configdir=str(args.data))
    relay = None
    if args.with_relay:
        import LXMF

        relay = LXMF.LXMRouter(
            identity=load_identity(args.data / "relay.identity"),
            storagepath=str(args.data / "relay"),
            autopeer=False,
            propagation_cost=13,
        )
        relay.enable_propagation()
    sites = []
    for name in ("main", "community"):
        sites.append(
            PageSite(
                load_identity(args.data / (name + ".identity")),
                name.title(),
                ROOT / "tests" / "fixtures" / "pages" / name,
            )
        )
    pages = args.data / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "index.mu").write_text(
        ">Micron compatibility\n"
        "Native Reticulum page request.\n"
        "`!Bold`! `_underline`_ `*italic`*\n"
        "`F70eColored`f text.\n"
        "`[Next page`next.mu]\n"
        f"`[Main site`{sites[0].destination.hash.hex()}:/page/index.mu]\n"
        f"`[Community site`{sites[1].destination.hash.hex()}:/page/index.mu]\n"
        "Name: `<24|name`visitor>\n"
        "`[Submit form`/page/result.mu`*|mode=test]\n"
        "`t\n| Item | State |\n| --- | --- |\n| Browser | Native |\n`t\n"
        "Literal HTML: <script>alert('not executable')</script>\n",
        encoding="utf-8",
    )
    (pages / "next.mu").write_text(
        ">Next page\nRelative navigation works.\n`[Home`index.mu]\n", encoding="utf-8"
    )
    rich = PageSite(
        load_identity(args.data / "rich.identity"), "Micron compatibility", pages
    )

    def result(path, data, request_id, link_id, remote_identity, requested_at):
        """Return a predictable native response for the fixture's request handler."""
        data = data or {}
        return f">Form result\nName: {data.get('field_name', '')}\nMode: {data.get('var_mode', '')}\nIdentified: {remote_identity is not None}\n".encode()

    rich.destination.register_request_handler(
        "/page/result.mu", response_generator=result, allow=RNS.Destination.ALLOW_ALL
    )
    rich.destination.register_request_handler(
        "/file/test.txt",
        response_generator=lambda path, data, request_id, link_id, remote_identity, requested_at: [
            "test.txt",
            b"Native NomadNet file download\n",
        ],
        allow=RNS.Destination.ALLOW_ALL,
    )
    sites.append(rich)
    from html import escape
    from urllib.parse import parse_qs, urlsplit

    from nomadpl import Response, Site, StaticSite
    from retdns.storage import Registry
    from retdns.transport import Server

    static = StaticSite(ROOT / "tests" / "fixtures" / "html-site")

    def html_application(request):
        """Serve HTML test responses with recognizable navigation and form content."""
        if urlsplit(request.target).path == "/redirect":
            return Response(302, [("Location", "/form/?from=redirect")], b"")
        if urlsplit(request.target).path == "/form/":
            if request.method == "POST":
                name = parse_qs(request.body.decode()).get("name", [""])[0]
                body = f'<html><head><title>Form result</title></head><body><h1>Form result</h1><p>Hello {escape(name)}</p><a href="/">Home</a></body></html>'
            else:
                body = '<html><head><title>Test form</title></head><body><h1>Test form</h1><form method="post" action="/form/"><label>Name<input name="name" value="Visitor"></label><button>Submit</button></form><a href="/">Home</a></body></html>'
            return Response(
                200, [("Content-Type", "text/html; charset=utf-8")], body.encode()
            )
        return static(request)

    html = Site(
        load_identity(args.data / "html.identity"),
        html_application,
        name="NomadPL demo",
    )
    registry = Registry(args.data / "records.sqlite")
    # These sites share this process, so their own broadcasts are not received
    # by the DNS collector. Register their genuine signed announces directly.
    for name, site in (("home", html), ("native", sites[0])):
        packet = site.destination.announce(app_data=site.name.encode(), send=False)
        packet.pack()
        registry.register(
            name, site.destination.hash.hex(), announce=packet.raw, replace=True
        )
    dns = Server(
        load_identity(args.data / "dns.identity"), registry, name="Browser test DNS"
    )
    sites.extend([html, dns])
    (args.data / "nodes.json").write_text(
        json.dumps(
            {
                **(
                    {"relay": relay.propagation_destination.hash.hex()} if relay else {}
                ),
                **{
                    key: site.destination.hash.hex()
                    for key, site in zip(
                        ("main", "community", "rich", "html", "dns"), sites
                    )
                },
            }
        )
    )
    # Let loopback clients reconnect before the single startup announcement.
    time.sleep(5)
    while True:
        for site in sites:
            site.announce()
        if relay:
            relay.announce_propagation_node()
        time.sleep(args.announce_interval)


if __name__ == "__main__":
    main()
