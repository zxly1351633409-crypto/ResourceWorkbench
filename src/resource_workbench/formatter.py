"""统一显示格式：封面图留在资源文件夹外层，其余内容收进“工程”子文件夹。

对应用户既有工作流的第 5 步（原“资源文件统一显示格式工具”）。
- 选封面：资源根目录下的图片里，按命名/大小挑最像封面的一张，保留在外层。
- 其余所有文件/文件夹收进“工程”子目录。
- 冲突安全（不覆盖）、写 `_format_manifest.json`，可一键撤销。
只在单个资源文件夹内移动，不跨目录、不删除内容。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .file_types import IMAGE_EXTS

try:
    from .classifier import _preview_name_score as _score
except Exception:  # pragma: no cover - fallback
    def _score(name: str) -> int:
        return 0

MANIFEST_NAME = "_format_manifest.json"


def _top_images(resource_dir: Path) -> list[Path]:
    images = []
    for child in resource_dir.iterdir():
        if child.is_file() and child.suffix.lower() in IMAGE_EXTS:
            images.append(child)
    return images


def _pick_cover(resource_dir: Path) -> Path | None:
    images = _top_images(resource_dir)
    if not images:
        return None

    def key(p: Path):
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        return (_score(p.name), size, p.name)

    return max(images, key=key)


def plan_cover_project(resource_dir: Path, project_name: str = "工程") -> dict:
    resource_dir = Path(resource_dir)
    if not resource_dir.is_dir():
        return {"ok": False, "error": "资源路径不是文件夹。"}
    cover = _pick_cover(resource_dir)
    project_dir = resource_dir / project_name
    move_items: list[str] = []
    for child in resource_dir.iterdir():
        if child.name == MANIFEST_NAME:
            continue
        if cover is not None and child == cover:
            continue
        if child == project_dir:
            continue
        move_items.append(child.name)
    already = (not move_items) and project_dir.exists()
    return {
        "ok": True,
        "resource_dir": str(resource_dir),
        "cover": cover.name if cover else None,
        "project_dir": project_name,
        "move_items": move_items,
        "already_organized": already,
    }


def apply_cover_project(resource_dir: Path, project_name: str = "工程") -> dict:
    plan = plan_cover_project(resource_dir, project_name)
    if not plan.get("ok"):
        return plan
    resource_dir = Path(resource_dir)
    if not plan["move_items"]:
        return {"ok": True, "skipped": True, "reason": "没有需要收纳的内容。", **plan}
    project_dir = resource_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    moves = []
    for name in plan["move_items"]:
        src = resource_dir / name
        if not src.exists():
            continue
        dest = _unique(project_dir / name)
        try:
            src.rename(dest)
        except OSError as exc:
            return {"ok": False, "error": f"移动 {name} 失败：{exc}", "moved": moves}
        moves.append({"name": name, "from": str(src), "to": str(dest)})
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "resource_dir": str(resource_dir),
        "project_dir": str(project_dir),
        "cover": plan.get("cover"),
        "moves": moves,
    }
    (resource_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True, "skipped": False, "moved": len(moves), "cover": plan.get("cover"),
            "project_dir": str(project_dir)}


def undo_cover_project(resource_dir: Path) -> dict:
    resource_dir = Path(resource_dir)
    manifest_path = resource_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return {"ok": False, "error": "没有找到整理记录，无法撤销。"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"读取整理记录失败：{exc}"}
    restored = 0
    for move in reversed(manifest.get("moves", [])):
        dest = Path(move["to"])
        src = Path(move["from"])
        if not dest.exists() or src.exists():
            continue
        try:
            dest.rename(src)
            restored += 1
        except OSError:
            pass
    project_dir = Path(manifest.get("project_dir", resource_dir / "工程"))
    try:
        if project_dir.exists() and not any(project_dir.iterdir()):
            project_dir.rmdir()
    except OSError:
        pass
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return {"ok": True, "restored": restored}


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    if path.is_dir():
        stem, suffix = path.name, ""
    i = 2
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1
