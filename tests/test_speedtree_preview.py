from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.preview import prepare_preview_image
from resource_workbench.speedtree_preview import (
    SPEEDTREE_PREVIEW_COMMAND_ENV,
    detect_speedtree_asset,
    resolve_speedtree_preview_source,
)


def _image(path: Path, color: tuple[int, int, int] = (40, 120, 70)) -> None:
    Image.new("RGB", (320, 220), color).save(path)


class SpeedTreePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.asset_dir = self.root / "Oak Tree"
        self.asset_dir.mkdir()
        self.cache_dir = self.root / "cache"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_existing_preview_is_reused_without_writing_asset_directory(self) -> None:
        project = self.asset_dir / "oak.spm"
        project.write_bytes(b"test project")
        preview = self.asset_dir / "preview.png"
        _image(preview)
        before = {path.name for path in self.asset_dir.iterdir()}

        source = resolve_speedtree_preview_source({"source_path": str(self.asset_dir)}, self.cache_dir)

        self.assertIsNotNone(source)
        self.assertEqual(source["path"], str(preview))
        self.assertEqual(source["speedtree_preview"], "existing_render")
        self.assertEqual(before, {path.name for path in self.asset_dir.iterdir()})

    def test_direct_project_prefers_its_stem_preview_over_other_larger_previews(self) -> None:
        oak = self.asset_dir / "oak.spm"
        pine = self.asset_dir / "pine.spm"
        oak.write_bytes(b"oak project")
        pine.write_bytes(b"pine project")
        _image(self.asset_dir / "oak_preview.png", (35, 130, 70))
        _image(self.asset_dir / "pine_preview.png", (45, 145, 80))
        # A name containing both a preview hint and a texture-channel hint must
        # still be rejected.
        _image(self.asset_dir / "bark_preview_normal.png", (90, 90, 180))

        source = resolve_speedtree_preview_source({"source_path": str(oak)}, self.cache_dir)

        self.assertEqual(Path(source["path"]).name, "oak_preview.png")

    def test_texture_is_not_presented_as_render_and_placeholder_is_explicit(self) -> None:
        project = self.asset_dir / "oak.spm"
        project.write_bytes(b"test project")
        _image(self.asset_dir / "oak_basecolor.png")
        _image(self.asset_dir / "oak_normal.png")
        before = {path.name for path in self.asset_dir.iterdir()}

        with mock.patch.dict(os.environ, {SPEEDTREE_PREVIEW_COMMAND_ENV: ""}):
            source = resolve_speedtree_preview_source({"source_path": str(self.asset_dir)}, self.cache_dir)

        self.assertIsNotNone(source)
        self.assertEqual(source["speedtree_preview"], "placeholder_not_rendered")
        self.assertTrue(Path(source["path"]).is_relative_to(self.cache_dir))
        self.assertTrue(Path(source["path"]).exists())
        self.assertEqual(before, {path.name for path in self.asset_dir.iterdir()})

    def test_prepare_preview_integrates_placeholder_for_card_without_preview_source(self) -> None:
        project = self.asset_dir / "tree.spm"
        project.write_bytes(b"project")
        card = {"source_path": str(self.asset_dir), "preview_source": None}

        result = prepare_preview_image(card, self.cache_dir, size=(260, 180))

        self.assertTrue(result["ok"], result)
        output = Path(result["path"])
        self.assertTrue(output.is_relative_to(self.cache_dir))
        with Image.open(output) as image:
            self.assertLessEqual(image.width, 260)
            self.assertLessEqual(image.height, 180)

    def test_text_subtitle_srt_is_not_misidentified(self) -> None:
        subtitle = self.asset_dir / "captions.srt"
        subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\n一棵树\n", encoding="utf-8")

        self.assertIsNone(detect_speedtree_asset({"source_path": str(subtitle)}))
        self.assertIsNone(detect_speedtree_asset({"source_path": str(self.asset_dir)}))

    def test_utf16_subtitle_srt_is_not_misidentified(self) -> None:
        subtitle = self.asset_dir / "captions.srt"
        subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\n一棵树\n", encoding="utf-16")

        self.assertIsNone(detect_speedtree_asset({"source_path": str(subtitle)}))

    def test_text_subtitle_stays_excluded_even_beside_spm_project(self) -> None:
        subtitle = self.asset_dir / "captions.srt"
        subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        project = self.asset_dir / "oak.spm"
        project.write_bytes(b"project")

        direct = detect_speedtree_asset({"source_path": str(subtitle)})
        directory = detect_speedtree_asset({"source_path": str(self.asset_dir)})

        self.assertIsNone(direct)
        self.assertIsNotNone(directory)
        self.assertEqual(directory.project_files, (project,))

    def test_binary_speedtree_runtime_srt_is_supported(self) -> None:
        runtime = self.asset_dir / "oak.srt"
        runtime.write_bytes(b"SRT\x00SpeedTree\x00" + b"\x01\x02" * 100)

        asset = detect_speedtree_asset({"source_path": str(runtime)})

        self.assertIsNotNone(asset)
        self.assertEqual(asset.primary_path, runtime)

    def test_external_generator_protocol_is_opt_in_cached_and_non_shell(self) -> None:
        project = self.asset_dir / "oak.spm"
        project.write_bytes(b"test project")
        executable = self.root / "headless-preview.exe"
        executable.write_bytes(b"placeholder executable for mocked test")
        template = json.dumps(
            [str(executable), "--input", "{input}", "--output", "{output}"],
            ensure_ascii=False,
        )

        def fake_run(command, **kwargs):  # noqa: ANN001
            output = Path(command[command.index("--output") + 1])
            _image(output, (80, 160, 100))
            self.assertEqual(command[command.index("--input") + 1], str(project))
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["timeout"], 12)
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with mock.patch.dict(os.environ, {SPEEDTREE_PREVIEW_COMMAND_ENV: template}), mock.patch(
            "resource_workbench.speedtree_preview.subprocess.run", side_effect=fake_run
        ) as run:
            first = resolve_speedtree_preview_source(
                {"source_path": str(project)}, self.cache_dir, timeout_seconds=12
            )
            second = resolve_speedtree_preview_source(
                {"source_path": str(project)}, self.cache_dir, timeout_seconds=12
            )

        self.assertEqual(first["speedtree_preview"], "external_generator")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(run.call_count, 1)

    def test_invalid_external_command_falls_back_without_execution(self) -> None:
        project = self.asset_dir / "oak.spm"
        project.write_bytes(b"test project")
        unsafe_shell_text = f'"{self.root / "tool.exe"}" --input {{input}} --output {{output}}'

        with mock.patch.dict(os.environ, {SPEEDTREE_PREVIEW_COMMAND_ENV: unsafe_shell_text}), mock.patch(
            "resource_workbench.speedtree_preview.subprocess.run"
        ) as run:
            source = resolve_speedtree_preview_source({"source_path": str(project)}, self.cache_dir)

        run.assert_not_called()
        self.assertEqual(source["speedtree_preview"], "placeholder_not_rendered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
