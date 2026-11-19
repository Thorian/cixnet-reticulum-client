"""Attachment boundaries and standard LXMF wire formats."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_core  # noqa: F401 - configures the supplied dependency sources.

import LXMF  # isort: skip - test_core adds the external dependency directories.

import attachments


class AttachmentTests(unittest.TestCase):
    def test_names_and_active_content(self):
        """Treat filenames as display metadata and refuse unsafe attachment content."""
        self.assertEqual(attachments.safe_name("../../secret.txt"), "secret.txt")
        self.assertEqual(attachments.safe_name("C:\\folder\\name\r\n.txt"), "name.txt")
        item = attachments.validate(
            [{"name": "page.svg", "data": b"<svg onload='run()'/>", "image": True}]
        )[0]
        self.assertFalse(item["image"])
        self.assertIsNone(attachments.image_type(item["data"]))

    def test_limits_and_malformed_fields(self):
        """
        Enforce attachment limits before accepting malformed or excessive payloads.
        """
        for upload in ([{"name": "x", "data": "not base64!"}], [{}], "invalid"):
            with self.assertRaises(ValueError):
                attachments.from_upload(upload)
        with self.assertRaises(ValueError):
            attachments.validate(
                [{"name": "x", "data": b"x" * (attachments.MAX_BYTES + 1)}]
            )
        with self.assertRaises(ValueError):
            attachments.validate([{"name": "x", "data": b""}] * 9)
        self.assertEqual(
            attachments.from_fields(
                {
                    LXMF.FIELD_IMAGE: ["png", 123],
                    LXMF.FIELD_FILE_ATTACHMENTS: [None, [123, b"x"]],
                }
            ),
            [],
        )

    def test_standard_file_and_image_fields(self):
        """Round-trip supported attachments through the standard LXMF field layout."""
        data = b"\x89PNG\r\n\x1a\nimage fixture"
        original = attachments.validate(
            [
                {"name": "file.bin", "data": b"\x00\xff"},
                {"name": "photo.png", "data": data, "image": True},
            ]
        )
        fields = attachments.to_fields(original)
        self.assertEqual(
            fields[LXMF.FIELD_FILE_ATTACHMENTS], [["file.bin", b"\x00\xff"]]
        )
        self.assertEqual(fields[LXMF.FIELD_IMAGE], ["png", data])
        received = attachments.from_fields(fields)
        self.assertEqual([item["data"] for item in received], [data, b"\x00\xff"])
        self.assertEqual(
            attachments.from_fields({LXMF.FIELD_IMAGE: data})[0]["data"], data
        )
