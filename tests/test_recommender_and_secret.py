"""目标文件夹推荐 + 本地密钥存储 单元测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import settings as settings_mod
from resource_workbench import target_recommender as tr


class RecommenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Z"
        # 构造一个近似真实资源库的树
        for rel in [
            r"M 模型/K 科幻/W 物件",
            r"M 模型/K 科幻/J 机甲",
            r"M 模型/K 科幻/Z 载具",
            r"M 模型/K 科幻/Q 枪支",
            r"M 模型/X 写实/R 人物",
            r"Z 照片/Z 自然/S 石头",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_hint_lists_siblings(self):
        card = {
            "name": "sci fi mech leg kitbash",
            "content_tags": ["科幻", "机甲"],
            "target_path_hints": [str(self.root / "M 模型" / "K 科幻" / "W 物件")],
        }
        res = tr.recommend_target_folders(card, self.root)
        self.assertTrue(res["ok"])
        # 命中三层，浏览起点应是 W 物件 的父级或自身；候选里应能看到机甲/物件等
        names = [c["name"] for c in res["candidates"]]
        self.assertTrue(any("物件" in n or "机甲" in n for n in names))
        # 完全命中已存在路径，不需要新建
        self.assertIsNone(res["suggested_new"])

    def test_existing_asset_children_are_not_offered_as_category_targets(self):
        category = self.root / "M 模型" / "K 科幻" / "W 物件"
        (category / "Old Crate Asset Pack Vol.01").mkdir()
        (category / "Industrial Panel Collection by Artist").mkdir()
        card = {
            "name": "New Sci Fi Props",
            "content_tags": ["科幻", "物件"],
            "target_path_hints": [str(category)],
        }
        res = tr.recommend_target_folders(card, self.root)
        names = [candidate["name"] for candidate in res["candidates"]]
        self.assertIn("W 物件", names)
        self.assertNotIn("Old Crate Asset Pack Vol.01", names)
        self.assertNotIn("Industrial Panel Collection by Artist", names)

    def test_missing_leaf_suggests_new(self):
        card = {
            "name": "robot",
            "content_tags": ["机器人"],
            "target_path_hints": [str(self.root / "M 模型" / "K 科幻" / "B 机器人")],
        }
        res = tr.recommend_target_folders(card, self.root)
        self.assertTrue(res["ok"])
        # B 机器人 不存在 -> 应给新建建议，且浏览起点回退到 K 科幻
        self.assertIsNotNone(res["suggested_new"])
        self.assertTrue(res["suggested_new"].endswith("B 机器人"))
        self.assertTrue(res["base"].endswith("K 科幻"))
        # 候选应包含 K 科幻 下的现有子目录
        names = [c["name"] for c in res["candidates"]]
        self.assertIn("J 机甲", names)

    def test_ranking_prefers_similar(self):
        card = {
            "name": "futuristic gun rifle ammo",
            "content_tags": ["枪支", "弹药"],
            "target_path_hints": [str(self.root / "M 模型" / "K 科幻")],
        }
        res = tr.recommend_target_folders(card, self.root)
        names = [c["name"] for c in res["candidates"]]
        # 枪支应排在机甲之前
        self.assertIn("Q 枪支", names)
        self.assertLess(names.index("Q 枪支"), names.index("J 机甲"))

    def test_english_robot_terms_match_chinese_mech_folder(self):
        card = {
            "name": "robot mechanical leg",
            "content_tags": [],
            "target_path_hints": [str(self.root / "M 模型" / "K 科幻" / "B 机器人")],
        }
        res = tr.recommend_target_folders(card, self.root)
        names = [c["name"] for c in res["candidates"]]
        self.assertIn("J 机甲", names)
        self.assertEqual(names[0], "J 机甲")

    def test_browse_subfolders(self):
        kids = tr.browse_subfolders(self.root / "M 模型", self.root, probe_children=True)
        names = [k["name"] for k in kids]
        self.assertIn("K 科幻", names)
        self.assertIn("X 写实", names)
        sci = [k for k in kids if k["name"] == "K 科幻"][0]
        self.assertTrue(sci["has_children"])

    def test_missing_root(self):
        res = tr.recommend_target_folders({}, Path(self.tmp.name) / "nope")
        self.assertFalse(res["ok"])


class SecretStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "workbench_data").mkdir()
        self.env_name = "DEEPSEEK_API_KEY_TEST_XYZ"
        os.environ.pop(self.env_name, None)

    def tearDown(self):
        os.environ.pop(self.env_name, None)
        self.tmp.cleanup()

    def _settings(self):
        s = settings_mod.load_settings(self.project)
        s["deepseek_api_key_env"] = self.env_name
        return s

    def test_no_key(self):
        s = self._settings()
        self.assertEqual(settings_mod.deepseek_api_key(s), "")
        self.assertEqual(settings_mod.deepseek_api_key_source(s), "none")

    def test_file_key(self):
        s = self._settings()
        settings_mod.save_deepseek_api_key(s, "sk-local-123")
        self.assertEqual(settings_mod.deepseek_api_key(s), "sk-local-123")
        self.assertEqual(settings_mod.deepseek_api_key_source(s), "file")
        # secret 文件确实写到了 workbench_data
        self.assertTrue((self.project / "workbench_data" / "secret.json").exists())

    def test_env_overrides_file(self):
        s = self._settings()
        settings_mod.save_deepseek_api_key(s, "sk-local-123")
        os.environ[self.env_name] = "sk-env-999"
        self.assertEqual(settings_mod.deepseek_api_key(s), "sk-env-999")
        self.assertEqual(settings_mod.deepseek_api_key_source(s), "env")

    def test_clear_key(self):
        s = self._settings()
        settings_mod.save_deepseek_api_key(s, "sk-local-123")
        settings_mod.save_deepseek_api_key(s, "")
        self.assertEqual(settings_mod.deepseek_api_key(s), "")

    def test_secret_not_in_settings_json(self):
        s = self._settings()
        settings_mod.save_deepseek_api_key(s, "sk-secret")
        settings_mod.save_settings(self.project, s)
        saved = (self.project / "workbench_data" / "settings.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-secret", saved)
        self.assertNotIn("_secret_file", saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
