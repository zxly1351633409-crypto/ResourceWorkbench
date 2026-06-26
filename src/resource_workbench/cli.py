from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archive import find_archive_backends, list_archive_entries
from .classifier import build_cards
from .file_types import is_archive
from .report import write_reports
from .scanner import ScanConfig, scan_input


DEFAULT_Z_ROOT = Path(r"Z:\整合——资源管理")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resource-workbench",
        description="资源入库工作台只读原型。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="只读扫描指定文件夹或压缩包。")
    analyze_parser.add_argument("input", help="要分析的文件夹或压缩包路径。")
    analyze_parser.add_argument("--output", default="reports", help="报告输出目录。")
    analyze_parser.add_argument("--z-root", default=str(DEFAULT_Z_ROOT), help="本地资源库根目录。")
    analyze_parser.add_argument("--max-files", type=int, default=30000, help="最多扫描文件数。")
    analyze_parser.add_argument("--max-depth", type=int, default=8, help="最多扫描目录深度。")
    analyze_parser.add_argument("--max-seconds", type=int, default=120, help="最多扫描秒数。")
    analyze_parser.add_argument("--json", action="store_true", help="在终端输出 JSON 摘要。")

    tools_parser = subparsers.add_parser("tools", help="检查当前可用工具。")
    tools_parser.add_argument("--json", action="store_true", help="在终端输出 JSON。")

    args = parser.parse_args(argv)

    if args.command == "tools":
        return _tools(args)
    if args.command == "analyze":
        return _analyze(args)
    parser.error("未知命令")
    return 2


def _tools(args: argparse.Namespace) -> int:
    payload = {
        "archive_backends": [
            {"name": backend.name, "executable": str(backend.executable)}
            for backend in find_archive_backends()
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("可用解压后端：")
        if not payload["archive_backends"]:
            print("- 未发现")
        for backend in payload["archive_backends"]:
            print(f"- {backend['name']}: {backend['executable']}")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir

    config = ScanConfig(
        max_files=args.max_files,
        max_depth=args.max_depth,
        max_seconds=args.max_seconds,
    )
    scan = scan_input(input_path, config=config)

    archive_listing = None
    if scan.get("kind") == "archive" and is_archive(input_path):
        archive_listing = list_archive_entries(input_path)
        scan["archive_listing"] = archive_listing

    z_root = Path(args.z_root) if args.z_root else None
    cards = build_cards(scan, z_root=z_root)
    paths = write_reports(scan, cards, output_dir=output_dir)

    summary = {
        "input": scan.get("input_path"),
        "total_files": scan.get("total_files"),
        "total_dirs": scan.get("total_dirs"),
        "cards": len(cards),
        "markdown_report": paths["markdown"],
        "json_report": paths["json"],
        "readonly": True,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("分析完成。")
        print(f"临时卡片数：{summary['cards']}")
        print(f"Markdown 报告：{summary['markdown_report']}")
        print(f"JSON 报告：{summary['json_report']}")
        print("安全状态：只读；没有移动、删除、上传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

