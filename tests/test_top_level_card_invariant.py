"""Regression: every first-level resource folder must have a card."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.classifier import build_cards
from resource_workbench.scanner import ScanConfig, scan_input


class TopLevelCardInvariantTests(unittest.TestCase):
    def test_nineteen_first_level_folders_produce_nineteen_cards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {f"resource-{index:02d}" for index in range(1, 20)}
            for index, name in enumerate(sorted(expected), start=1):
                folder = root / name
                folder.mkdir()
                # Keep one directory empty.  A first-level folder is still a
                # resource boundary and must not disappear silently.
                if index < 19:
                    (folder / "asset.zip").write_bytes(b"not-a-real-archive")

            scan = scan_input(root, config=ScanConfig(inspect_archives=False))
            cards = build_cards(scan)

            self.assertEqual(scan["top_level_directory_count"], 19)
            self.assertEqual(scan["top_level_card_count"], 19)
            self.assertEqual(scan["missing_top_level_directories"], [])
            self.assertEqual(len(cards), 19)
            self.assertEqual({card["source_top_level"] for card in cards}, expected)

    def test_snapshot_recovers_group_missing_after_child_read_failure(self):
        names = [f"folder-{index:02d}" for index in range(1, 20)]
        groups = {
            name: {
                "absolute_path": rf"X:\batch\{name}",
                "total_files": 1,
                "total_dirs": 1,
                "total_bytes": 10,
                "buckets": {"archive": 1},
                "extensions": {".zip": 1},
                "archives": [],
            }
            for name in names[:-1]
        }
        scan = {
            "input_path": r"X:\batch",
            "kind": "directory",
            "resource_root_depth": None,
            "groups": groups,
            "warnings": [],
            "top_level_directories": [
                {"name": name, "path": rf"X:\batch\{name}"} for name in names
            ],
            "top_level_directory_count": 19,
        }

        cards = build_cards(scan)

        self.assertEqual(len(cards), 19)
        self.assertEqual(scan["top_level_card_count"], 19)
        self.assertEqual(scan["missing_top_level_directories"], [])
        recovered = next(card for card in cards if card["source_top_level"] == names[-1])
        self.assertTrue(recovered["recovered_card"])
        self.assertEqual(recovered["source_path"], rf"X:\batch\{names[-1]}")

    def test_explicit_root_grouping_remains_one_card(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(19):
                folder = root / f"resource-{index:02d}"
                folder.mkdir()
                (folder / "readme.txt").write_text("asset", encoding="utf-8")

            scan = scan_input(root, config=ScanConfig(resource_root_depth=0))
            cards = build_cards(scan)

            self.assertEqual(len(cards), 1)
            self.assertFalse(scan["top_level_card_invariant_applied"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
