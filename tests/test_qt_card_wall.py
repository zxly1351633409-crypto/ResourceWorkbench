from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication
    import resource_workbench.qt_app as qt_app
    from resource_workbench.card_metadata import CardMetadataStore
    from resource_workbench.qt_app import MaintenanceWorker, MasonryCardWall, ResourceWorkbenchWindow
    from resource_workbench.review_panel import ReviewQueueDialog
except Exception as exc:  # noqa: BLE001 - PySide may be unavailable on CI.
    QApplication = None
    MasonryCardWall = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def _canonical_path(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


@unittest.skipIf(IMPORT_ERROR is not None, f"Qt unavailable: {IMPORT_ERROR}")
class MasonryCardWallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        if not qt_app.drain_async_pools(15_000):
            raise AssertionError("Qt 后台任务没有在测试类结束前停止")

    def setUp(self):
        self._runtime_dir = tempfile.TemporaryDirectory()
        self._data_root_patcher = mock.patch.object(qt_app, "DATA_ROOT", Path(self._runtime_dir.name))
        self._single_shot_patcher = mock.patch.object(qt_app.QTimer, "singleShot", return_value=None)
        self._data_root_patcher.start()
        self._single_shot_patcher.start()

    def tearDown(self):
        try:
            # Finish read-only QRunnables while their receiving widgets and the
            # QApplication still exist. This catches shutdown lifetime bugs and
            # keeps one test's background result out of the next test.
            for pool in (
                qt_app._LIBRARY_TREE_POOL,
                qt_app._LIBRARY_SIGNATURE_POOL,
                qt_app._IMAGE_PREVIEW_POOL,
                qt_app._VIDEO_PREVIEW_POOL,
            ):
                self.assertTrue(pool.waitForDone(15_000), "Qt 后台任务没有在测试清理期内结束")
            QApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QApplication.processEvents()
        finally:
            self._single_shot_patcher.stop()
            self._data_root_patcher.stop()
            self._runtime_dir.cleanup()

    def _wait_for(self, predicate, *, timeout: float = 5.0, message: str = "Qt 后台结果未按时返回"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        QApplication.processEvents()
        self.assertTrue(predicate(), message)

    def test_analysis_status_distinguishes_total_cards_from_review_subset(self):
        text = qt_app.analysis_completion_status(19, 18, 18)
        self.assertIn("共 19 张", text)
        self.assertIn("其中 18 张需确认", text)
        self.assertIn("本次入队 18 张", text)

        existing = qt_app.analysis_completion_status(19, 18, 0)
        self.assertIn("共 19 张", existing)
        self.assertIn("审阅队列已有对应记录", existing)

    def test_archive_reanalysis_label_explicitly_says_no_extraction(self):
        archive_label = qt_app.deep_analysis_action_label({"source_path": "D:/incoming/demo.zip"})
        folder_label = qt_app.deep_analysis_action_label({"source_path": "D:/incoming/demo"})
        self.assertIn("压缩包外层", archive_label)
        self.assertIn("不解压", archive_label)
        self.assertNotIn("解压后", archive_label)
        self.assertIn("不解压压缩包", folder_label)

    def test_normal_analysis_cannot_reenable_automatic_extraction(self):
        worker = qt_app.AnalyzeWorker(Path("demo.zip"), auto_extract_archives=True)
        targets, extraction = worker._scan_targets_for_source(Path("demo.zip"))
        self.assertFalse(worker.auto_extract_archives)
        self.assertEqual(targets, [Path("demo.zip")])
        self.assertIsNone(extraction)

    def test_archive_reanalysis_scans_archive_itself_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "demo.zip"
            archive.write_bytes(b"archive-placeholder")
            scan_result = {
                "input_path": str(archive),
                "kind": "file",
                "total_files": 1,
                "total_dirs": 0,
                "total_bytes": archive.stat().st_size,
                "extensions": {".zip": 1},
                "buckets": {"archive": 1},
                "groups": {},
                "archives": [],
                "warnings": [],
            }
            results = []
            worker = qt_app.DeepAnalyzeWorker(archive, Path(tmp) / "staging")
            worker.finished.connect(results.append)
            with (
                mock.patch.object(qt_app, "scan_input", return_value=scan_result) as scan_input,
                mock.patch.object(qt_app, "build_cards", return_value=[]),
                mock.patch.object(qt_app, "write_reports", return_value={"markdown": str(Path(tmp) / "report.md")}),
            ):
                worker.run()
            self.assertTrue(results[0]["ok"])
            self.assertEqual(Path(results[0]["scan_path"]), archive)
            self.assertIsNone(results[0]["extraction"])
            self.assertEqual(scan_input.call_args.args[0], archive)
            self.assertFalse(scan_input.call_args.kwargs["config"].inspect_archives)

    def test_empty_wall_can_be_set_before_any_rubber_selection(self):
        wall = MasonryCardWall()
        try:
            wall.set_cards([], Path("unused"), lambda _card: "")
            self.assertFalse(wall.empty_label.isHidden())
        finally:
            wall.deleteLater()

    def test_wall_accepts_first_cards_without_empty_label_crash(self):
        wall = MasonryCardWall()
        try:
            card = {
                "name": "Demo Asset",
                "display_name": "Demo Asset",
                "suggested_type": "model",
                "confidence": "medium",
                "target_path_hints": [],
            }
            wall.set_cards([(0, card)], Path("unused"), lambda _card: "")
            self.assertEqual(len(wall.cards), 1)
            self.assertTrue(wall.empty_label.isHidden())
        finally:
            wall.deleteLater()

    def test_selected_card_shows_badge(self):
        wall = MasonryCardWall()
        try:
            card = {
                "name": "Demo Asset",
                "display_name": "Demo Asset",
                "suggested_type": "model",
                "confidence": "medium",
                "target_path_hints": [],
            }
            wall.set_cards([(0, card)], Path("unused"), lambda _card: "")
            wall.select_card(0)
            self.assertFalse(wall.cards[0].selection_badge.isHidden())
            wall.select_card(None)
            self.assertTrue(wall.cards[0].selection_badge.isHidden())
        finally:
            wall.deleteLater()

    def test_select_mode_hides_card_hover_overlay(self):
        wall = MasonryCardWall()
        try:
            card = {
                "name": "Demo Asset",
                "display_name": "Demo Asset",
                "suggested_type": "model",
                "confidence": "medium",
                "target_path_hints": [],
            }
            wall.set_cards([(0, card)], Path("unused"), lambda _card: "")
            wall.cards[0].hover_overlay.show()
            wall.set_select_mode(True)
            self.assertTrue(wall.cards[0].hover_overlay.isHidden())
        finally:
            wall.deleteLater()

    def test_window_selects_first_card_before_select_mode_is_toggled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                card = {
                    "name": "Demo Asset",
                    "display_name": "Demo Asset",
                    "suggested_type": "model",
                    "confidence": "medium",
                    "target_path_hints": [],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], root, 0, True)
                self.assertEqual(window.current_card_index, 0)
                self.assertEqual(window.selected_indices, {0})
            finally:
                window.deleteLater()

    def test_command_bar_uses_one_input_and_separate_cancel_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                self.assertFalse(hasattr(window, "btn_folder"))
                self.assertFalse(hasattr(window, "btn_archive"))
                self.assertFalse(hasattr(window, "btn_web"))
                self.assertTrue(window.depth_combo.isHidden())
                self.assertTrue(window.filter_edit.isHidden())
                self.assertTrue(window.btn_cancel_analysis.isHidden())
                self.assertEqual(window.command_bar.height(), 58)
            finally:
                window.deleteLater()

    def test_version_is_only_shown_as_small_sidebar_footer_label(self):
        window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
        try:
            self.assertEqual(window.windowTitle(), "资源入库工作台")
            self.assertFalse(hasattr(window, "header_title"))
            self.assertEqual(window.version_label.text(), f"v{qt_app.__version__}")
            self.assertEqual(window.version_label.objectName(), "TinyText")
        finally:
            window.deleteLater()

    def test_settings_and_semantic_theme_standard_buttons_are_chinese(self):
        settings_dialog = qt_app.SettingsDialog({}, None)
        theme_dialog = qt_app.SemanticThemeDialog({}, None)
        try:
            settings_texts = {
                button.text()
                for box in settings_dialog.findChildren(qt_app.QDialogButtonBox)
                for button in box.buttons()
            }
            theme_texts = {
                button.text()
                for box in theme_dialog.findChildren(qt_app.QDialogButtonBox)
                for button in box.buttons()
            }
            self.assertIn("保存设置", settings_texts)
            self.assertIn("取消", settings_texts)
            self.assertIn("应用配色", theme_texts)
            self.assertIn("取消", theme_texts)
            self.assertGreaterEqual(theme_dialog.minimumWidth(), 820)
        finally:
            settings_dialog.deleteLater()
            theme_dialog.deleteLater()

    def test_library_video_content_overrides_photo_parent_name(self):
        window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
        try:
            card = window._classify_library_quick_card(
                {
                    "source_path": r"\\server\share\Z 照片\G 中国古建\寺庙\drone.mov",
                    "media_type": "video",
                    "suggested_type": "unknown",
                }
            )
            self.assertEqual(card["suggested_type"], "video")
            self.assertEqual(card["content_tags"], ["已入库", "视频"])
            self.assertIn("实际文件媒体类型", card["reasons"][0])
        finally:
            window.deleteLater()

    def test_sidebar_create_folder_creates_inside_selected_library_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir()
            window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
            try:
                window.settings["resource_root"] = str(library)
                window.populate_path_browser(library)
                with (
                    mock.patch.object(qt_app.QInputDialog, "getText", return_value=("新分类", True)),
                    mock.patch.object(window, "quick_browse_path") as browse,
                ):
                    window.create_library_folder()
                self.assertTrue((library / "新分类").is_dir())
                browse.assert_called_once()
            finally:
                window.deleteLater()

    def test_unified_input_parses_local_paths_and_web_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
            try:
                window.path_edit.setText(f'"{root}"; https://shotdeck.com/browse/stills\nwww.example.com/page')
                paths, urls = window._analysis_inputs_from_edit()
                self.assertEqual(paths, [root])
                self.assertEqual(
                    urls,
                    ["https://shotdeck.com/browse/stills", "https://www.example.com/page"],
                )
            finally:
                window.deleteLater()

    def test_editing_finished_does_not_start_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
            try:
                window.path_edit.setText(tmp)
                window.path_edit.editingFinished.emit()
                QApplication.processEvents()
                self.assertIsNone(window.thread)
                self.assertIsNone(window.worker)
            finally:
                window.deleteLater()

    def test_analyze_worker_accepts_web_only_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_card = {
                "resource_kind": "web",
                "name": "ShotDeck",
                "display_name": "ShotDeck",
                "source_url": "https://shotdeck.com/browse/stills",
                "suggested_type": "photo",
                "confidence": "medium",
                "content_tags": ["网页"],
                "target_suggestions": [],
                "target_path_hints": [],
                "needs_human_review": True,
                "archive_count": 0,
                "source_archive_count": 0,
                "inspected_archives": 0,
                "virtual_archive_count": 0,
                "total_files": 1,
                "total_dirs": 0,
                "total_bytes": 0,
                "buckets": {"web": 1},
                "reasons": ["test"],
            }
            results = []
            progress = []
            worker = qt_app.AnalyzeWorker(
                [],
                web_urls=["https://shotdeck.com/browse/stills"],
                web_preview_cache_dir=root / "previews",
            )
            worker.finished.connect(results.append)
            worker.progress.connect(lambda text, value: progress.append((text, value)))
            with mock.patch.object(qt_app, "DATA_ROOT", root):
                with mock.patch.object(qt_app, "create_web_resource_card", return_value=fake_card):
                    worker.run()
            self.assertTrue(results[0]["ok"])
            self.assertEqual(results[0]["scan"]["web_resource_count"], 1)
            self.assertEqual(len(results[0]["cards"]), 1)
            self.assertEqual(progress[-1][1], 100)

    def test_window_enqueue_review_cards_only_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                window.review_queue = qt_app.ReviewQueue(root / "queue.sqlite")
                cards = [
                    {"name": "Needs Review", "source_path": str(root / "a"), "needs_human_review": True},
                    {"name": "Confident", "source_path": str(root / "b"), "needs_human_review": False},
                ]
                count = window._enqueue_review_cards(cards)
                self.assertEqual(count, 1)
                self.assertEqual(len(window.review_queue.list_items()), 1)
            finally:
                window.deleteLater()

    def test_review_queue_dialog_shows_selected_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image

            root = Path(tmp)
            preview = root / "cover.png"
            Image.new("RGB", (96, 54), (30, 90, 160)).save(preview)
            queue = qt_app.ReviewQueue(root / "queue.sqlite")
            queue.enqueue_card(
                {
                    "name": "Preview Asset",
                    "display_name": "Preview Asset",
                    "source_path": str(root / "asset"),
                    "suggested_type": "model",
                    "confidence": "low",
                    "needs_human_review": True,
                    "target_path_hints": [str(root / "Z" / "M 模型")],
                    "preview_source": {"kind": "file", "path": str(preview)},
                    "reasons": ["测试预览图"],
                }
            )
            dialog = ReviewQueueDialog(queue, preview_cache_dir=root / "previews")
            try:
                QApplication.processEvents()
                dialog.list_widget.setCurrentRow(0)
                QApplication.processEvents()
                pixmap = dialog.preview_label.pixmap()
                self.assertIsNotNone(pixmap)
                self.assertFalse(pixmap.isNull())
                self.assertIn("Preview Asset", dialog.detail_text.toPlainText())
            finally:
                dialog.deleteLater()

    def test_maintenance_worker_reports_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "dup.txt").write_text("same", encoding="utf-8")
            (root / "b" / "dup.txt").write_text("same", encoding="utf-8")
            results = []
            worker = MaintenanceWorker("dedupe", root, use_hash=True)
            worker.finished.connect(results.append)
            worker.run()
            self.assertTrue(results)
            self.assertTrue(results[0]["ok"])
            self.assertEqual(len(results[0]["groups"]), 1)

    def test_format_selected_cards_applies_cover_project_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / "RobotLeg"
            resource.mkdir()
            (resource / "cover.jpg").write_bytes(b"x" * 2000)
            (resource / "leg.fbx").write_text("fbx", encoding="utf-8")
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            original_question = qt_app.QMessageBox.question
            try:
                qt_app.QMessageBox.question = lambda *args, **kwargs: qt_app.QMessageBox.Yes
                card = {
                    "name": "RobotLeg",
                    "display_name": "RobotLeg",
                    "source_path": str(resource),
                    "suggested_type": "model",
                    "confidence": "medium",
                    "target_path_hints": [],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], root, 0, True)
                window.selected_indices = {0}
                window.format_selected_cards()
                self.assertTrue((resource / "cover.jpg").exists())
                self.assertTrue((resource / "工程" / "leg.fbx").exists())
            finally:
                qt_app.QMessageBox.question = original_question
                window.deleteLater()

    def test_manual_tags_are_saved_and_filterable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / "Basalt"
            resource.mkdir()
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                window.card_metadata = CardMetadataStore(root / "metadata.sqlite")
                card = {
                    "name": "Basalt",
                    "display_name": "Basalt",
                    "source_path": str(resource),
                    "suggested_type": "photo",
                    "confidence": "medium",
                    "target_path_hints": [],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], root, 0, True)
                window._save_card_metadata(window.cards[0], ["玄武岩", "常用"], "湖边石柱")
                self.assertTrue(window._card_matches_query(window.cards[0], "#玄武"))
                self.assertTrue(window._card_matches_query(window.cards[0], "湖边"))
                window._set_view_cards("work", [dict(card)], root, 0, True)
                self.assertEqual(window.cards[0]["manual_tags"], ["玄武岩", "常用"])
            finally:
                window.deleteLater()

    def test_overview_html_summarizes_current_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                card = {
                    "name": "Basalt",
                    "display_name": "Basalt",
                    "source_path": str(root),
                    "suggested_type": "photo",
                    "confidence": "high",
                    "target_path_hints": [],
                    "reasons": [],
                    "content_tags": ["rock"],
                    "total_bytes": 2048,
                }
                window._set_view_cards("work", [card], root, 0, True)
                html = window._overview_html()
                self.assertIn("概览看板", html)
                self.assertIn("当前卡片", html)
                self.assertIn("rock", html)
            finally:
                window.deleteLater()

    def test_move_context_uses_resource_root_as_library_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            z_root = root / "Z"
            z_root.mkdir()
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                window.settings["resource_root"] = str(z_root)
                ctx = window._move_context()
                self.assertTrue(ctx["formal"])
                self.assertEqual(ctx["z_root"], z_root)
                self.assertEqual(ctx["destination_root"], z_root)
                self.assertEqual(ctx["mode_label"], "入库移动")
                self.assertTrue(ctx["all_source_roots"])
                self.assertTrue(ctx["source_roots"])
            finally:
                window.deleteLater()

    def test_move_context_ignores_removed_formal_source_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                window.settings["enable_formal_z_move"] = True
                window.settings["allow_all_formal_move_sources"] = False
                window.settings["formal_move_source_roots"] = str(root / "legacy-source")
                ctx = window._move_context()
                self.assertTrue(ctx["formal"])
                self.assertTrue(ctx["all_source_roots"])
                self.assertTrue(ctx["source_roots"])
                self.assertNotEqual(ctx["source_roots"], [root / "legacy-source"])
            finally:
                window.deleteLater()

    def test_formal_move_preview_lists_source_destination_and_requires_move_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = ResourceWorkbenchWindow(initial_path=Path(tmp), auto_run=False)
            plan = {
                "ok": True,
                "formal": True,
                "source": str(Path(tmp) / "source"),
                "destination": str(Path(tmp) / "library" / "source"),
                "file_count": 3,
                "byte_count": 2048,
            }
            try:
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.Yes) as question,
                    mock.patch.object(qt_app.QInputDialog, "getText", return_value=("MOVE", True)) as get_text,
                ):
                    self.assertTrue(window._confirm_move_plans([plan]))
                preview = question.call_args.args[2]
                self.assertIn(plan["source"], preview)
                self.assertIn(plan["destination"], preview)
                self.assertIn("3 个文件", preview)
                self.assertIn("2.0 KB", preview)
                get_text.assert_called_once()
            finally:
                window.deleteLater()

    def test_formal_move_cancel_or_wrong_token_never_confirms(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = ResourceWorkbenchWindow(initial_path=Path(tmp), auto_run=False)
            plan = {
                "ok": True,
                "formal": True,
                "source": str(Path(tmp) / "source"),
                "destination": str(Path(tmp) / "library" / "source"),
                "file_count": 1,
                "byte_count": 5,
            }
            try:
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.No),
                    mock.patch.object(qt_app.QInputDialog, "getText") as get_text,
                ):
                    self.assertFalse(window._confirm_move_plans([plan]))
                    get_text.assert_not_called()
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.Yes),
                    mock.patch.object(qt_app.QInputDialog, "getText", return_value=("move", True)),
                    mock.patch.object(qt_app.QMessageBox, "information"),
                ):
                    self.assertFalse(window._confirm_move_plans([plan]))
                self.assertIn("没有移动任何文件", window.status_label.text())
            finally:
                window.deleteLater()

    def test_test_move_uses_plan_preview_but_not_move_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = ResourceWorkbenchWindow(initial_path=Path(tmp), auto_run=False)
            plan = {
                "ok": True,
                "formal": False,
                "source": str(Path(tmp) / "source"),
                "destination": str(Path(tmp) / "test-output" / "source"),
                "file_count": 1,
                "byte_count": 5,
            }
            try:
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.Yes) as question,
                    mock.patch.object(qt_app.QInputDialog, "getText") as get_text,
                ):
                    self.assertTrue(window._confirm_move_plans([plan]))
                self.assertEqual(question.call_args.args[1], "测试移动计划预览")
                get_text.assert_not_called()
            finally:
                window.deleteLater()

    def test_translation_rename_refreshes_sidebar_input_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            old_folder = library / "Old Asset"
            old_folder.mkdir(parents=True)
            (old_folder / "mesh.txt").write_text("asset", encoding="utf-8")
            preview_patcher = mock.patch.object(qt_app.ResourceCardWidget, "_load_preview", return_value=None)
            preview_patcher.start()
            with (
                mock.patch.object(qt_app.QTimer, "singleShot", return_value=None),
                mock.patch.object(ResourceWorkbenchWindow, "_configured_resource_root", return_value=None),
            ):
                window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
            try:
                window.settings["resource_root"] = str(library)
                window.settings["rename_local_after_translate"] = True
                window.rename_log = None
                window.populate_path_browser(library)
                window.resource_index.index_children(library)
                window.quick_browse_path(library)
                card = {
                    "name": old_folder.name,
                    "display_name": old_folder.name,
                    "source_path": str(old_folder),
                    "suggested_type": "model",
                    "confidence": "medium",
                    "target_path_hints": [],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], old_folder, 0, True)
                window._set_input_paths([old_folder])

                renamed = window._maybe_rename_card_folder(window.cards[0], "Translated Asset")
                new_folder = library / "Translated Asset"

                self.assertIsNotNone(renamed)
                self.assertEqual(Path(str(renamed)), new_folder)
                self.assertFalse(old_folder.exists())
                self.assertTrue(new_folder.exists())
                self.assertEqual(Path(window.cards[0]["source_path"]), new_folder)
                self.assertEqual(window.path_edit.text(), str(new_folder))
                self.assertEqual(window.current_input_path, new_folder)
                self.assertEqual(window.view_paths["work"], new_folder)
                self.assertEqual(window.active_view, "work")

                self._wait_for(
                    lambda: window._find_library_tree_item(new_folder) is not None,
                    message="重命名后的资源树目录没有在异步刷新完成后出现",
                )

                tree_paths: list[str] = []

                def collect(item):
                    text = item.data(0, Qt.UserRole)
                    if text:
                        tree_paths.append(text)
                    for row in range(item.childCount()):
                        collect(item.child(row))

                for row in range(window.path_tree.topLevelItemCount()):
                    collect(window.path_tree.topLevelItem(row))
                self.assertIn(str(new_folder), tree_paths)
                self.assertNotIn(str(old_folder), tree_paths)

                cached_paths = {
                    _canonical_path(item["source_path"])
                    for item in window.resource_index.load_child_cards(library)
                }
                self.assertIn(_canonical_path(new_folder), cached_paths)
                self.assertNotIn(_canonical_path(old_folder), cached_paths)
            finally:
                window.deleteLater()
                preview_patcher.stop()

    def test_single_card_move_uses_hint_directly_and_removes_work_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source = source_root / "RobotLeg"
            z_root = root / "Z" / "整合——资源管理"
            target = z_root / "M 模型" / "K 科幻" / "J 机甲"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "leg.fbx").write_text("fbx", encoding="utf-8")
            window = ResourceWorkbenchWindow(initial_path=source_root, auto_run=False)
            try:
                window.settings["resource_root"] = str(z_root)
                card = {
                    "name": "RobotLeg",
                    "display_name": "RobotLeg",
                    "source_path": str(source),
                    "suggested_type": "model",
                    "confidence": "high",
                    "target_path_hints": [str(target)],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], source_root, 0, True)
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.Yes),
                    mock.patch.object(qt_app.QInputDialog, "getText", return_value=("MOVE", True)),
                ):
                    window.execute_selected_test_move(0)
                self.assertFalse(source.exists())
                self.assertTrue((target / "RobotLeg" / "leg.fbx").exists())
                self.assertEqual(window.cards, [])
            finally:
                window.deleteLater()

    def test_cancelled_formal_card_move_leaves_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source" / "KeepMe"
            z_root = root / "library"
            target = z_root / "M 模型"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "asset.fbx").write_text("fbx", encoding="utf-8")
            window = ResourceWorkbenchWindow(initial_path=source.parent, auto_run=False)
            try:
                window.settings["resource_root"] = str(z_root)
                card = {
                    "name": source.name,
                    "display_name": source.name,
                    "source_path": str(source),
                    "suggested_type": "model",
                    "confidence": "high",
                    "target_path_hints": [str(target)],
                    "reasons": [],
                    "content_tags": [],
                }
                window._set_view_cards("work", [card], source.parent, 0, True)
                with (
                    mock.patch.object(qt_app.QMessageBox, "question", return_value=qt_app.QMessageBox.No),
                    mock.patch.object(qt_app.QInputDialog, "getText") as get_text,
                ):
                    window.execute_selected_test_move(0)
                    get_text.assert_not_called()
                self.assertTrue(source.exists())
                self.assertTrue((source / "asset.fbx").exists())
                self.assertFalse((target / source.name).exists())
                self.assertEqual(len(window.cards), 1)
            finally:
                window.deleteLater()

    def test_shortened_z_target_is_normalised_under_resource_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            z_root = root / "Z" / "整合——资源管理"
            z_root.mkdir(parents=True)
            window = ResourceWorkbenchWindow(initial_path=root, auto_run=False)
            try:
                window.settings["resource_root"] = str(z_root)
                normalised = window._normalise_target_path(r"Z:\M 模型\K 科幻")
                self.assertEqual(Path(normalised), z_root / "M 模型" / "K 科幻")
            finally:
                window.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
