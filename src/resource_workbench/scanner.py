from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .archive import list_archive_entries
from .file_types import is_archive, is_archive_entrypoint, normalized_ext, texture_name_score, type_bucket


SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".sync",
    "System Volume Information",
    "$RECYCLE.BIN",
}


@dataclass(frozen=True)
class ScanConfig:
    max_files: int = 30000
    max_depth: int = 8
    max_seconds: int = 600
    sample_per_bucket: int = 12
    inspect_archives: bool = False
    split_archive_subresources: bool = False
    max_archives_to_inspect: int = 12
    max_entries_per_archive: int = 300
    archive_timeout_seconds: int = 60
    image_sample_limit: int = 40
    resource_root_depth: int | None = None
    cancel_check: Callable[[], bool] | None = None


def _empty_group(path: str, absolute_path: str | None = None) -> dict:
    return {
        "path": path,
        "absolute_path": absolute_path,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": Counter(),
        "extensions": Counter(),
        "archives": [],
        "inspected_archives": 0,
        "image_candidates": [],
        "video_candidates": [],
        "samples": defaultdict(list),
        "archive_previews": [],
        "archive_virtual_buckets": Counter(),
        "archive_virtual_extensions": Counter(),
        "archive_entry_samples": [],
        "archive_candidate_roots": Counter(),
        "archive_subresources": {},
        "texture_name_hits": 0,
    }


def _add_sample(group: dict, bucket: str, relative_path: str, limit: int) -> None:
    samples = group["samples"][bucket]
    if len(samples) < limit:
        samples.append(relative_path)


def scan_input(input_path: Path, config: ScanConfig | None = None) -> dict:
    config = config or ScanConfig()
    started = time.monotonic()
    input_path = input_path.expanduser().resolve()

    result = {
        "input_path": str(input_path),
        "exists": input_path.exists(),
        "kind": "missing",
        "stopped_early": False,
        "stop_reason": None,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "extensions": Counter(),
        "buckets": Counter(),
        "groups": {},
        "archives": [],
        "inspected_archives": 0,
        "warnings": [],
        "elapsed_seconds": 0.0,
        "resource_root_depth": config.resource_root_depth,
        "split_archive_subresources": config.split_archive_subresources,
        # Keep an explicit snapshot of the folders immediately below the input
        # root.  Groups describe discovered *content* and can legitimately be
        # empty after an I/O error; the snapshot is the invariant used later to
        # make sure a first-level resource folder is never silently omitted.
        "top_level_directories": [],
        "top_level_directory_count": 0,
    }

    if not input_path.exists():
        result["warnings"].append("输入路径不存在。")
        return _json_ready(result)

    if input_path.is_file():
        result["kind"] = "archive" if is_archive(input_path) else "file"
        group = _empty_group(input_path.name, str(input_path))
        pending_archives: list[tuple[dict, Path, str]] = []
        _record_file(result, group, input_path, Path(input_path.name), config, pending_archives)
        _inspect_pending_archives(result, pending_archives, started, config)
        result["groups"][input_path.name] = _json_ready(group)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return _json_ready(result)

    result["kind"] = "directory"
    root_group = _empty_group("(根目录文件)", str(input_path))
    groups: dict[str, dict] = {}
    pending_archives: list[tuple[dict, Path, str]] = []

    # Enumerate the root once up front.  Besides avoiding a second network-drive
    # round trip, this preserves the complete list of first-level resources even
    # when reading one of their children later fails.
    root_entries: list[Path] | None = None
    top_level_by_path: dict[str, dict[str, str]] = {}
    try:
        root_entries = list(input_path.iterdir())
    except OSError as exc:
        result["warnings"].append(f"首次读取根目录失败，将重试：{input_path}；原因：{exc}")

    if root_entries is not None:
        for entry in root_entries:
            try:
                is_top_dir = entry.is_dir()
            except OSError:
                is_top_dir = False
            if is_top_dir and entry.name not in SKIP_DIR_NAMES:
                top_level_by_path[str(entry).casefold()] = {
                    "name": entry.name,
                    "path": str(entry),
                }

    stack: list[tuple[Path, int]] = [(input_path, 0)]
    while stack:
        if config.cancel_check and config.cancel_check():
            result["stopped_early"] = True
            result["stop_reason"] = "用户取消了本次分析。"
            break
        if time.monotonic() - started > config.max_seconds:
            result["stopped_early"] = True
            result["stop_reason"] = f"目录遍历超过 {config.max_seconds} 秒，已停止。"
            break
        if result["total_files"] >= config.max_files:
            result["stopped_early"] = True
            result["stop_reason"] = f"文件数超过 {config.max_files}，已停止。"
            break

        current, depth = stack.pop()
        if depth == 0 and current == input_path and root_entries is not None:
            entries = root_entries
        else:
            try:
                entries = list(current.iterdir())
            except OSError as exc:
                result["warnings"].append(f"无法读取目录：{current}；原因：{exc}")
                continue

        for entry in entries:
            if config.cancel_check and config.cancel_check():
                result["stopped_early"] = True
                result["stop_reason"] = "用户取消了本次分析。"
                break
            try:
                relative = entry.relative_to(input_path)
            except ValueError:
                relative = Path(entry.name)

            if entry.is_dir():
                if entry.name in SKIP_DIR_NAMES:
                    continue
                if depth == 0:
                    top_level_by_path[str(entry).casefold()] = {
                        "name": entry.name,
                        "path": str(entry),
                    }
                result["total_dirs"] += 1
                group_name = _group_name_for_relative_dir(relative, config)
                group_path = input_path / Path(group_name) if group_name != "(根目录文件)" else input_path
                group = root_group if group_name == "(根目录文件)" else groups.setdefault(
                    group_name,
                    _empty_group(group_name, str(group_path)),
                )
                group["total_dirs"] += 1
                if depth < config.max_depth:
                    stack.append((entry, depth + 1))
                else:
                    result["warnings"].append(f"目录深度超过限制，未继续扫描：{relative}")
                continue

            if not entry.is_file():
                continue

            group_name = _group_name_for_relative_file(relative, config)
            group_path = input_path / Path(group_name) if group_name != "(根目录文件)" else input_path
            group = root_group if group_name == "(根目录文件)" else groups.setdefault(group_name, _empty_group(group_name, str(group_path)))
            _record_file(result, group, entry, relative, config, pending_archives)

            if result["total_files"] >= config.max_files:
                break

        if result["stopped_early"]:
            break

    if root_group["total_files"] > 0:
        groups[root_group["path"]] = root_group

    # 目录遍历已完成、所有资源都已成卡；压缩包目录预览作为“尽力而为”的第二阶段，
    # 即使超时也不会再漏掉任何资源。
    _inspect_pending_archives(result, pending_archives, started, config)

    result["top_level_directories"] = sorted(
        top_level_by_path.values(),
        key=lambda item: item["name"].casefold(),
    )
    result["top_level_directory_count"] = len(result["top_level_directories"])
    result["groups"] = {name: _json_ready(group) for name, group in sorted(groups.items())}
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return _json_ready(result)


def _record_file(result: dict, group: dict, file_path: Path, relative: Path, config: ScanConfig,
                 pending_archives: list | None = None) -> None:
    try:
        size = file_path.stat().st_size
    except OSError:
        size = 0

    ext = normalized_ext(file_path)
    bucket = type_bucket(file_path)
    relative_text = str(relative)

    result["total_files"] += 1
    result["total_bytes"] += size
    result["extensions"][ext or "(无扩展名)"] += 1
    result["buckets"][bucket] += 1

    group["total_files"] += 1
    group["total_bytes"] += size
    group["extensions"][ext or "(无扩展名)"] += 1
    group["buckets"][bucket] += 1
    group["texture_name_hits"] += texture_name_score(file_path.name)
    _add_sample(group, bucket, relative_text, config.sample_per_bucket)

    if bucket == "archive":
        archive_info = {
            "relative_path": relative_text,
            "absolute_path": str(file_path),
            "size": size,
            "extension": ext,
        }
        group["archives"].append(archive_info)
        if len(result["archives"]) < 200:
            result["archives"].append(archive_info)
        # 不在遍历阶段内联解析压缩包目录（会拖慢遍历、超时还会漏后面的资源）；
        # 先登记，遍历完再统一解析。
        if pending_archives is not None and config.inspect_archives:
            pending_archives.append((group, file_path, relative_text))
    elif bucket == "image" and len(group["image_candidates"]) < config.image_sample_limit:
        group["image_candidates"].append(str(file_path))
    elif bucket == "video" and len(group["video_candidates"]) < config.sample_per_bucket:
        group["video_candidates"].append(str(file_path))


def _group_name_for_relative_file(relative: Path, config: ScanConfig) -> str:
    return _group_name_for_directory_parts(relative.parts[:-1], config)


def _group_name_for_relative_dir(relative: Path, config: ScanConfig) -> str:
    return _group_name_for_directory_parts(relative.parts, config)


def _group_name_for_directory_parts(parts: tuple[str, ...], config: ScanConfig) -> str:
    if not parts:
        return "(根目录文件)"
    depth = config.resource_root_depth
    if depth == 0:
        return "(根目录文件)"
    if depth is None:
        group_parts = list(parts[:1])
    else:
        group_parts = list(parts[: min(depth, len(parts))])

    # A selected grouping depth can land on implementation folders inside one
    # resource (Textures/Maps/Normal/Roughness/FBX, etc.).  Fold those suffixes
    # back into their owning resource instead of turning them into extra cards.
    while group_parts and _is_resource_fragment_folder(group_parts[-1]):
        group_parts.pop()
    return str(Path(*group_parts)) if group_parts else "(根目录文件)"


def _inspect_pending_archives(result: dict, pending_archives: list, started: float, config: ScanConfig) -> None:
    """遍历完成后，统一解析已登记的压缩包目录（第二阶段，尽力而为）。

    这里超时只会停止预览解析，不会影响已经生成的资源卡片，杜绝“漏资源”。
    """
    if not config.inspect_archives:
        return
    for group, file_path, relative_text in pending_archives:
        if result["inspected_archives"] >= config.max_archives_to_inspect:
            break
        if config.cancel_check and config.cancel_check():
            break
        if time.monotonic() - started > config.max_seconds:
            result["warnings"].append("压缩包目录预览未全部完成（已达时间上限），但资源卡片已完整生成、未漏资源。")
            break
        _maybe_inspect_archive(result, group, file_path, relative_text, config)


def _maybe_inspect_archive(result: dict, group: dict, file_path: Path, relative_text: str, config: ScanConfig) -> None:
    if not config.inspect_archives:
        return
    if result["inspected_archives"] >= config.max_archives_to_inspect:
        return
    if not is_archive_entrypoint(file_path):
        return

    listing = list_archive_entries(
        file_path,
        limit=config.max_entries_per_archive,
        timeout_seconds=config.archive_timeout_seconds,
    )
    result["inspected_archives"] += 1
    group["inspected_archives"] += 1

    preview = {
        "relative_path": relative_text,
        "absolute_path": str(file_path),
        "ok": listing.get("ok"),
        "backend": listing.get("backend"),
        "sample_count": len(listing.get("entries", [])),
        "truncated": listing.get("truncated", False),
        "error": listing.get("error"),
        "samples": [],
        "buckets": Counter(),
        "extensions": Counter(),
        "candidate_roots": Counter(),
    }

    entry_parts: list[list[str]] = []
    entry_records: list[dict] = []
    for index, entry in enumerate(listing.get("entries", [])):
        entry_path = entry.get("Path") or ""
        if not entry_path:
            continue
        if index == 0 and ":" in entry_path[:5]:
            continue

        bucket = type_bucket(entry_path)
        ext = normalized_ext(entry_path) or "(无扩展名)"
        preview["buckets"][bucket] += 1
        preview["extensions"][ext] += 1
        group["archive_virtual_buckets"][bucket] += 1
        group["archive_virtual_extensions"][ext] += 1
        group["texture_name_hits"] += texture_name_score(entry_path)

        if len(preview["samples"]) < config.sample_per_bucket:
            preview["samples"].append(entry_path)
        if len(group["archive_entry_samples"]) < config.sample_per_bucket * 2:
            group["archive_entry_samples"].append(entry_path)
        parts = _split_archive_entry_path(entry_path)
        if parts:
            entry_parts.append(parts)
            entry_records.append(
                {
                    "path": entry_path,
                    "parts": parts,
                    "bucket": bucket,
                    "extension": ext,
                }
            )

    candidate_roots = _candidate_roots_from_parts(entry_parts)
    for candidate, count in candidate_roots.items():
        preview["candidate_roots"][candidate] += count
        group["archive_candidate_roots"][candidate] += count
    if config.split_archive_subresources:
        for record in entry_records:
            candidate = _candidate_for_parts(record["parts"], candidate_roots)
            if candidate:
                _record_archive_subresource(group, candidate, file_path, relative_text, record)

    preview["buckets"] = dict(preview["buckets"].most_common())
    preview["extensions"] = dict(preview["extensions"].most_common(12))
    preview["candidate_roots"] = dict(preview["candidate_roots"].most_common(20))
    group["archive_previews"].append(preview)


def _record_archive_subresource(group: dict, candidate: str, archive_path: Path, archive_relative: str, record: dict) -> None:
    subresources = group["archive_subresources"]
    sub = subresources.setdefault(
        candidate,
        {
            "name": candidate,
            "source_archives": [],
            "total_entries": 0,
            "buckets": Counter(),
            "extensions": Counter(),
            "samples": [],
            "image_samples": [],
            "archive_samples": [],
            "texture_name_hits": 0,
        },
    )
    archive_info = {
        "absolute_path": str(archive_path),
        "relative_path": archive_relative,
    }
    if archive_info not in sub["source_archives"]:
        sub["source_archives"].append(archive_info)

    entry_path = record["path"]
    bucket = record["bucket"]
    ext = record["extension"]
    sub["total_entries"] += 1
    sub["buckets"][bucket] += 1
    sub["extensions"][ext] += 1
    sub["texture_name_hits"] += texture_name_score(entry_path)
    if len(sub["samples"]) < 18:
        sub["samples"].append(entry_path)
    if bucket == "image" and len(sub["image_samples"]) < 6:
        sub["image_samples"].append(
            {
                "archive_path": str(archive_path),
                "entry_path": entry_path,
            }
        )
    elif bucket == "archive" and len(sub["archive_samples"]) < 6:
        sub["archive_samples"].append(entry_path)


def _split_archive_entry_path(entry_path: str) -> list[str]:
    normalized = entry_path.replace("/", "\\")
    return [part for part in normalized.split("\\") if part and not part.endswith(":")]


def _candidate_roots_from_parts(paths: list[list[str]]) -> Counter:
    if not paths:
        return Counter()

    first_counts = Counter(parts[0] for parts in paths if len(parts) >= 1 and _is_meaningful_segment(parts[0]))
    second_counts = Counter(parts[1] for parts in paths if len(parts) >= 2 and _is_meaningful_segment(parts[1]))
    if not first_counts:
        return Counter()

    top_first, top_first_count = first_counts.most_common(1)[0]
    dominant_first = top_first_count / max(1, sum(first_counts.values())) >= 0.8
    meaningful_second_count = len(second_counts)

    if dominant_first and meaningful_second_count >= 3:
        return second_counts
    return first_counts


def _candidate_for_parts(parts: list[str], candidates: Counter) -> str | None:
    if not candidates:
        return None
    if len(parts) >= 2 and parts[1] in candidates:
        return parts[1]
    if parts and parts[0] in candidates:
        return parts[0]
    for part in parts[:3]:
        if part in candidates:
            return part
    return None


# 资源内部的“格式 / 工程 / 通道”子文件夹名。单个资源常按这些拆目录，
# 它们不是独立资源，绝不能各自成卡。
_FORMAT_TOKENS = {
    "fbx", "obj", "blend", "blender", "max", "3dsmax", "3ds", "c4d", "cinema", "cinema4d",
    "maya", "ma", "mb", "marmoset", "toolbag", "unreal", "unrealengine", "ue", "ue4", "ue5",
    "unity", "textures", "texture", "tex", "maps", "map", "materials", "material", "mat", "mats",
    "source", "sources", "sourcefiles", "spp", "substance", "sbsar", "ztl", "zbrush", "zpr", "zbr",
    "render", "renders", "rendering", "preview", "previews", "thumbnail", "thumbnails",
    "lowpoly", "highpoly", "low", "high", "poly", "gltf", "glb", "usd", "usdz", "stl", "abc",
    "alembic", "rig", "rigged", "rigging", "animation", "animations", "anim", "scene", "scenes",
    "scenefile", "scenefiles", "format", "formats", "model", "models", "3d", "uv", "uvs",
    "png", "jpg", "jpeg", "exr", "tga", "tif", "tiff", "psd", "assets", "asset", "images", "image",
    "basecolor", "basecolour", "albedo", "diffuse", "normal", "normals", "nrm", "roughness", "rough", "rgh",
    "metallic", "metalness", "specular", "spec", "gloss", "glossiness", "ao", "ambientocclusion",
    "height", "displacement", "disp", "bump", "opacity", "transparency", "emissive", "emission",
    "mask", "masks", "cavity", "curvature", "subsurface", "sss", "orm", "arm", "pbr", "channel", "channels",
    "1k", "2k", "4k", "8k", "16k",
}
# 连接/填充词：只跟在格式词旁边，不单独构成意义。
_FILLER_TOKENS = {"and", "with", "plus", "amp", "the", "for", "of", "in", "only", "files", "file", "a", "to", "set"}

# 只用于磁盘目录建卡边界，比 ``_FORMAT_TOKENS`` 更保守：像 Models、
# Assets、Images 可能本身就是一个资源合集，不应一概折叠。
_RESOURCE_FRAGMENT_TOKENS = {
    "fbx", "obj", "blend", "blender", "max", "3dsmax", "3ds", "c4d", "maya", "ma", "mb",
    "marmoset", "toolbag", "ue", "ue4", "ue5", "unity", "gltf", "glb", "usd", "usdz", "stl", "abc",
    "textures", "texture", "tex", "maps", "map", "materials", "material", "mats", "mat",
    "source", "sources", "sourcefiles", "preview", "previews", "render", "renders", "thumbnail", "thumbnails",
    "basecolor", "basecolour", "albedo", "diffuse", "normal", "normals", "nrm", "roughness", "rough", "rgh",
    "metallic", "metalness", "specular", "spec", "gloss", "glossiness", "ao", "ambientocclusion",
    "height", "displacement", "disp", "bump", "opacity", "transparency", "emissive", "emission",
    "mask", "masks", "cavity", "curvature", "subsurface", "sss", "orm", "arm", "pbr", "channel", "channels",
    "1k", "2k", "4k", "8k", "16k", "png", "jpg", "jpeg", "exr", "tga", "tif", "tiff", "psd",
}
_CHINESE_FRAGMENT_FOLDERS = {
    "贴图", "贴图文件", "纹理", "材质", "材质贴图", "法线", "法线贴图", "粗糙度", "金属度",
    "置换", "置换贴图", "高度图", "遮罩", "透明度", "预览", "预览图", "渲染", "渲染图", "源文件",
}


def _is_resource_fragment_folder(segment: str) -> bool:
    """Return whether a disk folder is a technical child of one resource."""
    raw = segment.strip().lower()
    if not raw:
        return False
    if raw in _CHINESE_FRAGMENT_FOLDERS:
        return True
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw):
        return False
    words = [word for word in re.split(r"[^0-9a-z]+", raw) if word]
    return bool(words) and any(word in _RESOURCE_FRAGMENT_TOKENS for word in words) and all(
        word in _RESOURCE_FRAGMENT_TOKENS or word in _FILLER_TOKENS for word in words
    )


def _is_format_folder(segment: str) -> bool:
    """判断一个目录名是否只是“格式/工程/通道”子文件夹（如 fbx and blend / obj&textures / marmoset / textures）。"""
    raw = segment.strip().lower()
    if not raw:
        return False
    if raw in _CHINESE_FRAGMENT_FOLDERS:
        return True
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw):  # 含中文 → 视为真实资源名
        return False
    words = [w for w in re.split(r"[^0-9a-z]+", raw) if w]
    if not words:
        return False
    fmt = sum(1 for w in words if w in _FORMAT_TOKENS)
    if fmt == 0:
        return False
    # 全部由格式词 + 连接词组成（且至少含一个真正的格式词）→ 是格式文件夹
    return all(w in _FORMAT_TOKENS or w in _FILLER_TOKENS for w in words)


def _is_meaningful_segment(segment: str) -> bool:
    lower = segment.strip().lower()
    if not lower:
        return False
    if lower in {"assets", "asset", "textures", "texture", "maps", "images", "image", "preview", "previews", "file"}:
        return False
    if _is_format_folder(segment):
        return False
    if re.fullmatch(r"\d{1,3}", lower):
        return False
    if len(lower) < 4:
        return False
    return True


def _json_ready(value):
    if isinstance(value, Counter):
        return dict(value.most_common())
    if isinstance(value, defaultdict):
        return {key: list(items) for key, items in value.items()}
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
