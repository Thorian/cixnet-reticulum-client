"""Offline radio candidates. Advertisements are never proof of direct reception."""

import hashlib
import json
import math
import sqlite3
import threading
import time
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10000


def number(value, low, high):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("Invalid station number")
    return value


def normalise(item):
    """Whitelist public fields; never retain advertised passphrases or raw configs."""
    if not isinstance(item, dict):
        raise ValueError("Invalid station record")
    identity = item.get("identity")
    if not isinstance(identity, str) or len(identity) != 32:
        raise ValueError("Invalid station identity")
    if len(bytes.fromhex(identity)) != 16:
        raise ValueError("Invalid station identity")
    name = item.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 160:
        raise ValueError("Invalid station name")
    result = {"identity": identity.lower(), "name": name}
    for field, low, high in (
        ("latitude", -90, 90),
        ("longitude", -180, 180),
        ("frequency", 100000000, 3000000000),
        ("bandwidth", 7800, 1625000),
        ("sf", 5, 12),
        ("cr", 5, 8),
    ):
        result[field] = number(item.get(field), low, high)
    for field in ("frequency", "bandwidth", "sf", "cr"):
        if int(result[field]) != result[field]:
            raise ValueError("Radio settings must be whole numbers")
        result[field] = int(result[field])
    result["first_seen"] = number(item.get("first_seen"), 0, time.time() + 300)
    result["last_seen"] = number(
        item.get("last_seen"), result["first_seen"], time.time() + 300
    )
    return result


def key(item):
    """Keep separate radios/profiles even when they share a transport identity."""
    values = [
        item[k] for k in ("identity", "name", "frequency", "bandwidth", "sf", "cr")
    ]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class Stations:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            str(Path(directory) / "stations.sqlite"), check_same_thread=False
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS stations (id TEXT, source TEXT, record TEXT, PRIMARY KEY(id,source))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS station_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.db.commit()
        self.refresh_lock = threading.Lock()
        self.refresh_status = {"phase": "idle", "error": None}

    def refresh(self):
        """Fetch only ciXnet's compiled HTTPS file, never the upstream directory."""
        if not self.refresh_lock.acquire(blocking=False):
            return dict(self.refresh_status)

        def fetch():
            import urllib.request

            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    raise ValueError("Station update redirects are not accepted")

            try:
                opener = urllib.request.build_opener(NoRedirect())
                with opener.open(
                    "https://gw.cixnet.org/stations-v1.json", timeout=30
                ) as response:
                    data = response.read(MAX_BYTES + 1)
                result = self.import_list(data)
                self.refresh_status = {"phase": "done", "error": None, **result}
            except Exception as error:
                self.refresh_status = {"phase": "error", "error": str(error)[:300]}
            finally:
                self.refresh_lock.release()

        self.refresh_status = {"phase": "loading", "error": None}
        threading.Thread(target=fetch, daemon=True).start()
        return dict(self.refresh_status)

    def learn(self, info):
        """Called by upstream's signature/stamp-validated discovery decoder."""
        if not info or info.get("type") != "RNodeInterface":
            return
        now = time.time()
        try:
            item = normalise(
                dict(
                    identity=info.get("transport_id"),
                    name=info.get("name"),
                    latitude=info.get("latitude"),
                    longitude=info.get("longitude"),
                    frequency=info.get("frequency"),
                    bandwidth=info.get("bandwidth"),
                    sf=info.get("sf"),
                    cr=info.get("cr"),
                    first_seen=now,
                    last_seen=now,
                )
            )
        except (ValueError, TypeError):
            return
        with self.lock:
            previous = self.db.execute(
                "SELECT record FROM stations WHERE id=? AND source='learned'",
                (key(item),),
            ).fetchone()
            if previous:
                item["first_seen"] = json.loads(previous[0])["first_seen"]
            self.db.execute(
                "INSERT OR REPLACE INTO stations VALUES (?,?,?)",
                (key(item), "learned", json.dumps(item)),
            )
            # Bound unsolicited network data, retaining the most recently heard.
            self.db.execute(
                "DELETE FROM stations WHERE source='learned' AND id NOT IN (SELECT id FROM stations WHERE source='learned' ORDER BY json_extract(record,'$.last_seen') DESC LIMIT ?)",
                (MAX_RECORDS,),
            )
            self.db.commit()

    def import_list(self, data):
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise ValueError("Station list exceeds 4 MiB")
        document = json.loads(data)
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("Unsupported station list")
        compiled = number(document.get("compiled_at"), 0, time.time() + 300)
        rows = document.get("stations")
        if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
            raise ValueError("Invalid station count")
        items = [normalise(item) for item in rows]
        if len({key(item) for item in items}) != len(items):
            raise ValueError("Duplicate stations in list")
        with self.lock:
            previous = self.db.execute(
                "SELECT value FROM station_meta WHERE key='compiled_at'"
            ).fetchone()
            if previous and compiled < float(previous[0]):
                raise ValueError("This station list is older than your saved list")
            with self.db:
                self.db.execute("DELETE FROM stations WHERE source='directory'")
                self.db.executemany(
                    "INSERT INTO stations VALUES (?,?,?)",
                    [(key(i), "directory", json.dumps(i)) for i in items],
                )
                self.db.execute(
                    "INSERT OR REPLACE INTO station_meta VALUES ('compiled_at',?)",
                    (str(compiled),),
                )
        return {"imported": len(items), "compiled_at": compiled}

    def list(self, latitude=None, longitude=None):
        """Rank candidates locally without storing the user's position."""
        if latitude is not None or longitude is not None:
            number(latitude, -90, 90)
            number(longitude, -180, 180)
        with self.lock:
            rows = self.db.execute("SELECT id,source,record FROM stations").fetchall()
            meta = self.db.execute(
                "SELECT value FROM station_meta WHERE key='compiled_at'"
            ).fetchone()
        merged = {}
        for ident, source, record in rows:
            item = json.loads(record)
            old = merged.get(ident)
            sources = (old["sources"] if old else []) + [source]
            if old and old["last_seen"] > item["last_seen"]:
                old["sources"] = sources
                continue
            merged[ident] = dict(item, sources=sources, reception="advertised")
        items = list(merged.values())
        if latitude is not None:
            for item in items:
                lat1, lat2 = map(math.radians, (latitude, item["latitude"]))
                delta = math.radians(item["longitude"] - longitude)
                a = (
                    math.sin((lat2 - lat1) / 2) ** 2
                    + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
                )
                item["distance_km"] = round(
                    6371 * 2 * math.asin(math.sqrt(min(1, a))), 1
                )
        items.sort(key=lambda i: (i.get("distance_km", 0), -i["last_seen"]))
        groups = {}
        for item in items:
            profile = tuple(item[k] for k in ("frequency", "bandwidth", "sf", "cr"))
            groups.setdefault(profile, []).append(item)
        return {
            "stations": items,
            "profiles": [
                {
                    "frequency": p[0],
                    "bandwidth": p[1],
                    "sf": p[2],
                    "cr": p[3],
                    "stations": len(v),
                }
                for p, v in groups.items()
            ],
            "compiled_at": float(meta[0]) if meta else None,
            "refresh": dict(self.refresh_status),
        }
