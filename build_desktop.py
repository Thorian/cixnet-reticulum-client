"""Build a portable desktop folder and retain dependency licenses and versions."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

from build_support import check_dependencies


def main():
    """Package the desktop launcher using the project's build specification."""
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    check_dependencies()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(args.dist.resolve()),
            "--workpath",
            str(args.work.resolve()),
            str(root / "desktop.spec"),
        ],
        check=True,
        cwd=root,
    )
    destination = args.dist.resolve() / "ciXnet"
    notices = destination / "licenses"
    notices.mkdir(exist_ok=True)
    inventory = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        inventory.append({"name": name, "version": distribution.version})
        for entry in distribution.files or []:
            if "license" in str(entry).lower() or "copying" in entry.name.lower():
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    target = notices / name / str(entry)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, notices / "Python-LICENSE.txt")
    shutil.copy2(root / "THIRD_PARTY_NOTICES.md", destination)
    shutil.copy2(root / "LICENSE", destination / "LICENSE")
    shutil.copy2(root / "DESKTOP.md", destination / "README.md")
    (destination / "dependency-versions.json").write_text(
        json.dumps(sorted(inventory, key=lambda item: item["name"].lower()), indent=2),
        encoding="utf-8",
    )
    manifest = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.json":
            manifest[str(path.relative_to(destination))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (destination / "SHA256SUMS.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Portable desktop build: {destination}")


if __name__ == "__main__":
    main()
