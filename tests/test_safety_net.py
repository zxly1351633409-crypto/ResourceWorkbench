"""安全网：顶层资源文件夹永不被整包丢掉。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.classifier import build_cards


def _mk_scan(groups):
    return {"input_path": r"X:\测试", "kind": "directory", "groups": groups}


class SafetyNetTests(unittest.TestCase):
    def test_recovers_fully_dropped_resource(self):
        base = "10 MECHANICAL LEG_VOL.01 - Standard Use License by Arvin Sharifi"
        groups = {
            base: {
                "total_files": 1,
                "absolute_path": rf"X:\测试\{base}",
                "buckets": {"image": 1},
                "image_candidates": [rf"X:\测试\{base}\file.jpg"],
            },
            f"{base}\\Assets": {
                "total_files": 0, "total_dirs": 1,
                "absolute_path": rf"X:\测试\{base}\Assets",
                "archive_virtual_buckets": {"model": 50, "image": 10},
                "archive_entry_samples": ["Sci_Fi Robot Leg\\01\\Leg_01.FBX"],
            },
        }
        cards = build_cards(_mk_scan(groups), z_root=None)
        names = [c.get("name") for c in cards]
        self.assertTrue(any("MECHANICAL" in n for n in names), f"安全网未恢复 MECH：{names}")
        mech = next(c for c in cards if "MECHANICAL" in c.get("name", ""))
        self.assertTrue(mech.get("recovered_card"))
        self.assertEqual(mech.get("suggested_type"), "model")
        self.assertIn("兜底卡", mech.get("content_tags") or [])
        self.assertTrue(any("兜底" in r for r in (mech.get("reasons") or [])))

    def test_no_duplicate_for_normal_group(self):
        groups = {
            "RobotLeg": {"total_files": 5, "absolute_path": r"X:\测试\RobotLeg",
                          "buckets": {"model": 5}, "archive_entry_samples": []},
        }
        cards = build_cards(_mk_scan(groups), z_root=None)
        self.assertEqual(sum(1 for c in cards if "RobotLeg" in c.get("name", "")), 1)
        self.assertFalse(cards[0].get("recovered_card"))

    def test_empty_deeper_folder_does_not_hide_parent_card(self):
        base = "10 MECHANICAL LEG_VOL.01 - Standard Use License by Arvin Sharifi"
        groups = {
            base: {
                "total_files": 1,
                "absolute_path": rf"X:\测试\{base}",
                "buckets": {"image": 1},
                "image_candidates": [rf"X:\测试\{base}\file.jpg"],
            },
            f"{base}\\Mechanical-Leg-01": {
                "total_files": 0,
                "total_dirs": 1,
                "absolute_path": rf"X:\测试\{base}\Mechanical-Leg-01",
                "buckets": {},
            },
        }
        cards = build_cards(_mk_scan(groups), z_root=None)
        self.assertEqual(len(cards), 1)
        self.assertIn("MECHANICAL", cards[0].get("name", ""))
        self.assertFalse(cards[0].get("recovered_card"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
