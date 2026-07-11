from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from .archive import extract_archive_entry, silent_subprocess_kwargs
from .speedtree_preview import resolve_speedtree_preview_source


SUPPORTED_PREVIEW_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def prepare_preview_image(
    card: dict,
    cache_dir: Path,
    size: tuple[int, int] = (260, 180),
    preserve_aspect: bool = False,
) -> dict:
    """Prepare a thumbnail preview for a card.

    Returns a dict with ok/path/error. Source resources are never modified.
    """
    cache_dir = Path(cache_dir)
    # SpeedTree cards need special handling before the generic image candidate:
    # texture files are common beside a tree project and must not masquerade as
    # a rendered model preview. The adapter only reuses an explicitly named
    # render or creates a cache-only, clearly labelled placeholder.
    speedtree_source = resolve_speedtree_preview_source(card, cache_dir)
    source = speedtree_source or card.get("preview_source")
    if not source:
        return {"ok": False, "path": None, "error": "没有找到可用预览图。"}

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _source_key(source)
    suffix = "fit" if preserve_aspect else "box"
    final_path = cache_dir / f"{key}.png"
    if preserve_aspect:
        final_path = cache_dir / f"{key}_{suffix}_{size[0]}x{size[1]}.png"
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
    elif source.get("kind") == "video_file":
        video_path = Path(source.get("path", ""))
        if not video_path.exists():
            return {"ok": False, "path": None, "error": "视频预览源不存在。"}
        frame_path = temp_dir / "video_frame.png"
        extracted = _extract_video_frame(video_path, frame_path)
        if not extracted.get("ok"):
            return extracted
        source_path = frame_path
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
            if preserve_aspect:
                if image.mode in {"RGBA", "LA"}:
                    canvas = Image.new("RGBA", image.size, (245, 245, 245, 255))
                    canvas.paste(image.convert("RGBA"), (0, 0), image.convert("RGBA"))
                    canvas.convert("RGB").save(final_path, "PNG")
                else:
                    image.convert("RGB").save(final_path, "PNG")
                return {"ok": True, "path": str(final_path), "error": None}
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
    stat_path = source.get("archive_path") if source.get("kind") == "archive_entry" else source.get("path")
    if stat_path:
        try:
            stat = Path(str(stat_path)).stat()
        except (OSError, ValueError):
            pass
        else:
            raw += f"|size={stat.st_size}|mtime_ns={stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _extract_video_frame(video_path: Path, output_path: Path, timeout_seconds: int = 45) -> dict:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "path": None, "error": "没有找到 ffmpeg，暂时不能从视频生成预览图。"}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-ss",
        "00:00:03",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            **silent_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "path": None, "error": f"生成视频预览超过 {timeout_seconds} 秒，已停止。"}

    if completed.returncode != 0 or not output_path.exists():
        text = _decode_process_output(completed.stderr).strip() or _decode_process_output(completed.stdout).strip()
        return {"ok": False, "path": None, "error": (text[-400:] or "视频预览生成失败。")}

    return {"ok": True, "path": str(output_path), "error": None}


def _decode_process_output(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk", "cp936", "mbcs"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:  # noqa: BLE001 - optional backend
        return None
    return None
