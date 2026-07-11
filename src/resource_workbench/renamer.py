"""资源文件夹重命名（翻译后同步改本地目录名）。

- 文件名净化：去掉 Windows 非法字符、收尾空格/点、压缩空白、限长。
- 冲突安全：目标已存在则自动加 (2)(3)…，绝不覆盖。
- 全程记录到重命名日志，可撤销。
- 只改目录名，不移动、不删除内容。
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_ILLEGAL = r'\\/:*?"<>|'
STATUS_RENAMED = "renamed"
STATUS_REVERTED = "reverted"
STATUS_REVERT_FAILED = "revert_failed"


def sanitize_filename(name: str, max_len: int = 150) -> str:
    name = str(name or "").strip()
    name = "".join(("_" if ch in _ILLEGAL else ch) for ch in name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" .")  # Windows 不允许结尾空格或点
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name


def unique_destination(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        alt = parent / f"{name} ({counter})"
        if not alt.exists():
            return alt
        counter += 1


def rename_folder(path: Path, new_name: str, rename_log: "RenameLog | None" = None,
                  card_id: str = "") -> dict:
    src = Path(str(path))
    if not src.exists():
        return {"ok": False, "error": "来源路径不存在。"}
    clean = sanitize_filename(new_name)
    if not clean:
        return {"ok": False, "error": "重命名后的名称为空，已跳过。"}
    if clean == src.name:
        return {"ok": True, "skipped": True, "path": str(src), "reason": "名称未变化。"}
    dest = unique_destination(src.parent, clean)
    try:
        src.rename(dest)
    except OSError as exc:
        return {"ok": False, "error": f"重命名失败：{exc}"}
    rename_id = None
    if rename_log is not None:
        rename_id = rename_log.record(old_path=str(src), new_path=str(dest), card_id=card_id)
    return {"ok": True, "skipped": False, "rename_id": rename_id,
            "old_path": str(src), "path": str(dest), "new_name": dest.name}


def undo_rename(rename_id: str, rename_log: "RenameLog") -> dict:
    rec = rename_log.get(rename_id)
    if rec is None:
        return {"ok": False, "error": f"找不到重命名记录：{rename_id}"}
    if rec.get("status") != STATUS_RENAMED:
        return {"ok": False, "error": f"该记录状态为 {rec.get('status')}，不可撤销。"}
    new_path = Path(rec["new_path"])
    old_path = Path(rec["old_path"])
    if not new_path.exists():
        rename_log.set_status(rename_id, STATUS_REVERT_FAILED, note="当前名称已不存在。")
        return {"ok": False, "error": "当前文件夹已不存在，无法撤销。"}
    if old_path.exists():
        rename_log.set_status(rename_id, STATUS_REVERT_FAILED, note="原名已被占用。")
        return {"ok": False, "error": "原名称已被占用，撤销会冲突，已中止。"}
    try:
        new_path.rename(old_path)
    except OSError as exc:
        rename_log.set_status(rename_id, STATUS_REVERT_FAILED, note=f"撤销失败：{exc}")
        return {"ok": False, "error": f"撤销失败：{exc}"}
    rename_log.set_status(rename_id, STATUS_REVERTED)
    return {"ok": True, "restored_to": str(old_path)}


class RenameLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rename_records (
                    rename_id TEXT PRIMARY KEY,
                    card_id TEXT,
                    old_path TEXT,
                    new_path TEXT,
                    status TEXT,
                    note TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

    def record(self, *, old_path: str, new_path: str, card_id: str = "") -> str:
        rename_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO rename_records (rename_id, card_id, old_path, new_path,"
                " status, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (rename_id, card_id, old_path, new_path, STATUS_RENAMED, "", now, now),
            )
        return rename_id

    def set_status(self, rename_id: str, status: str, *, note: str | None = None) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if note is None:
                cur = conn.execute(
                    "UPDATE rename_records SET status=?, updated_at=? WHERE rename_id=?",
                    (status, now, rename_id))
            else:
                cur = conn.execute(
                    "UPDATE rename_records SET status=?, note=?, updated_at=? WHERE rename_id=?",
                    (status, note, now, rename_id))
            return cur.rowcount > 0

    def get(self, rename_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM rename_records WHERE rename_id=?", (rename_id,)).fetchone()
            return dict(row) if row else None

    def list_records(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM rename_records ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rename_records WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            return [dict(r) for r in rows]


def default_rename_log_path(project_root: Path) -> Path:
    return Path(project_root) / "workbench_data" / "rename_log.sqlite"
