"""Guard source, package, build-script, and Windows-resource versions."""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import __version__  # noqa: E402


class VersionConsistencyTests(unittest.TestCase):
    def test_source_project_and_windows_build_versions_match(self) -> None:
        project = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        project_version = str(project["project"]["version"])

        build_script = (PROJECT_ROOT / "tools" / "build_windows_app.ps1").read_text(
            encoding="utf-8"
        )
        match = re.search(r'^\$version\s*=\s*"([^"]+)"', build_script, re.MULTILINE)
        self.assertIsNotNone(match, "build_windows_app.ps1 缺少 $version 声明")
        build_version = match.group(1) if match else ""

        version_resource = (
            PROJECT_ROOT / "tools" / "windows_version_info.txt"
        ).read_text(encoding="utf-8")
        version_tuple = tuple(int(part) for part in __version__.split(".")) + (0,)
        resource_tuple = ", ".join(str(part) for part in version_tuple)

        self.assertEqual(__version__, project_version)
        self.assertEqual(__version__, build_version)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertIn(f"filevers=({resource_tuple})", version_resource)
        self.assertIn(f"prodvers=({resource_tuple})", version_resource)
        self.assertIn(
            f'StringStruct(u"FileVersion", u"{__version__}")',
            version_resource,
        )
        self.assertIn(
            f'StringStruct(u"ProductVersion", u"{__version__}")',
            version_resource,
        )
        self.assertIn("ResourceWorkbench Contributors", version_resource)
        self.assertIn('"--version-file", $versionInfoPath', build_script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
