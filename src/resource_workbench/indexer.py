from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .file_types import IMAGE_EXTS, VIDEO_EXTS, normalized_ext, type_bucket
from .web_resource import read_web_resource_card

SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".sync", "System Volume Information", "$RECYCLE.BIN"}
SKIP_FILE_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}


def index_db_path(project_root: Path) -> Path:
    return project_root / "workbench_data" / "resource_index.sqlite"


class ResourceIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def index_children(self, parent: Path, max_children: int = 240) -> int:
        parent = parent.expanduser().resolve()
        if not parent.exists() or not parent.is_dir():
            return 0
        try:
            entries = list(parent.iterdir())
        except OSError:
            return 0
        directories: list[Path] = []
        files: list[Path] = []
        for child in entries:
            try:
                if child.is_dir():
                    if child.name not in SKIP_DIR_NAMES:
                        directories.append(child)
                elif child.is_file() and child.name.casefold() not in SKIP_FILE_NAMES:
                    files.append(child)
            except OSError:
                continue

        # Keep the existing category-browser behaviour for non-leaf paths:
        # when folders exist, cards represent those folders.  A true leaf
        # directory, however, must expose its direct files or clicking into it
        # would produce preview-less placeholders forever.
        children_are_directories = bool(directories)
        children = sorted(directories or files, key=lambda item: item.name.lower())
        now = time.time()
        with self._connect() as connection:
            cached = {
                row[0]: row
                for row in connection.execute(
                    """
                    select path, parent_path, name, is_dir, mtime, total_files, total_dirs,
                           preview_kind, preview_path
                    from resources
                    where parent_path = ?
                    """,
                    (str(parent),),
                ).fetchall()
            }
            rows = []
            for child in children[:max_children]:
                child_key = str(child)
                cached_row = cached.get(child_key)
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    mtime = 0.0
                has_preview = bool(str(cached_row[8] or "")) if cached_row else False
                unchanged = (
                    cached_row
                    and bool(cached_row[3]) == children_are_directories
                    and abs(float(cached_row[4]) - float(mtime)) < 0.001
                )
                if unchanged and (has_preview or not children_are_directories):
                    rows.append(tuple(cached_row))
                else:
                    rows.append(_quick_row(child, parent) if children_are_directories else _file_row(child, parent))
            connection.execute("delete from resources where parent_path = ?", (str(parent),))
            connection.executemany(
                """
                insert or replace into resources (
                    path, parent_path, name, is_dir, mtime, total_files, total_dirs,
                    preview_kind, preview_path, indexed_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(*row, now) for row in rows],
            )
        return len(rows)

    def load_child_cards(self, parent: Path, max_cards: int = 120) -> list[dict]:
        parent = parent.expanduser().resolve()
        with self._connect() as connection:
            records = connection.execute(
                """
                select path, name, is_dir, total_files, total_dirs, preview_kind, preview_path
                from resources
                where parent_path = ?
                order by lower(name)
                limit ?
                """,
                (str(parent), max_cards),
            ).fetchall()
        return [_record_to_card(record) for record in records]

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists resources (
                    path text primary key,
                    parent_path text not null,
                    name text not null,
                    is_dir integer not null,
                    mtime real not null,
                    total_files integer not null,
                    total_dirs integer not null,
                    preview_kind text,
                    preview_path text,
                    indexed_at real not null
                )
                """
            )
            connection.execute("create index if not exists idx_resources_parent on resources(parent_path)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def quick_cards_for_path(path: Path, max_cards: int = 120) -> list[dict]:
    path = path.expanduser().resolve()
    if not path.exists():
        return []
    if path.is_file():
        return [_path_to_card(path)]
    try:
        dirs = sorted([child for child in path.iterdir() if child.is_dir() and child.name not in SKIP_DIR_NAMES], key=lambda item: item.name.lower())
    except OSError:
        return []
    if dirs:
        return [_path_to_card(child) for child in dirs[:max_cards]]

    try:
        files = sorted(
            [child for child in path.iterdir() if child.is_file() and child.name.casefold() not in SKIP_FILE_NAMES],
            key=lambda item: item.name.lower(),
        )
    except OSError:
        return []
    return [_path_to_card(child) for child in files[:max_cards]]


def placeholder_cards_for_path(path: Path, max_cards: int = 120) -> list[dict]:
    path = path.expanduser().resolve()
    if not path.exists():
        return []
    if path.is_file():
        return [_path_to_card(path)]
    try:
        dirs = sorted([child for child in path.iterdir() if child.is_dir() and child.name not in SKIP_DIR_NAMES], key=lambda item: item.name.lower())
    except OSError:
        return []
    if dirs:
        return [_placeholder_card(child) for child in dirs[:max_cards]]
    try:
        files = sorted(
            [child for child in path.iterdir() if child.is_file() and child.name.casefold() not in SKIP_FILE_NAMES],
            key=lambda item: item.name.lower(),
        )
    except OSError:
        return []
    # Direct leaf files are cheap to describe and already contain enough
    # information to expose image/video previews.  Directory placeholders stay
    # lightweight, preserving fast browsing for large NAS category trees.
    return [_path_to_card(child) for child in files[:max_cards]]


def _quick_row(path: Path, parent: Path) -> tuple:
    total_files = 0
    total_dirs = 0
    preview: Path | None = None
    preview_score = -10_000
    preview_kind = ""
    stack: list[tuple[Path, int]] = [(path, 0)]
    seen_dirs = 0
    while stack and total_files < 520 and seen_dirs < 320:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())[:220]
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                total_dirs += 1
                seen_dirs += 1
                if depth < 5 and seen_dirs < 320:
                    stack.append((entry, depth + 1))
                continue
            if not entry.is_file():
                continue
            total_files += 1
            ext = normalized_ext(entry)
            if ext in IMAGE_EXTS:
                score = _preview_score(entry)
                if preview is None or preview_kind != "file" or score > preview_score:
                    preview = entry
                    preview_score = score
                    preview_kind = "file"
            elif preview is None and ext in VIDEO_EXTS:
                preview = entry
                preview_score = -100
                preview_kind = "video_file"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (
        str(path),
        str(parent),
        path.name,
        1 if path.is_dir() else 0,
        mtime,
        total_files,
        total_dirs,
        preview_kind,
        str(preview) if preview else "",
    )


def _file_row(path: Path, parent: Path) -> tuple:
    bucket = type_bucket(path)
    preview_kind = "file" if bucket == "image" else "video_file" if bucket == "video" else ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (
        str(path),
        str(parent),
        path.name,
        0,
        mtime,
        1,
        0,
        preview_kind,
        str(path) if preview_kind else "",
    )


def _preview_score(path: Path) -> int:
    lower = path.name.lower()
    score = 0
    for hint in ("cover", "preview", "thumb", "thumbnail", "render", "screenshot", "poster", "main", "beauty", "file"):
        if hint in lower:
            score += 20
    for bad in ("normal", "roughness", "metallic", "specular", "opacity", "height", "displacement", "mask", "alpha", "ao", "logo", "icon", "qr"):
        if bad in lower:
            score -= 25
    if lower.startswith(("cover", "preview", "render", "main")):
        score += 12
    if any(token in lower for token in ("000", "001", "_01", "-01")):
        score += 4
    return score


def _path_to_card(path: Path) -> dict:
    if path.is_dir():
        row = _quick_row(path, path.parent)
        return _record_to_card((row[0], row[2], 1, row[5], row[6], row[7], row[8]))
    row = _file_row(path, path.parent)
    return _record_to_card((row[0], row[2], 0, row[5], row[6], row[7], row[8]))


def _placeholder_card(path: Path) -> dict:
    return _record_to_card((str(path), path.name, 1 if path.is_dir() else 0, 0, 0, "", ""))


def _record_to_card(record: tuple) -> dict:
    path_text, name, is_dir, total_files, total_dirs, preview_kind, preview_path = record
    preview_source = None
    if preview_kind and preview_path:
        preview_source = {"kind": preview_kind, "path": preview_path}
    if is_dir:
        media_type = "video" if preview_kind == "video_file" else "image" if preview_kind == "file" else "unknown"
    else:
        bucket = type_bucket(path_text)
        known_media = {"image", "video", "audio", "document", "model", "engine", "zbrush", "archive"}
        media_type = bucket if bucket in known_media else "other"
    web_card = read_web_resource_card(Path(path_text))
    if web_card:
        web_card["total_files"] = total_files
        web_card["total_dirs"] = total_dirs
        web_card["is_directory"] = bool(is_dir)
        web_card.setdefault("media_type", media_type)
        if not web_card.get("preview_source") and preview_source:
            web_card["preview_source"] = preview_source
        return web_card
    return {
        "name": name,
        "display_name": name,
        "source_path": path_text,
        "is_directory": bool(is_dir),
        "media_type": media_type,
        "suggested_type": "unknown",
        "confidence": "low",
        "content_tags": ["快速浏览"],
        "target_suggestions": [],
        "target_path_hints": [],
        "needs_human_review": True,
        "archive_count": 0,
        "source_archive_count": 0,
        "source_archives": [],
        "inspected_archives": 0,
        "virtual_archive_count": 0,
        "total_files": total_files,
        "total_dirs": total_dirs,
        "total_bytes": 0,
        "buckets": {},
        "archive_virtual_buckets": {},
        "top_extensions": {},
        "top_archive_extensions": {},
        "samples": {},
        "archive_entry_samples": [],
        "archive_previews": [],
        "candidate_subresources": {},
        "possible_split_count": 0,
        "preview_source": preview_source,
        "reasons": ["快速浏览卡片：用于即时查看内容，点击分析后再生成详细判断。"],
    }
