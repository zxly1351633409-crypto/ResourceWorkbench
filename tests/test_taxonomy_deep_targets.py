"""Fine-grained model target recommendations must use real library categories."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.classifier import build_cards
from resource_workbench.file_types import normalized_ext, type_bucket
from resource_workbench.scanner import ScanConfig, scan_input
from resource_workbench.taxonomy import suggest_target_paths


class DeepModelTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        for relative in (
            "M 模型/F 废土/场景",
            "M 模型/F 废土/建筑",
            "M 模型/F 废土/物件",
            "M 模型/F 废土/载具/C 车",
            "M 模型/C 城市/建筑",
            "M 模型/S 室内/场景",
            "M 模型/X 现代/载具/Q 汽车",
            "M 模型/J 近现代/物件",
            "M 模型/Y 一战二战/W 物件",
            "M 模型/Y 遗迹/J 建筑",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _target(self, text: str) -> Path:
        suggestions = suggest_target_paths("model", text, self.root)
        self.assertTrue(suggestions)
        return Path(suggestions[0]["path"])

    def test_ruin_batch_maps_each_subject_to_existing_deep_category(self) -> None:
        cases = {
            "废墟二期 Metal Scrap Scan 16K": "M 模型/F 废土/物件",
            "废墟二期 SCANS Ukraine Floor Vol.1": "M 模型/F 废土/建筑",
            "废墟二期 SCANS Ukraine Interior Vol.1": "M 模型/F 废土/场景",
            "废墟二期 SCANS Ukraine Buildings Vol.5": "M 模型/F 废土/建筑",
            "废墟二期 SCANS Ukraine Cars Vol.3": "M 模型/F 废土/载具/C 车",
            "废墟二期 SCANS Ukraine Debris Vol.1": "M 模型/F 废土/物件",
            "废墟二期 SCANS Ukraine Facades Vol.1": "M 模型/F 废土/建筑",
            "废墟二期 SCANS Ukraine Military Vol.3": "M 模型/F 废土/载具",
            "废墟二期 SCANS Ukraine Military Props Vol.1": "M 模型/F 废土/物件",
            "废墟二期 SCANS Ukraine Supermarket Vol.2": "M 模型/F 废土/物件",
        }
        for text, relative in cases.items():
            with self.subTest(text=text):
                target = self._target(text)
                self.assertEqual(target, self.root / relative)
                self.assertTrue(target.is_dir())

    def test_subject_context_selects_real_non_ruin_categories(self) -> None:
        cases = {
            "Ukraine Buildings Vol.5": "M 模型/C 城市/建筑",
            "Ukraine Interior Vol.1": "M 模型/S 室内/场景",
            "Ukraine Cars Vol.3": "M 模型/X 现代/载具/Q 汽车",
            "Ukraine Military Props Vol.1": "M 模型/J 近现代/物件",
            "WW2 Military Props": "M 模型/Y 一战二战/W 物件",
            "Ancient Ruins Building Scan": "M 模型/Y 遗迹/J 建筑",
        }
        for text, relative in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._target(text), self.root / relative)

    def test_blender_backup_is_model_evidence(self) -> None:
        self.assertEqual(normalized_ext("CARS-set-03.blend1"), ".blend")
        self.assertEqual(type_bucket("CARS-set-03.blend2"), "model")

        batch = Path(self.temp.name) / "batch"
        asset = batch / "SCANS from Ukraine Cars Vol.3"
        asset.mkdir(parents=True)
        (asset / "CARS-set-03.blend1").write_bytes(b"blend backup")
        (asset / "preview.jpg").write_bytes(b"preview")
        scan = scan_input(batch, config=ScanConfig(inspect_archives=False))
        cards = build_cards(scan, z_root=self.root)
        self.assertEqual(cards[0]["suggested_type"], "model")


if __name__ == "__main__":
    unittest.main(verbosity=2)
