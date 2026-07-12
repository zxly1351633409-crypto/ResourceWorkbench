"""持久化审阅队列。

把扫描出的资源卡片沉淀成一个可持久化、可被外部 Agent 读取的任务队列。
用户从“操作者”变成“审阅者”：软件负责解压/分析/翻译/分类/移动计划，
用户只在队列里逐张确认，确认后才执行移动或上传。

设计原则：
- 纯本地 SQLite，不联网、不移动文件，只记录状态。
- 状态机清晰，便于 GUI 面板和外部 Agent（Hanako/MCP）共享同一份真相。
- 卡片以 card_id 去重；同一来源重复入队只更新建议字段，不覆盖人工已确认的状态。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# 状态机
STATUS_PENDING = "pending"            # 待审阅
STATUS_APPROVED = "approved"          # 已通过，等待执行移动
STATUS_REJECTED = "rejected"          # 否决，不处理
STATUS_NEEDS_RECHECK = "needs_recheck"  # 需重新判断/深度分析
STATUS_MOVED = "moved"                # 已（测试）移动
STATUS_MOVE_FAILED = "move_failed"    # 移动失败
STATUS_UPLOAD_PENDING = "upload_pending"  # 待上传 115
STATUS_DONE = "done"                  # 全流程完成

ALL_STATUSES = (
    STATUS_PENDING,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_NEEDS_RECHECK,
    STATUS_MOVED,
    STATUS_MOVE_FAILED,
    STATUS_UPLOAD_PENDING,
    STATUS_DONE,
)

# 允许人工设置的“建议/计划”字段（不含系统字段）
EDITABLE_FIELDS = (
    "translated_name",
    "target_path",
    "suggested_type",
    "confidence",
    "review_reason",
    "new_folder_needed",
    "note",
)


def card_identity(card: dict) -> str:
    """为卡片生成稳定 id。优先 source_path，回退到拆分名/名称。"""
    basis = (
        str(card.get("source_path") or "")
        or str(card.get("source_url") or "")
        or str(card.get("split_from") or "")
        + "::"
        + str(card.get("name") or card.get("display_name") or "")
    )
    basis = basis.strip().lower()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _primary_target(card: dict) -> str:
    if card.get("user_target_path"):
        return str(card["user_target_path"])
    hints = card.get("target_path_hints") or []
    return str(hints[0]) if hints else ""


class ReviewQueue:
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
                CREATE TABLE IF NOT EXISTS review_items (
                    card_id TEXT PRIMARY KEY,
                    name TEXT,
                    display_name TEXT,
                    source_path TEXT,
                    suggested_type TEXT,
                    target_path TEXT,
                    translated_name TEXT,
                    confidence TEXT,
                    review_reason TEXT,
                    new_folder_needed INTEGER DEFAULT 0,
                    needs_human_review INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT,
                    payload TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

    # ---- 入队 ----
    def enqueue_card(self, card: dict, *, batch_id: str | None = None) -> str:
        card_id = card_identity(card)
        now = datetime.now().isoformat(timespec="seconds")
        target = _primary_target(card)
        payload = dict(card)
        if batch_id:
            payload["batch_id"] = batch_id
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT status, target_path, translated_name FROM review_items WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO review_items
                        (card_id, name, display_name, source_path, suggested_type,
                         target_path, translated_name, confidence, review_reason,
                         new_folder_needed, needs_human_review, status, note,
                         payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_id,
                        card.get("name", ""),
                        card.get("display_name", card.get("name", "")),
                        card.get("source_path", ""),
                        card.get("suggested_type", ""),
                        target,
                        "",
                        card.get("confidence", ""),
                        "",
                        0,
                        1 if card.get("needs_human_review") else 0,
                        STATUS_PENDING,
                        "",
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            else:
                # 已存在：只刷新机器建议字段和 payload，保留人工已设的目标/译名/状态。
                keep_target = existing["target_path"] or target
                conn.execute(
                    """
                    UPDATE review_items
                       SET name = ?, display_name = ?, suggested_type = ?,
                           target_path = ?, confidence = ?, needs_human_review = ?,
                           payload = ?, updated_at = ?
                     WHERE card_id = ?
                    """,
                    (
                        card.get("name", ""),
                        card.get("display_name", card.get("name", "")),
                        card.get("suggested_type", ""),
                        keep_target,
                        card.get("confidence", ""),
                        1 if card.get("needs_human_review") else 0,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        card_id,
                    ),
                )
        return card_id

    def enqueue_cards(self, cards: list[dict], *, batch_id: str | None = None) -> list[str]:
        return [self.enqueue_card(card, batch_id=batch_id) for card in cards]

    # ---- 更新 ----
    def set_status(self, card_id: str, status: str, *, note: str | None = None) -> bool:
        if status not in ALL_STATUSES:
            raise ValueError(f"未知状态：{status}")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if note is None:
                cur = conn.execute(
                    "UPDATE review_items SET status = ?, updated_at = ? WHERE card_id = ?",
                    (status, now, card_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE review_items SET status = ?, note = ?, updated_at = ? WHERE card_id = ?",
                    (status, note, now, card_id),
                )
            return cur.rowcount > 0

    def update_fields(self, card_id: str, **fields) -> bool:
        unknown = set(fields) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"不允许更新字段：{', '.join(sorted(unknown))}")
        if not fields:
            return False
        if "new_folder_needed" in fields:
            fields["new_folder_needed"] = 1 if fields["new_folder_needed"] else 0
        now = datetime.now().isoformat(timespec="seconds")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [now, card_id]
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE review_items SET {assignments}, updated_at = ? WHERE card_id = ?",
                values,
            )
            return cur.rowcount > 0

    def apply_suggestion(self, card_id: str, suggestion: dict) -> bool:
        """把 DeepSeek 结构化建议写入队列项（不改变状态）。"""
        fields = {}
        if suggestion.get("translated_name"):
            fields["translated_name"] = suggestion["translated_name"]
        if suggestion.get("target_path"):
            fields["target_path"] = suggestion["target_path"]
        if suggestion.get("confidence"):
            fields["confidence"] = suggestion["confidence"]
        if suggestion.get("review_reason") is not None:
            fields["review_reason"] = suggestion["review_reason"]
        if "new_folder_needed" in suggestion:
            fields["new_folder_needed"] = bool(suggestion["new_folder_needed"])
        if not fields:
            return False
        return self.update_fields(card_id, **fields)

    def remove(self, card_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM review_items WHERE card_id = ?", (card_id,))
            return cur.rowcount > 0

    def clear(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM review_items")
            return cur.rowcount

    # ---- 查询 ----
    def get(self, card_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_items WHERE card_id = ?", (card_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None

    def list_items(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM review_items ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM review_items WHERE status = ? ORDER BY updated_at DESC",
                    (status,),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def counts_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in ALL_STATUSES}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM review_items GROUP BY status"
            ).fetchall()
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["new_folder_needed"] = bool(data.get("new_folder_needed"))
    data["needs_human_review"] = bool(data.get("needs_human_review"))
    payload = data.get("payload")
    if payload:
        try:
            data["card"] = json.loads(payload)
        except json.JSONDecodeError:
            data["card"] = None
    else:
        data["card"] = None
    return data


def default_queue_path(project_root: Path) -> Path:
    return Path(project_root) / "workbench_data" / "review_queue.sqlite"
