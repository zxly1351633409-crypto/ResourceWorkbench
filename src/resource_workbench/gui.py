from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .classifier import build_cards
from .report import write_reports
from .scanner import ScanConfig, scan_input


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_PATH = Path(r"F:\gpt codex huancun\资源管理工具开发\测试")
DEFAULT_Z_ROOT = Path(r"Z:\整合——资源管理")


TYPE_LABELS = {
    "photo": "照片",
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


CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}


class ResourceWorkbenchApp(tk.Tk):
    def __init__(self, initial_path: Path | None = None, auto_run: bool = False) -> None:
        super().__init__()
        self.title("资源入库工作台 - 只读验证版" + ("（演示）" if auto_run else ""))
        self.geometry("1120x720")
        self.minsize(960, 620)

        self.result_queue: queue.Queue[dict] = queue.Queue()
        self.current_report: Path | None = None
        self.current_report_dir: Path = PROJECT_ROOT / "reports"

        default_path = initial_path or (DEFAULT_TEST_PATH if DEFAULT_TEST_PATH.exists() else PROJECT_ROOT)
        self.path_var = tk.StringVar(value=str(default_path))
        self.status_var = tk.StringVar(value="请选择一个资源文件夹或压缩包，然后点击“开始只读分析”。")
        self.summary_var = tk.StringVar(value="安全模式：只读；不会移动、删除、上传。")

        self._build_ui()
        self.after(150, self._poll_result_queue)
        if auto_run:
            self.after(600, self.start_analysis)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(16, 14, 16, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="资源路径").grid(row=0, column=0, sticky="w", padx=(0, 8))
        path_entry = ttk.Entry(top, textvariable=self.path_var)
        path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="选择文件夹", command=self.choose_folder).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="选择压缩包", command=self.choose_file).grid(row=0, column=3)

        actions = ttk.Frame(self, padding=(16, 0, 16, 8))
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(4, weight=1)

        self.analyze_button = ttk.Button(actions, text="开始只读分析", command=self.start_analysis)
        self.analyze_button.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="打开报告", command=self.open_report).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="打开报告文件夹", command=self.open_report_dir).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(actions, text="清空结果", command=self.clear_results).grid(row=0, column=3, padx=(0, 8))

        status = ttk.Label(actions, textvariable=self.status_var, foreground="#305f9f")
        status.grid(row=0, column=4, sticky="e")

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=3)
        main.add(right, weight=2)

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, textvariable=self.summary_var).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        columns = ("name", "type", "confidence", "archives", "split", "review")
        self.cards_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.cards_tree.heading("name", text="资源卡片")
        self.cards_tree.heading("type", text="类型")
        self.cards_tree.heading("confidence", text="置信度")
        self.cards_tree.heading("archives", text="压缩包")
        self.cards_tree.heading("split", text="子资源")
        self.cards_tree.heading("review", text="状态")
        self.cards_tree.column("name", width=420, anchor="w")
        self.cards_tree.column("type", width=80, anchor="center")
        self.cards_tree.column("confidence", width=70, anchor="center")
        self.cards_tree.column("archives", width=70, anchor="center")
        self.cards_tree.column("split", width=80, anchor="center")
        self.cards_tree.column("review", width=120, anchor="center")
        self.cards_tree.grid(row=1, column=0, sticky="nsew")
        self.cards_tree.bind("<<TreeviewSelect>>", self.on_card_selected)

        tree_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.cards_tree.yview)
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.cards_tree.configure(yscrollcommand=tree_scroll.set)

        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="卡片详情").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.detail_text = tk.Text(right, wrap="word", height=10, padx=10, pady=10)
        self.detail_text.grid(row=1, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.detail_text.yview)
        detail_scroll.grid(row=1, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.insert("1.0", "分析完成后，点击左侧卡片可以查看判断原因、压缩包目录样例和建议分类。")
        self.detail_text.configure(state="disabled")

        bottom = ttk.Frame(self, padding=(16, 0, 16, 14))
        bottom.grid(row=3, column=0, sticky="ew")
        ttk.Label(
            bottom,
            text="提示：这是只读验证版。它会读取目录结构和压缩包目录，但不会解压、移动、删除或上传。",
            foreground="#666666",
        ).grid(row=0, column=0, sticky="w")

    def choose_folder(self) -> None:
        initial = self.path_var.get()
        folder = filedialog.askdirectory(
            title="选择要分析的资源文件夹",
            initialdir=initial if Path(initial).exists() and Path(initial).is_dir() else str(PROJECT_ROOT),
        )
        if folder:
            self.path_var.set(folder)

    def choose_file(self) -> None:
        initial = self.path_var.get()
        file_path = filedialog.askopenfilename(
            title="选择要分析的压缩包",
            initialdir=initial if Path(initial).exists() and Path(initial).is_dir() else str(PROJECT_ROOT),
            filetypes=[
                ("压缩包", "*.zip *.rar *.7z *.tar *.gz *.tgz *.iso"),
                ("所有文件", "*.*"),
            ],
        )
        if file_path:
            self.path_var.set(file_path)

    def start_analysis(self) -> None:
        input_path = Path(self.path_var.get().strip().strip('"'))
        if not input_path.exists():
            messagebox.showerror("路径不存在", f"找不到这个路径：\n{input_path}")
            return

        self.clear_results(keep_status=True)
        self.status_var.set("正在只读分析，请稍等……")
        self.summary_var.set("分析中：只读扫描 + 预览压缩包目录。")
        self.analyze_button.configure(state="disabled")

        worker = threading.Thread(target=self._analysis_worker, args=(input_path,), daemon=True)
        worker.start()

    def _analysis_worker(self, input_path: Path) -> None:
        try:
            config = ScanConfig(
                max_files=50000,
                max_depth=8,
                max_seconds=120,
                inspect_archives=True,
                max_archives_to_inspect=12,
                max_entries_per_archive=300,
            )
            scan = scan_input(input_path, config=config)
            cards = build_cards(scan, z_root=DEFAULT_Z_ROOT)
            paths = write_reports(scan, cards, output_dir=PROJECT_ROOT / "reports")
            self.result_queue.put({"ok": True, "scan": scan, "cards": cards, "paths": paths})
        except Exception as exc:  # noqa: BLE001 - show GUI-friendly error
            self.result_queue.put({"ok": False, "error": str(exc)})

    def _poll_result_queue(self) -> None:
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_result_queue)
            return

        self.analyze_button.configure(state="normal")
        if not result["ok"]:
            self.status_var.set("分析失败。")
            messagebox.showerror("分析失败", result["error"])
        else:
            self._show_result(result)
        self.after(150, self._poll_result_queue)

    def _show_result(self, result: dict) -> None:
        scan = result["scan"]
        cards = result["cards"]
        paths = result["paths"]
        self.current_report = Path(paths["markdown"])
        self.current_report_dir = self.current_report.parent

        self.status_var.set("分析完成。")
        self.summary_var.set(
            f"发现 {scan.get('total_files', 0)} 个文件、{scan.get('total_dirs', 0)} 个文件夹；"
            f"生成 {len(cards)} 张临时卡片；预览压缩包 {scan.get('inspected_archives', 0)} 个。"
        )

        for index, card in enumerate(cards):
            review = "需确认" if card.get("needs_human_review") else "候选可用"
            self.cards_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    card.get("name", ""),
                    TYPE_LABELS.get(card.get("suggested_type"), card.get("suggested_type", "")),
                    CONFIDENCE_LABELS.get(card.get("confidence"), card.get("confidence", "")),
                    card.get("archive_count", 0),
                    card.get("possible_split_count", 0),
                    review,
                ),
            )

        self.cards = cards
        if cards:
            self.cards_tree.selection_set("0")
            self.cards_tree.focus("0")
            self.show_card_detail(cards[0])
        else:
            self.set_detail_text("没有生成卡片建议。")

    def on_card_selected(self, _event: object) -> None:
        selection = self.cards_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if hasattr(self, "cards") and 0 <= index < len(self.cards):
            self.show_card_detail(self.cards[index])

    def show_card_detail(self, card: dict) -> None:
        lines: list[str] = []
        lines.append(f"名称：{card.get('name', '')}")
        lines.append(f"建议类型：{TYPE_LABELS.get(card.get('suggested_type'), card.get('suggested_type', ''))}")
        lines.append(f"置信度：{CONFIDENCE_LABELS.get(card.get('confidence'), card.get('confidence', ''))}")
        lines.append(f"内部压缩包：{card.get('archive_count', 0)}")
        if card.get("inspected_archives"):
            lines.append(f"已预览压缩包：{card.get('inspected_archives')}")
        if card.get("virtual_archive_count"):
            lines.append(f"压缩包内仍有压缩包：{card.get('virtual_archive_count')}")
        if card.get("possible_split_count"):
            lines.append(f"可能需要拆分的子资源：约 {card.get('possible_split_count')} 个")

        target_hints = card.get("target_path_hints") or []
        if target_hints:
            lines.append("")
            lines.append("目标分类候选：")
            lines.extend(f"- {item}" for item in target_hints)

        reasons = card.get("reasons") or []
        if reasons:
            lines.append("")
            lines.append("判断原因：")
            lines.extend(f"- {item}" for item in reasons)

        virtual_buckets = card.get("archive_virtual_buckets") or {}
        if virtual_buckets:
            lines.append("")
            lines.append("压缩包目录预览摘要：")
            lines.extend(f"- {key}: {value}" for key, value in virtual_buckets.items())

        samples = card.get("archive_entry_samples") or []
        if samples:
            lines.append("")
            lines.append("压缩包目录样例：")
            lines.extend(f"- {item}" for item in samples[:12])

        subresources = card.get("candidate_subresources") or {}
        if card.get("possible_split_count", 0) >= 3 and subresources:
            lines.append("")
            lines.append("子资源候选：")
            for name, count in list(subresources.items())[:18]:
                lines.append(f"- {name}（样例项 {count}）")

        self.set_detail_text("\n".join(lines))

    def set_detail_text(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def clear_results(self, keep_status: bool = False) -> None:
        for item in self.cards_tree.get_children():
            self.cards_tree.delete(item)
        self.cards = []
        self.set_detail_text("分析完成后，点击左侧卡片可以查看判断原因、压缩包目录样例和建议分类。")
        if not keep_status:
            self.status_var.set("请选择一个资源文件夹或压缩包，然后点击“开始只读分析”。")
            self.summary_var.set("安全模式：只读；不会移动、删除、上传。")

    def open_report(self) -> None:
        if self.current_report and self.current_report.exists():
            os.startfile(self.current_report)  # noqa: S606 - user-triggered local open
            return
        messagebox.showinfo("暂无报告", "还没有可打开的报告。请先运行一次只读分析。")

    def open_report_dir(self) -> None:
        self.current_report_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.current_report_dir)  # noqa: S606 - user-triggered local open


def main() -> None:
    initial_path: Path | None = None
    auto_run = False
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--auto-run":
            auto_run = True
        elif arg == "--path" and index + 1 < len(args):
            path_parts: list[str] = []
            index += 1
            while index < len(args) and not args[index].startswith("--"):
                path_parts.append(args[index])
                index += 1
            initial_path = Path(" ".join(path_parts))
            continue
        index += 1

    app = ResourceWorkbenchApp(initial_path=initial_path, auto_run=auto_run)
    app.mainloop()


if __name__ == "__main__":
    main()
