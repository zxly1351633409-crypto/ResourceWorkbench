from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import settings as settings_mod
from resource_workbench import web_resource as web_resource_mod
from resource_workbench.web_resource import (
    build_web_preview,
    fetch_web_metadata,
    normalise_url,
    read_web_resource_card,
    save_web_resource_bundle,
)


class FakeResponse:
    def __init__(self, url: str, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.url = url
        self.body = body
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.url


class WebResourceTests(unittest.TestCase):
    def test_default_paths_are_blank_for_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_mod.load_settings(Path(tmp))
            self.assertEqual(settings["resource_root"], "")
            self.assertNotIn("test_move_root", settings)

    def test_url_normalisation_adds_https(self):
        self.assertEqual(normalise_url("example.com/page"), "https://example.com/page")

    def test_fetch_bilibili_video_uses_video_api(self):
        html = b"<html><title>Bilibili</title></html>"
        api = {
            "code": 0,
            "data": {
                "title": "Robot Rigging Tutorial",
                "desc": "A Blender rigging lesson.",
                "pic": "https://i0.hdslb.com/bfs/archive/demo.jpg",
                "tname": "野生技能协会",
                "owner": {"name": "Demo UP"},
                "stat": {"view": 1234},
            },
        }

        def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
            url = request.full_url
            if "x/web-interface/view" in url:
                return FakeResponse(url, json_bytes(api), "application/json")
            return FakeResponse("https://www.bilibili.com/video/BV1xx411c7mD", html)

        with mock.patch.object(web_resource_mod.urllib.request, "urlopen", fake_urlopen):
            metadata = fetch_web_metadata("https://www.bilibili.com/video/BV1xx411c7mD")

        self.assertEqual(metadata["platform"], "Bilibili")
        self.assertEqual(metadata["content_kind"], "video")
        self.assertEqual(metadata["title"], "Robot Rigging Tutorial")
        self.assertIn("Demo UP", metadata["description"])
        self.assertEqual(metadata["image_url"], "https://i0.hdslb.com/bfs/archive/demo.jpg")

    def test_fetch_jsonld_article_metadata(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"Article","headline":"Rock Scan Notes","description":"Photogrammetry article","image":"https://example.com/cover.jpg","author":{"name":"Ada"}}
        </script>
        </head></html>
        """.encode("utf-8")

        def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
            return FakeResponse("https://example.com/post", html)

        with mock.patch.object(web_resource_mod.urllib.request, "urlopen", fake_urlopen):
            metadata = fetch_web_metadata("https://example.com/post")

        self.assertEqual(metadata["title"], "Rock Scan Notes")
        self.assertEqual(metadata["content_kind"], "article")
        self.assertEqual(metadata["author"], "Ada")

    def test_preview_bundle_and_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = {
                "url": "https://example.com/tutorial",
                "final_url": "https://example.com/tutorial",
                "domain": "example.com",
                "title": "Example Tutorial",
                "description": "A small page for testing.",
                "image_url": "",
            }
            preview = build_web_preview(metadata, root / "cache")
            self.assertIsNotNone(preview)
            self.assertTrue(Path(preview).exists())
            card = {
                "resource_kind": "web",
                "display_name": "Example Tutorial",
                "source_url": "https://example.com/tutorial",
                "web_domain": "example.com",
                "web_description": "A small page for testing.",
                "content_tags": ["网页", "example.com"],
                "preview_source": {"kind": "file", "path": str(preview)},
            }
            result = save_web_resource_bundle(card, root / "library")
            self.assertTrue(result["ok"])
            folder = Path(result["folder_path"])
            self.assertTrue((folder / "web-resource.url").exists())
            self.assertTrue((folder / "metadata.json").exists())
            self.assertTrue((folder / "preview.png").exists())
            readback = read_web_resource_card(folder)
            self.assertIsNotNone(readback)
            self.assertEqual(readback["source_url"], "https://example.com/tutorial")

    def test_preview_prefers_screenshot_for_fallback_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenshot = root / "page.png"

            def fake_screenshot(_url, output_path):  # noqa: ANN001
                from PIL import Image

                Image.new("RGB", (320, 180), (60, 110, 180)).save(output_path)
                return Path(output_path)

            metadata = {
                "url": "https://superhivemarket.com/products/advanced-array-tool",
                "final_url": "https://superhivemarket.com/products/advanced-array-tool",
                "domain": "superhivemarket.com",
                "title": "Advanced Array Tool",
                "description": "Product page.",
                "image_url": "https://www.google.com/s2/favicons?domain=superhivemarket.com&sz=256",
                "image_is_fallback": True,
                "screenshot_preferred": True,
            }
            with mock.patch.object(web_resource_mod, "_capture_webpage_screenshot", side_effect=fake_screenshot) as shot:
                with mock.patch.object(web_resource_mod, "_download_image", return_value=screenshot) as download:
                    preview = build_web_preview(metadata, root / "cache")

            self.assertIsNotNone(preview)
            self.assertTrue(Path(preview).exists())
            shot.assert_called_once()
            download.assert_not_called()

    def test_shotdeck_is_no_longer_excluded_from_screenshot_capture(self):
        metadata = {
            "url": "https://shotdeck.com/browse/stills",
            "final_url": "https://shotdeck.com/browse/stills",
            "domain": "shotdeck.com",
            "image_url": "https://shotdeck.com/favicon.png",
            "image_is_fallback": True,
            "screenshot_preferred": True,
        }
        self.assertTrue(web_resource_mod._should_capture_page_screenshot(metadata))

    def test_blocked_headless_page_falls_back_instead_of_becoming_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "blocked.png"
            completed = mock.Mock(stdout=b"<html>Sorry, you have been blocked</html>", stderr=b"")
            with mock.patch.object(web_resource_mod, "_headless_browser_executable", return_value=Path("chrome.exe")):
                with mock.patch.object(web_resource_mod.subprocess, "run", return_value=completed):
                    result = web_resource_mod._capture_with_headless_browser("https://example.com", output)
            self.assertIsNone(result)
            self.assertFalse(output.exists())


def json_bytes(payload: dict) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
