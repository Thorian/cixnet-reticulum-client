"""Reject stale runtime dependencies before producing native packages."""

from importlib.metadata import PackageNotFoundError, version

RUNTIME_VERSIONS = {
    "rns": "1.6.1",
    "lxmf": "1.3.1",
    "retdns": "0.2.1",
    "nomadpl": "0.3.0",
}


def check_dependencies(overrides=()):
    """Explicit Android source overrides are reviewed separately from installed wheels."""
    overrides = set(overrides)
    for package, expected in RUNTIME_VERSIONS.items():
        if package in overrides:
            continue
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            raise RuntimeError(
                f"Build requires {package} {expected}; found {actual}. "
                "Install requirements.txt in this build environment first."
            )
