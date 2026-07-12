"""预览图选择评分单元测试。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import classifier as clf


class PreviewScoreTests(unittest.TestCase):
    def test_cover_beats_texture(self):
        self.assertGreater(
            clf._preview_name_score("cover.jpg"),
            clf._preview_name_score("wall_normal.jpg"),
        )

    def test_scene_render_beats_basecolor(self):
        self.assertGreater(
            clf._preview_name_score("street_scene_render.png"),
            clf._preview_name_score("street_basecolor.png"),
        )

    def test_texture_maps_negative(self):
        for tex in ["brick_normal.png", "metal_roughness.jpg", "wood_albedo.png",
                    "floor_ao.png", "x_displacement.png", "y_orm.png"]:
            self.assertLess(clf._preview_name_score(tex), 0, tex)

    def test_size_tiebreak(self):
        with tempfile.TemporaryDirectory() as d:
            small = Path(d) / "alley_aa.png"
            big = Path(d) / "alley_bb.png"
            small.write_bytes(b"x" * 100)
            big.write_bytes(b"x" * 50000)
            # 同名分（都不含关键词），应选更大的那张作为代表图
            chosen = clf._best_preview_path([str(small), str(big)])
            self.assertEqual(chosen, str(big))

    def test_good_hint_beats_size(self):
        with tempfile.TemporaryDirectory() as d:
            cover = Path(d) / "cover.png"
            huge_tex = Path(d) / "wall_normal.png"
            cover.write_bytes(b"x" * 100)
            huge_tex.write_bytes(b"x" * 90000)
            chosen = clf._best_preview_path([str(huge_tex), str(cover)])
            self.assertEqual(chosen, str(cover))


if __name__ == "__main__":
    unittest.main(verbosity=2)
