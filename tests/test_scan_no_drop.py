"""回归：扫描测试批次时不应漏掉任何顶层资源（如 MECHANICAL LEG）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.classifier import build_cards
from resource_workbench.scanner import ScanConfig, scan_input

TEST_DIR = Path(__file__).resolve().parents[2] / "测试"


@unittest.skipUnless(TEST_DIR.exists(), "本机测试目录不存在，跳过")
class ScanNoDropTests(unittest.TestCase):
    def _names(self, depth, inspect=False):
        scan = scan_input(TEST_DIR, config=ScanConfig(
            resource_root_depth=depth, inspect_archives=inspect, max_archives_to_inspect=40))
        return [c.get("name", "") for c in build_cards(scan, z_root=None)]

    def test_mechanical_leg_present_each_depth(self):
        for depth in (None, 1, 2, 3):
            names = self._names(depth)
            joined = " | ".join(names)
            self.assertTrue(
                any("MECHANICAL" in n or "Robot Leg" in n for n in names),
                f"depth={depth} 漏掉了 MECHANICAL LEG：{joined}",
            )

    def test_all_three_top_resources_present(self):
        names = self._names(3)
        joined = " | ".join(names)
        for key in ("MECHANICAL", "Basalt Columns", "科幻29"):
            self.assertTrue(any(key in n for n in names), f"depth=3 漏掉 {key}：{joined}")

    def test_no_drop_with_archive_inspection(self):
        # 开启压缩包检查时，资源仍应全部成卡（遍历优先，压缩包预览是第二阶段，超时也不漏资源）
        names = self._names(3, inspect=True)
        joined = " | ".join(names)
        for key in ("MECHANICAL", "Basalt Columns", "科幻29"):
            self.assertTrue(any(key in n for n in names), f"开启压缩包检查后漏 {key}：{joined}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
