"""115 路径镜像 + 凭证 + 未配置兜底 单元测试。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import settings as settings_mod
from resource_workbench import uploader_115 as up


class MirrorPathTests(unittest.TestCase):
    def test_relative(self):
        z = Path(r"/Z/整合")
        local = Path(r"/Z/整合/M 模型/K 科幻/W 物件/RobotLeg")
        self.assertEqual(up.mirror_relative_path(local, z), "M 模型/K 科幻/W 物件/RobotLeg")

    def test_remote_with_root(self):
        z = Path(r"/Z/整合")
        local = Path(r"/Z/整合/M 模型/K 科幻/RobotLeg")
        self.assertEqual(
            up.remote_target_path(local, z, remote_root="整合——资源管理"),
            "整合——资源管理/M 模型/K 科幻/RobotLeg",
        )

    def test_remote_no_root(self):
        z = Path(r"/Z/整合")
        local = Path(r"/Z/整合/C 材质/Brick")
        self.assertEqual(up.remote_target_path(local, z), "C 材质/Brick")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / "workbench_data").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_enabled(self):
        s = settings_mod.load_settings(self.project)
        u = up.Uploader115(s)
        self.assertFalse(u.is_configured())
        r = u.upload_folder(self.project, self.project, None)
        self.assertFalse(r["ok"])
        self.assertIn("启用", r["error"])

    def test_credentials_roundtrip(self):
        s = settings_mod.load_settings(self.project)
        s["enable_115"] = True
        s["p115_app_id"] = "app123"
        settings_mod.save_115_credentials(s, app_secret="secretXYZ", token="tok999")
        creds = settings_mod.get_115_credentials(s)
        self.assertEqual(creds["app_id"], "app123")
        self.assertEqual(creds["app_secret"], "secretXYZ")
        self.assertEqual(creds["token"], "tok999")
        u = up.Uploader115(s)
        self.assertTrue(u.is_configured())
        self.assertTrue(u.has_token())

    def test_configured_but_upload_placeholder(self):
        s = settings_mod.load_settings(self.project)
        s["enable_115"] = True
        s["p115_app_id"] = "app123"
        settings_mod.save_115_credentials(s, app_secret="secretXYZ", token="tok999")
        res = Path(self.tmp.name) / "data" / "Asset"
        res.mkdir(parents=True)
        (res / "a.txt").write_text("x", encoding="utf-8")
        u = up.Uploader115(s)
        r = u.upload_folder(res, Path(self.tmp.name) / "data", None)
        self.assertFalse(r["ok"])
        self.assertIn("占位", r["error"])

    def test_secret_not_in_settings_json(self):
        s = settings_mod.load_settings(self.project)
        settings_mod.save_115_credentials(s, app_secret="topsecret", token="t")
        settings_mod.save_settings(self.project, s)
        saved = (self.project / "workbench_data" / "settings.json").read_text(encoding="utf-8")
        self.assertNotIn("topsecret", saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
