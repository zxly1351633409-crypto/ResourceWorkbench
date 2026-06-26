from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .file_types import is_archive, normalized_ext, texture_name_score, type_bucket


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


def _empty_group(path: str) -> dict:
    return {
        "path": path,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": Counter(),
        "extensions": Counter(),
        "archives": [],
        "samples": defaultdict(list),
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
            "size": size,
            "extension": ext,
        }
        group["archives"].append(archive_info)
        if len(result["archives"]) < 200:
            result["archives"].append(archive_info)


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
