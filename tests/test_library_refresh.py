from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.library_refresh import (
    direct_child_signature,
    resolve_library_child,
    safe_mkdir,
    validate_windows_directory_name,
)


class WindowsDirectoryNameTests(unittest.TestCase):
    def test_accepts_normal_chinese_and_internal_spaces(self):
        for name in ("24-延庆寺 视频（无人机）", "G 中国古建", "asset.v2"):
            with self.subTest(name=name):
                self.assertTrue(validate_windows_directory_name(name).ok)

    def test_rejects_empty_relative_separators_and_invalid_characters(self):
        cases = {
            "": "empty",
            "   ": "empty",
            ".": "relative_component",
            "..": "relative_component",
            "a/b": "invalid_character",
            "a\\b": "invalid_character",
            "a:b": "invalid_character",
            "a\x00b": "invalid_character",
        }
        for name, code in cases.items():
            with self.subTest(name=repr(name)):
                result = validate_windows_directory_name(name)
                self.assertFalse(result.ok)
                self.assertEqual(result.error_code, code)

    def test_rejects_reserved_names_extensions_and_trailing_dot_or_space(self):
        for name in ("CON", "con.txt", "LPT9", "com1.backup", "NUL.json", "CLOCK$"):
            with self.subTest(name=name):
                self.assertEqual(validate_windows_directory_name(name).error_code, "reserved_name")
        for name in ("folder.", "folder "):
            with self.subTest(name=name):
                self.assertEqual(
                    validate_windows_directory_name(name).error_code,
                    "trailing_dot_or_space",
                )


class LibraryContainmentTests(unittest.TestCase):
    def test_nonexistent_child_under_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            parent = root / "models" / "architecture"
            parent.mkdir(parents=True)
            result = resolve_library_child(parent, "new category", [root])
            self.assertTrue(result.ok)
            self.assertEqual(result.target, parent / "new category")
            self.assertFalse(result.target.exists())

    def test_root_itself_is_a_valid_parent_for_a_new_child(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            root.mkdir()
            result = resolve_library_child(root, "top-level", [root])
            self.assertTrue(result.ok)
            self.assertEqual(result.library_root, root.resolve())

    def test_sibling_prefix_and_parent_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            sibling = base / "library-other"
            sibling.mkdir()
            self.assertEqual(
                resolve_library_child(sibling, "bad", [root]).error_code,
                "outside_library_roots",
            )
            escaped_parent = root / ".." / "outside"
            self.assertEqual(
                resolve_library_child(escaped_parent, "bad", [root]).error_code,
                "outside_library_roots",
            )

    def test_unc_checks_are_lexical_case_insensitive_and_do_not_need_to_exist(self):
        root = r"\\Server\Share\Library"
        parent = r"\\server\share\LIBRARY\G 中国古建\金代"
        result = resolve_library_child(parent, "24-延庆寺", [root])
        self.assertTrue(result.ok)
        self.assertEqual(str(result.target).casefold(), (parent + r"\24-延庆寺").casefold())

        outside = resolve_library_child(r"\\server\share\Library-Other", "bad", [root])
        self.assertEqual(outside.error_code, "outside_library_roots")

    @unittest.skipUnless(os.name == "nt", "Windows path casing is only meaningful on Windows")
    def test_local_windows_paths_are_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "LibraryCase"
            parent = root / "Models"
            parent.mkdir(parents=True)
            result = resolve_library_child(str(parent).swapcase(), "Child", [str(root).upper()])
            self.assertTrue(result.ok)


class DirectChildSignatureTests(unittest.TestCase):
    def test_signature_is_sorted_direct_only_and_changes_with_file_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "B-folder"
            nested.mkdir()
            item = root / "a.txt"
            item.write_bytes(b"a")

            first = direct_child_signature(root)
            self.assertTrue(first.ok)
            self.assertEqual([entry.name for entry in first.entries], ["a.txt", "B-folder"])
            self.assertEqual({entry.name: entry.is_dir for entry in first.entries}["B-folder"], True)

            item.write_bytes(b"a-longer-value")
            second = direct_child_signature(root)
            self.assertNotEqual(first, second)
            self.assertEqual({entry.name: entry.size for entry in second.entries}["a.txt"], 14)

    def test_missing_and_not_directory_are_stable_comparable_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing"
            first = direct_child_signature(missing)
            second = direct_child_signature(missing)
            self.assertEqual(first, second)
            self.assertEqual(first.status, "missing")

            file_path = root / "file.txt"
            file_path.write_text("x", encoding="utf-8")
            self.assertEqual(direct_child_signature(file_path).status, "not_directory")


class SafeMkdirTests(unittest.TestCase):
    def test_creates_one_valid_child_and_reports_existing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "library"
            parent = root / "models"
            parent.mkdir(parents=True)

            created = safe_mkdir(parent, "new folder", [root])
            self.assertTrue(created.ok)
            self.assertTrue(created.created)
            self.assertTrue((parent / "new folder").is_dir())

            repeated = safe_mkdir(parent, "new folder", [root])
            self.assertFalse(repeated.ok)
            self.assertEqual(repeated.error_code, "already_exists")

    def test_rejects_invalid_outside_and_missing_parent_without_side_effects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "library"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()

            invalid = safe_mkdir(root, "bad/name", [root])
            self.assertEqual(invalid.error_code, "invalid_character")
            self.assertFalse((root / "bad").exists())

            rejected = safe_mkdir(outside, "child", [root])
            self.assertEqual(rejected.error_code, "outside_library_roots")
            self.assertFalse((outside / "child").exists())

            missing_parent = root / "missing"
            missing = safe_mkdir(missing_parent, "child", [root])
            self.assertEqual(missing.error_code, "parent_missing")
            self.assertFalse((missing_parent / "child").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
