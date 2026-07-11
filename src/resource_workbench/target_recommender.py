"""目标文件夹推荐引擎。

解决“移动时被丢到一个总文件夹、还要自己一层层找”的问题：
根据卡片的建议分类（target_path_hints / user_target_path）和资源库真实目录树，
推荐若干个最近似的【现有】子文件夹，让用户像 Pinterest 选收藏夹一样直接挑一个，
而不是从根目录手动翻。

只读目录，不移动、不创建任何文件夹。
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from math import log2
from pathlib import Path

from .move_log import MoveLog, build_card_learning_features


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(text or "")).strip().lower()


def _tokens(text: str) -> set[str]:
    text = _norm(text)
    parts = re.split(r"[\s/\\,.，、;；]+", text)
    return {p for p in parts if len(p) >= 2}


def primary_target_relative_parts(card: dict, resource_root: Path) -> list[str]:
    """从卡片建议目标里取出相对资源库根的路径片段。"""
    target = str(card.get("user_target_path") or "")
    if not target:
        hints = card.get("target_path_hints") or []
        target = str(hints[0]) if hints else ""
    if not target:
        return []
    target_norm = target.replace("/", "\\")
    root_norm = str(resource_root).replace("/", "\\").rstrip("\\")
    root_name = Path(str(resource_root)).name
    parts = [p for p in target_norm.split("\\") if p and not p.endswith(":")]
    # 去掉资源库根前缀
    if root_norm and target_norm.lower().startswith(root_norm.lower()):
        rel = target_norm[len(root_norm):]
        return [p for p in rel.split("\\") if p]
    if root_name in parts:
        return parts[parts.index(root_name) + 1:]
    return parts


def _deepest_existing_base(resource_root: Path, parts: list[str]) -> tuple[Path, int]:
    """沿建议路径向下走，返回最深的【已存在】目录以及命中了几层。"""
    base = Path(resource_root)
    matched = 0
    for part in parts:
        candidate = base / part
        if candidate.is_dir():
            base = candidate
            matched += 1
        else:
            break
    return base, matched


def _list_subdirs(path: Path, limit: int = 400) -> list[Path]:
    try:
        items = []
        for child in path.iterdir():
            if child.is_dir() and not child.name.startswith(".") and child.name not in {"$RECYCLE.BIN", "System Volume Information"}:
                items.append(child)
                if len(items) >= limit:
                    break
        return items
    except OSError:
        return []


def _score_folder(folder_name: str, query_tokens: set[str], query_text: str, leaf_hint: str) -> float:
    name_norm = _norm(folder_name)
    name_tokens = _tokens(folder_name)
    score = 0.0
    # 词重叠
    if query_tokens and name_tokens:
        overlap = query_tokens & name_tokens
        score += 3.0 * len(overlap)
    # 子串包含（中英文都管用）
    for tok in query_tokens:
        if tok and tok in name_norm:
            score += 1.5
    # 整体相似度
    score += 2.0 * SequenceMatcher(None, query_text, name_norm).ratio()
    # 与建议路径叶子名相似
    if leaf_hint:
        score += 2.5 * SequenceMatcher(None, _norm(leaf_hint), name_norm).ratio()
    return round(score, 4)


def recommend_target_folders(
    card: dict,
    resource_root: Path,
    max_results: int = 12,
    *,
    move_log: MoveLog | None = None,
    history_limit: int = 2000,
) -> dict:
    """返回推荐结果。

    {
      "ok": True,
      "base": <用于浏览的起点目录>,
      "base_relative": <相对资源库根>,
      "matched_depth": <建议路径命中层数>,
      "hint_parts": [...],
      "suggested_new": <建议新建的完整路径或 None>,
      "candidates": [
         {"path","name","relative","score","exists": True, "is_hint_leaf": bool}
      ]
    }
    候选都是【现有文件夹】，按相近度排序；若建议叶子目录不存在，另给 suggested_new。
    """
    resource_root = Path(resource_root)
    if not resource_root.exists():
        return {"ok": False, "error": f"资源库根目录不存在：{resource_root}", "candidates": []}

    parts = primary_target_relative_parts(card, resource_root)
    base, matched = _deepest_existing_base(resource_root, parts)
    leaf_hint = parts[-1] if parts else ""
    fully_matched = matched == len(parts) and len(parts) > 0

    # 浏览起点：若命中的就是一个没有子目录的叶子，退回父级，好让用户看到兄弟分类来改投。
    subdirs_here = _list_subdirs(base)
    if (not subdirs_here or _mostly_asset_folders(subdirs_here)) and Path(base) != Path(resource_root):
        parent = Path(base).parent
        if _within_or_equal(parent, resource_root):
            base = parent

    query_text = _expand_synonyms(
        _norm(
            " ".join(
                [
                    str(card.get("display_name") or ""),
                    str(card.get("name") or ""),
                    str(card.get("suggested_type") or ""),
                    " ".join(card.get("content_tags") or []),
                    " ".join(card.get("reasons") or []),
                    " ".join(card.get("archive_entry_samples") or []),
                    leaf_hint,
                ]
            )
        )
    )
    query_tokens = _tokens(query_text)

    # 候选：浏览起点下的现有子目录。
    subdirs = _list_subdirs(base)
    scored: list[dict] = []
    for child in subdirs:
        scored.append(
            {
                "path": str(child),
                "name": child.name,
                "relative": _relative_to_root(child, resource_root),
                "score": _score_folder(child.name, query_tokens, query_text, leaf_hint),
                "exists": True,
                "is_hint_leaf": _norm(child.name) == _norm(leaf_hint),
                "is_history_match": False,
                "history_count": 0,
                "history_score": 0.0,
            }
        )

    # 用户每次成功移动都会留下“卡片特征 -> 目标分类”的结构化样本。
    # 学习候选可以跨出当前规则提示的母路径，但必须仍是资源库内真实存在的目录。
    history_candidates, history_examples_used = _history_target_candidates(
        card,
        resource_root,
        move_log,
        limit=history_limit,
    )
    by_path = {_path_key(item["path"]): item for item in scored}
    for learned in history_candidates:
        key = _path_key(learned["path"])
        existing = by_path.get(key)
        if existing is None:
            folder = Path(learned["path"])
            existing = {
                "path": str(folder),
                "name": folder.name,
                "relative": _relative_to_root(folder, resource_root),
                "score": _score_folder(folder.name, query_tokens, query_text, leaf_hint),
                "exists": True,
                "is_hint_leaf": _norm(folder.name) == _norm(leaf_hint),
                "is_history_match": True,
                "history_count": 0,
                "history_score": 0.0,
            }
            scored.append(existing)
            by_path[key] = existing
        existing["is_history_match"] = True
        existing["history_count"] = int(learned["history_count"])
        existing["history_score"] = float(learned["history_score"])
        existing["score"] = round(float(existing["score"]) + float(learned["history_score"]), 4)
    scored.sort(key=lambda item: (-item["score"], item["name"].lower()))

    suggested_new = None
    if parts and not fully_matched:
        # 建议路径里还有没创建的层级 -> 给一个“新建”建议路径。
        suggested_new = str(Path(resource_root, *parts))

    return {
        "ok": True,
        "base": str(base),
        "base_relative": _relative_to_root(base, resource_root) or "资源库根目录",
        "matched_depth": matched,
        "hint_parts": parts,
        "suggested_new": suggested_new,
        "history_examples_used": history_examples_used,
        "candidates": scored[:max_results],
    }


def apply_history_target_suggestions(
    card: dict,
    resource_root: Path,
    history_records: list[dict],
    *,
    max_history_results: int = 3,
    max_total_results: int = 5,
) -> int:
    """Merge learned, already-confirmed target folders into an analyzed card.

    Rule-based semantic paths keep a higher ceiling (the taxonomy uses 125 for
    a precise match).  A strong history match scores around 100, so it can beat
    the broad ``M 模型`` fallback without overriding a clear current signal.
    """
    root = Path(resource_root)
    if not root.exists() or not history_records:
        return 0
    learned, examples_used = _history_target_candidates_from_records(
        card,
        root,
        history_records,
    )
    if not learned:
        card["history_examples_used"] = 0
        return 0

    existing = [dict(item) for item in (card.get("target_suggestions") or []) if item.get("path")]
    by_path = {_path_key(item["path"]): item for item in existing}
    added = 0
    for item in learned[: max(0, int(max_history_results))]:
        path = str(item["path"])
        score = min(114.0, 96.0 + float(item.get("history_score") or 0.0))
        reason = f"根据 {int(item.get('history_count') or 0)} 次相似资源的已确认移动路径推荐。"
        key = _path_key(path)
        current = by_path.get(key)
        if current is None:
            current = {
                "path": path,
                "score": round(score, 3),
                "reason": reason,
                "history_learned": True,
                "history_count": int(item.get("history_count") or 0),
            }
            existing.append(current)
            by_path[key] = current
            added += 1
        else:
            current["history_learned"] = True
            current["history_count"] = int(item.get("history_count") or 0)
            if score > float(current.get("score") or 0.0):
                current["score"] = round(score, 3)
                current["reason"] = reason

    existing.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("path") or "").lower()))
    existing = existing[: max(1, int(max_total_results))]
    card["target_suggestions"] = existing
    card["target_path_hints"] = [str(item["path"]) for item in existing]
    card["history_examples_used"] = examples_used
    return added


def prepare_history_records(records: list[dict], resource_root: Path) -> list[dict]:
    """Canonicalize historical UNC/mapped-drive targets once per analysis batch.

    Formal moves may store a NAS UNC path while settings use ``Z:``.  Returning
    paths under the configured root keeps the UI consistent and avoids doing a
    network ``is_dir`` check for every card × every history row.
    """
    root = Path(resource_root)
    mapped_cache: dict[str, Path | None] = {}
    prepared: list[dict] = []
    for record in records:
        target_text = str(record.get("target_directory") or "").strip()
        if not target_text:
            continue
        cache_key = target_text.rstrip("\\/").casefold()
        if cache_key not in mapped_cache:
            mapped_cache[cache_key] = _target_under_configured_root(Path(target_text), root)
        target = mapped_cache[cache_key]
        if target is None:
            continue
        item = dict(record)
        item["target_directory"] = str(target)
        item["_target_prepared"] = True
        prepared.append(item)
    return prepared


def _history_target_candidates(
    card: dict,
    resource_root: Path,
    move_log: MoveLog | None,
    *,
    limit: int,
) -> tuple[list[dict], int]:
    if move_log is None:
        return [], 0
    try:
        records = move_log.learning_records(limit=limit)
    except (OSError, ValueError):
        return [], 0

    return _history_target_candidates_from_records(card, resource_root, records)


def _history_target_candidates_from_records(
    card: dict,
    resource_root: Path,
    records: list[dict],
) -> tuple[list[dict], int]:

    current = build_card_learning_features(card)
    aggregated: dict[str, dict] = defaultdict(
        lambda: {"path": "", "similarities": [], "history_count": 0}
    )
    used = 0
    root = Path(resource_root)
    for record in records:
        target_text = str(record.get("target_directory") or "").strip()
        if not target_text:
            continue
        target = (
            Path(target_text)
            if record.get("_target_prepared")
            else _target_under_configured_root(Path(target_text), root)
        )
        if target is None:
            continue
        similarity = _learning_similarity(current, record.get("card_features") or {})
        # 单纯同为“模型/照片”不够具体；至少要有名称/标签/扩展等共同线索。
        if similarity < 0.28:
            continue
        key = _path_key(target)
        bucket = aggregated[key]
        bucket["path"] = str(target)
        bucket["similarities"].append(similarity)
        bucket["history_count"] += 1
        used += 1

    candidates: list[dict] = []
    for bucket in aggregated.values():
        similarities = bucket.pop("similarities")
        count = int(bucket["history_count"])
        average = sum(similarities) / max(1, count)
        strongest = max(similarities)
        # 历史命中足以改变排序，但做上限，避免大量旧样本永久压住当前明确规则。
        boost = min(14.0, 2.0 + strongest * 8.0 + average * 3.0 + log2(count + 1))
        bucket["history_score"] = round(boost, 4)
        candidates.append(bucket)
    candidates.sort(
        key=lambda item: (-float(item["history_score"]), -int(item["history_count"]), item["path"].lower())
    )
    return candidates, used


def _learning_similarity(current: dict, previous: dict) -> float:
    current_keywords = set(current.get("keywords") or [])
    previous_keywords = set(previous.get("keywords") or [])
    current_tags = {_norm(value) for value in current.get("content_tags") or [] if _norm(value)}
    previous_tags = {_norm(value) for value in previous.get("content_tags") or [] if _norm(value)}
    current_extensions = set(current.get("extensions") or [])
    previous_extensions = set(previous.get("extensions") or [])

    score = 0.0
    score += 0.42 * _jaccard(current_keywords, previous_keywords)
    score += 0.24 * _jaccard(current_tags, previous_tags)
    score += 0.12 * _jaccard(current_extensions, previous_extensions)
    current_type = str(current.get("suggested_type") or "")
    previous_type = str(previous.get("suggested_type") or "")
    if current_type and current_type == previous_type:
        score += 0.12
    current_name = _norm(current.get("name") or "")
    previous_name = _norm(previous.get("name") or "")
    if current_name and previous_name:
        score += 0.10 * SequenceMatcher(None, current_name, previous_name).ratio()
    return round(min(1.0, score), 4)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _path_key(path: str | Path) -> str:
    return str(Path(path)).rstrip("\\/").casefold()


def browse_subfolders(path: Path, resource_root: Path, limit: int = 400, probe_children: bool = False) -> list[dict]:
    """供选择器“点进去”时列出某目录下的现有子目录。

    probe_children 默认关闭：在网络盘(NAS)上对每个子目录再 iterdir 探测会很慢，
    这里默认不探测，UI 直接允许双击进入，空目录交由调用方提示。
    """
    path = Path(path)
    result = []
    for child in _list_subdirs(path, limit=limit):
        result.append(
            {
                "path": str(child),
                "name": child.name,
                "relative": _relative_to_root(child, resource_root),
                "has_children": _has_subdir(child) if probe_children else None,
            }
        )
    result.sort(key=lambda item: item["name"].lower())
    return result


def _expand_synonyms(text: str) -> str:
    additions: list[str] = []
    groups = [
        (("robot", "mech", "mechanical", "android", "droid"), "机器人 机甲 机械"),
        (("gun", "rifle", "pistol", "ammo", "bullet", "weapon", "cartridge"), "枪支 武器 弹药"),
        (("building", "architecture", "facade", "house"), "建筑 楼 房屋"),
        (("vehicle", "car", "truck", "ship", "aircraft", "spaceship"), "载具 车辆 飞行器"),
        (("prop", "props", "kitbash", "parts", "accessory", "container", "panel"), "物件 道具 零件 配件"),
        (("tree", "plant", "flower", "grass", "vegetal", "vegetation"), "自然 植物 树 草"),
        (("rock", "stone", "basalt", "cliff"), "石头 岩石 玄武岩"),
        (("brush", "alpha", "stamp"), "笔刷 Alpha 贴图"),
        (("tutorial", "course", "lesson"), "教程 课程 教学"),
    ]
    for words, expansion in groups:
        if any(word in text for word in words):
            additions.append(expansion)
    if any(word in text for word in ("机甲", "机器人")):
        additions.append("robot mech mechanical")
    if "枪" in text or "武器" in text:
        additions.append("gun rifle weapon")
    if "建筑" in text:
        additions.append("building architecture")
    if "载具" in text:
        additions.append("vehicle car ship aircraft")
    if "物件" in text or "道具" in text:
        additions.append("prop kitbash parts")
    return f"{text} {' '.join(additions)}".strip()


def _has_subdir(path: Path) -> bool:
    try:
        for child in path.iterdir():
            if child.is_dir():
                return True
    except OSError:
        return False
    return False


_CATEGORY_LEAF_WORDS = {
    "人物", "兵器", "场景", "建筑", "枪支", "枪支大炮", "物件", "道具", "衣服",
    "角色配件", "贴图", "载具", "配件", "汽车", "车", "船", "飞机", "飞行器",
    "机甲", "人物道具", "冷兵器", "雕像", "骨头", "地形", "花草", "山", "树",
    "树树枝", "水", "石头", "天空", "星球", "云雾vdb", "男", "女", "小孩",
}


def _looks_like_category_folder(name: str) -> bool:
    normalized = _norm(name)
    normalized = re.sub(r"^[a-z]\s+", "", normalized)
    compact = normalized.replace(" ", "")
    return compact in _CATEGORY_LEAF_WORDS


def _mostly_asset_folders(children: list[Path]) -> bool:
    if not children:
        return False
    category_count = sum(1 for child in children if _looks_like_category_folder(child.name))
    return category_count < max(1, (len(children) + 1) // 2)


def _within_or_equal(path: Path, root: Path) -> bool:
    try:
        Path(path).expanduser().resolve(strict=False).relative_to(
            Path(root).expanduser().resolve(strict=False)
        )
        return True
    except (OSError, ValueError):
        return False


def _target_under_configured_root(target: Path, resource_root: Path) -> Path | None:
    root = Path(resource_root)
    try:
        canonical_root = root.expanduser().resolve(strict=False)
        canonical_target = Path(target).expanduser().resolve(strict=False)
        relative = canonical_target.relative_to(canonical_root)
        display_target = root.joinpath(*relative.parts)
        return display_target if display_target.is_dir() else None
    except (OSError, ValueError):
        pass

    # Some Windows/Python combinations preserve ``Z:`` instead of resolving it
    # to the NAS UNC.  Re-anchor the suffix after the shared library root name.
    root_name = root.name.casefold()
    parts = list(Path(target).parts)
    matches = [index for index, part in enumerate(parts) if str(part).casefold() == root_name]
    if not matches:
        return None
    candidate = root.joinpath(*parts[matches[-1] + 1 :])
    return candidate if candidate.is_dir() else None


def _relative_to_root(path: Path, resource_root: Path) -> str:
    try:
        return str(Path(path).relative_to(resource_root))
    except ValueError:
        return str(path)
