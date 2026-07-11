from __future__ import annotations

from pathlib import Path
import re

from .taxonomy import describe_content, suggest_target_paths


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
    resource_browser_mode = _is_library_scan(scan, z_root)
    allow_archive_subresource_split = bool(scan.get("split_archive_subresources", False))
    input_context = Path(scan.get("input_path", "")).name if scan.get("input_path") else ""
    groups = scan.get("groups", {})
    covered_tops: set[str] = set()
    expected_tops = _expected_top_level_directories(scan)
    enforce_top_level_coverage = (
        bool(expected_tops)
        and scan.get("kind") == "directory"
        and scan.get("resource_root_depth") != 0
    )
    for group_name, group in groups.items():
        if group.get("total_files", 0) <= 0:
            continue
        if _should_skip_wrapper_group(group_name, group, groups):
            continue
        context_text = input_context
        if group_name != "(根目录文件)":
            group["display_name"] = group.get("display_name") or _last_path_part(group_name)
        if resource_browser_mode:
            group["is_library_card"] = True
            if group.get("absolute_path"):
                group_path = Path(group["absolute_path"])
                group["library_target_path"] = str(group_path.parent)
        top = _top_prefix(group_name)
        if not resource_browser_mode and _should_split_group(
            group,
            allow_archive_subresources=allow_archive_subresource_split,
        ):
            for sub_name, subresource in _sorted_subresources(group):
                sub_group = _subresource_to_group(group_name, subresource)
                card = classify_group(sub_name, sub_group, z_root=z_root, context_text=group_name)
                if top:
                    card["source_top_level"] = top
                cards.append(card)
            if top:
                covered_tops.add(top)
            continue
        card = classify_group(group_name, group, z_root=z_root, context_text=context_text)
        if top:
            card["source_top_level"] = top
        cards.append(card)
        if top:
            covered_tops.add(top)

    # 安全网：保证扫描根目录下每个“顶层资源文件夹”至少生成一张卡片。
    # 无论包装层跳过、拆分异常还是其它边界情况，都不允许整个资源被静默丢掉。
    _ensure_top_level_coverage(
        scan,
        cards,
        covered_tops,
        resource_browser_mode,
        z_root,
        input_context,
        expected_tops if enforce_top_level_coverage and not scan.get("stopped_early") else [],
    )

    expected_keys = {_top_key(item["name"]): item["name"] for item in expected_tops}
    card_keys = {
        _top_key(card.get("source_top_level"))
        for card in cards
        if card.get("source_top_level")
    }
    missing = [name for key, name in expected_keys.items() if key not in card_keys]
    scan["top_level_directory_count"] = len(expected_tops) or int(scan.get("top_level_directory_count", 0) or 0)
    scan["top_level_card_count"] = sum(1 for key in expected_keys if key in card_keys)
    scan["missing_top_level_directories"] = missing
    scan["top_level_card_invariant_applied"] = enforce_top_level_coverage
    if missing and enforce_top_level_coverage and not scan.get("stopped_early"):
        scan.setdefault("warnings", []).append(
            "首层资源卡片校验未通过，缺少：" + "、".join(missing)
        )
    return cards


def _top_prefix(group_name: str) -> str | None:
    if not group_name or group_name == "(根目录文件)":
        return None
    parts = [p for p in re.split(r"[\\/]+", group_name) if p]
    return parts[0] if parts else None


def _top_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _expected_top_level_directories(scan: dict) -> list[dict[str, str]]:
    """Return the scanner's stable first-level folder snapshot.

    Older reports do not contain this field, so callers must continue to work
    with an empty list and fall back to group-derived coverage.
    """
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in scan.get("top_level_directories") or []:
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            path = str(raw.get("path") or "").strip()
        else:
            name = str(raw or "").strip()
            path = str(Path(scan.get("input_path") or "") / name) if name else ""
        key = _top_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        items.append({"name": name, "path": path})
    return items


def _new_aggregate(top: str, input_root: str) -> dict:
    absolute = str(Path(input_root) / top) if input_root else None
    return {
        "path": top,
        "display_name": _last_path_part(top),
        "absolute_path": absolute,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": {},
        "extensions": {},
        "archive_virtual_buckets": {},
        "archive_virtual_extensions": {},
        "archives": [],
        "source_archives": [],
        "inspected_archives": 0,
        "image_candidates": [],
        "video_candidates": [],
        "samples": {},
        "archive_previews": [],
        "archive_entry_samples": [],
        "archive_candidate_roots": {},
        "archive_subresources": {},
        "texture_name_hits": 0,
    }


def _merge_into_aggregate(agg: dict, group: dict) -> None:
    agg["total_files"] += int(group.get("total_files", 0))
    agg["total_dirs"] += int(group.get("total_dirs", 0))
    agg["total_bytes"] += int(group.get("total_bytes", 0))
    agg["inspected_archives"] += int(group.get("inspected_archives", 0))
    agg["texture_name_hits"] += int(group.get("texture_name_hits", 0))
    agg["buckets"] = _merge_counts(agg["buckets"], group.get("buckets", {}))
    agg["extensions"] = _merge_counts(agg["extensions"], group.get("extensions", {}))
    agg["archive_virtual_buckets"] = _merge_counts(agg["archive_virtual_buckets"], group.get("archive_virtual_buckets", {}))
    agg["archive_virtual_extensions"] = _merge_counts(agg["archive_virtual_extensions"], group.get("archive_virtual_extensions", {}))
    agg["archive_candidate_roots"] = _merge_counts(agg["archive_candidate_roots"], group.get("archive_candidate_roots", {}))
    for key in ("image_candidates", "video_candidates", "archive_entry_samples", "archive_previews", "archives", "source_archives"):
        items = group.get(key) or []
        if items:
            agg[key].extend(items)
    samples = group.get("samples") or {}
    if isinstance(samples, dict):
        for bucket, paths in samples.items():
            agg["samples"].setdefault(bucket, []).extend(paths or [])


def _ensure_top_level_coverage(
    scan: dict,
    cards: list[dict],
    covered_tops: set[str],
    resource_browser_mode: bool,
    z_root: Path | None,
    input_context: str,
    expected_tops: list[dict[str, str]] | None = None,
) -> None:
    input_root = scan.get("input_path") or ""
    groups = scan.get("groups", {})
    expected_tops = list(expected_tops or [])
    expected_keys = {_top_key(item["name"]) for item in expected_tops}
    covered_keys = {_top_key(top) for top in covered_tops}
    aggregates: dict[str, tuple[str, dict]] = {}
    order: list[str] = []

    # Seed the aggregate list from the root snapshot first.  This is what
    # recovers an empty or temporarily unreadable first-level folder: groups
    # alone cannot represent content that was never readable.
    for item in expected_tops:
        top = item["name"]
        key = _top_key(top)
        if not key or key in covered_keys or key in aggregates:
            continue
        aggregate = _new_aggregate(top, input_root)
        if item.get("path"):
            aggregate["absolute_path"] = item["path"]
        aggregates[key] = (top, aggregate)
        order.append(key)

    for group_name, group in groups.items():
        top = _top_prefix(group_name)
        key = _top_key(top)
        if not top or key in covered_keys:
            continue
        has_content = int(group.get("total_files", 0)) > 0 or bool(group.get("archive_virtual_buckets")) or bool(group.get("archive_subresources"))
        if not has_content and key not in expected_keys:
            continue
        if key not in aggregates:
            aggregates[key] = (top, _new_aggregate(top, input_root))
            order.append(key)
        _merge_into_aggregate(aggregates[key][1], group)
    for key in order:
        top, agg = aggregates[key]
        if (
            int(agg.get("total_files", 0)) <= 0
            and not agg.get("archive_virtual_buckets")
            and key not in expected_keys
        ):
            continue
        if resource_browser_mode:
            agg["is_library_card"] = True
            if agg.get("absolute_path"):
                agg["library_target_path"] = str(Path(agg["absolute_path"]).parent)
        card = classify_group(top, agg, z_root=z_root, context_text=input_context)
        card["recovered_card"] = True
        card["needs_human_review"] = True
        card["source_top_level"] = top
        if int(agg.get("total_files", 0)) <= 0 and not agg.get("archive_virtual_buckets"):
            recovery_reason = "首层目录兜底卡：已检测到文件夹，但没有读到可分类文件；可能为空目录或暂时无法读取，请人工检查。"
        else:
            recovery_reason = "自动兜底卡：此资源未被正常拆分，已用聚合内容生成；建议深度分析核对边界。"
        card["reasons"] = [recovery_reason] + list(card.get("reasons") or [])
        tags = list(card.get("content_tags") or [])
        if "兜底卡" not in tags:
            tags.insert(0, "兜底卡")
        card["content_tags"] = tags
        cards.append(card)
        covered_tops.add(top)
        covered_keys.add(key)


def _is_library_scan(scan: dict, z_root: Path | None) -> bool:
    if "library_browser_mode" in scan:
        return bool(scan.get("library_browser_mode"))
    if z_root is None:
        return False
    input_text = scan.get("input_path")
    if not input_text:
        return False
    try:
        Path(input_text).resolve().relative_to(z_root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _last_path_part(path_text: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", path_text) if part]
    return parts[-1] if parts else path_text


def _should_skip_wrapper_group(group_name: str, group: dict, groups: dict) -> bool:
    if group_name == "(根目录文件)":
        return False
    if int(group.get("total_files", 0)) > 1:
        return False
    prefix = f"{group_name}\\"
    alt_prefix = f"{group_name}/"
    has_deeper_group = any(
        (name.startswith(prefix) or name.startswith(alt_prefix)) and _group_has_content(deeper)
        for name, deeper in groups.items()
        if name != group_name
    )
    if not has_deeper_group:
        return False
    return True


def _group_has_content(group: dict) -> bool:
    return (
        int(group.get("total_files", 0) or 0) > 0
        or bool(group.get("archive_virtual_buckets"))
        or bool(group.get("archive_subresources"))
    )


def classify_group(group_name: str, group: dict, z_root: Path | None = None, context_text: str = "") -> dict:
    buckets = group.get("buckets", {})
    virtual_buckets = group.get("archive_virtual_buckets", {})
    combined_buckets = _merge_counts(buckets, virtual_buckets)
    total = max(1, group.get("total_files", 0) + sum(virtual_buckets.values()))
    entry_text = " ".join(group.get("archive_entry_samples", [])[:40])
    disk_sample_names: list[str] = []
    samples = group.get("samples") or {}
    if isinstance(samples, dict):
        for paths in samples.values():
            for path in paths or []:
                name = Path(str(path)).name
                if not _is_generic_sample_name(name):
                    disk_sample_names.append(name)
    archive_names = [
        Path(str(item.get("relative_path") or item.get("absolute_path") or "")).name
        for item in (group.get("archives") or [])
        if isinstance(item, dict)
    ]
    sample_text = " ".join([*disk_sample_names[:40], *archive_names[:20]])
    search_text = f"{context_text} {group_name} {sample_text} {entry_text}".lower()

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
    if video_count >= 2 and model_count == 0 and engine_count == 0 and zbrush_count == 0:
        scores["tutorial"] += 35
        reasons.append("视频是主要内容，倾向教程/课程。")
    if video_count > 0 and any(hint in search_text for hint in ("教程", "课程", "教学", "讲座", "网课", "lesson", "tutorial", "course")):
        scores["tutorial"] += 35
        reasons.append("路径或名称带教程语境，并发现视频内容。")
    if document_count >= 2 and video_count > 0:
        scores["tutorial"] += 15
        reasons.append("视频旁边有文档/字幕。")

    asset_video_terms = (
        "3d model",
        "model",
        "asset",
        "kitbash",
        "sci-fi",
        "scifi",
        "sci fi",
        "parts",
        "prop",
        "props",
        "trim sheet",
        "fbx",
        "obj",
        "blend",
    )
    if video_count > 0 and any(term in search_text for term in asset_video_terms) and not any(
        term in search_text for term in ("tutorial", "course", "lesson", "教程", "课程", "教学")
    ):
        scores["model"] += 40
        scores["tutorial"] = max(0, scores["tutorial"] - 30)
        reasons.append("视频更像资产预览而不是教程，结合名称优先按模型资源判断。")

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

    if group.get("is_library_card") and "j 教程" in search_text:
        resource_type = "tutorial"
        confidence = "high" if video_count > 0 or image_count > 0 or archive_count > 0 else "medium"
        reasons.append("当前位于 J 教程资源库，优先尊重已入库分类，不按内部工程文件改判为模型或UE。")
    elif group.get("is_library_card") and video_count > 0:
        resource_type = "tutorial"
        confidence = "high" if video_count >= 2 else "medium"
        reasons.append("当前是已入库资源库浏览，保留资源文件夹整体，不拆内部工程目录。")
    elif len(strong_types) >= 2:
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

    target_suggestions = suggest_target_paths(
        resource_type,
        search_text,
        z_root,
        name_text=group_name,
    )
    target_paths = [item["path"] for item in target_suggestions]
    if group.get("library_target_path"):
        library_target = group["library_target_path"]
        target_paths = [library_target, *[path for path in target_paths if path != library_target]]
    if not target_paths:
        target_hints = TYPE_TO_Z_HINTS.get(resource_type, [])
        if z_root is not None:
            for hint in target_hints:
                target_paths.append(str(z_root / hint))
        else:
            target_paths = target_hints

    return {
        "name": group_name,
        "display_name": group.get("display_name", group_name),
        "source_path": group.get("absolute_path"),
        "is_library_card": bool(group.get("is_library_card")),
        "library_target_path": group.get("library_target_path"),
        "split_from": group.get("split_from"),
        "is_split_card": bool(group.get("is_split_card")),
        "suggested_type": resource_type,
        "confidence": confidence,
        "content_tags": describe_content(resource_type, search_text),
        "scores": scores,
        "target_suggestions": target_suggestions,
        "target_path_hints": target_paths,
        "needs_human_review": confidence == "low" or resource_type == "mixed" or archive_count > 0,
        "archive_count": archive_count,
        "source_archive_count": len(group.get("source_archives", [])),
        "source_archives": group.get("source_archives", []),
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
        "preview_source": _preview_source(group),
        "reasons": reasons[:12],
    }


def _is_generic_sample_name(name: str) -> bool:
    stem = Path(str(name or "")).stem.lower().strip()
    stem = re.sub(r"[\s_\-()\d]+", "", stem)
    return stem in {
        "",
        "file",
        "image",
        "img",
        "preview",
        "render",
        "scene",
        "asset",
        "assets",
        "lp",
        "hp",
        "lowpoly",
        "highpoly",
        "thumbs",
        "defaultnormalsmap",
    }


def _merge_counts(*dicts: dict) -> dict:
    merged: dict[str, int] = {}
    for source in dicts:
        for key, value in source.items():
            merged[key] = merged.get(key, 0) + int(value)
    return merged


def _possible_split_count(group: dict) -> int:
    candidates = _split_candidate_names(group)
    return len(candidates) if len(candidates) >= 2 else 0


def _should_split_group(group: dict, *, allow_archive_subresources: bool = False) -> bool:
    if not allow_archive_subresources:
        return False
    subresources = group.get("archive_subresources") or {}
    useful = [
        sub
        for name, sub in subresources.items()
        if _is_useful_subresource(sub, fallback_name=name)
    ]
    return len(useful) >= 3


def _sorted_subresources(group: dict) -> list[tuple[str, dict]]:
    subresources = group.get("archive_subresources") or {}
    items = [
        (name, sub)
        for name, sub in subresources.items()
        if _is_useful_subresource(sub, fallback_name=name)
    ]
    return sorted(items, key=lambda item: (-item[1].get("total_entries", 0), item[0].lower()))


def _split_candidate_names(group: dict) -> list[str]:
    candidates = group.get("archive_candidate_roots", {}) or {}
    return [
        name
        for name, count in candidates.items()
        if count >= 2 and len(str(name)) >= 4
    ]


_TECHNICAL_SUBRESOURCE_TOKENS = {
    "textures", "texture", "tex", "maps", "map", "materials", "material", "mats", "mat",
    "basecolor", "basecolour", "albedo", "diffuse", "normal", "normals", "nrm", "roughness", "rough", "rgh",
    "metallic", "metalness", "specular", "spec", "gloss", "glossiness", "ao", "ambientocclusion",
    "height", "displacement", "disp", "bump", "opacity", "transparency", "emissive", "emission",
    "mask", "masks", "cavity", "curvature", "subsurface", "sss", "orm", "arm", "pbr", "channel", "channels",
    "source", "sources", "sourcefiles", "preview", "previews", "render", "renders", "thumbnail", "thumbnails",
    "fbx", "obj", "blend", "blender", "max", "3dsmax", "3ds", "c4d", "maya", "marmoset", "toolbag",
    "ue", "ue4", "ue5", "unity", "gltf", "glb", "usd", "usdz", "stl", "abc", "1k", "2k", "4k", "8k", "16k",
}
_TECHNICAL_SUBRESOURCE_FILLERS = {"and", "with", "plus", "amp", "the", "for", "of", "in", "only", "files", "file", "a", "to", "set"}
_TECHNICAL_SUBRESOURCE_CHINESE = {
    "贴图", "贴图文件", "纹理", "材质", "材质贴图", "法线", "法线贴图", "粗糙度", "金属度",
    "置换", "置换贴图", "高度图", "遮罩", "透明度", "预览", "预览图", "渲染", "渲染图", "源文件",
}


def _is_technical_subresource_name(name: str) -> bool:
    raw = str(name).strip().lower()
    if not raw:
        return False
    if raw in _TECHNICAL_SUBRESOURCE_CHINESE:
        return True
    if any("\u4e00" <= char <= "\u9fff" for char in raw):
        return False
    words = [word for word in re.split(r"[^0-9a-z]+", raw) if word]
    return bool(words) and any(word in _TECHNICAL_SUBRESOURCE_TOKENS for word in words) and all(
        word in _TECHNICAL_SUBRESOURCE_TOKENS or word in _TECHNICAL_SUBRESOURCE_FILLERS
        for word in words
    )


def _is_useful_subresource(subresource: dict, fallback_name: str = "") -> bool:
    name = str(subresource.get("name") or fallback_name)
    if _is_technical_subresource_name(name):
        return False
    buckets = subresource.get("buckets") or {}
    has_resource_payload = any(int(buckets.get(bucket, 0) or 0) > 0 for bucket in ("model", "image", "archive", "material", "ue", "zbrush", "alpha", "brush"))
    return int(subresource.get("total_entries", 0) or 0) >= 2 and has_resource_payload


def _subresource_to_group(parent_name: str, subresource: dict) -> dict:
    return {
        "path": f"{parent_name}\\{subresource.get('name', '')}",
        "display_name": subresource.get("name", ""),
        "split_from": parent_name,
        "is_split_card": True,
        "total_files": 0,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": {},
        "extensions": {},
        "archives": [],
        "source_archives": subresource.get("source_archives", []),
        "inspected_archives": len(subresource.get("source_archives", [])),
        "samples": {},
        "archive_previews": [],
        "archive_virtual_buckets": subresource.get("buckets", {}),
        "archive_virtual_extensions": subresource.get("extensions", {}),
        "archive_entry_samples": subresource.get("samples", []),
        "archive_candidate_roots": {},
        "archive_subresources": {},
        "image_candidates": [],
        "archive_image_candidates": subresource.get("image_samples", []),
        "texture_name_hits": subresource.get("texture_name_hits", 0),
    }


def _preview_source(group: dict) -> dict | None:
    image_candidates = group.get("image_candidates") or []
    if image_candidates:
        best_image = _best_preview_path(image_candidates)
        return {
            "kind": "file",
            "path": best_image,
        }
    archive_images = group.get("archive_image_candidates") or []
    if archive_images:
        first = _best_archive_preview(archive_images)
        return {
            "kind": "archive_entry",
            "archive_path": first.get("archive_path"),
            "entry_path": first.get("entry_path"),
        }
    for preview in group.get("archive_previews", []) or []:
        # Older whole-resource cards may not have archive_image_candidates.
        for sample in preview.get("samples", []) or []:
            lower = sample.lower()
            if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                return {
                    "kind": "archive_entry",
                    "archive_path": preview.get("absolute_path"),
                    "entry_path": sample,
                }
    video_candidates = group.get("video_candidates") or []
    if video_candidates:
        return {
            "kind": "video_file",
            "path": video_candidates[0],
        }
    return None


def _best_preview_path(paths: list[str]) -> str:
    # 排序优先级：名称分 > 路径越浅越好（封面常在资源根） > 文件大小（hero 图通常更大） > 稳定性。
    def key(path_text: str):
        depth = len([seg for seg in str(path_text).replace("\\", "/").split("/") if seg])
        return (_preview_name_score(path_text), -depth, _file_size_safe(path_text), path_text)

    return max(paths, key=key)


def _best_archive_preview(items: list[dict]) -> dict:
    return max(items, key=lambda item: _preview_name_score(str(item.get("entry_path", ""))))


def _file_size_safe(path_text: str) -> int:
    try:
        return Path(path_text).stat().st_size
    except OSError:
        return 0


# 像“渲染图 / 封面 / 成品图”的命名线索（加分）
_PREVIEW_GOOD_HINTS = (
    "cover", "preview", "thumb", "thumbnail", "render", "screenshot", "poster",
    "main", "beauty", "scene", "hero", "final", "result", "showcase", "promo",
    "display", "turntable", "wire", "title", "key", "view", "persp", "front",
)
# 像“贴图通道 / 图标 / 水印”的命名线索（强烈减分，避免把法线/粗糙度等当封面）
_PREVIEW_BAD_HINTS = (
    "normal", "_nrm", "roughness", "_rgh", "_rough", "metallic", "_met", "metal",
    "specular", "_spec", "glossiness", "gloss", "opacity", "height", "_disp",
    "displacement", "bump", "_bump", "basecolor", "base_color", "albedo",
    "diffuse", "_col", "emissive", "_emi", "_ao", "ambientocclusion", "orm",
    "_arm", "cavity", "curvature", "subsurface", "_sss", "_id", "_msk", "mask",
    "alpha", "opacitymask", "logo", "icon", "watermark", "qr", "uv_", "_uv",
    "atlas", "lightmap",
)


# 贴图/源文件常驻的文件夹（封面几乎不会放这里）
_PREVIEW_BAD_FOLDERS = {
    "textures", "texture", "tex", "maps", "map", "source", "sourceimages",
    "src", "material", "materials", "mat", "cache", "backup", "raw", "psd",
}
# 成品图/封面常驻的文件夹
_PREVIEW_GOOD_FOLDERS = {
    "preview", "previews", "render", "renders", "cover", "covers",
    "screenshot", "screenshots", "promo", "showcase", "thumbnail", "thumbnails",
}


def _preview_name_score(path_text: str) -> int:
    full = str(path_text).replace("\\", "/").lower()
    parts = [seg for seg in full.split("/") if seg]
    lower = (parts[-1] if parts else full)
    folders = parts[:-1]
    score = 0
    for hint in _PREVIEW_GOOD_HINTS:
        if hint in lower:
            score += 20
    for bad in _PREVIEW_BAD_HINTS:
        if bad in lower:
            score -= 35
    # 所在文件夹线索：贴图/源文件夹降权，成品/封面文件夹加权
    if any(seg in _PREVIEW_BAD_FOLDERS for seg in folders):
        score -= 22
    if any(seg in _PREVIEW_GOOD_FOLDERS for seg in folders):
        score += 14
    if "file" in lower:  # file.jpg 这类包装图：弱加分，仅在没有更好选择时兜底
        score += 5
    if lower.startswith(("cover", "preview", "render", "main", "scene", "hero")):
        score += 14
    if any(token in lower for token in ("000", "001", "_01", "-01", "_1.", "-1.")):
        score += 4
    return score
