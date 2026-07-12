"""Qt background runner for bounded runtime-data maintenance.

The filesystem and SQLite work can involve large staging trees or databases,
so it must never run on the GUI thread.  The controller owns one worker thread
at a time and rejects duplicate starts until the previous job has fully quit.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from . import maintenance


HISTORY_RESULT_KEYS = (
    "move_log",
    "resource_index",
    "review_queue",
    "rename_log",
    "upload_log",
)

MAINTENANCE_STORE_LABELS = (
    ("preview", "预览缓存", "candidate_files", "deleted_files", "个"),
    ("reports", "分析报告", "candidates", "deleted", "个"),
    ("move_log", "移动日志（仅已撤销）", "candidates", "deleted", "条"),
    ("staging", "暂存批次（仅完整、过期且非活动）", "candidates", "deleted", "个"),
    ("resource_index", "资源索引", "candidates", "deleted", "条"),
    ("review_queue", "复核历史（仅已完成）", "candidates", "deleted", "条"),
    ("rename_log", "重命名历史（仅已撤销）", "candidates", "deleted", "条"),
    ("upload_log", "上传历史（仅已上传）", "candidates", "deleted", "条"),
)


def _format_bytes(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


def summarize_runtime_maintenance(result: dict) -> dict:
    """Return stable UI counts for both dry-run plans and applied results."""
    preview = result.get("preview") or {}
    reports = result.get("reports") or {}
    staging = result.get("staging") or {}
    histories = [result.get(key) or {} for key in HISTORY_RESULT_KEYS]
    vacuums = list((result.get("sqlite_vacuum") or {}).values())
    summary = {
        "preview_candidates": int(preview.get("candidate_files") or 0),
        "preview_deleted": int(preview.get("deleted_files") or 0),
        "report_candidates": int(reports.get("candidates") or 0),
        "report_deleted": int(reports.get("deleted") or 0),
        "staging_candidates": int(staging.get("candidates") or 0),
        "staging_deleted": int(staging.get("deleted") or 0),
        "history_candidates": sum(int(item.get("candidates") or 0) for item in histories),
        "history_deleted": sum(int(item.get("deleted") or 0) for item in histories),
        "protected_history": sum(int(item.get("protected") or 0) for item in histories),
        "vacuum_candidates": sum(bool(item.get("vacuum_candidate")) for item in vacuums),
        "vacuumed": sum(bool(item.get("vacuumed")) for item in vacuums),
        "candidate_bytes": int(preview.get("candidate_bytes") or 0)
        + int(staging.get("candidate_bytes") or 0),
        "deleted_bytes": int(preview.get("deleted_bytes") or 0)
        + int(staging.get("deleted_bytes") or 0),
    }
    summary["action_candidates"] = (
        summary["preview_candidates"]
        + summary["report_candidates"]
        + summary["staging_candidates"]
        + summary["history_candidates"]
        + summary["vacuum_candidates"]
    )
    return summary


def format_runtime_maintenance_plan(result: dict) -> str:
    """Build the full manual-confirmation text without hiding zero-count stores."""
    lines = ["清理计划（只处理工作台自己的派生数据和明确完成的历史）："]
    for key, label, candidate_key, _deleted_key, unit in MAINTENANCE_STORE_LABELS:
        store = result.get(key) or {}
        count = int(store.get(candidate_key) or 0)
        suffix = ""
        if key in {"preview", "staging"}:
            suffix = f"，约 {_format_bytes(int(store.get('candidate_bytes') or 0))}"
        lines.append(f"• {label}：{count} {unit}{suffix}")

    vacuums = list((result.get("sqlite_vacuum") or {}).values())
    vacuum_candidates = sum(bool(item.get("vacuum_candidate")) for item in vacuums)
    lines.extend(
        [
            f"• SQLite 空闲空间整理候选：{vacuum_candidates} 个数据库",
            "",
            "保护规则：",
            "• 正在分析、解压或仍有活动标记的暂存数据不会删除；来源文件从不参与清理。",
            "• 未完成、仍可撤销、失败或未知状态的移动 / 复核 / 重命名 / 上传记录会保留。",
            "• 用户手工标签、说明和卡片元数据只允许整理 SQLite 空闲空间，不删除数据行。",
        ]
    )
    return "\n".join(lines)


class RuntimeMaintenanceWorker(QObject):
    finished = Signal(dict)

    def __init__(self, data_root: Path, settings: dict, *, dry_run: bool) -> None:
        super().__init__()
        self.data_root = Path(data_root)
        self.settings = dict(settings)
        self.dry_run = bool(dry_run)

    @Slot()
    def run(self) -> None:
        started = time.monotonic()
        try:
            result = maintenance.maintain_workbench_runtime(
                self.data_root,
                self.settings,
                dry_run=self.dry_run,
            )
            result = dict(result)
            result.setdefault("ok", True)
        except Exception as exc:  # noqa: BLE001 - send failure back to the GUI
            result = {"ok": False, "error": str(exc), "dry_run": self.dry_run}
        result["maintenance_mode"] = "plan" if self.dry_run else "apply"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        self.finished.emit(result)


class RuntimeMaintenanceController(QObject):
    """Run at most one runtime maintenance job and deliver results on the GUI thread."""

    finished = Signal(dict)
    busy_changed = Signal(bool)
    duplicate_rejected = Signal()

    def __init__(self, data_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.data_root = Path(data_root)
        self._thread: QThread | None = None
        self._worker: RuntimeMaintenanceWorker | None = None
        self._pending_result: dict | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(self, settings: dict, *, dry_run: bool) -> bool:
        if self.busy:
            self.duplicate_rejected.emit()
            return False

        thread = QThread()
        worker = RuntimeMaintenanceWorker(self.data_root, settings, dry_run=dry_run)
        worker.moveToThread(thread)
        self._thread = thread
        self._worker = worker
        self._pending_result = None

        thread.started.connect(worker.run)
        worker.finished.connect(self._store_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_run)
        thread.finished.connect(thread.deleteLater)
        self.busy_changed.emit(True)
        thread.start()
        return True

    @Slot(dict)
    def _store_result(self, result: dict) -> None:
        self._pending_result = dict(result)

    @Slot()
    def _finish_run(self) -> None:
        result = self._pending_result or {
            "ok": False,
            "error": "运行数据维护线程未返回结果。",
        }
        self._thread = None
        self._worker = None
        self._pending_result = None
        self.busy_changed.emit(False)
        self.finished.emit(result)
