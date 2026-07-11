"""扫描拆分：格式子文件夹不得各自成卡；真合集仍要拆。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import classifier as clf
from resource_workbench import scanner as sc


class FormatFolderTests(unittest.TestCase):
    def test_format_folders_detected(self):
        for name in ["fbx and blend", "obj&textures", "obj & textures", "marmoset",
                     "Marmoset Scene", "textures", "Source Files", "UE5", "Low Poly",
                     "FBX", "OBJ + Textures", "3D model", "Substance", "ZBrush"]:
            self.assertTrue(sc._is_format_folder(name), f"应判为格式文件夹: {name}")

    def test_real_resources_kept(self):
        for name in ["Sci-Fi Rifles Set  Kitbash", "GSLV rocket 3D model",
                     "300 Blackout Ammo Assortment Pack", "Robot Mech Percival",
                     "科幻机器人腿", "Basalt Columns Lake", "ROOFTOP Props Collection Kitbash 2_72"]:
            self.assertFalse(sc._is_format_folder(name), f"不应判为格式文件夹: {name}")
            self.assertTrue(sc._is_meaningful_segment(name), f"应是有意义资源名: {name}")

    def test_texture_channel_folders_are_not_resources(self):
        for name in [
            "Textures", "Maps", "Normal", "Roughness", "Metallic", "BaseColor",
            "AO", "Displacement", "4K Textures", "法线贴图", "粗糙度",
        ]:
            self.assertTrue(sc._is_format_folder(name), f"应判为资源内部目录: {name}")
            self.assertFalse(sc._is_meaningful_segment(name), f"不应成为压缩包子资源: {name}")


class CandidateRootTests(unittest.TestCase):
    def test_single_model_not_split_by_formats(self):
        # 一个模型，内部按格式分目录 -> 候选根应只有模型名，不按格式拆
        paths = [
            ["Sci_Fi Robot Leg", "fbx and blend", "leg.fbx"],
            ["Sci_Fi Robot Leg", "marmoset", "leg.tbscene"],
            ["Sci_Fi Robot Leg", "obj&textures", "leg.obj"],
            ["Sci_Fi Robot Leg", "obj&textures", "diffuse.png"],
        ]
        roots = sc._candidate_roots_from_parts(paths)
        self.assertIn("Sci_Fi Robot Leg", roots)
        self.assertNotIn("marmoset", roots)
        self.assertNotIn("fbx and blend", roots)
        self.assertNotIn("obj&textures", roots)
        # 只有 1 个候选 -> 不会触发 >=3 的拆分
        self.assertEqual(len(roots), 1)

    def test_real_collection_still_splits(self):
        paths = [
            ["科幻29", "300 Blackout Ammo Assortment Pack", "a.fbx"],
            ["科幻29", "GSLV rocket 3D model", "b.fbx"],
            ["科幻29", "Robot Mech Percival", "c.fbx"],
            ["科幻29", "Mars 3 3D model", "d.fbx"],
        ]
        roots = sc._candidate_roots_from_parts(paths)
        # 第一层 科幻29 占主导，第二层是真实资源名 -> 按第二层拆
        self.assertIn("300 Blackout Ammo Assortment Pack", roots)
        self.assertIn("Robot Mech Percival", roots)
        self.assertNotIn("科幻29", roots)


class SplitBoundaryTests(unittest.TestCase):
    def test_single_candidate_is_not_reported_as_possible_split(self):
        group = {"archive_candidate_roots": {"MW Robot Low-poly 3D model": 4}}
        self.assertEqual(clf._possible_split_count(group), 0)

    def test_two_candidates_are_possible_but_not_auto_split(self):
        group = {
            "archive_candidate_roots": {"Robot A": 3, "Robot B": 3},
            "archive_subresources": {
                "Robot A": {"total_entries": 3, "buckets": {"model": 1, "image": 2}},
                "Robot B": {"total_entries": 3, "buckets": {"model": 1, "image": 2}},
            },
        }
        self.assertEqual(clf._possible_split_count(group), 2)
        self.assertFalse(clf._should_split_group(group))

    def test_three_payload_candidates_require_explicit_opt_in(self):
        group = {
            "archive_candidate_roots": {"Robot A": 3, "Robot B": 3, "Robot C": 3},
            "archive_subresources": {
                "Robot A": {"total_entries": 3, "buckets": {"model": 1}},
                "Robot B": {"total_entries": 3, "buckets": {"image": 2}},
                "Robot C": {"total_entries": 3, "buckets": {"archive": 2}},
            },
        }
        self.assertFalse(clf._should_split_group(group))
        self.assertTrue(clf._should_split_group(group, allow_archive_subresources=True))

    def test_texture_channel_candidates_never_split(self):
        group = {
            "archive_subresources": {
                "Textures": {"total_entries": 20, "buckets": {"image": 20}},
                "Normal": {"total_entries": 20, "buckets": {"image": 20}},
                "Roughness": {"total_entries": 20, "buckets": {"image": 20}},
            },
        }
        self.assertFalse(clf._should_split_group(group, allow_archive_subresources=True))


class ScanDefaultsTests(unittest.TestCase):
    def test_archive_inspection_and_splitting_are_off_by_default(self):
        config = sc.ScanConfig()
        self.assertFalse(config.inspect_archives)
        self.assertFalse(config.split_archive_subresources)

    def test_disk_fragment_folders_fold_into_owning_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = [
                root / "Robot Pack" / "Textures" / "Normal" / "robot_normal.png",
                root / "Robot Pack" / "Maps" / "Roughness" / "robot_roughness.png",
                root / "Robot Pack" / "FBX" / "robot.fbx",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")

            scan = sc.scan_input(
                root,
                config=sc.ScanConfig(resource_root_depth=3),
            )
            self.assertEqual(list(scan["groups"]), ["Robot Pack"])
            self.assertEqual(scan["groups"]["Robot Pack"]["total_files"], 3)

    def test_root_texture_folders_make_one_root_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder, filename in (
                ("Textures", "basecolor.png"),
                ("Normal", "normal.png"),
                ("Roughness", "roughness.png"),
            ):
                path = root / folder / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")

            scan = sc.scan_input(root, config=sc.ScanConfig(resource_root_depth=2))
            self.assertEqual(list(scan["groups"]), ["(根目录文件)"])
            self.assertEqual(scan["groups"]["(根目录文件)"]["total_files"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
