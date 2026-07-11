from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .review_queue import card_identity


def default_metadata_path(project_root: Path) -> Path:
    return Path(project_root) / "workbench_data" / "card_metadata.sqlite"


def normalize_tags(tags: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(tags, str):
        raw = tags.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",")
        parts = [part.strip().lstrip("#") for part in raw.split(",")]
    else:
        parts = [str(part).strip().lstrip("#") for part in tags]
    normalized: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        compact = " ".join(part.split())
        key = compact.lower()
        if key in seen:
            continue
        normalized.append(compact)
        seen.add(key)
    return normalized[:24]


class CardMetadataStore:
    def __init__(self, db_path: Path) -> None:
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
                CREATE TABLE IF NOT EXISTS card_metadata (
                    card_id TEXT PRIMARY KEY,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, card_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tags_json, note FROM card_metadata WHERE card_id = ?",
                (card_id,),
            ).fetchone()
        if row is None:
            return {"tags": [], "note": ""}
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except json.JSONDecodeError:
            tags = []
        return {"tags": normalize_tags(tags), "note": str(row["note"] or "")}

    def set(self, card_id: str, tags: str | list[str], note: str) -> None:
        clean_tags = normalize_tags(tags)
        clean_note = str(note or "").strip()
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if clean_tags or clean_note:
                conn.execute(
                    """
                    INSERT INTO card_metadata (card_id, tags_json, note, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        tags_json = excluded.tags_json,
                        note = excluded.note,
                        updated_at = excluded.updated_at
                    """,
                    (card_id, json.dumps(clean_tags, ensure_ascii=False), clean_note, now),
                )
            else:
                conn.execute("DELETE FROM card_metadata WHERE card_id = ?", (card_id,))

    def apply_to_card(self, card: dict) -> dict:
        card_id = card_identity(card)
        metadata = self.get(card_id)
        card["metadata_card_id"] = card_id
        card["manual_tags"] = metadata["tags"]
        card["manual_note"] = metadata["note"]
        return card
