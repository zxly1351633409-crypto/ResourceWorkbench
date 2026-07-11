from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
import time

from .passwords import infer_archive_passwords


@dataclass(frozen=True)
class ArchiveBackend:
    name: str
    executable: Path


KNOWN_7Z_PATHS = [
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
]

KNOWN_HAOZIP_PATHS = [
    Path(r"E:\Haozip\HaoZipC.exe"),
    Path(r"C:\Program Files\2345Soft\HaoZip\HaoZipC.exe"),
    Path(r"C:\Program Files (x86)\2345Soft\HaoZip\HaoZipC.exe"),
]


def silent_subprocess_kwargs() -> dict[str, object]:
    """Return platform-specific options for silent archive commands.

    7-Zip/HaoZip are console programs.  Without these flags Windows creates a
    transient console window which can steal focus from the workbench.
    """
    if os.name != "nt":
        return {}

    kwargs: dict[str, object] = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _subprocess_kwargs() -> dict[str, object]:
    """Backward-compatible private alias used by existing tests."""
    return silent_subprocess_kwargs()


def find_archive_backends() -> list[ArchiveBackend]:
    backends: list[ArchiveBackend] = []

    for command_name in ("7z", "7za", "7zr"):
        found = shutil.which(command_name)
        if found:
            backends.append(ArchiveBackend("7zip", Path(found)))

    for candidate in KNOWN_7Z_PATHS:
        if candidate.exists():
            backends.append(ArchiveBackend("7zip", candidate))

    for candidate in KNOWN_HAOZIP_PATHS:
        if candidate.exists():
            backends.append(ArchiveBackend("haozip", candidate))

    seen: set[Path] = set()
    unique: list[ArchiveBackend] = []
    for backend in backends:
        resolved = backend.executable.resolve()
        if resolved not in seen:
            unique.append(backend)
            seen.add(resolved)
    return unique


def preferred_archive_backend() -> ArchiveBackend | None:
    backends = find_archive_backends()
    if not backends:
        return None
    for backend in backends:
        if backend.name == "7zip":
            return backend
    return backends[0]


def list_archive_entries(archive_path: Path, limit: int = 200, timeout_seconds: int = 30) -> dict:
    backend = preferred_archive_backend()
    if backend is None:
        return {
            "ok": False,
            "backend": None,
            "entries": [],
            "error": "没有找到可用的命令行解压工具。",
        }

    command = [
        str(backend.executable),
        "l",
        "-slt",
        str(archive_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            **_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "backend": str(backend.executable),
            "entries": [],
            "error": f"列出压缩包内容超过 {timeout_seconds} 秒，已停止。",
        }

    if completed.returncode != 0:
        fallback_text = _decode_process_output(completed.stderr).strip() or _decode_process_output(completed.stdout).strip()
        return {
            "ok": False,
            "backend": str(backend.executable),
            "entries": [],
            "error": fallback_text[-800:],
        }

    entries: list[dict] = []
    current: dict[str, str] = {}
    stdout = _decode_process_output(completed.stdout)
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current.get("Path"):
                entries.append(current)
                current = {}
            if len(entries) >= limit:
                break
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key in {"Path", "Size", "Packed Size", "Modified", "Attributes"}:
            current[key] = value

    if current.get("Path") and len(entries) < limit:
        entries.append(current)

    return {
        "ok": True,
        "backend": str(backend.executable),
        "entries": entries[:limit],
        "truncated": len(entries) >= limit,
        "error": None,
    }


def extract_archive_entry(archive_path: Path, entry_path: str, output_dir: Path, timeout_seconds: int = 60) -> dict:
    """Extract one archive entry to a cache directory.

    This is used only for preview images. It does not modify the source archive.
    """
    backend = preferred_archive_backend()
    if backend is None:
        return {
            "ok": False,
            "path": None,
            "error": "没有找到可用的命令行解压工具。",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    before = time.time()
    passwords = infer_archive_passwords(archive_path)
    last_error = ""
    newest: Path | None = None

    for password in passwords:
        before = time.time()
        command = [
            str(backend.executable),
            "e",
            "-y",
            f"-p{password}",
            str(archive_path),
            entry_path,
            f"-o{output_dir}",
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                **_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired:
            last_error = f"抽取预览图超过 {timeout_seconds} 秒，已停止。"
            continue

        extracted_files = [
            item
            for item in output_dir.iterdir()
            if item.is_file() and item.stat().st_mtime >= before - 1
        ]
        if not extracted_files:
            extracted_files = [item for item in output_dir.iterdir() if item.is_file()]
        if extracted_files:
            newest = max(extracted_files, key=lambda item: item.stat().st_mtime)
            break

        fallback_text = _decode_process_output(completed.stderr).strip() or _decode_process_output(completed.stdout).strip()
        last_error = fallback_text[-800:]

    if newest is None:
        return {
            "ok": False,
            "path": None,
            "error": last_error or "预览图抽取完成，但没有找到输出文件。",
        }

    return {
        "ok": True,
        "path": str(newest),
        "error": None,
    }


def _decode_process_output(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk", "cp936", "mbcs"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")
