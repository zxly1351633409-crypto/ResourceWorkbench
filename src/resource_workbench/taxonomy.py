from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


NOISE_DIR_NAMES = {"工程", "Assets", "Asset", "新建文件夹", "__MACOSX", ".sync"}


def suggest_target_paths(
    resource_type: str,
    search_text: str,
    z_root: Path | None,
    *,
    name_text: str = "",
) -> list[dict]:
    """Suggest fine-grained target paths using the user's existing Z-library tree."""
    if z_root is None or not z_root.exists():
        return []

    normalized = _normalize(search_text)
    suggestions: list[dict] = []

    if resource_type == "model":
        suggestions.extend(_suggest_model_targets(z_root, normalized, _normalize(name_text) if name_text else ""))
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
    elif resource_type in ("mixed", "unknown"):
        # Fallback: try all known type handlers
        suggestions.extend(_suggest_model_targets(z_root, normalized, _normalize(name_text) if name_text else ""))
        suggestions.extend(_suggest_photo_targets(z_root, normalized))
        suggestions.extend(_suggest_tutorial_targets(z_root, normalized))
        for prefix, reason in [("C ", "材质"), ("U ", "UE"), ("Z zb", "ZBrush")]:
            path = _find_top(z_root, prefix)
            if path:
                suggestions.append(_make_suggestion(path, 35, f"类型未确定，尝试匹配 {reason} 顶层。"))

    suggestions.extend(_learned_name_matches(z_root, resource_type, normalized))
    return _dedupe_suggestions(suggestions)[:5]


def describe_content(resource_type: str, search_text: str) -> list[str]:
    normalized = _normalize(search_text)
    tags: list[str] = []

    if resource_type == "model":
        for label, words in [
            ("废土/废墟", ["wasteland", "post apocalyptic", "post-apocalyptic", "abandoned", "destroyed", "demolished", "debris", "rubble", "scrap", "wreck", "ruined", "废土", "废墟", "废弃", "残骸", "碎石", "瓦砾"]),
            ("科幻", ["sci fi", "sci-fi", "scifi", "futuristic", "future", "cyber", "robot", "mech", "space"]),
            ("机甲/机器人", ["robot", "mech", "mechanical", "android", "droid", "leg", "arm"]),
            ("枪支/弹药", ["gun", "rifle", "pistol", "ammo", "bullet", "cartridge", "weapon", "blackout", "5.56", "9mm"]),
            ("建筑/立面", ["building", "buildings", "architecture", "facade", "facades", "floor", "wall", "建筑", "立面", "楼层", "地板"]),
            ("城市/场景", ["city", "factory", "street", "town", "urban", "environment", "scene", "城市", "街道", "场景"]),
            ("室内/商业空间", ["interior", "indoor", "room", "supermarket", "store", "shop", "室内", "超市", "商店"]),
            ("道具/残骸", ["prop", "props", "debris", "rubble", "scrap", "wreck", "object", "objects", "道具", "残骸", "碎石", "废料"]),
            ("军事/近现代", ["military", "army", "combat", "军事", "军用", "近现代"]),
            ("乌克兰扫描", ["ukraine", "乌克兰"]),
            ("载具/飞行器", ["vehicle", "car", "cars", "truck", "ship", "rocket", "aircraft", "spaceship", "载具", "汽车", "车辆"]),
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


def _suggest_model_targets(z_root: Path, text: str, title_text: str = "") -> list[dict]:
    model_root = _find_top(z_root, "M ")
    if model_root is None:
        return []

    style: str | None = None
    style_reason = ""
    if _has_any(text, ["sci fi", "sci-fi", "scifi", "futuristic", "future", "cyber", "robot", "mech", "space"]):
        style = "K 科幻"
        style_reason = "名称/目录包含科幻、未来、机器人或机甲线索。"
    elif _has_any(text, ["ancient ruins", "archaeological", "archaeology", "temple ruins", "古代遗迹", "考古", "遗址"]):
        style = "Y 遗迹"
        style_reason = "名称/目录包含古代遗迹或考古线索。"
    elif _has_any(text, ["ww1", "ww2", "world war", "worldwar", "1940s", "一战", "二战", "世界大战"]):
        style = "Y 一战二战"
        style_reason = "名称/目录明确包含一战、二战或世界大战线索。"
    elif _has_any(
        text,
        [
            "wasteland", "post apocalyptic", "post-apocalyptic", "abandoned", "destroyed",
            "demolished", "debris", "rubble", "scrap", "wreck", "ruined", "decay",
            "trash", "junk", "garbage", "dump", "废墟", "废弃", "残骸", "碎石", "瓦砾", "破败", "拆除",
        ],
    ):
        style = "F 废土"
        style_reason = "名称或批次语境包含废墟、废弃、残骸或拆除线索。"
    elif _has_any(text, ["interior", "indoor", "room", "supermarket", "store", "shop", "floor", "室内", "超市", "商店", "房间"]):
        style = "S 室内"
        style_reason = "名称/目录包含室内、楼层或商业空间线索。"
    elif _has_any(text, ["building", "buildings", "architecture", "facade", "facades", "city", "street", "urban", "town", "建筑", "立面", "城市", "街道"]):
        style = "C 城市"
        style_reason = "名称/目录包含城市、建筑、立面或街道线索。"
    elif _has_any(text, ["military", "army", "combat", "军事", "军用", "近现代"]):
        style = "J 近现代"
        style_reason = "名称/目录包含近现代军事或乌克兰语境，且没有世界大战年代线索。"
    elif _has_any(text, ["vehicle", "car", "cars", "truck", "van", "bus", "汽车", "车辆"]):
        style = "X 现代"
        style_reason = "名称/目录包含现代车辆线索。"
    elif _has_any(text, ["tree", "plant", "flower", "grass", "rock", "stone", "terrain", "mountain", "nature"]):
        style = "Z 自然"
        style_reason = "名称/目录包含自然、植物、石头或地形线索。"
    elif _has_any(text, ["medieval", "castle", "knight"]):
        style = "Z 中世纪"
        style_reason = "名称/目录包含中世纪线索。"
    elif _has_any(text, ["modern", "contemporary", "gun", "rifle", "ammo", "pistol", "cartridge", "现代"]):
        style = "X 现代"
        style_reason = "名称/目录包含现代、枪支或弹药线索。"
    elif _has_any(text, ["stylized", "cartoon"]):
        style = "F 风格化"
        style_reason = "名称/目录包含风格化线索。"

    subject: str | None = None
    subject_reason = ""
    has_weapon_terms = _has_any(text, ["ammo", "bullet", "cartridge", "gun", "rifle", "pistol", "weapon", "blackout", "9mm", "5.56"])
    has_military_terms = _has_any(text, ["military", "army", "combat", "军事", "军用"])
    has_parts_terms = _has_any(
        text,
        [
            "parts",
            "part",
            "prop",
            "props",
            "item",
            "kitbash",
            "hard surface",
            "column",
            "container",
            "panel",
            "panels",
            "trim sheet",
            "accessory",
            "accessories",
        ],
    )
    if _has_any(text, ["robot", "mech", "mechanical", "android", "droid"]):
        subject = "mech"
        subject_reason = "内容像机器人/机甲。"
    elif has_weapon_terms and not (has_parts_terms and not _has_any(text, ["rifle", "gun", "pistol", "ammo", "bullet", "cartridge", "weapon"])):
        subject = "weapon"
        subject_reason = "内容像枪支、弹药或武器。"
    elif has_military_terms and not has_parts_terms:
        subject = "vehicle"
        subject_reason = "Military 合集更像坦克、装甲车等军用载具。"
    elif _has_any(text, ["vehicle", "car", "cars", "truck", "van", "bus", "ship", "rocket", "aircraft", "spaceship", "载具", "汽车", "车辆"]):
        subject = "vehicle"
        subject_reason = "内容像载具或飞行器。"
    elif _has_any(text, ["building", "buildings", "architecture", "house", "wall", "facade", "facades", "floor", "建筑", "立面", "楼层", "地板"]):
        subject = "building"
        subject_reason = "内容像建筑、立面或楼层构件。"
    elif _has_any(text, ["supermarket", "grocery", "store props", "shop props", "超市", "杂货店"]):
        subject = "object"
        subject_reason = "内容像超市/杂货店中的箱盒和散件道具。"
    elif _has_any(text, ["interior", "indoor", "room", "scene", "environment", "city", "factory", "street", "town", "室内", "商店", "场景"]):
        subject = "scene"
        subject_reason = "内容像室内、商业空间或环境场景。"
    elif has_parts_terms or _has_any(text, ["debris", "rubble", "scrap", "wreck", "military", "object", "objects", "废料", "残骸", "瓦砾", "军事", "道具"]):
        subject = "object"
        subject_reason = "内容像道具、残骸、军用品或散件。"
    elif _has_any(text, ["character", "person", "human", "soldier", "female", "male", "body"]):
        subject = "character"
        subject_reason = "内容像人物/角色。"
    elif _has_any(text, ["trim sheet", "texture", "panel", "material"]):
        subject = "texture"
        subject_reason = "内容像贴图、材质面板或 trim sheet。"
    elif _has_any(text, ["prop", "item", "kit", "assortment", "accessory", "accessories"]):
        subject = "object"
        subject_reason = "内容像物件或配件。"

    style_path = _child_named(model_root, style) if style else None
    suggestions: list[dict] = []
    if style_path and subject:
        subject_path = _semantic_subject_child(style_path, subject)
        if subject_path:
            detail_path, detail_reason = _semantic_detail_child(subject_path, subject, text)
            if detail_path is not None:
                suggestions.append(
                    _make_suggestion(
                        detail_path,
                        135,
                        f"{style_reason}{subject_reason}{detail_reason}已匹配资源库现有三级分类。",
                    )
                )
            suggestions.append(_make_suggestion(subject_path, 125, f"{style_reason}{subject_reason}已匹配资源库现有深层分类。"))
    if style_path:
        suggestions.append(_make_suggestion(style_path, 90, style_reason))
    suggestions.append(_make_suggestion(model_root, 45, "模型资源的顶层兜底分类；仅在没有更具体线索时使用。"))
    if title_text and title_text != text:
        # The batch context (for example “废墟二期”) is valuable, but the card
        # title can carry a competing subject such as Interior/Military/Cars.
        # Keep a slightly lower title-only alternative instead of hiding it.
        for candidate in _suggest_model_targets(z_root, title_text):
            if Path(candidate["path"]) == model_root:
                continue
            alternative = dict(candidate)
            alternative["score"] = max(1, int(alternative.get("score") or 0) - 12)
            alternative["reason"] = "仅按当前资源标题判断的备选：" + str(alternative.get("reason") or "")
            suggestions.append(alternative)
    return suggestions


_SUBJECT_CHILD_ALIASES = {
    "scene": ("场景", "c 场景"),
    "building": ("建筑", "j 建筑"),
    "object": ("物件", "w 物件", "道具", "配件", "p 配件"),
    "vehicle": ("载具", "z 载具"),
    "weapon": ("枪支", "枪支 大炮", "q 枪支", "q 枪支 大炮", "兵器"),
    "character": ("人物", "r 人物", "r 人物道具"),
    "texture": ("贴图", "t 贴图"),
    "mech": ("机甲", "j 机甲"),
}


@lru_cache(maxsize=512)
def _semantic_subject_child(style_path: Path, subject: str) -> Path | None:
    aliases = {_normalize(alias) for alias in _SUBJECT_CHILD_ALIASES.get(subject, ())}
    try:
        children = [child for child in style_path.iterdir() if child.is_dir()]
    except OSError:
        return None
    exact = [child for child in children if _normalize(child.name) in aliases]
    if exact:
        return sorted(exact, key=lambda child: len(child.name))[0]
    for child in children:
        child_name = _normalize(child.name)
        if any(alias and (child_name.endswith(alias) or alias.endswith(child_name)) for alias in aliases):
            return child
    return None


@lru_cache(maxsize=1024)
def _semantic_detail_child(subject_path: Path, subject: str, text: str) -> tuple[Path | None, str]:
    aliases: tuple[str, ...] = ()
    reason = ""
    if subject == "vehicle" and _has_any(text, ["car", "cars", "truck", "van", "bus", "automobile", "汽车", "车辆"]):
        aliases = ("c 车", "q 汽车", "车", "汽车")
        reason = "进一步识别为汽车/车辆。"
    elif subject == "vehicle" and _has_any(text, ["ship", "boat", "vessel", "船", "舰"]):
        aliases = ("c 船", "船")
        reason = "进一步识别为船舶。"
    elif subject == "vehicle" and _has_any(text, ["aircraft", "airplane", "plane", "jet", "飞机", "飞行器"]):
        aliases = ("z 飞机", "飞机")
        reason = "进一步识别为飞机/飞行器。"
    if not aliases:
        return None, ""
    wanted = {_normalize(alias) for alias in aliases}
    try:
        children = [child for child in subject_path.iterdir() if child.is_dir()]
    except OSError:
        return None, ""
    for child in children:
        if _normalize(child.name) in wanted:
            return child, reason
    return None, ""


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
    # For unknown/mixed types, search across all known roots
    prefixes: list[str]
    if resource_type in ("unknown", "mixed"):
        prefixes = list(roots.values())
    else:
        prefix = roots.get(resource_type)
        if not prefix:
            return []
        prefixes = [prefix]

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
    for pf in prefixes:
        top = _find_top(z_root, pf)
        if top is None:
            continue
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


@lru_cache(maxsize=128)
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


@lru_cache(maxsize=512)
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
