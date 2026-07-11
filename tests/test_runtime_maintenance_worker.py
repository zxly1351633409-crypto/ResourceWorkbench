from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from PySide6.QtCore import QCoreApplication

    from resource_workbench.runtime_maintenance import (
        RuntimeMaintenanceController,
        format_runtime_maintenance_plan,
        summarize_runtime_maintenance,
    )
except ImportError:  # pragma: no cover - optional in headless minimal installs
    QCoreApplication = None
    RuntimeMaintenanceController = None
    format_runtime_maintenance_plan = None
    summarize_runtime_maintenance = None


@unittest.skipIf(QCoreApplication is None, "PySide6 is unavailable")
class RuntimeMaintenanceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _wait_until(self, predicate, timeout: float = 3.0) -> None:  # noqa: ANN001
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "background maintenance did not finish in time")

    def test_work_runs_off_gui_thread_and_duplicate_start_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            controller = RuntimeMaintenanceController(Path(tmp))
            release = threading.Event()
            entered = threading.Event()
            calls: list[tuple[int, bool]] = []
            results: list[dict] = []
            rejected: list[bool] = []

            def fake_maintain(_root, _settings, *, dry_run):  # noqa: ANN001
                calls.append((threading.get_ident(), bool(dry_run)))
                entered.set()
                release.wait(timeout=2)
                return {"ok": True, "dry_run": bool(dry_run)}

            controller.finished.connect(results.append)
            controller.duplicate_rejected.connect(lambda: rejected.append(True))
            gui_thread_id = threading.get_ident()
            with patch(
                "resource_workbench.runtime_maintenance.maintenance.maintain_workbench_runtime",
                side_effect=fake_maintain,
            ):
                self.assertTrue(controller.start({}, dry_run=True))
                self.assertTrue(entered.wait(timeout=1))
                self.assertFalse(controller.start({}, dry_run=False))
                self.assertEqual(rejected, [True])
                release.set()
                self._wait_until(lambda: bool(results))

            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0][0], gui_thread_id)
            self.assertTrue(calls[0][1])
            self.assertFalse(controller.busy)
            self.assertEqual(results[0]["maintenance_mode"], "plan")

    def test_apply_failure_is_returned_without_leaving_busy_guard_stuck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            controller = RuntimeMaintenanceController(Path(tmp))
            results: list[dict] = []
            controller.finished.connect(results.append)
            with patch(
                "resource_workbench.runtime_maintenance.maintenance.maintain_workbench_runtime",
                side_effect=RuntimeError("boom"),
            ):
                self.assertTrue(controller.start({}, dry_run=False))
                self._wait_until(lambda: bool(results))
            self.assertFalse(results[0]["ok"])
            self.assertEqual(results[0]["maintenance_mode"], "apply")
            self.assertIn("boom", results[0]["error"])
            self.assertFalse(controller.busy)

    def test_summary_counts_each_store_once(self) -> None:
        summary = summarize_runtime_maintenance(
            {
                "preview": {"candidate_files": 2, "deleted_files": 1, "candidate_bytes": 20, "deleted_bytes": 10},
                "reports": {"candidates": 3, "deleted": 2},
                "staging": {"candidates": 4, "deleted": 3, "candidate_bytes": 40, "deleted_bytes": 30},
                "move_log": {"candidates": 5, "deleted": 4, "protected": 10},
                "resource_index": {"candidates": 6, "deleted": 5, "protected": 0},
                "review_queue": {"candidates": 7, "deleted": 6, "protected": 11},
                "rename_log": {"candidates": 8, "deleted": 7, "protected": 12},
                "upload_log": {"candidates": 9, "deleted": 8, "protected": 13},
                "sqlite_vacuum": {
                    "one": {"vacuum_candidate": True, "vacuumed": True},
                    "two": {"vacuum_candidate": False, "vacuumed": False},
                },
            }
        )
        self.assertEqual(summary["history_candidates"], 35)
        self.assertEqual(summary["history_deleted"], 30)
        self.assertEqual(summary["protected_history"], 46)
        self.assertEqual(summary["candidate_bytes"], 60)
        self.assertEqual(summary["deleted_bytes"], 40)
        self.assertEqual(summary["vacuum_candidates"], 1)
        self.assertEqual(summary["action_candidates"], 45)

    def test_manual_plan_text_names_every_store_and_protection_rule(self) -> None:
        text = format_runtime_maintenance_plan(
            {
                "preview": {"candidate_files": 2, "candidate_bytes": 2048},
                "reports": {"candidates": 3},
                "move_log": {"candidates": 4},
                "staging": {"candidates": 5, "candidate_bytes": 4096},
                "resource_index": {"candidates": 6},
                "review_queue": {"candidates": 7},
                "rename_log": {"candidates": 8},
                "upload_log": {"candidates": 9},
                "sqlite_vacuum": {"move_log": {"vacuum_candidate": True}},
            }
        )
        for label in (
            "预览缓存",
            "分析报告",
            "移动日志（仅已撤销）",
            "暂存批次（仅完整、过期且非活动）",
            "资源索引",
            "复核历史（仅已完成）",
            "重命名历史（仅已撤销）",
            "上传历史（仅已上传）",
            "SQLite 空闲空间整理候选",
        ):
            self.assertIn(label, text)
        self.assertIn("来源文件从不参与清理", text)
        self.assertIn("用户手工标签、说明和卡片元数据", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
