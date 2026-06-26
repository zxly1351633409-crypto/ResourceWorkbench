from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


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
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "backend": str(backend.executable),
            "entries": [],
            "error": f"列出压缩包内容超过 {timeout_seconds} 秒，已停止。",
        }

    if completed.returncode != 0:
        fallback_text = completed.stderr.strip() or completed.stdout.strip()
        return {
            "ok": False,
            "backend": str(backend.executable),
            "entries": [],
            "error": fallback_text[-800:],
        }

    entries: list[dict] = []
    current: dict[str, str] = {}
    for raw_line in completed.stdout.splitlines():
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

