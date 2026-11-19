"""Search old text without leaking another identity or interpreting SQL syntax."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_core  # noqa: F401 - local Reticulum dependency paths

from messaging import Messaging


class SearchTests(unittest.TestCase):
    def test_old_messages_unicode_literal_input_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Messaging(Path(directory))
            try:
                app.store(
                    "old",
                    "owner",
                    "peer",
                    "in",
                    "Straße rendezvous 100%_",
                    "received",
                    files=[{"name": "note.txt", "data": b"details", "image": False}],
                )
                app.db.execute("UPDATE messages SET timestamp=1 WHERE id='old'")
                for number in range(1005):
                    app.db.execute(
                        "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                        (
                            str(number),
                            "owner",
                            "other-peer",
                            "in",
                            "unrelated",
                            number + 10,
                            "received",
                        ),
                    )
                app.store(
                    "hidden",
                    "other-owner",
                    "peer",
                    "in",
                    "rendezvous secret",
                    "received",
                )
                app.db.commit()
                self.assertNotIn("old", [x["id"] for x in app.history("owner")])
                self.assertEqual(
                    [x["id"] for x in app.search("owner", "STRASSE")], ["old"]
                )
                self.assertEqual(
                    [x["id"] for x in app.search("owner", "100%_")], ["old"]
                )
                self.assertEqual(app.search("owner", "' OR 1=1 --"), [])
                self.assertEqual(
                    [x["id"] for x in app.search("owner", "rendezvous")], ["old"]
                )
                context = app.history("owner", around="old")
                self.assertEqual(context[0]["id"], "old")
                self.assertEqual(context[0]["attachments"][0]["name"], "note.txt")
                with self.assertRaises(ValueError):
                    app.history("other-owner", around="old")
                for query in ["", " ", None, "x" * 257]:
                    with self.subTest(query=query), self.assertRaises(ValueError):
                        app.search("owner", query)
            finally:
                app.db.close()

    def test_one_newest_preview_per_conversation_and_saved_names(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Messaging(Path(directory))
            try:
                app.store("one", "owner", "peer", "in", "find this", "received")
                app.store("two", "owner", "peer", "out", "find this too", "delivered")
                # Windows clocks can give adjacent inserts the same timestamp.
                # This fixture tests newest-message selection, not tie ordering.
                app.db.execute("UPDATE messages SET timestamp=1 WHERE id='one'")
                app.db.execute("UPDATE messages SET timestamp=2 WHERE id='two'")
                app.db.commit()
                app.remember_peer_names(
                    [{"address": "peer", "kind": "lxmf", "display_name": "Thorian"}]
                )
                self.assertEqual(
                    [x["id"] for x in app.search("owner", "find")], ["two"]
                )
                self.assertEqual(
                    [x["id"] for x in app.search("owner", "THORIAN")], ["two"]
                )
            finally:
                app.db.close()
