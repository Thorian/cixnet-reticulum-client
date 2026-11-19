"""Durable store-and-forward delivery across independent, intermittently reachable relays.

Relay storage receipts complete one copy only. Direct delivery or an authenticated
ciXnet receipt completes the message and cancels remaining local work.
"""

import secrets
import threading
import time

import LXMF
import RNS
import RNS.vendor.umsgpack as msgpack

import attachments
from appearance import encode

RECEIPT_TYPE = "cixnet.delivery-receipt.v1"
RECEIPT_REQUEST = "cixnet.delivery.v1"


class Outbox:
    MAX_MESSAGES = 100
    MAX_BYTES = 64 * 1024 * 1024
    ANNOUNCE_CHECK_INTERVAL = 60

    def __init__(self, messaging):
        """Restore durable outgoing work and prepare independent relay sessions."""
        self.messaging = messaging
        self.active = set()
        self.servers = []
        self.mode = "auto"
        self.mailbox_interval = 300
        self.relay_routers = {}
        self.path_requests = {}
        self.known_paths = set()
        self.next_path_check = 0
        self.sync_next = {}
        self.sync_index = {}
        self.sync_rounds = {}
        self.sync_priority = {}
        self.last_relay_check = {}
        with messaging.lock:
            messaging.db.executescript("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT, owner TEXT, packed BLOB, fields BLOB,
                    attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, last_error TEXT,
                    PRIMARY KEY(id,owner));
                CREATE TABLE IF NOT EXISTS relay_copies (
                    id TEXT, owner TEXT, server TEXT, accepted REAL,
                    PRIMARY KEY(id,owner,server));
                CREATE TABLE IF NOT EXISTS sent_messages (
                    id TEXT, owner TEXT, wire_hash TEXT, peer TEXT,
                    PRIMARY KEY(id,owner));
                CREATE TABLE IF NOT EXISTS receipt_requests (
                    owner TEXT, wire_hash TEXT, peer TEXT,
                    PRIMARY KEY(owner,wire_hash));
            """)
            columns = {
                row[1] for row in messaging.db.execute("PRAGMA table_info(outbox)")
            }
            if "fields" not in columns:
                messaging.db.execute("ALTER TABLE outbox ADD COLUMN fields BLOB")
            messaging.db.execute("""UPDATE messages SET status='queued'
                WHERE EXISTS (SELECT 1 FROM outbox WHERE outbox.id=messages.id AND outbox.owner=messages.owner)""")
            messaging.db.commit()

    def configure(self, settings):
        """Apply delivery settings and reset the schedules affected by them."""
        with self.messaging.lock:
            self.servers = list(settings.get("propagationServers", []))
            self.mode = settings.get("deliveryMode", "auto")
            self.mailbox_interval = settings.get("mailboxCheckMinutes", 5) * 60
            self.sync_next.clear()
            self.sync_priority.clear()
            self.messaging.db.execute("UPDATE outbox SET due=0")
            self.messaging.db.commit()
        for owner in list(self.messaging.routers):
            self.ensure_relays(owner)

    def ensure_relays(self, owner):
        """Run on the main thread: LXMF installs process signal handlers.

        Each outbound router owns one relay link. Sharing a mutable outbound-node
        setting across simultaneous transfers would route copies incorrectly.
        Only the primary router registers the incoming delivery destination.
        """
        for server in self.servers:
            key = (owner, server)
            if key not in self.relay_routers:
                if len(self.relay_routers) >= 64:
                    raise ValueError("Relay session limit reached; restart the client")
                identity = RNS.Identity.from_file(
                    str(self.messaging.data / (owner + ".identity"))
                )
                router = LXMF.LXMRouter(
                    identity=identity,
                    storagepath=str(self.messaging.data / f"relay-{owner}-{server}"),
                    autopeer=False,
                )
                router.set_outbound_propagation_node(bytes.fromhex(server))
                self.relay_routers[key] = router

    def prepare(
        self, owner, peer, content, fields, packed=None, method="direct", timestamp=None
    ):
        """Preserve signed payload identity when rebuilding transport state."""
        identity = RNS.Identity.recall(bytes.fromhex(peer))
        if identity is None:
            self.request_path(peer)
            return None
        destination = RNS.Destination(
            identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
        )
        if destination.hash.hex() != peer:
            raise ValueError("This address is not an LXMF delivery destination")
        original = LXMF.LXMessage.unpack_from_bytes(packed) if packed else None
        message = LXMF.LXMessage(
            destination,
            self.messaging.routers[owner][1],
            original.content if original else content,
            title=original.title if original else "",
            fields=original.fields if original else fields,
            desired_method=LXMF.LXMessage.PROPAGATED
            if method == "relay"
            else LXMF.LXMessage.DIRECT,
        )
        message.timestamp = original.timestamp if original else timestamp
        message.pack()
        if original and message.hash != original.hash:
            raise ValueError(
                "Saved message hash changed; refusing to create a duplicate retry"
            )
        return message

    def enqueue(self, owner, peer, content, files, receipt_for=None):
        """Persist outgoing content before attempting direct or relay delivery."""
        app = self.messaging
        fields = {
            LXMF.FIELD_ICON_APPEARANCE: encode(app.profiles[owner]),
            **attachments.to_fields(files),
        }
        if receipt_for is None:
            fields[LXMF.FIELD_CUSTOM_META] = {RECEIPT_REQUEST: True}
        else:
            fields[LXMF.FIELD_CUSTOM_TYPE] = RECEIPT_TYPE
            fields[LXMF.FIELD_CUSTOM_DATA] = receipt_for
        message = self.prepare(owner, peer, content, fields)
        ident = message.hash.hex() if message else secrets.token_hex(32)
        # Receipt records are idempotent even if a crash interrupts their creation.
        if receipt_for:
            ident = "receipt-" + owner + "-" + receipt_for
        packed = message.packed if message else None
        saved_fields = b"" if packed else msgpack.packb(fields)
        with app.lock:
            if app.db.execute(
                "SELECT 1 FROM messages WHERE id=? AND owner=?", (ident, owner)
            ).fetchone():
                return {"id": ident}
            count, size = app.db.execute(
                "SELECT count(*),coalesce(sum(length(packed)+length(fields)),0) FROM outbox"
            ).fetchone()
            file_size = app.db.execute(
                "SELECT coalesce(sum(length(data)),0) FROM attachments WHERE EXISTS (SELECT 1 FROM outbox WHERE outbox.id=attachments.message AND outbox.owner=attachments.owner)"
            ).fetchone()[0]
            added = (
                len(packed or b"")
                + len(saved_fields)
                + sum(len(item["data"]) for item in files)
            )
            if count >= self.MAX_MESSAGES or size + file_size + added > self.MAX_BYTES:
                raise ValueError("The saved outbox is full (100 messages / 64 MiB)")
            try:
                app.store(
                    ident,
                    owner,
                    peer,
                    "system" if receipt_for else "out",
                    content,
                    "queued",
                    files,
                    commit=False,
                )
                app.db.execute(
                    "INSERT INTO outbox (id,owner,packed,fields,attempts,due,last_error) VALUES (?,?,?,?,0,0,'')",
                    (ident, owner, packed, saved_fields),
                )
                if message:
                    app.db.execute(
                        "INSERT INTO sent_messages VALUES (?,?,?,?)",
                        (ident, owner, message.hash.hex(), peer),
                    )
                app.db.commit()
            except Exception:
                app.db.rollback()
                raise
        return {"id": ident}

    def request_path(self, address):
        """Request a missing destination path without repeatedly flooding discovery."""
        now = time.monotonic()
        if now >= self.path_requests.get(address, 0):
            RNS.Transport.request_path(bytes.fromhex(address))
            self.path_requests[address] = now + 30

    def retry(self, ident, owner, error):
        """Schedule another delivery attempt while preserving the saved message."""
        app = self.messaging
        with app.lock:
            row = app.db.execute(
                "SELECT attempts FROM outbox WHERE id=? AND owner=?", (ident, owner)
            ).fetchone()
            if row:
                delay = min(900, 15 * 2 ** min(row[0], 6))
                app.db.execute(
                    "UPDATE outbox SET attempts=attempts+1,due=?,last_error=? WHERE id=? AND owner=?",
                    (time.time() + delay, str(error)[:200], ident, owner),
                )
                app.db.execute(
                    "UPDATE messages SET status='queued' WHERE id=? AND owner=?",
                    (ident, owner),
                )
                app.db.commit()
            app.pending.pop(ident, None)
            self.active.discard(owner)

    def complete(self, ident, owner):
        """Only direct proof or a signed receipt from this recipient ends all copies."""
        app = self.messaging
        with app.lock:
            batch = app.pending.pop(ident, None)
            if batch:
                batch["done"] = True
            app.db.execute("DELETE FROM outbox WHERE id=? AND owner=?", (ident, owner))
            app.db.execute(
                "UPDATE messages SET status='delivered' WHERE id=? AND owner=?",
                (ident, owner),
            )
            app.db.commit()
            if batch:
                self.active.discard(owner)
        if batch:
            for router, message in batch["routes"].values():
                router.cancel_outbound(message.hash)

    def receive_receipt(self, owner, peer, wire_hash):
        """Accept a receipt only when its signature and recipient match the message."""
        app = self.messaging
        with app.lock:
            row = app.db.execute(
                "SELECT id FROM sent_messages WHERE owner=? AND peer=? AND wire_hash=?",
                (owner, peer, wire_hash),
            ).fetchone()
        if row:
            self.complete(row[0], owner)

    def finish_route(self, ident, owner, route, message, success):
        """Record the outcome of one route without completing unrelated relay copies."""
        app = self.messaging
        direct = success and route == "direct"
        with app.lock:
            batch = app.pending.get(ident)
            if not batch or batch["done"] or route in batch["finished"]:
                return
            if batch["routes"].get(route, (None, None))[1] is not message:
                return
            batch["finished"].add(route)
            if success and route != "direct":
                app.db.execute(
                    "INSERT OR IGNORE INTO relay_copies VALUES (?,?,?,?)",
                    (ident, owner, route, time.time()),
                )
                app.db.commit()
            exhausted = batch["started"] and len(batch["finished"]) == len(
                batch["routes"]
            )
        if direct:
            self.complete(ident, owner)
        elif exhausted:
            self.end_batch(ident, owner)

    def end_batch(self, ident, owner):
        """Release active batch state after all scheduled routes have settled."""
        app = self.messaging
        with app.lock:
            batch = app.pending.get(ident)
            if (
                not batch
                or batch["done"]
                or len(batch["finished"]) != len(batch["routes"])
            ):
                return
            app.pending.pop(ident, None)
            batch["done"] = True
            accepted = {
                row[0]
                for row in app.db.execute(
                    "SELECT server FROM relay_copies WHERE id=? AND owner=?",
                    (ident, owner),
                )
            }
            all_stored = bool(self.servers) and set(self.servers) <= accepted
            if all_stored:
                app.db.execute(
                    "DELETE FROM outbox WHERE id=? AND owner=?", (ident, owner)
                )
                app.db.execute(
                    "UPDATE messages SET status='stored_on_relays' WHERE id=? AND owner=?",
                    (ident, owner),
                )
                app.db.commit()
                self.active.discard(owner)
                return
        self.retry(
            ident, owner, "Waiting for the remaining relays or recipient confirmation"
        )

    def dispatch(self, row):
        """Launch the next eligible delivery attempt from durable queued work."""
        ident, owner, peer, content, timestamp, packed, saved_fields = row
        app = self.messaging
        try:
            fields = msgpack.unpackb(saved_fields) if saved_fields else {}
            base = self.prepare(
                owner, peer, content, fields, packed, timestamp=timestamp
            )
            if base is None:
                self.retry(ident, owner, "Waiting for recipient identity")
                return
            with app.lock:
                accepted = {
                    r[0]
                    for r in app.db.execute(
                        "SELECT server FROM relay_copies WHERE id=? AND owner=?",
                        (ident, owner),
                    )
                }
            routes = {}
            if self.mode != "relay":
                routes["direct"] = (app.routers[owner][0], base)
            if self.mode != "direct":
                for server in list(self.servers):
                    if server in accepted:
                        continue
                    address = bytes.fromhex(server)
                    if RNS.Transport.has_path(address) and RNS.Identity.recall(address):
                        router = self.relay_routers[(owner, server)]
                        routes[server] = (
                            router,
                            self.prepare(
                                owner,
                                peer,
                                content,
                                fields,
                                base.packed,
                                "relay",
                                timestamp,
                            ),
                        )
                    else:
                        self.request_path(server)
            if not routes:
                if self.servers and set(self.servers) <= accepted:
                    with app.lock:
                        app.db.execute(
                            "DELETE FROM outbox WHERE id=? AND owner=?", (ident, owner)
                        )
                        app.db.execute(
                            "UPDATE messages SET status='stored_on_relays' WHERE id=? AND owner=?",
                            (ident, owner),
                        )
                        app.db.commit()
                        self.active.discard(owner)
                    return
                self.retry(ident, owner, "Waiting for reachable relays")
                return
            initial_routes = list(routes.items())
            batch = dict(routes=routes, done=False, finished=set(), started=False)
            with app.lock:
                if not app.db.execute(
                    "SELECT 1 FROM outbox WHERE id=? AND owner=?", (ident, owner)
                ).fetchone():
                    self.active.discard(owner)
                    return
                app.db.execute(
                    "UPDATE outbox SET packed=?,fields=? WHERE id=? AND owner=?",
                    (base.packed, b"", ident, owner),
                )
                app.db.execute(
                    "INSERT OR REPLACE INTO sent_messages VALUES (?,?,?,?)",
                    (ident, owner, base.hash.hex(), peer),
                )
                app.db.execute(
                    "UPDATE messages SET status='sending' WHERE id=? AND owner=?",
                    (ident, owner),
                )
                app.db.commit()
                app.pending[ident] = batch
            for route, (router, message) in initial_routes:
                message.register_delivery_callback(
                    lambda msg, key=route: self.finish_route(
                        ident, owner, key, msg, True
                    )
                )
                message.register_failed_callback(
                    lambda msg, key=route: self.finish_route(
                        ident, owner, key, msg, False
                    )
                )
            for route, (router, message) in initial_routes:

                def send(key=route, transport=router, msg=message):
                    """
                    Send this queued message and settle its route when the attempt
                    fails.
                    """
                    with app.lock:
                        if batch["done"]:
                            return
                    try:
                        transport.handle_outbound(msg)
                    except Exception:
                        self.finish_route(ident, owner, key, msg, False)

                threading.Thread(target=send, daemon=True).start()
            with app.lock:
                batch["started"] = True
                exhausted = len(batch["finished"]) == len(routes) and not batch["done"]
            if exhausted:
                self.end_batch(ident, owner)
        except Exception as error:
            self.retry(ident, owner, error)

    def prepare_receipts(self):
        """Queue authenticated acknowledgements requested by received messages."""
        app = self.messaging
        with app.lock:
            requests = app.db.execute(
                "SELECT owner,wire_hash,peer FROM receipt_requests LIMIT 4"
            ).fetchall()
        for owner, wire_hash, peer in requests:
            if owner not in app.routers:
                continue
            try:
                self.enqueue(owner, peer, "Delivery receipt", [], receipt_for=wire_hash)
                with app.lock:
                    app.db.execute(
                        "DELETE FROM receipt_requests WHERE owner=? AND wire_hash=?",
                        (owner, wire_hash),
                    )
                    app.db.commit()
            except (ValueError, OSError):
                return  # Keep durable requests when the outbox is full/offline.

    def path_available(self, address):
        """React to newly reachable destinations with pending delivery work."""
        app = self.messaging
        with app.lock:
            if address in self.servers:
                app.db.execute(
                    "UPDATE outbox SET due=0 WHERE NOT EXISTS (SELECT 1 FROM relay_copies c WHERE c.id=outbox.id AND c.owner=outbox.owner AND c.server=?)",
                    (address,),
                )
                now = time.monotonic()
                for owner in list(app.routers):
                    last_check = self.last_relay_check.get((owner, address))
                    if (
                        last_check is None
                        or now - last_check >= self.ANNOUNCE_CHECK_INTERVAL
                    ):
                        pending = self.sync_priority.setdefault(owner, [])
                        if address not in pending:
                            pending.append(address)
                        self.sync_next[owner] = 0
            else:
                app.db.execute(
                    "UPDATE outbox SET due=0 WHERE EXISTS (SELECT 1 FROM messages m WHERE m.id=outbox.id AND m.owner=outbox.owner AND m.peer=?)",
                    (address,),
                )
            app.db.commit()
        # A drive-by relay must not wait for an unrelated, slow direct transfer.
        if address in self.servers and self.mode != "direct":
            self.join_relay(address)

    def join_relay(self, server):
        """Attach a newly reachable mailbox to batches already in flight."""
        app = self.messaging
        if not RNS.Transport.has_path(bytes.fromhex(server)):
            return
        with app.lock:
            for ident, batch in list(app.pending.items()):
                if batch["done"] or server in batch["routes"]:
                    continue
                row = app.db.execute(
                    """SELECT m.owner,m.peer,m.content,m.timestamp,o.packed
                    FROM outbox o JOIN messages m ON m.id=o.id AND m.owner=o.owner
                    WHERE o.id=? AND NOT EXISTS (SELECT 1 FROM relay_copies c
                    WHERE c.id=o.id AND c.owner=o.owner AND c.server=?)""",
                    (ident, server),
                ).fetchone()
                if not row:
                    continue
                owner, peer, content, timestamp, packed = row
                router = self.relay_routers.get((owner, server))
                if router is None:
                    continue
                message = self.prepare(
                    owner, peer, content, {}, packed, "relay", timestamp
                )
                if message is None:
                    continue
                batch["routes"][server] = (router, message)
                message.register_delivery_callback(
                    lambda msg, key=ident, identity=owner: self.finish_route(
                        key, identity, server, msg, True
                    )
                )
                message.register_failed_callback(
                    lambda msg, key=ident, identity=owner: self.finish_route(
                        key, identity, server, msg, False
                    )
                )

                def send(
                    key=ident,
                    identity=owner,
                    transfer=message,
                    transport=router,
                    current=batch,
                ):
                    """
                    Send an additional relay copy without disturbing other active
                    transfers.
                    """
                    with app.lock:
                        if current["done"]:
                            return
                    try:
                        transport.handle_outbound(transfer)
                    except Exception:
                        self.finish_route(key, identity, server, transfer, False)

                threading.Thread(target=send, daemon=True).start()

    def watch_paths(self):
        """Notice path changes that can unblock queued messages or relay copies."""
        if time.monotonic() < self.next_path_check:
            return
        self.next_path_check = time.monotonic() + 5
        with self.messaging.lock:
            if not self.messaging.db.execute("SELECT 1 FROM outbox LIMIT 1").fetchone():
                return
        available = set()
        for server in list(self.servers):
            if RNS.Transport.has_path(bytes.fromhex(server)):
                available.add(server)
                if server not in self.known_paths:
                    self.path_available(server)
            else:
                self.request_path(server)
        self.known_paths = available

    def tick(self):
        """Advance outgoing delivery work from the main service loop."""
        self.prepare_receipts()
        self.watch_paths()
        app = self.messaging
        with app.lock:
            rows = app.db.execute(
                """SELECT m.id,m.owner,m.peer,m.content,m.timestamp,o.packed,o.fields
                FROM outbox o JOIN messages m ON m.id=o.id AND m.owner=o.owner
                WHERE o.due<=? ORDER BY CASE WHEN m.direction='system' THEN 0 ELSE 1 END,m.timestamp LIMIT 100""",
                (time.time(),),
            ).fetchall()
            for row in rows:
                owner = row[1]
                if (
                    owner not in app.routers
                    or owner in self.active
                    or len(self.active) >= 4
                ):
                    continue
                router = app.routers[owner][0]
                if 0 < router.propagation_transfer_state < LXMF.LXMRouter.PR_COMPLETE:
                    continue
                self.active.add(owner)
                threading.Thread(target=self.dispatch, args=(row,), daemon=True).start()
        self.sync_due()

    def sync(self, owner, preferred=None):
        """Perform the requested mailbox synchronization for one relay session."""
        app = self.messaging
        if owner not in app.routers:
            raise ValueError("Select an identity first")
        with app.lock:
            if not self.servers:
                raise ValueError("Add at least one propagation server")
            router, destination = app.routers[owner]
            if (
                owner in self.active
                or 0 < router.propagation_transfer_state < LXMF.LXMRouter.PR_COMPLETE
            ):
                raise ValueError("A message transfer is already active")
            start = self.sync_index.get(owner, 0)
            server = None
            candidates = (
                [preferred]
                if preferred
                else [
                    self.servers[(start + step) % len(self.servers)]
                    for step in range(len(self.servers))
                ]
            )
            for candidate in candidates:
                if candidate not in self.servers:
                    continue
                if RNS.Transport.has_path(bytes.fromhex(candidate)):
                    server = candidate
                    self.sync_index[owner] = self.servers.index(candidate) + 1
                    break
                self.request_path(candidate)
            if server is None:
                raise ValueError("Waiting for a route to a configured relay")
            remaining = self.sync_rounds.get(owner, len(self.servers)) - 1
            self.sync_rounds[owner] = remaining
            self.sync_next[owner] = time.monotonic() + (
                1 if remaining > 0 else self.mailbox_interval
            )
            router.set_outbound_propagation_node(bytes.fromhex(server))
            router.request_messages_from_propagation_node(destination.identity)
            self.last_relay_check[(owner, server)] = time.monotonic()
            return dict(server=server, state=router.propagation_transfer_state)

    def request_sync(self, owner):
        """Schedule a mailbox check while retaining already pending relay work."""
        self.sync_rounds[owner] = len(self.servers)
        self.sync_next[owner] = 0
        return self.sync(owner)

    def sync_due(self):
        """Start due mailbox checks without interrupting an active transfer."""
        if not self.servers:
            return
        for owner in list(self.messaging.routers):
            if time.monotonic() >= self.sync_next.get(owner, 0):
                if self.sync_rounds.get(owner, 0) <= 0:
                    self.sync_rounds[owner] = len(self.servers)
                try:
                    with self.messaging.lock:
                        pending = self.sync_priority.get(owner, [])
                        # A brief contact can disappear before the current
                        # transfer finishes. Do not block other mailboxes on it.
                        while pending and not RNS.Transport.has_path(
                            bytes.fromhex(pending[0])
                        ):
                            pending.pop(0)
                        preferred = pending[0] if pending else None
                    # Fetch the announcing mailbox first, rather than whichever
                    # server happens to be next in the regular polling rotation.
                    self.sync(owner, preferred=preferred)
                    with self.messaging.lock:
                        pending = self.sync_priority.get(owner, [])
                        if preferred in pending:
                            pending.remove(preferred)
                        if pending:
                            self.sync_next[owner] = 0
                except ValueError:
                    self.sync_next[owner] = time.monotonic() + 5

    def cancel(self, owner, ident):
        """Cancel local pending work for a message without altering received history."""
        app = self.messaging
        with app.lock:
            if not app.db.execute(
                "SELECT 1 FROM outbox WHERE owner=? AND id=?", (owner, ident)
            ).fetchone():
                raise ValueError("Queued message not found")
            batch = app.pending.pop(ident, None)
            if batch:
                batch["done"] = True
                self.active.discard(owner)
            app.db.execute("DELETE FROM outbox WHERE owner=? AND id=?", (owner, ident))
            app.db.execute(
                "UPDATE messages SET status='cancelled' WHERE owner=? AND id=?",
                (owner, ident),
            )
            app.db.commit()
        if batch:
            for router, message in batch["routes"].values():
                router.cancel_outbound(message.hash)
        return dict(ok=True)
