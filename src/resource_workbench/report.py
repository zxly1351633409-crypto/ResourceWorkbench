from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_reports(scan: dict, cards: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    json_path = output_dir / f"resource_scan_{stamp}.json"
    md_path = output_dir / f"resource_scan_{stamp}.md"

    payload = {
        "scan": scan,
        "cards": cards,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "safety": {
            "readonly": True,
            "moved_files": False,
            "deleted_files": False,
            "uploaded_to_115": False,
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    return {
        "json": str(json_path),
        "markdown": str(md_path),
    }


def render_markdown(payload: dict) -> str:
    scan = payload["scan"]
    cards = payload["cards"]
    lines: list[str] = []

    lines.append("# 资源批次只读分析报告")
    lines.append("")
    lines.append(f"- 生成时间：{payload['generated_at']}")
    lines.append(f"- 输入路径：`{scan.get('input_path')}`")
    lines.append(f"- 输入类型：{scan.get('kind')}")
    lines.append(f"- 文件数：{scan.get('total_files')}")
    lines.append(f"- 文件夹数：{scan.get('total_dirs')}")
    if scan.get("top_level_card_invariant_applied"):
        lines.append(f"- 首层资源文件夹：{scan.get('top_level_directory_count', 0)}")
        lines.append(f"- 已有卡片覆盖的首层资源：{scan.get('top_level_card_count', 0)}")
        missing = scan.get("missing_top_level_directories") or []
        lines.append(f"- 首层资源缺卡：{'、'.join(missing) if missing else '无'}")
    lines.append(f"- 扫描耗时：{scan.get('elapsed_seconds')} 秒")
    lines.append("- 安全状态：只读扫描；没有移动、删除、上传。")
    lines.append("")

    if scan.get("stopped_early"):
        lines.append(f"> ⚠️ 扫描提前停止：{scan.get('stop_reason')}")
        lines.append("")

    if scan.get("warnings"):
        lines.append("## 警告")
        lines.append("")
        for warning in scan["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## 整体文件类型")
    lines.append("")
    if scan.get("buckets"):
        for bucket, count in scan["buckets"].items():
            lines.append(f"- {bucket}: {count}")
    else:
        lines.append("- 没有发现文件。")
    lines.append("")

    lines.append("## 临时资源卡片建议")
    lines.append("")
    if not cards:
        lines.append("没有生成卡片建议。")
        lines.append("")
    for index, card in enumerate(cards, start=1):
        review = "需要人工确认" if card["needs_human_review"] else "可作为候选"
        lines.append(f"### {index}. {card['name']}")
        lines.append("")
        if card.get("split_from"):
            lines.append(f"- 拆分来源：`{card['split_from']}`")
        lines.append(f"- 建议类型：{card['suggested_type']}")
        lines.append(f"- 置信度：{card['confidence']}")
        if card.get("content_tags"):
            lines.append(f"- 内容线索：{' / '.join(card['content_tags'])}")
        lines.append(f"- 状态：{review}")
        lines.append(f"- 文件数：{card['total_files']}")
        lines.append(f"- 内部压缩包：{card['archive_count']}")
        if card.get("source_archive_count"):
            lines.append(f"- 来源压缩包：{card['source_archive_count']}")
        if card.get("inspected_archives"):
            lines.append(f"- 已预览压缩包：{card['inspected_archives']}")
        if card.get("virtual_archive_count"):
            lines.append(f"- 压缩包内仍有压缩包：{card['virtual_archive_count']}")
        if card.get("possible_split_count", 0) >= 3:
            lines.append(f"- 可能需要拆分的子资源：约 {card['possible_split_count']} 个")
        if card["target_path_hints"]:
            lines.append("- 目标分类候选：")
            suggestions = card.get("target_suggestions") or []
            if suggestions:
                for suggestion in suggestions[:5]:
                    lines.append(f"  - `{suggestion['path']}`：{suggestion['reason']}")
            else:
                for target in card["target_path_hints"]:
                    lines.append(f"  - `{target}`")
        lines.append("- 判断原因：")
        for reason in card["reasons"] or ["暂无明显原因。"]:
            lines.append(f"  - {reason}")
        lines.append("- 文件类型摘要：")
        for bucket, count in card["buckets"].items():
            lines.append(f"  - {bucket}: {count}")
        if card.get("archive_virtual_buckets"):
            lines.append("- 压缩包目录预览摘要：")
            for bucket, count in card["archive_virtual_buckets"].items():
                lines.append(f"  - {bucket}: {count}")
        if card.get("archive_entry_samples"):
            lines.append("- 压缩包目录样例：")
            for sample in card["archive_entry_samples"][:8]:
                lines.append(f"  - `{sample}`")
        if card.get("possible_split_count", 0) >= 3:
            lines.append("- 子资源候选：")
            for candidate, count in list(card.get("candidate_subresources", {}).items())[:12]:
                lines.append(f"  - `{candidate}`（样例项 {count}）")
        lines.append("")

    lines.append("## 下一步建议")
    lines.append("")
    lines.append("1. 先人工检查每张卡片是否应该合并或拆分。")
    lines.append("2. 如果内部存在压缩包，先标记哪些应继续解压，哪些应保留。")
    lines.append("3. 规则确认稳定后，再进入翻译、封面整理、移动和 115 上传阶段。")
    lines.append("")
    return "\n".join(lines)
