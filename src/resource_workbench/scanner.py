from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

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
    max_seconds: int = 120
    sample_per_bucket: int = 12
    inspect_archives: bool = True
    max_archives_to_inspect: int = 12
    max_entries_per_archive: int = 300
    archive_timeout_seconds: int = 60


def _empty_group(path: str) -> dict:
    return {
        "path": path,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": Counter(),
        "extensions": Counter(),
        "archives": [],
        "inspected_archives": 0,
        "image_candidates": [],
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
    }

    if not input_path.exists():
        result["warnings"].append("输入路径不存在。")
        return _json_ready(result)

    if input_path.is_file():
        result["kind"] = "archive" if is_archive(input_path) else "file"
        group = _empty_group(input_path.name)
        _record_file(result, group, input_path, Path(input_path.name), config)
        result["groups"][input_path.name] = _json_ready(group)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return _json_ready(result)

    result["kind"] = "directory"
    root_group = _empty_group("(根目录文件)")
    groups: dict[str, dict] = {}

    stack: list[tuple[Path, int]] = [(input_path, 0)]
    while stack:
        if time.monotonic() - started > config.max_seconds:
            result["stopped_early"] = True
            result["stop_reason"] = f"扫描超过 {config.max_seconds} 秒，已停止。"
            break
        if result["total_files"] >= config.max_files:
            result["stopped_early"] = True
            result["stop_reason"] = f"文件数超过 {config.max_files}，已停止。"
            break

        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError as exc:
            result["warnings"].append(f"无法读取目录：{current}；原因：{exc}")
            continue

        for entry in entries:
            try:
                relative = entry.relative_to(input_path)
            except ValueError:
                relative = Path(entry.name)

            if entry.is_dir():
                if entry.name in SKIP_DIR_NAMES:
                    continue
                result["total_dirs"] += 1
                first_part = relative.parts[0] if relative.parts else entry.name
                groups.setdefault(first_part, _empty_group(first_part))["total_dirs"] += 1
                if depth < config.max_depth:
                    stack.append((entry, depth + 1))
                else:
                    result["warnings"].append(f"目录深度超过限制，未继续扫描：{relative}")
                continue

            if not entry.is_file():
                continue

            if relative.parts:
                group_name = relative.parts[0] if len(relative.parts) > 1 else "(根目录文件)"
            else:
                group_name = "(根目录文件)"
            group = root_group if group_name == "(根目录文件)" else groups.setdefault(group_name, _empty_group(group_name))
            _record_file(result, group, entry, relative, config)

            if result["total_files"] >= config.max_files:
                break

    if root_group["total_files"] > 0:
        groups[root_group["path"]] = root_group

    result["groups"] = {name: _json_ready(group) for name, group in sorted(groups.items())}
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return _json_ready(result)


def _record_file(result: dict, group: dict, file_path: Path, relative: Path, config: ScanConfig) -> None:
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
        _maybe_inspect_archive(result, group, file_path, relative_text, config)
    elif bucket == "image" and len(group["image_candidates"]) < config.sample_per_bucket:
        group["image_candidates"].append(str(file_path))


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


def _is_meaningful_segment(segment: str) -> bool:
    lower = segment.strip().lower()
    if not lower:
        return False
    if lower in {"assets", "asset", "textures", "texture", "maps", "images", "image", "preview", "previews", "file"}:
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
