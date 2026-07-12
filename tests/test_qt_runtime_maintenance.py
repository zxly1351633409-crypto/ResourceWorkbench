from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from PySide6.QtWidgets import QApplication

    import resource_workbench.qt_app as qt_app
except Exception as exc:  # noqa: BLE001 - optional in headless minimal installs
    QApplication = None
    qt_app = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(IMPORT_ERROR is not None, f"Qt unavailable: {IMPORT_ERROR}")
class QtRuntimeMaintenanceFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _new_window(self, data_root: Path):  # noqa: ANN001
        with (
            mock.patch.object(qt_app, "DATA_ROOT", data_root),
            mock.patch.object(qt_app.QTimer, "singleShot", return_value=None),
        ):
            window = qt_app.ResourceWorkbenchWindow(auto_run=False)
        window.library_poll_timer.stop()
        window.library_refresh_timer.stop()
        return window

    def test_startup_and_manual_checks_are_dispatched_to_background_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            window = self._new_window(Path(tmp))
            try:
                with mock.patch.object(window.runtime_maintenance, "start", return_value=True) as start:
                    window._auto_prune_runtime_data()
                    start.assert_called_once_with(window.settings, dry_run=False)
                window._runtime_maintenance_request = None
                with mock.patch.object(window.runtime_maintenance, "start", return_value=True) as start:
                    window.cleanup_runtime_data(ask_confirmation=False)
                    self.assertTrue(start.call_args.kwargs["dry_run"])
                    self.assertEqual(window._runtime_maintenance_request["kind"], "manual_plan")
            finally:
                window.close()
                window.deleteLater()

    def test_manual_plan_dispatches_apply_only_after_background_plan_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            window = self._new_window(Path(tmp))
            try:
                window._runtime_maintenance_request = {
                    "kind": "manual_plan",
                    "settings": {"preview_cache_max_mb": 10},
                    "ask_confirmation": False,
                }
                plan = {
                    "ok": True,
                    "preview": {"candidate_files": 1, "candidate_bytes": 10},
                    "reports": {},
                    "staging": {},
                    "move_log": {},
                    "resource_index": {},
                    "review_queue": {},
                    "rename_log": {},
                    "upload_log": {},
                    "sqlite_vacuum": {},
                }
                with mock.patch.object(window, "_start_runtime_maintenance", return_value=True) as start:
                    window._on_runtime_maintenance_finished(plan)
                self.assertFalse(start.call_args.kwargs["dry_run"])
                self.assertEqual(start.call_args.kwargs["request"], {"kind": "manual_apply"})
            finally:
                window.close()
                window.deleteLater()

    def test_empty_startup_maintenance_does_not_replace_current_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            window = self._new_window(Path(tmp))
            try:
                window.status_label.setText("用户正在查看的状态")
                window._runtime_maintenance_request = {"kind": "auto_apply"}
                window._on_runtime_maintenance_finished(
                    {
                        "ok": True,
                        "preview": {},
                        "reports": {},
                        "staging": {},
                        "move_log": {},
                        "resource_index": {},
                        "review_queue": {},
                        "rename_log": {},
                        "upload_log": {},
                        "sqlite_vacuum": {},
                    }
                )
                self.assertEqual(window.status_label.text(), "用户正在查看的状态")
            finally:
                window.close()
                window.deleteLater()

    def test_close_waits_for_active_maintenance_thread_then_exits_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            window = self._new_window(Path(tmp))
            entered = threading.Event()
            release = threading.Event()

            def fake_maintain(_root, _settings, *, dry_run):  # noqa: ANN001
                entered.set()
                release.wait(timeout=2)
                return {"ok": True, "dry_run": bool(dry_run)}

            with mock.patch(
                "resource_workbench.runtime_maintenance.maintenance.maintain_workbench_runtime",
                side_effect=fake_maintain,
            ):
                window.show()
                self.assertTrue(
                    window._start_runtime_maintenance({}, dry_run=False, request={"kind": "auto_apply"})
                )
                self.assertTrue(entered.wait(timeout=1))
                window.close()
                self.assertTrue(window._runtime_maintenance_close_pending)
                self.assertTrue(window.isVisible())
                release.set()
                deadline = time.monotonic() + 3
                while (window.runtime_maintenance.busy or window.isVisible()) and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.app.processEvents()
            self.assertFalse(window.runtime_maintenance.busy)
            self.assertFalse(window.isVisible())
            window.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
