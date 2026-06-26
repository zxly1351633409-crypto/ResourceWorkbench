from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from .archive import extract_archive_entry


SUPPORTED_PREVIEW_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def prepare_preview_image(card: dict, cache_dir: Path, size: tuple[int, int] = (260, 180)) -> dict:
    """Prepare a thumbnail preview for a card.

    Returns a dict with ok/path/error. Source resources are never modified.
    """
    source = card.get("preview_source")
    if not source:
        return {"ok": False, "path": None, "error": "没有找到可用预览图。"}

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _source_key(source)
    final_path = cache_dir / f"{key}.png"
    if final_path.exists():
        return {"ok": True, "path": str(final_path), "error": None}

    source_path: Path | None = None
    temp_dir = cache_dir / "_extract" / key
    if source.get("kind") == "file":
        source_path = Path(source.get("path", ""))
    elif source.get("kind") == "archive_entry":
        archive_path = Path(source.get("archive_path", ""))
        entry_path = source.get("entry_path") or ""
        if not archive_path.exists() or not entry_path:
            return {"ok": False, "path": None, "error": "压缩包预览源不存在。"}
        extracted = extract_archive_entry(archive_path, entry_path, temp_dir)
        if not extracted.get("ok"):
            return extracted
        source_path = Path(extracted["path"])
    else:
        return {"ok": False, "path": None, "error": "未知预览源类型。"}

    if source_path is None or not source_path.exists():
        return {"ok": False, "path": None, "error": "预览源文件不存在。"}
    if source_path.suffix.lower() not in SUPPORTED_PREVIEW_EXTS:
        return {"ok": False, "path": None, "error": f"暂不支持这种预览格式：{source_path.suffix}"}

    try:
        Image.MAX_IMAGE_PIXELS = 120_000_000
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", size, (245, 245, 245))
            x = (size[0] - image.width) // 2
            y = (size[1] - image.height) // 2
            if image.mode in {"RGBA", "LA"}:
                canvas.paste(image.convert("RGBA"), (x, y), image.convert("RGBA"))
            else:
                canvas.paste(image.convert("RGB"), (x, y))
            canvas.save(final_path, "PNG")
    except Exception as exc:  # noqa: BLE001 - return GUI-friendly preview failure
        return {"ok": False, "path": None, "error": f"生成预览图失败：{exc}"}
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    return {"ok": True, "path": str(final_path), "error": None}


def _source_key(source: dict) -> str:
    raw = "|".join(str(source.get(key, "")) for key in ("kind", "path", "archive_path", "entry_path"))
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]

