from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import archive as ar
from resource_workbench import scanner as sc
from resource_workbench.classifier import build_cards


class ArchiveSubprocessTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows-specific console flags")
    def test_windows_subprocess_options_hide_console(self):
        kwargs = ar._subprocess_kwargs()
        self.assertTrue(kwargs["creationflags"] & ar.subprocess.CREATE_NO_WINDOW)
        self.assertIn("startupinfo", kwargs)
        self.assertTrue(kwargs["startupinfo"].dwFlags & ar.subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, ar.subprocess.SW_HIDE)

    def test_list_archive_entries_uses_shared_silent_options(self):
        backend = ar.ArchiveBackend("7zip", Path(r"C:\fake\7z.exe"))
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        silent = {"creationflags": 12345}
        with (
            patch.object(ar, "preferred_archive_backend", return_value=backend),
            patch.object(ar, "_subprocess_kwargs", return_value=silent),
            patch.object(ar.subprocess, "run", return_value=completed) as run,
        ):
            result = ar.list_archive_entries(Path("sample.zip"))

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.kwargs["creationflags"], 12345)

    def test_extract_archive_entry_uses_shared_silent_options(self):
        backend = ar.ArchiveBackend("haozip", Path(r"C:\fake\HaoZipC.exe"))
        completed = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        silent = {"creationflags": 54321}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            preview = output / "preview.png"
            preview.write_bytes(b"preview")
            with (
                patch.object(ar, "preferred_archive_backend", return_value=backend),
                patch.object(ar, "infer_archive_passwords", return_value=[""]),
                patch.object(ar, "_subprocess_kwargs", return_value=silent),
                patch.object(ar.subprocess, "run", return_value=completed) as run,
            ):
                result = ar.extract_archive_entry(
                    Path("sample.zip"),
                    "preview.png",
                    output,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.kwargs["creationflags"], 54321)


class ArchiveScanPolicyTests(unittest.TestCase):
    @staticmethod
    def _listing() -> dict:
        return {
            "ok": True,
            "backend": "fake-7z",
            "entries": [
                {"Path": "Robot A/a.fbx"},
                {"Path": "Robot A/a.png"},
                {"Path": "Robot B/b.fbx"},
                {"Path": "Robot B/b.png"},
                {"Path": "Robot C/c.fbx"},
                {"Path": "Robot C/c.png"},
            ],
            "truncated": False,
            "error": None,
        }

    def test_default_scan_never_lists_archive_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "collection.zip"
            archive_path.write_bytes(b"not a real zip")
            with patch.object(sc, "list_archive_entries") as listing:
                scan = sc.scan_input(Path(tmp))

        listing.assert_not_called()
        self.assertEqual(scan["inspected_archives"], 0)
        self.assertFalse(scan["split_archive_subresources"])
        self.assertEqual(len(build_cards(scan)), 1)

    def test_inspection_without_split_keeps_archive_as_one_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "collection.zip"
            archive_path.write_bytes(b"not a real zip")
            with patch.object(sc, "list_archive_entries", return_value=self._listing()):
                scan = sc.scan_input(
                    Path(tmp),
                    config=sc.ScanConfig(inspect_archives=True),
                )

        group = next(iter(scan["groups"].values()))
        self.assertEqual(scan["inspected_archives"], 1)
        self.assertEqual(group["archive_subresources"], {})
        self.assertEqual(len(build_cards(scan)), 1)

    def test_subresource_cards_require_both_inspection_and_split_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "collection.zip"
            archive_path.write_bytes(b"not a real zip")
            with patch.object(sc, "list_archive_entries", return_value=self._listing()):
                scan = sc.scan_input(
                    Path(tmp),
                    config=sc.ScanConfig(
                        inspect_archives=True,
                        split_archive_subresources=True,
                    ),
                )

        self.assertTrue(scan["split_archive_subresources"])
        self.assertEqual(len(build_cards(scan)), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
