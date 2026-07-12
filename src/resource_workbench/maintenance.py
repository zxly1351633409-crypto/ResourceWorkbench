"""库维护工具：资源查重 + 空目录清理（只读为主，删除仅限空目录）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path

SKIP = {".git", "__pycache__", "node_modules", ".sync", "System Volume Information", "$RECYCLE.BIN"}
STAGING_MANIFEST = "_extraction_manifest.json"
STAGING_ACTIVITY_MARKER = ".resource_workbench_active"
_SQLITE_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _iter_files(root: Path, max_files: int = 200000):
    count = 0
    for p in root.rglob("*"):
        if any(part in SKIP for part in p.parts):
            continue
        if p.is_file():
            yield p
            count += 1
            if count >= max_files:
                return


def _sha1(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return ""
    return h.hexdigest()


def find_duplicates(root: Path, use_hash: bool = False, max_files: int = 200000) -> list[dict]:
    """按 (文件名小写, 大小) 找疑似重复；use_hash=True 时对候选再用 sha1 确认。

    返回每组：{"key", "size", "count", "paths", "confirmed"}（confirmed 仅在 use_hash 时有效）。
    """
    root = Path(root)
    if not root.exists():
        return []
    buckets: dict[tuple, list[Path]] = defaultdict(list)
    for f in _iter_files(root, max_files=max_files):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        buckets[(f.name.lower(), size)].append(f)

    groups: list[dict] = []
    for (name, size), paths in buckets.items():
        if len(paths) < 2:
            continue
        if use_hash:
            by_hash: dict[str, list[Path]] = defaultdict(list)
            for p in paths:
                by_hash[_sha1(p)].append(p)
            for digest, hpaths in by_hash.items():
                if digest and len(hpaths) >= 2:
                    groups.append({
                        "key": name, "size": size, "count": len(hpaths),
                        "paths": [str(p) for p in hpaths], "confirmed": True,
                    })
        else:
            groups.append({
                "key": name, "size": size, "count": len(paths),
                "paths": [str(p) for p in paths], "confirmed": False,
            })
    groups.sort(key=lambda g: (-g["count"], -g["size"], g["key"]))
    return groups


def find_empty_dirs(root: Path) -> list[str]:
    """找出没有任何文件（递归）的目录，自底向上。"""
    root = Path(root)
    if not root.exists():
        return []
    empties: list[str] = []
    for d in sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        if any(part in SKIP for part in d.parts):
            continue
        try:
            has_file = any(child.is_file() for child in d.rglob("*"))
        except OSError:
            continue
        if not has_file:
            empties.append(str(d))
    return empties


def remove_empty_dirs(root: Path) -> dict:
    """删除空目录（自底向上 rmdir）。只删真正空的目录，安全。"""
    removed: list[str] = []
    for d in find_empty_dirs(root):
        p = Path(d)
        try:
            # 自底向上把链条上的空目录都清掉
            while p != Path(root) and p.is_dir() and not any(p.iterdir()):
                p.rmdir()
                removed.append(str(p))
                p = p.parent
        except OSError:
            continue
    return {"ok": True, "removed": removed, "count": len(removed)}


def prune_cache_directory(
    root: Path,
    *,
    max_bytes: int | None,
    max_age_days: int | None,
    dry_run: bool = False,
) -> dict:
    """Bound a derived-data cache by age and total size.

    Only files discovered below ``root`` are candidates. Source resources are
    never passed here by the workbench.
    """
    root = Path(root)
    if max_bytes is not None and int(max_bytes) < 0:
        raise ValueError("max_bytes 不能小于 0")
    if max_age_days is not None and int(max_age_days) < 0:
        raise ValueError("max_age_days 不能小于 0")
    if not root.exists():
        return {
            "ok": True,
            "root": str(root),
            "before_files": 0,
            "after_files": 0,
            "before_bytes": 0,
            "after_bytes": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "dry_run": bool(dry_run),
        }
    files: list[tuple[Path, int, float]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((path, int(stat.st_size), float(stat.st_mtime)))
    before_bytes = sum(size for _path, size, _mtime in files)
    selected: set[Path] = set()
    if max_age_days is not None:
        cutoff = time.time() - int(max_age_days) * 86_400
        selected.update(path for path, _size, mtime in files if mtime < cutoff)
    remaining_bytes = before_bytes - sum(size for path, size, _mtime in files if path in selected)
    if max_bytes is not None and remaining_bytes > int(max_bytes):
        for path, size, _mtime in sorted(files, key=lambda item: (item[2], str(item[0]).casefold())):
            if path in selected:
                continue
            selected.add(path)
            remaining_bytes -= size
            if remaining_bytes <= int(max_bytes):
                break
    deleted_bytes = sum(size for path, size, _mtime in files if path in selected)
    deleted_files = 0
    if not dry_run:
        for path in selected:
            try:
                path.unlink()
                deleted_files += 1
            except OSError:
                pass
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
    after_files = len(files) - (len(selected) if dry_run else deleted_files)
    after_bytes = before_bytes - (deleted_bytes if dry_run else sum(
        size for path, size, _mtime in files if path in selected and not path.exists()
    ))
    return {
        "ok": True,
        "root": str(root),
        "before_files": len(files),
        "after_files": max(0, after_files),
        "before_bytes": before_bytes,
        "after_bytes": max(0, after_bytes),
        "deleted_files": 0 if dry_run else deleted_files,
        "deleted_bytes": 0 if dry_run else max(0, before_bytes - after_bytes),
        "candidate_files": len(selected),
        "candidate_bytes": deleted_bytes,
        "dry_run": bool(dry_run),
    }


def prune_report_directory(
    root: Path,
    *,
    max_files: int = 400,
    max_age_days: int = 365,
    dry_run: bool = False,
) -> dict:
    """Keep generated Markdown/JSON analysis reports from growing forever."""
    root = Path(root)
    if not root.exists():
        return {"ok": True, "before": 0, "after": 0, "deleted": 0, "dry_run": bool(dry_run)}
    entries: list[tuple[Path, float]] = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".json", ".md"}:
            continue
        try:
            entries.append((path, path.stat().st_mtime))
        except OSError:
            continue
    entries.sort(key=lambda item: (item[1], str(item[0]).casefold()))
    cutoff = time.time() - max(0, int(max_age_days)) * 86_400
    selected = {path for path, mtime in entries if mtime < cutoff}
    remaining = len(entries) - len(selected)
    if remaining > max(0, int(max_files)):
        need = remaining - max(0, int(max_files))
        for path, _mtime in entries:
            if path in selected:
                continue
            selected.add(path)
            need -= 1
            if need <= 0:
                break
    deleted = 0
    if not dry_run:
        for path in selected:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
    return {
        "ok": True,
        "before": len(entries),
        "after": len(entries) - (len(selected) if dry_run else deleted),
        "deleted": 0 if dry_run else deleted,
        "candidates": len(selected),
        "dry_run": bool(dry_run),
    }


def _directory_size(root: Path) -> int:
    """Return the physical file bytes below a workbench-owned directory.

    Directory links are not followed.  This helper is used for reporting only;
    a size calculation never makes a directory eligible for deletion.
    """
    total = 0
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(current) / name).is_symlink()
        ]
        for name in files:
            path = Path(current) / name
            try:
                total += int(path.lstat().st_size)
            except OSError:
                continue
    return total


def _read_complete_staging_manifest(batch: Path) -> tuple[dict | None, str]:
    manifest_path = batch / STAGING_MANIFEST
    if not manifest_path.is_file():
        return None, "missing_manifest"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "invalid_manifest"
    if not isinstance(payload, dict):
        return None, "invalid_manifest"
    required = {
        "manifest_schema",
        "kind",
        "source",
        "source_archives_kept",
        "delete_source_allowed",
        "status",
        "complete",
        "completed_at",
    }
    if not required.issubset(payload):
        return None, "incomplete_manifest"
    try:
        schema = int(payload.get("manifest_schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema < 2 or payload.get("complete") is not True:
        return None, "incomplete_manifest"
    if payload.get("source_archives_kept") is not True or payload.get("delete_source_allowed") is not False:
        return None, "unsafe_manifest"
    if str(payload.get("status") or "") not in {"ok", "failed"}:
        return None, "active_status"
    sources_retained, source_reason = _manifest_sources_retained(payload)
    if not sources_retained:
        return None, source_reason
    return payload, "complete"


def _manifest_sources_retained(payload: dict) -> tuple[bool, str]:
    """Verify that a staging batch is not the last surviving copy of input data."""
    kind = str(payload.get("kind") or "").strip()
    if kind == "single_archive":
        source = str(payload.get("source") or "").strip()
        if not source or not Path(source).is_file():
            return False, "source_archive_missing"
        return True, "retained"
    if kind == "folder_batch":
        archives = payload.get("archives")
        if not isinstance(archives, list) or not archives:
            return False, "source_archive_list_missing"
        for value in archives:
            source = str(value or "").strip()
            if not source or not Path(source).is_file():
                return False, "source_archive_missing"
        return True, "retained"
    return False, "unknown_manifest_kind"


def _manifest_time(payload: dict, manifest_path: Path) -> float:
    for key in ("completed_at", "created_at"):
        raw = str(payload.get(key) or "").strip()
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, OSError, OverflowError):
            continue
    try:
        return float(manifest_path.stat().st_mtime)
    except OSError:
        return 0.0


def prune_staging_batches(
    root: Path,
    *,
    max_age_days: int,
    min_inactive_hours: int = 24,
    dry_run: bool = False,
) -> dict:
    """Remove only completed, inactive, expired extraction batches.

    A top-level staging directory is eligible only when it has a complete
    extraction manifest, confirms that source archives were retained, has no
    activity marker anywhere below it, and is older than both retention gates.
    Unknown/unmanifested directories are reported and preserved.
    """
    if int(max_age_days) < 0:
        raise ValueError("max_age_days 不能小于 0")
    if int(min_inactive_hours) < 0:
        raise ValueError("min_inactive_hours 不能小于 0")
    root = Path(root)
    if not root.exists():
        return {
            "ok": True,
            "root": str(root),
            "before_batches": 0,
            "after_batches": 0,
            "before_bytes": 0,
            "after_bytes": 0,
            "candidates": 0,
            "candidate_bytes": 0,
            "deleted": 0,
            "deleted_bytes": 0,
            "preserved": 0,
            "preserved_reasons": {},
            "dry_run": bool(dry_run),
        }

    now = time.time()
    age_cutoff = now - int(max_age_days) * 86_400
    inactive_cutoff = now - int(min_inactive_hours) * 3_600
    batches = sorted(
        (path for path in root.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.name.casefold(),
    )
    sizes: dict[Path, int] = {batch: _directory_size(batch) for batch in batches}
    selected: list[Path] = []
    reasons: dict[str, int] = defaultdict(int)
    for batch in batches:
        payload, reason = _read_complete_staging_manifest(batch)
        if payload is None:
            reasons[reason] += 1
            continue
        try:
            has_activity_marker = any(
                marker.is_file() for marker in batch.rglob(STAGING_ACTIVITY_MARKER)
            )
        except OSError:
            reasons["unreadable"] += 1
            continue
        if has_activity_marker:
            reasons["active_marker"] += 1
            continue
        completed_at = _manifest_time(payload, batch / STAGING_MANIFEST)
        if completed_at <= 0 or completed_at >= age_cutoff:
            reasons["within_retention"] += 1
            continue
        if completed_at >= inactive_cutoff:
            reasons["recently_active"] += 1
            continue
        selected.append(batch)

    candidate_bytes = sum(sizes[path] for path in selected)
    deleted = 0
    deleted_bytes = 0
    if not dry_run:
        resolved_root = root.resolve()
        for batch in selected:
            try:
                resolved_batch = batch.resolve()
                if resolved_batch.parent != resolved_root:
                    reasons["outside_root"] += 1
                    continue
                shutil.rmtree(batch)
                deleted += 1
                deleted_bytes += sizes[batch]
            except OSError:
                reasons["delete_failed"] += 1

    before_bytes = sum(sizes.values())
    projected_deleted = len(selected) if dry_run else deleted
    projected_bytes = candidate_bytes if dry_run else deleted_bytes
    return {
        "ok": True,
        "root": str(root),
        "before_batches": len(batches),
        "after_batches": max(0, len(batches) - projected_deleted),
        "before_bytes": before_bytes,
        "after_bytes": max(0, before_bytes - projected_bytes),
        "candidates": len(selected),
        "candidate_bytes": candidate_bytes,
        "deleted": 0 if dry_run else deleted,
        "deleted_bytes": 0 if dry_run else deleted_bytes,
        "preserved": len(batches) - len(selected),
        "preserved_reasons": dict(sorted(reasons.items())),
        "dry_run": bool(dry_run),
    }


def _safe_identifier(value: str) -> str:
    if not value or any(char not in _SQLITE_IDENTIFIER_CHARS for char in value):
        raise ValueError(f"不安全的 SQLite 标识符：{value!r}")
    return value


def sqlite_database_stats(db_path: Path, *, table: str | None = None) -> dict:
    """Collect bounded-growth diagnostics without modifying the database."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "exists": False,
            "path": str(db_path),
            "rows": 0,
            "db_bytes": 0,
            "wal_bytes": 0,
            "free_bytes": 0,
        }
    rows = 0
    page_size = 0
    page_count = 0
    freelist_count = 0
    try:
        with closing(sqlite3.connect(str(db_path), timeout=2)) as conn:
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
            freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            if table:
                safe_table = _safe_identifier(table)
                rows = int(conn.execute(f"SELECT COUNT(*) FROM {safe_table}").fetchone()[0])
    except (OSError, sqlite3.Error):
        pass
    wal_path = Path(f"{db_path}-wal")
    try:
        db_bytes = int(db_path.stat().st_size)
    except OSError:
        db_bytes = 0
    try:
        wal_bytes = int(wal_path.stat().st_size)
    except OSError:
        wal_bytes = 0
    return {
        "exists": True,
        "path": str(db_path),
        "rows": rows,
        "db_bytes": db_bytes,
        "wal_bytes": wal_bytes,
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "free_bytes": page_size * freelist_count,
    }


def _timestamp_epoch(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, OSError, OverflowError):
        return 0.0


def prune_sqlite_history(
    db_path: Path,
    *,
    table: str,
    timestamp_column: str,
    max_records: int | None,
    max_age_days: int | None,
    status_column: str | None = None,
    terminal_statuses: tuple[str, ...] = (),
    dry_run: bool = False,
) -> dict:
    """Prune only a caller-declared, demonstrably terminal history subset.

    If ``status_column`` is supplied, rows outside ``terminal_statuses`` are
    protected unconditionally.  The record cap applies to the eligible subset,
    never to active rows.  Databases or schemas that cannot be verified are
    reported and left untouched.
    """
    if max_records is not None and int(max_records) < 0:
        raise ValueError("max_records 不能小于 0")
    if max_age_days is not None and int(max_age_days) < 0:
        raise ValueError("max_age_days 不能小于 0")
    safe_table = _safe_identifier(table)
    safe_timestamp = _safe_identifier(timestamp_column)
    safe_status = _safe_identifier(status_column) if status_column else None
    db_path = Path(db_path)
    initial = sqlite_database_stats(db_path, table=safe_table)
    base = {
        "ok": True,
        "path": str(db_path),
        "policy": "terminal_history" if safe_status else "derived_cache",
        "before": int(initial.get("rows") or 0),
        "after": int(initial.get("rows") or 0),
        "projected_after": int(initial.get("rows") or 0),
        "eligible": 0,
        "protected": 0,
        "candidates": 0,
        "deleted": 0,
        "dry_run": bool(dry_run),
        "db_bytes_before": int(initial.get("db_bytes") or 0),
        "db_bytes_after": int(initial.get("db_bytes") or 0),
        "free_bytes": int(initial.get("free_bytes") or 0),
        "vacuumed": False,
    }
    if not initial.get("exists"):
        base["policy"] = "database_absent"
        return base
    if safe_status and not terminal_statuses:
        base["policy"] = "vacuum_only_no_safe_terminal_status"
        return base

    try:
        with closing(sqlite3.connect(str(db_path), timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {
                str(row[1]) for row in conn.execute(f"PRAGMA table_info({safe_table})").fetchall()
            }
            required = {safe_timestamp}
            if safe_status:
                required.add(safe_status)
            if not required.issubset(columns):
                base["ok"] = False
                base["policy"] = "vacuum_only_unverified_schema"
                return base

            where = ""
            args: list[object] = []
            if safe_status:
                placeholders = ",".join("?" for _ in terminal_statuses)
                where = f"WHERE {safe_status} IN ({placeholders})"
                args.extend(terminal_statuses)
            queried_rows = conn.execute(
                f"SELECT rowid AS _rowid, {safe_timestamp} AS _timestamp "
                f"FROM {safe_table} {where} ORDER BY {safe_timestamp} DESC, rowid DESC",
                args,
            ).fetchall()
            # A missing or malformed timestamp is not a trustworthy historical
            # boundary.  Preserve that row even when a record cap is exceeded.
            rows = [row for row in queried_rows if _timestamp_epoch(row["_timestamp"]) > 0]
            eligible = len(rows)
            selected: set[int] = set()
            if max_age_days is not None:
                cutoff = time.time() - int(max_age_days) * 86_400
                selected.update(
                    int(row["_rowid"])
                    for row in rows
                    if 0 < _timestamp_epoch(row["_timestamp"]) < cutoff
                )
            if max_records is not None:
                keep = max(0, int(max_records))
                selected.update(int(row["_rowid"]) for row in rows[keep:])
            if selected and not dry_run:
                identifiers = sorted(selected)
                for start in range(0, len(identifiers), 500):
                    chunk = identifiers[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(
                        f"DELETE FROM {safe_table} WHERE rowid IN ({placeholders})",
                        chunk,
                    )
                conn.commit()
    except (OSError, sqlite3.Error) as exc:
        base["ok"] = False
        base["error"] = str(exc)
        base["policy"] = "vacuum_only_database_busy_or_invalid"
        return base

    before = int(initial.get("rows") or 0)
    projected_after = max(0, before - len(selected))
    base.update(
        {
            "eligible": eligible,
            "protected": max(0, before - eligible),
            "candidates": len(selected),
            "deleted": 0 if dry_run else len(selected),
            "projected_after": projected_after,
            "after": before if dry_run else projected_after,
        }
    )
    final = sqlite_database_stats(db_path, table=safe_table)
    base["db_bytes_after"] = int(final.get("db_bytes") or 0)
    base["free_bytes"] = int(final.get("free_bytes") or 0)
    return base


def vacuum_sqlite_if_worthwhile(
    db_path: Path,
    *,
    table: str,
    min_reclaim_bytes: int,
    dry_run: bool = False,
) -> dict:
    """VACUUM only when SQLite reports enough reclaimable free pages."""
    stats = sqlite_database_stats(db_path, table=table)
    result = {
        "ok": True,
        "policy": "vacuum_only_manual_data_preserved",
        **stats,
        "vacuum_candidate": bool(
            stats.get("exists") and int(stats.get("free_bytes") or 0) >= max(0, int(min_reclaim_bytes))
        ),
        "vacuumed": False,
        "dry_run": bool(dry_run),
    }
    if not result["vacuum_candidate"] or dry_run:
        return result
    try:
        with closing(sqlite3.connect(str(db_path), timeout=5, isolation_level=None)) as conn:
            conn.execute("VACUUM")
    except (OSError, sqlite3.Error) as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return result
    final = sqlite_database_stats(db_path, table=table)
    result["vacuumed"] = True
    result["db_bytes_after"] = int(final.get("db_bytes") or 0)
    result["free_bytes_after"] = int(final.get("free_bytes") or 0)
    return result


def maintain_workbench_runtime(data_root: Path, settings: dict, *, dry_run: bool = False) -> dict:
    """Apply conservative retention policies to workbench-owned runtime data.

    Source resources are never passed to any deletion helper.  Active workflow
    rows and manual card metadata are preserved regardless of size.
    """
    from .move_log import (
        STATUS_MOVED,
        STATUS_REVERT_FAILED,
        MoveLog,
        default_move_log_path,
    )

    data_root = Path(data_root)
    runtime_root = data_root / "workbench_data"
    preview_limit = max(0, int(settings.get("preview_cache_max_mb") or 0)) * 1024 * 1024
    preview_age = max(0, int(settings.get("preview_cache_max_age_days") or 0))
    log_limit = max(0, int(settings.get("move_log_max_records") or 0))
    log_age = max(0, int(settings.get("move_log_max_age_days") or 0))
    vacuum_min_bytes = max(0, int(settings.get("sqlite_vacuum_min_reclaim_mb") or 8)) * 1024 * 1024
    preview = prune_cache_directory(
        runtime_root / "previews",
        max_bytes=preview_limit,
        max_age_days=preview_age,
        dry_run=dry_run,
    )
    move_log_path = default_move_log_path(data_root)
    if move_log_path.exists():
        move_log = MoveLog(move_log_path, max_records=log_limit, max_age_days=log_age)
        log = move_log.prune(
            max_records=log_limit,
            max_age_days=log_age,
            vacuum=False,
            preserve_statuses=(STATUS_MOVED, STATUS_REVERT_FAILED),
            dry_run=dry_run,
        )
    else:
        log = {
            "ok": True,
            "dry_run": bool(dry_run),
            "before": 0,
            "after": 0,
            "projected_after": 0,
            "deleted": 0,
            "candidates": 0,
            "protected": 0,
            "vacuumed": False,
            "db_bytes_before": 0,
            "db_bytes_after": 0,
            "policy": "database_absent",
        }
    reports = prune_report_directory(data_root / "reports", dry_run=dry_run)
    staging = prune_staging_batches(
        runtime_root / "staging",
        max_age_days=max(0, int(settings.get("staging_max_age_days") or 60)),
        min_inactive_hours=max(0, int(settings.get("staging_min_inactive_hours") or 24)),
        dry_run=dry_run,
    )
    resource_index = prune_sqlite_history(
        runtime_root / "resource_index.sqlite",
        table="resources",
        timestamp_column="indexed_at",
        max_records=max(0, int(settings.get("resource_index_max_records") or 250_000)),
        max_age_days=max(0, int(settings.get("resource_index_max_age_days") or 365)),
        dry_run=dry_run,
    )
    review_queue = prune_sqlite_history(
        runtime_root / "review_queue.sqlite",
        table="review_items",
        timestamp_column="updated_at",
        status_column="status",
        terminal_statuses=("done",),
        max_records=max(0, int(settings.get("review_history_max_records") or 20_000)),
        max_age_days=max(0, int(settings.get("review_history_max_age_days") or 730)),
        dry_run=dry_run,
    )
    rename_log = prune_sqlite_history(
        runtime_root / "rename_log.sqlite",
        table="rename_records",
        timestamp_column="updated_at",
        status_column="status",
        terminal_statuses=("reverted",),
        max_records=max(0, int(settings.get("rename_log_max_records") or 20_000)),
        max_age_days=max(0, int(settings.get("rename_log_max_age_days") or 730)),
        dry_run=dry_run,
    )
    upload_log = prune_sqlite_history(
        runtime_root / "upload_log.sqlite",
        table="upload_records",
        timestamp_column="updated_at",
        status_column="status",
        terminal_statuses=("uploaded",),
        max_records=max(0, int(settings.get("upload_log_max_records") or 20_000)),
        max_age_days=max(0, int(settings.get("upload_log_max_age_days") or 730)),
        dry_run=dry_run,
    )

    sqlite_vacuum = {
        "move_log": vacuum_sqlite_if_worthwhile(
            runtime_root / "move_log.sqlite",
            table="move_records",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
        "resource_index": vacuum_sqlite_if_worthwhile(
            runtime_root / "resource_index.sqlite",
            table="resources",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
        "review_queue": vacuum_sqlite_if_worthwhile(
            runtime_root / "review_queue.sqlite",
            table="review_items",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
        "card_metadata": vacuum_sqlite_if_worthwhile(
            runtime_root / "card_metadata.sqlite",
            table="card_metadata",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
        "rename_log": vacuum_sqlite_if_worthwhile(
            runtime_root / "rename_log.sqlite",
            table="rename_records",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
        "upload_log": vacuum_sqlite_if_worthwhile(
            runtime_root / "upload_log.sqlite",
            table="upload_records",
            min_reclaim_bytes=vacuum_min_bytes,
            dry_run=dry_run,
        ),
    }
    card_metadata = dict(sqlite_vacuum["card_metadata"])
    card_metadata["rows_deleted"] = 0
    card_metadata["manual_data_preserved"] = True
    return {
        "ok": True,
        "preview": preview,
        "move_log": log,
        "reports": reports,
        "staging": staging,
        "resource_index": resource_index,
        "review_queue": review_queue,
        "card_metadata": card_metadata,
        "rename_log": rename_log,
        "upload_log": upload_log,
        "sqlite_vacuum": sqlite_vacuum,
        "dry_run": bool(dry_run),
    }
