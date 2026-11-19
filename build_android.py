"""Stage shared client sources and build an Android debug APK with local SDK tools."""

import argparse
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_support import check_dependencies


def dependency_root(module, override=None):
    """Find installed dependencies or an explicitly supplied source checkout."""
    if override:
        return Path(override)
    spec = importlib.util.find_spec(module)
    if spec and spec.origin:
        return Path(spec.origin).parent.parent
    raise ValueError(
        f"Install requirements.txt or supply --{module.lower()} source path"
    )


def copy_notice(source, distribution, target, fallback=None):
    for candidate in (source / "LICENSE", source.parent / "LICENSE"):
        if candidate.is_file():
            shutil.copy2(candidate, target)
            return
    installed = importlib.metadata.distribution(distribution)
    for entry in installed.files or []:
        if entry.name.lower() in ("license", "license.txt", "license.md"):
            shutil.copy2(installed.locate_file(entry), target)
            return
    # The pinned RNS/LXMF wheels omit standalone license files. Keep the
    # upstream texts already bundled with the client's About page.
    if fallback and fallback.is_file():
        shutil.copy2(fallback, target)
        return
    raise ValueError(f"Missing license for {distribution}")


def stage(root, reticulum, lxmf, retdns=None, nomadpl=None):
    """Copy only build inputs; original upstream trees stay unchanged."""
    project = root / "android"
    generated = project / "generated"
    python = generated / "python"
    python.mkdir(parents=True, exist_ok=True)
    client = python / "cixnet"
    client.mkdir(exist_ok=True)
    for source in root.glob("*.py"):
        if source.name != "desktop.py" and not source.name.startswith("build_"):
            shutil.copy2(source, client / source.name)
    (client / "__init__.py").touch()
    sources = {
        "RNS": reticulum / "RNS",
        "LXMF": lxmf / "LXMF",
        "retdns": dependency_root("retdns", retdns) / "retdns",
        "nomadpl": dependency_root("nomadpl", nomadpl) / "nomadpl",
    }
    for name, source in sources.items():
        destination = python / name
        if not destination.resolve().is_relative_to(python.resolve()):
            raise ValueError("Generated dependency path escaped the staging directory")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    # Android owns service shutdown. CPython signal handlers cannot be installed
    # by a Java service worker. Keep native desktop behavior unchanged.
    for relative in ("RNS/Reticulum.py", "LXMF/LXMRouter.py"):
        target = python / relative
        lines = target.read_text(encoding="utf-8").splitlines()
        changed = 0
        for index, line in enumerate(lines):
            if line.strip().startswith("signal.signal("):
                indent = line[: len(line) - len(line.lstrip())]
                lines[index] = (
                    indent
                    + "if threading.current_thread() is threading.main_thread(): "
                    + line.strip()
                )
                changed += 1
        if changed != 2:
            raise RuntimeError(
                "Review upstream signal handler changes before building Android"
            )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assets = generated / "assets"
    shutil.copytree(root / "ui", assets / "ui", dirs_exist_ok=True)
    licenses = assets / "licenses"
    licenses.mkdir(exist_ok=True)
    for name, source in [
        ("ciXnet", root),
        ("Reticulum", reticulum),
        ("LXMF", lxmf),
        ("RetDNS", sources["retdns"].parent),
        ("NomadPL", sources["nomadpl"].parent),
    ]:
        distribution = {
            "Reticulum": "rns",
            "LXMF": "lxmf",
            "RetDNS": "retdns",
            "NomadPL": "nomadpl",
        }.get(name, name)
        notice = {"Reticulum": "reticulum.txt", "LXMF": "lxmf.txt"}.get(name)
        copy_notice(
            source,
            distribution,
            licenses / (name + "-LICENSE.txt"),
            root / "ui/licenses" / notice if notice else None,
        )
    shutil.copy2(root / "THIRD_PARTY_NOTICES.md", licenses)
    return project


def main():
    root = Path(__file__).resolve().parent
    tools = root.parents[1] / "work" / "android-tools"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=tools / "sdk")
    parser.add_argument(
        "--jdk", type=Path, default=next((tools / "jdk").glob("jdk-*"), tools / "jdk")
    )
    parser.add_argument(
        "--gradle", type=Path, default=tools / "gradle-8.9" / "bin" / "gradle.bat"
    )
    parser.add_argument("--reticulum", type=Path)
    parser.add_argument("--lxmf", type=Path)
    parser.add_argument("--retdns", type=Path)
    parser.add_argument("--nomadpl", type=Path)
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()
    check_dependencies(
        name
        for name in ("rns", "lxmf", "retdns", "nomadpl")
        if getattr(args, "reticulum" if name == "rns" else name)
    )
    project = stage(
        root,
        dependency_root("RNS", args.reticulum),
        dependency_root("LXMF", args.lxmf),
        args.retdns,
        args.nomadpl,
    )
    if args.stage_only:
        return
    keystore = project / "generated" / "debug.keystore"
    if not keystore.exists():
        subprocess.run(
            [
                str(
                    args.jdk / "bin" / ("keytool.exe" if os.name == "nt" else "keytool")
                ),
                "-genkeypair",
                "-keystore",
                str(keystore),
                "-storepass",
                "android",
                "-alias",
                "androiddebugkey",
                "-keypass",
                "android",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-dname",
                "CN=ciXnet Debug",
            ],
            check=True,
        )
    environment = dict(
        os.environ,
        JAVA_HOME=str(args.jdk.resolve()),
        ANDROID_HOME=str(args.sdk.resolve()),
        GRADLE_USER_HOME=str(tools / "gradle-cache"),
    )
    subprocess.run(
        [
            str(args.gradle.resolve()),
            "--no-daemon",
            "--console=plain",
            "-PbuildPython=" + sys.executable,
            "assembleDebug",
        ],
        cwd=project,
        env=environment,
        check=True,
    )
    source = project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    target = root.parent / "cixnet-android"
    target.mkdir(exist_ok=True)
    shutil.copy2(source, target / "ciXnet-debug.apk")
    print("APK:", target / "ciXnet-debug.apk")


if __name__ == "__main__":
    main()
