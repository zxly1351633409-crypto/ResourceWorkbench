"""重命名：净化、冲突安全、日志、撤销 单元测试。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import renamer


class SanitizeTests(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(renamer.sanitize_filename('a/b:c*d?"e'), "a_b_c_d__e")

    def test_collapse_and_trim(self):
        self.assertEqual(renamer.sanitize_filename("  科幻  机器人腿   "), "科幻 机器人腿")

    def test_trailing_dot_space(self):
        self.assertEqual(renamer.sanitize_filename("name. ."), "name")

    def test_maxlen(self):
        self.assertLessEqual(len(renamer.sanitize_filename("x" * 500)), 150)


class RenameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = renamer.RenameLog(self.root / "rename_log.sqlite")
        self.folder = self.root / "Sci_Fi Robot Leg"
        self.folder.mkdir()
        (self.folder / "a.fbx").write_text("x", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rename_and_undo(self):
        r = renamer.rename_folder(self.folder, "科幻机器人腿 Sci_Fi Robot Leg", self.log)
        self.assertTrue(r["ok"] and not r["skipped"], r)
        newp = Path(r["path"])
        self.assertTrue(newp.exists())
        self.assertFalse(self.folder.exists())
        self.assertTrue((newp / "a.fbx").exists())
        u = renamer.undo_rename(r["rename_id"], self.log)
        self.assertTrue(u["ok"], u)
        self.assertTrue(self.folder.exists())

    def test_skip_when_unchanged(self):
        r = renamer.rename_folder(self.folder, "Sci_Fi Robot Leg", self.log)
        self.assertTrue(r["ok"] and r["skipped"])

    def test_conflict_safe(self):
        (self.root / "科幻腿").mkdir()
        r = renamer.rename_folder(self.folder, "科幻腿", self.log)
        self.assertTrue(r["ok"])
        self.assertTrue(Path(r["path"]).name.startswith("科幻腿 (2)") or Path(r["path"]).name == "科幻腿 (2)")

    def test_missing_source(self):
        r = renamer.rename_folder(self.root / "nope", "x", self.log)
        self.assertFalse(r["ok"])

    def test_empty_name_skipped(self):
        r = renamer.rename_folder(self.folder, '???', self.log)
        # '???' -> '___' 实际是合法净化结果；用全非法+空格测真正为空
        r2 = renamer.rename_folder(self.folder, '   ', self.log)
        self.assertFalse(r2["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
