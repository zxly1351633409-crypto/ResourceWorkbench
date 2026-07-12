from __future__ import annotations

import argparse
import json
from pathlib import Path

from .archive import find_archive_backends, list_archive_entries
from .classifier import build_cards
from .file_types import is_archive
from .move_log import MoveLog, default_move_log_path, export_records_json
from .mover import execute_formal_move, execute_test_move, undo_move
from .report import write_reports
from .review_queue import (
    ALL_STATUSES,
    ReviewQueue,
    card_identity,
    default_queue_path,
)
from .scanner import ScanConfig, scan_input
from .target_recommender import recommend_target_folders
from . import formatter
from . import maintenance
from .settings import load_settings


import os as _os
PROJECT_ROOT = Path(_os.environ.get("RESOURCE_WORKBENCH_HOME") or Path(__file__).resolve().parents[2])
DEFAULT_Z_ROOT = _os.environ.get("RESOURCE_WORKBENCH_LIBRARY_ROOT", "").strip()
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


def infer_resource_root_depth(input_path: Path) -> int | None:
    name = input_path.name
    parent_name = input_path.parent.name
    if name == "J 教程":
        return 2
    if parent_name == "J 教程":
        return 1
    if name in LIBRARY_SECTION_NAMES:
        return 2
    if parent_name in LIBRARY_SECTION_NAMES:
        return 1
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resource-workbench",
        description="资源入库工作台只读原型 + 审阅队列 / 可回滚测试移动。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="只读扫描指定文件夹或压缩包。")
    analyze_parser.add_argument("input", help="要分析的文件夹或压缩包路径。")
    analyze_parser.add_argument("--output", default="reports", help="报告输出目录。")
    analyze_parser.add_argument("--z-root", default=DEFAULT_Z_ROOT, help="本地资源库根目录。")
    analyze_parser.add_argument("--max-files", type=int, default=30000, help="最多扫描文件数。")
    analyze_parser.add_argument("--max-depth", type=int, default=8, help="最多扫描目录深度。")
    analyze_parser.add_argument("--max-seconds", type=int, default=120, help="最多扫描秒数。")
    analyze_parser.add_argument("--no-inspect-archives", action="store_true", help="不预览压缩包目录。")
    analyze_parser.add_argument("--max-archives", type=int, default=12, help="最多预览多少个压缩包目录。")
    analyze_parser.add_argument("--max-archive-entries", type=int, default=300, help="每个压缩包最多读取多少条目录项。")
    analyze_parser.add_argument(
        "--resource-depth",
        type=int,
        choices=range(1, 5),
        metavar="1-4",
        help="资源库浏览时按几层文件夹合并成一张卡；不填则自动判断。",
    )
    analyze_parser.add_argument("--enqueue", action="store_true", help="把分析得到的卡片写入审阅队列。")
    analyze_parser.add_argument("--json", action="store_true", help="在终端输出 JSON 摘要。")

    tools_parser = subparsers.add_parser("tools", help="检查当前可用工具。")
    tools_parser.add_argument("--json", action="store_true", help="在终端输出 JSON。")

    queue_parser = subparsers.add_parser("queue", help="查看/管理审阅队列。")
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)
    q_list = queue_sub.add_parser("list", help="列出队列项。")
    q_list.add_argument("--status", choices=ALL_STATUSES, help="只看某状态。")
    q_list.add_argument("--json", action="store_true")
    queue_sub.add_parser("counts", help="按状态统计数量。")
    q_set = queue_sub.add_parser("set-status", help="设置某卡片状态。")
    q_set.add_argument("card_id")
    q_set.add_argument("status", choices=ALL_STATUSES)
    q_set.add_argument("--note", default=None)
    q_target = queue_sub.add_parser("set-target", help="设置某卡片目标分类。")
    q_target.add_argument("card_id")
    q_target.add_argument("target_path")

    move_parser = subparsers.add_parser("move", help="执行测试移动（带可回滚日志）。")
    move_parser.add_argument("card_id", help="审阅队列中的 card_id。")
    move_parser.add_argument("--source-root", default=None, help="允许移动的来源目录；可配合 --formal 使用。")
    move_parser.add_argument("--z-root", default=DEFAULT_Z_ROOT)
    move_parser.add_argument("--formal", action="store_true", help="正式移动到 z-root；默认仍移动到测试落点。")
    move_parser.add_argument("--all-source-roots", action="store_true", help="正式移动时允许所有已挂载盘符作为来源。")
    move_parser.add_argument("--dry-run", action="store_true", help="只预演目标路径，不移动文件。")

    undo_parser = subparsers.add_parser("undo", help="撤销一次测试移动。")
    undo_parser.add_argument("move_id")

    moves_parser = subparsers.add_parser("moves", help="查看移动日志。")
    moves_parser.add_argument("--status", default=None)
    moves_parser.add_argument("--export", default=None, help="导出 JSON 到指定路径。")

    recommend_parser = subparsers.add_parser("recommend", help="对某路径的卡片给出目标分类推荐（只读）。")
    recommend_parser.add_argument("input", help="要分析的文件夹或压缩包路径。")
    recommend_parser.add_argument("--z-root", default=DEFAULT_Z_ROOT, help="资源库根目录（用于查找近似分类）。")
    recommend_parser.add_argument("--resource-depth", type=int, choices=range(1, 5), metavar="1-4")
    recommend_parser.add_argument("--top", type=int, default=5, help="每张卡片最多显示几个候选。")
    recommend_parser.add_argument("--json", action="store_true")

    format_parser = subparsers.add_parser("format", help="统一显示格式：封面留外层、其余进“工程”（默认只预览）。")
    format_parser.add_argument("input", help="单个资源文件夹路径。")
    format_parser.add_argument("--project-name", default="工程")
    format_parser.add_argument("--apply", action="store_true", help="真正执行整理（默认只预览）。")
    format_parser.add_argument("--undo", action="store_true", help="撤销上次整理。")

    dedupe_parser = subparsers.add_parser("dedupe", help="在指定路径下找疑似重复文件（只读）。")
    dedupe_parser.add_argument("input")
    dedupe_parser.add_argument("--hash", action="store_true", help="对候选用 sha1 确认内容一致。")
    dedupe_parser.add_argument("--top", type=int, default=40)
    dedupe_parser.add_argument("--json", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup", help="清理空目录（默认只列出，--apply 才删除）。")
    cleanup_parser.add_argument("input")
    cleanup_parser.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "tools":
        return _tools(args)
    if args.command == "analyze":
        return _analyze(args)
    if args.command == "queue":
        return _queue(args)
    if args.command == "move":
        return _move(args)
    if args.command == "undo":
        return _undo(args)
    if args.command == "moves":
        return _moves(args)
    if args.command == "recommend":
        return _recommend(args)
    if args.command == "format":
        return _format(args)
    if args.command == "dedupe":
        return _dedupe(args)
    if args.command == "cleanup":
        return _cleanup(args)
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
        inspect_archives=not args.no_inspect_archives,
        max_archives_to_inspect=args.max_archives,
        max_entries_per_archive=args.max_archive_entries,
        resource_root_depth=args.resource_depth or infer_resource_root_depth(input_path),
    )
    scan = scan_input(input_path, config=config)

    archive_listing = None
    if scan.get("kind") == "archive" and is_archive(input_path):
        archive_listing = list_archive_entries(input_path)
        scan["archive_listing"] = archive_listing

    z_root = Path(args.z_root) if args.z_root else None
    cards = build_cards(scan, z_root=z_root)
    paths = write_reports(scan, cards, output_dir=output_dir)

    enqueued = 0
    if getattr(args, "enqueue", False):
        queue = ReviewQueue(default_queue_path(PROJECT_ROOT))
        ids = queue.enqueue_cards(cards)
        enqueued = len(ids)

    summary = {
        "input": scan.get("input_path"),
        "total_files": scan.get("total_files"),
        "total_dirs": scan.get("total_dirs"),
        "cards": len(cards),
        "enqueued": enqueued,
        "inspected_archives": scan.get("inspected_archives", 0),
        "markdown_report": paths["markdown"],
        "json_report": paths["json"],
        "readonly": enqueued == 0,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("分析完成。")
        print(f"临时卡片数：{summary['cards']}")
        if enqueued:
            print(f"已写入审阅队列：{enqueued} 张")
        print(f"Markdown 报告：{summary['markdown_report']}")
        print(f"JSON 报告：{summary['json_report']}")
        print("安全状态：未移动、未删除、未上传。")
    return 0


def _queue(args: argparse.Namespace) -> int:
    queue = ReviewQueue(default_queue_path(PROJECT_ROOT))
    if args.queue_command == "list":
        items = queue.list_items(status=args.status)
        if getattr(args, "json", False):
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        if not items:
            print("队列为空。")
            return 0
        for item in items:
            print(
                f"[{item['status']}] {item['card_id']}  {item['display_name']}"
                f"  -> {item['target_path'] or '(未定)'}"
            )
        return 0
    if args.queue_command == "counts":
        counts = queue.counts_by_status()
        for status, n in counts.items():
            print(f"{status}: {n}")
        return 0
    if args.queue_command == "set-status":
        ok = queue.set_status(args.card_id, args.status, note=args.note)
        print("已更新。" if ok else "未找到该 card_id。")
        return 0 if ok else 1
    if args.queue_command == "set-target":
        ok = queue.update_fields(args.card_id, target_path=args.target_path)
        print("已更新。" if ok else "未找到该 card_id。")
        return 0 if ok else 1
    return 2


def _move(args: argparse.Namespace) -> int:
    if not str(args.z_root or "").strip():
        print("请通过 --z-root 指定资源库根目录。")
        return 2
    queue = ReviewQueue(default_queue_path(PROJECT_ROOT))
    item = queue.get(args.card_id)
    if item is None:
        print("未找到该 card_id。")
        return 1
    card = item.get("card") or {}
    card["card_id"] = args.card_id
    if item.get("target_path"):
        card["user_target_path"] = item["target_path"]
    move_log = MoveLog(default_move_log_path(PROJECT_ROOT))
    settings = load_settings(PROJECT_ROOT)
    if args.formal:
        source_roots = _mounted_drive_roots() if args.all_source_roots else ([Path(args.source_root)] if args.source_root else [])
        result = execute_formal_move(
            card,
            source_roots,
            Path(args.z_root),
            move_log=move_log,
            dry_run=args.dry_run,
        )
    else:
        if not args.source_root:
            print("测试移动需要 --source-root。")
            return 2
        test_move_root = Path(str(settings.get("test_move_root") or PROJECT_ROOT / "workbench_data" / "test_moves"))
        result = execute_test_move(
            card,
            Path(args.source_root),
            test_move_root,
            Path(args.z_root),
            move_log=None if args.dry_run else move_log,
    )
    if not result.get("ok"):
        if not args.dry_run:
            queue.set_status(args.card_id, "move_failed", note=result.get("error"))
        print(f"移动失败：{result.get('error')}")
        return 1
    if args.dry_run:
        print(f"移动预演：{result['destination']}")
        print(f"文件数：{result['file_count']}  容量：{result['byte_count']} bytes")
        return 0
    queue.set_status(args.card_id, "moved", note=f"move_id={result['move_id']}")
    print(f"移动完成：{result['destination']}")
    print(f"move_id：{result['move_id']}  校验：{'通过' if result['verified'] else '不一致'}")
    return 0


def _mounted_drive_roots() -> list[Path]:
    if _os.name == "nt":
        roots = [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
        return roots or [Path("C:\\")]
    return [Path("/")]


def _undo(args: argparse.Namespace) -> int:
    move_log = MoveLog(default_move_log_path(PROJECT_ROOT))
    result = undo_move(args.move_id, move_log)
    if not result.get("ok"):
        print(f"撤销失败：{result.get('error')}")
        return 1
    print(f"已撤销，恢复到：{result['restored_to']}")
    return 0


def _moves(args: argparse.Namespace) -> int:
    move_log = MoveLog(default_move_log_path(PROJECT_ROOT))
    if args.export:
        out = export_records_json(move_log, Path(args.export))
        print(f"已导出移动日志：{out}")
        return 0
    records = move_log.list_records(status=args.status)
    if not records:
        print("暂无移动记录。")
        return 0
    for rec in records:
        print(
            f"[{rec['status']}] {rec['move_id']}  "
            f"{rec['source']} -> {rec['destination']}  "
            f"({rec['file_count']} 文件, 校验={'OK' if rec['verified'] else 'X'})"
        )
    return 0


def _dedupe(args: argparse.Namespace) -> int:
    groups = maintenance.find_duplicates(Path(args.input), use_hash=args.hash)
    if args.json:
        print(json.dumps(groups[: args.top], ensure_ascii=False, indent=2))
        return 0
    if not groups:
        print("没有发现疑似重复。")
        return 0
    tag = "（已用 sha1 确认）" if args.hash else "（按 名称+大小 初判，加 --hash 确认）"
    print(f"疑似重复组：{len(groups)} {tag}")
    for g in groups[: args.top]:
        print(f"\n[{g['count']}×] {g['key']}  ({g['size']} bytes)")
        for path in g["paths"][:10]:
            print(f"   - {path}")
    print("\n安全状态：只读；没有删除任何文件。")
    return 0


def _cleanup(args: argparse.Namespace) -> int:
    if args.apply:
        result = maintenance.remove_empty_dirs(Path(args.input))
        print(f"已删除空目录：{result['count']} 个")
        for d in result["removed"][:50]:
            print(f"   - {d}")
        return 0
    empties = maintenance.find_empty_dirs(Path(args.input))
    if not empties:
        print("没有空目录。")
        return 0
    print(f"空目录：{len(empties)} 个（加 --apply 才会删除）")
    for d in empties[:50]:
        print(f"   - {d}")
    return 0


def _format(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if args.undo:
        result = formatter.undo_cover_project(path)
        print("撤销完成。" if result.get("ok") else f"撤销失败：{result.get('error')}")
        return 0 if result.get("ok") else 1
    plan = formatter.plan_cover_project(path, project_name=args.project_name)
    if not plan.get("ok"):
        print(f"无法整理：{plan.get('error')}")
        return 1
    print(f"封面：{plan.get('cover') or '（无）'}")
    print(f"将收进“{args.project_name}”的项：{len(plan.get('move_items', []))}")
    for name in plan.get("move_items", [])[:50]:
        print(f"  - {name}")
    if plan.get("already_organized"):
        print("已是封面+工程结构，无需整理。")
        return 0
    if not args.apply:
        print("\n（这是预览。加 --apply 才会真正整理；加 --undo 可撤销。）")
        return 0
    result = formatter.apply_cover_project(path, project_name=args.project_name)
    if result.get("ok"):
        print(f"已整理：收纳 {result.get('moved', 0)} 项；封面 {result.get('cover') or '无'}。")
        return 0
    print(f"整理失败：{result.get('error')}")
    return 1


def _recommend(args: argparse.Namespace) -> int:
    if not str(args.z_root or "").strip():
        print("请通过 --z-root 指定资源库根目录。")
        return 2
    input_path = Path(args.input)
    z_root = Path(args.z_root)
    config = ScanConfig(
        inspect_archives=False,
        resource_root_depth=args.resource_depth or infer_resource_root_depth(input_path),
    )
    scan = scan_input(input_path, config=config)
    cards = build_cards(scan, z_root=z_root)
    payload = []
    for card in cards:
        rec = recommend_target_folders(card, z_root, max_results=args.top)
        payload.append(
            {
                "name": card.get("display_name") or card.get("name"),
                "suggested_type": card.get("suggested_type"),
                "base": rec.get("base_relative"),
                "suggested_new": rec.get("suggested_new"),
                "candidates": [c.get("relative") for c in rec.get("candidates", [])],
            }
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not payload:
        print("没有生成卡片。")
        return 0
    for item in payload:
        print(f"\n■ {item['name']}  [{item['suggested_type']}]")
        print(f"  母路径：{item['base']}")
        if item["candidates"]:
            for cand in item["candidates"]:
                print(f"   - {cand}")
        if item["suggested_new"]:
            print(f"  建议新建：{item['suggested_new']}")
    print("\n安全状态：只读；没有移动、删除、上传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
