"""操作记录面板：查看移动 / 重命名日志，并一键撤销。

后端 undo_move / undo_rename 已就绪，这里只做可视化与触发。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
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
    QVBoxLayout,
)

from .move_log import MoveLog
from .mover import undo_move
from .renamer import RenameLog, undo_rename

MOVE_STATUS_LABELS = {
    "moved": "已移动",
    "reverted": "已撤销",
    "revert_failed": "撤销失败",
}
RENAME_STATUS_LABELS = {
    "renamed": "已改名",
    "reverted": "已撤销",
    "revert_failed": "撤销失败",
}


class HistoryDialog(QDialog):
    def __init__(
        self,
        move_log: MoveLog,
        rename_log: RenameLog,
        relative_formatter: Callable[[str], str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("操作记录 / 撤销")
        self.setMinimumSize(760, 520)
        self.move_log = move_log
        self.rename_log = rename_log
        self._relative = relative_formatter or (lambda x: x)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("记录类型"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("移动记录", "move")
        self.kind_combo.addItem("重命名记录", "rename")
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._reload())
        top.addWidget(self.kind_combo)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._reload)
        top.addWidget(self.btn_refresh)
        top.addStretch(1)
        tip = QLabel("选中一条“已移动/已改名”的记录可撤销；撤销同样安全、可再核对。")
        tip.setObjectName("MutedText")
        top.addWidget(tip)
        layout.addLayout(top)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setStyleSheet(
            "QListWidget{background:#ffffff;border:1px solid #d7dbe0;border-radius:8px;font-size:13px;}"
            "QListWidget::item{padding:9px 10px;border-bottom:1px solid #eef1f4;}"
            "QListWidget::item:selected{background:#2563eb;color:#ffffff;}"
        )
        layout.addWidget(self.list_widget, 1)

        row = QHBoxLayout()
        self.btn_undo = QPushButton("撤销选中")
        self.btn_undo.clicked.connect(self._undo)
        row.addWidget(self.btn_undo)
        row.addStretch(1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self._reload()

    def _kind(self) -> str:
        return self.kind_combo.currentData()

    def _reload(self) -> None:
        self.list_widget.clear()
        if self._kind() == "move":
            records = self.move_log.list_records()
            if not records:
                self._placeholder("（暂无移动记录）")
                return
            for rec in records:
                status = MOVE_STATUS_LABELS.get(rec.get("status"), rec.get("status"))
                src = Path(str(rec.get("source") or "")).name
                dst = self._relative(str(rec.get("destination") or ""))
                ver = "校验OK" if rec.get("verified") else "校验X"
                label = f"[{status}] {src}  →  {dst}　({rec.get('file_count', 0)}文件, {ver})　{rec.get('moved_at', '')}"
                li = QListWidgetItem(label)
                li.setData(Qt.UserRole, rec)
                self.list_widget.addItem(li)
        else:
            records = self.rename_log.list_records()
            if not records:
                self._placeholder("（暂无重命名记录）")
                return
            for rec in records:
                status = RENAME_STATUS_LABELS.get(rec.get("status"), rec.get("status"))
                old = Path(str(rec.get("old_path") or "")).name
                new = Path(str(rec.get("new_path") or "")).name
                label = f"[{status}] {old}  →  {new}　{rec.get('created_at', '')}"
                li = QListWidgetItem(label)
                li.setData(Qt.UserRole, rec)
                self.list_widget.addItem(li)

    def _placeholder(self, text: str) -> None:
        li = QListWidgetItem(text)
        li.setFlags(Qt.NoItemFlags)
        self.list_widget.addItem(li)

    def _undo(self) -> None:
        items = [li.data(Qt.UserRole) for li in self.list_widget.selectedItems()]
        items = [it for it in items if isinstance(it, dict)]
        if not items:
            QMessageBox.information(self, "未选择", "请先选中要撤销的记录。")
            return
        kind = self._kind()
        ok = 0
        failed = 0
        first_error = ""
        for rec in items:
            if kind == "move":
                result = undo_move(rec.get("move_id"), self.move_log)
            else:
                result = undo_rename(rec.get("rename_id"), self.rename_log)
            if result.get("ok"):
                ok += 1
            else:
                failed += 1
                if not first_error:
                    first_error = str(result.get("error") or "")
        self._reload()
        msg = f"撤销完成：成功 {ok} 条"
        if failed:
            msg += f"，失败 {failed} 条\n第一条原因：\n{first_error or '（无）'}"
        QMessageBox.information(self, "撤销结果", msg)
