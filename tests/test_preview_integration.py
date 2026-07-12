"""端到端：扫描真实临时目录 -> build_cards -> 校验预览源选对。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import classifier as clf
from resource_workbench.scanner import ScanConfig, scan_input


def _png(path: Path, size: int = 2000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * size)


class PreviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "待整理"
        asset = self.root / "JapanAlley"
        # 根层封面 + 渲染图，外加一堆贴图通道（应被避开）
        _png(asset / "cover.jpg", 1500)
        _png(asset / "scene_render.png", 3000)
        for tex in ["wall_normal", "wall_basecolor", "wall_roughness", "ground_ao", "wall_height"]:
            _png(asset / "textures" / f"{tex}.png", 9000)  # 贴图更大，但不能被选
        (asset / "model.fbx").write_bytes(b"fbx" * 500)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_picks_cover_not_texture(self):
        scan = scan_input(self.root, config=ScanConfig(resource_root_depth=1, inspect_archives=False))
        cards = build = clf.build_cards(scan, z_root=None)
        self.assertTrue(cards)
        card = next((c for c in cards if "JapanAlley" in (c.get("name") or "")), cards[0])
        src = card.get("preview_source") or {}
        self.assertEqual(src.get("kind"), "file")
        chosen = Path(src.get("path", "")).name.lower()
        self.assertIn(chosen, {"cover.jpg", "scene_render.png"},
                      f"应选根层封面/渲染图，却选了 {chosen}")
        self.assertNotIn("textures", str(src.get("path", "")).replace("\\", "/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
