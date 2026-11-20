"""Bounded asynchronous NomadNet requests over native Reticulum links.

The HTTP thread only starts/polls jobs. Slow radio requests must not stop message
reception or settings. Remote page text is returned as data, never executed.
"""

import posixpath
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import RNS

from attachments import safe_name

PAGE_LIMIT = 1024 * 1024


def resolve_url(value, base=None):
    """Resolve a native NomadNet address or relative page reference safely."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("Enter a NomadNet node address and page path")
    value = value.strip().split("#", 1)[0]
    for prefix in ("nnn@", "nomadnetwork.node@"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    if base and value.startswith(":/"):
        value = value[1:]
    match = re.fullmatch(r"([0-9a-fA-F]{32})(?::(.*))?", value)
    if match:
        node, path = match.group(1).lower(), match.group(2) or "/page/index.mu"
    elif base:
        node, previous = resolve_url(base).split(":", 1)
        path = (
            value
            if value.startswith("/")
            else posixpath.join(posixpath.dirname(previous), value)
        )
    else:
        raise ValueError(
            "Use a 32-character NomadNet node address, not an identity or LXMF address"
        )
    if any(ord(c) < 32 for c in path) or "\\" in path or ":" in path or "?" in path:
        raise ValueError("Invalid NomadNet page path")
    path = posixpath.normpath("/" + path.lstrip("/"))
    if not (
        (path.startswith("/page/") and path.endswith(".mu"))
        or path.startswith("/file/")
        or path.startswith("/media/")
    ):
        raise ValueError("Use a native /page/*.mu page or /file/ download path")
    return f"{node}:{path}"


class NomadBrowser:
    def __init__(self, profiles, web=None):
        """Prepare owner-scoped bookmarks, request jobs and reusable link state."""
        self.web = web
        self.profiles = profiles
        self.lock = threading.RLock()
        self.jobs = OrderedDict()
        self.links = OrderedDict()
        self.db = sqlite3.connect(
            str(profiles.directory / "browser.sqlite"), check_same_thread=False
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS bookmarks (owner TEXT, url TEXT, name TEXT, PRIMARY KEY(owner,url))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS page_identity (owner TEXT, url TEXT, identify INTEGER, PRIMARY KEY(owner,url))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS node_identity (owner TEXT, node TEXT, identify INTEGER, PRIMARY KEY(owner,node))"
        )
        self.db.commit()

    def page_identity(self, owner, url, identify=None, base=None):
        """Remember disclosure per destination and local identity, across page paths."""
        self.profiles.get(owner)
        url = self._validate_url(url, base)
        canonical = self.web.canonical(owner, url) if self.web else url
        if canonical.startswith("nomadpl://"):
            node = "nomadpl://" + urlsplit(canonical).netloc.lower()
            legacy_prefix = node + "/%"
        else:
            node = canonical.split(":", 1)[0].lower()
            legacy_prefix = node + ":%"
        if identify is not None and type(identify) is not bool:
            raise ValueError("Identify must be true or false")
        with self.lock:
            if identify is not None:
                self.db.execute(
                    "INSERT INTO node_identity VALUES (?, ?, ?) ON CONFLICT(owner,node) DO UPDATE SET identify=excluded.identify",
                    (owner, node, int(identify)),
                )
            row = self.db.execute(
                "SELECT identify FROM node_identity WHERE owner=? AND node=?",
                (owner, node),
            ).fetchone()
            if row is None:
                # Keep the most recently chosen page setting when upgrading.
                row = self.db.execute(
                    "SELECT identify FROM page_identity WHERE owner=? AND (url=? OR url LIKE ?) ORDER BY rowid DESC LIMIT 1",
                    (owner, url, legacy_prefix),
                ).fetchone()
                if row is not None:
                    self.db.execute(
                        "INSERT INTO node_identity VALUES (?, ?, ?)",
                        (owner, node, row[0]),
                    )
            self.db.commit()
        return {"url": url, "identify": bool(row[0]) if row else False}

    def _validate_url(self, value, base=None):
        """Check a resolved request against the browser's allowed page/file paths."""
        if (
            base
            and isinstance(value, str)
            and value.endswith(".mu")
            and ":" not in value
        ):
            return resolve_url(value, base)
        if (
            self.web
            and isinstance(value, str)
            and (
                value.startswith("nomadpl://")
                or re.match(r"^[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+(?::|/|$)", value)
            )
        ):
            if len(value) > 2048 or any(ord(c) < 33 for c in value) or "\\" in value:
                raise ValueError("Invalid network URL")
            return value
        return resolve_url(value, base)

    def bookmarks(self, owner):
        """Return only the bookmarks belonging to the selected local identity."""
        self.profiles.get(owner)
        with self.lock:
            return [
                {"url": url, "name": name}
                for url, name in self.db.execute(
                    "SELECT url,name FROM bookmarks WHERE owner=? ORDER BY name",
                    (owner,),
                ).fetchall()
            ]

    def bookmark(self, owner, url, name, remove=False):
        """Add, rename or remove a validated bookmark for its owner."""
        self.profiles.get(owner)
        if type(remove) is not bool:
            raise ValueError("Remove must be true or false")
        url = self._validate_url(url)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Bookmark name must contain 1â€“100 characters")
        with self.lock:
            if remove:
                self.db.execute(
                    "DELETE FROM bookmarks WHERE owner=? AND url=?", (owner, url)
                )
            else:
                if len(self.bookmarks(owner)) >= 200 and not any(
                    item["url"] == url for item in self.bookmarks(owner)
                ):
                    raise ValueError("This identity already has 200 bookmarks")
                self.db.execute(
                    """
                    INSERT INTO bookmarks VALUES (?, ?, ?)
                    ON CONFLICT(owner, url) DO UPDATE SET name = excluded.name
                    """,
                    (owner, url, name.strip()),
                )
            self.db.commit()
        return self.bookmarks(owner)

    def open(
        self,
        owner,
        url,
        base=None,
        data=None,
        identify=False,
        source=False,
        max_bytes=None,
    ):
        """Create a bounded asynchronous page job without blocking the HTTP thread."""
        self.profiles.get(owner)
        if max_bytes is not None and (
            type(max_bytes) is not int or not 1024 <= max_bytes <= 8 * PAGE_LIMIT
        ):
            raise ValueError("Invalid response size limit")
        url = self._validate_url(url, base)
        if type(source) is not bool:
            raise ValueError("Source must be true or false")
        if type(identify) is not bool:
            raise ValueError("Identify must be true or false")
        if data is not None:
            if (
                not isinstance(data, dict)
                or len(data) > 64
                or any(
                    not isinstance(k, str)
                    or not isinstance(v, str)
                    or not k.startswith(("field_", "var_"))
                    or len(k) > 100
                    or len(v.encode()) > 16000
                    for k, v in data.items()
                )
            ):
                raise ValueError("Invalid NomadNet form data")
        with self.lock:
            # One request per local identity, with a bound on retained page data.
            for job in self.jobs.values():
                if job["owner"] == owner and job["phase"] not in (
                    "done",
                    "error",
                    "cancelled",
                ):
                    self._cancel(job)
            if (
                sum(
                    job["phase"] not in ("done", "error", "cancelled")
                    for job in self.jobs.values()
                )
                >= 8
            ):
                raise ValueError("Too many page requests are active")
            while len(self.jobs) >= 16:
                key = next(
                    (
                        key
                        for key, job in self.jobs.items()
                        if job["phase"] in ("done", "error", "cancelled")
                    ),
                    None,
                )
                if key is None:
                    raise ValueError("Too many page requests")
                self.jobs.pop(key)
            ident = secrets.token_hex(16)
            job = {
                "id": ident,
                "owner": owner,
                "url": url,
                "requested_url": url,
                "view_source": source,
                "max_bytes": max_bytes,
                "phase": "finding_path",
                "progress": 0,
                "source": None,
                "frame": None,
                "error": None,
                "download": None,
                "file_data": None,
                "stop": threading.Event(),
                "link": None,
            }
            self.jobs[ident] = job
        threading.Thread(
            target=self._fetch, args=(job, data, identify), daemon=True
        ).start()
        return self.status(owner, ident)

    def status(self, owner, ident):
        """Return the public progress snapshot for an owner-authorized job."""
        self.profiles.get(owner)
        with self.lock:
            job = self.jobs.get(ident)
            if not job or job["owner"] != owner:
                raise ValueError("Page request not found for this identity")
            return {
                key: job[key]
                for key in (
                    "id",
                    "url",
                    "requested_url",
                    "phase",
                    "progress",
                    "source",
                    "frame",
                    "error",
                    "download",
                )
            }

    def download(self, owner, ident):
        """Return completed file bytes only to the job's owning identity."""
        self.status(owner, ident)
        with self.lock:
            job = self.jobs[ident]
            if job["phase"] != "done" or job["file_data"] is None:
                raise ValueError("The file is not available")
            return job["download"]["name"], job["file_data"]

    def _cancel(self, job):
        """Mark a pending job cancelled and tear down its active link."""
        job["stop"].set()
        job["phase"] = "cancelled"
        if job["link"]:
            job["link"].teardown()

    def cancel(self, owner, ident):
        """Authorize a cancellation request before stopping the matching job."""
        self.status(owner, ident)
        with self.lock:
            self._cancel(self.jobs[ident])
        return {"ok": True}

    def _update(self, job, **fields):
        """Apply progress changes only while the job remains active."""
        with self.lock:
            if not job["stop"].is_set():
                job.update(fields)

    def _wait(self, job, ready, seconds, error):
        """Wait for a request condition while honoring cancellation and timeout."""
        deadline = time.monotonic() + seconds
        while not ready():
            if job["stop"].wait(0.1):
                return False
            if time.monotonic() >= deadline:
                raise ValueError(error)
        return not job["stop"].is_set()

    def _fetch(self, job, data, identify):
        """
        Resolve the destination and carry out a bounded native page or file request.
        """
        link = None
        try:
            if self.web:
                canonical = self.web.canonical(job["owner"], job["url"])
                if job["stop"].is_set():
                    return
                if canonical.startswith("nomadpl://"):
                    if job["view_source"]:
                        source = self.web.source(job["owner"], canonical, identify)
                        self._update(
                            job, phase="done", progress=1, url=canonical, source=source
                        )
                        return
                    frame = self.web.gateway(job["owner"], canonical, identify)
                    self._update(
                        job,
                        phase="done",
                        progress=1,
                        frame=frame,
                        url=canonical,
                        source="",
                    )
                    return
                self._update(job, url=canonical)
            node, path = job["url"].split(":", 1)
            limit = (
                8 * PAGE_LIMIT if path.startswith(("/file/", "/media/")) else PAGE_LIMIT
            )
            if job.get("max_bytes") is not None:
                limit = min(limit, job["max_bytes"])
            address = bytes.fromhex(node)
            if not RNS.Transport.has_path(address):
                RNS.Transport.request_path(address)
            if not self._wait(
                job,
                lambda: RNS.Transport.has_path(address),
                30,
                "No route to this node. Check the connection or wait for its announce.",
            ):
                return
            identity = RNS.Identity.recall(address)
            if identity is None:
                raise ValueError("Node identity is not known yet")
            destination = RNS.Destination(
                identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "nomadnetwork",
                "node",
            )
            if destination.hash != address:
                raise ValueError("This address is not a NomadNet page node")
            key = (job["owner"], node, identify)
            with self.lock:
                link = self.links.get(key)
                if link is None or link.status != RNS.Link.ACTIVE:
                    link = RNS.Link(destination)
                    self.links[key] = link
                self.links.move_to_end(key)
                while len(self.links) > 8:
                    _, old = self.links.popitem(last=False)
                    old.teardown()
                job["link"] = link
            self._update(job, phase="connecting")
            if not self._wait(
                job,
                lambda: link.status in (RNS.Link.ACTIVE, RNS.Link.CLOSED),
                45,
                "The node did not establish a link",
            ):
                return
            if link.status != RNS.Link.ACTIVE:
                raise ValueError("The node closed the connection")
            if identify:
                selected = RNS.Identity.from_file(
                    str(self.profiles.directory / f"{job['owner']}.identity")
                )
                link.identify(selected)
            complete = threading.Event()

            def failed(receipt):
                """Wake the page worker after a failed native request."""
                self._update(
                    job,
                    phase="error",
                    error="Page unavailable, denied, too large, or request timed out",
                )
                complete.set()

            def received(receipt):
                """
                Capture the native response so the worker can validate and expose it.
                """
                try:
                    response = receipt.response
                    if hasattr(response, "read"):
                        try:
                            response = response.read(limit + 1)
                        finally:
                            receipt.response.close()
                    if path.startswith("/media/"):
                        if not isinstance(response, bytes) or len(response) > limit:
                            raise ValueError("The node did not return valid image data")
                        self._update(
                            job,
                            phase="done",
                            progress=1,
                            download={
                                "name": safe_name(path.rsplit("/", 1)[-1]),
                                "size": len(response),
                            },
                            file_data=response,
                        )
                        return
                    if path.startswith("/file/"):
                        if (
                            not isinstance(response, (list, tuple))
                            or len(response) != 2
                            or not isinstance(response[0], str)
                            or not isinstance(response[1], bytes)
                            or len(response[1]) > limit
                        ):
                            raise ValueError(
                                "The node did not return a valid file within the 8 MiB limit"
                            )
                        self._update(
                            job,
                            phase="done",
                            progress=1,
                            download={
                                "name": safe_name(response[0]),
                                "size": len(response[1]),
                            },
                            file_data=response[1],
                        )
                        return
                    if not isinstance(response, bytes) or len(response) > PAGE_LIMIT:
                        raise ValueError(
                            "The node did not return a Micron page within the 1 MiB limit"
                        )
                    source = response.decode("utf-8-sig")
                    self._update(job, phase="done", progress=1, source=source)
                except (ValueError, UnicodeError) as error:
                    self._update(job, phase="error", error=str(error))
                finally:
                    complete.set()

            self._update(job, phase="requesting")
            receipt = link.request(
                "/media" if path.startswith("/media/") else path,
                data={"path": path, "key": None}
                if path.startswith("/media/")
                else data,
                response_callback=received,
                failed_callback=failed,
                progress_callback=lambda receipt: self._update(
                    job, phase="receiving", progress=receipt.progress
                ),
                timeout=120,
                max_response_size=limit,
            )
            if not receipt:
                raise ValueError("Could not send the page request")
            if not self._wait(job, complete.is_set, 125, "The page request timed out"):
                return
        except Exception as error:
            self._update(job, phase="error", error=str(error))
            if link:
                link.teardown()
