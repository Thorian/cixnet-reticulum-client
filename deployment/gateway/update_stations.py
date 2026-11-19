"""Weekly operator-side fetch. Deploy only after RMAP redistribution is agreed."""

import argparse
import json
import urllib.request
from pathlib import Path

from compile_stations import compile_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    request = urllib.request.Request(
        "https://rmap.world/nodes.php",
        headers={"User-Agent": "ciXnet-station-compiler/1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Source exceeds 16 MiB; keeping the existing list")
    result = compile_list(data.decode("utf-8"))
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
