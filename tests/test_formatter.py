"""统一显示格式（封面+工程）单元测试。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import formatter


class FormatterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.res = Path(self.tmp.name) / "RobotLeg"
        self.res.mkdir()
        (self.res / "cover.jpg").write_bytes(b"x" * 5000)        # 应作为封面留外层
        (self.res / "wall_normal.png").write_bytes(b"x" * 9000)  # 贴图，不应当封面
        (self.res / "leg.fbx").write_text("fbx", encoding="utf-8")
        (self.res / "leg.blend").write_text("blend", encoding="utf-8")
        sub = self.res / "textures"
        sub.mkdir()
        (sub / "diffuse.png").write_bytes(b"x" * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_picks_cover(self):
        plan = formatter.plan_cover_project(self.res)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["cover"], "cover.jpg")
        self.assertIn("leg.fbx", plan["move_items"])
        self.assertIn("wall_normal.png", plan["move_items"])
        self.assertIn("textures", plan["move_items"])
        self.assertNotIn("cover.jpg", plan["move_items"])

    def test_apply_and_structure(self):
        result = formatter.apply_cover_project(self.res)
        self.assertTrue(result["ok"] and not result.get("skipped"), result)
        # 封面仍在外层
        self.assertTrue((self.res / "cover.jpg").exists())
        # 其余进入“工程”
        proj = self.res / "工程"
        self.assertTrue(proj.is_dir())
        self.assertTrue((proj / "leg.fbx").exists())
        self.assertTrue((proj / "wall_normal.png").exists())
        self.assertTrue((proj / "textures" / "diffuse.png").exists())
        # 外层只剩封面 + 工程 + manifest
        top = sorted(p.name for p in self.res.iterdir())
        self.assertEqual(top, sorted(["cover.jpg", "工程", "_format_manifest.json"]))

    def test_undo_restores(self):
        formatter.apply_cover_project(self.res)
        undo = formatter.undo_cover_project(self.res)
        self.assertTrue(undo["ok"], undo)
        self.assertTrue((self.res / "leg.fbx").exists())
        self.assertTrue((self.res / "textures" / "diffuse.png").exists())
        self.assertFalse((self.res / "工程").exists())
        self.assertFalse((self.res / "_format_manifest.json").exists())

    def test_idempotent_already_organized(self):
        formatter.apply_cover_project(self.res)
        second = formatter.apply_cover_project(self.res)
        self.assertTrue(second["ok"])
        self.assertTrue(second.get("skipped"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
