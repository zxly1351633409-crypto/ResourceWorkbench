from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import indexer
from resource_workbench.indexer import ResourceIndex, placeholder_cards_for_path, quick_cards_for_path


def _canonical_path(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


class LeafMediaIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "index.sqlite"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _cards(self, folder: Path) -> list[dict]:
        resource_index = ResourceIndex(self.db_path)
        count = resource_index.index_children(folder)
        cards = resource_index.load_child_cards(folder)
        self.assertEqual(count, len(cards))
        return cards

    def test_mov_leaf_files_are_indexed_with_video_previews(self) -> None:
        leaf = self.root / "无人机视频"
        leaf.mkdir()
        for index in range(3):
            (leaf / f"DJI_{index:04d}.mov").write_bytes(b"mov")

        with mock.patch.object(indexer, "_quick_row", side_effect=AssertionError("leaf files must not recurse")):
            cards = self._cards(leaf)

        self.assertEqual(len(cards), 3)
        for card in cards:
            self.assertFalse(card["is_directory"])
            self.assertEqual(card["media_type"], "video")
            self.assertEqual(card["preview_source"]["kind"], "video_file")
            self.assertEqual(Path(card["preview_source"]["path"]).suffix.lower(), ".mov")

    def test_png_leaf_files_are_indexed_with_image_previews(self) -> None:
        leaf = self.root / "整理图片"
        leaf.mkdir()
        for index in range(2):
            (leaf / f"render_{index}.png").write_bytes(b"png")

        cards = self._cards(leaf)

        self.assertEqual(len(cards), 2)
        self.assertEqual({card["media_type"] for card in cards}, {"image"})
        self.assertEqual({card["preview_source"]["kind"] for card in cards}, {"file"})

    def test_mixed_leaf_preserves_each_direct_file_media_type(self) -> None:
        leaf = self.root / "混合媒体"
        leaf.mkdir()
        (leaf / "cover.png").write_bytes(b"png")
        (leaf / "flythrough.mov").write_bytes(b"mov")
        (leaf / "notes.txt").write_text("notes", encoding="utf-8")

        cards = self._cards(leaf)
        by_name = {card["name"]: card for card in cards}

        self.assertEqual(set(by_name), {"cover.png", "flythrough.mov", "notes.txt"})
        self.assertEqual(by_name["cover.png"]["media_type"], "image")
        self.assertEqual(by_name["cover.png"]["preview_source"]["kind"], "file")
        self.assertEqual(by_name["flythrough.mov"]["media_type"], "video")
        self.assertEqual(by_name["flythrough.mov"]["preview_source"]["kind"], "video_file")
        self.assertEqual(by_name["notes.txt"]["media_type"], "document")
        self.assertIsNone(by_name["notes.txt"]["preview_source"])

    def test_windows_metadata_files_do_not_become_resource_cards(self) -> None:
        leaf = self.root / "整理图片"
        leaf.mkdir()
        (leaf / "render.png").write_bytes(b"png")
        (leaf / "Thumbs.db").write_bytes(b"cache")
        (leaf / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")

        cards = self._cards(leaf)

        self.assertEqual([card["name"] for card in cards], ["render.png"])

    def test_placeholders_and_quick_cards_expose_leaf_file_previews(self) -> None:
        leaf = self.root / "leaf"
        leaf.mkdir()
        image = leaf / "cover.png"
        video = leaf / "clip.mov"
        image.write_bytes(b"png")
        video.write_bytes(b"mov")

        for cards in (placeholder_cards_for_path(leaf), quick_cards_for_path(leaf)):
            by_name = {card["name"]: card for card in cards}
            self.assertEqual(by_name[image.name]["preview_source"]["kind"], "file")
            self.assertEqual(
                _canonical_path(by_name[image.name]["preview_source"]["path"]),
                _canonical_path(image),
            )
            self.assertEqual(by_name[video.name]["preview_source"]["kind"], "video_file")
            self.assertEqual(
                _canonical_path(by_name[video.name]["preview_source"]["path"]),
                _canonical_path(video),
            )

        direct = placeholder_cards_for_path(video)
        self.assertEqual(direct[0]["preview_source"]["kind"], "video_file")
        self.assertEqual(_canonical_path(direct[0]["preview_source"]["path"]), _canonical_path(video))

    def test_non_leaf_directory_keeps_folder_first_compatibility(self) -> None:
        parent = self.root / "category"
        child = parent / "asset"
        child.mkdir(parents=True)
        (parent / "loose.png").write_bytes(b"png")
        (child / "cover.png").write_bytes(b"png")

        cards = self._cards(parent)

        self.assertEqual([card["name"] for card in cards], ["asset"])
        self.assertTrue(cards[0]["is_directory"])
        self.assertEqual(cards[0]["media_type"], "image")


if __name__ == "__main__":
    unittest.main(verbosity=2)
