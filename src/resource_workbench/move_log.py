"""可回滚移动日志。

每一次（测试）移动都写一条记录，包含来源、目标、时间、数量/容量校验，
以及当前状态（moved / reverted / revert_failed）。
有了这份日志，移动就可以被审计和撤销，是后续开放正式移动的前提。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

STATUS_MOVED = "moved"
STATUS_REVERTED = "reverted"
STATUS_REVERT_FAILED = "revert_failed"

DEFAULT_MAX_RECORDS = 10_000
DEFAULT_MAX_AGE_DAYS = 730
LEARNING_FEATURE_VERSION = 1


def count_tree(path: Path) -> tuple[int, int]:
    """返回 (文件数, 总字节数)。单文件按 1 个文件计。"""
    path = Path(path)
    if not path.exists():
        return (0, 0)
    if path.is_file():
        try:
            return (1, path.stat().st_size)
        except OSError:
            return (1, 0)
    files = 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            files += 1
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return (files, total)


class MoveLog:
    def __init__(
        self,
        db_path: Path,
        *,
        max_records: int | None = DEFAULT_MAX_RECORDS,
        max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
    ):
        self.db_path = Path(db_path)
        self.max_records = max_records
        self.max_age_days = max_age_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
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
                CREATE TABLE IF NOT EXISTS move_records (
                    move_id TEXT PRIMARY KEY,
                    card_id TEXT,
                    source TEXT,
                    destination TEXT,
                    file_count INTEGER,
                    byte_count INTEGER,
                    dest_file_count INTEGER,
                    dest_byte_count INTEGER,
                    verified INTEGER,
                    status TEXT,
                    note TEXT,
                    moved_at TEXT,
                    updated_at TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(move_records)").fetchall()
            }
            migrations = {
                "move_kind": "TEXT NOT NULL DEFAULT ''",
                "target_directory": "TEXT NOT NULL DEFAULT ''",
                "card_features_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE move_records ADD COLUMN {name} {definition}"
                    )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_move_records_status_time "
                "ON move_records(status, moved_at DESC)"
            )

    def record_move(
        self,
        *,
        source: str,
        destination: str,
        file_count: int,
        byte_count: int,
        dest_file_count: int,
        dest_byte_count: int,
        verified: bool,
        card_id: str | None = None,
        note: str = "",
        card: dict | None = None,
        target_directory: str = "",
        move_kind: str = "",
    ) -> str:
        move_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        card_features_json = json.dumps(
            build_card_learning_features(card or {}),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO move_records
                    (move_id, card_id, source, destination, file_count, byte_count,
                     dest_file_count, dest_byte_count, verified, status, note,
                     moved_at, updated_at, move_kind, target_directory,
                     card_features_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    move_id,
                    card_id or "",
                    source,
                    destination,
                    file_count,
                    byte_count,
                    dest_file_count,
                    dest_byte_count,
                    1 if verified else 0,
                    STATUS_MOVED,
                    note,
                    now,
                    now,
                    str(move_kind or ""),
                    str(target_directory or ""),
                    card_features_json,
                ),
            )
        # 每次写入只做轻量保留策略，不在交互路径里 VACUUM。手动维护时再压缩数据库。
        self.prune(
            max_records=self.max_records,
            max_age_days=self.max_age_days,
            vacuum=False,
            preserve_statuses=(STATUS_MOVED, STATUS_REVERT_FAILED),
        )
        return move_id

    def set_status(self, move_id: str, status: str, *, note: str | None = None) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if note is None:
                cur = conn.execute(
                    "UPDATE move_records SET status = ?, updated_at = ? WHERE move_id = ?",
                    (status, now, move_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE move_records SET status = ?, note = ?, updated_at = ? WHERE move_id = ?",
                    (status, note, now, move_id),
                )
            return cur.rowcount > 0

    def get(self, move_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM move_records WHERE move_id = ?", (move_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None

    def list_records(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM move_records ORDER BY moved_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM move_records WHERE status = ? ORDER BY moved_at DESC",
                    (status,),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def last_movable(self) -> dict | None:
        """最近一条仍处于已移动状态、可撤销的记录。"""
        records = self.list_records(status=STATUS_MOVED)
        return records[0] if records else None

    def learning_records(self, limit: int = 2000) -> list[dict]:
        """返回可用于目标路径学习的成功移动样本。

        只使用仍处于 moved 且数量/容量校验通过的记录；撤销和失败记录不会继续
        影响推荐。旧版数据库没有结构化特征时，会用来源名称和实际目标父目录兜底。
        """
        limit = max(1, min(int(limit), 20_000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM move_records
                WHERE status = ? AND verified = 1
                ORDER BY moved_at DESC
                LIMIT ?
                """,
                (STATUS_MOVED, limit),
            ).fetchall()
        records: list[dict] = []
        for row in rows:
            item = _row_to_dict(row)
            if not item.get("target_directory"):
                destination = str(item.get("destination") or "")
                item["target_directory"] = str(Path(destination).parent) if destination else ""
            features = item.get("card_features") or {}
            if not features.get("keywords"):
                features = build_card_learning_features(
                    {"name": Path(str(item.get("source") or "")).name}
                )
                item["card_features"] = features
            records.append(item)
        return records

    def prune(
        self,
        *,
        max_records: int | None = DEFAULT_MAX_RECORDS,
        max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
        vacuum: bool = False,
        preserve_statuses: Iterable[str] = (STATUS_MOVED, STATUS_REVERT_FAILED),
        dry_run: bool = False,
    ) -> dict:
        """按条数/天数清理已撤销历史，并可执行 SQLite VACUUM。

        只有明确终态 ``reverted`` 会进入候选。仍可撤销的 ``moved``、撤销失败、
        未知/未来状态以及时间戳不可信的记录都永久保护；传空
        ``preserve_statuses`` 也不会把未知状态变成可删除数据。``dry_run`` 只返回
        计划，不执行删除或 VACUUM。
        """
        if max_records is not None and int(max_records) < 0:
            raise ValueError("max_records 不能小于 0")
        if max_age_days is not None and int(max_age_days) < 0:
            raise ValueError("max_age_days 不能小于 0")

        preserve = tuple(dict.fromkeys(str(value) for value in preserve_statuses if value))
        db_bytes_before = self.db_path.stat().st_size if self.db_path.exists() else 0
        with self._connect() as conn:
            before = int(conn.execute("SELECT COUNT(*) FROM move_records").fetchone()[0])
            terminal_statuses = tuple(
                status for status in (STATUS_REVERTED,) if status not in preserve
            )
            if terminal_statuses:
                placeholders = ",".join("?" for _ in terminal_statuses)
                queried_rows = conn.execute(
                    f"SELECT move_id, moved_at FROM move_records "
                    f"WHERE status IN ({placeholders}) "
                    "ORDER BY moved_at ASC, move_id ASC",
                    terminal_statuses,
                ).fetchall()
            else:
                queried_rows = []

            eligible_rows = [
                row for row in queried_rows if _parse_history_timestamp(row["moved_at"]) is not None
            ]
            protected = max(0, before - len(eligible_rows))
            selected: set[str] = set()
            if max_age_days is not None:
                cutoff = datetime.now() - timedelta(days=int(max_age_days))
                selected.update(
                    str(row["move_id"])
                    for row in eligible_rows
                    if (_parse_history_timestamp(row["moved_at"]) or datetime.max) < cutoff
                )

            remaining_after_age = before - len(selected)
            if max_records is not None and remaining_after_age > int(max_records):
                need = remaining_after_age - int(max_records)
                for row in eligible_rows:
                    move_id = str(row["move_id"])
                    if move_id in selected:
                        continue
                    selected.add(move_id)
                    need -= 1
                    if need <= 0:
                        break

            if selected and not dry_run:
                move_ids = sorted(selected)
                for start in range(0, len(move_ids), 500):
                    chunk = move_ids[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(
                        f"DELETE FROM move_records WHERE move_id IN ({placeholders})",
                        chunk,
                    )

        if vacuum and not dry_run:
            with self._connect() as conn:
                conn.execute("VACUUM")

        after = before if dry_run else before - len(selected)
        db_bytes_after = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "ok": True,
            "policy": "terminal_reverted_history",
            "dry_run": bool(dry_run),
            "before": before,
            "after": after,
            "projected_after": before - len(selected),
            "eligible": len(eligible_rows),
            "deleted": 0 if dry_run else len(selected),
            "candidates": len(selected),
            "protected": protected,
            "vacuumed": bool(vacuum and not dry_run),
            "db_bytes_before": db_bytes_before,
            "db_bytes_after": db_bytes_after,
        }


def _parse_history_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["verified"] = bool(data.get("verified"))
    raw_features = data.pop("card_features_json", "{}")
    try:
        features = json.loads(raw_features or "{}")
    except (TypeError, json.JSONDecodeError):
        features = {}
    data["card_features"] = features if isinstance(features, dict) else {}
    return data


def build_card_learning_features(card: dict) -> dict:
    """提取稳定、紧凑且不含 API/绝对来源路径的推荐学习特征。"""

    def strings(value) -> list[str]:  # noqa: ANN001
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if value is not None and str(value).strip() else []

    original_name = str(card.get("name") or "").strip()
    display_name = str(card.get("display_name") or "").strip()
    name = display_name or original_name
    if not name:
        source = str(card.get("source_path") or "")
        name = Path(source).name if source else ""
    suggested_type = str(card.get("suggested_type") or "").strip().lower()
    tags = strings(card.get("content_tags")) + strings(card.get("manual_tags"))
    extensions: list[str] = []
    for field in ("extension_counts", "top_extensions", "top_archive_extensions"):
        extension_counts = card.get(field) or {}
        if isinstance(extension_counts, dict):
            extensions.extend(str(key).lower().lstrip(".") for key in extension_counts if str(key).strip())
    extensions.extend(
        Path(sample).suffix.lower().lstrip(".")
        for sample in strings(card.get("archive_entry_samples"))
        if Path(sample).suffix
    )
    text_parts = [name, original_name, display_name, suggested_type, *tags]
    text_parts.extend(strings(card.get("reasons")))
    text_parts.extend(strings(card.get("archive_entry_samples"))[:30])
    samples = card.get("samples") or {}
    if isinstance(samples, dict):
        sample_names: list[str] = []
        for paths in samples.values():
            sample_names.extend(Path(path).name for path in strings(paths))
        text_parts.extend(sample_names[:40])
    batch_source = str(card.get("batch_source_path") or "").strip()
    if batch_source:
        text_parts.append(Path(batch_source).name)
    keywords = sorted(_learning_tokens(" ".join(text_parts)))[:160]
    return {
        "version": LEARNING_FEATURE_VERSION,
        "name": name[:300],
        "suggested_type": suggested_type[:80],
        "content_tags": sorted({tag.strip() for tag in tags if tag.strip()})[:80],
        "extensions": sorted({ext for ext in extensions if ext})[:80],
        "keywords": keywords,
    }


def _learning_tokens(text: str) -> set[str]:
    normalized = re.sub(r"[\s_\-]+", " ", str(text or "").strip().lower())
    return {
        part
        for part in re.split(r"[\s/\\,.，、;；:：|()（）\[\]{}]+", normalized)
        if len(part) >= 2
    }


def default_move_log_path(project_root: Path) -> Path:
    return Path(project_root) / "workbench_data" / "move_log.sqlite"


def export_records_json(move_log: MoveLog, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(move_log.list_records(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
