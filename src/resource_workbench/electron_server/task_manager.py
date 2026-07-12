"""
TaskManager — background task lifecycle with progress and cancellation.

Manages scan, index, translate, and move tasks.  Each task exposes
its current status, progress (0.0–1.0), and a cancel flag so the
frontend can poll progress and safely abort long operations.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TaskKind(Enum):
    SCAN = "scan"
    LIBRARY_LOAD = "library_load"
    TRANSLATE = "translate"
    TRANSLATE_ALL = "translate_all"
    MOVE = "move"
    MAINTENANCE = "maintenance"


@dataclass
class Task:
    kind: TaskKind
    label: str = ""
    progress: float = 0.0
    status_text: str = "等待中"
    cancelled: bool = False
    error: str | None = None
    result: Any = None


class TaskManager:
    """Owns the current foreground task and its cancel token."""

    def __init__(self) -> None:
        self._current: Task | None = None
        self._last_result: Any = None
        self._lock = threading.Lock()
        self._task_id: int = 0

    # ── task lifecycle ────────────────────────────────────────────

    def start(self, kind: TaskKind, label: str = "") -> Task:
        """Begin a new task, atomically replacing any in-progress task."""
        task = Task(kind=kind, label=label)
        with self._lock:
            # Cancel old task by marking it, then atomically swap
            if self._current and not self._current.cancelled:
                self._current.cancelled = True
            self._current = task
            self._task_id += 1
        return task

    def finish(self, result: Any = None) -> None:
        with self._lock:
            if self._current:
                self._current.progress = 1.0
                self._current.status_text = "完成"
                self._current.result = result
                self._last_result = result
                self._current = None

    def fail(self, error: str) -> None:
        with self._lock:
            if self._current:
                self._current.error = error
                self._current.status_text = f"失败: {error[:80]}"
                self._current = None

    def cancel_current(self) -> bool:
        """Signal cancellation.  Returns True if a task was cancelled."""
        with self._lock:
            if self._current and not self._current.cancelled:
                self._current.cancelled = True
                self._current.status_text = "已取消"
                self._current = None
                return True
        return False

    def update_progress(self, progress: float, text: str = "") -> None:
        with self._lock:
            if self._current:
                self._current.progress = max(0.0, min(1.0, progress))
                if text:
                    self._current.status_text = text

    # ── cancel check helper ───────────────────────────────────────

    def cancel_check(self) -> Callable[[], bool]:
        """Return a callable that the scanner can use to poll for cancellation."""
        def _check() -> bool:
            with self._lock:
                if self._current and self._current.cancelled:
                    return True
            return False
        return _check

    # ── status ────────────────────────────────────────────────────

    @property
    def current(self) -> Task | None:
        with self._lock:
            return self._current

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def status_dict(self) -> dict:
        with self._lock:
            if self._current is None:
                return {"busy": False}
            return {
                "busy": True,
                "kind": self._current.kind.value,
                "label": self._current.label,
                "progress": self._current.progress,
                "status_text": self._current.status_text,
                "task_id": self._task_id,
            }
