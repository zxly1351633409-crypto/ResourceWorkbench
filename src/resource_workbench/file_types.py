from __future__ import annotations

from pathlib import Path


IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".heic",
    ".exr",
    ".hdr",
    ".psd",
    ".ai",
    ".svg",
}

VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
}

AUDIO_EXTS = {
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".m4a",
}

DOCUMENT_EXTS = {
    ".pdf",
    ".txt",
    ".md",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".rtf",
    ".html",
    ".htm",
    ".url",
}

SUBTITLE_EXTS = {
    ".srt",
    ".ass",
    ".vtt",
    ".ssa",
}

MODEL_EXTS = {
    ".fbx",
    ".obj",
    ".blend",
    ".c4d",
    ".max",
    ".ma",
    ".mb",
    ".abc",
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
    ".dae",
    ".gltf",
    ".glb",
    ".3ds",
    ".stl",
    ".spm",
    ".spp",
    ".sbs",
    ".sbsar",
}

ENGINE_EXTS = {
    ".uproject",
    ".uasset",
    ".umap",
    ".unity",
    ".unitypackage",
}

ZBRUSH_EXTS = {
    ".ztl",
    ".zpr",
    ".zbp",
    ".zmt",
    ".zsc",
}

ARCHIVE_EXTS = {
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".iso",
    ".cab",
}

TEXTURE_NAME_HINTS = {
    "albedo",
    "basecolor",
    "base_color",
    "diffuse",
    "normal",
    "roughness",
    "metallic",
    "specular",
    "ao",
    "ambientocclusion",
    "height",
    "displacement",
    "opacity",
}


def normalized_ext(path: Path | str) -> str:
    name = Path(path).name.lower()
    if name.endswith(".tar.gz"):
        return ".tgz"
    if name.endswith(".tar.bz2"):
        return ".tbz2"
    if name.endswith(".tar.xz"):
        return ".txz"
    return Path(name).suffix.lower()


def is_archive(path: Path | str) -> bool:
    name = Path(path).name.lower()
    if normalized_ext(path) in ARCHIVE_EXTS:
        return True
    if ".part" in name and name.endswith(".rar"):
        return True
    if name.endswith(".z01") or name.endswith(".z02") or name.endswith(".001"):
        return True
    return False


def is_archive_entrypoint(path: Path | str) -> bool:
    """Return True when this archive path is likely the first usable volume.

    For multipart archives we should inspect/extract only part1/001, not every
    continuation volume.
    """
    name = Path(path).name.lower()
    if not is_archive(path):
        return False
    if ".part" in name and name.endswith(".rar"):
        return ".part1.rar" in name or ".part01.rar" in name
    if name.endswith(".001"):
        return True
    if name.endswith(".z01") or name.endswith(".z02"):
        return False
    return True


def type_bucket(path: Path | str) -> str:
    ext = normalized_ext(path)
    if is_archive(path):
        return "archive"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in DOCUMENT_EXTS or ext in SUBTITLE_EXTS:
        return "document"
    if ext in MODEL_EXTS:
        return "model"
    if ext in ENGINE_EXTS:
        return "engine"
    if ext in ZBRUSH_EXTS:
        return "zbrush"
    return "other"


def texture_name_score(name: str) -> int:
    lower = name.lower()
    return sum(1 for hint in TEXTURE_NAME_HINTS if hint in lower)
