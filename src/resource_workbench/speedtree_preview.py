from __future__ import annotations

"""Safe SpeedTree preview discovery and fallback generation.

This module deliberately does not automate the SpeedTree GUI.  It only reads
asset metadata, reuses an explicitly named render beside the asset, optionally
calls an administrator-configured headless command, or creates a clearly
labelled placeholder in the ResourceWorkbench cache.
"""

import hashlib
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .archive import silent_subprocess_kwargs


SPEEDTREE_PROJECT_EXTS = frozenset({".spm"})
SPEEDTREE_RUNTIME_EXTS = frozenset({".srt"})
SPEEDTREE_PREVIEW_COMMAND_ENV = "RESOURCE_WORKBENCH_SPEEDTREE_PREVIEW_COMMAND"
SPEEDTREE_PREVIEW_ADAPTER_VERSION = "1"
EXISTING_RENDER_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})

_GOOD_RENDER_HINTS = (
    "preview",
    "render",
    "screenshot",
    "screen_shot",
    "thumbnail",
    "thumb",
    "cover",
    "beauty",
    "hero",
    "turntable",
    "showcase",
)
_TEXTURE_HINTS = (
    "albedo",
    "basecolor",
    "base_color",
    "diffuse",
    "normal",
    "roughness",
    "metallic",
    "specular",
    "gloss",
    "glossiness",
    "opacity",
    "height",
    "displacement",
    "bump",
    "ambientocclusion",
    "_ao",
    "mask",
    "atlas",
    "cluster",
    "leafmap",
    "leaf_map",
)
_MAX_DIRECTORY_ENTRIES = 2048
_MAX_GENERATED_BYTES = 100 * 1024 * 1024
_MAX_IMAGE_EDGE = 30_000


@dataclass(frozen=True)
class SpeedTreeAsset:
    """A conservatively identified SpeedTree asset."""

    primary_path: Path
    asset_dir: Path
    project_files: tuple[Path, ...]


def resolve_speedtree_preview_source(
    card: dict,
    cache_dir: Path,
    *,
    timeout_seconds: int = 45,
) -> dict | None:
    """Return a safe image source for a SpeedTree card, or ``None``.

    Resolution order is intentional:

    1. an explicitly named render/screenshot beside the project;
    2. an opt-in external *headless* generator configured as a JSON argv list;
    3. a cache-only placeholder that says it is not a real render.

    The source asset and its directory are never written to by this adapter.
    """

    asset = detect_speedtree_asset(card)
    if asset is None:
        return None

    existing = find_existing_speedtree_render(asset)
    if existing is not None:
        return {
            "kind": "file",
            "path": str(existing),
            "speedtree_preview": "existing_render",
        }

    cache_dir = Path(cache_dir)
    generated = _run_external_generator(asset, cache_dir, timeout_seconds=timeout_seconds)
    if generated is not None:
        return {
            "kind": "file",
            "path": str(generated),
            "speedtree_preview": "external_generator",
        }

    placeholder = _build_placeholder(asset, cache_dir)
    return {
        "kind": "file",
        "path": str(placeholder),
        "speedtree_preview": "placeholder_not_rendered",
    }


def detect_speedtree_asset(card: dict) -> SpeedTreeAsset | None:
    """Identify .spm and binary .srt assets without treating subtitles as trees."""

    raw_path = card.get("source_path") or card.get("path")
    if not raw_path:
        return None
    try:
        source_path = Path(str(raw_path)).expanduser()
    except (OSError, TypeError, ValueError):
        return None
    if not source_path.exists():
        return None

    if source_path.is_file():
        suffix = source_path.suffix.lower()
        if suffix in SPEEDTREE_PROJECT_EXTS:
            return SpeedTreeAsset(source_path, source_path.parent, (source_path,))
        if suffix in SPEEDTREE_RUNTIME_EXTS and _is_probably_speedtree_runtime(source_path):
            return SpeedTreeAsset(source_path, source_path.parent, (source_path,))
        return None

    if not source_path.is_dir():
        return None
    try:
        direct_files = tuple(path for path in islice(source_path.iterdir(), _MAX_DIRECTORY_ENTRIES) if path.is_file())
    except OSError:
        return None

    projects = sorted(
        (path for path in direct_files if path.suffix.lower() in SPEEDTREE_PROJECT_EXTS),
        key=lambda path: path.name.casefold(),
    )
    runtimes = sorted(
        (
            path
            for path in direct_files
            if path.suffix.lower() in SPEEDTREE_RUNTIME_EXTS
            and _is_probably_speedtree_runtime(path)
        ),
        key=lambda path: path.name.casefold(),
    )
    project_files = tuple(projects + runtimes)
    if not project_files:
        return None
    return SpeedTreeAsset(project_files[0], source_path, project_files)


def find_existing_speedtree_render(asset: SpeedTreeAsset) -> Path | None:
    """Find an explicitly named, same-directory render without guessing textures."""

    try:
        images = [
            path
            for path in islice(asset.asset_dir.iterdir(), _MAX_DIRECTORY_ENTRIES)
            if path.is_file() and path.suffix.lower() in EXISTING_RENDER_EXTS
        ]
    except OSError:
        return None

    scored: list[tuple[int, int, str, Path]] = []
    project_stems = {path.stem.casefold() for path in asset.project_files}
    for image_path in images:
        score = _existing_render_score(image_path, project_stems)
        if score < 50:
            continue
        try:
            size = image_path.stat().st_size
        except OSError:
            size = 0
        scored.append((score, size, image_path.name.casefold(), image_path))
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], item[1], item[2]))[3]


def _existing_render_score(path: Path, project_stems: set[str]) -> int:
    stem = path.stem.casefold()
    score = 0
    if stem == "preview":
        score += 140
    if any(stem == f"{project_stem}_preview" for project_stem in project_stems):
        score += 130
    if any(hint in stem for hint in _GOOD_RENDER_HINTS):
        score += 70
    if any(hint in stem for hint in _TEXTURE_HINTS):
        score -= 180
    return score


def _is_probably_speedtree_runtime(path: Path) -> bool:
    """Differentiate binary SpeedTree .srt files from SubRip subtitle text."""

    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return False
    if not sample:
        return False
    if _looks_like_subrip(sample):
        return False
    lowered = sample.lower()
    if b"speedtree" in lowered or sample.startswith((b"SRT ", b"SRT\x00")):
        return True
    if b"\x00" in sample:
        return True
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        visible = sum(character.isprintable() or character in "\t\n\r" for character in text)
        if text and visible / len(text) >= 0.90:
            # Unknown but convincingly textual .srt content stays a document.
            return False
    return True


def _looks_like_subrip(sample: bytes) -> bool:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            text = sample.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "-->" not in text:
            continue
        if re.search(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}", text):
            return True
    return False


def _run_external_generator(asset: SpeedTreeAsset, cache_dir: Path, *, timeout_seconds: int) -> Path | None:
    raw_template = os.environ.get(SPEEDTREE_PREVIEW_COMMAND_ENV, "").strip()
    if not raw_template:
        return None
    template = _parse_generator_template(raw_template)
    if template is None:
        return None

    executable = Path(template[0])
    if not executable.is_absolute() or not executable.is_file():
        return None
    try:
        executable_stat = executable.stat()
        executable_identity = f"{executable_stat.st_size}|{executable_stat.st_mtime_ns}"
    except OSError:
        return None
    key = _asset_cache_key(asset, extra=f"{raw_template}|exe={executable_identity}")
    output_dir = cache_dir / "_speedtree_sources"
    output_path = output_dir / f"{key}_external.png"
    if _is_valid_generated_image(output_path):
        return output_path

    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_output = output_dir / f".{key}_{os.getpid()}_{uuid.uuid4().hex}.tmp.png"
    replacements = {"input": str(asset.primary_path), "output": str(temporary_output)}
    try:
        command = [argument.format_map(replacements) for argument in template]
    except (KeyError, ValueError):
        return None

    try:
        completed = subprocess.run(
            command,
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=max(1, min(int(timeout_seconds), 300)),
            shell=False,
            **silent_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None

    try:
        if completed is None or completed.returncode != 0 or not _is_valid_generated_image(temporary_output):
            return None
        os.replace(temporary_output, output_path)
        return output_path
    finally:
        if temporary_output.exists():
            try:
                temporary_output.unlink()
            except OSError:
                pass


def _parse_generator_template(raw_template: str) -> list[str] | None:
    try:
        value = json.loads(raw_template)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        return None
    if len(value) > 64 or sum(len(item) for item in value) > 32_768:
        return None
    joined = "\n".join(value)
    if "{input}" not in joined or "{output}" not in joined:
        return None
    # Only the two documented placeholders are accepted.  format_map will
    # reject unknown names as a second line of defence.
    reduced = joined.replace("{input}", "").replace("{output}", "")
    if "{" in reduced or "}" in reduced:
        return None
    return list(value)


def _is_valid_generated_image(path: Path) -> bool:
    try:
        stat = path.stat()
        if stat.st_size <= 0 or stat.st_size > _MAX_GENERATED_BYTES:
            return False
        Image.MAX_IMAGE_PIXELS = 120_000_000
        with Image.open(path) as image:
            width, height = image.size
            if width < 32 or height < 32 or width > _MAX_IMAGE_EDGE or height > _MAX_IMAGE_EDGE:
                return False
            image.verify()
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


def _build_placeholder(asset: SpeedTreeAsset, cache_dir: Path) -> Path:
    output_dir = cache_dir / "_speedtree_sources"
    output_dir.mkdir(parents=True, exist_ok=True)
    key = _asset_cache_key(asset, extra="placeholder")
    output_path = output_dir / f"{key}_placeholder.png"
    if _is_valid_generated_image(output_path):
        return output_path

    image = Image.new("RGB", (960, 640), "#10271F")
    draw = ImageDraw.Draw(image)
    for y in range(image.height):
        ratio = y / max(1, image.height - 1)
        color = (
            int(16 + 12 * ratio),
            int(39 + 25 * ratio),
            int(31 + 15 * ratio),
        )
        draw.line((0, y, image.width, y), fill=color)

    draw.rounded_rectangle((54, 54, 906, 586), radius=34, fill="#17372C", outline="#3D6E59", width=2)
    draw.ellipse((90, 90, 196, 196), fill="#275A45", outline="#69B98A", width=3)
    # A generic leaf mark denotes the file type; it is not an asset render.
    draw.ellipse((119, 111, 170, 176), fill="#72C792")
    draw.line((126, 171, 169, 117), fill="#D9F3E2", width=4)

    title_font = _load_font(44, bold=True)
    name_font = _load_font(56, bold=True)
    body_font = _load_font(26)
    badge_font = _load_font(24, bold=True)
    draw.text((226, 100), "SPEEDTREE ASSET", font=title_font, fill="#DDF3E5")
    draw.text((226, 157), "PLACEHOLDER  /  NOT A MODEL RENDER", font=body_font, fill="#91B8A3")

    display_name = asset.asset_dir.name if asset.asset_dir != asset.primary_path.parent else asset.primary_path.stem
    display_name = _ellipsize(display_name, 34)
    draw.text((92, 270), display_name, font=name_font, fill="#FFFFFF")

    extensions = sorted({path.suffix.upper() for path in asset.project_files})
    badge_text = " + ".join(extensions) or ".SPM"
    draw.rounded_rectangle((92, 386, 274, 434), radius=14, fill="#2F6B50")
    draw.text((111, 395), _ellipsize(badge_text, 12), font=badge_font, fill="#E9FFF0")
    count_text = f"{len(asset.project_files)} project file" + ("s" if len(asset.project_files) != 1 else "")
    draw.text((300, 395), count_text, font=body_font, fill="#B6D4C3")
    draw.text((92, 506), "No rendered preview was found beside this asset.", font=body_font, fill="#91B8A3")

    temporary_output = output_dir / f".{key}_{os.getpid()}_{uuid.uuid4().hex}.tmp.png"
    try:
        image.save(temporary_output, "PNG", optimize=True)
        os.replace(temporary_output, output_path)
    finally:
        if temporary_output.exists():
            try:
                temporary_output.unlink()
            except OSError:
                pass
    return output_path


def _asset_cache_key(asset: SpeedTreeAsset, *, extra: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"speedtree-preview:{SPEEDTREE_PREVIEW_ADAPTER_VERSION}|{extra}".encode("utf-8"))
    for path in asset.project_files:
        digest.update(str(path).encode("utf-8", errors="surrogatepass"))
        try:
            stat = path.stat()
        except OSError:
            digest.update(b"|missing")
        else:
            digest.update(f"|{stat.st_size}|{stat.st_mtime_ns}".encode("ascii"))
    return digest.hexdigest()[:24]


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates: Iterable[Path] = (
        windows_fonts / ("msyhbd.ttc" if bold else "msyh.ttc"),
        windows_fonts / ("seguisb.ttf" if bold else "segoeui.ttf"),
        windows_fonts / "arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _ellipsize(value: str, limit: int) -> str:
    compact = " ".join(str(value).split())
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)] + "…"
