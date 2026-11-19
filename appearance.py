"""Validate the LXMF icon-appearance wire format independently of any client UI."""

import json
import os
from pathlib import Path

# Android copies UI assets into private storage before starting the receiver.
UI_ROOT = Path(os.environ.get("CIXNET_UI_ROOT", Path(__file__).parent / "ui"))
ICONS = json.loads((UI_ROOT / "vendor/mdi/icons.json").read_text(encoding="utf-8"))
PALETTE = {
    "green": ("70e7a3", "2e503c"),
    "teal": ("9de9de", "204d49"),
    "blue": ("b4d5ff", "254566"),
    "amber": ("ffdc9b", "574326"),
    "purple": ("e1bdff", "49335f"),
    "rose": ("ffbfd9", "60364b"),
}


def encode(profile):
    """Encode the chosen icon and RGB colors in LXMF's appearance field."""
    icon = profile.get("icon", "account")
    if icon not in ICONS:
        icon = "account"
    fg, bg = PALETTE.get(profile.get("color"), PALETTE["green"])
    return [icon, bytes.fromhex(fg), bytes.fromhex(bg)]


def decode(value):
    """Accept only the supported icon and fixed-size RGB appearance format."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    icon, fg, bg = value
    if not isinstance(icon, str) or icon not in ICONS:
        return None
    if (
        not isinstance(fg, bytes)
        or not isinstance(bg, bytes)
        or len(fg) != 3
        or len(bg) != 3
    ):
        return None
    return {"icon": icon, "foreground": fg.hex(), "background": bg.hex()}
