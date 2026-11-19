"""Validate attachment metadata and map it to standard LXMF fields.

Names are display metadata, never disk paths. Only recognized raster formats
get image previews; HTML, SVG, and arbitrary files remain downloads.
"""

import base64
import re

import LXMF

MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 8


def safe_name(value):
    """Reduce an attachment name to safe display metadata, never a storage path."""
    if not isinstance(value, str):
        raise ValueError("Attachment name must be text")
    name = re.split(r"[/\\]", value)[-1]
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)[:180].strip()
    return name if name not in ("", ".", "..") else "attachment.bin"


def image_type(data):
    """Identify supported raster image formats from their binary signatures."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def validate(items):
    """Check attachment counts, sizes and metadata before storing or sending them."""
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise ValueError(f"Choose at most {MAX_FILES} attachments")
    total = 0
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("data"), bytes):
            raise ValueError("Invalid attachment data")
        data = item["data"]
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("Attachments must total at most 8 MiB per message")
        result.append(
            {
                "name": safe_name(item.get("name")),
                "data": data,
                "image": bool(item.get("image")) and image_type(data) is not None,
            }
        )
    return result


def from_upload(items):
    """Decode and validate the browser's bounded attachment payload."""
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise ValueError("Choose at most 8 attachments")
    decoded = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str):
            raise ValueError("Invalid attachment upload")
        decoded.append({**item, "data": base64.b64decode(item["data"], validate=True)})
    return validate(decoded)


def to_fields(items):
    """Translate validated attachments into standard LXMF file and image fields."""
    fields = {}
    files = []
    for item in items:
        # LXMF has one dedicated image slot; further images travel as files.
        if item["image"] and LXMF.FIELD_IMAGE not in fields:
            fields[LXMF.FIELD_IMAGE] = [image_type(item["data"])[0], item["data"]]
        else:
            files.append([item["name"], item["data"]])
    if files:
        fields[LXMF.FIELD_FILE_ATTACHMENTS] = files
    return fields


def from_fields(fields):
    """Malformed remote metadata must not break text-message reception."""
    items = []
    files = fields.get(LXMF.FIELD_FILE_ATTACHMENTS, [])
    if isinstance(files, (list, tuple)):
        for entry in files[:MAX_FILES]:
            if (
                isinstance(entry, (list, tuple))
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], bytes)
            ):
                items.append(
                    {
                        "name": entry[0],
                        "data": entry[1],
                        "image": image_type(entry[1]) is not None,
                    }
                )
    image = fields.get(LXMF.FIELD_IMAGE)
    data = (
        image
        if isinstance(image, bytes)
        else image[1]
        if isinstance(image, (list, tuple)) and len(image) == 2
        else None
    )
    if isinstance(data, bytes):
        kind = image_type(data)
        items.insert(
            0,
            {
                "name": f"image.{kind[0]}" if kind else "image.bin",
                "data": data,
                "image": kind is not None,
            },
        )
    try:
        return validate(items)
    except ValueError:
        return []
