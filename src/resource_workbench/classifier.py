from __future__ import annotations

from pathlib import Path


TYPE_TO_Z_HINTS = {
    "photo": ["Z 照片"],
    "model": ["M 模型"],
    "tutorial": ["J 教程"],
    "material": ["C 材质"],
    "ue": ["U UE"],
    "zbrush": ["Z zb brush"],
    "alpha": ["A Alphas"],
    "brush": ["B 笔刷"],
    "mixed": [],
    "unknown": [],
}


NAME_HINTS = {
    "photo": ["photo", "photopack", "reference", "ref", "照片", "摄影", "罗曼"],
    "model": ["model", "asset", "kit", "tree", "flower", "plant", "speedtree", "模型", "植物", "树", "花草"],
    "tutorial": ["tutorial", "course", "lesson", "mastery", "教程", "课程", "教学"],
    "material": ["material", "texture", "sbsar", "材质", "贴图"],
    "ue": ["unreal", "ue", "ue4", "ue5", "虚幻"],
    "zbrush": ["zbrush", "ztl", "zbrush", "雕刻"],
    "alpha": ["alpha", "阿尔法"],
    "brush": ["brush", "笔刷"],
}


def build_cards(scan: dict, z_root: Path | None = None) -> list[dict]:
    cards: list[dict] = []
    for group_name, group in scan.get("groups", {}).items():
        if group.get("total_files", 0) <= 0:
            continue
        cards.append(classify_group(group_name, group, z_root=z_root))
    return cards


def classify_group(group_name: str, group: dict, z_root: Path | None = None) -> dict:
    buckets = group.get("buckets", {})
    virtual_buckets = group.get("archive_virtual_buckets", {})
    combined_buckets = _merge_counts(buckets, virtual_buckets)
    total = max(1, group.get("total_files", 0) + sum(virtual_buckets.values()))
    entry_text = " ".join(group.get("archive_entry_samples", [])[:40])
    search_text = f"{group_name} {entry_text}".lower()

    scores = {
        "photo": 0,
        "model": 0,
        "tutorial": 0,
        "material": 0,
        "ue": 0,
        "zbrush": 0,
        "alpha": 0,
        "brush": 0,
    }
    reasons: list[str] = []

    image_count = combined_buckets.get("image", 0)
    video_count = combined_buckets.get("video", 0)
    document_count = combined_buckets.get("document", 0)
    model_count = combined_buckets.get("model", 0)
    engine_count = combined_buckets.get("engine", 0)
    zbrush_count = combined_buckets.get("zbrush", 0)
    archive_count = buckets.get("archive", 0)
    virtual_archive_count = virtual_buckets.get("archive", 0)
    texture_hits = group.get("texture_name_hits", 0)

    image_ratio = image_count / total
    if image_count >= 20 and image_ratio >= 0.65 and model_count == 0:
        scores["photo"] += 75
        reasons.append("大量图片且缺少模型工程文件，倾向照片/参考图。")
    elif image_count >= 8 and image_ratio >= 0.5:
        scores["photo"] += 45
        reasons.append("图片占比较高。")

    if model_count > 0:
        scores["model"] += min(90, 45 + model_count * 10)
        reasons.append("发现模型或 DCC 工程格式。")
    if image_count >= 5 and model_count > 0:
        scores["model"] += 15
        reasons.append("模型文件旁边存在贴图/预览图。")

    if video_count > 0:
        scores["tutorial"] += min(85, 45 + video_count * 8)
        reasons.append("发现视频文件，可能是教程。")
    if document_count >= 2 and video_count > 0:
        scores["tutorial"] += 15
        reasons.append("视频旁边有文档/字幕。")

    if texture_hits >= 6:
        scores["material"] += min(85, 35 + texture_hits * 4)
        reasons.append("文件名包含大量贴图通道关键词。")
    if ".sbsar" in group.get("extensions", {}) or ".sbs" in group.get("extensions", {}):
        scores["material"] += 85
        reasons.append("发现 Substance 材质文件。")

    if engine_count > 0:
        scores["ue"] += min(90, 55 + engine_count * 10)
        reasons.append("发现 UE/Unity 工程或资源格式。")

    if zbrush_count > 0:
        scores["zbrush"] += min(90, 55 + zbrush_count * 10)
        reasons.append("发现 ZBrush 格式。")

    for type_name, hints in NAME_HINTS.items():
        if any(hint in search_text for hint in hints):
            scores[type_name] += 25
            reasons.append(f"名称包含 {type_name} 相关关键词。")

    if any(phrase in search_text for phrase in ("photo pack", "photo packs", "photos of", "fotoref")):
        scores["photo"] += 45
        reasons.append("名称或压缩包目录明显指向照片包。")

    if any(phrase in search_text for phrase in ("3d model", "blend", "fbx", "obj", "mechanical", "robot", "sci-fi", "scifi", "kitbash")):
        scores["model"] += 45
        reasons.append("名称或压缩包目录明显指向模型资源。")

    if group.get("inspected_archives", 0) > 0:
        reasons.append("已读取压缩包目录用于判断，但没有解压。")

    if archive_count > 0:
        reasons.append("内部存在压缩包，需要判断是运输包还是资源内容包。")
    if virtual_archive_count > 0:
        reasons.append("压缩包内部还包含压缩包，可能需要后续递归解压或保留。")

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = sorted_scores[0]
    strong_types = [type_name for type_name, score in sorted_scores if score >= 55]

    if len(strong_types) >= 2:
        resource_type = "mixed"
        confidence = "low"
        reasons.append("同时命中多个强类型，建议拆分或人工确认。")
    elif top_score >= 75:
        resource_type = top_type
        confidence = "high"
    elif top_score >= 45:
        resource_type = top_type
        confidence = "medium"
    else:
        resource_type = "unknown"
        confidence = "low"
        reasons.append("现有规则无法稳定判断类型。")

    target_hints = TYPE_TO_Z_HINTS.get(resource_type, [])
    target_paths = []
    if z_root is not None:
        for hint in target_hints:
            target_paths.append(str(z_root / hint))
    else:
        target_paths = target_hints

    return {
        "name": group_name,
        "suggested_type": resource_type,
        "confidence": confidence,
        "scores": scores,
        "target_path_hints": target_paths,
        "needs_human_review": confidence == "low" or resource_type == "mixed" or archive_count > 0,
        "archive_count": archive_count,
        "inspected_archives": group.get("inspected_archives", 0),
        "virtual_archive_count": virtual_archive_count,
        "total_files": group.get("total_files", 0),
        "total_dirs": group.get("total_dirs", 0),
        "total_bytes": group.get("total_bytes", 0),
        "buckets": buckets,
        "archive_virtual_buckets": virtual_buckets,
        "top_extensions": dict(list(group.get("extensions", {}).items())[:12]),
        "top_archive_extensions": dict(list(group.get("archive_virtual_extensions", {}).items())[:12]),
        "samples": group.get("samples", {}),
        "archive_entry_samples": group.get("archive_entry_samples", []),
        "archive_previews": group.get("archive_previews", []),
        "candidate_subresources": dict(list(group.get("archive_candidate_roots", {}).items())[:30]),
        "possible_split_count": _possible_split_count(group),
        "reasons": reasons[:12],
    }


def _merge_counts(*dicts: dict) -> dict:
    merged: dict[str, int] = {}
    for source in dicts:
        for key, value in source.items():
            merged[key] = merged.get(key, 0) + int(value)
    return merged


def _possible_split_count(group: dict) -> int:
    candidates = group.get("archive_candidate_roots", {})
    return len([name for name, count in candidates.items() if count >= 2 and len(name) >= 4])
