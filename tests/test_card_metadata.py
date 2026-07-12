from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.card_metadata import CardMetadataStore, normalize_tags


class CardMetadataTests(unittest.TestCase):
    def test_normalize_tags_dedupes_and_strips_hash(self):
        self.assertEqual(
            normalize_tags("#常用, 常用，角色 ;  #石头"),
            ["常用", "角色", "石头"],
        )

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CardMetadataStore(Path(tmp) / "metadata.sqlite")
            store.set("abc", ["常用", "角色"], "这套已经看过")
            self.assertEqual(store.get("abc"), {"tags": ["常用", "角色"], "note": "这套已经看过"})
            store.set("abc", [], "")
            self.assertEqual(store.get("abc"), {"tags": [], "note": ""})


if __name__ == "__main__":
    unittest.main(verbosity=2)
