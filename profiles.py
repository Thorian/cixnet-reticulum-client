"""Local identity metadata, private-key files, and validated preferences.

Profile edits never regenerate keys. Keep metadata and cryptographic identity
separate so a nickname or avatar change cannot change a messaging address.
"""

import json
import os
import threading
from pathlib import Path

import RNS

from appearance import ICONS, PALETTE
from interface_config import validate_interfaces


def validate_name(value, label="Nickname"):
    """Reject empty/oversized names and hidden control characters."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 60:
        raise ValueError(f"{label} must contain 1–60 characters")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} cannot contain control characters")
    return value.strip()


class ProfileStore:
    def __init__(self, directory):
        """Open the local profile directory and restore its saved metadata."""
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "profiles.json"
        self.lock = threading.RLock()

    def read(self):
        """Return metadata only; private bytes have an explicit export method."""
        with self.lock:
            if self.path.exists():
                state = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                state = {
                    "profiles": [],
                    "settings": {
                        "media": "auto",
                        "localDiscovery": True,
                        "fallback": True,
                        "interfaces": [],
                        "propagationServers": ["49ec09143c134d6bb5d8b522c4cefa37"],
                    },
                }
            # Migrate early prototype profiles without replacing their key files.
            state["settings"].setdefault("fallback", True)
            state["settings"].setdefault("fallbackHost", "gw.cixnet.org")
            state["settings"].setdefault("fallbackPort", 4242)
            state["settings"].setdefault("announceMinutes", 15)
            state["settings"].setdefault("propagationServers", [])
            state["settings"].setdefault("deliveryMode", "auto")
            state["settings"].setdefault("mailboxCheckMinutes", 5)
            for profile in state["profiles"]:
                profile.setdefault("display_name", profile["nickname"])
                profile.setdefault("color", "green")
                profile.setdefault("icon", "account")
            return state

    def _save(self, state):
        """Atomic replacement avoids leaving a half-written JSON file."""
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    @staticmethod
    def _find(state, identity_id):
        """Locate an existing profile or reject an unknown identity reference."""
        for profile in state["profiles"]:
            if profile["id"] == identity_id:
                return profile
        raise ValueError("Identity not found on this device")

    def get(self, identity_id):
        """Return the selected profile after checking that it exists."""
        return self._find(self.read(), identity_id)

    def create(self, nickname, private_bytes=None):
        """Create a persistent identity and save its initial profile metadata."""
        nickname = validate_name(nickname)
        identity = RNS.Identity(create_keys=private_bytes is None)
        if private_bytes is not None:
            if len(private_bytes) != 64 or not identity.load_private_key(private_bytes):
                raise ValueError("Choose a raw 64-byte Reticulum private identity file")
        identity_id = identity.hash.hex()
        with self.lock:
            state = self.read()
            if any(profile["id"] == identity_id for profile in state["profiles"]):
                raise ValueError("This identity is already on this device")
            key_path = self.directory / f"{identity_id}.identity"
            if not identity.to_file(str(key_path)):
                raise OSError("Could not save identity")
            os.chmod(key_path, 0o600)
            profile = {
                "id": identity_id,
                "nickname": nickname,
                "display_name": nickname,
                "color": "green",
                "icon": "account",
            }
            state["profiles"].append(profile)
            self._save(state)
            return profile

    def update(self, identity_id, fields):
        """Change profile metadata without replacing the identity's private key."""
        nickname = validate_name(fields.get("nickname"))
        display_name = validate_name(fields.get("display_name"), "Display name")
        color = fields.get("color", "green")
        icon = fields.get("icon", "account")
        if not isinstance(color, str) or color not in PALETTE:
            raise ValueError("Choose an available avatar color")
        if not isinstance(icon, str) or icon not in ICONS:
            raise ValueError("Choose an available Material Design icon")
        with self.lock:
            state = self.read()
            profile = self._find(state, identity_id)
            profile.update(
                nickname=nickname, display_name=display_name, color=color, icon=icon
            )
            self._save(state)
            return profile

    def rename(self, identity_id, nickname):
        """Retain the early API, but keep public display names independent."""
        profile = self.get(identity_id)
        return self.update(identity_id, {**profile, "nickname": nickname})

    def export(self, identity_id):
        # Resolve a known profile first: never build a path from arbitrary input.
        """Return the selected identity's private-key file for explicit backup."""
        profile = self.get(identity_id)
        return (self.directory / f"{profile['id']}.identity").read_bytes()

    def save_settings(self, fields):
        """Validate settings as a whole before persisting any changes."""
        servers = fields.get("propagationServers", [])
        if (
            not isinstance(servers, list)
            or len(servers) > 8
            or any(
                not isinstance(value, str)
                or len(value) != 32
                or any(c not in "0123456789abcdefABCDEF" for c in value)
                for value in servers
            )
        ):
            raise ValueError("Use up to eight propagation destination hashes")
        servers = [value.lower() for value in servers]
        if len(set(servers)) != len(servers):
            raise ValueError("Propagation servers must be unique")
        mode = fields.get("deliveryMode", "auto")
        if mode not in ("auto", "direct", "relay"):
            raise ValueError("Invalid message delivery mode")
        if mode == "relay" and not servers:
            raise ValueError("Relay delivery needs at least one propagation server")
        interval = fields.get("announceMinutes", 15)
        mailbox_interval = fields.get("mailboxCheckMinutes", 5)
        if type(mailbox_interval) is not int or not 1 <= mailbox_interval <= 60:
            raise ValueError("Mailbox check interval must be 1–60 whole minutes")
        if type(interval) is not int or not 1 <= interval <= 1440:
            raise ValueError("Announce interval must be 1–1440 whole minutes")
        if fields.get("media") not in ("auto", "all", "text"):
            raise ValueError("Invalid media preference")
        interfaces = fields.get("interfaces", [])
        validate_interfaces(interfaces)
        for setting in ("localDiscovery", "fallback"):
            if not isinstance(fields.get(setting), bool):
                raise ValueError(f"{setting} must be true or false")
        from fallback import validate_gateway

        previous = self.read()["settings"]
        host, port = validate_gateway(
            fields.get("fallbackHost", previous["fallbackHost"]),
            fields.get("fallbackPort", previous["fallbackPort"]),
        )
        with self.lock:
            state = self.read()
            state["settings"] = {
                "announceMinutes": interval,
                "propagationServers": servers,
                "deliveryMode": mode,
                "mailboxCheckMinutes": mailbox_interval,
                "media": fields["media"],
                "interfaces": interfaces,
                "localDiscovery": fields["localDiscovery"],
                "fallback": fields["fallback"],
                "fallbackHost": host,
                "fallbackPort": port,
            }
            self._save(state)
