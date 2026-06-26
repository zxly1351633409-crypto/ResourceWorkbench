from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


NOISE_DIR_NAMES = {"工程", "Assets", "Asset", "新建文件夹", "__MACOSX"}


def suggest_target_paths(resource_type: str, search_text: str, z_root: Path | None) -> list[dict]:
    """Suggest fine-grained target paths using the user's existing Z-library tree."""
    if z_root is None or not z_root.exists():
        return []

    normalized = _normalize(search_text)
    suggestions: list[dict] = []

    if resource_type == "model":
        suggestions.extend(_suggest_model_targets(z_root, normalized))
    elif resource_type == "photo":
        suggestions.extend(_suggest_photo_targets(z_root, normalized))
    elif resource_type == "tutorial":
        suggestions.extend(_suggest_tutorial_targets(z_root, normalized))
    elif resource_type == "material":
        path = _find_top(z_root, "C ")
        if path:
            suggestions.append(_make_suggestion(path, 70, "识别为材质资源，匹配 C 材质。"))
    elif resource_type == "ue":
        path = _find_top(z_root, "U ")
        if path:
            suggestions.append(_make_suggestion(path, 70, "识别为 UE 资源，匹配 U UE。"))
    elif resource_type == "zbrush":
        path = _find_top(z_root, "Z zb")
        if path:
            suggestions.append(_make_suggestion(path, 70, "识别为 ZBrush 资源，匹配 Z zb brush。"))

    suggestions.extend(_learned_name_matches(z_root, resource_type, normalized))
    return _dedupe_suggestions(suggestions)[:5]


def describe_content(resource_type: str, search_text: str) -> list[str]:
    normalized = _normalize(search_text)
    tags: list[str] = []

    if resource_type == "model":
        for label, words in [
            ("科幻", ["sci fi", "sci-fi", "scifi", "futuristic", "future", "cyber", "robot", "mech", "space"]),
            ("机甲/机器人", ["robot", "mech", "mechanical", "android", "droid", "leg", "arm"]),
            ("枪支/弹药", ["gun", "rifle", "pistol", "ammo", "bullet", "cartridge", "weapon", "blackout", "5.56", "9mm"]),
            ("建筑/城市", ["building", "architecture", "city", "factory", "street", "town", "urban"]),
            ("载具/飞行器", ["vehicle", "car", "truck", "ship", "rocket", "aircraft", "spaceship"]),
            ("角色/人物", ["character", "soldier", "female", "male", "human", "body", "pose"]),
            ("贴图/面板", ["trim sheet", "texture", "panel", "material"]),
            ("自然", ["tree", "plant", "flower", "grass", "rock", "stone", "terrain", "mountain"]),
        ]:
            if _has_any(normalized, words):
                tags.append(label)

    elif resource_type == "photo":
        for label, words in [
            ("照片包/参考图", ["photo pack", "photopack", "reference", "fotoref", "photos of"]),
            ("岩石/玄武岩", ["basalt", "rock", "stone", "cliff", "column"]),
            ("湖泊/水域", ["lake", "river", "water", "sea", "ocean", "beach"]),
            ("森林/树木", ["forest", "tree", "bamboo", "woods"]),
            ("沙漠/荒漠", ["desert", "mojave", "sand"]),
            ("山脉", ["mountain", "mountains", "hill"]),
            ("城市/建筑", ["city", "street", "building", "urban", "havana", "trinidad"]),
        ]:
            if _has_any(normalized, words):
                tags.append(label)

    elif resource_type == "tutorial":
        for label, words in [
            ("UE/虚幻教程", ["ue", "ue4", "ue5", "unreal"]),
            ("Marvelous Designer/服装教程", ["marvelous", "designer", "md", "clothing", "garment"]),
            ("PS/绘画教程", ["photoshop", "ps", "painting", "concept"]),
            ("CG/影视流程", ["cgi", "film", "filmmaking", "cinematic"]),
        ]:
            if _has_any(normalized, words):
                tags.append(label)

    return tags[:6]


def _suggest_model_targets(z_root: Path, text: str) -> list[dict]:
    model_root = _find_top(z_root, "M ")
    if model_root is None:
        return []

    style = "M 模型"
    style_reason = "识别为模型资源。"
    if _has_any(text, ["sci fi", "sci-fi", "scifi", "futuristic", "future", "cyber", "robot", "mech", "space"]):
        style = "K 科幻"
        style_reason = "名称/目录包含科幻、未来、机器人或机甲线索。"
    elif _has_any(text, ["tree", "plant", "flower", "grass", "rock", "stone", "terrain", "mountain", "nature"]):
        style = "Z 自然"
        style_reason = "名称/目录包含自然、植物、石头或地形线索。"
    elif _has_any(text, ["medieval", "castle", "knight"]):
        style = "Z 中世纪"
        style_reason = "名称/目录包含中世纪线索。"
    elif _has_any(text, ["modern", "street", "gun", "rifle", "ammo", "pistol", "cartridge"]):
        style = "X 现代"
        style_reason = "名称/目录包含现代、枪支或弹药线索。"
    elif _has_any(text, ["ww1", "ww2", "world war", "military"]):
        style = "Y 一战二战"
        style_reason = "名称/目录包含一战、二战或军事线索。"
    elif _has_any(text, ["stylized", "cartoon"]):
        style = "F 风格化"
        style_reason = "名称/目录包含风格化线索。"

    subject = None
    subject_reason = ""
    if _has_any(text, ["robot", "mech", "mechanical", "android", "droid"]):
        subject = "J 机甲"
        subject_reason = "内容像机器人/机甲。"
    elif _has_any(text, ["ammo", "bullet", "cartridge", "gun", "rifle", "pistol", "weapon", "blackout", "9mm", "5.56"]):
        subject = "Q 枪支"
        subject_reason = "内容像枪支、弹药或武器。"
    elif _has_any(text, ["city", "scene", "environment", "factory", "street", "town"]):
        subject = "C 场景"
        subject_reason = "内容像场景或城市环境。"
    elif _has_any(text, ["building", "architecture", "house", "wall", "facade"]):
        subject = "J 建筑"
        subject_reason = "内容像建筑。"
    elif _has_any(text, ["vehicle", "car", "truck", "ship", "rocket", "aircraft", "spaceship"]):
        subject = "Z 载具"
        subject_reason = "内容像载具或飞行器。"
    elif _has_any(text, ["character", "person", "human", "soldier", "female", "male", "body"]):
        subject = "R 人物"
        subject_reason = "内容像人物/角色。"
    elif _has_any(text, ["trim sheet", "texture", "panel", "material"]):
        subject = "贴图"
        subject_reason = "内容像贴图、材质面板或 trim sheet。"
    elif _has_any(text, ["prop", "item", "kit", "assortment", "accessory", "accessories"]):
        subject = "W 物件"
        subject_reason = "内容像物件或配件。"

    style_path = _child_named(model_root, style)
    suggestions: list[dict] = []
    if style_path and subject:
        subject_path = _child_named(style_path, subject) or _child_contains(style_path, subject.split(maxsplit=1)[-1])
        if subject_path:
            suggestions.append(_make_suggestion(subject_path, 110, f"{style_reason}{subject_reason}"))
    if style_path:
        suggestions.append(_make_suggestion(style_path, 85, style_reason))
    suggestions.append(_make_suggestion(model_root, 50, "模型资源的顶层兜底分类。"))
    return suggestions


def _suggest_photo_targets(z_root: Path, text: str) -> list[dict]:
    photo_root = _find_top(z_root, "Z ")
    if photo_root is None:
        return []

    suggestions: list[dict] = []
    nature = _child_named(photo_root, "Z 自然")
    if nature:
        if _has_any(text, ["basalt", "rock", "stone", "cliff", "column"]):
            path = _child_named(nature, "S 石头")
            if path:
                suggestions.append(_make_suggestion(path, 115, "照片内容像岩石/玄武岩/石柱。"))
        if _has_any(text, ["lake", "river", "water"]):
            path = _child_named(nature, "S 水")
            if path:
                suggestions.append(_make_suggestion(path, 105, "照片内容像湖泊或水域。"))
        if _has_any(text, ["forest", "bamboo", "woods"]):
            path = _child_named(nature, "S 森林") or _child_named(nature, "S 树")
            if path:
                suggestions.append(_make_suggestion(path, 105, "照片内容像森林/树木。"))
        if _has_any(text, ["mountain", "mountains", "hill"]):
            path = _child_named(nature, "S 山脉")
            if path:
                suggestions.append(_make_suggestion(path, 105, "照片内容像山脉。"))
        if _has_any(text, ["desert", "mojave", "sand"]):
            path = _child_named(nature, "S 沙漠") or _child_named(nature, "H 荒漠")
            if path:
                suggestions.append(_make_suggestion(path, 105, "照片内容像沙漠/荒漠。"))
        suggestions.append(_make_suggestion(nature, 70, "照片内容更偏自然参考。"))

    if _has_any(text, ["photo pack", "photopack", "fotoref"]):
        roman = _child_named(photo_root, "L 罗曼照片")
        if roman:
            suggestions.append(_make_suggestion(roman, 65, "名称包含照片包线索，可作为照片包兜底候选。"))

    suggestions.append(_make_suggestion(photo_root, 45, "照片资源顶层兜底分类。"))
    return suggestions


def _suggest_tutorial_targets(z_root: Path, text: str) -> list[dict]:
    tutorial_root = _find_top(z_root, "J ")
    if tutorial_root is None:
        return []
    suggestions: list[dict] = []
    if _has_any(text, ["ue", "ue4", "ue5", "unreal"]):
        path = _child_named(tutorial_root, "U ue")
        if path:
            suggestions.append(_make_suggestion(path, 110, "教程内容与 UE/Unreal 相关。"))
    if _has_any(text, ["marvelous", "designer", "garment", "clothing"]):
        path = _child_named(tutorial_root, "M MD")
        if path:
            suggestions.append(_make_suggestion(path, 110, "教程内容与 Marvelous Designer/服装相关。"))
    if _has_any(text, ["photoshop", "ps", "painting", "concept"]):
        path = _child_named(tutorial_root, "P ps")
        if path:
            suggestions.append(_make_suggestion(path, 100, "教程内容与 PS/绘画/概念设计相关。"))
    if _has_any(text, ["cgi", "film", "filmmaking", "lecture"]):
        path = _child_named(tutorial_root, "J 讲座")
        if path:
            suggestions.append(_make_suggestion(path, 90, "教程内容像讲座或 CG 影视流程。"))
    suggestions.append(_make_suggestion(tutorial_root, 45, "教程资源顶层兜底分类。"))
    return suggestions


def _learned_name_matches(z_root: Path, resource_type: str, text: str) -> list[dict]:
    roots = {
        "model": "M ",
        "photo": "Z ",
        "tutorial": "J ",
        "material": "C ",
        "ue": "U ",
    }
    prefix = roots.get(resource_type)
    if not prefix:
        return []
    top = _find_top(z_root, prefix)
    if top is None:
        return []

    stop_words = {
        "model",
        "models",
        "photo",
        "photos",
        "reference",
        "references",
        "pack",
        "packs",
        "standard",
        "license",
        "personal",
        "use",
        "vol",
        "volume",
    }
    words = [
        word
        for word in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text)
        if len(word) >= 3 and word not in stop_words and not word.isdigit()
    ]
    if not words:
        return []

    suggestions: list[dict] = []
    for path in _category_paths(top, max_depth=2):
        name_text = _normalize(path.name)
        score = 0
        for word in words:
            if word in name_text:
                score += 12
        if score >= 36:
            suggestions.append(_make_suggestion(path, min(75, score), "与现有分类目录名有关键词重合。"))
    return suggestions


@lru_cache(maxsize=64)
def _category_paths(root: Path, max_depth: int = 2) -> tuple[Path, ...]:
    paths: list[Path] = []
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted([child for child in current.iterdir() if child.is_dir()], key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if child.name in NOISE_DIR_NAMES:
                continue
            if depth >= 1 and _looks_like_resource_leaf(child.name):
                continue
            paths.append(child)
            stack.append((child, depth + 1))
            if len(paths) >= 2000:
                return tuple(paths)
    return tuple(paths)


def _find_top(z_root: Path, prefix: str) -> Path | None:
    try:
        children = [child for child in z_root.iterdir() if child.is_dir()]
    except OSError:
        return None
    candidates = [child for child in children if child.name.startswith(prefix)]
    if prefix == "M ":
        candidates = [child for child in candidates if child.name != "M MD"]
    if prefix == "Z ":
        candidates = [child for child in candidates if "zb" not in child.name.lower()]
    return sorted(candidates, key=lambda p: len(p.name))[0] if candidates else None


def _child_named(parent: Path, name: str) -> Path | None:
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name == name:
                return child
    except OSError:
        return None
    return None


def _child_contains(parent: Path, text: str) -> Path | None:
    needle = _normalize(text)
    try:
        children = [child for child in parent.iterdir() if child.is_dir()]
    except OSError:
        return None
    for child in children:
        if needle and needle in _normalize(child.name):
            return child
    return None


def _make_suggestion(path: Path, score: int, reason: str) -> dict:
    return {
        "path": str(path),
        "score": score,
        "reason": reason,
    }


def _dedupe_suggestions(suggestions: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for suggestion in suggestions:
        path = suggestion["path"]
        if path not in best or suggestion["score"] > best[path]["score"]:
            best[path] = suggestion
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)


def _normalize(text: str) -> str:
    text = text.lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text)


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _looks_like_resource_leaf(name: str) -> bool:
    lower = name.lower()
    if len(name) >= 36:
        return True
    if "_" in name:
        return True
    if any(token in lower for token in (" by ", "license", "standard", "personal", "vol.", "vol ")):
        return True
    if re.search(r"\d{2,}", lower):
        return True
    return False
