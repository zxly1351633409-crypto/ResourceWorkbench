from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.settings import app_data_root, load_settings, save_settings


class DistributionLayoutTests(unittest.TestCase):
    def test_explicit_home_isolation_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            isolated = Path(tmp) / "clean-home"
            with (
                mock.patch.dict(
                    os.environ,
                    {"RESOURCE_WORKBENCH_HOME": str(isolated), "LOCALAPPDATA": str(Path(tmp) / "local")},
                    clear=True,
                ),
                mock.patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual(app_data_root(ROOT), isolated)

    def test_frozen_exe_uses_public_stable_profile_without_personal_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp) / "LocalAppData"
            personal_root = local_app_data / "ResourceWorkbench"
            personal = load_settings(personal_root)
            personal["resource_root"] = "PERSONAL-LIBRARY"
            save_settings(personal_root, personal)

            with (
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True),
                mock.patch.object(sys, "frozen", True, create=True),
            ):
                first_root = app_data_root(ROOT)
                expected = personal_root / "Profiles" / "Public" / "Stable"
                self.assertEqual(first_root, expected)
                self.assertEqual(load_settings(first_root)["resource_root"], "")

                public = load_settings(first_root)
                public["resource_root"] = "PUBLIC-LIBRARY"
                save_settings(first_root, public)

                second_root = app_data_root(ROOT)
                self.assertEqual(second_root, first_root)
                self.assertEqual(load_settings(second_root)["resource_root"], "PUBLIC-LIBRARY")

            self.assertEqual(load_settings(personal_root)["resource_root"], "PERSONAL-LIBRARY")

    def test_three_launchers_use_separate_runtime_homes(self) -> None:
        development = (ROOT / "启动-开发工作台.bat").read_text(encoding="utf-8")
        formal = (ROOT / "启动-正式工作台.bat").read_text(encoding="utf-8")
        clean = (ROOT / "启动-干净分发预览.bat").read_text(encoding="utf-8")
        self.assertIn(".runtime\\development", development)
        self.assertIn("%LOCALAPPDATA%\\ResourceWorkbench", formal)
        self.assertNotIn("Profiles\\Public\\Stable", formal)
        self.assertIn("ResourceWorkbench-CleanPreview", clean)
        self.assertIn("%RANDOM%", clean)
        self.assertNotIn("rmdir /s /q", clean)

        for launcher in ROOT.glob("启动-*.bat"):
            text = launcher.read_text(encoding="utf-8")
            self.assertIn("RESOURCE_WORKBENCH_HOME", text, launcher.name)
            self.assertNotIn("F:\\gpt codex huancun", text, launcher.name)

    def test_build_has_runtime_data_safety_gate(self) -> None:
        script = (ROOT / "tools" / "build_windows_app.ps1").read_text(encoding="utf-8")
        for forbidden in (
            "workbench_data",
            "secret.json",
            "settings.json",
            "move_log.sqlite",
            "resource_index.sqlite",
            "review_queue.sqlite",
        ):
            self.assertIn(forbidden, script)
        self.assertIn("Assert-CleanDistributionArchive", script)
        self.assertIn("machine-specific path", script)
        self.assertIn("credential-like value", script)
        self.assertIn("Get-KnownBuildSecrets", script)
        self.assertIn("Profiles\\Public\\Stable", script)
        self.assertIn("Compress-Archive", script)

    def test_archive_gate_is_repeatable_and_never_echoes_secret(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")

        script = ROOT / "tools" / "build_windows_app.ps1"
        fake_secret = "sk-private-test-value-1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            safe_zip = temp / "safe.zip"
            with zipfile.ZipFile(safe_zip, "w") as archive:
                archive.writestr(
                    "ResourceWorkbench/USER_GUIDE.md",
                    "%LOCALAPPDATA%\\ResourceWorkbench\\Profiles\\Public\\Stable",
                )

            safe = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-AuditArchive",
                    str(safe_zip),
                ],
                cwd=ROOT,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)

            unsafe_zip = temp / "unsafe.zip"
            with zipfile.ZipFile(unsafe_zip, "w") as archive:
                archive.writestr(
                    "ResourceWorkbench/notes.txt",
                    f"library=C:\\Users\\private-user\\私有目录\napi_key={fake_secret}\n",
                )

            env = dict(os.environ)
            env["DEEPSEEK_API_KEY"] = fake_secret
            unsafe = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-AuditArchive",
                    str(unsafe_zip),
                ],
                cwd=ROOT,
                env=env,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
            )
            output = unsafe.stdout + unsafe.stderr
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertNotIn(fake_secret, output)

            state_zip = temp / "state.zip"
            with zipfile.ZipFile(state_zip, "w") as archive:
                archive.writestr("ResourceWorkbench/workbench_data/settings.json", "{}")
            state = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-AuditArchive",
                    str(state_zip),
                ],
                cwd=ROOT,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(state.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
