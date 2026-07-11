"""CLI recommend 端到端测试。"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import cli


class CliRecommendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.z = Path(self.tmp.name) / "Z"
        for rel in ["M 模型/K 科幻/Q 枪支", "M 模型/K 科幻/J 机甲", "M 模型/K 科幻/W 物件"]:
            (self.z / rel).mkdir(parents=True)
        self.work = Path(self.tmp.name) / "待整理" / "sci fi gun rifle pack"
        self.work.mkdir(parents=True)
        (self.work / "cover.png").write_text("x", encoding="utf-8")
        (self.work / "model.fbx").write_text("y", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_recommend_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main([
                "recommend", str(self.work.parent),
                "--z-root", str(self.z),
                "--resource-depth", "1", "--json",
            ])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data)
        cands = data[0]["candidates"]
        self.assertTrue(any("枪支" in c for c in cands))
        # 枪支应排在机甲前面
        gun = next(i for i, c in enumerate(cands) if "枪支" in c)
        mech = next((i for i, c in enumerate(cands) if "机甲" in c), 999)
        self.assertLess(gun, mech)


if __name__ == "__main__":
    unittest.main(verbosity=2)
