"""
CardStore — stable card identity and state management.

Every card gets a stable ``card_id`` derived from its source path
(via ``review_queue.card_identity``).  The frontend references cards
by ``card_id``, never by array index.  The store keeps two separate
collections: *work* (analysis results) and *library* (resource browser).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..review_queue import card_identity


@dataclass
class CardStore:
    """Holds analysed and library cards with stable identity."""

    work_cards: dict[str, dict] = field(default_factory=dict)
    work_order: list[str] = field(default_factory=list)
    library_cards: dict[str, dict] = field(default_factory=dict)
    library_order: list[str] = field(default_factory=list)
    _next_local_id: int = 1

    # ── identity ──────────────────────────────────────────────────

    @staticmethod
    def card_id(card: dict) -> str:
        """Derive a stable id for *card*.  Falls back to sequential local id."""
        try:
            cid = card_identity(card)
            if cid:
                return cid
        except Exception:
            pass
        return f"local:{card.get('source_path', '')}:{card.get('name', '')}"

    # ── work cards ────────────────────────────────────────────────

    def replace_work(self, cards: list[dict]) -> None:
        """Replace the entire work card set (e.g. after a fresh scan)."""
        self.work_cards.clear()
        self.work_order.clear()
        for card in cards:
            cid = self.card_id(card)
            card["card_id"] = cid
            self.work_cards[cid] = card
            self.work_order.append(cid)

    def get_work(self, card_id: str) -> dict | None:
        return self.work_cards.get(card_id)

    def get_work_by_local_index(self, index: int) -> dict | None:
        if 0 <= index < len(self.work_order):
            return self.work_cards[self.work_order[index]]
        return None

    def work_as_list(self) -> list[dict]:
        return [self.work_cards[cid] for cid in self.work_order]

    def update_work(self, card_id: str, updates: dict) -> bool:
        card = self.work_cards.get(card_id)
        if card is None:
            return False
        card.update(updates)
        return True

    @property
    def work_count(self) -> int:
        return len(self.work_order)

    # ── library cards ─────────────────────────────────────────────

    def replace_library(self, cards: list[dict]) -> None:
        self.library_cards.clear()
        self.library_order.clear()
        for card in cards:
            cid = self.card_id(card)
            card["card_id"] = cid
            self.library_cards[cid] = card
            self.library_order.append(cid)

    def get_library(self, card_id: str) -> dict | None:
        return self.library_cards.get(card_id)

    def get_library_by_local_index(self, index: int) -> dict | None:
        if 0 <= index < len(self.library_order):
            return self.library_cards[self.library_order[index]]
        return None

    def get_any(self, card_id: str) -> dict | None:
        """Look up a card by id across both stores."""
        return self.work_cards.get(card_id) or self.library_cards.get(card_id)

    def get_any_by_local_index(self, index: int, *, prefer: str = "work") -> dict | None:
        """Look up by local index across both stores."""
        if prefer == "library":
            card = self.get_library_by_local_index(index)
            if card is not None:
                return card
            return self.get_work_by_local_index(index)
        card = self.get_work_by_local_index(index)
        if card is not None:
            return card
        return self.get_library_by_local_index(index)

    def library_as_list(self) -> list[dict]:
        return [self.library_cards[cid] for cid in self.library_order]

    def update_library(self, card_id: str, updates: dict) -> bool:
        card = self.library_cards.get(card_id)
        if card is None:
            return False
        card.update(updates)
        return True

    @property
    def library_count(self) -> int:
        return len(self.library_order)

    # ── serialisation ─────────────────────────────────────────────

    def serialise_list(self, cards: list[dict]) -> list[dict]:
        """Convert cards for JSON transmission.  Handles Counter, Path, etc."""
        out = []
        for card in cards:
            r = {}
            for k, v in card.items():
                if hasattr(v, "most_common"):
                    r[k] = dict(v.most_common(20))
                elif isinstance(v, Path):
                    r[k] = str(v)
                elif k in ("extensions", "buckets") and isinstance(v, dict):
                    r[k] = {str(k2): v2 for k2, v2 in v.items()}
                else:
                    r[k] = v
            # fill display fields
            r.setdefault("display_name", r.get("name", ""))
            if not r.get("suggested_type") and r.get("media_type"):
                mt_map = {
                    "image": "photo", "video": "video", "model": "model",
                    "engine": "ue", "zbrush": "zbrush",
                }
                r["suggested_type"] = mt_map.get(str(r["media_type"]), "unknown")
            r.setdefault("suggested_type", "unknown")
            # Effective target path: user > ai > library > hints[0]
            r["effective_target_path"] = self._eff_target(r)
            # ensure card_id survives serialisation
            r.setdefault("card_id", card.get("card_id", ""))
            out.append(r)
        return out

    @staticmethod
    def _eff_target(card: dict) -> str:
        """Priority: user_target_path > ai_target_path > library_target_path > target_path_hints[0]."""
        for key in ("user_target_path", "ai_target_path", "library_target_path"):
            val = str(card.get(key) or "").strip()
            if val:
                return val
        hints = card.get("target_path_hints") or []
        if hints and isinstance(hints, list):
            return str(hints[0] or "").strip()
        return ""
