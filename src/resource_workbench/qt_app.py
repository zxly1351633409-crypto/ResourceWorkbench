from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from html import escape
from pathlib import Path
from threading import Lock

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "resource_workbench"

from PySide6.QtCore import (
    QCoreApplication,
    QFileSystemWatcher,
    QLibraryInfo,
    QLocale,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    QTranslator,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QRubberBand,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .classifier import build_cards
from .card_metadata import CardMetadataStore, default_metadata_path, normalize_tags
from .deepseek import request_card_suggestion, request_structured_card_suggestion, selected_model, test_deepseek_connection
from .indexer import ResourceIndex, index_db_path, placeholder_cards_for_path, quick_cards_for_path
from .library_refresh import direct_child_signature, safe_mkdir
from .mover import execute_formal_move, execute_test_move, plan_move
from .target_recommender import (
    apply_history_target_suggestions,
    browse_subfolders,
    prepare_history_records,
    recommend_target_folders,
)
from .move_log import MoveLog, default_move_log_path
from .review_queue import ReviewQueue, default_queue_path, card_identity, STATUS_APPROVED
from .review_panel import ReviewQueueDialog
from .history_panel import HistoryDialog
from . import __version__, formatter, maintenance
from .runtime_maintenance import (
    RuntimeMaintenanceController,
    format_runtime_maintenance_plan,
    summarize_runtime_maintenance,
)
from .renamer import RenameLog, default_rename_log_path, rename_folder
from .planner import write_review_plan
from .preview import prepare_preview_image
from .report import write_reports
from .scanner import ScanConfig, scan_input
from .settings import (
    app_data_root,
    deepseek_api_key,
    deepseek_api_key_source,
    load_settings,
    save_deepseek_api_key,
    save_settings,
)
from .file_types import is_archive
from .fluent_skin import apply_qfluent_theme, build_fluent_qss, optional_color
from .web_resource import create_web_resource_card, is_web_card, normalise_url, save_web_resource_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = app_data_root(PROJECT_ROOT)
DEEPSEEK_API_KEYS_URL = "https://platform.deepseek.com/api_keys"


def deep_analysis_action_label(card: dict) -> str:
    """Return a context-menu label that matches the no-extraction policy."""
    source = str(card.get("source_path") or "").strip()
    archive_sources = card.get("source_archives") or []
    if (source and is_archive(source)) or archive_sources:
        return "分析压缩包外层（当前不解压）"
    return "重新分析当前来源（不解压压缩包）"


def _load_target_history_records(resource_root: Path | None) -> list[dict]:
    if resource_root is None or not Path(resource_root).exists():
        return []
    try:
        records = MoveLog(default_move_log_path(DATA_ROOT)).learning_records(limit=2000)
        return prepare_history_records(records, resource_root)
    except (OSError, ValueError):
        return []


def _apply_target_history(cards: list[dict], resource_root: Path | None, records: list[dict]) -> None:
    if resource_root is None or not records:
        return
    for card in cards:
        apply_history_target_suggestions(card, resource_root, records)


TYPE_LABELS = {
    "photo": "照片",
    "video": "视频",
    "model": "模型",
    "tutorial": "教程",
    "material": "材质",
    "ue": "UE",
    "zbrush": "ZBrush",
    "alpha": "Alpha",
    "brush": "笔刷",
    "mixed": "混合",
    "unknown": "未知",
}

CONFIDENCE_LABELS = {"high": "高", "medium": "中", "low": "低"}
LIBRARY_SECTION_NAMES = {
    "A Alphas",
    "B Blender笔记",
    "B 笔刷",
    "C 材质",
    "J 教程",
    "M 模型",
    "U UE",
    "Z zb brush",
    "Z 照片",
}
SKIP_SIDEBAR_DIR_NAMES = {".git", "__pycache__", "node_modules", ".sync", "System Volume Information", "$RECYCLE.BIN"}


def install_qt_chinese_translations(app: QApplication) -> bool:
    """Load Qt's bundled Chinese catalog for native/standard dialog controls."""
    QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
    candidates: list[Path] = []
    try:
        candidates.append(Path(QLibraryInfo.path(QLibraryInfo.TranslationsPath)))
    except (AttributeError, TypeError):
        pass
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.extend(
            [
                Path(frozen_root) / "PySide6" / "translations",
                Path(frozen_root) / "translations",
            ]
        )
    seen: set[str] = set()
    translators: list[QTranslator] = []
    for directory in candidates:
        key = os.path.normcase(os.path.normpath(str(directory)))
        if key in seen or not directory.exists():
            continue
        seen.add(key)
        for catalog in ("qtbase_zh_CN", "qt_zh_CN"):
            translator = QTranslator(app)
            if translator.load(catalog, str(directory)):
                app.installTranslator(translator)
                translators.append(translator)
                break
        if translators:
            break
    # QTranslator must stay alive for the lifetime of QApplication.
    app._resource_workbench_translators = translators  # type: ignore[attr-defined]
    return bool(translators)


def choose_project_color(parent: QWidget, current: str, title: str = "选择颜色") -> QColor | None:
    """Use a translated, consistently styled non-native color dialog."""
    dialog = QColorDialog(QColor(current), parent)
    dialog.setWindowTitle(title)
    dialog.setOption(QColorDialog.DontUseNativeDialog, True)
    dialog.setOption(QColorDialog.ShowAlphaChannel, False)
    if dialog.exec() != QDialog.Accepted:
        return None
    color = dialog.currentColor()
    return color if color.isValid() else None


def infer_resource_root_depth(input_path: Path) -> int | None:
    """Infer card grouping depth for already-organized library folders."""
    path = input_path.expanduser()
    name = path.name
    parent_name = path.parent.name
    if name == "J 教程":
        return 2
    if parent_name == "J 教程":
        return 1
    if name in LIBRARY_SECTION_NAMES:
        return 2
    if parent_name in LIBRARY_SECTION_NAMES:
        return 1
    return None


def infer_batch_resource_root_depth(input_path: Path) -> int | None:
    """Infer grouping depth for extracted, not-yet-organized batches."""
    path = input_path.expanduser()
    if not path.exists() or not path.is_dir():
        return None

    top_dirs = _depth_child_dirs(path, limit=80)
    if not top_dirs:
        return None
    if _mostly_numbered_dirs(top_dirs):
        return 0
    if len(top_dirs) >= 2:
        return 3 if any(_has_nested_resource_dirs(child) for child in top_dirs) else None

    only = top_dirs[0]
    only_dirs = _depth_child_dirs(only, limit=80)
    if not only_dirs:
        return None
    if _mostly_numbered_dirs(only_dirs):
        return 1
    if len(only_dirs) >= 6:
        return 2
    if len(only_dirs) == 1:
        grand_dirs = _depth_child_dirs(only_dirs[0], limit=80)
        if _mostly_numbered_dirs(grand_dirs):
            return 3
        if len(grand_dirs) >= 4:
            return 3
    if len(only_dirs) >= 2:
        return 2
    return None


def _depth_child_dirs(path: Path, limit: int = 80) -> list[Path]:
    try:
        children = []
        for child in path.iterdir():
            if child.is_dir() and child.name not in SKIP_SIDEBAR_DIR_NAMES:
                children.append(child)
                if len(children) >= limit:
                    break
        return sorted(children, key=lambda item: item.name.lower())
    except OSError:
        return []


def _has_nested_resource_dirs(path: Path) -> bool:
    children = _depth_child_dirs(path, limit=20)
    if len(children) >= 2:
        return True
    if len(children) == 1:
        return bool(_depth_child_dirs(children[0], limit=4))
    return False


def _mostly_numbered_dirs(paths: list[Path]) -> bool:
    if len(paths) < 2:
        return False
    numeric = 0
    for path in paths:
        name = path.name.strip().lower()
        if re.fullmatch(r"\d{1,3}|part\s*\d{1,3}|chapter\s*\d{1,3}|section\s*\d{1,3}", name):
            numeric += 1
    return numeric >= max(2, int(len(paths) * 0.7))


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _combined_resource_depth(scans: list[dict]) -> int | None:
    depths = {scan.get("resource_root_depth") for scan in scans if isinstance(scan.get("resource_root_depth"), int)}
    return next(iter(depths)) if len(depths) == 1 else None


def analysis_completion_status(total_cards: int, review_required: int, newly_queued: int) -> str:
    """Make total cards unmistakable from the review-queue subset."""
    total_cards = max(0, int(total_cards))
    review_required = max(0, int(review_required))
    newly_queued = max(0, int(newly_queued))
    if review_required:
        queue_text = f"本次入队 {newly_queued} 张" if newly_queued else "审阅队列已有对应记录"
        return (
            f"分析完成：共 {total_cards} 张，其中 {review_required} 张需确认"
            f"（{queue_text}）；不会自动移动。"
        )
    return f"分析完成：共 {total_cards} 张，无需人工确认；不会自动移动。"


def _asset_path(name: str) -> Path:
    candidates = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "resource_workbench" / "assets" / name)
    candidates.append(Path(__file__).resolve().parent / "assets" / name)
    candidates.append(PROJECT_ROOT / "src" / "resource_workbench" / "assets" / name)
    for path in candidates:
        if path.exists():
            return path
    return candidates[-1]


def _app_icon() -> QIcon:
    for name in ("logo.ico", "logo.png"):
        path = _asset_path(name)
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def make_line_icon(name: str, color: str = "#17202a") -> QIcon:
    icon = QIcon()
    for size in (24, 32, 48, 64, 96):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(size / 24, size / 24)
        pen = QPen(QColor(color), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        _draw_line_icon(painter, name, color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _draw_line_icon(painter: QPainter, name: str, color: str) -> None:
    if name == "translate":
        painter.drawLine(4.8, 17, 8, 7)
        painter.drawLine(8, 7, 11.2, 17)
        painter.drawLine(6.2, 12.5, 9.8, 12.5)
        painter.drawLine(14, 8, 19.5, 8)
        painter.drawLine(14, 12, 19.5, 12)
        painter.drawLine(14, 16, 18, 16)
        painter.drawLine(10.7, 10, 13, 10)
        painter.drawLine(13, 10, 11.7, 8.8)
        painter.drawLine(13, 10, 11.7, 11.2)
    elif name == "move":
        painter.drawLine(4, 8, 9, 8)
        painter.drawLine(9, 8, 11, 10)
        painter.drawRoundedRect(QRectF(4, 9, 16, 10), 2.4, 2.4)
        painter.drawLine(8.5, 14, 16.5, 14)
        painter.drawLine(14.5, 11.8, 17, 14)
        painter.drawLine(14.5, 16.2, 17, 14)
    elif name == "upload":
        painter.drawRoundedRect(QRectF(5, 14, 14, 5), 2, 2)
        painter.drawLine(12, 15, 12, 6)
        painter.drawLine(8.5, 9.5, 12, 6)
        painter.drawLine(15.5, 9.5, 12, 6)
    elif name == "folder":
        painter.drawLine(4, 8, 9.5, 8)
        painter.drawLine(9.5, 8, 11.5, 10)
        painter.drawRoundedRect(QRectF(4, 9, 16, 10), 2.4, 2.4)
    elif name == "web":
        painter.drawEllipse(QRectF(4.5, 4.5, 15, 15))
        painter.drawLine(5.5, 12, 18.5, 12)
        painter.drawLine(12, 4.5, 12, 19.5)
        painter.drawArc(QRectF(7.2, 4.8, 9.6, 14.4), 90 * 16, 180 * 16)
        painter.drawArc(QRectF(7.2, 4.8, 9.6, 14.4), -90 * 16, 180 * 16)
    elif name == "library":
        painter.drawRoundedRect(QRectF(4.5, 5, 6, 6), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(13.5, 5, 6, 6), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(4.5, 14, 6, 6), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(13.5, 14, 6, 6), 1.5, 1.5)
    elif name == "target":
        painter.drawEllipse(QRectF(5, 5, 14, 14))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        painter.drawLine(12, 3.5, 12, 7)
        painter.drawLine(12, 17, 12, 20.5)
        painter.drawLine(3.5, 12, 7, 12)
        painter.drawLine(17, 12, 20.5, 12)
    elif name == "more":
        painter.setBrush(QColor(color))
        for x in (6.8, 12, 17.2):
            painter.drawEllipse(QRectF(x - 1.3, 10.7, 2.6, 2.6))
    elif name == "panel-left":
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 2, 2)
        painter.drawLine(10, 5, 10, 19)
    elif name == "panel-right":
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 2, 2)
        painter.drawLine(14, 5, 14, 19)
    elif name == "search":
        painter.drawEllipse(QRectF(5, 5, 10, 10))
        painter.drawLine(14, 14, 19, 19)
    elif name == "dedupe":
        painter.drawRoundedRect(QRectF(5, 7, 10, 10), 2, 2)
        painter.drawRoundedRect(QRectF(9, 4, 10, 10), 2, 2)
    elif name == "cleanup":
        painter.drawLine(8, 5, 17, 14)
        painter.drawLine(5, 17, 13, 9)
        painter.drawLine(5, 17, 10, 20)
        painter.drawLine(8, 14, 13, 18)
        painter.drawLine(12, 10, 16, 6)
    elif name == "add":
        painter.drawLine(12, 5.5, 12, 18.5)
        painter.drawLine(5.5, 12, 18.5, 12)
    elif name == "refresh":
        painter.drawArc(QRectF(5, 5, 14, 14), 35 * 16, 285 * 16)
        painter.drawLine(16.2, 4.8, 19.3, 5.4)
        painter.drawLine(19.3, 5.4, 18.5, 8.5)
    elif name == "play":
        painter.drawRoundedRect(QRectF(4.5, 4.5, 15, 15), 3, 3)
        painter.drawLine(10, 8.5, 10, 15.5)
        painter.drawLine(10, 8.5, 15.5, 12)
        painter.drawLine(10, 15.5, 15.5, 12)
    elif name == "settings":
        painter.drawLine(5, 7, 19, 7)
        painter.drawLine(5, 12, 19, 12)
        painter.drawLine(5, 17, 19, 17)
        painter.drawEllipse(QRectF(8.2, 5.2, 3.6, 3.6))
        painter.drawEllipse(QRectF(14.2, 10.2, 3.6, 3.6))
        painter.drawEllipse(QRectF(6.2, 15.2, 3.6, 3.6))
    elif name == "archive":
        painter.drawRoundedRect(QRectF(5.5, 4.5, 13, 15), 2, 2)
        painter.drawLine(10, 5, 10, 19)
        for y in (7.5, 10.5, 13.5, 16.5):
            painter.drawLine(10, y, 13.5, y)
    elif name == "report":
        painter.drawRoundedRect(QRectF(6, 4, 12, 16), 2, 2)
        painter.drawLine(9, 9, 15, 9)
        painter.drawLine(9, 13, 15, 13)
        painter.drawLine(9, 17, 13, 17)
    elif name == "agent":
        painter.drawRoundedRect(QRectF(4.5, 5.5, 15, 11), 3, 3)
        painter.drawLine(8, 16.5, 6.2, 20)
        painter.drawLine(8, 16.5, 11, 16.5)
        painter.drawLine(8, 10, 16, 10)
        painter.drawLine(8, 13, 14, 13)
    elif name == "check":
        painter.drawLine(5, 12, 10, 17)
        painter.drawLine(10, 17, 19, 7)
    else:
        painter.drawEllipse(QRectF(6, 6, 12, 12))


class _PreviewTaskSignals(QObject):
    finished = Signal(dict)


class _PreviewTask(QRunnable):
    def __init__(self, card: dict, cache_dir: Path) -> None:
        super().__init__()
        self.card = dict(card)
        self.cache_dir = Path(cache_dir)
        self.signals = _PreviewTaskSignals()

    def run(self) -> None:
        signals = self.signals
        try:
            try:
                result = prepare_preview_image(
                    self.card,
                    self.cache_dir,
                    size=(520, 760),
                    preserve_aspect=True,
                )
            except Exception as exc:  # noqa: BLE001 - report a card-local preview failure
                result = {"ok": False, "path": None, "error": str(exc)}
            if QCoreApplication.closingDown():
                return
            try:
                signals.finished.emit(result)
            except RuntimeError:
                # A card/window can be closed while its preview is still decoding.
                pass
        finally:
            _release_async_task(_ACTIVE_PREVIEW_TASKS, self)


_IMAGE_PREVIEW_POOL = QThreadPool()
_IMAGE_PREVIEW_POOL.setMaxThreadCount(2)
_VIDEO_PREVIEW_POOL = QThreadPool()
_VIDEO_PREVIEW_POOL.setMaxThreadCount(1)


class _LibrarySignatureTaskSignals(QObject):
    finished = Signal(dict)


class _LibrarySignatureTask(QRunnable):
    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = [Path(path) for path in paths]
        self.signals = _LibrarySignatureTaskSignals()

    def run(self) -> None:
        signals = self.signals
        try:
            results = {str(path): direct_child_signature(path) for path in self.paths}
            if QCoreApplication.closingDown():
                return
            try:
                signals.finished.emit(results)
            except RuntimeError:
                # The application/window may have closed while a slow network
                # directory was being inspected. There is no receiver to update.
                pass
        finally:
            _release_async_task(_ACTIVE_LIBRARY_SIGNATURE_TASKS, self)


_LIBRARY_SIGNATURE_POOL = QThreadPool()
_LIBRARY_SIGNATURE_POOL.setMaxThreadCount(1)


LIBRARY_TREE_PAGE_SIZE = 400
TREE_ROLE_LOADED = Qt.UserRole + 1
TREE_ROLE_PLACEHOLDER = Qt.UserRole + 2
TREE_ROLE_LABEL = Qt.UserRole + 3
TREE_ROLE_HAS_CHILDREN = Qt.UserRole + 4
TREE_ROLE_KIND = Qt.UserRole + 5
TREE_ROLE_OFFSET = Qt.UserRole + 6
TREE_ROLE_GENERATION = Qt.UserRole + 7
TREE_ROLE_REQUEST = Qt.UserRole + 8
TREE_ROLE_REQUEST_OFFSET = Qt.UserRole + 9


def _compact_library_tree_error(exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError):
        return "路径已不存在"
    if isinstance(exc, NotADirectoryError):
        return "路径不是文件夹"
    if isinstance(exc, PermissionError):
        return "没有访问权限"
    text = " ".join(str(exc).split())
    return f"读取失败：{text[:72]}" if text else "读取失败"


def _library_tree_has_child_dirs(path: Path) -> tuple[bool, str]:
    """Probe one directory in a worker thread, never from the Qt GUI thread."""
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name in SKIP_SIDEBAR_DIR_NAMES:
                    continue
                try:
                    if entry.is_dir():
                        return True, ""
                except OSError:
                    continue
    except OSError as exc:
        return False, _compact_library_tree_error(exc)
    return False, ""


def _read_library_tree_page(path: Path, offset: int, page_size: int = LIBRARY_TREE_PAGE_SIZE) -> dict:
    """Enumerate and probe one resource-tree page outside the GUI thread."""
    path = Path(path)
    offset = max(0, int(offset))
    page_size = max(1, int(page_size))
    try:
        directories: list[tuple[str, str]] = []
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name in SKIP_SIDEBAR_DIR_NAMES:
                    continue
                try:
                    if entry.is_dir():
                        directories.append((entry.name, entry.path))
                except OSError:
                    continue
    except OSError as exc:
        return {
            "status": "error",
            "error": _compact_library_tree_error(exc),
            "entries": [],
            "total": 0,
            "offset": offset,
            "next_offset": offset,
            "remaining": 0,
        }

    directories.sort(key=lambda value: (value[0].casefold(), value[0]))
    page = directories[offset : offset + page_size]
    result_entries = []
    for name, child_text in page:
        child = Path(child_text)
        has_children, probe_error = _library_tree_has_child_dirs(child)
        result_entries.append(
            {
                "name": name,
                "path": str(child),
                "has_children": has_children,
                "probe_error": probe_error,
            }
        )
    next_offset = min(len(directories), offset + len(page))
    return {
        "status": "ok",
        "error": "",
        "entries": result_entries,
        "total": len(directories),
        "offset": offset,
        "next_offset": next_offset,
        "remaining": max(0, len(directories) - next_offset),
    }


class _LibraryTreeReadTaskSignals(QObject):
    finished = Signal(dict)


class _LibraryTreeReadTask(QRunnable):
    def __init__(self, path: Path, offset: int, generation: int, request_id: int) -> None:
        super().__init__()
        self.path = Path(path)
        self.offset = max(0, int(offset))
        self.generation = int(generation)
        self.request_id = int(request_id)
        self.signals = _LibraryTreeReadTaskSignals()

    def run(self) -> None:
        # Keep the signal source alive even if its window is destroyed while a
        # slow drive or UNC path is still being read by the global thread pool.
        signals = self.signals
        try:
            try:
                result = _read_library_tree_page(self.path, self.offset)
            except Exception as exc:  # noqa: BLE001 - keep a tree-local failure compact
                result = {
                    "status": "error",
                    "error": f"读取失败：{' '.join(str(exc).split())[:72]}",
                    "entries": [],
                    "total": 0,
                    "offset": self.offset,
                    "next_offset": self.offset,
                    "remaining": 0,
                }
            result.update(
                {
                    "path": str(self.path),
                    "generation": self.generation,
                    "request_id": self.request_id,
                }
            )
            if QCoreApplication.closingDown():
                return
            try:
                signals.finished.emit(result)
            except RuntimeError:
                # Qt can tear down signal sources during application shutdown.
                # The scan is read-only and its result is intentionally discarded.
                pass
        finally:
            _release_async_task(_ACTIVE_LIBRARY_TREE_TASKS, self)


_LIBRARY_TREE_POOL = QThreadPool()
_LIBRARY_TREE_POOL.setMaxThreadCount(4)

_ASYNC_TASK_LOCK = Lock()
_ACTIVE_PREVIEW_TASKS: set[_PreviewTask] = set()
_ACTIVE_LIBRARY_SIGNATURE_TASKS: set[_LibrarySignatureTask] = set()
_ACTIVE_LIBRARY_TREE_TASKS: set[_LibraryTreeReadTask] = set()


def _retain_async_task(registry: set, task: QRunnable) -> None:
    """Keep the Python wrapper/signal source alive while Qt owns the runnable."""
    with _ASYNC_TASK_LOCK:
        registry.add(task)


def _release_async_task(registry: set, task: QRunnable) -> None:
    with _ASYNC_TASK_LOCK:
        registry.discard(task)


def drain_async_pools(timeout_ms: int = -1) -> bool:
    """Drain read-only background pools while QApplication is still alive.

    Queued work is no longer useful once the last window closes, so it is
    cleared first. Already-running filesystem/preview reads are allowed to
    finish before Qt destroys their Python QRunnable and signal wrappers.
    """
    pools = (
        _IMAGE_PREVIEW_POOL,
        _VIDEO_PREVIEW_POOL,
        _LIBRARY_SIGNATURE_POOL,
        _LIBRARY_TREE_POOL,
    )
    for pool in pools:
        pool.clear()
    completed = True
    for pool in pools:
        completed = bool(pool.waitForDone(timeout_ms)) and completed
    if completed:
        with _ASYNC_TASK_LOCK:
            _ACTIVE_PREVIEW_TASKS.clear()
            _ACTIVE_LIBRARY_SIGNATURE_TASKS.clear()
            _ACTIVE_LIBRARY_TREE_TASKS.clear()
    return completed


class ResourceCardWidget(QFrame):
    CARD_WIDTH = 250
    CARD_INSET = 5
    PREVIEW_WIDTH = CARD_WIDTH - CARD_INSET * 2

    selected = Signal(int)
    action_requested = Signal(str, int)
    preview_ready = Signal()

    def __init__(self, index: int, card: dict, preview_cache_dir: Path, target_text: str) -> None:
        super().__init__()
        self.index = index
        self.card = card
        self.preview_cache_dir = preview_cache_dir
        self.target_text = target_text
        self.select_mode = False
        self._preview_task: _PreviewTask | None = None

        self.setObjectName("ResourceCard")
        self.setProperty("selected", False)
        self.setProperty("review", bool(card.get("needs_human_review")))
        self.setFixedWidth(self.CARD_WIDTH)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.CARD_INSET, self.CARD_INSET, self.CARD_INSET, 9)
        layout.setSpacing(6)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("CardPreview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedWidth(self.PREVIEW_WIDTH)
        self.preview_label.setWordWrap(False)
        self.preview_label.setText("预览加载中")
        self.preview_label.setProperty("empty", True)
        self.preview_label.setFixedHeight(188)
        layout.addWidget(self.preview_label)

        self.selection_badge = QLabel("✓", self)
        self.selection_badge.setObjectName("CardSelectedBadge")
        self.selection_badge.setAlignment(Qt.AlignCenter)
        self.selection_badge.setFixedSize(28, 28)
        self.selection_badge.hide()

        self.hover_overlay = QFrame(self)
        self.hover_overlay.setObjectName("CardHoverOverlay")
        self.hover_overlay.hide()

        overlay_layout = QVBoxLayout(self.hover_overlay)
        overlay_layout.setContentsMargins(8, 8, 8, 8)
        overlay_layout.setSpacing(0)

        # 悬浮操作精简为四个：翻译 / 移动（上排），打开 / 目标分类（下排）。
        # 其余操作（重新分析、复制路径、标记需确认等）保留在右键菜单。
        top_actions = QHBoxLayout()
        top_actions.setSpacing(6)
        top_actions.addStretch(1)
        self.btn_hover_translate = QPushButton()
        self.btn_hover_translate.setIcon(make_line_icon("translate", "#ffffff"))
        self.btn_hover_translate.setToolTip("翻译命名")
        self.btn_hover_move = QPushButton()
        self.btn_hover_move.setIcon(make_line_icon("move", "#ffffff"))
        self.btn_hover_move.setToolTip("保存到资源库" if is_web_card(card) else "移动入库")
        for button, action, bg, bg_hover in [
            (self.btn_hover_translate, "translate", "#2563eb", "#1d4ed8"),
            (self.btn_hover_move, "move", "#16a34a", "#15803d"),
        ]:
            button.setObjectName("HoverIconButton")
            button.setFixedSize(32, 30)
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton{{background:{bg};border:none;border-radius:8px;}}"
                f"QPushButton:hover{{background:{bg_hover};}}"
            )
            button.clicked.connect(lambda _checked=False, key=action: self.action_requested.emit(key, self.index))
            top_actions.addWidget(button)
        overlay_layout.addLayout(top_actions)
        overlay_layout.addStretch(1)

        bottom_actions = QHBoxLayout()
        bottom_actions.setSpacing(6)
        self.btn_hover_open = QPushButton()
        self.btn_hover_open.setIcon(make_line_icon("web" if is_web_card(card) else "folder", "#ffffff"))
        self.btn_hover_open.setToolTip("打开网页" if is_web_card(card) else "打开所在文件夹")
        self.btn_hover_open.setObjectName("HoverIconButton")
        self.btn_hover_open.setFixedSize(32, 30)
        self.btn_hover_open.setIconSize(QSize(18, 18))
        self.btn_hover_open.setCursor(Qt.PointingHandCursor)
        self.btn_hover_open.setStyleSheet(
            "QPushButton{background:#475569;border:none;border-radius:8px;}"
            "QPushButton:hover{background:#334155;}"
        )
        self.btn_hover_open.clicked.connect(lambda: self.action_requested.emit("open_location", self.index))
        bottom_actions.addWidget(self.btn_hover_open)
        target_badge = self._compact_target(target_text)
        if target_badge:
            self.btn_hover_target = QPushButton(target_badge)
            self.btn_hover_target.setToolTip(f"选择目标分类：{target_text}")
            self.btn_hover_target.setObjectName("HoverTextButton")
            self.btn_hover_target.setFixedHeight(30)
            self.btn_hover_target.setMaximumWidth(132)
            self.btn_hover_target.setCursor(Qt.PointingHandCursor)
            self.btn_hover_target.clicked.connect(lambda: self.action_requested.emit("change_target", self.index))
            bottom_actions.addWidget(self.btn_hover_target, 1)
        else:
            bottom_actions.addStretch(1)
        overlay_layout.addLayout(bottom_actions)

        full_title = card.get("display_name") or card.get("name", "")
        self.title_label = QLabel(self._compact_title(full_title))
        self.title_label.setObjectName("CardTitle")
        self.title_label.setToolTip(full_title)
        self.title_label.setWordWrap(False)
        self.title_label.setFixedHeight(22)
        self.title_label.setContentsMargins(7, 1, 7, 0)
        layout.addWidget(self.title_label)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(7, 0, 7, 0)
        self.type_chip = QLabel(TYPE_LABELS.get(card.get("suggested_type"), card.get("suggested_type", "")))
        self.type_chip.setObjectName("TypeChip")
        meta_row.addWidget(self.type_chip)
        if card.get("needs_human_review"):
            self.status_chip = QLabel("需确认")
            self.status_chip.setObjectName("StatusChip")
            self.status_chip.setProperty("warning", True)
            meta_row.addWidget(self.status_chip)
        manual_tags = card.get("manual_tags") or []
        if manual_tags:
            tag_text = str(manual_tags[0])
            if len(manual_tags) > 1:
                tag_text += f" +{len(manual_tags) - 1}"
            self.manual_tag_chip = QLabel(self._compact_title(tag_text))
            self.manual_tag_chip.setObjectName("StatusChip")
            self.manual_tag_chip.setToolTip("人工标签：" + " / ".join(str(tag) for tag in manual_tags))
            meta_row.addWidget(self.manual_tag_chip)
        meta_row.addStretch(1)
        layout.addLayout(meta_row)

        if target_badge:
            self.target_label = QLabel(target_badge)
            self.target_label.setObjectName("CardTargetInline")
            self.target_label.setToolTip(target_text)
            self.target_label.setFixedHeight(19)
            self.target_label.setContentsMargins(7, 0, 7, 0)
            layout.addWidget(self.target_label)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._load_preview)
        self._preview_timer.start(min(2200, 45 * max(0, index)))

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.selection_badge.setVisible(is_selected)
        if is_selected:
            self.selection_badge.raise_()
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() in {Qt.LeftButton, Qt.RightButton}:
            self.selected.emit(self.index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.action_requested.emit("show_detail", self.index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:  # noqa: ANN001
        if self.select_mode:
            self.hover_overlay.hide()
            super().enterEvent(event)
            return
        self.hover_overlay.show()
        self.hover_overlay.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self.hover_overlay.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._position_overlay()
        self.selection_badge.move(self.width() - self.selection_badge.width() - 11, 10)

    def _open_context_menu(self, pos: QPoint) -> None:
        self.selected.emit(self.index)
        menu = QMenu(self)
        if is_web_card(self.card):
            actions = [
                ("open_location", "打开网页"),
                ("copy_source_path", "复制网页链接"),
                ("change_target", "修改目标分类"),
                ("mark_review", "标记需确认"),
                ("edit_metadata", "备注 / 标签"),
                ("translate", "翻译命名"),
                ("move", "保存到资源库"),
            ]
        else:
            actions = [
                ("open_location", "打开所在文件夹"),
                ("copy_source_path", "复制来源路径"),
                ("change_target", "修改目标分类"),
                ("mark_review", "标记需确认"),
                ("edit_metadata", "备注 / 标签"),
                ("deep_analyze", deep_analysis_action_label(self.card)),
                ("format_cover", "整理为封面+工程"),
                ("translate", "翻译命名"),
                ("move", "移动入库"),
            ]
        for action_key, label in actions:
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, key=action_key: self.action_requested.emit(key, self.index))
            menu.addAction(action)
            if action_key == "mark_review":
                menu.addSeparator()
            elif action_key == "translate":
                menu.addSeparator()
        menu.exec(self.mapToGlobal(pos))

    def _compact_title(self, title: str) -> str:
        title = " ".join(str(title).split())
        if len(title) <= 28:
            return title
        return f"{title[:27]}..."

    def _compact_target(self, target: str) -> str:
        target = " ".join(str(target or "").split())
        if not target:
            return ""
        parts = [part for part in re.split(r"[\\/]+", target) if part]
        if len(parts) >= 2:
            target = " / ".join(parts[-2:])
        elif parts:
            target = parts[-1]
        if len(target) <= 26:
            return target
        return f"{target[:25]}..."

    def _load_preview(self) -> None:
        if self._preview_task is not None:
            return
        task = _PreviewTask(self.card, self.preview_cache_dir)
        self._preview_task = task
        task.signals.finished.connect(self._apply_preview_result)
        preview_source = self.card.get("preview_source") or {}
        pool = _VIDEO_PREVIEW_POOL if preview_source.get("kind") == "video_file" else _IMAGE_PREVIEW_POOL
        _retain_async_task(_ACTIVE_PREVIEW_TASKS, task)
        try:
            pool.start(task)
        except Exception as exc:  # noqa: BLE001 - keep a card-local failure contained
            _release_async_task(_ACTIVE_PREVIEW_TASKS, task)
            self._apply_preview_result({"ok": False, "path": None, "error": str(exc)})

    def _apply_preview_result(self, result: dict) -> None:
        self._preview_task = None
        if not result.get("ok"):
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("无预览")
            self.preview_label.setToolTip(result.get("error") or "没有找到可用预览图。")
            self.preview_label.setProperty("empty", True)
            self.preview_label.setFixedHeight(176)
            self.preview_label.style().unpolish(self.preview_label)
            self.preview_label.style().polish(self.preview_label)
            self._position_overlay()
            self.preview_ready.emit()
            return

        pixmap = QPixmap(result["path"])
        if pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("预览失败")
            self.preview_label.setToolTip("预览图文件存在，但无法加载。")
            self.preview_label.setProperty("empty", True)
            self.preview_label.setFixedHeight(176)
            self.preview_label.style().unpolish(self.preview_label)
            self.preview_label.style().polish(self.preview_label)
            self._position_overlay()
            self.preview_ready.emit()
            return

        self.preview_label.setText("")
        self.preview_label.setToolTip("")
        self.preview_label.setProperty("empty", False)
        ratio = pixmap.height() / max(1, pixmap.width())
        image_height = int(self.PREVIEW_WIDTH * ratio)
        image_height = max(150, min(380, image_height))
        self.preview_label.setFixedHeight(image_height)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.width(),
                self.preview_label.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        self._position_overlay()
        self.preview_ready.emit()

    def _position_overlay(self) -> None:
        geom = self.preview_label.geometry()
        if geom.width() > 0 and geom.height() > 0:
            self.hover_overlay.setGeometry(geom)
        else:
            self.hover_overlay.setGeometry(
                self.CARD_INSET,
                self.CARD_INSET,
                self.PREVIEW_WIDTH,
                self.preview_label.height(),
            )


class _CardSurface(QWidget):
    """卡片承载面板：在多选模式下支持框选（拖动出矩形选中多张）。"""

    def __init__(self, wall: "MasonryCardWall") -> None:
        super().__init__()
        self._wall = wall

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if self._wall.select_mode and event.button() == Qt.LeftButton:
            self._wall._band_start(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._wall._band_active():
            self._wall._band_update(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if self._wall._band_active():
            self._wall._band_finish()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ShimmerLabel(QLabel):
    """Small, low-noise animated status used while analysis runs."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._shimmer_active = False
        self._phase = -0.35
        self._timer = QTimer(self)
        self._timer.setInterval(42)
        self._timer.timeout.connect(self._advance_shimmer)
        self.setAlignment(Qt.AlignCenter)

    def set_shimmer_active(self, active: bool) -> None:
        self._shimmer_active = bool(active)
        if self._shimmer_active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance_shimmer(self) -> None:
        self._phase += 0.035
        if self._phase > 1.35:
            self._phase = -0.35
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt event type is binding-specific
        if not self._shimmer_active:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        base = self.palette().color(self.foregroundRole())
        highlight = QColor("#7aa7ff")
        gradient = QLinearGradient(0, 0, max(1, self.width()), 0)
        leading = max(0.0, min(1.0, self._phase - 0.18))
        center = max(0.0, min(1.0, self._phase))
        trailing = max(0.0, min(1.0, self._phase + 0.18))
        gradient.setColorAt(0.0, base)
        gradient.setColorAt(leading, base)
        gradient.setColorAt(center, highlight)
        gradient.setColorAt(trailing, base)
        gradient.setColorAt(1.0, base)
        painter.setPen(QPen(QBrush(gradient), 1))
        painter.setFont(self.font())
        painter.drawText(self.rect(), self.alignment(), self.text())


class MasonryCardWall(QScrollArea):
    card_selected = Signal(int)
    card_action_requested = Signal(str, int)
    rubber_selected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("CardWall")
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.cards: list[ResourceCardWidget] = []
        self.selected_index: int | None = None
        self.select_mode = False
        self._band: QRubberBand | None = None
        self._band_origin: QPoint | None = None
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(60)
        self._relayout_timer.timeout.connect(self.relayout_cards)

        self.surface = _CardSurface(self)
        self.surface.setObjectName("MasonrySurface")
        self.setWidget(self.surface)

        self.empty_label = QLabel("还没有卡片。可先设置资源库，或在路径框输入待整理路径，也可以导入网页链接。")
        self.empty_label.setObjectName("EmptyWallText")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setParent(self.surface)

    def set_select_mode(self, on: bool) -> None:
        self.select_mode = bool(on)
        for card_widget in self.cards:
            card_widget.select_mode = self.select_mode
            if self.select_mode:
                card_widget.hover_overlay.hide()

    def _band_start(self, pos: QPoint) -> None:
        self._band_origin = pos
        if self._band is None:
            self._band = QRubberBand(QRubberBand.Rectangle, self.surface)
        self._band.setGeometry(QRect(pos, QSize()))
        self._band.show()

    def _band_active(self) -> bool:
        return self._band_origin is not None

    def _band_update(self, pos: QPoint) -> None:
        if self._band is not None and self._band_origin is not None:
            self._band.setGeometry(QRect(self._band_origin, pos).normalized())

    def _band_finish(self) -> None:
        if self._band is None or self._band_origin is None:
            return
        rect = self._band.geometry()
        self._band.hide()
        self._band_origin = None
        hits = {w.index for w in self.cards if rect.intersects(w.geometry())}
        if hits:
            self.rubber_selected.emit(hits)

    def set_cards(self, items: list[tuple[int, dict]], preview_cache_dir: Path, target_formatter) -> None:  # noqa: ANN001
        for card_widget in self.cards:
            card_widget.setParent(None)
            card_widget.deleteLater()
        self.cards = []

        for index, card in items:
            widget = ResourceCardWidget(index, card, preview_cache_dir, target_formatter(card))
            widget.setParent(self.surface)
            widget.selected.connect(self.card_selected)
            widget.action_requested.connect(self.card_action_requested)
            widget.preview_ready.connect(self.schedule_relayout)
            widget.show()
            self.cards.append(widget)

        self.empty_label.setVisible(not self.cards)
        self.schedule_relayout(0)

    def select_card(self, index: int | None) -> None:
        self.selected_index = index
        selected_widget: ResourceCardWidget | None = None
        for card_widget in self.cards:
            is_selected = index is not None and card_widget.index == index
            card_widget.set_selected(is_selected)
            if is_selected:
                selected_widget = card_widget
        if selected_widget is not None:
            self.ensureWidgetVisible(selected_widget, 0, 22)

    def apply_selection(self, indices) -> None:
        sel = set(indices)
        self.selected_index = next(iter(sel)) if len(sel) == 1 else self.selected_index
        for card_widget in self.cards:
            card_widget.set_selected(card_widget.index in sel)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.schedule_relayout(0)

    def schedule_relayout(self, delay_ms: int | None = None) -> None:
        """合并多次重排请求（预览陆续加载时），避免每张图就绪都全量重排造成卡顿。"""
        self._relayout_timer.start(60 if delay_ms is None else max(0, int(delay_ms)))

    def relayout_cards(self) -> None:
        viewport_width = max(320, self.viewport().width())
        gap = 14
        top_pad = 12
        card_width = ResourceCardWidget.CARD_WIDTH
        columns = max(1, (viewport_width + gap) // (card_width + gap))
        total_width = columns * card_width + (columns - 1) * gap
        left_pad = max(12, (viewport_width - total_width) // 2)

        if not self.cards:
            self.surface.resize(viewport_width, max(280, self.viewport().height()))
            self.empty_label.setGeometry(0, 0, viewport_width, 240)
            return

        heights = [top_pad for _ in range(columns)]
        for card_widget in self.cards:
            card_height = card_widget.sizeHint().height()
            column = min(range(columns), key=lambda item: heights[item])
            x = left_pad + column * (card_width + gap)
            y = heights[column]
            card_widget.setGeometry(x, y, card_width, card_height)
            heights[column] += card_height + gap

        wall_height = max(heights) + top_pad
        self.surface.resize(viewport_width, max(wall_height, self.viewport().height()))


class ExplorerTreeWidget(QTreeWidget):
    branch_toggled = Signal(QTreeWidgetItem)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - Qt event type varies by binding
        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        item = self.itemAt(point)
        if item is not None and self._is_branch_hit(item, point):
            item.setExpanded(not item.isExpanded())
            self.setCurrentItem(item)
            self.branch_toggled.emit(item)
            event.accept()
            return
        super().mousePressEvent(event)

    def _is_branch_hit(self, item: QTreeWidgetItem, point: QPoint) -> bool:
        if item.childCount() <= 0:
            return False
        depth = 0
        parent = item.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        indentation = max(16, self.indentation())
        left = depth * indentation
        right = left + indentation
        return left <= point.x() <= right


class AnalyzeWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(dict)

    def __init__(
        self,
        input_path: Path | list[Path],
        resource_root_depth: int | None = None,
        staging_root: Path | None = None,
        auto_extract_archives: bool = False,
        z_root: Path | None = None,
        web_urls: list[str] | None = None,
        web_preview_cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.input_paths = input_path if isinstance(input_path, list) else [input_path]
        self.resource_root_depth = resource_root_depth
        self.staging_root = staging_root
        # v0.3.0 安全边界：普通分析永远不自动解压。保留参数只为兼容旧调用，
        # 即使旧代码传入 True 也不能重新开启隐式解压。
        self.auto_extract_archives = False
        self.z_root = z_root
        self.web_urls = list(web_urls or [])
        self.web_preview_cache_dir = Path(web_preview_cache_dir) if web_preview_cache_dir else DATA_ROOT / "workbench_data" / "previews" / "web"
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        try:
            scans: list[dict] = []
            cards: list[dict] = []
            extractions: list[dict] = []
            web_errors: list[str] = []
            history_records = _load_target_history_records(self.z_root)
            total_sources = max(1, len(self.input_paths) + len(self.web_urls))
            for source_index, source_path in enumerate(self.input_paths):
                if self.cancel_requested:
                    break
                self.progress.emit(f"准备读取：{source_path.name or source_path}", 5 + int(source_index / total_sources * 12))
                scan_targets, extraction = self._scan_targets_for_source(source_path)
                if extraction:
                    extractions.append(extraction)
                for scan_path in scan_targets:
                    if self.cancel_requested:
                        break
                    self.progress.emit(f"正在扫描：{scan_path.name or scan_path}", 18 + int(source_index / total_sources * 52))
                    resource_root_depth = self._depth_for_scan(scan_path)
                    config = ScanConfig(
                        max_files=300000,
                        max_depth=10,
                        max_seconds=900,
                        inspect_archives=False,
                        max_archives_to_inspect=0,
                        max_entries_per_archive=500,
                        resource_root_depth=resource_root_depth,
                        cancel_check=lambda: self.cancel_requested,
                    )
                    scan = scan_input(scan_path, config=config)
                    scan["library_browser_mode"] = bool(self.z_root and _is_path_inside(scan_path, self.z_root))
                    scans.append(scan)
                    self.progress.emit("正在生成资源卡片", 76)
                    source_cards = build_cards(scan, z_root=self.z_root)
                    _apply_target_history(source_cards, self.z_root, history_records)
                    self._attach_batch_context(source_cards, source_path, scan_path, extraction)
                    cards.extend(source_cards)
            for web_index, url in enumerate(self.web_urls):
                if self.cancel_requested:
                    break
                source_index = len(self.input_paths) + web_index
                domain = QUrl(url).host() or url
                self.progress.emit(f"正在读取网页：{domain}", 18 + int(source_index / total_sources * 58))
                try:
                    cards.append(create_web_resource_card(url, self.web_preview_cache_dir))
                except Exception as exc:  # noqa: BLE001 - keep other inputs usable
                    web_errors.append(f"网页导入失败：{url}；{exc}")
            if web_errors and not cards and not scans and not self.cancel_requested:
                self.finished.emit({"ok": False, "error": "\n".join(web_errors)})
                return
            self.progress.emit("正在整理分析结果", 90)
            scan = self._combined_scan(scans, extractions)
            scan["warnings"].extend(web_errors)
            scan["web_resource_count"] = sum(1 for card in cards if is_web_card(card))
            paths = write_reports(scan, cards, output_dir=DATA_ROOT / "reports")
            extraction_payload = extractions[0] if len(extractions) == 1 else {"items": extractions} if extractions else None
            self.progress.emit("分析完成", 100)
            self.finished.emit({"ok": True, "scan": scan, "cards": cards, "paths": paths, "extraction": extraction_payload})
        except Exception as exc:  # noqa: BLE001
            self.finished.emit({"ok": False, "error": str(exc)})

    def _scan_targets_for_source(self, source_path: Path) -> tuple[list[Path], dict | None]:
        # 压缩包只作为一个外层文件参与扫描；读取/解压内部必须由未来独立、
        # 明示的高级流程实现，不能从普通分析参数悄悄恢复。
        return [source_path], None

    def _depth_for_scan(self, scan_path: Path) -> int | None:
        if self.resource_root_depth is not None:
            return self.resource_root_depth
        library_depth = infer_resource_root_depth(scan_path)
        if library_depth is not None and self.z_root is not None and _is_path_inside(scan_path, self.z_root):
            return library_depth
        return infer_batch_resource_root_depth(scan_path)

    def _attach_batch_context(
        self,
        cards: list[dict],
        source_path: Path,
        scan_path: Path,
        extraction: dict | None,
    ) -> None:
        manifest_path = (extraction or {}).get("manifest_path")
        for card in cards:
            card["batch_source_path"] = str(source_path)
            card["staging_scan_path"] = str(scan_path)
            if manifest_path:
                card["extraction_manifest"] = manifest_path
            if str(card.get("name", "")).startswith("("):
                display = scan_path.name or source_path.stem or source_path.name
                card["name"] = display
                card["display_name"] = display

    def _combined_scan(self, scans: list[dict], extractions: list[dict]) -> dict:
        buckets: dict[str, int] = {}
        extensions: dict[str, int] = {}
        warnings: list[str] = []
        missing_top_level_directories: list[str] = []
        for scan in scans:
            for bucket, count in (scan.get("buckets") or {}).items():
                buckets[bucket] = buckets.get(bucket, 0) + int(count)
            for ext, count in (scan.get("extensions") or {}).items():
                extensions[ext] = extensions.get(ext, 0) + int(count)
            warnings.extend(scan.get("warnings") or [])
            source_label = Path(scan.get("input_path") or "").name
            for name in scan.get("missing_top_level_directories") or []:
                missing_top_level_directories.append(
                    f"{source_label} / {name}" if len(scans) > 1 and source_label else str(name)
                )
        for extraction in extractions:
            for failure in extraction.get("failures") or []:
                warnings.append(f"解压失败：{failure.get('archive')}；{failure.get('error')}")
        return {
            "input_path": " ; ".join([*(str(path) for path in self.input_paths), *self.web_urls]),
            "kind": "batch" if len(self.input_paths) > 1 or len(scans) > 1 else (scans[0].get("kind") if scans else "missing"),
            "exists": all(path.exists() for path in self.input_paths),
            "stopped_early": any(scan.get("stopped_early") for scan in scans) or self.cancel_requested,
            "stop_reason": "用户取消了本次分析。" if self.cancel_requested else next((scan.get("stop_reason") for scan in scans if scan.get("stop_reason")), None),
            "total_files": sum(int(scan.get("total_files", 0)) for scan in scans),
            "total_dirs": sum(int(scan.get("total_dirs", 0)) for scan in scans),
            "total_bytes": sum(int(scan.get("total_bytes", 0)) for scan in scans),
            "extensions": dict(sorted(extensions.items(), key=lambda item: item[1], reverse=True)),
            "buckets": dict(sorted(buckets.items(), key=lambda item: item[1], reverse=True)),
            "groups": {},
            "archives": [],
            "inspected_archives": sum(int(scan.get("inspected_archives", 0)) for scan in scans),
            "warnings": warnings,
            "elapsed_seconds": round(sum(float(scan.get("elapsed_seconds", 0)) for scan in scans), 3),
            "resource_root_depth": _combined_resource_depth(scans),
            "top_level_directory_count": sum(int(scan.get("top_level_directory_count", 0) or 0) for scan in scans),
            "top_level_card_count": sum(int(scan.get("top_level_card_count", 0) or 0) for scan in scans),
            "missing_top_level_directories": missing_top_level_directories,
            "top_level_card_invariant_applied": any(bool(scan.get("top_level_card_invariant_applied")) for scan in scans),
            "scan_count": len(scans),
            "extraction_count": len(extractions),
        }


class DeepAnalyzeWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(dict)

    def __init__(self, source_path: Path, staging_root: Path, z_root: Path | None = None) -> None:
        super().__init__()
        self.source_path = source_path
        self.staging_root = staging_root
        self.z_root = z_root
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        try:
            self.progress.emit("准备重新分析当前资源", 8)
            if self.cancel_requested:
                self.finished.emit({"ok": False, "error": "用户取消了本次重新分析。"})
                return
            scan_path = self.source_path
            extraction: dict | None = None

            resource_root_depth = (
                infer_resource_root_depth(scan_path)
                if self.z_root is not None and _is_path_inside(scan_path, self.z_root)
                else infer_batch_resource_root_depth(scan_path)
            )
            config = ScanConfig(
                max_files=80000,
                max_depth=10,
                max_seconds=180,
                inspect_archives=False,
                max_archives_to_inspect=0,
                max_entries_per_archive=800,
                resource_root_depth=resource_root_depth,
                cancel_check=lambda: self.cancel_requested,
            )
            self.progress.emit("正在扫描当前资源", 35)
            scan = scan_input(scan_path, config=config)
            scan["library_browser_mode"] = bool(self.z_root and _is_path_inside(scan_path, self.z_root))
            self.progress.emit("正在生成资源卡片", 78)
            cards = build_cards(scan, z_root=self.z_root)
            _apply_target_history(cards, self.z_root, _load_target_history_records(self.z_root))
            paths = write_reports(scan, cards, output_dir=DATA_ROOT / "reports")
            self.progress.emit("重新分析完成（未解压）", 100)
            self.finished.emit(
                {
                    "ok": True,
                    "source_path": str(self.source_path),
                    "scan_path": str(scan_path),
                    "extraction": extraction,
                    "scan": scan,
                    "cards": cards,
                    "paths": paths,
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.finished.emit({"ok": False, "error": str(exc)})


class LibraryIndexWorker(QObject):
    parent_indexed = Signal(str, int, int)
    finished = Signal(dict)

    def __init__(self, db_path: Path, root_path: Path, max_depth: int = 2, max_children: int = 320) -> None:
        super().__init__()
        self.db_path = db_path
        self.root_path = root_path
        self.max_depth = max_depth
        self.max_children = max_children
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def run(self) -> None:
        started = time.monotonic()
        indexed_parents = 0
        indexed_rows = 0
        try:
            index = ResourceIndex(self.db_path)
            queue: list[tuple[Path, int]] = [(self.root_path, 0)]
            seen: set[str] = set()
            while queue and not self.cancel_requested:
                parent, depth = queue.pop(0)
                key = str(parent).lower()
                if key in seen or not parent.exists() or not parent.is_dir():
                    continue
                seen.add(key)
                rows = index.index_children(parent, max_children=self.max_children)
                indexed_parents += 1
                indexed_rows += rows
                self.parent_indexed.emit(str(parent), rows, depth)
                if depth >= self.max_depth:
                    continue
                for child in _worker_child_dirs(parent, self.max_children):
                    queue.append((child, depth + 1))
            self.finished.emit(
                {
                    "ok": True,
                    "cancelled": self.cancel_requested,
                    "parents": indexed_parents,
                    "rows": indexed_rows,
                    "elapsed": round(time.monotonic() - started, 2),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.finished.emit({"ok": False, "error": str(exc)})


class MaintenanceWorker(QObject):
    finished = Signal(dict)

    def __init__(self, action: str, root: Path, use_hash: bool = False) -> None:
        super().__init__()
        self.action = action
        self.root = root
        self.use_hash = use_hash

    def run(self) -> None:
        started = time.monotonic()
        try:
            if self.action == "dedupe":
                groups = maintenance.find_duplicates(self.root, use_hash=self.use_hash)
                self.finished.emit(
                    {
                        "ok": True,
                        "action": self.action,
                        "root": str(self.root),
                        "groups": groups,
                        "use_hash": self.use_hash,
                        "elapsed": round(time.monotonic() - started, 2),
                    }
                )
                return
            if self.action == "empty_dirs_preview":
                empties = maintenance.find_empty_dirs(self.root)
                self.finished.emit(
                    {
                        "ok": True,
                        "action": self.action,
                        "root": str(self.root),
                        "empty_dirs": empties,
                        "elapsed": round(time.monotonic() - started, 2),
                    }
                )
                return
            if self.action == "empty_dirs_apply":
                result = maintenance.remove_empty_dirs(self.root)
                self.finished.emit(
                    {
                        "ok": True,
                        "action": self.action,
                        "root": str(self.root),
                        "removed": result.get("removed", []),
                        "count": result.get("count", 0),
                        "elapsed": round(time.monotonic() - started, 2),
                    }
                )
                return
            self.finished.emit({"ok": False, "error": f"未知维护动作：{self.action}"})
        except Exception as exc:  # noqa: BLE001
            self.finished.emit({"ok": False, "action": self.action, "root": str(self.root), "error": str(exc)})


def _worker_child_dirs(root: Path, limit: int) -> list[Path]:
    try:
        children = []
        for child in root.iterdir():
            if child.is_dir() and child.name not in SKIP_SIDEBAR_DIR_NAMES:
                children.append(child)
                if len(children) >= limit:
                    break
        return sorted(children, key=lambda path: path.name.lower())
    except OSError:
        return []


class SemanticThemeDialog(QDialog):
    """Blender-style semantic colour roles without making Settings too tall."""

    ROLES = [
        ("ui_window_color", "窗口背景", "#f6f4ef"),
        ("ui_sidebar_color", "资源库侧栏", "#f2f0eb"),
        ("ui_card_color", "资源卡片", "#fffefd"),
        ("ui_input_color", "输入框", "#fffefd"),
        ("ui_text_color", "主要文字", "#2d2925"),
        ("ui_muted_text_color", "弱提示文字", "#756b62"),
        ("ui_border_color", "边框", "#dfd6cd"),
        ("ui_icon_color", "图标", "#3c3630"),
        ("ui_button_hover_color", "按钮悬停", "#ebe5dd"),
        ("ui_button_selected_color", "按钮 / 卡片选中", "#9b5a45"),
    ]
    ROLE_DESCRIPTIONS = {
        "ui_window_color": "应用最外层背景",
        "ui_sidebar_color": "左侧资源库区域",
        "ui_card_color": "资源卡片和主要表面",
        "ui_input_color": "路径、搜索和设置输入框",
        "ui_text_color": "标题与正文",
        "ui_muted_text_color": "状态、说明与次要信息",
        "ui_border_color": "面板、卡片和输入框分隔线",
        "ui_icon_color": "工具栏与目录图标",
        "ui_button_hover_color": "鼠标悬停反馈",
        "ui_button_selected_color": "选中卡片与主操作强调",
    }
    GROUPS = [
        ("表面", ("ui_window_color", "ui_sidebar_color", "ui_card_color", "ui_input_color")),
        ("文字与线条", ("ui_text_color", "ui_muted_text_color", "ui_border_color", "ui_icon_color")),
        ("交互状态", ("ui_button_hover_color", "ui_button_selected_color")),
    ]

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("自定义界面配色")
        self.setMinimumSize(820, 640)
        self.resize(900, 700)
        self._fallbacks = {key: fallback for key, _label, fallback in self.ROLES}
        self._labels = {key: label for key, label, _fallback in self.ROLES}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("界面语义配色")
        title.setObjectName("SettingsSectionTitle")
        layout.addWidget(title)
        hint = QLabel("像 Blender 主题一样按用途调整颜色。留空会跟随当前主题；右侧只预览界面关系，不会改动资源文件。")
        hint.setObjectName("MutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        follow_button = QPushButton("全部跟随当前主题")
        light_button = QPushButton("柔和浅色预设")
        dark_button = QPushButton("沉稳深色预设")
        follow_button.clicked.connect(lambda: self._apply_preset({}))
        light_button.clicked.connect(lambda: self._apply_preset(self._fallbacks))
        dark_button.clicked.connect(
            lambda: self._apply_preset(
                {
                    "ui_window_color": "#15191f",
                    "ui_sidebar_color": "#11151a",
                    "ui_card_color": "#20262e",
                    "ui_input_color": "#171c22",
                    "ui_text_color": "#eef2f7",
                    "ui_muted_text_color": "#9aa6b2",
                    "ui_border_color": "#343d48",
                    "ui_icon_color": "#d9e1ea",
                    "ui_button_hover_color": "#2c3540",
                    "ui_button_selected_color": "#4f86d9",
                }
            )
        )
        for button in (follow_button, light_button, dark_button):
            button.setObjectName("ThemePresetButton")
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        body = QHBoxLayout()
        body.setSpacing(16)
        controls_scroll = QScrollArea()
        controls_scroll.setObjectName("ThemeControlsScroll")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.NoFrame)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 4, 0)
        controls_layout.setSpacing(10)
        controls_scroll.setWidget(controls)
        body.addWidget(controls_scroll, 1)

        self.edits: dict[str, QLineEdit] = {}
        role_map = {key: (label, fallback) for key, label, fallback in self.ROLES}
        for group_name, keys in self.GROUPS:
            group_title = QLabel(group_name)
            group_title.setObjectName("ThemeGroupTitle")
            controls_layout.addWidget(group_title)
            for key in keys:
                label, fallback = role_map[key]
                edit = QLineEdit(str(settings.get(key) or ""))
                edit.setPlaceholderText("跟随主题")
                edit.setFixedWidth(112)
                self.edits[key] = edit
                controls_layout.addWidget(self._role_row(key, label, fallback, edit))
        controls_layout.addStretch(1)

        preview = QFrame()
        preview.setObjectName("ThemePreviewPanel")
        preview.setFixedWidth(250)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(9)
        preview_title = QLabel("实时预览")
        preview_title.setObjectName("ThemeGroupTitle")
        preview_layout.addWidget(preview_title)
        self.preview_window = QFrame()
        window_layout = QHBoxLayout(self.preview_window)
        window_layout.setContentsMargins(7, 7, 7, 7)
        window_layout.setSpacing(7)
        self.preview_sidebar = QFrame()
        self.preview_sidebar.setFixedWidth(54)
        sidebar_layout = QVBoxLayout(self.preview_sidebar)
        sidebar_layout.setContentsMargins(6, 7, 6, 7)
        sidebar_layout.addWidget(QLabel("资源库"))
        sidebar_layout.addStretch(1)
        window_layout.addWidget(self.preview_sidebar)
        preview_content = QVBoxLayout()
        self.preview_primary = QLabel("资源卡片")
        self.preview_muted = QLabel("说明与状态文字")
        self.preview_input = QLineEdit("路径或网址")
        self.preview_input.setReadOnly(True)
        self.preview_card = QFrame()
        card_layout = QVBoxLayout(self.preview_card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.addWidget(self.preview_primary)
        card_layout.addWidget(self.preview_muted)
        self.preview_button = QPushButton("选中 / 主操作")
        card_layout.addWidget(self.preview_input)
        card_layout.addWidget(self.preview_button)
        preview_content.addWidget(self.preview_card)
        preview_content.addStretch(1)
        window_layout.addLayout(preview_content, 1)
        preview_layout.addWidget(self.preview_window, 1)
        body.addWidget(preview)
        layout.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("应用配色")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_preview()

    def _role_row(self, key: str, label: str, fallback: str, edit: QLineEdit) -> QWidget:
        row = QFrame()
        row.setObjectName("ThemeRoleRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 8, 8)
        row_layout.setSpacing(8)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        role_label = QLabel(label)
        role_label.setObjectName("ThemeRoleLabel")
        role_description = QLabel(self.ROLE_DESCRIPTIONS.get(key, ""))
        role_description.setObjectName("ThemeRoleDescription")
        text_layout.addWidget(role_label)
        text_layout.addWidget(role_description)
        row_layout.addLayout(text_layout, 1)
        row_layout.addWidget(edit)
        swatch = QPushButton()
        swatch.setObjectName("ThemeSwatchButton")
        swatch.setToolTip(f"选择{label}")
        swatch.setFixedSize(44, 32)
        reset = QToolButton()
        reset.setText("↺")
        reset.setToolTip("恢复为跟随主题")
        reset.setObjectName("ThemeResetButton")
        reset.setFixedSize(30, 30)
        reset.clicked.connect(edit.clear)

        def choose() -> None:
            current = optional_color(edit.text()) or fallback
            color = choose_project_color(self, current, f"选择{label}")
            if color is not None:
                edit.setText(color.name())

        def refresh(_text: str = "") -> None:
            value = optional_color(edit.text()) or fallback
            fg = "#ffffff" if QColor(value).lightness() < 135 else "#17202a"
            swatch.setStyleSheet(
                f"QPushButton {{ background: {value}; color: {fg}; border: 1px solid rgba(0,0,0,40); border-radius: 8px; }}"
            )
            self._refresh_preview()

        swatch.clicked.connect(choose)
        edit.textChanged.connect(refresh)
        refresh()
        row_layout.addWidget(swatch)
        row_layout.addWidget(reset)
        return row

    def _apply_preset(self, values: dict[str, str]) -> None:
        for key, edit in self.edits.items():
            edit.setText(str(values.get(key) or ""))
        self._refresh_preview()

    def _role_color(self, key: str) -> str:
        return optional_color(self.edits[key].text()) or self._fallbacks[key]

    def _refresh_preview(self) -> None:
        if not hasattr(self, "preview_window"):
            return
        window = self._role_color("ui_window_color")
        sidebar = self._role_color("ui_sidebar_color")
        card = self._role_color("ui_card_color")
        input_color = self._role_color("ui_input_color")
        text_color = self._role_color("ui_text_color")
        muted = self._role_color("ui_muted_text_color")
        border = self._role_color("ui_border_color")
        selected = self._role_color("ui_button_selected_color")
        self.preview_window.setStyleSheet(f"QFrame {{ background:{window}; border:1px solid {border}; border-radius:9px; }}")
        self.preview_sidebar.setStyleSheet(f"QFrame {{ background:{sidebar}; border:1px solid {border}; border-radius:7px; }} QLabel {{ color:{text_color}; border:none; }}")
        self.preview_card.setStyleSheet(f"QFrame {{ background:{card}; border:1px solid {border}; border-radius:7px; }}")
        self.preview_primary.setStyleSheet(f"color:{text_color}; font-weight:800; border:none;")
        self.preview_muted.setStyleSheet(f"color:{muted}; border:none;")
        self.preview_input.setStyleSheet(f"background:{input_color}; color:{text_color}; border:1px solid {border}; border-radius:6px; padding:5px;")
        selected_fg = "#ffffff" if QColor(selected).lightness() < 145 else "#17202a"
        self.preview_button.setStyleSheet(f"background:{selected}; color:{selected_fg}; border:none; border-radius:6px; padding:6px;")

    def values(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.edits.items()}


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setObjectName("SettingsDialog")
        self.setMinimumWidth(600)
        self.resize(640, 780)
        self.settings = dict(settings)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 12)
        outer_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll, 1)

        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.resource_root_edit = QLineEdit(str(self.settings.get("resource_root", "")))
        self.deepseek_base_edit = QLineEdit(str(self.settings.get("deepseek_base_url", "")))
        self.deepseek_flash_edit = QLineEdit(str(self.settings.get("deepseek_flash_model", "deepseek-v4-flash")))
        self.deepseek_pro_edit = QLineEdit(str(self.settings.get("deepseek_pro_model", "deepseek-v4-pro")))
        self.deepseek_tier_combo = QComboBox()
        self.deepseek_tier_combo.addItem("Flash（默认，省钱）", "flash")
        self.deepseek_tier_combo.addItem("Pro（更强，花费更高）", "pro")
        tier_index = self.deepseek_tier_combo.findData(str(self.settings.get("deepseek_default_tier") or "flash"))
        self.deepseek_tier_combo.setCurrentIndex(max(0, tier_index))
        self.deepseek_current_label = QLabel("")
        self.deepseek_current_label.setObjectName("MutedText")
        self.deepseek_current_label.setWordWrap(True)
        self.deepseek_env_edit = QLineEdit(str(self.settings.get("deepseek_api_key_env", "")))
        prefilled_key = deepseek_api_key(self.settings) if deepseek_api_key_source(self.settings) == "file" else ""
        self.deepseek_key_edit = QLineEdit(prefilled_key)
        self.deepseek_key_edit.setEchoMode(QLineEdit.Password)
        self.deepseek_key_edit.setPlaceholderText("把 DeepSeek API Key 粘贴到这里")
        self._prefilled_key = prefilled_key
        self.translation_mode_combo = QComboBox()
        for label, value in [
            ("中文名 + 原英文名", "zh_en"),
            ("原英文名 + 中文名", "en_zh"),
            ("只有中文名", "zh_only"),
            ("保留原英文名", "en_only"),
        ]:
            self.translation_mode_combo.addItem(label, value)
        translation_index = self.translation_mode_combo.findData(str(self.settings.get("translation_name_mode") or "zh_en"))
        self.translation_mode_combo.setCurrentIndex(max(0, translation_index))
        self.btn_test_deepseek = QPushButton("验证当前模型")
        self.btn_test_deepseek.setIcon(make_line_icon("check"))
        self.btn_test_deepseek.setObjectName("SettingsActionButton")
        self.btn_test_deepseek.setFixedHeight(32)
        self.btn_test_deepseek.clicked.connect(self._test_deepseek_api)
        self.btn_create_deepseek_key = QPushButton("创建 API Key")
        self.btn_create_deepseek_key.setIcon(make_line_icon("web"))
        self.btn_create_deepseek_key.setObjectName("SettingsActionButton")
        self.btn_create_deepseek_key.setFixedHeight(32)
        self.btn_create_deepseek_key.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DEEPSEEK_API_KEYS_URL))
        )
        self.auto_index_check = QCheckBox("打开资源库路径时刷新快速索引")
        self.auto_index_check.setChecked(bool(self.settings.get("auto_index_on_library_open", True)))
        self.rename_after_translate_check = QCheckBox("翻译后同步重命名本地文件夹（可在重命名日志撤销）")
        self.rename_after_translate_check.setChecked(bool(self.settings.get("rename_local_after_translate", True)))
        self.cleanup_after_move_check = QCheckBox("移动成功后清理原来源链路中的空目录")
        self.cleanup_after_move_check.setChecked(bool(self.settings.get("cleanup_empty_source_parents_after_move", False)))
        self.preview_cache_limit_spin = QSpinBox()
        self.preview_cache_limit_spin.setRange(128, 102400)
        self.preview_cache_limit_spin.setSuffix(" MB")
        self.preview_cache_limit_spin.setValue(int(self.settings.get("preview_cache_max_mb") or 2048))
        self.preview_cache_age_spin = QSpinBox()
        self.preview_cache_age_spin.setRange(7, 3650)
        self.preview_cache_age_spin.setSuffix(" 天")
        self.preview_cache_age_spin.setValue(int(self.settings.get("preview_cache_max_age_days") or 180))
        self.move_log_limit_spin = QSpinBox()
        self.move_log_limit_spin.setRange(100, 1000000)
        self.move_log_limit_spin.setSuffix(" 条")
        self.move_log_limit_spin.setValue(int(self.settings.get("move_log_max_records") or 10000))
        self.move_log_age_spin = QSpinBox()
        self.move_log_age_spin.setRange(30, 3650)
        self.move_log_age_spin.setSuffix(" 天")
        self.move_log_age_spin.setValue(int(self.settings.get("move_log_max_age_days") or 730))
        self.btn_cleanup_runtime = QPushButton("检查并清理工作台运行数据")
        self.btn_cleanup_runtime.setObjectName("SettingsActionButton")
        self.btn_cleanup_runtime.setFixedHeight(32)
        self.btn_cleanup_runtime.clicked.connect(self._request_runtime_cleanup)
        self.use_qfluent_check = QCheckBox("启用 QFluentWidgets（未安装时使用内置 Fluent 风格）")
        self.use_qfluent_check.setChecked(bool(self.settings.get("use_qfluentwidgets", True)))
        self.theme_combo = QComboBox()
        for label, value in [
            ("清晰工作台", "claude_light"),
            ("Fluent 深色", "fluent_dark"),
            ("Fluent 浅色", "fluent_light"),
            ("经典浅色", "classic"),
        ]:
            self.theme_combo.addItem(label, value)
        theme_index = self.theme_combo.findData(str(self.settings.get("ui_theme") or "claude_light"))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.accent_color_edit = QLineEdit(str(self.settings.get("ui_accent_color") or "#2563eb"))
        self.panel_color_edit = QLineEdit(str(self.settings.get("ui_panel_color") or ""))
        self.panel_color_edit.setPlaceholderText("留空跟随主题，例如 #202936")
        self.canvas_color_edit = QLineEdit(str(self.settings.get("ui_canvas_color") or ""))
        self.canvas_color_edit.setPlaceholderText("留空跟随主题，例如 #111827")
        self.button_color_edit = QLineEdit(str(self.settings.get("ui_button_color") or ""))
        self.button_color_edit.setPlaceholderText("留空跟随主题，例如 #273449")
        self.semantic_colors = {
            key: str(self.settings.get(key) or "")
            for key, _label, _fallback in SemanticThemeDialog.ROLES
        }
        self.btn_semantic_colors = QPushButton()
        self.btn_semantic_colors.setObjectName("SettingsActionButton")
        self.btn_semantic_colors.setFixedHeight(32)
        self.btn_semantic_colors.clicked.connect(self._open_semantic_colors)
        self._refresh_semantic_color_button()
        self.auto_extract_check = QCheckBox("自动解压已关闭：请先手动解压资源后再分析移动")
        self.auto_extract_check.setChecked(False)
        self.auto_extract_check.setEnabled(False)

        path_section = QLabel("路径")
        path_section.setObjectName("SettingsSectionTitle")
        layout.addWidget(path_section)
        form.addRow("资源库根路径", self._path_row(self.resource_root_edit))
        layout.addLayout(form)

        ds_section = QLabel("DeepSeek")
        ds_section.setObjectName("SettingsSectionTitle")
        layout.addWidget(ds_section)
        ds_form = QFormLayout()
        ds_form.setLabelAlignment(Qt.AlignRight)
        ds_form.addRow("API 地址", self.deepseek_base_edit)
        ds_form.addRow("调用档位", self.deepseek_tier_combo)
        ds_form.addRow("当前会用", self.deepseek_current_label)
        ds_form.addRow("Flash 模型 ID", self.deepseek_flash_edit)
        ds_form.addRow("Pro 模型 ID", self.deepseek_pro_edit)
        ds_form.addRow("翻译命名", self.translation_mode_combo)
        ds_form.addRow("API Key", self.deepseek_key_edit)
        ds_form.addRow("没有 Key", self.btn_create_deepseek_key)
        ds_form.addRow("Key 环境变量", self.deepseek_env_edit)
        ds_form.addRow("联网验证", self.btn_test_deepseek)
        layout.addLayout(ds_form)

        behavior_section = QLabel("行为")
        behavior_section.setObjectName("SettingsSectionTitle")
        layout.addWidget(behavior_section)
        layout.addWidget(self.auto_index_check)
        layout.addWidget(self.rename_after_translate_check)
        layout.addWidget(self.cleanup_after_move_check)
        layout.addWidget(self.auto_extract_check)
        retention_form = QFormLayout()
        retention_form.setLabelAlignment(Qt.AlignRight)
        retention_form.addRow("预览缓存上限", self._retention_row(self.preview_cache_limit_spin, self.preview_cache_age_spin))
        retention_form.addRow("移动日志保留", self._retention_row(self.move_log_limit_spin, self.move_log_age_spin))
        retention_form.addRow("清理工作台数据", self.btn_cleanup_runtime)
        layout.addLayout(retention_form)

        appearance_section = QLabel("界面")
        appearance_section.setObjectName("SettingsSectionTitle")
        layout.addWidget(appearance_section)
        appearance_form = QFormLayout()
        appearance_form.setLabelAlignment(Qt.AlignRight)
        appearance_form.addRow("主题", self.theme_combo)
        appearance_form.addRow("强调色", self._color_row(self.accent_color_edit, "#2563eb"))
        appearance_form.addRow("面板色", self._color_row(self.panel_color_edit, "#ffffff"))
        appearance_form.addRow("画布色", self._color_row(self.canvas_color_edit, "#eef2f7"))
        appearance_form.addRow("按钮色", self._color_row(self.button_color_edit, "#edf1f5"))
        appearance_form.addRow("语义颜色", self.btn_semantic_colors)
        layout.addLayout(appearance_form)
        layout.addWidget(self.use_qfluent_check)

        source_label = {"env": "来自环境变量", "file": "来自本机保存", "none": "未检测到"}[deepseek_api_key_source(self.settings)]
        hint = QLabel(
            f"DeepSeek Key 当前：{source_label}。可直接在上面 API Key 框粘贴，保存后写入本机 "
            "workbench_data\\secret.json（不进版本库、不随设置分享）。若设置了环境变量，则环境变量优先。"
        )
        hint.setObjectName("MutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存设置")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer_layout.addWidget(buttons)
        self.deepseek_tier_combo.currentIndexChanged.connect(lambda _i: self._sync_deepseek_model_hint())
        self.deepseek_flash_edit.textChanged.connect(lambda _text: self._sync_deepseek_model_hint())
        self.deepseek_pro_edit.textChanged.connect(lambda _text: self._sync_deepseek_model_hint())
        self._sync_deepseek_model_hint()

    def _sync_deepseek_model_hint(self) -> None:
        tier = str(self.deepseek_tier_combo.currentData() or "flash")
        if tier == "pro":
            model = self.deepseek_pro_edit.text().strip() or "deepseek-v4-pro"
            label = "Pro"
            note = "更适合难判断资源，花费更高"
        else:
            model = self.deepseek_flash_edit.text().strip() or "deepseek-v4-flash"
            label = "Flash"
            note = "默认使用，速度快、花费低"
        self.deepseek_current_label.setText(f"{label}：{model}（{note}）。翻译命名和分类建议都会调用这一档。")

    def _path_row(self, edit: QLineEdit) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(edit, 1)
        button = QPushButton()
        icon_color = "#edf5ff" if str(self.settings.get("ui_theme") or "") == "fluent_dark" else "#17202a"
        button.setIcon(make_line_icon("folder", icon_color))
        button.setObjectName("ToolbarIconButton")
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(20, 20))
        button.clicked.connect(lambda: self._choose_path(edit))
        layout.addWidget(button)
        return row

    def _color_row(self, edit: QLineEdit, fallback: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        edit.setPlaceholderText(edit.placeholderText() or "例如 #2563eb")
        layout.addWidget(edit, 1)
        button = QPushButton()
        button.setToolTip("选择颜色")
        button.setObjectName("ToolbarIconButton")
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(20, 20))
        button.clicked.connect(lambda: self._choose_color(edit, fallback))
        layout.addWidget(button)

        def refresh(_text: str = "") -> None:
            value = edit.text().strip() or fallback
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                value = fallback
            fg = "#ffffff" if QColor(value).lightness() < 135 else "#17202a"
            button.setStyleSheet(
                f"QPushButton {{ background: {value}; color: {fg}; border: 1px solid rgba(0,0,0,40); border-radius: 8px; }}"
            )
            button.setIcon(make_line_icon("settings", fg))

        edit.textChanged.connect(refresh)
        refresh()
        return row

    def _choose_color(self, edit: QLineEdit, fallback: str) -> None:
        current = edit.text().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", current):
            current = fallback
        color = choose_project_color(self, current, "选择颜色")
        if color is not None:
            edit.setText(color.name())

    def _choose_path(self, edit: QLineEdit) -> None:
        start = edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择路径", start)
        if folder:
            edit.setText(folder)

    def _test_deepseek_api(self) -> None:
        self.btn_test_deepseek.setEnabled(False)
        self.btn_test_deepseek.setText("验证中")
        QApplication.processEvents()
        tier = str(self.deepseek_tier_combo.currentData() or "flash")
        result = test_deepseek_connection(self.values(), timeout_seconds=20, tier=tier)
        self.btn_test_deepseek.setEnabled(True)
        self.btn_test_deepseek.setText("验证当前模型")
        if result.get("ok"):
            QMessageBox.information(self, "DeepSeek 可用", f"已连通当前模型：{result.get('model', '')}")
        else:
            QMessageBox.warning(self, "DeepSeek 不可用", str(result.get("error") or "验证失败"))

    def values(self) -> dict:
        updated = dict(self.settings)
        updated["resource_root"] = self.resource_root_edit.text().strip()
        updated["deepseek_base_url"] = self.deepseek_base_edit.text().strip()
        updated["deepseek_flash_model"] = self.deepseek_flash_edit.text().strip() or "deepseek-v4-flash"
        updated["deepseek_pro_model"] = self.deepseek_pro_edit.text().strip() or "deepseek-v4-pro"
        updated["deepseek_default_tier"] = str(self.deepseek_tier_combo.currentData() or "flash")
        updated["deepseek_api_key_env"] = self.deepseek_env_edit.text().strip() or "DEEPSEEK_API_KEY"
        updated["translation_name_mode"] = str(self.translation_mode_combo.currentData() or "zh_en")
        updated["auto_index_on_library_open"] = self.auto_index_check.isChecked()
        updated["auto_extract_archives_before_analysis"] = False
        updated["rename_local_after_translate"] = self.rename_after_translate_check.isChecked()
        updated["cleanup_empty_source_parents_after_move"] = self.cleanup_after_move_check.isChecked()
        updated["preview_cache_max_mb"] = self.preview_cache_limit_spin.value()
        updated["preview_cache_max_age_days"] = self.preview_cache_age_spin.value()
        updated["move_log_max_records"] = self.move_log_limit_spin.value()
        updated["move_log_max_age_days"] = self.move_log_age_spin.value()
        updated["use_qfluentwidgets"] = self.use_qfluent_check.isChecked()
        updated["ui_theme"] = str(self.theme_combo.currentData() or "claude_light")
        updated["ui_accent_color"] = self.accent_color_edit.text().strip() or "#2563eb"
        updated["ui_panel_color"] = self.panel_color_edit.text().strip()
        updated["ui_canvas_color"] = self.canvas_color_edit.text().strip()
        updated["ui_button_color"] = self.button_color_edit.text().strip()
        updated.update(self.semantic_colors)
        return updated

    def _open_semantic_colors(self) -> None:
        dialog = SemanticThemeDialog(self.semantic_colors, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.semantic_colors.update(dialog.values())
        self._refresh_semantic_color_button()

    def _refresh_semantic_color_button(self) -> None:
        custom_count = sum(1 for value in self.semantic_colors.values() if optional_color(value))
        suffix = f"（已自定义 {custom_count} 项）" if custom_count else "（全部跟随主题）"
        self.btn_semantic_colors.setText("窗口 / 侧栏 / 卡片 / 文字等 " + suffix)

    def _retention_row(self, limit_spin: QSpinBox, age_spin: QSpinBox) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(limit_spin)
        row_layout.addWidget(QLabel("或最近"))
        row_layout.addWidget(age_spin)
        row_layout.addStretch(1)
        return row

    def _request_runtime_cleanup(self) -> None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "cleanup_runtime_data"):
            parent.cleanup_runtime_data(settings_override=self.values(), ask_confirmation=True)

    def api_key_input(self) -> tuple[bool, str]:
        """返回 (是否改动, Key 文本)。用于决定是否写入本地 secret 文件。"""
        text = self.deepseek_key_edit.text().strip()
        return (text != self._prefilled_key, text)


class TargetPickerDialog(QDialog):
    """Pinterest 式目标分类选择器：先给推荐的近似文件夹，可搜索、点进去翻、选中一个再确认。"""

    def __init__(
        self,
        card: dict,
        resource_root: Path,
        parent: QWidget | None = None,
        move_log: MoveLog | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择目标分类")
        self.setMinimumSize(560, 600)
        self.resource_root = Path(resource_root)
        self.card = card
        self.move_log = move_log
        self._selected_path: str | None = None
        self.current_base = self.resource_root
        self.recommended: list[dict] = []
        self.suggested_new: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        tip = QLabel("先看推荐分类，点进去翻一翻，选中一个文件夹再确认。这只是选择目标，不会立即移动。")
        tip.setObjectName("MutedText")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.btn_up = QPushButton("返回上一级")
        self.btn_up.clicked.connect(self._go_up)
        nav_row.addWidget(self.btn_up)
        self.crumb = QLabel("")
        self.crumb.setObjectName("PickerCrumb")
        self.crumb.setWordWrap(True)
        nav_row.addWidget(self.crumb, 1)
        layout.addLayout(nav_row)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索这一层的文件夹名")
        self.search_edit.textChanged.connect(lambda _t: self._refresh_list())
        layout.addWidget(self.search_edit)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        self.selected_label = QLabel("尚未选择目标")
        self.selected_label.setObjectName("MutedText")
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)

        btn_row = QHBoxLayout()
        self.btn_pick_here = QPushButton("选择当前这层目录")
        self.btn_pick_here.clicked.connect(self._pick_current_base)
        btn_row.addWidget(self.btn_pick_here)
        btn_row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("选这个文件夹")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self._confirm)
        self.buttons.rejected.connect(self.reject)
        btn_row.addWidget(self.buttons)
        layout.addLayout(btn_row)

        self.setStyleSheet(
            "QDialog { background:#f7f8fa; }"
            "#PickerCrumb { color:#0f172a; font-size:13px; font-weight:700;"
            " background:#e7ecf3; border-radius:6px; padding:6px 10px; }"
            "QListWidget { background:#ffffff; border:1px solid #d7dbe0;"
            " border-radius:8px; font-size:13px; outline:0; }"
            "QListWidget::item { padding:9px 10px; border-bottom:1px solid #eef1f4; }"
            "QListWidget::item:selected { background:#2563eb; color:#ffffff; }"
            "#MutedText { color:#475569; }"
            "QPushButton { padding:6px 12px; border-radius:6px; }"
        )

        self._recommend()

    def selected_path(self) -> str | None:
        return self._selected_path

    def _confirm(self) -> None:
        if not self._selected_path:
            QMessageBox.information(self, "还没选择", "请选中一个文件夹，或点“选择当前这层目录”。")
            return
        self.accept()

    def _recommend(self) -> None:
        result = recommend_target_folders(self.card, self.resource_root, move_log=self.move_log)
        if not result.get("ok"):
            self._refresh_list(error=result.get("error"))
            return
        self.current_base = Path(result["base"])
        self.recommended = result["candidates"]
        self.suggested_new = result.get("suggested_new")
        self._refresh_list(show_recommended=True)

    def _refresh_list(self, show_recommended: bool = False, error: str | None = None) -> None:
        self.list_widget.clear()
        self.crumb.setText("母路径：" + self._relative(self.current_base))
        if error:
            item = QListWidgetItem(f"⚠ {error}")
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
            return

        filter_text = self.search_edit.text().strip().lower()

        if self.suggested_new and not filter_text:
            rel = self._relative(Path(self.suggested_new))
            item = QListWidgetItem(f"＋ 新建并使用：{rel}")
            item.setData(Qt.UserRole, {"path": self.suggested_new, "new": True})
            self.list_widget.addItem(item)

        if show_recommended and self.recommended and not filter_text:
            header = QListWidgetItem("— 推荐分类（按相近度）—")
            header.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(header)
            for cand in self.recommended:
                if cand.get("is_history_match"):
                    history_count = int(cand.get("history_count") or 0)
                    prefix = f"↻ 习惯推荐 ×{history_count}"
                else:
                    prefix = "★ 推荐"
                item = QListWidgetItem(f"{prefix}  {cand['name']}    （{cand['relative']}）")
                item.setData(Qt.UserRole, {"path": cand["path"], "new": False})
                self.list_widget.addItem(item)
            sep = QListWidgetItem("— 这一层的全部文件夹 —")
            sep.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(sep)

        shown = 0
        for child in browse_subfolders(self.current_base, self.resource_root):
            if filter_text and filter_text not in child["name"].lower():
                continue
            item = QListWidgetItem(f"{child['name']}      ›")
            item.setData(Qt.UserRole, {"path": child["path"], "new": False})
            self.list_widget.addItem(item)
            shown += 1
        if shown == 0 and not filter_text:
            hint = QListWidgetItem("（这一层没有更细的子文件夹；可点下方“选择当前这层目录”）")
            hint.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(hint)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not data:
            return
        self._set_selected(data["path"], bool(data.get("new")))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not data or data.get("new"):
            return
        path = Path(data["path"])
        if path.is_dir():
            self.current_base = path
            self.search_edit.clear()
            self._refresh_list(show_recommended=False)

    def _pick_current_base(self) -> None:
        self._set_selected(str(self.current_base), False)

    def _set_selected(self, path: str, is_new: bool) -> None:
        self._selected_path = path
        prefix = "将新建并移动到：" if is_new else "将移动到："
        self.selected_label.setText(prefix + self._relative(Path(path)))

    def _go_up(self) -> None:
        if Path(self.current_base) == self.resource_root:
            return
        parent = Path(self.current_base).parent
        try:
            parent.relative_to(self.resource_root)
        except ValueError:
            return
        self.current_base = parent
        self.search_edit.clear()
        self._refresh_list(show_recommended=False)

    def _relative(self, path: Path) -> str:
        try:
            rel = str(Path(path).relative_to(self.resource_root))
            return rel if rel != "." else Path(self.resource_root).name
        except ValueError:
            return str(path)


class ResourceWorkbenchWindow(QMainWindow):
    def __init__(self, initial_path: Path | None = None, auto_run: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("资源入库工作台")
        self.setWindowIcon(_app_icon())
        self.resize(1520, 900)
        self.setMinimumSize(1220, 720)

        self.cards: list[dict] = []
        self.view_cards: dict[str, list[dict]] = {"work": [], "library": []}
        self.view_paths: dict[str, Path | None] = {"work": None, "library": None}
        self.view_selected: dict[str, int | None] = {"work": None, "library": None}
        self.active_view = "work"
        self.input_paths: list[Path] = []
        self.current_input_path: Path | None = None
        self.current_card_index: int | None = None
        self.select_mode = False
        self.selected_indices: set[int] = set()
        self.current_report: Path | None = None
        self.current_report_dir = DATA_ROOT / "reports"
        self.preview_cache_dir = DATA_ROOT / "workbench_data" / "previews"
        self.staging_root = DATA_ROOT / "workbench_data" / "staging"
        self.thread: QThread | None = None
        self.worker: AnalyzeWorker | None = None
        self.analysis_cancel_requested = False
        self.web_import_active = False
        self.web_import_cancel_requested = False
        self.deep_thread: QThread | None = None
        self.deep_worker: DeepAnalyzeWorker | None = None
        self.library_index_thread: QThread | None = None
        self.library_index_worker: LibraryIndexWorker | None = None
        self.maintenance_thread: QThread | None = None
        self.maintenance_worker: MaintenanceWorker | None = None
        self.pending_library_preload_root: Path | None = None
        self.pending_library_preload_depth: int | None = None
        self.library_root_path: Path | None = None
        self._library_path_signatures: dict[str, tuple] = {}
        self._pending_library_refresh_paths: set[str] = set()
        self._library_signature_task: _LibrarySignatureTask | None = None
        self._library_tree_generation = 0
        self._library_tree_closing = False
        self._library_tree_request_seq = 0
        self._library_tree_tasks: dict[int, _LibraryTreeReadTask] = {}
        self._library_tree_available_keys: set[str] = set()
        self._library_tree_restore_expanded: dict[str, Path] = {}
        self._library_tree_restore_selected: Path | None = None
        self.settings = load_settings(DATA_ROOT)
        self.runtime_maintenance = RuntimeMaintenanceController(DATA_ROOT, self)
        self._runtime_maintenance_request: dict | None = None
        self._runtime_maintenance_close_pending = False
        self.runtime_maintenance.finished.connect(self._on_runtime_maintenance_finished)
        self.runtime_maintenance.duplicate_rejected.connect(self._on_runtime_maintenance_duplicate)
        self.library_watcher = QFileSystemWatcher(self)
        self.library_watcher.directoryChanged.connect(self._queue_library_path_refresh)
        self.library_refresh_timer = QTimer(self)
        self.library_refresh_timer.setSingleShot(True)
        self.library_refresh_timer.setInterval(650)
        self.library_refresh_timer.timeout.connect(self._flush_library_path_refreshes)
        self.library_poll_timer = QTimer(self)
        self.library_poll_timer.setInterval(4000)
        self.library_poll_timer.timeout.connect(self._poll_library_signatures)
        self.library_poll_timer.start()
        self.resource_index = ResourceIndex(index_db_path(DATA_ROOT))
        try:
            self.review_queue = ReviewQueue(default_queue_path(DATA_ROOT))
        except Exception:
            self.review_queue = None
        try:
            self.card_metadata = CardMetadataStore(default_metadata_path(DATA_ROOT))
        except Exception:
            self.card_metadata = None
        try:
            self.rename_log = RenameLog(default_rename_log_path(DATA_ROOT))
        except Exception:
            self.rename_log = None

        default_path = initial_path if initial_path is not None else None
        if default_path is not None and not default_path.exists():
            default_path = None
        self.path_edit = QLineEdit(str(default_path) if default_path is not None else "")
        self.path_edit.setPlaceholderText("粘贴待整理路径、压缩包路径，或网页链接")
        self.path_edit.setMinimumWidth(420)
        self.path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.filter_edit = QLineEdit()
        self.filter_edit.setMinimumWidth(140)
        self.filter_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.filter_edit.setPlaceholderText("搜索名称、标签、分类")
        self.depth_combo = QComboBox()
        self.depth_combo.setObjectName("DepthCombo")
        self.depth_combo.setToolTip("资源卡片按几层文件夹合并。自动适合已整理资源库；多级课程可切到 3 层或 4 层重扫。")
        self.depth_combo.addItem("自动", None)
        for depth in range(1, 5):
            self.depth_combo.addItem(f"{depth} 层", depth)
        self.status_label = QLabel("准备就绪：只读模式，不移动、不删除、不上传。")
        self.summary_label = QLabel("选择一个批次后开始分析。")

        self.status_label.setObjectName("StatusBar")
        self.status_label.setMinimumHeight(28)
        self.status_label.setWordWrap(False)
        self.status_label.setMaximumWidth(520)
        self.summary_label.setObjectName("SummaryText")
        self.summary_label.setMinimumWidth(0)
        self.summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.analysis_progress = QProgressBar()
        self.analysis_progress.setObjectName("AnalysisProgress")
        self.analysis_progress.setFixedHeight(5)
        self.analysis_progress.setTextVisible(False)
        self.analysis_progress.setRange(0, 100)
        self.analysis_progress.setValue(0)
        self.analysis_progress.hide()

        self._build_ui()
        self._apply_style()

        if auto_run:
            QTimer.singleShot(120, self.start_analysis)
        else:
            QTimer.singleShot(120, self.load_startup_library)
        QTimer.singleShot(1800, self._auto_prune_runtime_data)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(226)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(12, 16, 10, 14)
        side_layout.setSpacing(8)

        self.btn_analyze = QPushButton()
        self.btn_cancel_analysis = QPushButton("取消分析")
        self.btn_cancel_analysis_inline = QPushButton("取消分析")
        self.btn_translate_all = QPushButton()
        self.btn_overview = QPushButton()
        self.btn_review_queue = QPushButton()
        self.btn_history = QPushButton()
        self.btn_select_mode = QPushButton("多选")
        self.btn_select_mode.setCheckable(True)
        self.btn_select_all = QPushButton("全选")
        self.btn_clear_sel = QPushButton("清空")
        self.btn_translate_selected = QPushButton("翻译选中")
        self.btn_format_selected = QPushButton("整理选中")
        self.btn_move_selected = QPushButton("移动选中")
        self.btn_library = QPushButton()
        self.btn_review_plan = QPushButton()
        self.btn_agent = QPushButton()
        self.btn_report = QPushButton()
        self.btn_report_dir = QPushButton()
        self.btn_dedupe = QPushButton()
        self.btn_cleanup = QPushButton()
        self.btn_change_target = QPushButton("修改目标分类")
        self.btn_mark_review = QPushButton("标记需确认")
        self.btn_settings = QToolButton()
        self.btn_new_library_folder = QToolButton()
        self.btn_refresh_library = QToolButton()

        self.library_box = QFrame()
        self.library_box.setObjectName("SidebarLibraryBox")
        library_layout = QVBoxLayout(self.library_box)
        library_layout.setContentsMargins(8, 8, 8, 8)
        library_layout.setSpacing(6)
        library_title_row = QHBoxLayout()
        library_title_row.setSpacing(4)
        path_title = QLabel("资源库")
        path_title.setObjectName("SidebarSectionTitle")
        library_title_row.addWidget(path_title)
        library_title_row.addStretch(1)
        for button, icon_name, tooltip in (
            (self.btn_new_library_folder, "add", "在选中的资源库目录中新建文件夹"),
            (self.btn_refresh_library, "refresh", "刷新资源库目录和当前卡片"),
        ):
            button.setObjectName("SidebarMiniButton")
            button.setIcon(make_line_icon(icon_name, self._sidebar_icon_color()))
            button.setToolTip(tooltip)
            button.setFixedSize(28, 26)
            button.setIconSize(QSize(16, 16))
            button.setAutoRaise(False)
            library_title_row.addWidget(button)
        library_layout.addLayout(library_title_row)
        self.path_tree = ExplorerTreeWidget()
        self.path_tree.setObjectName("PathTree")
        self.path_tree.setMinimumHeight(420)
        self.path_tree.setIconSize(QSize(18, 18))
        self.path_tree.setHeaderHidden(True)
        self.path_tree.setRootIsDecorated(True)
        self.path_tree.setItemsExpandable(True)
        self.path_tree.setExpandsOnDoubleClick(False)
        self.path_tree.setIndentation(18)
        self.path_tree.setUniformRowHeights(True)
        self.path_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.path_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        library_layout.addWidget(self.path_tree, 1)
        side_layout.addWidget(self.library_box, 1)

        side_footer = QHBoxLayout()
        side_footer.setSpacing(8)
        self.btn_settings.setIcon(make_line_icon("settings", "#f8fafc"))
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setObjectName("SidebarIconButton")
        self.btn_settings.setFixedSize(34, 32)
        self.btn_settings.setIconSize(QSize(19, 19))
        self.btn_settings.setAutoRaise(False)
        self.btn_settings.setToolButtonStyle(Qt.ToolButtonIconOnly)
        side_footer.addWidget(self.btn_settings)
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setObjectName("TinyText")
        self.version_label.setToolTip(f"资源入库工作台 {__version__}")
        side_footer.addStretch(1)
        side_footer.addWidget(self.version_label)
        side_layout.addLayout(side_footer)
        root_layout.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 14)
        content_layout.setSpacing(10)
        root_layout.addWidget(content, 1)

        hero = QFrame()
        hero.setObjectName("Hero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(12, 10, 12, 10)
        hero_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.btn_toggle_left = QPushButton()
        self.btn_toggle_left.setIcon(make_line_icon("panel-left"))
        self.btn_toggle_left.setObjectName("ToolbarIconButton")
        self.btn_toggle_left.setToolTip("收起/展开左侧")
        self.btn_toggle_left.setFixedSize(34, 32)
        self.btn_toggle_left.setIconSize(QSize(20, 20))
        top_row.addWidget(self.btn_toggle_left)
        self.btn_work_view = QPushButton("待整理")
        self.btn_library_view = QPushButton("资源库")
        for button in (self.btn_work_view, self.btn_library_view):
            button.setObjectName("ViewSwitchButton")
            button.setCheckable(True)
            button.setFixedHeight(32)
            top_row.addWidget(button)
        top_row.addWidget(self.summary_label, 1)
        self.btn_actions = QToolButton()
        self.btn_actions.setIcon(make_line_icon("more"))
        self.btn_actions.setObjectName("ToolbarIconButton")
        self.btn_actions.setToolTip("更多工具")
        self.btn_actions.setFixedSize(34, 32)
        self.btn_actions.setIconSize(QSize(20, 20))
        self.btn_actions.setAutoRaise(False)
        self.btn_actions.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_actions.setPopupMode(QToolButton.InstantPopup)
        actions_menu = QMenu(self.btn_actions)
        for label, icon_name, handler in [
            ("浏览资源库", "library", self.choose_library_folder),
            ("一键翻译", "translate", self.translate_all_cards),
            ("概览看板", "library", self.open_overview),
            ("审阅队列", "report", self.open_review_queue),
            ("操作记录", "archive", self.open_history),
            ("查找重复", "dedupe", self.find_duplicates_current),
            ("清理空目录", "cleanup", self.cleanup_empty_dirs_current),
        ]:
            action = QAction(make_line_icon(icon_name), label, self)
            action.triggered.connect(lambda _checked=False, slot=handler: slot())
            actions_menu.addAction(action)
        self.btn_actions.setMenu(actions_menu)
        top_row.addWidget(self.btn_actions)
        self.btn_select_mode.setObjectName("ViewSwitchButton")
        self.btn_select_mode.setFixedHeight(32)
        self.btn_select_mode.setToolTip("进入/退出多选模式：进入后单击勾选卡片、可拖动框选，顶部统一翻译/移动")
        top_row.addWidget(self.btn_select_mode)
        self._select_action_buttons = [
            self.btn_select_all, self.btn_clear_sel, self.btn_translate_selected, self.btn_format_selected, self.btn_move_selected,
        ]
        for sbtn, stip in [
            (self.btn_select_all, "全选当前视图所有卡片"),
            (self.btn_clear_sel, "清空已勾选"),
            (self.btn_translate_selected, "翻译勾选的卡片"),
            (self.btn_format_selected, "把勾选的资源批量整理为封面 + 工程结构"),
            (self.btn_move_selected, "把勾选的卡片一起移动到同一目标分类"),
        ]:
            sbtn.setObjectName("ViewSwitchButton")
            sbtn.setFixedHeight(32)
            sbtn.setToolTip(stip)
            sbtn.setVisible(False)
            top_row.addWidget(sbtn)
        self.btn_toggle_right = QPushButton()
        self.btn_toggle_right.setIcon(make_line_icon("panel-right"))
        self.btn_toggle_right.setObjectName("ToolbarIconButton")
        self.btn_toggle_right.setToolTip("查看/隐藏所选卡片详情")
        self.btn_toggle_right.setFixedSize(34, 32)
        self.btn_toggle_right.setIconSize(QSize(20, 20))
        top_row.addWidget(self.btn_toggle_right)
        hero_layout.addLayout(top_row)

        content_layout.addWidget(hero)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        splitter.setMinimumHeight(180)
        content_layout.addWidget(splitter, 1)

        left_panel = QFrame()
        left_panel.setObjectName("CanvasPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)
        self.analysis_state_box = QFrame()
        self.analysis_state_box.setObjectName("AnalysisStateBox")
        analysis_state_layout = QVBoxLayout(self.analysis_state_box)
        analysis_state_layout.setContentsMargins(14, 12, 14, 12)
        analysis_state_layout.setSpacing(8)
        self.analysis_status_text = ShimmerLabel("正在分析中，请稍后")
        self.analysis_status_text.setObjectName("AnalysisShimmerText")
        analysis_state_layout.addWidget(self.analysis_status_text)
        analysis_state_layout.addWidget(self.analysis_progress)
        inline_cancel_row = QHBoxLayout()
        inline_cancel_row.addStretch(1)
        self.btn_cancel_analysis_inline.setObjectName("CommandCancelButton")
        self.btn_cancel_analysis_inline.setFixedHeight(30)
        inline_cancel_row.addWidget(self.btn_cancel_analysis_inline)
        inline_cancel_row.addStretch(1)
        analysis_state_layout.addLayout(inline_cancel_row)
        self.analysis_state_box.hide()
        left_layout.addWidget(self.analysis_state_box)
        self.card_wall = MasonryCardWall()
        left_layout.addWidget(self.card_wall, 1)
        splitter.addWidget(left_panel)

        # 右侧常驻详情面板已移除：主区域全部留给卡片墙，详情/预览改为双击卡片时弹窗显示。
        self.detail_dialog = QDialog(self)
        self.detail_dialog.setWindowTitle("预览与判断")
        self.detail_dialog.setMinimumSize(460, 580)
        detail_dialog_layout = QVBoxLayout(self.detail_dialog)
        detail_dialog_layout.setContentsMargins(16, 14, 16, 14)
        detail_dialog_layout.setSpacing(12)

        self.preview_label = QLabel("暂无预览图")
        self.preview_label.setObjectName("PreviewBox")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedHeight(240)
        self.preview_label.setWordWrap(False)
        detail_dialog_layout.addWidget(self.preview_label)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_dialog_layout.addWidget(self.detail_text, 1)
        splitter.setSizes([1])

        command_bar = QFrame()
        self.command_bar = command_bar
        command_bar.setObjectName("CommandBar")
        command_bar.setAttribute(Qt.WA_StyledBackground, True)
        command_bar.setFixedHeight(58)
        command_layout = QVBoxLayout(command_bar)
        command_layout.setContentsMargins(10, 9, 10, 9)
        command_layout.setSpacing(0)

        command_input_row = QHBoxLayout()
        command_input_row.setSpacing(8)
        command_input_row.addWidget(self.path_edit, 1)
        self.btn_analyze.setIcon(make_line_icon("play"))
        self.btn_analyze.setText("\u5206\u6790")
        self.btn_analyze.setToolTip("\u5206\u6790\u5f85\u6574\u7406\u8def\u5f84")
        self.btn_analyze.setObjectName("CommandRunButton")
        self.btn_analyze.setMinimumWidth(84)
        self.btn_analyze.setFixedHeight(36)
        self.btn_analyze.setIconSize(QSize(18, 18))
        command_input_row.addWidget(self.btn_analyze)
        self.btn_cancel_analysis.setObjectName("CommandCancelButton")
        self.btn_cancel_analysis.setFixedHeight(36)
        self.btn_cancel_analysis.setMinimumWidth(82)
        self.btn_cancel_analysis.hide()
        command_input_row.addWidget(self.btn_cancel_analysis)
        command_layout.addLayout(command_input_row)
        hero_layout.addWidget(command_bar)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 2, 0)
        status_row.addStretch(1)
        status_row.addWidget(self.status_label)
        content_layout.addLayout(status_row)
        content_layout.setStretchFactor(hero, 0)
        content_layout.setStretchFactor(splitter, 1)

        self.btn_analyze.clicked.connect(self.start_analysis)
        self.btn_cancel_analysis.clicked.connect(self.cancel_analysis)
        self.btn_cancel_analysis_inline.clicked.connect(self.cancel_analysis)
        self.btn_translate_all.clicked.connect(self.translate_all_cards)
        self.btn_overview.clicked.connect(self.open_overview)
        self.btn_review_queue.clicked.connect(self.open_review_queue)
        self.btn_history.clicked.connect(self.open_history)
        self.btn_move_selected.clicked.connect(self.move_selected_cards)
        self.btn_select_mode.toggled.connect(self.toggle_select_mode)
        self.btn_select_all.clicked.connect(self.select_all_cards)
        self.btn_clear_sel.clicked.connect(self.clear_selection)
        self.btn_translate_selected.clicked.connect(self.translate_selected_cards)
        self.btn_format_selected.clicked.connect(self.format_selected_cards)
        self.btn_library.clicked.connect(self.choose_library_folder)
        self.btn_review_plan.clicked.connect(self.export_review_plan)
        self.btn_agent.clicked.connect(self.open_agent_panel)
        self.btn_report.clicked.connect(self.open_report)
        self.btn_report_dir.clicked.connect(self.open_report_dir)
        self.btn_dedupe.clicked.connect(self.find_duplicates_current)
        self.btn_cleanup.clicked.connect(self.cleanup_empty_dirs_current)
        self.btn_change_target.clicked.connect(self.change_selected_target)
        self.btn_mark_review.clicked.connect(self.mark_selected_review)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_new_library_folder.clicked.connect(self.create_library_folder)
        self.btn_refresh_library.clicked.connect(self.refresh_library_now)
        self.btn_toggle_left.clicked.connect(self.toggle_left_sidebar)
        self.btn_toggle_right.clicked.connect(self.toggle_right_panel)
        self.btn_work_view.clicked.connect(lambda: self.set_active_view("work"))
        self.btn_library_view.clicked.connect(lambda: self.set_active_view("library"))
        self.filter_edit.textChanged.connect(lambda _text: self.populate_cards())
        self.path_edit.returnPressed.connect(self.start_analysis)
        self.path_tree.itemClicked.connect(self.open_sidebar_path)
        self.path_tree.itemDoubleClicked.connect(self.activate_sidebar_tree_item)
        self.path_tree.itemExpanded.connect(self.expand_sidebar_path)
        self.path_tree.itemCollapsed.connect(self.collapse_sidebar_path)
        self.path_tree.customContextMenuRequested.connect(self.open_library_tree_menu)
        self.card_wall.card_selected.connect(self.select_card)
        self.card_wall.card_action_requested.connect(self.handle_card_action)
        self.card_wall.rubber_selected.connect(self.on_rubber_selected)

        configured_root = self._configured_resource_root()
        if configured_root is not None and configured_root.exists():
            self.populate_path_browser(configured_root)

    def load_startup_library(self) -> None:
        library_root = self._configured_resource_root()
        if library_root is None or not library_root.exists():
            self.summary_label.setText("资源库未设置；待整理为空。")
            self.status_label.setText("先在设置里选择资源库路径，或在资源路径框输入待整理路径，也可以导入网页链接。")
            self._set_view_cards("work", [], None, None, True)
            return
        self.quick_browse_path(library_root, refresh_index=False)
        self.start_library_preload(library_root)

    def _auto_prune_runtime_data(self) -> None:
        self._start_runtime_maintenance(
            self.settings,
            dry_run=False,
            request={"kind": "auto_apply"},
        )

    def cleanup_runtime_data(self, *, settings_override: dict | None = None, ask_confirmation: bool = True) -> None:
        runtime_settings = dict(self.settings)
        if settings_override:
            runtime_settings.update(settings_override)
        self._start_runtime_maintenance(
            runtime_settings,
            dry_run=True,
            request={
                "kind": "manual_plan",
                "settings": runtime_settings,
                "ask_confirmation": bool(ask_confirmation),
            },
        )

    def _start_runtime_maintenance(self, runtime_settings: dict, *, dry_run: bool, request: dict) -> bool:
        if self.runtime_maintenance.busy:
            self._on_runtime_maintenance_duplicate()
            return False
        self._runtime_maintenance_request = dict(request)
        started = self.runtime_maintenance.start(runtime_settings, dry_run=dry_run)
        if not started:
            self._runtime_maintenance_request = None
            return False
        if request.get("kind") == "manual_plan":
            self.status_label.setText("正在后台检查工作台运行数据…")
        return True

    def _on_runtime_maintenance_duplicate(self) -> None:
        self.status_label.setText("工作台运行数据维护正在后台进行，请稍后再试。")

    def _on_runtime_maintenance_finished(self, result: dict) -> None:
        request = self._runtime_maintenance_request or {"kind": "unknown"}
        self._runtime_maintenance_request = None
        kind = str(request.get("kind") or "unknown")
        if self._runtime_maintenance_close_pending:
            self._runtime_maintenance_close_pending = False
            QTimer.singleShot(0, self.close)
            return
        if not result.get("ok"):
            error = str(result.get("error") or "未知错误")
            if kind == "auto_apply":
                self.status_label.setText(f"后台运行数据维护未完成：{error}")
            else:
                QMessageBox.warning(self, "工作台运行数据维护失败", error)
            return

        summary = summarize_runtime_maintenance(result)
        if kind == "manual_plan":
            if int(summary.get("action_candidates") or 0) <= 0:
                self.status_label.setText("工作台运行数据均在保留上限内，无需清理。")
                return
            if request.get("ask_confirmation", True):
                message = format_runtime_maintenance_plan(result) + "\n\n确认执行以上清理吗？"
                if QMessageBox.question(self, "清理工作台运行数据", message) != QMessageBox.Yes:
                    self.status_label.setText("已取消清理；没有改动任何运行数据。")
                    return
            self._start_runtime_maintenance(
                request.get("settings") or self.settings,
                dry_run=False,
                request={"kind": "manual_apply"},
            )
            return

        deleted_items = (
            int(summary.get("preview_deleted") or 0)
            + int(summary.get("report_deleted") or 0)
            + int(summary.get("staging_deleted") or 0)
            + int(summary.get("history_deleted") or 0)
        )
        vacuumed = int(summary.get("vacuumed") or 0)
        released = self._format_bytes(int(summary.get("deleted_bytes") or 0))
        if kind == "auto_apply" and deleted_items <= 0 and vacuumed <= 0:
            return
        prefix = "后台维护完成" if kind == "auto_apply" else "清理完成"
        self.status_label.setText(
            f"{prefix}：清理 {deleted_items} 项（约 {released}），整理 {vacuumed} 个数据库；活动与人工数据已保留。"
        )

    def _configured_resource_root(self) -> Path | None:
        text = str(self.settings.get("resource_root") or "").strip().strip('"')
        return Path(text) if text else None

    def _toolbar_icon(self, name: str) -> QIcon:
        return make_line_icon(name, self._toolbar_icon_color())

    def _toolbar_icon_color(self) -> str:
        custom = optional_color(str(self.settings.get("ui_icon_color") or ""))
        if custom:
            return custom
        return "#edf5ff" if str(self.settings.get("ui_theme") or "") == "fluent_dark" else "#17202a"

    def _sidebar_icon_color(self) -> str:
        custom = optional_color(str(self.settings.get("ui_icon_color") or ""))
        if custom:
            return custom
        theme = str(self.settings.get("ui_theme") or "")
        return "#3c3630" if theme in {"fluent_light", "claude_light", "warm_light"} else "#fffaf3"

    def _apply_theme_icons(self) -> None:
        if not hasattr(self, "btn_analyze"):
            return
        specs = [
            (self.btn_analyze, "play"),
            (self.btn_translate_all, "translate"),
            (self.btn_overview, "library"),
            (self.btn_review_queue, "report"),
            (self.btn_history, "archive"),
            (self.btn_dedupe, "dedupe"),
            (self.btn_cleanup, "cleanup"),
            (self.btn_toggle_right, "panel-right"),
        ]
        if hasattr(self, "btn_actions"):
            specs.append((self.btn_actions, "more"))
        left_name = "panel-left" if self.sidebar.isVisible() else "panel-right"
        specs.append((self.btn_toggle_left, left_name))
        for button, icon_name in specs:
            button.setIcon(self._toolbar_icon(icon_name))
        self.btn_settings.setIcon(make_line_icon("settings", self._sidebar_icon_color()))
        if hasattr(self, "btn_new_library_folder"):
            self.btn_new_library_folder.setIcon(make_line_icon("add", self._sidebar_icon_color()))
        if hasattr(self, "btn_refresh_library"):
            self.btn_refresh_library.setIcon(make_line_icon("refresh", self._sidebar_icon_color()))
        self._refresh_tree_icon_colors()

    def _refresh_tree_icon_colors(self) -> None:
        if not hasattr(self, "path_tree"):
            return
        color = self._sidebar_icon_color()
        for row in range(self.path_tree.topLevelItemCount()):
            item = self.path_tree.topLevelItem(row)
            item.setIcon(0, make_line_icon("library", color))
            self._refresh_child_tree_icons(item, color)

    def _refresh_child_tree_icons(self, item: QTreeWidgetItem, color: str) -> None:
        for row in range(item.childCount()):
            child = item.child(row)
            if not child.data(0, Qt.UserRole + 2):
                child.setIcon(0, make_line_icon("folder", color))
            self._refresh_child_tree_icons(child, color)

    def _apply_style(self) -> None:
        app_font = QFont("Microsoft YaHei UI", 10)
        QApplication.instance().setFont(app_font)
        branch_closed = _asset_path("tree_branch_closed.svg").as_posix()
        branch_open = _asset_path("tree_branch_open.svg").as_posix()
        theme = str(self.settings.get("ui_theme") or "claude_light")
        if theme.startswith("fluent") or theme in {"claude_light", "warm_light", "classic"}:
            self._fluent_backend = apply_qfluent_theme(self.settings)
            self.setStyleSheet(
                build_fluent_qss(
                    theme,
                    str(self.settings.get("ui_accent_color") or "#2563eb"),
                    branch_closed,
                    branch_open,
                    {
                        key: str(value or "")
                        for key, value in self.settings.items()
                        if key.startswith("ui_") and key.endswith("_color")
                    },
                )
            )
            self._apply_theme_icons()
            return
        self.setStyleSheet(
            """
            * { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }
            QMainWindow { background: #f5f6f3; }
            #Sidebar { background: #11161d; color: white; }
            #AppTitle { color: white; font-size: 28px; font-weight: 800; line-height: 1.2; }
            #MutedText { color: #d0d7de; font-size: 13px; line-height: 1.5; }
            #TinyText { color: #aab4bf; font-size: 11px; }
            #SummaryText { color: #617080; font-size: 12px; font-weight: 700; }
            #StatusBar {
                background: #ffffff; color: #617080; border: 1px solid #d7dee7;
                border-radius: 8px; padding: 6px 10px; font-size: 12px; font-weight: 600;
            }
            #SidebarSectionTitle {
                color: #94a3b8; font-size: 11px; font-weight: 800; margin-top: 8px;
            }
            #SettingsSectionTitle {
                color: #17202a; font-size: 14px; font-weight: 800; margin-top: 10px;
            }
            QPushButton {
                border: none; border-radius: 8px; padding: 9px 12px;
                background: #e4e7ea; color: #1f2933; font-weight: 600;
            }
            #Sidebar QPushButton {
                background: #2b3642; color: #f8fafc; text-align: left; padding-left: 16px;
            }
            #Sidebar QPushButton:hover { background: #3a4756; }
            #SidebarIconButton {
                background: #1c232d; color: #f8fafc; border-radius: 8px;
                padding: 0; text-align: center;
            }
            #SidebarIconButton:hover { background: #28313d; }
            #SidebarMiniButton {
                background: transparent; color: #f8fafc; border: 1px solid transparent;
                border-radius: 7px; padding: 0; text-align: center;
            }
            #SidebarMiniButton:hover { background: #28313d; border-color: #3a4756; }
            QPushButton:hover { background: #d8dde3; }
            QLineEdit {
                border: 1px solid #d6dbe1; border-radius: 8px; padding: 9px 12px;
                background: white; font-size: 12px;
            }
            QComboBox {
                border: 1px solid #d6dbe1; border-radius: 8px; padding: 8px 28px 8px 10px;
                background: white; color: #1f2933; font-size: 12px; min-width: 74px;
            }
            QComboBox:hover { border-color: #b8c1cc; }
            QComboBox::drop-down { border: none; width: 24px; }
            #PathTree {
                background: transparent; border: none; border-radius: 0;
                color: #d7dee8; outline: none; padding: 1px 0 2px 0;
            }
            #PathTree::item {
                min-height: 30px; padding: 5px 7px; border-radius: 7px;
            }
            #PathTree::item:hover { background: #1b222c; color: #f8fafc; }
            #PathTree::item:selected { background: #252d38; color: #ffffff; }
            #ViewSwitchButton {
                background: #eef1f4; color: #334155; border: 1px solid #d7dee7; border-radius: 8px;
                padding: 0 12px; font-size: 12px; font-weight: 800;
            }
            #ViewSwitchButton:checked { background: #17202a; color: #f8fafc; border-color: #17202a; }
            #ViewSwitchButton:hover { background: #dfe5eb; color: #17202a; }
            #ViewSwitchButton:checked:hover { background: #223042; color: #f8fafc; }
            #Hero, #Panel {
                background: white; border: 1px solid #e2e6ea; border-radius: 8px;
            }
            #CommandBar {
                background: #ffffff; border: 1px solid #d7dee7; border-radius: 8px;
            }
            #CommandIconButton {
                background: #eef1f4; color: #1f2933; border: 1px solid #d7dee7;
                border-radius: 8px; padding: 0;
            }
            #CommandIconButton:hover { background: #dfe5eb; border-color: #aebccc; }
            #CommandRunButton {
                background: #2563eb; color: #ffffff; border: 1px solid #2563eb;
                border-radius: 8px; padding: 0 14px; font-size: 12px; font-weight: 900;
            }
            #CommandRunButton:hover { background: #1d4ed8; border-color: #1d4ed8; }
            #CanvasPanel {
                background: #eef2f7; border: 1px solid #d7dee7; border-radius: 8px;
            }
            #ToolbarIconButton {
                background: #eef1f4; color: #1f2933; border: 1px solid #d7dee7; border-radius: 8px;
                padding: 0; font-size: 15px; font-weight: 800;
            }
            #ToolbarIconButton:hover { background: #dfe5eb; border-color: #aebccc; }
            #ToolbarIconButton::menu-indicator { image: none; width: 0; }
            #PageTitle { font-size: 20px; font-weight: 800; color: #17202a; }
            #SectionTitle { font-size: 16px; font-weight: 800; color: #17202a; }
            QLabel { color: #334155; font-size: 12px; }
            QScrollArea#CardWall { border: none; background: #eef2f7; }
            QScrollArea#CardWall > QWidget { background: #eef2f7; }
            #MasonrySurface { background: #eef2f7; }
            #EmptyWallText { color: #7b8794; font-size: 13px; }
            #ResourceCard {
                background: #ffffff; border: 1px solid #d7dee7; border-radius: 8px;
            }
            #ResourceCard:hover { border-color: #aebccc; background: #f4f8ff; }
            #ResourceCard[selected="true"] {
                border: 2px solid #2563eb; background: #eef5ff;
            }
            #CardSelectedBadge {
                background: #2563eb; color: #ffffff; border: 2px solid #ffffff;
                border-radius: 14px; font-size: 16px; font-weight: 900;
            }
            #CardPreview {
                background: #eef1f3; border: none; border-radius: 7px;
                color: #7b8794; font-size: 13px;
            }
            #CardPreview[empty="true"] {
                background: #f0f2f1; color: #8a949e;
            }
            #CardTitle { color: #17202a; font-size: 12px; font-weight: 700; }
            #TypeChip, #ConfidenceChip, #StatusChip {
                border-radius: 5px; padding: 2px 6px; font-size: 10px; font-weight: 700;
            }
            #TypeChip { background: #e6f4ec; color: #166534; }
            #ConfidenceChip { background: #fff3d8; color: #92400e; }
            #StatusChip { background: #e8eef8; color: #1d4ed8; }
            #StatusChip[warning="true"] { background: #fdebc0; color: #9a3412; }
            #CardTags { color: #52616f; font-size: 11px; }
            #CardTarget {
                color: #2f3b46; font-size: 11px; background: #f7f8f6;
                border-radius: 6px; padding: 6px;
            }
            #CardTargetInline {
                color: #475569; font-size: 10px; font-weight: 700;
                background: #f3f6f8; border-radius: 5px; padding: 2px 5px;
            }
            #CardHint { color: #8a949e; font-size: 11px; }
            #CardHoverOverlay {
                background: rgba(15, 23, 42, 130); border-radius: 7px;
            }
            #HoverIconButton {
                background: rgba(255, 255, 255, 225); color: #17202a;
                border-radius: 8px; padding: 0; font-size: 11px; font-weight: 800;
            }
            #HoverIconButton:hover { background: white; }
            #HoverTextButton {
                background: #f59e0b; color: #ffffff;
                border-radius: 8px; padding: 5px 9px; font-size: 11px; font-weight: 800;
            }
            #HoverTextButton:hover { background: #d97706; }
            #SettingsActionButton {
                background: #17202a; color: #f8fafc; border-radius: 8px;
                padding: 7px 12px; font-size: 12px; font-weight: 800;
            }
            #SettingsActionButton:hover { background: #253142; }
            #ThemeRoleRow, #ThemePreviewPanel {
                background: #ffffff; border: 1px solid #d7dee7; border-radius: 8px;
            }
            #ThemeGroupTitle, #ThemeRoleLabel { color: #17202a; font-weight: 800; }
            #ThemeRoleDescription { color: #64748b; font-size: 10px; }
            #ThemeResetButton {
                background: transparent; color: #64748b; border: 1px solid transparent; border-radius: 6px;
            }
            #ThemeResetButton:hover { background: #eef1f4; color: #17202a; }
            QTextEdit {
                border: 1px solid #e2e7ec; border-radius: 8px; padding: 12px;
                background: #fbfdff; color: #1f2937; font-size: 12px; line-height: 1.5;
            }
            #PreviewBox {
                border: 1px solid #e2e7ec; border-radius: 8px; background: #f8fafc;
                color: #64748b; font-size: 13px;
            }
            QMenu {
                background: #ffffff; border: 1px solid #d8dde3; padding: 6px;
            }
            QMenu::item { padding: 7px 28px 7px 12px; color: #1f2933; }
            QMenu::item:selected { background: #e8eef8; color: #1d4ed8; }
            QScrollBar:vertical {
                background: transparent; width: 8px; margin: 4px 2px 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1; border-radius: 4px; min-height: 42px;
            }
            QScrollBar::handle:vertical:hover { background: #94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; background: transparent; border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar:horizontal {
                background: transparent; height: 8px; margin: 2px 4px 2px 4px;
            }
            QScrollBar::handle:horizontal {
                background: #cbd5e1; border-radius: 4px; min-width: 42px;
            }
            QScrollBar::handle:horizontal:hover { background: #94a3b8; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0; background: transparent; border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
            """
            + f"""
            #PathTree::branch:closed:has-children {{
                image: url("{branch_closed}");
            }}
            #PathTree::branch:open:has-children {{
                image: url("{branch_open}");
            }}
            #PathTree::branch:has-children:closed {{
                image: url("{branch_closed}");
            }}
            #PathTree::branch:has-children:open {{
                image: url("{branch_open}");
            }}
            #PathTree::branch:!has-children {{
                image: none;
            }}
            """
        )
        self._apply_theme_icons()

    def toggle_left_sidebar(self) -> None:
        is_visible = self.sidebar.isVisible()
        self.sidebar.setVisible(not is_visible)
        self.btn_toggle_left.setIcon(self._toolbar_icon("panel-left" if not is_visible else "panel-right"))
        self.card_wall.schedule_relayout(0)

    def toggle_right_panel(self) -> None:
        index = self._selected_card_index()
        if index is not None:
            self.select_card(index)
        if self.detail_dialog.isVisible():
            self.detail_dialog.hide()
        else:
            self.detail_dialog.show()
            self.detail_dialog.raise_()
            self.detail_dialog.activateWindow()

    def show_detail_dialog(self, index: int) -> None:
        if not (0 <= index < len(self.cards)):
            return
        self.select_card(index)
        self.detail_dialog.show()
        self.detail_dialog.raise_()
        self.detail_dialog.activateWindow()

    def set_active_view(self, view: str, preferred_index: int | None = None) -> None:
        if view not in self.view_cards:
            return
        if self.active_view in self.view_selected:
            self.view_selected[self.active_view] = self.current_card_index
        self.active_view = view
        self.cards = self.view_cards[view]
        self.current_input_path = self.view_paths.get(view)
        self.current_card_index = preferred_index if preferred_index is not None else self.view_selected.get(view)
        self._sync_view_buttons()
        self.populate_cards(preferred_index=self.current_card_index)

    def _sync_view_buttons(self) -> None:
        if not hasattr(self, "btn_work_view"):
            return
        self.btn_work_view.setChecked(self.active_view == "work")
        self.btn_library_view.setChecked(self.active_view == "library")

    def _set_view_cards(
        self,
        view: str,
        cards: list[dict],
        path: Path | None,
        preferred_index: int | None = 0,
        activate: bool = True,
    ) -> None:
        cards = self._apply_card_metadata(cards)
        self.view_cards[view] = cards
        self.view_paths[view] = path
        self.view_selected[view] = preferred_index if cards else None
        if activate or self.active_view == view:
            self.active_view = view
            self.cards = cards
            self.current_input_path = path
            self.current_card_index = self.view_selected[view]
            self._sync_view_buttons()
            self.populate_cards(preferred_index=self.current_card_index)

    def _apply_card_metadata(self, cards: list[dict]) -> list[dict]:
        store = getattr(self, "card_metadata", None)
        if store is None:
            return cards
        for card in cards:
            try:
                store.apply_to_card(card)
            except Exception:
                card.setdefault("manual_tags", [])
                card.setdefault("manual_note", "")
        return cards

    def _input_paths_from_edit(self) -> list[Path]:
        parts, _urls = self._analysis_inputs_from_edit()
        return parts

    def _analysis_inputs_from_edit(self) -> tuple[list[Path], list[str]]:
        text = self.path_edit.text().strip()
        if not text:
            return [], []
        parts = [part.strip().strip('"') for part in re.split(r"[;\n]+", text) if part.strip().strip('"')]
        paths: list[Path] = []
        urls: list[str] = []
        seen_paths: set[str] = set()
        seen_urls: set[str] = set()
        for part in parts:
            if self._looks_like_web_input(part):
                try:
                    url = normalise_url(part)
                except ValueError:
                    url = ""
                key = url.casefold()
                if url and key not in seen_urls:
                    urls.append(url)
                    seen_urls.add(key)
                continue
            path = Path(part)
            key = str(path).lower()
            if key not in seen_paths:
                paths.append(path)
                seen_paths.add(key)
        return paths, urls

    @staticmethod
    def _looks_like_web_input(text: str) -> bool:
        value = str(text or "").strip()
        if re.match(r"^https?://", value, re.IGNORECASE):
            return True
        if re.match(r"^www\.[^\s/]+\.[a-z]{2,}(?:/|$)", value, re.IGNORECASE):
            return True
        # Also accept a plain domain while keeping drive letters and UNC paths
        # unambiguous on Windows.
        return bool(re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:[/:?#]|$)", value, re.IGNORECASE))

    def _set_input_paths(self, paths: list[Path]) -> None:
        self.input_paths = paths
        self.path_edit.setText(" ; ".join(str(path) for path in paths))
        self.view_paths["work"] = paths[0] if len(paths) == 1 else None

    @staticmethod
    def _resolved_for_path_compare(path: Path) -> Path:
        try:
            return Path(path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return Path(path).expanduser()

    def _path_key(self, path: Path | str) -> str:
        resolved = self._resolved_for_path_compare(Path(path))
        return os.path.normcase(os.path.normpath(str(resolved))).rstrip("\\/")

    def _remap_path_after_rename(self, path: Path | None, old_path: Path, new_path: Path) -> Path | None:
        if path is None:
            return None
        path = Path(path)
        old_path = Path(old_path)
        new_path = Path(new_path)
        path_key = self._path_key(path)
        old_key = self._path_key(old_path)
        if path_key == old_key:
            return new_path
        if path_key.startswith(old_key + os.sep):
            path_text = os.path.normpath(str(self._resolved_for_path_compare(path)))
            old_text = os.path.normpath(str(self._resolved_for_path_compare(old_path)))
            suffix = path_text[len(old_text) :].lstrip("\\/")
            parts = [part for part in re.split(r"[\\/]+", suffix) if part]
            return new_path.joinpath(*parts) if parts else new_path
        return path

    def _remap_path_list_after_rename(
        self, paths: list[Path], old_path: Path, new_path: Path
    ) -> tuple[list[Path], bool]:
        remapped: list[Path] = []
        seen: set[str] = set()
        changed = False
        for path in paths:
            mapped = self._remap_path_after_rename(path, old_path, new_path)
            if mapped is None:
                continue
            if self._path_key(path) != self._path_key(mapped):
                changed = True
            key = self._path_key(mapped)
            if key in seen:
                changed = True
                continue
            remapped.append(mapped)
            seen.add(key)
        return remapped, changed

    def _remap_cards_after_folder_rename(self, cards: list[dict], old_path: Path, new_path: Path) -> None:
        old_key = self._path_key(old_path)
        for card in cards:
            source = str(card.get("source_path") or "")
            if source:
                source_path = Path(source)
                mapped = self._remap_path_after_rename(source_path, old_path, new_path)
                if mapped is not None and self._path_key(source_path) != self._path_key(mapped):
                    exact_source = self._path_key(source_path) == old_key
                    card["source_path"] = str(mapped)
                    if exact_source:
                        if not card.get("name") or str(card.get("name")) == old_path.name:
                            card["name"] = mapped.name
                        if not card.get("display_name") or str(card.get("display_name")) == old_path.name:
                            card["display_name"] = mapped.name

    def _after_folder_renamed(self, old_path: Path, new_path: Path) -> None:
        old_path = Path(old_path)
        new_path = Path(new_path)
        for cards in self.view_cards.values():
            self._remap_cards_after_folder_rename(cards, old_path, new_path)
        if self.active_view in self.view_cards:
            self.cards = self.view_cards[self.active_view]

        edited_paths = self._input_paths_from_edit()
        paths_to_remap = edited_paths or list(self.input_paths)
        if paths_to_remap:
            remapped, changed = self._remap_path_list_after_rename(paths_to_remap, old_path, new_path)
            if changed:
                if edited_paths:
                    self._set_input_paths(remapped)
                else:
                    self.input_paths = remapped

        for view, view_path in list(self.view_paths.items()):
            self.view_paths[view] = self._remap_path_after_rename(view_path, old_path, new_path)
        self.current_input_path = self._remap_path_after_rename(self.current_input_path, old_path, new_path)

        indexed_parents: set[str] = set()
        for parent in (old_path.parent, new_path.parent):
            if parent.exists() and parent.is_dir():
                key = self._path_key(parent)
                if key not in indexed_parents:
                    indexed_parents.add(key)
                    self.resource_index.index_children(parent)

        root = self.library_root_path or self._configured_resource_root()
        root = self._remap_path_after_rename(root, old_path, new_path)
        if root is not None and root.exists() and root.is_dir():
            self.library_root_path = root
            self._refresh_library_tree_preserving_state(
                preferred_selected=new_path,
                ensure_expanded=[new_path.parent],
            )

        library_path = self.view_paths.get("library")
        if library_path is not None and library_path.exists():
            max_cards = int(self.settings.get("quick_browse_max_cards") or 120)
            if library_path.is_dir():
                self.resource_index.index_children(library_path)
                cached_cards = self.resource_index.load_child_cards(library_path, max_cards=max_cards)
                cards = self._prepare_quick_cards(
                    cached_cards or placeholder_cards_for_path(library_path, max_cards=max_cards)
                )
            else:
                cards = self._prepare_quick_cards(placeholder_cards_for_path(library_path, max_cards=max_cards))
            self._set_view_cards(
                "library",
                cards,
                library_path,
                self.view_selected.get("library"),
                self.active_view == "library",
            )
            if self.active_view == "library":
                self.summary_label.setText(f"资源库已同步：{library_path.name or library_path}；显示 {len(cards)} 张卡片。")

    def _append_input_path(self, path: Path) -> None:
        paths = self._input_paths_from_edit()
        configured_root = self._configured_resource_root()
        if len(paths) == 1 and not self.view_cards["work"]:
            try:
                if configured_root is not None and paths[0].resolve() == configured_root.resolve():
                    paths = []
            except OSError:
                pass
        if str(path).lower() not in {str(item).lower() for item in paths}:
            paths.append(path)
        self._set_input_paths(paths)
        self.quick_preview_work_paths(paths)

    def quick_preview_work_paths(self, paths: list[Path]) -> None:
        max_cards = int(self.settings.get("quick_browse_max_cards") or 120)
        cards: list[dict] = []
        per_source = max(12, max_cards // max(1, len(paths)))
        for path in paths:
            for card in placeholder_cards_for_path(path, max_cards=per_source):
                card = dict(card)
                card["batch_source_path"] = str(path)
                cards.append(card)
                if len(cards) >= max_cards:
                    break
            if len(cards) >= max_cards:
                break
        self.summary_label.setText(f"待整理来源：{len(paths)} 个；已快速显示 {len(cards)} 张占位卡。")
        self.status_label.setText("这是轻量预览，未深扫文件。点击顶部分析后会进入审阅队列。")
        self._set_view_cards("work", self._prepare_quick_cards(cards), paths[0] if len(paths) == 1 else None, 0, True)

    def auto_analyze_input_paths(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            return
        paths = self._input_paths_from_edit()
        if not paths or any(not path.exists() for path in paths):
            return
        library_root = self._configured_resource_root()
        if len(paths) == 1:
            try:
                if library_root is not None and library_root.exists() and paths[0].resolve() == library_root.resolve():
                    return
            except OSError:
                pass
        self.start_analysis()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择资源文件夹", self.path_edit.text())
        if folder:
            self._append_input_path(Path(folder))

    def choose_archive(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择压缩包",
            self.path_edit.text(),
            "压缩包 (*.zip *.rar *.7z *.tar *.gz *.tgz *.iso);;所有文件 (*.*)",
        )
        if file_path:
            self._append_input_path(Path(file_path))
            self.status_label.setText("已选择压缩包。点击顶部分析按钮读取压缩包目录。")

    def add_web_resource(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            "添加网页资源",
            "粘贴网页链接",
            text=QApplication.clipboard().text().strip() if QApplication.clipboard() else "",
        )
        if not ok or not str(url).strip():
            return
        progress = QProgressDialog("正在读取网页并生成卡片预览……", None, 0, 0, self)
        progress.setWindowTitle("添加网页资源")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        try:
            card = create_web_resource_card(str(url), self.preview_cache_dir / "web")
        except Exception as exc:  # noqa: BLE001
            progress.close()
            QMessageBox.warning(self, "网页资源添加失败", str(exc))
            return
        progress.close()

        cards = list(self.view_cards.get("work") or [])
        cards.append(card)
        self.path_edit.clear()
        self._set_view_cards("work", cards, None, len(cards) - 1, True)
        self.status_label.setText("网页卡片已生成。选择目标分类后，点击卡片上的入库按钮即可保存到资源库。")
        self.summary_label.setText(f"待整理：{len(cards)} 张卡片；其中包含网页资源。")

    def choose_library_folder(self) -> None:
        configured_root = self._configured_resource_root()
        start_path = str(configured_root if configured_root and configured_root.exists() else Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择要浏览的已存资源路径", start_path)
        if not folder:
            return
        selected = Path(folder)
        if configured_root is not None and selected == configured_root:
            answer = QMessageBox.question(
                self,
                "确认浏览根目录",
                "你选择的是资源库根目录。当前会先快速显示子路径，不会立刻做完整分析。\n\n需要详细判断时，再点击顶部分析按钮。",
            )
            if answer != QMessageBox.Yes:
                return
        self.populate_path_browser(selected)
        self.quick_browse_path(selected)

    def start_analysis(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.status_label.setText("分析正在后台进行；如需停止，请点“取消分析”。")
            return
        if self.deep_thread is not None and self.deep_thread.isRunning():
            self.status_label.setText("当前来源正在后台重新分析；如需停止，请点“取消分析”。")
            return
        input_paths, web_urls = self._analysis_inputs_from_edit()
        missing_paths = [path for path in input_paths if not path.exists()]
        if not input_paths and not web_urls:
            QMessageBox.information(self, "还没有待整理来源", "请先在资源路径框输入待整理文件夹/压缩包路径，或粘贴网页链接生成卡片。")
            return
        if missing_paths:
            message = "\n".join(str(path) for path in (missing_paths or input_paths))
            QMessageBox.warning(self, "路径不存在", f"找不到这些路径：\n{message}")
            return

        input_path = input_paths[0] if input_paths else None
        self.input_paths = list(input_paths)
        self.active_view = "work"
        self.view_cards["work"] = []
        self.view_selected["work"] = None
        self.view_paths["work"] = input_path if len(input_paths) == 1 and not web_urls else None
        self.cards = self.view_cards["work"]
        self.current_input_path = self.view_paths["work"]
        self.current_card_index = None
        resource_root_depth = self._selected_resource_root_depth(input_path) if input_path is not None else None
        if len(input_paths) > 1 and not isinstance(self.depth_combo.currentData(), int):
            resource_root_depth = None
        self._sync_view_buttons()
        self.analysis_cancel_requested = False
        self.btn_analyze.setIcon(self._toolbar_icon("play"))
        self.status_label.setText("正在后台分析；窗口仍可正常移动和切换。")
        source_count = len(input_paths) + len(web_urls)
        self.summary_label.setText(f"正在分析 {source_count} 个来源，请稍等。")
        self.card_wall.set_cards([], self.preview_cache_dir, self._short_target)
        self.detail_text.setText("")
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("分析中……")
        self._set_analysis_active(True, "正在分析中，请稍后", 4)

        self.thread = QThread()
        self.worker = AnalyzeWorker(
            input_paths,
            resource_root_depth,
            self.staging_root,
            False,
            self._configured_resource_root(),
            web_urls,
            self.preview_cache_dir / "web",
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_analysis_progress)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, "thread", None))
        self.thread.finished.connect(lambda: setattr(self, "worker", None))
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _set_analysis_active(self, active: bool, text: str = "", value: int = 0) -> None:
        active = bool(active)
        self.analysis_state_box.setVisible(active)
        self.analysis_progress.setVisible(active)
        self.btn_cancel_analysis.setVisible(active)
        self.btn_cancel_analysis_inline.setVisible(active)
        self.btn_analyze.setEnabled(not active)
        self.path_edit.setEnabled(not active)
        self.analysis_status_text.setText(text or "正在分析中，请稍后")
        self.analysis_status_text.set_shimmer_active(active)
        if active:
            self.analysis_progress.setValue(max(0, min(100, int(value))))

    def on_analysis_progress(self, text: str, value: int) -> None:
        self.analysis_status_text.setText(text or "正在分析中，请稍后")
        self.analysis_progress.setValue(max(0, min(100, int(value))))
        self.status_label.setText(text)

    def cancel_analysis(self) -> None:
        cancelled = False
        if self.thread is not None and self.thread.isRunning() and self.worker is not None:
            self.worker.cancel()
            cancelled = True
        if self.deep_thread is not None and self.deep_thread.isRunning() and self.deep_worker is not None:
            self.deep_worker.cancel()
            cancelled = True
        if not cancelled:
            self.status_label.setText("当前没有正在运行的分析。")
            return
        self.analysis_cancel_requested = True
        self.btn_cancel_analysis.setEnabled(False)
        self.btn_cancel_analysis_inline.setEnabled(False)
        self.analysis_status_text.setText("正在安全停止分析……")
        self.status_label.setText("已请求取消；正在结束当前文件读取。")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        """Invalidate queued tree work before Qt starts destroying widgets."""
        if self.runtime_maintenance.busy:
            self._runtime_maintenance_close_pending = True
            self.status_label.setText("正在安全完成后台运行数据维护，完成后将自动退出…")
            event.ignore()
            return
        self._library_tree_closing = True
        self._library_tree_generation += 1
        self.library_refresh_timer.stop()
        self.library_poll_timer.stop()
        self.library_watcher.blockSignals(True)
        super().closeEvent(event)

    def _iter_library_tree_items(self):
        pending = [self.path_tree.topLevelItem(row) for row in range(self.path_tree.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            yield item
            pending[0:0] = [item.child(row) for row in range(item.childCount())]

    def _find_library_tree_item(self, path: Path | str) -> QTreeWidgetItem | None:
        wanted = self._path_key(path)
        for item in self._iter_library_tree_items():
            item_path = item.data(0, Qt.UserRole)
            if item_path and self._path_key(str(item_path)) == wanted:
                return item
        return None

    def _expanded_library_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self._iter_library_tree_items():
            path_text = item.data(0, Qt.UserRole)
            if path_text and item.isExpanded():
                paths.append(Path(str(path_text)))
        return paths

    def _current_library_tree_path(self) -> Path | None:
        item = self.path_tree.currentItem()
        path_text = item.data(0, Qt.UserRole) if item is not None else None
        return Path(str(path_text)) if path_text else None

    def _refresh_library_tree_preserving_state(
        self,
        preferred_selected: Path | None = None,
        ensure_expanded: list[Path] | None = None,
    ) -> None:
        root = self.library_root_path or self._configured_resource_root()
        if root is None:
            return
        expanded = self._expanded_library_paths()
        for path in ensure_expanded or []:
            if self._path_key(path) not in {self._path_key(item) for item in expanded}:
                expanded.append(Path(path))
        selected = preferred_selected or self._current_library_tree_path()
        self.populate_path_browser(root, restore_expanded=expanded, restore_selected=selected)

    def _sync_library_watch_paths(self) -> None:
        if not hasattr(self, "path_tree"):
            return
        desired: list[Path] = []
        for candidate in [
            self.library_root_path,
            self.view_paths.get("library"),
            *self._expanded_library_paths(),
        ]:
            if candidate is None:
                continue
            candidate = Path(candidate)
            key = self._path_key(candidate)
            if key in self._library_tree_available_keys and key not in {self._path_key(path) for path in desired}:
                desired.append(candidate)
            if len(desired) >= 64:
                break
        wanted = {self._path_key(path): str(path) for path in desired}
        current = {self._path_key(path): path for path in self.library_watcher.directories()}
        remove = [path for key, path in current.items() if key not in wanted]
        add = [path for key, path in wanted.items() if key not in current]
        if remove:
            self.library_watcher.removePaths(remove)
        if add:
            try:
                self.library_watcher.addPaths(add)
            except OSError:
                pass

    def _poll_library_signatures(self) -> None:
        if self._library_tree_closing or self._library_signature_task is not None or not hasattr(self, "path_tree"):
            return
        paths: list[Path] = []
        seen: set[str] = set()
        for candidate in [
            self.library_root_path,
            self.view_paths.get("library"),
            *self._expanded_library_paths(),
        ]:
            if candidate is None:
                continue
            candidate = Path(candidate)
            key = self._path_key(candidate)
            if key in seen or key not in self._library_tree_available_keys:
                continue
            seen.add(key)
            paths.append(candidate)
            if len(paths) >= 64:
                break
        if not paths:
            return
        task = _LibrarySignatureTask(paths)
        self._library_signature_task = task
        task.signals.finished.connect(self._on_library_signatures_ready)
        _retain_async_task(_ACTIVE_LIBRARY_SIGNATURE_TASKS, task)
        try:
            _LIBRARY_SIGNATURE_POOL.start(task)
        except Exception:  # noqa: BLE001 - polling will retry on its next interval
            _release_async_task(_ACTIVE_LIBRARY_SIGNATURE_TASKS, task)
            self._library_signature_task = None

    def _on_library_signatures_ready(self, results: dict) -> None:
        self._library_signature_task = None
        if self._library_tree_closing:
            return
        for path_text, signature in results.items():
            key = self._path_key(path_text)
            fingerprint = (signature.status, signature.entries)
            previous = self._library_path_signatures.get(key)
            self._library_path_signatures[key] = fingerprint
            if previous is not None and previous != fingerprint:
                self._queue_library_path_refresh(path_text)

    def _queue_library_path_refresh(self, path_text: str) -> None:
        if self._library_tree_closing or not path_text:
            return
        self._pending_library_refresh_paths.add(str(path_text))
        self.library_refresh_timer.start()

    def _flush_library_path_refreshes(self) -> None:
        changed = [Path(path) for path in self._pending_library_refresh_paths]
        self._pending_library_refresh_paths.clear()
        if not changed:
            return
        self._refresh_library_tree_preserving_state()
        current = self.view_paths.get("library")
        if current is not None and current.exists() and current.is_dir():
            current_key = self._path_key(current)
            if any(self._path_key(path) == current_key for path in changed):
                self.start_library_preload(current, prioritize=True, depth_override=0)
        self.status_label.setText("检测到资源库内容变化，正在后台同步目录和卡片。")

    def _selected_library_parent(self) -> Path | None:
        selected = self._current_library_tree_path()
        if selected is not None:
            return selected
        current = self.view_paths.get("library")
        if current is not None:
            return Path(current)
        root = self.library_root_path or self._configured_resource_root()
        return Path(root) if root is not None else None

    def create_library_folder(self) -> None:
        parent = self._selected_library_parent()
        root = self.library_root_path or self._configured_resource_root()
        if parent is None or root is None:
            QMessageBox.information(self, "尚未设置资源库", "请先在设置中选择资源库根路径。")
            return
        name, ok = QInputDialog.getText(
            self,
            "新建资源库文件夹",
            f"将在这里新建：\n{parent}\n\n文件夹名称",
        )
        if not ok:
            return
        result = safe_mkdir(parent, name, [root])
        if not result.ok or result.path is None:
            message = result.error_message or "无法创建文件夹。"
            QMessageBox.warning(self, "新建失败", message)
            return
        self._queue_library_path_refresh(str(parent))
        self._refresh_library_tree_preserving_state(
            preferred_selected=result.path,
            ensure_expanded=[parent],
        )
        self.quick_browse_path(result.path, refresh_index=True)
        self.status_label.setText(f"已新建文件夹：{result.path}")

    def open_library_tree_menu(self, pos: QPoint) -> None:
        item = self.path_tree.itemAt(pos)
        if item is not None:
            self.path_tree.setCurrentItem(item)
        menu = QMenu(self.path_tree)
        create_action = menu.addAction(make_line_icon("add"), "新建文件夹")
        refresh_action = menu.addAction(make_line_icon("refresh"), "刷新当前路径")
        chosen = menu.exec(self.path_tree.viewport().mapToGlobal(pos))
        if chosen is create_action:
            self.create_library_folder()
        elif chosen is refresh_action:
            self.refresh_library_now()

    def refresh_library_now(self) -> None:
        path = self._selected_library_parent()
        if path is None:
            QMessageBox.information(self, "尚未设置资源库", "请先在设置中选择资源库根路径。")
            return
        self._library_path_signatures.pop(self._path_key(path), None)
        self._refresh_library_tree_preserving_state()
        self.start_library_preload(path, prioritize=True, depth_override=0)
        self.status_label.setText(f"正在后台刷新：{path}")

    def populate_path_browser(
        self,
        root: Path,
        *,
        restore_expanded: list[Path] | None = None,
        restore_selected: Path | None = None,
    ) -> None:
        root = root.expanduser()
        self._library_tree_generation += 1
        self.library_root_path = root
        self._library_tree_available_keys.clear()
        self._library_tree_restore_expanded = {
            self._path_key(path): Path(path) for path in (restore_expanded or [])
        }
        self._library_tree_restore_selected = Path(restore_selected) if restore_selected is not None else None
        self.path_tree.blockSignals(True)
        self.path_tree.clear()

        root_label = self._sidebar_path_label(root, is_root=True)
        root_item = QTreeWidgetItem([root_label])
        root_item.setIcon(0, make_line_icon("library", self._sidebar_icon_color()))
        root_item.setData(0, Qt.UserRole, str(root))
        root_item.setData(0, TREE_ROLE_LABEL, root_label)
        root_item.setData(0, TREE_ROLE_HAS_CHILDREN, True)
        root_item.setData(0, TREE_ROLE_GENERATION, self._library_tree_generation)
        root_item.setToolTip(0, str(root))
        self.path_tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self.path_tree.setCurrentItem(root_item)
        self._request_tree_children(root_item, root, offset=0, reset=True)
        self.path_tree.blockSignals(False)
        self._sync_library_watch_paths()

    def _sidebar_path_label(self, path: Path, is_root: bool = False) -> str:
        name = path.name or str(path)
        if is_root:
            return f"当前：{name}"
        return name

    def _add_tree_status_item(
        self,
        item: QTreeWidgetItem,
        text: str,
        kind: str,
        *,
        offset: int = 0,
        tooltip: str = "",
    ) -> QTreeWidgetItem:
        status_item = QTreeWidgetItem([text])
        status_item.setData(0, TREE_ROLE_PLACEHOLDER, True)
        status_item.setData(0, TREE_ROLE_KIND, kind)
        status_item.setData(0, TREE_ROLE_OFFSET, max(0, int(offset)))
        status_item.setData(0, TREE_ROLE_GENERATION, self._library_tree_generation)
        if tooltip:
            status_item.setToolTip(0, tooltip)
        if kind == "more":
            status_item.setIcon(0, make_line_icon("more", self._sidebar_icon_color()))
        elif kind == "retry":
            status_item.setIcon(0, make_line_icon("refresh", self._sidebar_icon_color()))
        item.addChild(status_item)
        return status_item

    def _remove_tree_status_children(self, item: QTreeWidgetItem) -> None:
        for row in range(item.childCount() - 1, -1, -1):
            child = item.child(row)
            if child.data(0, TREE_ROLE_PLACEHOLDER):
                item.takeChild(row)

    def _add_tree_placeholder(self, item: QTreeWidgetItem) -> None:
        self._add_tree_status_item(item, "…", "collapsed")

    def _request_tree_children(
        self,
        item: QTreeWidgetItem,
        path: Path,
        *,
        offset: int = 0,
        reset: bool,
    ) -> None:
        if self._library_tree_closing or item.data(0, TREE_ROLE_REQUEST):
            return
        if reset:
            item.takeChildren()
            item.setData(0, TREE_ROLE_LOADED, False)
        else:
            self._remove_tree_status_children(item)
        self._library_tree_request_seq += 1
        request_id = self._library_tree_request_seq
        generation = self._library_tree_generation
        item.setData(0, TREE_ROLE_REQUEST, request_id)
        item.setData(0, TREE_ROLE_REQUEST_OFFSET, max(0, int(offset)))
        item.setData(0, TREE_ROLE_GENERATION, generation)
        self._add_tree_status_item(item, "正在读取…", "loading", offset=offset)
        task = _LibraryTreeReadTask(path, offset, generation, request_id)
        self._library_tree_tasks[request_id] = task
        task.signals.finished.connect(self._on_library_tree_page_ready)
        _retain_async_task(_ACTIVE_LIBRARY_TREE_TASKS, task)
        try:
            _LIBRARY_TREE_POOL.start(task)
        except Exception as exc:  # noqa: BLE001 - turn pool failure into a retry row
            _release_async_task(_ACTIVE_LIBRARY_TREE_TASKS, task)
            self._on_library_tree_page_ready(
                {
                    "status": "error",
                    "error": f"读取失败：{' '.join(str(exc).split())[:72]}",
                    "entries": [],
                    "total": 0,
                    "offset": offset,
                    "next_offset": offset,
                    "remaining": 0,
                    "path": str(path),
                    "generation": generation,
                    "request_id": request_id,
                }
            )

    def _restore_needs_next_tree_page(self, parent: Path, item: QTreeWidgetItem) -> bool:
        parent_key = self._path_key(parent)
        prefix = parent_key + os.sep
        wanted = list(self._library_tree_restore_expanded.values())
        if self._library_tree_restore_selected is not None:
            wanted.append(self._library_tree_restore_selected)
        loaded = {
            self._path_key(str(item.child(row).data(0, Qt.UserRole)))
            for row in range(item.childCount())
            if item.child(row).data(0, Qt.UserRole)
        }
        for path in wanted:
            key = self._path_key(path)
            if not key.startswith(prefix):
                continue
            suffix = key[len(prefix) :]
            first = suffix.split(os.sep, 1)[0]
            if first and prefix + first not in loaded:
                return True
        return False

    def _restore_library_tree_item(self, item: QTreeWidgetItem) -> None:
        path_text = item.data(0, Qt.UserRole)
        if not path_text:
            return
        key = self._path_key(str(path_text))
        selected = self._library_tree_restore_selected
        if selected is not None and key == self._path_key(selected):
            self.path_tree.setCurrentItem(item)
        if key in self._library_tree_restore_expanded and not item.isExpanded():
            item.setExpanded(True)

    def _on_library_tree_page_ready(self, result: dict) -> None:
        request_id = int(result.get("request_id") or 0)
        self._library_tree_tasks.pop(request_id, None)
        if self._library_tree_closing:
            return
        if int(result.get("generation") or -1) != self._library_tree_generation:
            return
        path = Path(str(result.get("path") or ""))
        item = self._find_library_tree_item(path)
        if item is None or int(item.data(0, TREE_ROLE_REQUEST) or 0) != request_id:
            return
        if int(item.data(0, TREE_ROLE_GENERATION) or -1) != self._library_tree_generation:
            return
        requested_offset = max(0, int(item.data(0, TREE_ROLE_REQUEST_OFFSET) or 0))
        result_offset = max(0, int(result.get("offset") or 0))
        item.setData(0, TREE_ROLE_REQUEST, None)
        item.setData(0, TREE_ROLE_REQUEST_OFFSET, None)
        self._remove_tree_status_children(item)

        if result_offset != requested_offset:
            item.setData(0, TREE_ROLE_LOADED, bool(requested_offset))
            self._add_tree_status_item(
                item,
                "读取结果已过期（点击重试）",
                "retry",
                offset=requested_offset,
                tooltip=str(path),
            )
            self.status_label.setText(f"资源树“{path.name or path}”返回了错误的分页位置，已安全丢弃。")
            return

        if result.get("status") != "ok":
            error = str(result.get("error") or "读取失败")
            if requested_offset == 0:
                self._library_tree_available_keys.discard(self._path_key(path))
                item.setData(0, TREE_ROLE_LOADED, False)
            else:
                # A later page failure must not erase the pages that are already
                # visible. Keep the parent watchable and retry the exact offset.
                item.setData(0, TREE_ROLE_LOADED, True)
            has_loaded_children = any(
                bool(item.child(row).data(0, Qt.UserRole)) for row in range(item.childCount())
            )
            if has_loaded_children:
                item.setData(0, TREE_ROLE_HAS_CHILDREN, True)
            self._add_tree_status_item(
                item,
                f"{error}（点击重试）",
                "retry",
                offset=requested_offset,
                tooltip=str(path),
            )
            self.status_label.setText(f"资源树未能读取“{path.name or path}”：{error}。")
            self._sync_library_watch_paths()
            return

        self._library_tree_available_keys.add(self._path_key(path))
        existing = {
            self._path_key(str(item.child(row).data(0, Qt.UserRole)))
            for row in range(item.childCount())
            if item.child(row).data(0, Qt.UserRole)
        }
        new_items: list[QTreeWidgetItem] = []
        for entry in result.get("entries") or []:
            child_path = Path(str(entry.get("path") or ""))
            child_key = self._path_key(child_path)
            self._library_tree_available_keys.add(child_key)
            if child_key in existing:
                continue
            child_item = QTreeWidgetItem([str(entry.get("name") or child_path.name)])
            child_item.setIcon(0, make_line_icon("folder", self._sidebar_icon_color()))
            child_item.setData(0, Qt.UserRole, str(child_path))
            child_item.setData(0, TREE_ROLE_LABEL, str(entry.get("name") or child_path.name))
            child_item.setData(0, TREE_ROLE_HAS_CHILDREN, bool(entry.get("has_children")))
            child_item.setData(0, TREE_ROLE_LOADED, False)
            child_item.setData(0, TREE_ROLE_GENERATION, self._library_tree_generation)
            tooltip = str(child_path)
            if entry.get("probe_error"):
                tooltip += f"\n子目录状态：{entry['probe_error']}"
            child_item.setToolTip(0, tooltip)
            item.addChild(child_item)
            existing.add(child_key)
            new_items.append(child_item)
            if entry.get("has_children"):
                self._add_tree_placeholder(child_item)

        item.setData(0, TREE_ROLE_LOADED, True)
        has_loaded_children = any(
            bool(item.child(row).data(0, Qt.UserRole)) for row in range(item.childCount())
        )
        item.setData(
            0,
            TREE_ROLE_HAS_CHILDREN,
            bool(int(result.get("total") or 0)) or has_loaded_children,
        )
        for child_item in new_items:
            self._restore_library_tree_item(child_item)

        remaining = max(0, int(result.get("remaining") or 0))
        next_offset = max(0, int(result.get("next_offset") or 0))
        if remaining and next_offset <= result_offset:
            self._add_tree_status_item(
                item,
                "分页位置异常（点击重试）",
                "retry",
                offset=result_offset,
                tooltip=str(path),
            )
            self.status_label.setText(f"资源树“{path.name or path}”的分页没有前进，已停止自动加载。")
        elif remaining and self._restore_needs_next_tree_page(path, item):
            self._request_tree_children(item, path, offset=next_offset, reset=False)
        elif remaining:
            self._add_tree_status_item(
                item,
                f"继续加载（剩余 {remaining}）",
                "more",
                offset=next_offset,
                tooltip="点击或双击加载下一页",
            )
        elif int(result.get("total") or 0) == 0 and int(result.get("offset") or 0) == 0:
            self._add_tree_status_item(item, "（没有子文件夹）", "empty")
        self._restore_library_tree_item(item)
        self._sync_library_watch_paths()

    def expand_sidebar_path(self, item: QTreeWidgetItem) -> None:
        path_text = item.data(0, Qt.UserRole)
        if not path_text:
            return
        if not item.data(0, TREE_ROLE_LOADED) and not item.data(0, TREE_ROLE_REQUEST):
            self._request_tree_children(item, Path(str(path_text)), offset=0, reset=True)
        self._sync_library_watch_paths()

    def collapse_sidebar_path(self, item: QTreeWidgetItem) -> None:
        self._sync_library_watch_paths()

    def open_sidebar_path(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        item_kind = item.data(0, TREE_ROLE_KIND)
        if item_kind in {"more", "retry"}:
            parent = item.parent()
            path_text = parent.data(0, Qt.UserRole) if parent is not None else None
            if path_text and not parent.data(0, TREE_ROLE_REQUEST):
                offset = int(item.data(0, TREE_ROLE_OFFSET) or 0)
                self._request_tree_children(
                    parent,
                    Path(str(path_text)),
                    offset=offset,
                    reset=item_kind == "retry" and offset == 0,
                )
            return
        if item.data(0, TREE_ROLE_PLACEHOLDER):
            return
        path_text = item.data(0, Qt.UserRole)
        if not path_text:
            return
        path = Path(path_text)
        if not path.exists():
            QMessageBox.warning(self, "路径不存在", f"找不到这个路径：\n{path}")
            return
        self.quick_browse_path(path, refresh_index=True)

    def activate_sidebar_tree_item(self, item: QTreeWidgetItem, column: int = 0) -> None:
        if item.data(0, TREE_ROLE_KIND) in {"more", "retry"}:
            self.open_sidebar_path(item, column)

    def quick_browse_path(self, path: Path, refresh_index: bool = False) -> None:
        max_cards = int(self.settings.get("quick_browse_max_cards") or 120)
        cached_cards = self.resource_index.load_child_cards(path, max_cards=max_cards) if path.is_dir() else []
        cards = self._prepare_quick_cards(cached_cards or placeholder_cards_for_path(path, max_cards=max_cards))
        source = "缓存" if cached_cards else "快速"
        self.summary_label.setText(f"{source}浏览：{path.name or path}；显示 {len(self.cards)} 张卡片。")
        self.status_label.setText("快速浏览中：点击顶部分析按钮可生成详细分类判断。")
        # Library browsing keeps the latest work/report context intact.
        self._set_view_cards("library", cards, path, 0 if cards else None, True)
        self.summary_label.setText(f"资源库浏览：{path.name or path}；显示 {len(cards)} 张卡片。")
        self._sync_library_watch_paths()
        if path.is_dir() and (
            refresh_index
            or not cached_cards
            or not any(card.get("preview_source") for card in cached_cards)
        ):
            self.start_library_preload(path, prioritize=True, depth_override=0)

    def refresh_quick_index(self, path: Path) -> None:
        if path.exists() and path.is_dir():
            self.start_library_preload(path, prioritize=True, depth_override=0)

    def start_library_preload(
        self,
        root: Path,
        prioritize: bool = False,
        depth_override: int | None = None,
    ) -> None:
        if not root.exists() or not root.is_dir():
            return
        depth = max(0, int(depth_override)) if depth_override is not None else int(self.settings.get("library_preload_depth") or 2)
        if self.library_index_thread is not None and self.library_index_thread.isRunning():
            self.pending_library_preload_root = root
            self.pending_library_preload_depth = depth
            if prioritize and self.library_index_worker is not None:
                self.library_index_worker.cancel()
                self.status_label.setText("正在切换到当前路径的资源库索引；卡片会先显示，缩略图随后补齐。")
            return
        self.library_index_thread = QThread()
        self.library_index_worker = LibraryIndexWorker(index_db_path(DATA_ROOT), root, max_depth=depth)
        self.library_index_worker.moveToThread(self.library_index_thread)
        self.library_index_thread.started.connect(self.library_index_worker.run)
        self.library_index_worker.parent_indexed.connect(self.on_library_parent_indexed)
        self.library_index_worker.finished.connect(self.on_library_preload_finished)
        self.library_index_worker.finished.connect(self.library_index_thread.quit)
        self.library_index_worker.finished.connect(self.library_index_worker.deleteLater)
        self.library_index_thread.finished.connect(lambda: setattr(self, "library_index_thread", None))
        self.library_index_thread.finished.connect(lambda: setattr(self, "library_index_worker", None))
        self.library_index_thread.finished.connect(self.library_index_thread.deleteLater)
        self.status_label.setText("资源库正在后台建立浅层索引；你可以继续浏览或整理。")
        self.library_index_thread.start()

    def on_library_parent_indexed(self, parent_text: str, rows: int, _depth: int) -> None:
        parent = Path(parent_text)
        current = self.view_paths.get("library")
        if current is None:
            return
        try:
            if current.resolve() != parent.resolve():
                return
        except OSError:
            return
        max_cards = int(self.settings.get("quick_browse_max_cards") or 120)
        cards = self._prepare_quick_cards(self.resource_index.load_child_cards(parent, max_cards=max_cards))
        if cards:
            self._set_view_cards("library", cards, parent, self.view_selected.get("library"), self.active_view == "library")
            self.summary_label.setText(f"资源库缓存已就绪：{parent.name or parent}；显示 {len(cards)} 张卡片。")

    def on_library_preload_finished(self, result: dict) -> None:
        if not result.get("ok"):
            self.status_label.setText(f"资源库后台索引失败：{result.get('error')}")
            return
        if result.get("cancelled"):
            self.status_label.setText("资源库后台索引已取消。")
            self._start_pending_library_preload()
            return
        self.status_label.setText(
            f"资源库浅层索引完成：同步 {result.get('parents', 0)} 个路径，缓存 {result.get('rows', 0)} 个子项。"
        )
        self._start_pending_library_preload()

    def _start_pending_library_preload(self) -> None:
        pending = self.pending_library_preload_root
        pending_depth = self.pending_library_preload_depth
        self.pending_library_preload_root = None
        self.pending_library_preload_depth = None
        if pending is None or not pending.exists() or not pending.is_dir():
            return
        QTimer.singleShot(
            60,
            lambda root=pending, depth=pending_depth: self.start_library_preload(
                root,
                prioritize=False,
                depth_override=depth,
            ),
        )

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.settings = dialog.values()
        key_changed, key_text = dialog.api_key_input()
        if key_changed:
            save_deepseek_api_key(self.settings, key_text)
        save_settings(DATA_ROOT, self.settings)
        self._apply_style()
        configured_root = self._configured_resource_root()
        if configured_root is not None and configured_root.exists():
            self.populate_path_browser(configured_root)
            self.quick_browse_path(configured_root, refresh_index=False)
            self.start_library_preload(configured_root)
        else:
            self.library_root_path = None
            self.path_tree.clear()
            self._set_view_cards("library", [], None, None, self.active_view == "library")
        self.status_label.setText("设置已保存。")

    def _current_maintenance_root(self) -> Path | None:
        if self.active_view == "library":
            root = self.current_input_path or self.view_paths.get("library")
        else:
            input_paths = self._input_paths_from_edit()
            if len(input_paths) > 1:
                QMessageBox.information(self, "一次处理一个路径", "查重和清理空目录一次只处理一个根路径。请保留一个待整理路径后再试。")
                return None
            root = input_paths[0] if input_paths else (self.current_input_path or self.view_paths.get("work"))

        if root is None:
            QMessageBox.information(self, "没有当前路径", "请先选择或输入一个待整理路径。")
            return None
        root = Path(root)
        if root.is_file():
            root = root.parent
        if not root.exists() or not root.is_dir():
            QMessageBox.warning(self, "路径不可用", f"找不到可维护的文件夹：\n{root}")
            return None
        return root

    def find_duplicates_current(self) -> None:
        root = self._current_maintenance_root()
        if root is None:
            return
        answer = QMessageBox.question(
            self,
            "查重方式",
            "是否用内容哈希确认重复？\n\n选择“是”更准确，但大目录会更慢；选择“否”会按文件名和大小快速列出疑似重复。",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if answer == QMessageBox.Cancel:
            return
        self._start_maintenance("dedupe", root, use_hash=answer == QMessageBox.Yes)

    def cleanup_empty_dirs_current(self) -> None:
        root = self._current_maintenance_root()
        if root is None:
            return
        self._start_maintenance("empty_dirs_preview", root)

    def _start_maintenance(self, action: str, root: Path, use_hash: bool = False) -> None:
        if self.maintenance_thread is not None and self.maintenance_thread.isRunning():
            QMessageBox.information(self, "维护任务进行中", "请等当前查重或清理任务完成。")
            return

        self.btn_dedupe.setEnabled(False)
        self.btn_cleanup.setEnabled(False)
        action_text = "查重" if action == "dedupe" else "扫描空目录" if action == "empty_dirs_preview" else "清理空目录"
        self.status_label.setText(f"正在{action_text}：{root}")

        self.maintenance_thread = QThread()
        self.maintenance_worker = MaintenanceWorker(action, root, use_hash=use_hash)
        self.maintenance_worker.moveToThread(self.maintenance_thread)
        self.maintenance_thread.started.connect(self.maintenance_worker.run)
        self.maintenance_worker.finished.connect(self.on_maintenance_finished)
        self.maintenance_worker.finished.connect(self.maintenance_thread.quit)
        self.maintenance_worker.finished.connect(self.maintenance_worker.deleteLater)
        self.maintenance_thread.finished.connect(lambda: setattr(self, "maintenance_thread", None))
        self.maintenance_thread.finished.connect(lambda: setattr(self, "maintenance_worker", None))
        self.maintenance_thread.finished.connect(self.maintenance_thread.deleteLater)
        self.maintenance_thread.start()

    def on_maintenance_finished(self, result: dict) -> None:
        self.btn_dedupe.setEnabled(True)
        self.btn_cleanup.setEnabled(True)
        if not result.get("ok"):
            self.status_label.setText("维护任务失败。")
            QMessageBox.critical(self, "维护任务失败", result.get("error", "未知错误"))
            return

        action = result.get("action")
        root = Path(str(result.get("root") or ""))
        elapsed = result.get("elapsed")
        if action == "dedupe":
            groups = result.get("groups") or []
            text = self._format_duplicate_groups(root, groups, bool(result.get("use_hash")), elapsed)
            self._show_text_dialog("查重结果", text)
            self.status_label.setText(f"查重完成：发现 {len(groups)} 组重复/疑似重复。")
            return

        if action == "empty_dirs_preview":
            empties = result.get("empty_dirs") or []
            if not empties:
                self.status_label.setText("空目录扫描完成：没有发现空目录。")
                QMessageBox.information(self, "空目录清理", "没有发现空目录。")
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("空目录清理")
            box.setText(f"发现 {len(empties)} 个空目录。")
            box.setInformativeText("是否删除这些目录？只会删除真正为空的目录；包含文件的目录会被跳过。")
            box.setDetailedText("\n".join(empties[:800]))
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() == QMessageBox.Yes:
                self._start_maintenance("empty_dirs_apply", root)
            else:
                self.status_label.setText(f"空目录扫描完成：发现 {len(empties)} 个，未删除。")
            return

        if action == "empty_dirs_apply":
            removed = result.get("removed") or []
            text = self._format_path_report(root, removed, f"已删除 {len(removed)} 个空目录", elapsed)
            self._show_text_dialog("空目录清理结果", text)
            self.status_label.setText(f"空目录清理完成：删除 {len(removed)} 个。")

    def _format_duplicate_groups(self, root: Path, groups: list[dict], use_hash: bool, elapsed: float | None) -> str:
        mode = "内容哈希确认" if use_hash else "文件名 + 大小疑似匹配"
        lines = [
            f"路径：{root}",
            f"方式：{mode}",
            f"耗时：{elapsed} 秒" if elapsed is not None else "",
            f"发现：{len(groups)} 组",
            "",
        ]
        if not groups:
            lines.append("没有发现重复或疑似重复文件。")
            return "\n".join(line for line in lines if line != "")

        for index, group in enumerate(groups[:120], 1):
            lines.append(f"{index}. {group.get('key')}  |  {self._format_bytes(int(group.get('size', 0)))}  |  {group.get('count')} 个")
            for path in (group.get("paths") or [])[:30]:
                lines.append(f"   {path}")
            if len(group.get("paths") or []) > 30:
                lines.append("   ...")
            lines.append("")
        if len(groups) > 120:
            lines.append(f"其余 {len(groups) - 120} 组未展开。")
        return "\n".join(lines)

    def _format_path_report(self, root: Path, paths: list[str], title: str, elapsed: float | None) -> str:
        lines = [
            title,
            f"路径：{root}",
            f"耗时：{elapsed} 秒" if elapsed is not None else "",
            "",
        ]
        if not paths:
            lines.append("没有目录被删除。")
        else:
            lines.extend(paths[:1000])
            if len(paths) > 1000:
                lines.append(f"... 其余 {len(paths) - 1000} 项未展开。")
        return "\n".join(line for line in lines if line != "")

    def _show_text_dialog(self, title: str, text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    @staticmethod
    def _format_bytes(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    def _prepare_quick_cards(self, cards: list[dict]) -> list[dict]:
        return [self._classify_library_quick_card(dict(card)) for card in cards]

    def _classify_library_quick_card(self, card: dict) -> dict:
        source = card.get("source_path")
        if not source:
            return card
        source_path = Path(str(source))
        parts = self._resource_library_parts(str(source_path))
        if not parts:
            return card

        media_type = str(card.get("media_type") or "").lower()
        content_type = {
            "video": "video",
            "model": "model",
            "zbrush": "zbrush",
            "engine": "ue",
        }.get(media_type)
        top = parts[0].lower()
        resource_type = content_type or "unknown"
        if resource_type == "unknown":
            if top.startswith("j "):
                resource_type = "tutorial"
            elif top.startswith("m "):
                resource_type = "model"
            elif top.startswith("u "):
                resource_type = "ue"
            elif top.startswith("c "):
                resource_type = "material"
            elif top.startswith("a "):
                resource_type = "alpha"
            elif top.startswith("b "):
                resource_type = "brush"
            elif top.startswith("z zb"):
                resource_type = "zbrush"
            elif top.startswith("z "):
                resource_type = "photo"

        if resource_type == "unknown":
            return card
        card["suggested_type"] = resource_type
        card["confidence"] = "high"
        card["needs_human_review"] = False
        card["content_tags"] = ["已入库", TYPE_LABELS.get(resource_type, resource_type)]
        card["target_path_hints"] = [str(source_path.parent)]
        if content_type:
            card["reasons"] = ["快速浏览卡片：优先按实际文件媒体类型显示，不再由上级目录名称覆盖。"]
        else:
            card["reasons"] = ["快速浏览卡片：来源位于已整理资源库，按所在分类路径显示类型；点击详细分析可重新判断。"]
        return card

    def _resource_library_parts(self, path_text: str) -> list[str]:
        raw_parts = [part for part in re.split(r"[\\/]+", path_text) if part]
        if not raw_parts:
            return []
        section_index = next(
            (
                index
                for index, part in enumerate(raw_parts)
                if part in LIBRARY_SECTION_NAMES
                or part.lower().startswith(("a ", "b ", "c ", "j ", "m ", "u ", "z "))
            ),
            None,
        )
        if section_index is None:
            return []
        return raw_parts[section_index:]

    def _selected_resource_root_depth(self, input_path: Path) -> int | None:
        selected = self.depth_combo.currentData()
        if isinstance(selected, int):
            return selected
        return None

    def on_analysis_finished(self, result: dict) -> None:
        self._set_analysis_active(False)
        self.btn_cancel_analysis.setEnabled(True)
        self.btn_cancel_analysis_inline.setEnabled(True)
        self.btn_analyze.setIcon(self._toolbar_icon("play"))
        self.btn_analyze.setToolTip("详细分析当前路径")
        if not result.get("ok"):
            if self.analysis_cancel_requested:
                self.status_label.setText("分析已取消。")
                self.summary_label.setText("分析已取消；没有改动源文件。")
                return
            self.status_label.setText("分析失败。")
            QMessageBox.critical(self, "分析失败", result.get("error", "未知错误"))
            return

        self._set_view_cards("work", result["cards"], self.view_paths.get("work"), 0 if result["cards"] else None, True)
        self.current_report = Path(result["paths"]["markdown"])
        self.current_report_dir = self.current_report.parent
        queued_reviews = self._enqueue_review_cards(result["cards"])
        scan = result["scan"]
        extraction = result.get("extraction") or {}
        extraction_text = ""
        if extraction.get("output_dir"):
            extraction_text = "；已先解压到临时工作区"
        depth_text = f"；按 {scan['resource_root_depth']} 层建卡" if scan.get("resource_root_depth") else ""
        top_level_count = int(scan.get("top_level_directory_count", 0) or 0)
        top_level_card_count = int(scan.get("top_level_card_count", 0) or 0)
        top_level_text = (
            f"首层资源文件夹 {top_level_count} 个、卡片覆盖 {top_level_card_count} 个；"
            if scan.get("top_level_card_invariant_applied") and top_level_count
            else ""
        )
        self.summary_label.setText(
            f"{top_level_text}发现 {scan.get('total_files', 0)} 个文件、{scan.get('total_dirs', 0)} 个文件夹；"
            f"生成 {len(self.cards)} 张卡片；网页资源 {scan.get('web_resource_count', 0)} 个{depth_text}{extraction_text}。"
        )
        missing_top_level = list(scan.get("missing_top_level_directories") or [])
        if missing_top_level and not scan.get("stopped_early"):
            missing_text = "\n".join(f"- {name}" for name in missing_top_level)
            self.status_label.setText("⚠ 首层资源卡片校验未通过；请查看缺失目录。")
            QMessageBox.warning(
                self,
                "资源卡片数量校验失败",
                f"这些首层文件夹没有对应卡片：\n{missing_text}\n\n本次结果已保留，但不会把少卡当作正常完成。",
            )
        elif scan.get("stopped_early"):
            if self.analysis_cancel_requested or "用户取消" in str(scan.get("stop_reason") or ""):
                self.status_label.setText("分析已取消；已完成的卡片仍可查看。")
            else:
                self.status_label.setText(f"⚠ 分析未完成：{scan.get('stop_reason')}")
                QMessageBox.warning(
                    self,
                    "分析未完成，可能漏掉资源",
                    f"{scan.get('stop_reason')}\n\n"
                    "为避免漏读，可缩小一次分析范围后重试。当前已生成的卡片仍可使用。",
                )
        else:
            review_required = sum(1 for card in result["cards"] if card.get("needs_human_review"))
            self.status_label.setText(
                analysis_completion_status(len(result["cards"]), review_required, queued_reviews)
            )
        self.populate_cards()

    def populate_cards(self, preferred_index: int | None = None) -> None:
        query = self.filter_edit.text().strip().lower()
        items: list[tuple[int, dict]] = []
        for index, card in enumerate(self.cards):
            if query and not self._card_matches_query(card, query):
                continue
            items.append((index, card))

        self.card_wall.set_cards(items, self.preview_cache_dir, self._short_target)
        if not items:
            self.current_card_index = None
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("暂无预览图")
            self.detail_text.setText("没有匹配的卡片。")
            return

        visible_indices = {index for index, _card in items}
        next_index = preferred_index if preferred_index in visible_indices else self.current_card_index
        if next_index not in visible_indices:
            next_index = items[0][0]
        self.select_card(next_index)

    def select_card(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self.cards)):
            return
        mods = QApplication.keyboardModifiers()
        if self.select_mode:
            if (mods & Qt.ShiftModifier) and self.current_card_index is not None:
                lo, hi = sorted((self.current_card_index, index))
                self.selected_indices |= set(range(lo, hi + 1))
            elif index in self.selected_indices:
                self.selected_indices.discard(index)
            else:
                self.selected_indices.add(index)
        elif mods & Qt.ControlModifier:
            if index in self.selected_indices:
                self.selected_indices.discard(index)
            else:
                self.selected_indices.add(index)
        elif (mods & Qt.ShiftModifier) and self.current_card_index is not None:
            lo, hi = sorted((self.current_card_index, index))
            self.selected_indices |= set(range(lo, hi + 1))
        else:
            self.selected_indices = {index}
        self.current_card_index = index
        self.view_selected[self.active_view] = index
        self.card_wall.apply_selection(self.selected_indices)
        self._update_batch_button()
        self.show_card(self.cards[index])

    def _update_batch_button(self) -> None:
        n = len([i for i in self.selected_indices if 0 <= i < len(self.cards)])
        if hasattr(self, "btn_move_selected"):
            self.btn_move_selected.setText(f"移动选中 ({n})" if n else "移动选中")
            self.btn_move_selected.setEnabled(n > 0)
        if hasattr(self, "btn_translate_selected"):
            self.btn_translate_selected.setText(f"翻译选中 ({n})" if n else "翻译选中")
            self.btn_translate_selected.setEnabled(n > 0)
        if hasattr(self, "btn_format_selected"):
            self.btn_format_selected.setText(f"整理选中 ({n})" if n else "整理选中")
            self.btn_format_selected.setEnabled(n > 0)

    def toggle_select_mode(self, on: bool) -> None:
        self.select_mode = bool(on)
        self.card_wall.set_select_mode(self.select_mode)
        if hasattr(self, "btn_select_mode"):
            self.btn_select_mode.setText("完成" if self.select_mode else "多选")
        for sbtn in getattr(self, "_select_action_buttons", []):
            sbtn.setVisible(self.select_mode)
        if not self.select_mode:
            self.selected_indices = set()
            self.card_wall.apply_selection(self.selected_indices)
        self._update_batch_button()
        self.status_label.setText(
            "多选模式：单击勾选、拖动框选、Shift 连选；顶部可统一翻译/移动。" if self.select_mode
            else "已退出多选模式。"
        )

    def select_all_cards(self) -> None:
        self.selected_indices = set(range(len(self.cards)))
        self.card_wall.apply_selection(self.selected_indices)
        self._update_batch_button()

    def clear_selection(self) -> None:
        self.selected_indices = set()
        self.card_wall.apply_selection(self.selected_indices)
        self._update_batch_button()

    def on_rubber_selected(self, indices) -> None:
        self.selected_indices |= {i for i in indices if 0 <= i < len(self.cards)}
        self.card_wall.apply_selection(self.selected_indices)
        self._update_batch_button()

    def _formal_source_roots(self) -> list[Path]:
        return self._mounted_drive_roots()

    def _mounted_drive_roots(self) -> list[Path]:
        if sys.platform.startswith("win"):
            roots = [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
            return roots or [Path("C:\\")]
        return [Path("/")]

    def _move_context(self) -> dict:
        z_root = self._configured_resource_root() or (DATA_ROOT / "library")
        return {
            "formal": True,
            "source_roots": self._formal_source_roots(),
            "destination_root": z_root,
            "z_root": z_root,
            "mode_label": "入库移动",
            "all_source_roots": True,
        }

    def _plan_card_move(self, card: dict, source: Path, target_path: str | None = None) -> dict:
        move_card = dict(card)
        move_card["source_path"] = str(source)
        if target_path:
            move_card["user_target_path"] = target_path
        ctx = self._move_context()
        return plan_move(
            move_card,
            ctx["source_roots"],
            ctx["destination_root"],
            ctx["z_root"],
            formal=bool(ctx["formal"]),
        )

    def _execute_card_move(self, card: dict, source: Path, target_path: str | None, move_log: MoveLog) -> dict:
        move_card = dict(card)
        move_card["source_path"] = str(source)
        if target_path:
            move_card["user_target_path"] = target_path
        ctx = self._move_context()
        if ctx["formal"]:
            return execute_formal_move(move_card, ctx["source_roots"], ctx["z_root"], move_log=move_log)
        return execute_test_move(
            move_card,
            ctx["source_roots"][0],
            ctx["destination_root"],
            ctx["z_root"],
            move_log=move_log,
        )

    def _effective_target_path(self, card: dict) -> str:
        for key in ("user_target_path", "ai_target_path", "library_target_path"):
            value = str(card.get(key) or "").strip()
            if value:
                return self._normalise_target_path(value)
        hints = card.get("target_path_hints") or []
        for hint in hints:
            value = str(hint or "").strip()
            if value:
                return self._normalise_target_path(value)
        return ""

    def _remove_moved_cards_from_work_view(self, indices: set[int]) -> None:
        if self.active_view != "work" or not indices:
            self.populate_cards(preferred_index=self.current_card_index)
            return
        old_cards = list(self.view_cards.get("work") or self.cards)
        next_index = min(indices) if indices else None
        self.view_cards["work"] = [card for idx, card in enumerate(old_cards) if idx not in indices]
        self.cards = self.view_cards["work"]
        self.selected_indices = set()
        if self.cards:
            self.current_card_index = min(next_index or 0, len(self.cards) - 1)
        else:
            self.current_card_index = None
        self.view_selected["work"] = self.current_card_index
        self.populate_cards(preferred_index=self.current_card_index)

    def _confirm_move_plans(self, plans: list[dict]) -> bool:
        if not plans:
            return False
        bad = [plan for plan in plans if not plan.get("ok")]
        if bad:
            QMessageBox.warning(self, "无法移动", str(bad[0].get("error") or "移动预演失败。"))
            return False

        total_files = sum(int(plan.get("file_count") or 0) for plan in plans)
        total_bytes = sum(int(plan.get("byte_count") or 0) for plan in plans)
        lines = [
            f"移动项目：{len(plans)} 项　文件：{total_files} 个　容量：{self._format_bytes(total_bytes)}",
            "",
        ]
        for number, plan in enumerate(plans, 1):
            lines.extend(
                [
                    f"{number}. {plan.get('source') or '（未知来源）'}",
                    f"   → {plan.get('destination') or '（未知目标）'}",
                    f"   {int(plan.get('file_count') or 0)} 个文件 / {self._format_bytes(int(plan.get('byte_count') or 0))}",
                ]
            )
        preview = "\n".join(lines)
        formal = any(bool(plan.get("formal")) for plan in plans)
        if formal:
            answer = QMessageBox.question(
                self,
                "正式移动计划预览",
                preview + "\n\n这会把来源实际移动到资源库。是否进入二次确认？",
            )
            if answer != QMessageBox.Yes:
                self.status_label.setText("已取消正式移动；没有移动任何文件。")
                return False
            token, accepted = QInputDialog.getText(
                self,
                "正式移动二次确认",
                "请核对上面的来源与目标。确认无误后输入 MOVE；关闭或输入其他内容都不会移动：",
            )
            if not accepted or token.strip() != "MOVE":
                self.status_label.setText("已取消正式移动；没有移动任何文件。")
                if accepted and token.strip():
                    QMessageBox.information(self, "未执行移动", "确认文字不正确；必须完整输入 MOVE。没有移动任何文件。")
                return False
            return True

        answer = QMessageBox.question(
            self,
            "测试移动计划预览",
            preview + "\n\n这是测试模式。确认按以上计划移动？",
        )
        if answer != QMessageBox.Yes:
            self.status_label.setText("已取消测试移动；没有移动任何文件。")
            return False
        return True

    def _cleanup_empty_source_chain(self, source: Path) -> list[str]:
        if not bool(self.settings.get("cleanup_empty_source_parents_after_move", False)):
            return []
        ctx = self._move_context()
        try:
            source_parent = Path(source).resolve().parent
        except OSError:
            source_parent = Path(source).parent
        matching_roots = []
        for root in ctx["source_roots"]:
            try:
                root_resolved = Path(root).resolve()
                source_parent.relative_to(root_resolved)
                matching_roots.append(root_resolved)
            except (OSError, ValueError):
                continue
        if not matching_roots:
            return []
        stop_root = max(matching_roots, key=lambda p: len(p.parts))
        removed: list[str] = []
        current = source_parent
        while current != stop_root and current.exists() and current.is_dir():
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
            except OSError:
                break
            removed.append(str(current))
            current = current.parent
        return removed

    def _overview_html(self) -> str:
        cards = list(self.cards or [])
        total = len(cards)
        by_type = Counter(str(card.get("suggested_type") or "unknown") for card in cards)
        by_confidence = Counter(str(card.get("confidence") or "unknown") for card in cards)
        tags = Counter()
        for card in cards:
            tags.update(str(tag) for tag in (card.get("content_tags") or []))
            tags.update(str(tag) for tag in (card.get("manual_tags") or []))
        review_count = sum(1 for card in cards if card.get("needs_human_review"))
        recovered_count = sum(1 for card in cards if card.get("recovered_card"))
        split_count = sum(1 for card in cards if card.get("is_split_card"))
        moved_count = sum(1 for card in cards if card.get("test_move_destination") or card.get("formal_move_destination"))
        total_bytes = sum(int(card.get("total_bytes") or 0) for card in cards)
        latest_report = self._latest_report_snapshot()
        move_ctx = self._move_context()

        def chips(counter: Counter, labels: dict | None = None, limit: int = 10) -> str:
            if not counter:
                return "<span class='muted'>暂无</span>"
            out = []
            for key, value in counter.most_common(limit):
                label = labels.get(key, key) if labels else key
                out.append(f"<span class='chip'>{escape(str(label))}: {value}</span>")
            return " ".join(out)

        report_html = "<span class='muted'>暂无报告</span>"
        if latest_report:
            report_html = (
                f"<b>{escape(latest_report['name'])}</b><br>"
                f"路径：{escape(str(latest_report.get('input_path') or ''))}<br>"
                f"卡片：{latest_report.get('cards', 0)}，文件：{latest_report.get('files', 0)}，"
                f"容量：{escape(self._format_bytes(int(latest_report.get('bytes') or 0)))}"
                + (f"<br><span class='warn'>中断：{escape(str(latest_report.get('stop_reason') or ''))}</span>" if latest_report.get("stopped_early") else "")
            )

        return f"""
        <style>
            body {{ font-family: "Microsoft YaHei UI", sans-serif; color: #17202a; font-size: 12px; line-height: 1.6; }}
            h2 {{ margin: 0 0 10px 0; font-size: 20px; }}
            h3 {{ margin: 18px 0 8px 0; font-size: 13px; }}
            .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
            .metric {{ background: #f3f6f8; border-radius: 8px; padding: 10px; }}
            .num {{ font-size: 22px; font-weight: 800; color: #0f172a; }}
            .muted {{ color: #64748b; }}
            .warn {{ color: #b45309; font-weight: 700; }}
            .chip {{ display: inline-block; background: #edf2f7; border-radius: 6px; padding: 4px 7px; margin: 0 6px 6px 0; }}
        </style>
        <h2>概览看板</h2>
        <div class='grid'>
            <div class='metric'><div class='num'>{total}</div><div class='muted'>当前卡片</div></div>
            <div class='metric'><div class='num'>{review_count}</div><div class='muted'>待确认</div></div>
            <div class='metric'><div class='num'>{moved_count}</div><div class='muted'>已移动</div></div>
            <div class='metric'><div class='num'>{escape(self._format_bytes(total_bytes))}</div><div class='muted'>资源容量</div></div>
        </div>
        <h3>类型分布</h3>
        {chips(by_type, TYPE_LABELS)}
        <h3>置信度</h3>
        {chips(by_confidence, CONFIDENCE_LABELS)}
        <h3>标签热度</h3>
        {chips(tags, limit=14)}
        <h3>边界状态</h3>
        <span class='chip'>拆分卡: {split_count}</span>
        <span class='chip'>兜底恢复: {recovered_count}</span>
        <h3>移动模式</h3>
        <span class='chip'>{escape(str(move_ctx['mode_label']))}</span>
        <span class='chip'>来源根: {len(move_ctx['source_roots'])}</span>
        <h3>最新报告</h3>
        {report_html}
        """

    def _latest_report_snapshot(self) -> dict | None:
        report_dir = DATA_ROOT / "reports"
        reports = sorted(report_dir.glob("resource_scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in reports[:5]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scan = data.get("scan") or {}
            cards = data.get("cards") or []
            return {
                "name": path.name,
                "input_path": scan.get("input_path"),
                "cards": len(cards),
                "files": scan.get("total_files") or 0,
                "bytes": scan.get("total_bytes") or 0,
                "stopped_early": bool(scan.get("stopped_early")),
                "stop_reason": scan.get("stop_reason") or "",
            }
        return None

    def _format_bytes(self, value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{value} B"

    def open_overview(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("概览看板")
        dialog.setMinimumSize(720, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        overview = QTextEdit()
        overview.setReadOnly(True)
        overview.setHtml(self._overview_html())
        layout.addWidget(overview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def open_review_queue(self) -> None:
        if not getattr(self, "review_queue", None):
            QMessageBox.information(self, "审阅队列不可用", "队列未初始化。")
            return
        dialog = ReviewQueueDialog(
            self.review_queue,
            mover_callback=self.queue_execute_move,
            relative_formatter=self._relative_target,
            preview_cache_dir=self.preview_cache_dir,
            parent=self,
        )
        dialog.exec()
        self.populate_cards(preferred_index=self.current_card_index)

    def queue_execute_move(self, item: dict) -> dict:
        card = dict(item.get("card") or {})
        card["source_path"] = item.get("source_path") or card.get("source_path")
        if item.get("target_path"):
            card["user_target_path"] = item["target_path"]
        src = str(card.get("source_path") or "")
        if not src or not Path(src).exists():
            return {"ok": False, "error": "来源不存在或已移动。"}
        card["card_id"] = item.get("card_id") or card.get("card_id")
        plan = self._plan_card_move(card, Path(src), card.get("user_target_path"))
        if not self._confirm_move_plans([plan]):
            return {"ok": False, "cancelled": True, "error": "用户取消移动；没有移动文件。"}
        move_log = MoveLog(default_move_log_path(DATA_ROOT))
        result = self._execute_card_move(card, Path(src), card.get("user_target_path"), move_log)
        if result.get("ok"):
            self._cleanup_empty_source_chain(Path(src))
        if getattr(self, "review_queue", None):
            try:
                self.review_queue.set_status(
                    item["card_id"],
                    "moved" if result.get("ok") else "move_failed",
                    note=None if result.get("ok") else str(result.get("error") or ""),
                )
            except Exception:
                pass
        return result

    def open_history(self) -> None:
        move_log = MoveLog(default_move_log_path(DATA_ROOT))
        rename_log = RenameLog(default_rename_log_path(DATA_ROOT))
        dialog = HistoryDialog(
            move_log, rename_log, relative_formatter=self._relative_target, parent=self
        )
        dialog.exec()
        self.populate_cards(preferred_index=self.current_card_index)

    def format_card_cover_project(self, index: int) -> None:
        source = self._card_source_path(index)
        if source is None or not Path(str(source)).is_dir():
            QMessageBox.information(self, "无法整理", "这张卡片没有可整理的文件夹来源。")
            return
        plan = formatter.plan_cover_project(Path(source))
        if not plan.get("ok"):
            QMessageBox.warning(self, "整理失败", str(plan.get("error") or ""))
            return
        if plan.get("already_organized") or not plan.get("move_items"):
            QMessageBox.information(self, "无需整理", "该资源已经是“封面 + 工程”结构。")
            return
        cover = plan.get("cover") or "（无封面图，将全部收进工程）"
        msg = (
            f"将把封面留在外层、其余 {len(plan['move_items'])} 项收进“工程”子文件夹。\n\n"
            f"封面：{cover}\n来源：\n{source}\n\n确认整理？（可在该文件夹的整理记录里撤销）"
        )
        if QMessageBox.question(self, "整理为封面+工程", msg) != QMessageBox.Yes:
            return
        result = formatter.apply_cover_project(Path(source))
        if not result.get("ok"):
            QMessageBox.warning(self, "整理失败", str(result.get("error") or ""))
            return
        self.status_label.setText(
            f"已整理：封面 {result.get('cover') or '无'}，收纳 {result.get('moved', 0)} 项到“工程”。"
        )

    def format_selected_cards(self) -> None:
        indices = sorted(i for i in self.selected_indices if 0 <= i < len(self.cards))
        candidates: list[tuple[int, Path, dict]] = []
        skipped = 0
        failed_plans: list[str] = []
        for index in indices:
            source = self._card_source_path(index)
            if source is None or not source.is_dir():
                skipped += 1
                continue
            plan = formatter.plan_cover_project(source)
            if not plan.get("ok"):
                failed_plans.append(f"{source}: {plan.get('error') or '无法生成整理计划'}")
                continue
            if plan.get("already_organized") or not plan.get("move_items"):
                skipped += 1
                continue
            candidates.append((index, source, plan))

        if not candidates:
            message = "选中的卡片里没有需要整理的文件夹资源。"
            if failed_plans:
                message += f"\n\n第一条错误：\n{failed_plans[0]}"
            QMessageBox.information(self, "无需批量整理", message)
            return

        total_items = sum(len(plan.get("move_items") or []) for _index, _source, plan in candidates)
        sample = "\n".join(str(source) for _index, source, _plan in candidates[:8])
        if len(candidates) > 8:
            sample += f"\n... 其余 {len(candidates) - 8} 个"
        message = (
            f"将整理 {len(candidates)} 个资源，把封面留在外层，其余共 {total_items} 项收进“工程”子文件夹。\n"
            f"已跳过 {skipped} 个无需整理或没有文件夹来源的卡片。\n\n"
            f"{sample}\n\n确认执行？（每个资源会写入整理记录，可单独撤销）"
        )
        if QMessageBox.question(self, "批量整理为封面+工程", message) != QMessageBox.Yes:
            return

        progress = QProgressDialog("正在批量整理……", "取消", 0, len(candidates), self)
        progress.setWindowTitle("批量整理")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        ok = 0
        failed = 0
        first_error = ""
        moved_total = 0
        for pos, (_index, source, _plan) in enumerate(candidates):
            if progress.wasCanceled():
                break
            progress.setValue(pos)
            progress.setLabelText(f"整理 {pos + 1}/{len(candidates)}：{source.name}")
            QApplication.processEvents()
            result = formatter.apply_cover_project(source)
            if result.get("ok"):
                ok += 1
                moved_total += int(result.get("moved") or 0)
            else:
                failed += 1
                if not first_error:
                    first_error = f"{source}\n{result.get('error') or '未知错误'}"
        progress.setValue(len(candidates))
        self.status_label.setText(
            f"批量整理完成：成功 {ok} 个，收纳 {moved_total} 项"
            + (f"，失败 {failed} 个" if failed else "")
            + "。"
        )
        if failed:
            QMessageBox.warning(self, "部分整理失败", f"成功 {ok} 个，失败 {failed} 个。\n第一条错误：\n{first_error or '（无）'}")
        self.populate_cards(preferred_index=self.current_card_index)

    def move_selected_cards(self) -> None:
        indices = sorted(i for i in self.selected_indices if 0 <= i < len(self.cards))
        movable = []
        for i in indices:
            src = self._card_source_path(i)
            if src is not None:
                movable.append((i, src))
        if not movable:
            QMessageBox.information(self, "未选择可移动卡片", "请先按住 Ctrl 点选多张卡片（需有可移动来源）。")
            return
        chosen = self._pick_target_for_card(movable[0][0])
        if not chosen:
            return
        chosen = self._normalise_target_path(chosen)
        plans = []
        for i, src in movable:
            plans.append(self._plan_card_move(self.cards[i], src, chosen))
        if not self._confirm_move_plans(plans):
            return
        progress = QProgressDialog("正在批量移动并校验……", "取消", 0, len(movable), self)
        progress.setWindowTitle("批量移动")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        move_log = MoveLog(default_move_log_path(DATA_ROOT))
        ok = 0
        failed = 0
        first_error = ""
        moved_indices: set[int] = set()
        for pos, (i, src) in enumerate(movable):
            if progress.wasCanceled():
                break
            progress.setValue(pos)
            progress.setLabelText(f"移动 {pos + 1}/{len(movable)}：{self.cards[i].get('display_name') or self.cards[i].get('name') or ''}")
            QApplication.processEvents()
            card = self.cards[i]
            result = self._execute_card_move(card, src, chosen, move_log)
            if result.get("ok"):
                self._cleanup_empty_source_chain(src)
                card["source_path"] = result["destination"]
                if result.get("formal"):
                    card["formal_move_destination"] = result["destination"]
                else:
                    card["test_move_destination"] = result["destination"]
                card["user_target_path"] = chosen
                card["needs_human_review"] = False
                self._queue_card(card, status="moved")
                moved_indices.add(i)
                ok += 1
            else:
                failed += 1
                if not first_error:
                    first_error = str(result.get("error") or "")
        progress.setValue(len(movable))
        self.selected_indices = set()
        self._remove_moved_cards_from_work_view(moved_indices)
        self.status_label.setText(f"批量移动完成：成功 {ok} 个" + (f"，失败 {failed} 个" if failed else "") + "。")
        if failed:
            QMessageBox.warning(self, "部分移动失败", f"成功 {ok} 个，失败 {failed} 个。\n第一条错误：\n{first_error or '（无）'}")

    def show_card(self, card: dict) -> None:
        self.show_preview(card)
        title = escape(str(card.get("display_name") or card.get("name") or "未命名资源"))
        type_label = escape(str(TYPE_LABELS.get(card.get("suggested_type"), card.get("suggested_type", ""))))
        confidence = escape(str(CONFIDENCE_LABELS.get(card.get("confidence"), card.get("confidence", ""))))
        review_text = "需确认" if card.get("needs_human_review") else "已入库/候选"
        tags = " / ".join(escape(str(tag)) for tag in card.get("content_tags") or [])
        html: list[str] = [
            "<style>",
            "body { color:#1f2937; font-size:12px; line-height:1.62; }",
            "h2 { font-size:17px; margin:0 0 12px 0; color:#111827; }",
            "h3 { font-size:13px; margin:18px 0 9px 0; color:#111827; }",
            ".meta { margin:8px 0 13px 0; }",
            ".chip { display:inline-block; padding:4px 8px; border-radius:6px; margin:0 8px 7px 0; font-weight:700; }",
            ".type { background:#e6f4ec; color:#166534; }",
            ".confidence { background:#fff3d8; color:#92400e; }",
            ".review { background:#e8eef8; color:#1d4ed8; }",
            ".path { background:#f6f8fa; border-radius:6px; padding:7px; margin:5px 0; }",
            "ul { margin-top:4px; padding-left:18px; }",
            ".muted { color:#64748b; }",
            ".ai { background:#f8fafc; border-left:3px solid #2563eb; padding:8px; white-space:pre-wrap; }",
            "</style>",
            f"<h2>{title}</h2>",
            "<div class='meta'>",
            f"<span class='chip type'>{type_label}</span>",
            f"<span class='chip confidence'>置信度：{confidence}</span>",
            f"<span class='chip review'>{review_text}</span>",
            "</div>",
        ]
        if tags:
            html.append(f"<div class='muted'>内容线索：{tags}</div>")
        manual_tags = " / ".join(escape(str(tag)) for tag in card.get("manual_tags") or [])
        if manual_tags:
            html.append(f"<div class='muted'>人工标签：{manual_tags}</div>")
        if card.get("manual_note"):
            html.append("<h3>备注</h3>")
            html.append(f"<div class='ai'>{escape(str(card.get('manual_note')))}</div>")
        if card.get("split_from"):
            html.append(f"<div class='muted'>拆分来源：{escape(str(card.get('split_from')))}</div>")
        if is_web_card(card):
            html.append("<h3>网页</h3>")
            web_meta = " / ".join(
                escape(str(value))
                for value in (card.get("web_platform"), card.get("web_content_label"), card.get("web_author"))
                if value
            )
            if web_meta:
                html.append(f"<div class='muted'>{web_meta}</div>")
            html.append(f"<div class='path'>{escape(str(card.get('source_url') or ''))}</div>")
            if card.get("web_description"):
                html.append(f"<div class='ai'>{escape(str(card.get('web_description')))}</div>")
        if card.get("source_path"):
            html.append("<h3>来源</h3>")
            html.append(f"<div class='path'>{escape(str(card.get('source_path')))}</div>")
        if card.get("user_target_path"):
            html.append("<h3>手动目标分类</h3>")
            html.append(f"<div class='path'>{escape(str(card['user_target_path']))}</div>")

        html.append("<h3>目标分类候选</h3>")
        suggestions = card.get("target_suggestions") or []
        if suggestions:
            html.append("<ul>")
            for item in suggestions[:5]:
                target = escape(self._relative_target(item["path"]))
                reason = escape(str(item.get("reason", "")))
                html.append(f"<li><b>{target}</b><br><span class='muted'>{reason}</span></li>")
            html.append("</ul>")
        else:
            html.append("<ul>")
            for path in card.get("target_path_hints", []):
                html.append(f"<li>{escape(self._relative_target(path))}</li>")
            if not card.get("target_path_hints"):
                html.append("<li class='muted'>暂无候选。</li>")
            html.append("</ul>")

        html.append("<h3>判断原因</h3><ul>")
        for reason in card.get("reasons") or ["暂无明显原因。"]:
            html.append(f"<li>{escape(str(reason))}</li>")
        html.append("</ul>")
        suggestion = card.get("deepseek_suggestion")
        if suggestion:
            html.append("<h3>DeepSeek 建议</h3>")
            if isinstance(suggestion, dict):
                rows = [
                    ("译名", suggestion.get("translated_name")),
                    ("建议分类", suggestion.get("target_path")),
                    ("是否新建目录", "是" if suggestion.get("new_folder_needed") else "否"),
                    ("置信度", suggestion.get("confidence")),
                    ("需确认原因", suggestion.get("review_reason")),
                ]
                html.append("<div class='ai'>")
                for label, value in rows:
                    if value:
                        html.append(f"<div><b>{escape(str(label))}：</b>{escape(str(value))}</div>")
                html.append("</div>")
            else:
                html.append(f"<div class='ai'>{escape(str(suggestion))}</div>")
        samples = card.get("archive_entry_samples") or []
        if samples:
            html.append("<h3>目录样例</h3><ul>")
            for sample in samples[:10]:
                html.append(f"<li>{escape(str(sample))}</li>")
            html.append("</ul>")
        html.append("<h3>操作状态</h3>")
        html.append("<div class='muted'>悬浮或右键卡片可打开位置、翻译、移动入库、重新分析（压缩包不解压）。</div>")
        self.detail_text.setHtml("".join(html))

    def show_preview(self, card: dict) -> None:
        result = prepare_preview_image(card, self.preview_cache_dir, size=(520, 340))
        if not result.get("ok"):
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("暂无预览图")
            self.preview_label.setToolTip(result.get("error") or "没有找到可用预览图。")
            return
        pixmap = QPixmap(result["path"])
        if pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("预览图加载失败")
            self.preview_label.setToolTip("预览图文件存在，但无法加载。")
            return
        self.preview_label.setText("")
        self.preview_label.setToolTip("")
        self.preview_label.setPixmap(pixmap.scaled(420, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def change_selected_target(self) -> None:
        index = self._selected_card_index()
        if index is None:
            return
        chosen = self._pick_target_for_card(index)
        if not chosen:
            return
        card = self.cards[index]
        card["user_target_path"] = chosen
        card["needs_human_review"] = True
        self.populate_cards(preferred_index=index)
        self.status_label.setText("已选择目标分类；这只是建议，没有移动文件。")

    def _pick_target_for_card(self, index: int) -> str | None:
        if not (0 <= index < len(self.cards)):
            return None
        card = self.cards[index]
        resource_root = self._configured_resource_root()
        if resource_root is None:
            QMessageBox.information(self, "先设置资源库", "请先在设置里选择资源库根路径，再为卡片选择目标分类。")
            return None
        if not resource_root.exists():
            folder = QFileDialog.getExistingDirectory(
                self, "选择这张卡片的目标分类", str(Path.home())
            )
            return folder or None
        try:
            move_log = MoveLog(default_move_log_path(DATA_ROOT))
        except Exception:
            move_log = None
        dialog = TargetPickerDialog(card, resource_root, self, move_log=move_log)
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.selected_path()

    def _deepseek_model_summary(self) -> str:
        tier = str(self.settings.get("deepseek_default_tier") or "flash")
        label = "Pro" if tier == "pro" else "Flash"
        return f"{label} / {selected_model(self.settings, tier)}"

    def _show_deepseek_key_help(self, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("需要 DeepSeek API Key")
        box.setText(message)
        box.setInformativeText("没有 Key 时，可以先打开 DeepSeek 官方平台创建 API Key，再回到设置里粘贴。")
        open_button = box.addButton("打开创建页", QMessageBox.ActionRole)
        settings_button = box.addButton("去设置", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked == open_button:
            QDesktopServices.openUrl(QUrl(DEEPSEEK_API_KEYS_URL))
        elif clicked == settings_button:
            self.open_settings()

    def translate_card(self, index: int) -> None:
        if not (0 <= index < len(self.cards)):
            return
        card = self.cards[index]
        card["pending_translation"] = True
        card["needs_human_review"] = True
        self.populate_cards(preferred_index=index)
        if not deepseek_api_key(self.settings):
            self._show_deepseek_key_help("已标记为待翻译，但当前还没有 DeepSeek API Key。")
            return
        self.status_label.setText(f"正在请求 DeepSeek（{self._deepseek_model_summary()}）翻译与分类建议……")
        QApplication.processEvents()
        result = request_structured_card_suggestion(card, self.settings)
        if not result.get("ok"):
            QMessageBox.warning(self, "DeepSeek 请求失败", result.get("error", "未知错误"))
            self.status_label.setText("DeepSeek 请求失败；已保留待翻译标记。")
            return
        suggestion = result.get("suggestion") or {}
        self._apply_suggestion_to_card(card, suggestion)
        translated = str(suggestion.get("translated_name") or "").strip()
        ai_target = str(suggestion.get("target_path") or "").strip()
        renamed = self._maybe_rename_card_folder(card, translated)
        self.populate_cards(preferred_index=index)
        self.show_card(card)
        conf = suggestion.get("confidence") or "?"
        rename_note = f"；已把本地文件夹改名为「{Path(renamed).name}」" if renamed else ""
        move_note = "" if renamed else "；未自动移动"
        self.status_label.setText(
            f"DeepSeek（{self._deepseek_model_summary()}）译名：{translated or '（无）'}；建议分类：{ai_target or '（无）'}；置信度 {conf}{rename_note}{move_note}。"
        )

    def _queue_card(self, card: dict, *, status: str | None = None, suggestion: dict | None = None) -> None:
        """把卡片同步进持久化审阅队列（失败静默，不影响主流程）。"""
        if not getattr(self, "review_queue", None):
            return
        try:
            card_id = self.review_queue.enqueue_card(card)
            if suggestion:
                self.review_queue.apply_suggestion(card_id, suggestion)
            if status:
                self.review_queue.set_status(card_id, status)
        except Exception:
            pass

    def _enqueue_review_cards(self, cards: list[dict]) -> int:
        """分析完成后，把真正不确定的卡片放进审阅队列。"""
        if not getattr(self, "review_queue", None):
            return 0
        candidates = [card for card in cards if card.get("needs_human_review")]
        if not candidates:
            return 0
        try:
            self.review_queue.enqueue_cards(candidates, batch_id=f"analysis:{int(time.time())}")
            return len(candidates)
        except Exception:
            return 0

    def _apply_suggestion_to_card(self, card: dict, suggestion: dict) -> None:
        card["deepseek_suggestion"] = suggestion
        card["pending_translation"] = False
        translated = str(suggestion.get("translated_name") or "").strip()
        if translated:
            card["translated_name"] = translated
            card["display_name"] = translated
        ai_target = str(suggestion.get("target_path") or "").strip()
        if ai_target:
            ai_target = self._normalise_target_path(ai_target)
            suggestion["target_path"] = ai_target
            card["ai_target_path"] = ai_target
            hints = [ai_target] + [h for h in (card.get("target_path_hints") or []) if h != ai_target]
            card["target_path_hints"] = hints
        card["needs_human_review"] = self._suggestion_needs_review(suggestion, ai_target)
        status = STATUS_APPROVED if not card["needs_human_review"] else None
        self._queue_card(card, status=status, suggestion=suggestion)

    def _normalise_target_path(self, target: str) -> str:
        target = str(target or "").strip()
        if not target:
            return ""
        path = Path(target)
        root = self._configured_resource_root()
        if root is None:
            return str(path) if path.is_absolute() else target
        if path.is_absolute():
            try:
                resolved = path.resolve()
                root_resolved = root.resolve()
                if resolved == root_resolved or resolved.is_relative_to(root_resolved):
                    return str(path)
            except (OSError, ValueError):
                pass
            parts = self._library_relative_parts(path, root)
            if parts:
                return str(root.joinpath(*parts))
            return str(path)
        parts = [part for part in re.split(r"[\\/]+", target) if part and not part.endswith(":")]
        root_name = root.name
        if root_name in parts:
            parts = parts[parts.index(root_name) + 1 :]
        return str(root.joinpath(*parts)) if parts else str(root)

    def _library_relative_parts(self, path: Path, root: Path) -> list[str]:
        parts = [part for part in path.parts if part and part != path.anchor]
        if not parts:
            return []
        root_name = Path(root).name
        if root_name in parts:
            return parts[parts.index(root_name) + 1 :]
        first = parts[0].lower()
        prefixes = ("a ", "b ", "c ", "j ", "m ", "u ", "z ")
        if first.startswith(prefixes) or parts[0] in {"A", "B", "C", "J", "M", "U", "Z"}:
            return parts
        return []

    def _suggestion_needs_review(self, suggestion: dict, ai_target: str) -> bool:
        confidence = str(suggestion.get("confidence") or "").strip().lower()
        review_reason = str(suggestion.get("review_reason") or "").strip()
        if confidence != "high" or review_reason or bool(suggestion.get("new_folder_needed")):
            return True
        if not ai_target:
            return True
        path = Path(ai_target)
        root = self._configured_resource_root()
        if root is None:
            return True
        try:
            if path.exists() and (path.resolve() == root.resolve() or path.resolve().is_relative_to(root.resolve())):
                return False
        except (OSError, ValueError):
            return True
        return True

    def _maybe_rename_card_folder(self, card: dict, translated_name: str) -> str | None:
        """按设置把卡片对应的本地文件夹改成译名；返回新路径或 None。"""
        if not self.settings.get("rename_local_after_translate"):
            return None
        translated_name = (translated_name or "").strip()
        if not translated_name:
            return None
        src = str(card.get("source_path") or "")
        if not src or not Path(src).exists() or not Path(src).is_dir():
            return None
        old_path = Path(src)
        try:
            result = rename_folder(
                old_path, translated_name, getattr(self, "rename_log", None),
                card_id=str(card.get("card_id") or ""),
            )
        except Exception:
            return None
        if result.get("ok") and not result.get("skipped"):
            new_path = Path(str(result["path"]))
            card["source_path"] = str(new_path)
            card["display_name"] = new_path.name
            self._after_folder_renamed(old_path, new_path)
            return str(new_path)
        return None

    def translate_all_cards(self) -> None:
        if not self.cards:
            QMessageBox.information(self, "暂无卡片", "请先运行一次分析或浏览资源库。")
            return
        self._translate_indices(list(range(len(self.cards))), scope_label="全部")

    def translate_selected_cards(self) -> None:
        indices = sorted(i for i in self.selected_indices if 0 <= i < len(self.cards))
        if not indices:
            QMessageBox.information(self, "未选择", "请先进入多选并勾选要翻译的卡片。")
            return
        self._translate_indices(indices, scope_label="选中")

    def _translate_indices(self, indices: list[int], scope_label: str = "全部") -> None:
        indices = [i for i in indices if 0 <= i < len(self.cards)]
        if not indices:
            return
        if not deepseek_api_key(self.settings):
            self._show_deepseek_key_help("当前还没有 DeepSeek API Key，暂时不能批量翻译。")
            return
        rename_on = bool(self.settings.get("rename_local_after_translate"))
        model_text = self._deepseek_model_summary()
        if rename_on:
            ans = QMessageBox.question(
                self,
                "确认翻译并重命名",
                f"将使用 DeepSeek（{model_text}）翻译{scope_label} {len(indices)} 张卡片，"
                "并把成功的【本地文件夹】同步改成译名。\n"
                "（改名安全、可在重命名日志里撤销；不会移动或删除内容。）\n\n是否继续？",
            )
            if ans != QMessageBox.Yes:
                return
        total = len(indices)
        renamed_count = 0
        progress = QProgressDialog(f"正在翻译……当前模型：{model_text}", "取消", 0, total, self)
        progress.setWindowTitle("翻译")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        applied = 0
        failed = 0
        first_error = ""
        for position, idx in enumerate(indices):
            if progress.wasCanceled():
                break
            card = self.cards[idx]
            name = card.get("display_name") or card.get("name") or ""
            progress.setLabelText(f"正在翻译（{position + 1}/{total}，{model_text}）：{name}")
            progress.setValue(position)
            QApplication.processEvents()
            result = request_structured_card_suggestion(card, self.settings)
            if result.get("ok"):
                sug = result.get("suggestion") or {}
                self._apply_suggestion_to_card(self.cards[idx], sug)
                applied += 1
                if rename_on and self._maybe_rename_card_folder(self.cards[idx], str(sug.get("translated_name") or "")):
                    renamed_count += 1
            else:
                failed += 1
                if not first_error:
                    first_error = str(result.get("error") or "")
        progress.setValue(total)
        self.populate_cards(preferred_index=self.current_card_index)
        msg = f"翻译完成：成功 {applied} 张"
        if failed:
            msg += f"，失败 {failed} 张"
        if rename_on:
            msg += f"；本地文件夹已重命名 {renamed_count} 个"
        msg += "。"
        self.status_label.setText(msg)
        if applied == 0 and total > 0:
            QMessageBox.warning(
                self,
                "翻译未生效",
                "没有任何卡片成功翻译。\n\n常见原因：\n"
                "1) API Key 无效或余额不足；\n"
                "2) 模型名或 API 地址不对（设置里可点“验证 API”自测）；\n"
                "3) 网络/代理问题。\n\n"
                f"返回的第一条错误：\n{first_error or '（无）'}",
            )
        elif failed:
            QMessageBox.information(
                self,
                "部分翻译失败",
                f"成功 {applied} 张，失败 {failed} 张。\n第一条错误：\n{first_error or '（无）'}",
            )

    def mark_selected_review(self) -> None:
        index = self._selected_card_index()
        if index is None:
            return
        self.cards[index]["needs_human_review"] = True
        self.populate_cards(preferred_index=index)
        self.status_label.setText("已标记为需确认。")

    def edit_card_metadata(self, index: int | None = None) -> None:
        if index is None:
            index = self._selected_card_index()
        if index is None or not (0 <= index < len(self.cards)):
            return
        card = self.cards[index]
        dialog = QDialog(self)
        dialog.setWindowTitle("备注 / 标签")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel(str(card.get("display_name") or card.get("name") or "未命名资源"))
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFormLayout()
        tag_input = QLineEdit(", ".join(str(tag) for tag in card.get("manual_tags") or []))
        tag_input.setPlaceholderText("例如：待买、常用、角色、石头")
        note_input = QTextEdit()
        note_input.setPlainText(str(card.get("manual_note") or ""))
        note_input.setPlaceholderText("给自己看的备注")
        note_input.setMinimumHeight(140)
        form.addRow("标签", tag_input)
        form.addRow("备注", note_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return

        tags = normalize_tags(tag_input.text())
        note = note_input.toPlainText().strip()
        self._save_card_metadata(card, tags, note)
        self.populate_cards(preferred_index=index)
        self.status_label.setText("已保存备注 / 标签。")

    def _save_card_metadata(self, card: dict, tags: list[str], note: str) -> None:
        card["manual_tags"] = tags
        card["manual_note"] = note
        card_id = str(card.get("metadata_card_id") or card_identity(card))
        card["metadata_card_id"] = card_id
        store = getattr(self, "card_metadata", None)
        if store is not None:
            store.set(card_id, tags, note)

    def open_agent_panel(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("审阅者 Agent")
        dialog.setMinimumSize(640, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        transcript = QTextEdit()
        transcript.setReadOnly(True)
        paths = self._input_paths_from_edit()
        transcript.setText(
            "审阅者模式草稿\n\n"
            f"当前待整理来源：{len(paths)} 个\n"
            f"当前视图卡片：{len(self.cards)} 张\n\n"
            "可交给 Agent 的流程：解压到 staging -> 生成卡片 -> 翻译/归类建议 -> 等你审批 -> 移动入库。\n"
            "当前版本仍不会自动删除源压缩包；解压会写 manifest 便于回溯。"
        )
        layout.addWidget(transcript, 1)

        row = QHBoxLayout()
        prompt = QLineEdit()
        prompt.setPlaceholderText("输入整理指令或审阅备注")
        send_button = QPushButton("记录")
        send_button.clicked.connect(
            lambda: (
                transcript.append(f"\n你：{prompt.text().strip()}"),
                transcript.append("Agent：已记录到本轮审阅上下文。真实自动执行将在 DeepSeek/Hanako 接入后开放。"),
                prompt.clear(),
            )
            if prompt.text().strip()
            else None
        )
        row.addWidget(prompt, 1)
        row.addWidget(send_button)
        layout.addLayout(row)
        dialog.exec()

    def export_review_plan(self) -> None:
        if not self.cards:
            QMessageBox.information(self, "暂无卡片", "请先运行一次分析。")
            return
        paths = write_review_plan(self.cards, self.current_report_dir)
        plan_path = Path(paths["markdown"])
        self.current_report = plan_path
        self.status_label.setText("已生成入库审阅计划；仍然没有移动、删除或上传。")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(plan_path)))

    def handle_card_action(self, action: str, index: int) -> None:
        self.select_card(index)
        if action == "show_detail":
            self.show_detail_dialog(index)
        elif action == "open_location":
            self.open_card_location(index)
        elif action == "copy_source_path":
            card = self.cards[index] if 0 <= index < len(self.cards) else {}
            if is_web_card(card):
                QApplication.clipboard().setText(str(card.get("source_url") or ""))
                self.status_label.setText("已复制网页链接。")
            else:
                source = self._card_source_path(index)
                QApplication.clipboard().setText(str(source) if source else "")
                self.status_label.setText("已复制来源路径。")
        elif action == "change_target":
            self.change_selected_target()
        elif action == "mark_review":
            self.mark_selected_review()
        elif action == "edit_metadata":
            self.edit_card_metadata(index)
        elif action == "deep_analyze":
            self.start_deep_analysis(index)
        elif action == "format_cover":
            self.format_card_cover_project(index)
        elif action == "translate":
            self.translate_card(index)
        elif action == "move":
            self.execute_selected_test_move(index)

    def execute_selected_test_move(self, index: int) -> None:
        if not (0 <= index < len(self.cards)):
            return
        card = self.cards[index]
        if is_web_card(card):
            self.save_web_card_to_library(index)
            return
        source = self._card_source_path(index)
        if source is None:
            QMessageBox.information(self, "没有来源路径", "这张卡片没有可移动的来源路径。")
            return
        target_path = self._effective_target_path(card)
        if not target_path:
            chosen = self._pick_target_for_card(index)
            if not chosen:
                self.status_label.setText("已取消：未选择目标分类，没有移动文件。")
                return
            target_path = self._normalise_target_path(chosen)
            card["user_target_path"] = target_path
            self.populate_cards(preferred_index=index)
        else:
            card["user_target_path"] = target_path
        plan = self._plan_card_move(card, source, target_path)
        if not self._confirm_move_plans([plan]):
            return
        progress = QProgressDialog("正在移动并校验数量/容量……", None, 0, 0, self)
        progress.setWindowTitle("移动入库")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        try:
            move_log = MoveLog(default_move_log_path(DATA_ROOT))
            result = self._execute_card_move(card, source, target_path, move_log)
        finally:
            progress.close()
        if not result.get("ok"):
            QMessageBox.warning(self, "移动未执行", result.get("error", "未知错误"))
            return
        self._cleanup_empty_source_chain(source)
        card["source_path"] = result["destination"]
        if result.get("formal"):
            card["formal_move_destination"] = result["destination"]
        else:
            card["test_move_destination"] = result["destination"]
        card["needs_human_review"] = False
        self._queue_card(card, status="moved")
        self._remove_moved_cards_from_work_view({index})
        verify_text = "校验通过" if result.get("verified") else "⚠ 数量/容量不一致，请复核"
        mode_text = "入库移动" if result.get("formal") else "移动"
        self.status_label.setText(f"已{mode_text}到：{result['destination']}（{verify_text}）")

    def save_web_card_to_library(self, index: int) -> None:
        if not (0 <= index < len(self.cards)):
            return
        card = self.cards[index]
        target_path = self._effective_target_path(card)
        if not target_path:
            chosen = self._pick_target_for_card(index)
            if not chosen:
                self.status_label.setText("已取消：未选择网页资源的目标分类。")
                return
            target_path = self._normalise_target_path(chosen)
            card["user_target_path"] = target_path
            self.populate_cards(preferred_index=index)
        target_dir = Path(target_path)
        if not target_dir.is_absolute():
            root = self._configured_resource_root()
            if root is None:
                QMessageBox.information(self, "先设置资源库", "请先在设置里选择资源库根路径，再保存网页资源。")
                return
            target_dir = root / target_dir

        title = card.get("display_name") or card.get("name") or "网页资源"
        answer = QMessageBox.question(
            self,
            "保存网页资源",
            f"将把网页资源保存到：\n{target_dir}\n\n网页：{card.get('source_url')}\n\n是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        result = save_web_resource_bundle(card, target_dir)
        if not result.get("ok"):
            QMessageBox.warning(self, "网页资源未保存", result.get("error", "未知错误"))
            return

        folder_path = str(result["folder_path"])
        card["source_path"] = folder_path
        card["web_resource_folder"] = folder_path
        card["target_path_hints"] = [str(target_dir)]
        card["needs_human_review"] = False
        self._queue_card(card, status="moved")
        self._remove_moved_cards_from_work_view({index})
        self.status_label.setText(f"网页资源已保存：{title} -> {folder_path}")

    def start_deep_analysis(self, index: int) -> None:
        if self.deep_thread is not None and self.deep_thread.isRunning():
            QMessageBox.information(self, "正在重新分析", "请等待当前来源重新分析完成。")
            return
        source = self._card_source_path(index)
        if source is None:
            QMessageBox.information(self, "没有来源路径", "这张卡片暂时没有可重新分析的来源路径。")
            return

        if source.is_file() and is_archive(source):
            message = (
                "当前只分析压缩包文件本身和外层元数据，不会解压，也不会读取或拆分内部目录。\n"
                "如需分析内部内容，请先在工作台外手动解压，再分析解压后的文件夹。\n\n"
                f"压缩包：\n{source}"
            )
            title = "确认分析压缩包外层"
        elif source.is_file():
            message = f"将重新分析这个文件，不会自动解压、移动、删除或上传。\n\n来源：\n{source}"
            title = "确认重新分析"
        else:
            message = (
                "将重新扫描这个来源文件夹并生成卡片；遇到压缩包时只把它作为一个外层文件，"
                "不会解压或读取内部目录。\n\n"
                f"来源文件夹：\n{source}"
            )
            title = "确认重新分析"
        answer = QMessageBox.question(self, title, message)
        if answer != QMessageBox.Yes:
            return

        self.cards[index]["needs_human_review"] = True
        self.cards[index]["deep_analyze_requested"] = True
        self.populate_cards(preferred_index=index)
        self.analysis_cancel_requested = False
        self.btn_analyze.setIcon(self._toolbar_icon("play"))
        self.btn_analyze.setToolTip("正在重新分析当前来源")
        self.status_label.setText("正在重新分析：只扫描当前来源，不自动解压。")
        self._set_analysis_active(True, "正在重新分析，请稍后（不解压）", 6)

        self.deep_thread = QThread()
        self.deep_worker = DeepAnalyzeWorker(source, self.staging_root, self._configured_resource_root())
        self.deep_worker.moveToThread(self.deep_thread)
        self.deep_thread.started.connect(self.deep_worker.run)
        self.deep_worker.progress.connect(self.on_analysis_progress)
        self.deep_worker.finished.connect(self.on_deep_analysis_finished)
        self.deep_worker.finished.connect(self.deep_thread.quit)
        self.deep_worker.finished.connect(self.deep_worker.deleteLater)
        self.deep_thread.finished.connect(lambda: setattr(self, "deep_thread", None))
        self.deep_thread.finished.connect(lambda: setattr(self, "deep_worker", None))
        self.deep_thread.finished.connect(self.deep_thread.deleteLater)
        self.deep_thread.start()

    def on_deep_analysis_finished(self, result: dict) -> None:
        self._set_analysis_active(False)
        self.btn_cancel_analysis.setEnabled(True)
        self.btn_cancel_analysis_inline.setEnabled(True)
        self.btn_analyze.setIcon(self._toolbar_icon("play"))
        self.btn_analyze.setToolTip("详细分析当前路径")
        if not result.get("ok"):
            if self.analysis_cancel_requested or "用户取消" in str(result.get("error") or ""):
                self.status_label.setText("重新分析已取消。")
                return
            self.status_label.setText("重新分析失败。")
            QMessageBox.critical(self, "重新分析失败", result.get("error", "未知错误"))
            return

        scan_path = Path(result["scan_path"])
        self.current_input_path = scan_path
        self._set_view_cards("work", result["cards"], scan_path, 0 if result["cards"] else None, True)
        self.current_report = Path(result["paths"]["markdown"])
        self.current_report_dir = self.current_report.parent
        scan = result["scan"]
        source_text = "已重新扫描来源（未解压压缩包）"
        self.summary_label.setText(
            f"{source_text}；发现 {scan.get('total_files', 0)} 个文件、{scan.get('total_dirs', 0)} 个文件夹；"
            f"生成 {len(self.cards)} 张卡片。"
        )
        if self.analysis_cancel_requested or "用户取消" in str(scan.get("stop_reason") or ""):
            self.status_label.setText("重新分析已取消；已完成的卡片仍可查看。")
        else:
            self.status_label.setText("重新分析完成；压缩包未解压，结果仍是建议，不会自动移动。")
        self.populate_cards(preferred_index=0)

    def open_card_location(self, index: int) -> None:
        if 0 <= index < len(self.cards) and is_web_card(self.cards[index]):
            url = str(self.cards[index].get("source_url") or "").strip()
            if not url:
                QMessageBox.information(self, "没有网页链接", "这张网页卡片暂时没有可打开的链接。")
                return
            QDesktopServices.openUrl(QUrl(url))
            return
        source = self._card_source_path(index)
        if source is None:
            QMessageBox.information(self, "没有来源路径", "这张卡片暂时没有可打开的来源路径。")
            return
        open_path = source.parent if source.is_file() else source
        if not open_path.exists():
            QMessageBox.information(self, "路径不存在", f"来源路径已经不存在：\n{open_path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(open_path)))

    def open_report(self) -> None:
        if not self.current_report or not self.current_report.exists():
            QMessageBox.information(self, "暂无报告", "请先运行一次分析。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_report)))

    def open_report_dir(self) -> None:
        self.current_report_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_report_dir)))

    def _selected_card_index(self) -> int | None:
        if self.current_card_index is None:
            return None
        if not (0 <= self.current_card_index < len(self.cards)):
            return None
        return self.current_card_index

    def _card_source_path(self, index: int) -> Path | None:
        if not (0 <= index < len(self.cards)):
            return None
        card = self.cards[index]
        source_path = card.get("source_path")
        if source_path:
            candidate_source = Path(source_path)
            if candidate_source.exists():
                return candidate_source
        archives = card.get("source_archives") or []
        if archives:
            archive_path = Path(archives[0].get("absolute_path", ""))
            if archive_path.exists():
                return archive_path

        if self.current_input_path is None:
            return None
        if self.current_input_path.is_file():
            return self.current_input_path

        source_name = card.get("split_from") or card.get("name") or ""
        candidate = self.current_input_path / source_name
        if candidate.exists():
            return candidate
        return self.current_input_path

    def _card_search_text(self, card: dict) -> str:
        parts = [
            card.get("name", ""),
            card.get("display_name", ""),
            TYPE_LABELS.get(card.get("suggested_type"), card.get("suggested_type", "")),
            CONFIDENCE_LABELS.get(card.get("confidence"), card.get("confidence", "")),
            self._short_target(card),
            " ".join(card.get("content_tags") or []),
            " ".join(card.get("manual_tags") or []),
            card.get("manual_note", ""),
            card.get("source_url", ""),
            card.get("web_domain", ""),
            card.get("web_content_label", ""),
            card.get("web_platform", ""),
            card.get("web_author", ""),
            card.get("web_description", ""),
            " ".join(card.get("reasons") or []),
        ]
        return " ".join(str(part).lower() for part in parts)

    def _card_matches_query(self, card: dict, query: str) -> bool:
        query = str(query or "").strip().lower()
        if not query:
            return True
        if query.startswith("#"):
            tag_query = query[1:].strip()
            if not tag_query:
                return True
            return any(tag_query in str(tag).lower() for tag in card.get("manual_tags") or [])
        return all(part in self._card_search_text(card) for part in query.split())

    def _short_target(self, card: dict) -> str:
        if self.active_view == "library" and card.get("source_path"):
            relative_source = self._relative_target(card.get("source_path", ""))
            if relative_source and relative_source != "资源库根目录":
                parts = [part for part in re.split(r"[\\/]+", relative_source) if part]
                if parts:
                    return "已入库 / " + " / ".join(parts[:2])
            return "已入库"
        target = card.get("user_target_path")
        if not target:
            targets = card.get("target_path_hints") or []
            target = targets[0] if targets else ""
        if not target and is_web_card(card):
            return "网页资源"
        return self._relative_target(target)

    def _relative_target(self, target: str | Path) -> str:
        target = str(target or "")
        roots = [
            str(self.settings.get("resource_root") or ""),
        ]
        for root_text in roots:
            root_text = str(root_text or "").rstrip("\\/")
            if not root_text:
                continue
            if target.lower().startswith(root_text.lower()):
                relative = target[len(root_text) :].lstrip("\\/")
                return relative or "资源库根目录"
            root_name = Path(root_text).name
            parts = [part for part in re.split(r"[\\/]+", target) if part]
            if root_name and root_name in parts:
                root_index = parts.index(root_name)
                relative = "\\".join(parts[root_index + 1 :])
                return relative or "资源库根目录"
        return target


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    initial_path: Path | None = None
    auto_run = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--auto-run":
            auto_run = True
        elif arg == "--path" and index + 1 < len(argv):
            path_parts: list[str] = []
            index += 1
            while index < len(argv) and not argv[index].startswith("--"):
                path_parts.append(argv[index])
                index += 1
            initial_path = Path(" ".join(path_parts))
            continue
        index += 1

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-gpu-compositing")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("资源入库工作台")
    app.setApplicationVersion(__version__)
    install_qt_chinese_translations(app)
    app.setWindowIcon(_app_icon())
    window = ResourceWorkbenchWindow(initial_path=initial_path, auto_run=auto_run)
    window.show()
    exit_code = app.exec()
    drain_async_pools()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
