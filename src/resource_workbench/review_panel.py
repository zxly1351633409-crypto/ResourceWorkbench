"""审阅队列面板：把持久化审阅队列做成窗口内的“收件箱”，让用户逐张过审。

用户从操作者变审阅者的落地界面：
- 顶部按状态筛选 + 数量统计。
- 列表多选，一键 通过 / 退回重判 / 否决 / 移除。
- 右侧显示当前选中卡片的预览图、目标路径与判断理由。
- 对“已通过/选中”的卡片执行移动（经主窗口回调，仍写可回滚日志）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .preview import prepare_preview_image
from .review_queue import (
    ALL_STATUSES,
    STATUS_APPROVED,
    STATUS_DONE,
    STATUS_MOVE_FAILED,
    STATUS_MOVED,
    STATUS_NEEDS_RECHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_UPLOAD_PENDING,
    ReviewQueue,
)

STATUS_LABELS = {
    STATUS_PENDING: "待审阅",
    STATUS_APPROVED: "已通过",
    STATUS_REJECTED: "已否决",
    STATUS_NEEDS_RECHECK: "退回重判",
    STATUS_MOVED: "已移动",
    STATUS_MOVE_FAILED: "移动失败",
    STATUS_UPLOAD_PENDING: "待上传",
    STATUS_DONE: "完成",
}


class ReviewQueueDialog(QDialog):
    def __init__(
        self,
        queue: ReviewQueue,
        mover_callback: Callable[[dict], dict] | None = None,
        relative_formatter: Callable[[str], str] | None = None,
        preview_cache_dir: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("审阅队列")
        self.setMinimumSize(980, 620)
        self.queue = queue
        self.mover_callback = mover_callback
        self._relative = relative_formatter or (lambda x: x)
        self.preview_cache_dir = Path(preview_cache_dir) if preview_cache_dir else Path.cwd() / "workbench_data" / "previews"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.counts_label = QLabel("")
        self.counts_label.setObjectName("MutedText")
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("筛选状态"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部", None)
        for status in ALL_STATUSES:
            self.filter_combo.addItem(STATUS_LABELS.get(status, status), status)
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._reload())
        filter_row.addWidget(self.filter_combo)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._reload)
        filter_row.addWidget(self.btn_refresh)
        filter_row.addStretch(1)
        tip = QLabel("左边可多选；右边显示当前选中卡片的预览和判断信息。")
        tip.setObjectName("MutedText")
        filter_row.addWidget(tip)
        layout.addLayout(filter_row)

        body = QSplitter(Qt.Horizontal)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._show_selected_preview)
        body.addWidget(self.list_widget)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(10, 0, 0, 0)
        detail_layout.setSpacing(10)
        self.preview_label = QLabel("选择一项后显示预览图")
        self.preview_label.setObjectName("PreviewBox")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(360, 260)
        self.preview_label.setWordWrap(True)
        detail_layout.addWidget(self.preview_label)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text, 1)
        body.addWidget(detail_panel)
        body.setSizes([560, 400])
        layout.addWidget(body, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_approve = QPushButton("通过")
        self.btn_recheck = QPushButton("退回重判")
        self.btn_reject = QPushButton("否决")
        self.btn_move = QPushButton("执行移动")
        self.btn_remove = QPushButton("移除")
        self.btn_approve.clicked.connect(lambda: self._set_status(STATUS_APPROVED))
        self.btn_recheck.clicked.connect(lambda: self._set_status(STATUS_NEEDS_RECHECK))
        self.btn_reject.clicked.connect(lambda: self._set_status(STATUS_REJECTED))
        self.btn_move.clicked.connect(self._execute_move)
        self.btn_remove.clicked.connect(self._remove)
        for b in (self.btn_approve, self.btn_recheck, self.btn_reject, self.btn_move, self.btn_remove):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        if self.mover_callback is None:
            self.btn_move.setEnabled(False)
            self.btn_move.setToolTip("当前未提供移动能力。")

        self._reload()

    def _reload(self) -> None:
        counts = self.queue.counts_by_status()
        parts = [f"{STATUS_LABELS.get(s, s)} {counts.get(s, 0)}" for s in ALL_STATUSES]
        self.counts_label.setText("　·　".join(parts))
        status = self.filter_combo.currentData()
        items = self.queue.list_items(status=status)
        self.list_widget.clear()
        if not items:
            placeholder = QListWidgetItem("（此状态下没有卡片）")
            placeholder.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)
            self._clear_preview("此状态下没有卡片")
            return
        for item in items:
            name = item.get("display_name") or item.get("name") or item.get("card_id")
            target = item.get("target_path") or ""
            target_text = self._relative(target) if target else "未定目标"
            label = f"[{STATUS_LABELS.get(item.get('status'), item.get('status'))}] {name}  →  {target_text}"
            li = QListWidgetItem(label)
            li.setData(Qt.UserRole, item)
            self.list_widget.addItem(li)
        self.list_widget.setCurrentRow(0)
        self._show_selected_preview()

    def _selected_items(self) -> list[dict]:
        result = []
        for li in self.list_widget.selectedItems():
            data = li.data(Qt.UserRole)
            if isinstance(data, dict):
                result.append(data)
        return result

    def _first_selected_item(self) -> dict | None:
        items = self._selected_items()
        if items:
            return items[0]
        current = self.list_widget.currentItem()
        if current is None:
            return None
        data = current.data(Qt.UserRole)
        return data if isinstance(data, dict) else None

    def _show_selected_preview(self) -> None:
        item = self._first_selected_item()
        if not item:
            self._clear_preview("选择一项后显示预览图")
            return

        card = dict(item.get("card") or {})
        name = item.get("display_name") or item.get("name") or card.get("display_name") or card.get("name") or ""
        target = item.get("target_path") or card.get("user_target_path") or ""
        if not target:
            hints = card.get("target_path_hints") or []
            target = hints[0] if hints else ""
        confidence = item.get("confidence") or card.get("confidence") or ""
        suggested_type = item.get("suggested_type") or card.get("suggested_type") or ""
        reason = item.get("review_reason") or ""
        if not reason:
            reason = "\n".join(str(text) for text in (card.get("reasons") or [])[:6])
        source = item.get("source_path") or card.get("source_path") or ""

        self.detail_text.setPlainText(
            "\n".join(
                line
                for line in [
                    f"名称：{name}",
                    f"状态：{STATUS_LABELS.get(item.get('status'), item.get('status') or '')}",
                    f"类型：{suggested_type or '未定'}",
                    f"置信度：{confidence or '未定'}",
                    f"目标：{self._relative(str(target)) if target else '未定目标'}",
                    f"来源：{source or '未知'}",
                    "",
                    "判断理由：",
                    reason or "暂无理由",
                ]
                if line is not None
            )
        )

        if not card.get("preview_source"):
            self._clear_preview("这项没有可用预览图")
            return
        result = prepare_preview_image(card, self.preview_cache_dir, size=(720, 460), preserve_aspect=True)
        if not result.get("ok"):
            self._clear_preview(str(result.get("error") or "预览图生成失败"))
            return
        pixmap = QPixmap(str(result.get("path") or ""))
        if pixmap.isNull():
            self._clear_preview("预览图加载失败")
            return
        target_size = self.preview_label.size()
        if target_size.width() < 40 or target_size.height() < 40:
            target_size = QSize(360, 260)
        self.preview_label.setText("")
        self.preview_label.setPixmap(pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _clear_preview(self, text: str) -> None:
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(text)
        if hasattr(self, "detail_text") and not self._first_selected_item():
            self.detail_text.setPlainText("")

    def _set_status(self, status: str) -> None:
        items = self._selected_items()
        if not items:
            QMessageBox.information(self, "未选择", "请先在列表里选中一项或多项。")
            return
        for item in items:
            try:
                self.queue.set_status(item["card_id"], status)
            except Exception:
                pass
        self._reload()

    def _remove(self) -> None:
        items = self._selected_items()
        if not items:
            QMessageBox.information(self, "未选择", "请先选中要移除的项。")
            return
        if QMessageBox.question(self, "确认移除", f"从队列移除 {len(items)} 项？（只移出队列，不动文件）") != QMessageBox.Yes:
            return
        for item in items:
            try:
                self.queue.remove(item["card_id"])
            except Exception:
                pass
        self._reload()

    def _execute_move(self) -> None:
        if self.mover_callback is None:
            return
        items = self._selected_items()
        if not items:
            QMessageBox.information(self, "未选择", "请先选中要移动的卡片。")
            return
        ok = 0
        failed = 0
        first_error = ""
        for item in items:
            try:
                result = self.mover_callback(item)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            if result.get("ok"):
                ok += 1
            else:
                failed += 1
                if not first_error:
                    first_error = str(result.get("error") or "")
        self._reload()
        msg = f"移动完成：成功 {ok} 项"
        if failed:
            msg += f"，失败 {failed} 项\n第一条错误：\n{first_error or '（无）'}"
        QMessageBox.information(self, "执行结果", msg)
