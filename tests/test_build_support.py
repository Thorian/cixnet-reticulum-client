"""A native package must not silently use stale companion libraries."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_support import RUNTIME_VERSIONS, check_dependencies


class BuildDependencyTests(unittest.TestCase):
    def test_stale_library_blocks_packaging(self):
        versions = {**RUNTIME_VERSIONS, "nomadpl": "0.2.0"}
        with patch("build_support.version", side_effect=versions.__getitem__):
            with self.assertRaisesRegex(RuntimeError, "nomadpl 0.3.0; found 0.2.0"):
                check_dependencies()

    def test_reviewed_source_overrides_can_replace_installed_libraries(self):
        versions = {**RUNTIME_VERSIONS, "nomadpl": "old", "retdns": "old"}
        with patch("build_support.version", side_effect=versions.__getitem__):
            check_dependencies(name for name in ("nomadpl", "retdns"))
