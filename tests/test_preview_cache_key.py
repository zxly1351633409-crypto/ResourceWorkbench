from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.preview import _source_key, prepare_preview_image


class PreviewCacheKeyTests(unittest.TestCase):
    def test_key_changes_when_same_path_size_or_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "preview.png"
            source.write_bytes(b"first")
            card_source = {"kind": "file", "path": str(source)}
            first = _source_key(card_source)

            source.write_bytes(b"a-different-size")
            second = _source_key(card_source)
            self.assertNotEqual(first, second)

            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            third = _source_key(card_source)
            self.assertNotEqual(second, third)

    def test_replaced_image_same_path_generates_new_cached_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            cache = root / "cache"
            card = {"preview_source": {"kind": "file", "path": str(source)}}

            Image.new("RGB", (40, 20), (255, 0, 0)).save(source)
            first = prepare_preview_image(card, cache, size=(40, 20), preserve_aspect=True)
            self.assertTrue(first["ok"], first)

            old_stat = source.stat()
            Image.new("RGB", (40, 20), (0, 0, 255)).save(source)
            os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000))
            second = prepare_preview_image(card, cache, size=(40, 20), preserve_aspect=True)
            self.assertTrue(second["ok"], second)
            self.assertNotEqual(first["path"], second["path"])

            with Image.open(second["path"]) as image:
                self.assertEqual(image.convert("RGB").getpixel((10, 10)), (0, 0, 255))

    def test_missing_source_stat_falls_back_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = {"kind": "file", "path": str(Path(tmp) / "missing.png")}
            self.assertEqual(_source_key(source), _source_key(source))


if __name__ == "__main__":
    unittest.main(verbosity=2)
