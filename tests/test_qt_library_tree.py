from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication, QTreeWidgetItem

    import resource_workbench.qt_app as qt_app
    from resource_workbench.qt_app import ResourceWorkbenchWindow
except Exception as exc:  # noqa: BLE001 - PySide may be unavailable on CI.
    QApplication = None
    ResourceWorkbenchWindow = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class _RecordingPool:
    """Record QRunnables so tests can deterministically execute them later."""

    def __init__(self) -> None:
        self.pending = []

    def start(self, task) -> None:
        self.pending.append(task)

    def run_next(self):
        task = self.pending.pop(0)
        task.run()
        QApplication.processEvents()
        return task


@unittest.skipIf(IMPORT_ERROR is not None, f"Qt unavailable: {IMPORT_ERROR}")
class AsyncLibraryTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        if not qt_app.drain_async_pools(15_000):
            raise AssertionError("Qt 后台任务没有在测试类结束前停止")

    def tearDown(self):
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()

    @staticmethod
    def _real_children(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        return [
            item.child(row)
            for row in range(item.childCount())
            if item.child(row).data(0, Qt.UserRole)
        ]

    @staticmethod
    def _status_child(item: QTreeWidgetItem, kind: str) -> QTreeWidgetItem | None:
        for row in range(item.childCount()):
            child = item.child(row)
            if child.data(0, qt_app.TREE_ROLE_KIND) == kind:
                return child
        return None

    @staticmethod
    def _result(task, entries: list[dict], *, total: int | None = None) -> dict:
        count = len(entries)
        total = count if total is None else total
        next_offset = min(total, task.offset + count)
        return {
            "status": "ok",
            "error": "",
            "entries": entries,
            "total": total,
            "offset": task.offset,
            "next_offset": next_offset,
            "remaining": max(0, total - next_offset),
            "path": str(task.path),
            "generation": task.generation,
            "request_id": task.request_id,
        }

    def _new_window(self, data_root: Path) -> ResourceWorkbenchWindow:
        # Never inherit the developer machine's configured resource_root and do
        # not leave startup/maintenance single-shots alive past the test.
        with (
            mock.patch.object(qt_app, "DATA_ROOT", data_root),
            mock.patch.object(qt_app.QTimer, "singleShot", return_value=None),
        ):
            window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
        window.library_poll_timer.stop()
        window.library_refresh_timer.stop()
        window.library_watcher.blockSignals(True)
        return window

    def test_root_and_expand_only_enqueue_background_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            child = root / "Models"
            grandchild = child / "Vehicles"
            grandchild.mkdir(parents=True)
            pool = _RecordingPool()
            window = self._new_window(Path(tmp) / "data")
            try:
                # If populate/expand tried to enumerate synchronously, this
                # patched function would fail the test before a task was queued.
                with (
                    mock.patch.object(qt_app, "_LIBRARY_TREE_POOL", pool),
                    mock.patch.object(
                        qt_app,
                        "_read_library_tree_page",
                        side_effect=AssertionError("GUI thread performed a directory read"),
                    ),
                ):
                    window.populate_path_browser(root)
                    self.assertEqual(len(pool.pending), 1)
                    root_task = pool.pending.pop(0)
                    self.assertIsInstance(root_task, qt_app._LibraryTreeReadTask)
                    self.assertEqual(root_task.path, root)
                    self.assertEqual(root_task.offset, 0)

                    root_item = window.path_tree.topLevelItem(0)
                    self.assertEqual(root_item.data(0, qt_app.TREE_ROLE_REQUEST), root_task.request_id)
                    self.assertIsNotNone(self._status_child(root_item, "loading"))

                    window._on_library_tree_page_ready(
                        self._result(
                            root_task,
                            [
                                {
                                    "name": child.name,
                                    "path": str(child),
                                    "has_children": True,
                                    "probe_error": "",
                                }
                            ],
                        )
                    )
                    qt_app._release_async_task(qt_app._ACTIVE_LIBRARY_TREE_TASKS, root_task)
                    child_item = self._real_children(root_item)[0]
                    self.assertEqual(
                        child_item.data(0, qt_app.TREE_ROLE_GENERATION),
                        window._library_tree_generation,
                    )

                    window.expand_sidebar_path(child_item)
                    self.assertEqual(len(pool.pending), 1)
                    child_task = pool.pending.pop(0)
                    self.assertEqual(child_task.path, child)
                    self.assertEqual(child_task.generation, window._library_tree_generation)
                    self.assertIsNotNone(self._status_child(child_item, "loading"))
                    window._on_library_tree_page_ready(self._result(child_task, []))
                    qt_app._release_async_task(qt_app._ACTIVE_LIBRARY_TREE_TASKS, child_task)
            finally:
                window.deleteLater()

    def test_stale_generation_result_is_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root_a = base / "library-a"
            root_b = base / "library-b"
            child_a = root_a / "Old"
            child_b = root_b / "Current"
            child_a.mkdir(parents=True)
            child_b.mkdir(parents=True)
            pool = _RecordingPool()
            window = self._new_window(base / "data")
            try:
                with mock.patch.object(qt_app, "_LIBRARY_TREE_POOL", pool):
                    window.populate_path_browser(root_a)
                    task_a = pool.pending.pop(0)
                    window.populate_path_browser(root_b)
                    task_b = pool.pending.pop(0)
                    self.assertGreater(task_b.generation, task_a.generation)

                    window._on_library_tree_page_ready(
                        self._result(
                            task_a,
                            [{"name": child_a.name, "path": str(child_a), "has_children": False, "probe_error": ""}],
                        )
                    )
                    qt_app._release_async_task(qt_app._ACTIVE_LIBRARY_TREE_TASKS, task_a)
                    root_item = window.path_tree.topLevelItem(0)
                    self.assertEqual(Path(root_item.data(0, Qt.UserRole)), root_b)
                    self.assertEqual(self._real_children(root_item), [])
                    self.assertEqual(root_item.data(0, qt_app.TREE_ROLE_REQUEST), task_b.request_id)

                    window._on_library_tree_page_ready(
                        self._result(
                            task_b,
                            [{"name": child_b.name, "path": str(child_b), "has_children": False, "probe_error": ""}],
                        )
                    )
                    qt_app._release_async_task(qt_app._ACTIVE_LIBRARY_TREE_TASKS, task_b)
                    paths = [Path(item.data(0, Qt.UserRole)) for item in self._real_children(root_item)]
                    self.assertEqual(paths, [child_b])
                    self.assertNotIn(task_a.request_id, window._library_tree_tasks)
                    self.assertNotIn(task_b.request_id, window._library_tree_tasks)
            finally:
                window.deleteLater()

    def test_close_invalidates_pending_tree_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            child = root / "Too Late"
            child.mkdir(parents=True)
            pool = _RecordingPool()
            window = self._new_window(Path(tmp) / "data")
            try:
                with mock.patch.object(qt_app, "_LIBRARY_TREE_POOL", pool):
                    window.populate_path_browser(root)
                    task = pool.pending.pop(0)
                    generation = window._library_tree_generation

                    window.close()
                    self.assertTrue(window._library_tree_closing)
                    self.assertGreater(window._library_tree_generation, generation)
                    self.assertFalse(window.library_poll_timer.isActive())

                    task.run()
                    QApplication.processEvents()
                    root_item = window.path_tree.topLevelItem(0)
                    self.assertEqual(self._real_children(root_item), [])
                    self.assertNotIn(task.request_id, window._library_tree_tasks)
                    self.assertNotIn(task, qt_app._ACTIVE_LIBRARY_TREE_TASKS)
            finally:
                window.deleteLater()

    def test_four_hundred_item_page_continue_and_restore_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            root.mkdir()
            children = []
            for index in range(qt_app.LIBRARY_TREE_PAGE_SIZE + 5):
                child = root / f"folder-{index:03d}"
                child.mkdir()
                children.append(child)

            pool = _RecordingPool()
            window = self._new_window(Path(tmp) / "data")
            try:
                with mock.patch.object(qt_app, "_LIBRARY_TREE_POOL", pool):
                    window.populate_path_browser(root)
                    pool.run_next()
                    root_item = window.path_tree.topLevelItem(0)
                    first_page = self._real_children(root_item)
                    self.assertEqual(len(first_page), qt_app.LIBRARY_TREE_PAGE_SIZE)
                    more = self._status_child(root_item, "more")
                    self.assertIsNotNone(more)
                    self.assertEqual(more.data(0, qt_app.TREE_ROLE_OFFSET), qt_app.LIBRARY_TREE_PAGE_SIZE)

                    window.open_sidebar_path(more)
                    self.assertEqual(len(pool.pending), 1)
                    self.assertEqual(pool.pending[0].offset, qt_app.LIBRARY_TREE_PAGE_SIZE)
                    pool.run_next()
                    all_items = self._real_children(root_item)
                    all_paths = [Path(item.data(0, Qt.UserRole)) for item in all_items]
                    self.assertEqual(len(all_paths), len(children))
                    self.assertEqual(len(set(all_paths)), len(children))
                    self.assertIsNone(self._status_child(root_item, "more"))

                    # A refresh must automatically fetch the page containing a
                    # previously selected item and restore that selection.
                    last_item = next(item for item in all_items if Path(item.data(0, Qt.UserRole)) == children[-1])
                    window.path_tree.setCurrentItem(last_item)
                    window._refresh_library_tree_preserving_state()
                    self.assertEqual(len(pool.pending), 1)
                    pool.run_next()
                    self.assertEqual(len(pool.pending), 1)
                    self.assertEqual(pool.pending[0].offset, qt_app.LIBRARY_TREE_PAGE_SIZE)
                    pool.run_next()

                    selected = window.path_tree.currentItem()
                    self.assertIsNotNone(selected)
                    self.assertEqual(Path(selected.data(0, Qt.UserRole)), children[-1])
                    refreshed_root = window.path_tree.topLevelItem(0)
                    refreshed_paths = [
                        Path(item.data(0, Qt.UserRole)) for item in self._real_children(refreshed_root)
                    ]
                    self.assertEqual(len(refreshed_paths), len(children))
                    self.assertEqual(len(set(refreshed_paths)), len(children))
            finally:
                window.deleteLater()

    def test_later_page_path_disappearance_preserves_state_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "library"
            root.mkdir()
            for index in range(qt_app.LIBRARY_TREE_PAGE_SIZE + 1):
                (root / f"folder-{index:03d}").mkdir()

            pool = _RecordingPool()
            window = self._new_window(base / "data")
            try:
                with mock.patch.object(qt_app, "_LIBRARY_TREE_POOL", pool):
                    window.populate_path_browser(root)
                    pool.run_next()
                    root_item = window.path_tree.topLevelItem(0)
                    more = self._status_child(root_item, "more")
                    self.assertIsNotNone(more)

                    missing = base / "library-temporarily-missing"
                    root.rename(missing)
                    window.open_sidebar_path(more)
                    failed_task = pool.pending[0]
                    self.assertEqual(failed_task.offset, qt_app.LIBRARY_TREE_PAGE_SIZE)
                    pool.run_next()

                    self.assertEqual(len(self._real_children(root_item)), qt_app.LIBRARY_TREE_PAGE_SIZE)
                    self.assertTrue(root_item.data(0, qt_app.TREE_ROLE_LOADED))
                    self.assertTrue(root_item.data(0, qt_app.TREE_ROLE_HAS_CHILDREN))
                    retry = self._status_child(root_item, "retry")
                    self.assertIsNotNone(retry)
                    self.assertEqual(retry.data(0, qt_app.TREE_ROLE_OFFSET), qt_app.LIBRARY_TREE_PAGE_SIZE)
                    self.assertIn("路径已不存在", retry.text(0))

                    missing.rename(root)
                    window.open_sidebar_path(retry)
                    self.assertEqual(len(pool.pending), 1)
                    self.assertEqual(pool.pending[0].offset, qt_app.LIBRARY_TREE_PAGE_SIZE)
                    pool.run_next()

                    paths = [
                        Path(item.data(0, Qt.UserRole)) for item in self._real_children(root_item)
                    ]
                    self.assertEqual(len(paths), qt_app.LIBRARY_TREE_PAGE_SIZE + 1)
                    self.assertEqual(len(set(paths)), qt_app.LIBRARY_TREE_PAGE_SIZE + 1)
                    self.assertIsNone(self._status_child(root_item, "retry"))
            finally:
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
