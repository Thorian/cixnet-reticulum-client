"""LXMF lifecycle and per-identity durable history.

Router creation runs on the main thread because LXMF installs signal handlers.
Delivery callbacks run on worker threads, so every SQLite operation is locked.
"""

import json
import logging
import sqlite3
import threading
import time

import LXMF
import RNS

import attachments
from appearance import decode
from outbox import RECEIPT_REQUEST, RECEIPT_TYPE, Outbox


class Messaging:
    def __init__(self, data):
        """Open durable message storage and initialize per-identity router state."""
        self.data = data
        self.lock = threading.RLock()
        self.routers = {}
        self.pending = {}
        self.on_message = None
        self.profiles = {}
        self.announce_minutes = 45
        self.last_announced = {}
        self.db = sqlite3.connect(
            str(data / "messages.sqlite"), check_same_thread=False
        )
        self.db.create_function(
            "cixnet_casefold",
            1,
            lambda value: (value or "").casefold(),
            deterministic=True,
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT, owner TEXT, peer TEXT, direction TEXT,
                content TEXT, timestamp REAL, status TEXT,
                PRIMARY KEY(id, owner)
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS messages_owner_time ON messages(owner,timestamp DESC)"
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS appearances (
                owner TEXT, peer TEXT, appearance TEXT, timestamp REAL,
                PRIMARY KEY(owner, peer)
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                owner TEXT, message TEXT, position INTEGER,
                name TEXT, data BLOB, image INTEGER,
                PRIMARY KEY(owner, message, position)
            )
            """
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS peer_names (peer TEXT PRIMARY KEY, name TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS blocked_contacts "
            "(owner TEXT, peer TEXT, PRIMARY KEY(owner, peer))"
        )
        self.peer_names = dict(
            self.db.execute("SELECT peer,name FROM peer_names").fetchall()
        )
        self.db.execute(
            """
            UPDATE messages SET status = 'interrupted'
            WHERE direction = 'out' AND status IN ('queued', 'sending')
            """
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS unverified_messages "
            "(id TEXT, owner TEXT, peer TEXT, packed BLOB, received REAL, PRIMARY KEY(id,owner))"
        )
        self.db.commit()
        self.next_verification = 0
        self.outbox = Outbox(self)

    def blocked_contacts(self, owner):
        """Return this identity's persisted block list, without affecting others."""
        with self.lock:
            return [
                row[0]
                for row in self.db.execute(
                    "SELECT peer FROM blocked_contacts WHERE owner=?", (owner,)
                )
            ]

    def set_blocked(self, owner, peer, blocked):
        """Keep old history, but discard new incoming messages from this address."""
        if not isinstance(peer, str) or len(peer) != 32:
            raise ValueError("Enter a 32-character LXMF address")
        try:
            if len(bytes.fromhex(peer)) != 16:
                raise ValueError()
        except ValueError:
            raise ValueError("Invalid LXMF address") from None
        if not isinstance(blocked, bool):
            raise ValueError("Blocked must be true or false")
        peer = peer.lower()
        with self.lock:
            if blocked:
                self.db.execute(
                    "INSERT OR IGNORE INTO blocked_contacts VALUES (?,?)", (owner, peer)
                )
            else:
                self.db.execute(
                    "DELETE FROM blocked_contacts WHERE owner=? AND peer=?",
                    (owner, peer),
                )
            self.db.commit()
            queued = (
                self.db.execute(
                    "SELECT m.id FROM messages m JOIN outbox o ON m.id=o.id AND m.owner=o.owner "
                    "WHERE m.owner=? AND m.peer=?",
                    (owner, peer),
                ).fetchall()
                if blocked
                else []
            )
        for (ident,) in queued:
            self.outbox.cancel(owner, ident)
        return {"blocked": self.blocked_contacts(owner)}

    def activate(self, profile):
        """Load each identity once; edits update metadata without replacing keys."""
        owner = profile["id"]
        self.profiles[owner] = dict(profile)
        if owner not in self.routers:
            identity = RNS.Identity.from_file(str(self.data / (owner + ".identity")))
            if identity is None:
                raise ValueError("Could not open identity")
            router = LXMF.LXMRouter(storagepath=str(self.data / ("lxmf-" + owner)))
            dest = router.register_delivery_identity(
                identity, display_name=profile.get("display_name", profile["nickname"])
            )
            router.register_delivery_callback(
                lambda message: self.receive(owner, message)
            )
            self.routers[owner] = (router, dest)
        router, dest = self.routers[owner]
        dest.display_name = profile.get("display_name", profile["nickname"])
        self.outbox.ensure_relays(owner)
        return {"address": dest.hash.hex(), "identity": owner}

    def announce(self, owner):
        """
        Publish one identity's delivery destination and remember the announce time.
        """
        router, dest = self.routers[owner]
        router.announce(dest.hash)
        self.last_announced[owner] = time.monotonic()

    def announce_due(self):
        """Called by the main server loop, even with no browser open.

        Use elapsed time so wall-clock adjustments cannot cause announce floods.
        Never replay missed intervals after sleep; announce each identity once.
        """
        now = time.monotonic()
        for owner in list(self.routers):
            if (
                now - self.last_announced.get(owner, float("-inf"))
                >= self.announce_minutes * 60
            ):
                self.announce(owner)

    def receive(self, owner, message):
        """Persist only authenticated messages and validated optional appearance."""
        if not message.signature_validated:
            if (
                getattr(message, "unverified_reason", None)
                == LXMF.LXMessage.SOURCE_UNKNOWN
            ):
                self.defer_verification(owner, message)
            return
        if message.source_hash.hex() in self.blocked_contacts(owner):
            return
        fields = message.fields or {}
        if fields.get(LXMF.FIELD_CUSTOM_TYPE) == RECEIPT_TYPE:
            wire_hash = fields.get(LXMF.FIELD_CUSTOM_DATA)
            if (
                isinstance(wire_hash, str)
                and len(wire_hash) == 64
                and all(c in "0123456789abcdef" for c in wire_hash)
            ):
                self.outbox.receive_receipt(owner, message.source_hash.hex(), wire_hash)
            return
        appearance = decode(fields.get(LXMF.FIELD_ICON_APPEARANCE))
        if appearance:
            with self.lock:
                self.db.execute(
                    """
                    INSERT INTO appearances VALUES (?, ?, ?, ?)
                    ON CONFLICT(owner, peer) DO UPDATE SET
                        appearance = excluded.appearance,
                        timestamp = excluded.timestamp
                    WHERE excluded.timestamp >= appearances.timestamp
                    """,
                    (
                        owner,
                        message.source_hash.hex(),
                        json.dumps(appearance),
                        message.timestamp,
                    ),
                )
                self.db.commit()
        with self.lock:
            fresh = self.store(
                message.hash.hex(),
                owner,
                message.source_hash.hex(),
                "in",
                message.content_as_string(),
                "received",
                attachments.from_fields(fields),
                commit=False,
            )
            metadata = fields.get(LXMF.FIELD_CUSTOM_META)
            if isinstance(metadata, dict) and metadata.get(RECEIPT_REQUEST) is True:
                self.db.execute(
                    "INSERT OR IGNORE INTO receipt_requests VALUES (?,?,?)",
                    (owner, message.hash.hex(), message.source_hash.hex()),
                )
            self.db.commit()
        if fresh and self.on_message:
            try:
                self.on_message(owner, message.source_hash.hex(), message.hash.hex())
            except Exception:
                logging.exception("Incoming message was saved but notification failed")

    def defer_verification(self, owner, message):
        """Keep signed bytes until the sender's public key becomes available."""
        packed = message.packed
        if not isinstance(packed, bytes) or len(packed) > 8 * 1024 * 1024:
            return
        peer = message.source_hash.hex()
        if peer in self.blocked_contacts(owner):
            return
        with self.lock:
            self.db.execute(
                "DELETE FROM unverified_messages WHERE received<?",
                (time.time() - 7 * 86400,),
            )
            count, size = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(LENGTH(packed)),0) FROM unverified_messages"
            ).fetchone()
            if count >= 100 or size + len(packed) > 64 * 1024 * 1024:
                logging.warning("Pending message verification storage is full")
                return
            self.db.execute(
                "INSERT OR IGNORE INTO unverified_messages VALUES (?,?,?,?,?)",
                (message.hash.hex(), owner, peer, packed, time.time()),
            )
            self.db.commit()

    def verify_pending(self):
        """Retry authentication without exposing unverified content to the UI."""
        now = time.monotonic()
        if now < self.next_verification:
            return
        self.next_verification = now + 2
        with self.lock:
            rows = self.db.execute(
                "SELECT id,owner,peer,packed,received FROM unverified_messages"
            ).fetchall()
        for ident, owner, peer, packed, received in rows:
            if time.time() - received < 7 * 86400 and peer not in self.blocked_contacts(
                owner
            ):
                if RNS.Identity.recall(bytes.fromhex(peer)) is None:
                    self.outbox.request_path(peer)
                    continue
                try:
                    message = LXMF.LXMessage.unpack_from_bytes(packed)
                    if message.signature_validated:
                        self.receive(owner, message)
                except Exception:
                    logging.exception("Could not verify a retained incoming message")
                    continue
            with self.lock:
                self.db.execute(
                    "DELETE FROM unverified_messages WHERE id=? AND owner=?",
                    (ident, owner),
                )
                self.db.commit()

    def store(
        self, ident, owner, peer, direction, content, status, files=None, commit=True
    ):
        # Retried network delivery must not create duplicate conversation entries.
        """Save a message and its attachments within the owning identity's history."""
        with self.lock:
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?)",
                (ident, owner, peer, direction, content, time.time(), status),
            )
            for position, item in enumerate(files or []):
                self.db.execute(
                    "INSERT OR IGNORE INTO attachments VALUES (?,?,?,?,?,?)",
                    (
                        owner,
                        ident,
                        position,
                        item["name"],
                        item["data"],
                        int(item["image"]),
                    ),
                )
            if commit:
                self.db.commit()
            return inserted.rowcount == 1

    def update(self, ident, owner, status):
        """Persist a delivery-state change for the specified identity and message."""
        with self.lock:
            self.db.execute(
                "UPDATE messages SET status=? WHERE id=? AND owner=?",
                (status, ident, owner),
            )
            self.db.commit()
            if status in ("delivered", "failed"):
                self.pending.pop(ident, None)

    def send(self, owner, peer, content, files=None):
        """Queue direct LXMF delivery; the response is not a delivery receipt."""
        if isinstance(peer, str) and peer.lower() in self.blocked_contacts(owner):
            raise ValueError("Unblock this contact before sending")
        files = attachments.validate(files or [])
        if not isinstance(peer, str) or len(peer) != 32:
            raise ValueError("Enter a 32-character LXMF address")
        try:
            address = bytes.fromhex(peer)
        except ValueError:
            raise ValueError("Destination must contain hexadecimal characters")
        if len(address) != 16:
            raise ValueError("Invalid destination")
        if (
            not isinstance(content, str)
            or (not content.strip() and not files)
            or len(content.encode()) > 16000
        ):
            raise ValueError("Message must contain 1–16000 UTF-8 bytes")
        if owner not in self.routers:
            raise ValueError("Select an identity before sending")
        return self.outbox.enqueue(owner, peer.lower(), content, files)

    def history(self, owner, around=None):
        """Return recent history, or a bounded conversation window around a search hit."""
        with self.lock:
            if around is None:
                rows = self.db.execute(
                    "SELECT id,peer,direction,content,timestamp,status FROM messages "
                    "WHERE owner=? AND direction IN ('in','out') ORDER BY timestamp DESC LIMIT 1000",
                    (owner,),
                ).fetchall()
            else:
                if not isinstance(around, str) or not 1 <= len(around) <= 128:
                    raise ValueError("Invalid search message")
                anchor = self.db.execute(
                    "SELECT peer,timestamp FROM messages WHERE owner=? AND id=? AND direction IN ('in','out')",
                    (owner, around),
                ).fetchone()
                if anchor is None:
                    raise ValueError("Search message is no longer available")
                peer, timestamp = anchor
                before = self.db.execute(
                    "SELECT id,peer,direction,content,timestamp,status FROM messages "
                    "WHERE owner=? AND peer=? AND direction IN ('in','out') AND timestamp<=? "
                    "ORDER BY timestamp DESC LIMIT 51",
                    (owner, peer, timestamp),
                ).fetchall()
                after = self.db.execute(
                    "SELECT id,peer,direction,content,timestamp,status FROM messages "
                    "WHERE owner=? AND peer=? AND direction IN ('in','out') AND timestamp>? "
                    "ORDER BY timestamp LIMIT 49",
                    (owner, peer, timestamp),
                ).fetchall()
                rows = sorted(before + after, key=lambda row: row[4], reverse=True)
            if around is not None and not any(row[0] == around for row in rows):
                rows.append(
                    self.db.execute(
                        "SELECT id,peer,direction,content,timestamp,status FROM messages WHERE owner=? AND id=?",
                        (owner, around),
                    ).fetchone()
                )
                rows.sort(key=lambda row: row[4], reverse=True)
            file_rows = []
            for offset in range(0, len(rows), 400):
                ids = [row[0] for row in rows[offset : offset + 400]]
                placeholders = ",".join("?" for _ in ids)
                file_rows.extend(
                    self.db.execute(
                        "SELECT message,position,name,length(data),image FROM attachments "
                        f"WHERE owner=? AND message IN ({placeholders})",
                        (owner, *ids),
                    ).fetchall()
                )
            copies = dict(
                self.db.execute(
                    "SELECT id,count(*) FROM relay_copies WHERE owner=? GROUP BY id",
                    (owner,),
                ).fetchall()
            )
            queued = {
                ident: (due, error)
                for ident, due, error in self.db.execute(
                    "SELECT id,due,last_error FROM outbox WHERE owner=?", (owner,)
                )
            }
        metadata = {}
        for message, position, name, size, image in file_rows:
            metadata.setdefault(message, []).append(
                {"position": position, "name": name, "size": size, "image": bool(image)}
            )
        return [
            dict(
                zip(("id", "peer", "direction", "content", "timestamp", "status"), row),
                attachments=metadata.get(row[0], []),
                relay_copies=copies.get(row[0], 0),
                relay_target=len(self.outbox.servers),
                queued=row[0] in queued,
                queue_error=queued.get(row[0], (0, ""))[1],
            )
            for row in reversed(rows)
        ]

    def search(self, owner, query):
        """Find conversations across the complete saved text, scoped to one identity.

        Parameters are literal substrings, including SQL wildcard characters.
        Return one newest matching preview per peer, with a bounded result count.
        """
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 256:
            raise ValueError("Enter a search term of up to 256 characters")
        folded = query.strip().casefold()
        matches = []
        peers = set()
        with self.lock:
            rows = self.db.execute(
                "SELECT m.id,m.peer,m.direction,m.content,m.timestamp,m.status "
                "FROM messages m LEFT JOIN peer_names p ON p.peer=m.peer "
                "WHERE m.owner=? AND m.direction IN ('in','out') AND "
                "(instr(cixnet_casefold(m.content),?)>0 OR instr(cixnet_casefold(m.peer),?)>0 "
                "OR instr(cixnet_casefold(p.name),?)>0) ORDER BY m.timestamp DESC",
                (owner, folded, folded, folded),
            )
            for row in rows:
                if row[1] in peers:
                    continue
                peers.add(row[1])
                matches.append(
                    dict(
                        zip(
                            (
                                "id",
                                "peer",
                                "direction",
                                "content",
                                "timestamp",
                                "status",
                            ),
                            row,
                        )
                    )
                )
                if len(matches) == 200:
                    break
        return matches

    def message_counts(self):
        """Show users which local identity owns each saved history."""
        with self.lock:
            return dict(
                self.db.execute(
                    "SELECT owner,count(*) FROM messages WHERE direction IN ('in','out') GROUP BY owner"
                ).fetchall()
            )

    def remember_peer_names(self, announces):
        """Keep known public names when a service restart clears live announces.

        Addresses remain the identifiers; names are unverified display metadata.
        Avoid rewriting the database during every unchanged polling request.
        """
        with self.lock:
            changed = False
            for item in announces:
                peer, name = item.get("address"), item.get("display_name")
                if (
                    item.get("kind") == "lxmf"
                    and isinstance(name, str)
                    and name
                    and self.peer_names.get(peer) != name
                ):
                    self.db.execute(
                        """
                        INSERT INTO peer_names VALUES (?, ?)
                        ON CONFLICT(peer) DO UPDATE SET name = excluded.name
                        """,
                        (peer, name),
                    )
                    self.peer_names[peer] = name
                    changed = True
            if changed:
                self.db.commit()

    def names(self, owner):
        """Return saved public peer names appearing in this identity's history."""
        with self.lock:
            return dict(
                self.db.execute(
                    """
                    SELECT DISTINCT peer_names.peer, peer_names.name
                    FROM peer_names
                    JOIN messages ON messages.peer = peer_names.peer
                    WHERE messages.owner = ?
                    """,
                    (owner,),
                ).fetchall()
            )

    def attachment(self, owner, message, position):
        """Exact owner/message lookup; filenames never select storage paths."""
        if not isinstance(message, str) or type(position) is not int:
            raise ValueError("Invalid attachment reference")
        with self.lock:
            row = self.db.execute(
                "SELECT name,data,image FROM attachments WHERE owner=? AND message=? AND position=?",
                (owner, message, position),
            ).fetchone()
        if row is None:
            raise ValueError("Attachment not found for this identity")
        return row

    def appearances(self, owner):
        """Return stored icon and color metadata for this identity's peers."""
        with self.lock:
            rows = self.db.execute(
                "SELECT peer,appearance FROM appearances WHERE owner=?", (owner,)
            ).fetchall()
        return {peer: json.loads(value) for peer, value in rows}
