from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
PUBLIC_RUNTIME = Path(tempfile.mkdtemp(prefix="ResourceWorkbench-PublicRuntime-"))
os.environ["RESOURCE_WORKBENCH_HOME"] = str(PUBLIC_RUNTIME / "profile")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from resource_workbench.qt_app import ResourceWorkbenchWindow


def _preview(path: Path, colors: tuple[str, str], variant: int) -> None:
    image = QImage(640, 420, QImage.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(640, 420))
    gradient.setColorAt(0.0, QColor(colors[0]))
    gradient.setColorAt(1.0, QColor(colors[1]))
    painter.fillRect(image.rect(), gradient)
    painter.setPen(Qt.NoPen)

    if variant == 0:
        painter.setBrush(QColor(247, 213, 157, 190))
        painter.drawRect(QRectF(84, 105, 140, 220))
        painter.drawRect(QRectF(245, 64, 185, 261))
        painter.drawRect(QRectF(452, 138, 104, 187))
        painter.setBrush(QColor(39, 47, 56, 210))
        painter.drawRect(QRectF(105, 190, 44, 135))
        painter.drawRect(QRectF(290, 165, 62, 160))
        painter.drawRect(QRectF(475, 215, 38, 110))
    elif variant == 1:
        painter.setBrush(QColor(220, 243, 239, 210))
        for x in (80, 245, 410):
            painter.drawRoundedRect(QRectF(x, 110, 135, 225), 66, 66)
        painter.setBrush(QColor(19, 88, 88, 210))
        painter.drawRect(QRectF(0, 320, 640, 100))
    elif variant == 2:
        painter.setBrush(QColor(221, 235, 255, 230))
        painter.drawRoundedRect(QRectF(120, 180, 400, 105), 35, 35)
        painter.drawRoundedRect(QRectF(205, 120, 230, 110), 42, 42)
        painter.setBrush(QColor(31, 54, 96, 230))
        painter.drawEllipse(QRectF(170, 250, 82, 82))
        painter.drawEllipse(QRectF(400, 250, 82, 82))
    else:
        painter.setPen(QPen(QColor(255, 255, 255, 210), 5))
        for inset in (55, 90, 125):
            painter.drawRoundedRect(QRectF(inset, inset * 0.58, 640 - inset * 2, 420 - inset * 1.16), 28, 28)
        painter.setFont(QFont(QApplication.font().family(), 42, QFont.DemiBold))
        painter.drawText(image.rect(), Qt.AlignCenter, "WEB")

    painter.end()
    image.save(str(path), "PNG")


def main() -> int:
    print("screenshot: start", flush=True)
    output = PROJECT_ROOT / "docs" / "assets" / "resourceworkbench-0.3.1.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ResourceWorkbench-PublicShot-") as tmp:
        runtime = Path(tmp)
        os.environ["RESOURCE_WORKBENCH_HOME"] = str(runtime / "profile")
        preview_dir = runtime / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        app = QApplication.instance() or QApplication([])
        print("screenshot: app ready", flush=True)
        font_id = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
        font_families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        app.setFont(QFont(font_families[0] if font_families else "Microsoft YaHei", 9))
        specs = [
            (("#202a44", "#9f7145"), 0),
            (("#0f3d48", "#38a89d"), 1),
            (("#162d54", "#4c83d4"), 2),
            (("#33205e", "#9c55c7"), 3),
        ]
        paths = []
        for index, (colors, variant) in enumerate(specs):
            path = preview_dir / f"preview_{index}.png"
            _preview(path, colors, variant)
            paths.append(path)
        print("screenshot: previews ready", flush=True)
        window = ResourceWorkbenchWindow(initial_path=None, auto_run=False)
        print("screenshot: window ready", flush=True)
        window.resize(1440, 880)
        window.path_edit.setText(r"D:\待整理\示例资源批次")
        window.summary_label.setText("首层资源文件夹 4 个、卡片覆盖 4 个；后台分析完成，可确认目标后入库。")
        window.status_label.setText("分析完成：共 4 张卡片，其中 1 张需确认。")

        tree = window.path_tree
        tree.clear()
        root = QTreeWidgetItem(["示例资源库"])
        root.setExpanded(True)
        tree.addTopLevelItem(root)
        for label in ("M 模型", "Z 照片", "V 视频", "W 网页资料"):
            root.addChild(QTreeWidgetItem([label]))

        cards = [
            {
                "name": "Ruined Factory",
                "display_name": "废墟工厂场景",
                "source_path": r"D:\待整理\示例资源批次\Ruined Factory",
                "suggested_type": "model",
                "confidence": "high",
                "needs_human_review": False,
                "content_tags": ["废土", "建筑", "场景"],
                "target_path_hints": [r"M 模型\F 废土\建筑"],
                "preview_source": {"kind": "file", "path": str(paths[0])},
            },
            {
                "name": "Ancient Hall",
                "display_name": "古建殿堂内景",
                "source_path": r"D:\待整理\示例资源批次\Ancient Hall",
                "suggested_type": "model",
                "confidence": "high",
                "needs_human_review": False,
                "content_tags": ["古建", "室内"],
                "target_path_hints": [r"M 模型\G 中国古建\室内"],
                "preview_source": {"kind": "file", "path": str(paths[1])},
            },
            {
                "name": "Utility Vehicle",
                "display_name": "现代工程车辆",
                "source_path": r"D:\待整理\示例资源批次\Utility Vehicle",
                "suggested_type": "model",
                "confidence": "high",
                "needs_human_review": False,
                "content_tags": ["载具", "车辆"],
                "target_path_hints": [r"M 模型\X 现代\载具\汽车"],
                "preview_source": {"kind": "file", "path": str(paths[2])},
            },
            {
                "name": "Reference Website",
                "display_name": "网页视觉参考",
                "source_path": "https://example.com/reference",
                "url": "https://example.com/reference",
                "resource_kind": "web",
                "suggested_type": "web",
                "confidence": "medium",
                "needs_human_review": True,
                "content_tags": ["网页", "参考"],
                "target_path_hints": [r"W 网页资料\视觉参考"],
                "preview_source": {"kind": "file", "path": str(paths[3])},
            },
        ]
        window._set_view_cards("work", cards, Path(r"D:\待整理\示例资源批次"), 0, True)
        print("screenshot: cards ready", flush=True)
        window.show()
        print("screenshot: shown", flush=True)

        def restore_demo_after_startup() -> None:
            window.path_edit.setText(r"D:\待整理\示例资源批次")
            window.summary_label.setText("首层资源文件夹 4 个、卡片覆盖 4 个；后台分析完成，可确认目标后入库。")
            window.status_label.setText("分析完成：共 4 张卡片，其中 1 张需确认。")
            tree.clear()
            restored_root = QTreeWidgetItem(["示例资源库"])
            restored_root.setExpanded(True)
            tree.addTopLevelItem(restored_root)
            for label in ("M 模型", "Z 照片", "V 视频", "W 网页资料"):
                restored_root.addChild(QTreeWidgetItem([label]))
            window._set_view_cards("work", cards, Path(r"D:\待整理\示例资源批次"), 0, True)

        QTimer.singleShot(350, restore_demo_after_startup)

        def capture() -> None:
            window.grab().save(str(output), "PNG")
            window.close()
            app.quit()

        QTimer.singleShot(4200, capture)
        app.exec()
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
