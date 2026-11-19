"""Compile an operator-fetched RMAP snapshot into a small static JSON directory.

Run on ciXnet infrastructure only; clients never fetch RMAP. Redistribution
permission must be settled before publishing. Parsing does not execute JavaScript.
"""

import argparse
import calendar
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from stations import MAX_RECORDS, key, normalise  # noqa: E402


def month_before(timestamp):
    date = datetime.fromtimestamp(timestamp, timezone.utc)
    year, month = (
        (date.year - 1, 12) if date.month == 1 else (date.year, date.month - 1)
    )
    return date.replace(
        year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1])
    ).timestamp()


def units(value, unit):
    if type(value) in (int, float):
        return value
    match = re.fullmatch(r"([0-9.]+)\s*(Hz|kHz|MHz)", value or "")
    if not match:
        raise ValueError(f"Invalid {unit}")
    return float(match[1]) * {"Hz": 1, "kHz": 1000, "MHz": 1000000}[match[2]]


def compile_list(html, now=None):
    now = time.time() if now is None else now
    if len(html.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("Source page exceeds 16 MiB")
    marker = re.search(r"const\s+allNodes\s*=\s*", html)
    if not marker:
        raise ValueError("RMAP data format changed; keep the last published list")
    rows, _ = json.JSONDecoder().raw_decode(html[marker.end() :])
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("Unexpected RMAP record count")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("iface_type") != "RNodeInterface":
            continue
        try:
            first, last = row["first_seen_ts"], row["last_seen_ts"]
            if not 0 <= first < month_before(now) or not now - 86400 < last <= now:
                continue
            item = normalise(
                dict(
                    identity=row.get("transport_id") or row["hash"],
                    name=row["display_name"],
                    latitude=row.get("lat"),
                    longitude=row.get("lon"),
                    frequency=units(row.get("frequency"), "frequency"),
                    bandwidth=units(row.get("bandwidth"), "bandwidth"),
                    sf=row.get("spreading_factor"),
                    cr=row.get("coding_rate"),
                    first_seen=first,
                    last_seen=last,
                )
            )
            previous = result.get(key(item))
            if not previous or item["last_seen"] > previous["last_seen"]:
                result[key(item)] = item
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    if not result or len(result) > MAX_RECORDS:
        raise ValueError("Empty or oversized result; keep the last published list")
    return {
        "version": 1,
        "compiled_at": now,
        "source": "https://rmap.world/nodes.php",
        "stations": sorted(result.values(), key=key),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="RMAP HTML fetched by the operator")
    parser.add_argument("output", type=Path, help="Static stations-v1.json output")
    args = parser.parse_args()
    result = compile_list(args.snapshot.read_text(encoding="utf-8"))
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    temporary.replace(args.output)
    print(f"Compiled {len(result['stations'])} stations")


if __name__ == "__main__":
    main()
