from __future__ import annotations

import re
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .archive import preferred_archive_backend, silent_subprocess_kwargs
from .file_types import is_archive, is_archive_entrypoint
from .passwords import infer_archive_passwords


INVALID_NAME_CHARS = r'<>:"/\|?*'
STAGING_ACTIVITY_MARKER = ".resource_workbench_active"


def extract_archive_to_staging(
    archive_path: Path,
    staging_root: Path,
    timeout_seconds: int = 900,
) -> dict:
    """Extract an archive into a unique staging folder without touching the source."""
    archive_path = archive_path.expanduser().resolve()
    staging_root = staging_root.expanduser().resolve()

    if not archive_path.exists():
        return {"ok": False, "output_dir": None, "error": "源压缩包不存在。"}
    if not archive_path.is_file() or not is_archive(archive_path):
        return {"ok": False, "output_dir": None, "error": "当前来源不是可解压的压缩包。"}
    if not is_archive_entrypoint(archive_path):
        return {"ok": False, "output_dir": None, "error": "这不是分卷压缩包入口，请从 part1 或 001 卷开始。"}

    backend = preferred_archive_backend()
    if backend is None:
        return {"ok": False, "output_dir": None, "error": "没有找到可用的命令行解压工具。"}

    output_dir = _unique_staging_dir(staging_root, archive_path)
    passwords = infer_archive_passwords(archive_path)
    last_error = ""

    for password in passwords:
        _reset_output_dir(output_dir, staging_root)
        _mark_staging_active(output_dir)
        command = [
            str(backend.executable),
            "x",
            "-y",
            f"-p{password}",
            str(archive_path),
            f"-o{output_dir}",
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
            last_error = f"解压超过 {timeout_seconds} 秒，已停止。"
            continue

        if completed.returncode == 0 and _has_extracted_content(output_dir):
            manifest_path = _write_manifest(
                output_dir,
                {
                    "kind": "single_archive",
                    "source": str(archive_path),
                    "source_archives_kept": True,
                    "delete_source_allowed": False,
                    "output_dir": str(output_dir),
                    "backend": str(backend.executable),
                    "password_used": password,
                    "status": "ok",
                },
            )
            _clear_staging_active(output_dir)
            return {
                "ok": True,
                "output_dir": str(output_dir),
                "backend": str(backend.executable),
                "password_used": password,
                "source_archive": str(archive_path),
                "manifest_path": str(manifest_path),
                "error": None,
            }

        fallback_text = _decode_process_output(completed.stderr).strip() or _decode_process_output(completed.stdout).strip()
        last_error = fallback_text[-800:] or "解压失败。"

    manifest_path = _write_manifest(
        output_dir,
        {
            "kind": "single_archive",
            "source": str(archive_path),
            "source_archives_kept": True,
            "delete_source_allowed": False,
            "output_dir": str(output_dir),
            "backend": str(backend.executable),
            "password_used": None,
            "status": "failed",
            "error": last_error or "所有密码候选都无法解压。",
        },
    )
    _clear_staging_active(output_dir)
    return {
        "ok": False,
        "output_dir": str(output_dir),
        "backend": str(backend.executable),
        "password_used": None,
        "manifest_path": str(manifest_path),
        "error": last_error or "所有密码候选都无法解压。",
    }


def extract_folder_archives_to_staging(
    source_dir: Path,
    staging_root: Path,
    max_archives: int = 24,
) -> dict:
    """Extract archive entrypoints found under a folder into one staging batch."""
    source_dir = source_dir.expanduser().resolve()
    staging_root = staging_root.expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        return {"ok": False, "output_dir": None, "error": "来源文件夹不存在。", "archives": []}

    archives: list[Path] = []
    for candidate in source_dir.rglob("*"):
        if candidate.is_file() and is_archive(candidate) and is_archive_entrypoint(candidate):
            archives.append(candidate)
            if len(archives) >= max_archives:
                break

    if not archives:
        return {"ok": True, "output_dir": None, "error": None, "archives": []}

    batch_root = _unique_staging_dir(staging_root, source_dir)
    batch_root.mkdir(parents=True, exist_ok=True)
    _mark_staging_active(batch_root)
    extracted = []
    failures = []
    for archive_path in archives:
        result = extract_archive_to_staging(archive_path, batch_root)
        if result.get("ok"):
            extracted.append(result)
        else:
            failures.append({"archive": str(archive_path), "error": result.get("error")})

    payload = {
        "ok": bool(extracted),
        "output_dir": str(batch_root) if extracted else None,
        "error": None if extracted else "没有压缩包成功解压。",
        "archives": [str(item) for item in archives],
        "extracted": extracted,
        "failures": failures,
    }
    manifest_path = _write_manifest(
        batch_root,
        {
            "kind": "folder_batch",
            "source": str(source_dir),
            "source_archives_kept": True,
            "delete_source_allowed": False,
            "archives": [str(item) for item in archives],
            "extracted": extracted,
            "failures": failures,
            "status": "ok" if extracted else "failed",
        },
    )
    payload["manifest_path"] = str(manifest_path)
    _clear_staging_active(batch_root)
    return payload


def _unique_staging_dir(staging_root: Path, archive_path: Path) -> Path:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = _safe_name(archive_path.stem)[:60] or "archive"
    base = staging_root / f"{now}_{safe_stem}"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = staging_root / f"{base.name}_{suffix:02d}"
    return candidate


def _safe_name(name: str) -> str:
    pattern = f"[{re.escape(INVALID_NAME_CHARS)}]"
    cleaned = re.sub(pattern, "_", name).strip(" .")
    return cleaned or "resource"


def _reset_output_dir(output_dir: Path, staging_root: Path) -> None:
    staging_root.mkdir(parents=True, exist_ok=True)
    resolved_root = staging_root.resolve()
    resolved_output = output_dir.resolve()
    if resolved_root not in [resolved_output, *resolved_output.parents]:
        raise ValueError(f"拒绝清理 staging 外部目录：{output_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _has_extracted_content(output_dir: Path) -> bool:
    try:
        return any(
            child.name not in {STAGING_ACTIVITY_MARKER, "_extraction_manifest.json"}
            for child in output_dir.iterdir()
        )
    except OSError:
        return False


def _decode_process_output(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk", "cp936", "mbcs"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _mark_staging_active(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    marker = root / STAGING_ACTIVITY_MARKER
    marker.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return marker


def _clear_staging_active(root: Path) -> None:
    try:
        (root / STAGING_ACTIVITY_MARKER).unlink(missing_ok=True)
    except OSError:
        # A leftover marker intentionally fails safe: maintenance preserves the
        # batch until the marker is removed after inspection.
        pass


def _write_manifest(root: Path, payload: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "_extraction_manifest.json"
    now = datetime.now().isoformat(timespec="seconds")
    complete_payload = dict(payload)
    complete_payload.setdefault("manifest_schema", 2)
    complete_payload.setdefault("created_at", now)
    complete_payload["completed_at"] = now
    complete_payload["complete"] = True
    path.write_text(json.dumps(complete_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
