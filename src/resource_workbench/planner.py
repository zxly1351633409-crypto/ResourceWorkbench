from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_review_plan(cards: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    payload = build_review_plan(cards)
    json_path = output_dir / f"review_plan_{stamp}.json"
    md_path = output_dir / f"review_plan_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_review_plan_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def build_review_plan(cards: list[dict]) -> dict:
    items = []
    for index, card in enumerate(cards, start=1):
        target_path = _primary_target(card)
        target_exists = bool(target_path and Path(target_path).exists())
        needs_create_target = bool(target_path and not target_exists)
        needs_deep_analyze = bool(card.get("archive_count") or card.get("virtual_archive_count"))
        items.append(
            {
                "index": index,
                "name": card.get("name", ""),
                "display_name": card.get("display_name", card.get("name", "")),
                "source_path": card.get("source_path"),
                "suggested_type": card.get("suggested_type"),
                "confidence": card.get("confidence"),
                "needs_human_review": bool(card.get("needs_human_review")),
                "needs_translation": bool(card.get("pending_translation")),
                "needs_deep_analyze": needs_deep_analyze,
                "target_path": target_path,
                "target_exists": target_exists,
                "needs_create_target": needs_create_target,
                "move_status": "not_executed",
                "upload_status": "not_executed",
                "delete_source_status": "not_allowed",
                "reasons": card.get("reasons", [])[:6],
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "cards": len(cards),
            "needs_human_review": sum(1 for item in items if item["needs_human_review"]),
            "needs_deep_analyze": sum(1 for item in items if item["needs_deep_analyze"]),
            "needs_create_target": sum(1 for item in items if item["needs_create_target"]),
        },
        "safety": {
            "readonly": True,
            "moved_files": False,
            "deleted_files": False,
            "uploaded_to_115": False,
        },
        "items": items,
    }


def render_review_plan_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        "# 入库审阅计划",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 卡片数：{summary['cards']}",
        f"- 需人工确认：{summary['needs_human_review']}",
        f"- 建议深度分析：{summary['needs_deep_analyze']}",
        f"- 目标分类可能需新建：{summary['needs_create_target']}",
        "- 安全状态：只生成计划；没有移动、删除、上传。",
        "",
        "## 卡片计划",
        "",
    ]

    for item in payload["items"]:
        lines.append(f"### {item['index']}. {item['display_name']}")
        lines.append("")
        lines.append(f"- 来源：`{item.get('source_path') or ''}`")
        lines.append(f"- 建议类型：{item.get('suggested_type')}")
        lines.append(f"- 置信度：{item.get('confidence')}")
        lines.append(f"- 目标分类：`{item.get('target_path') or ''}`")
        if item["needs_create_target"]:
            lines.append("- 目标状态：可能需要新建分类。")
        elif item["target_exists"]:
            lines.append("- 目标状态：目标分类已存在。")
        if item["needs_deep_analyze"]:
            lines.append("- 建议：先做解压后深度分析。")
        if item["needs_translation"]:
            lines.append("- 建议：等待翻译命名。")
        if item["needs_human_review"]:
            lines.append("- 审阅状态：需要人工确认。")
        lines.append("- 执行状态：尚未移动、尚未上传、禁止删除源文件。")
        if item.get("reasons"):
            lines.append("- 判断原因：")
            for reason in item["reasons"]:
                lines.append(f"  - {reason}")
        lines.append("")
    return "\n".join(lines)


def _primary_target(card: dict) -> str:
    if card.get("user_target_path"):
        return str(card["user_target_path"])
    targets = card.get("target_path_hints") or []
    return str(targets[0]) if targets else ""
