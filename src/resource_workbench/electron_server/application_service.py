"""
ApplicationService — central business orchestrator for the Electron frontend.

Wraps all original ResourceWorkbench modules and exposes a clean,
card_id–based API for the HTTP server.  Integrates with:

- ``CardStore`` — stable card identity
- ``TaskManager`` — progress / cancellation
- Original ``MoveLog``, ``ReviewQueue``, ``RenameLog`` — full audit trail
- Original ``settings`` — shared configuration (secret.json, JSON settings)

Uses the **original** project's ``workbench_data/`` directory.
Never creates a second data store.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

# ── project root (src/resource_workbench/electron_server → up three levels) ──
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _PROJECT_ROOT / "workbench_data"

# ── original modules ──────────────────────────────────────────────
from .. import __version__
from ..classifier import build_cards
from ..scanner import ScanConfig, scan_input
from ..preview import prepare_preview_image
from ..deepseek import request_structured_card_suggestion
from ..mover import plan_move, execute_test_move, execute_formal_move, undo_move
from ..target_recommender import recommend_target_folders, apply_history_target_suggestions, prepare_history_records
from ..indexer import ResourceIndex, index_db_path, placeholder_cards_for_path, quick_cards_for_path
from ..review_queue import ReviewQueue, default_queue_path
from ..move_log import MoveLog, default_move_log_path
from ..renamer import RenameLog, default_rename_log_path, rename_folder
from ..maintenance import find_duplicates as _find_duplicates
from ..maintenance import remove_empty_dirs as _remove_empty_dirs
from ..web_resource import create_web_resource_card, is_web_card, normalise_url
from ..formatter import plan_cover_project, apply_cover_project, undo_cover_project
from ..card_metadata import CardMetadataStore, default_metadata_path
from ..review_queue import STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_RECHECK
from ..settings import (
    app_data_root,
    load_settings,
    save_settings as _save_settings,
    deepseek_api_key,
    deepseek_api_key_source,
    save_deepseek_api_key,
)

from .card_store import CardStore
from .task_manager import TaskManager, TaskKind


class ApplicationService:
    """Single-instance service that backs the Electron HTTP API."""

    def __init__(self) -> None:
        self.project_root = _PROJECT_ROOT
        self.data_root = _DATA_ROOT
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.store = CardStore()
        self.tasks = TaskManager()

        # Lazy-loaded persistent helpers
        self._move_log: MoveLog | None = None
        self._rename_log: RenameLog | None = None
        self._review_queue: ReviewQueue | None = None
        self._resource_index: ResourceIndex | None = None

        # Settings cache
        self._settings: dict | None = None
        self._preview_cache_dir = self.data_root / "previews"
        self._preview_cache_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════════
    # Settings
    # ═══════════════════════════════════════════════════════════════

    def get_settings(self) -> dict:
        """Load (or return cached) settings.  Always re-reads secret."""
        self._settings = load_settings(self.project_root)
        # Add key status without revealing the actual key
        self._settings["deepseek_api_key"] = bool(deepseek_api_key(self._settings))
        return self._settings

    def save_settings(self, updates: dict) -> dict:
        """Merge *updates* into settings and persist."""
        current = self.get_settings()
        current.update(updates)
        _save_settings(self.project_root, current)
        self._settings = current
        # Persist API key separately if provided (skip empty to avoid clearing)
        if "deepseek_api_key" in updates:
            key_val = (updates.get("deepseek_api_key") or "").strip()
            if key_val:
                save_deepseek_api_key(current, key_val)
        return {"ok": True}

    def get_api_key_source(self) -> str:
        return deepseek_api_key_source(self.get_settings())

    # ═══════════════════════════════════════════════════════════════
    # Persistent helpers (lazy)
    # ═══════════════════════════════════════════════════════════════

    @property
    def move_log(self) -> MoveLog:
        if self._move_log is None:
            self._move_log = MoveLog(default_move_log_path(self.project_root))
        return self._move_log

    @property
    def rename_log(self) -> RenameLog:
        if self._rename_log is None:
            self._rename_log = RenameLog(default_rename_log_path(self.project_root))
        return self._rename_log

    @property
    def review_queue(self) -> ReviewQueue:
        if self._review_queue is None:
            self._review_queue = ReviewQueue(default_queue_path(self.project_root))
        return self._review_queue

    @property
    def resource_index(self) -> ResourceIndex:
        if self._resource_index is None:
            self._resource_index = ResourceIndex(index_db_path(self.project_root))
        return self._resource_index

    # ═══════════════════════════════════════════════════════════════
    # Analyse / Scan
    # ═══════════════════════════════════════════════════════════════

    def analyse(self, paths: list[str]) -> dict:
        """Scan one or more paths and build classifier cards."""
        settings = self.get_settings()
        z_root_str = settings.get("resource_root", "")
        z_root = None
        if z_root_str:
            try:
                zr = Path(z_root_str)
                if zr.exists():
                    z_root = zr
            except (OSError, PermissionError):
                pass  # Z drive may not be accessible, proceed without taxonomy

        # Clear old work cards immediately
        self.store.replace_work([])

        task = self.tasks.start(TaskKind.SCAN, f"\u626b\u63cf {len(paths)} \u4e2a\u8def\u5f84")
        self.tasks.update_progress(0.0, "\u6b63\u5728\u626b\u63cf...")

        # Pre-load move history for target recommendations
        history_records = []
        if z_root and z_root.exists():
            try:
                records = self.move_log.learning_records(limit=2000)
                history_records = prepare_history_records(records, z_root)
            except Exception:
                pass

        def _run():
            cards_all: list[dict] = []
            warnings: list[str] = []
            web_count = 0
            try:
                total = len(paths)
                for i, p in enumerate(paths):
                    if task.cancelled:
                        break
                    # Detect web URLs
                    ps = str(p)
                    if ps.startswith(("http://", "https://", "www.")):
                        try:
                            self.tasks.update_progress((i + 0.2) / total, f"读取网页: {ps[:50]}")
                            wc = self.data_root / "_web_cache"
                            wc.mkdir(parents=True, exist_ok=True)
                            web_card = create_web_resource_card(ps, wc)
                            web_card["card_id"] = self.store.card_id(web_card)
                            cards_all.append(web_card)
                            web_count += 1
                        except Exception as e:
                            warnings.append(f"网页失败: {e}")
                        continue
                    # Handle file paths
                    try:
                        pp = Path(p).expanduser()
                    except Exception:
                        pp = Path(p)
                    if not pp.exists():
                        warnings.append(f"\u8def\u5f84\u4e0d\u5b58\u5728\uff1a{p}")
                        self.tasks.update_progress((i + 1) / total, f"\u8df3\u8fc7\u4e0d\u5b58\u5728: {str(p)[-40:]}")
                        continue
                    try:
                        self.tasks.update_progress((i + 0.1) / total, f"\u626b\u63cf\u4e2d: {pp.name}")
                        cfg = ScanConfig(
                            max_files=300000,
                            max_depth=10,
                            max_seconds=900,
                            max_archives_to_inspect=0,
                            inspect_archives=False,
                            split_archive_subresources=False,
                            cancel_check=self.tasks.cancel_check(),
                        )
                        scan = scan_input(pp, cfg)
                        self.tasks.update_progress((i + 0.5) / total, f"\u5206\u7c7b\u4e2d: {pp.name}")
                        cards_all.extend(build_cards(scan, z_root=z_root))
                        # Filter empty wrapper cards: if scan dir has sub-cards,
                        # skip root-level cards with 0 actual files
                        sub_cards = [c for c in cards_all if not str(c.get("name","")).startswith("(")]
                        for c in list(cards_all):
                            if str(c.get("name","")).startswith("(") and sub_cards and c.get("total_files", 0) == 0:
                                cards_all.remove(c)
                        # Apply move history to target suggestions
                        if history_records and z_root:
                            for card in cards_all:
                                try:
                                    apply_history_target_suggestions(card, z_root, history_records)
                                except Exception:
                                    pass
                        # Fix display names: replace placeholders with scan path name
                        for card in cards_all:
                            if str(card.get("name", "")).startswith("("):
                                card["name"] = pp.name
                                card["display_name"] = pp.name
                            card["batch_source_path"] = str(pp)
                        self.tasks.update_progress((i + 0.9) / total, f"\u5b8c\u6210: {pp.name}")
                    except Exception as e:
                        import traceback as _tb
                        _tb.print_exc()
                        warnings.append(f"{pp.name}: {e}")
            except Exception as e:
                import traceback as _tb
                _tb.print_exc()
                warnings.append(f"\u626b\u63cf\u672a\u77e5\u9519\u8bef: {e}")
            finally:
                self.store.replace_work(cards_all)
                self.tasks.finish({
                    "total": len(cards_all),
                    "warnings": warnings,
                    "web_count": web_count,
                })

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "task": task.kind.value, "busy": True, "path_count": len(paths)}

    def cancel_analysis(self) -> dict:
        cancelled = self.tasks.cancel_current()
        return {"ok": True, "cancelled": cancelled}

    def get_work_cards(self) -> dict:
        cards = self.store.work_as_list()
        warnings = []
        if self.tasks._last_result and isinstance(self.tasks._last_result, dict):
            warnings = self.tasks._last_result.get("warnings", [])
        return {
            "ok": True,
            "cards": self.store.serialise_list(cards),
            "total": len(cards),
            "warnings": warnings,
        }

    # ═══════════════════════════════════════════════════════════════
    # Library / Resource Browser
    # ═══════════════════════════════════════════════════════════════

    def library_tree(self, path_str: str = "") -> dict:
        """Return a directory tree under the resource root."""
        settings = self.get_settings()
        root_str = settings.get("resource_root", "")
        if not root_str:
            return {"ok": True, "children": [
                {"name": "未设置资源库路径", "path": "", "children": []}
            ]}
        root = Path(root_str).expanduser()
        if path_str:
            current = Path(path_str)
            if not (current.is_absolute() and str(current).startswith(str(root))):
                current = root / path_str.lstrip("\\/")
        else:
            current = root
        if not current.exists():
            return {"ok": True, "children": []}
        return {"ok": True, "children": self._list_dirs(current)}

    @staticmethod
    def _list_dirs(path: Path, depth: int = 0, max_depth: int = 1) -> list[dict]:
        if depth > max_depth:
            return []
        skip = {".git", "__pycache__", "node_modules", ".sync",
                "System Volume Information", "$RECYCLE.BIN"}
        try:
            entries = sorted(
                [e for e in path.iterdir() if e.is_dir() and e.name not in skip],
                key=lambda e: e.name.lower(),
            )
        except OSError:
            return []
        result = []
        for entry in entries[:80]:
            has_children = False
            try:
                has_children = any(
                    c.is_dir() and c.name not in skip for c in entry.iterdir()
                )
            except OSError:
                pass
            item = {"name": entry.name, "path": str(entry), "children": []}
            if has_children:
                item["children"] = [{"name": "…", "path": str(entry), "children": []}]
            result.append(item)
        return result

    def library_cards(self, path_str: str) -> dict:
        """Load cards from SQLite index when available, fall back to quick scan."""
        settings = self.get_settings()
        root_str = settings.get("resource_root", "")
        if not root_str:
            return {"ok": True, "cards": []}
        root = Path(root_str).expanduser()
        if path_str:
            current = Path(path_str)
            if not (current.is_absolute() and str(current).startswith(str(root))):
                current = root / path_str.lstrip("\\/")
        else:
            current = root
        if not current.exists():
            return {"ok": True, "cards": []}
        try:
            idx = self.resource_index
            cached = idx.load_child_cards(current, max_cards=120)
            cards = cached if (cached and len(cached) > 0) else quick_cards_for_path(current)
            # Annotate each card with library context
            for card in cards:
                self._annotate_library_card(card, root)
            self.store.replace_library(cards)
            self._start_background_preload(current)
            cached_flag = bool(cached and len(cached) > 0)
            return {
                "ok": True,
                "cards": self.store.serialise_list(
                    self.store.library_as_list()
                ),
                "cached": cached_flag,
            }
        except Exception as e:
            return {"ok": True, "cards": [], "error": str(e)}

    @staticmethod
    def _annotate_library_card(card: dict, root: Path) -> None:
        """Infer type and target from folder position, matching _classify_library_quick_card."""
        src = card.get("source_path", "")
        if not src:
            return
        src_path = Path(src)

        # Try relative_to; if paths use different representations (UNC vs drive letter),
        # compare resolved absolute forms
        rel_parts = []
        try:
            rel = str(src_path.relative_to(root))
            rel_parts = [p for p in rel.replace("\\", "/").split("/") if p]
        except ValueError:
            # Resolve both and compare by path components
            try:
                src_parts = src_path.resolve().parts
                root_parts = root.resolve().parts
            except (OSError, RuntimeError):
                return
            if len(src_parts) > len(root_parts) and src_parts[:len(root_parts)] == root_parts:
                rel_parts = list(src_parts[len(root_parts):])
            else:
                return

        if not rel_parts:
            return

        # Infer type from top-level folder
        top = rel_parts[0].lower()
        media_type = str(card.get("media_type") or "").lower()
        content_type_map = {"video": "video", "model": "model", "zbrush": "zbrush", "engine": "ue"}
        resource_type = content_type_map.get(media_type, "unknown")
        if resource_type == "unknown":
            if top.startswith("j "):
                resource_type = "tutorial"
            elif top.startswith("m "):
                resource_type = "model"
            elif top.startswith("u "):
                resource_type = "ue"
            elif top.startswith("c "):
                resource_type = "material"
            elif top.startswith("a "):
                resource_type = "alpha"
            elif top.startswith("b "):
                resource_type = "brush"
            elif top.startswith("z zb"):
                resource_type = "zbrush"
            elif top.startswith("z "):
                resource_type = "photo"

        if resource_type != "unknown":
            card["suggested_type"] = resource_type
            card["confidence"] = "high"
            card["needs_human_review"] = False

        # library_target_path: parent dir relative to root
        if len(rel_parts) >= 2:
            card["library_target_path"] = str(root / "/".join(rel_parts[:-1]))
        else:
            card["library_target_path"] = str(root)
        card["target_path_hints"] = [card["library_target_path"]]
        card["is_library_card"] = True

        # Short display label: top category + all intermediate parents (up to 4 levels)
        parent_parts = rel_parts[:-1] if len(rel_parts) > 1 else rel_parts
        display_parts = [parent_parts[0]]
        # Add meaningful intermediate levels, skip duplicates
        for p in parent_parts[1:]:
            if p not in display_parts:
                display_parts.append(p)
        if len(display_parts) > 4:
            display_parts = display_parts[:1] + display_parts[-3:]
        card["library_display"] = " / ".join(display_parts)

    def _start_background_preload(self, path: Path) -> None:
        def _run():
            try:
                idx = self.resource_index
                idx.index_children(path, max_children=240)
                cached = idx.load_child_cards(path, max_cards=120)
                for card in cached:
                    try:
                        prepare_preview_image(card, self._preview_cache_dir, size=(400, 600), preserve_aspect=True)
                    except Exception:
                        pass
                # Preload deeper levels (up to 3 deep)
                self._preload_deeper(path, depth=0, max_depth=2)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _preload_deeper(self, path: Path, depth: int, max_depth: int) -> None:
        if depth >= max_depth:
            return
        try:
            skip = {".git", "__pycache__", "node_modules", ".sync"}
            children = sorted(
                [c for c in path.iterdir() if c.is_dir() and c.name not in skip],
                key=lambda c: c.name.lower()
            )[:20]
            idx = self.resource_index
            for child in children:
                try:
                    idx.index_children(child, max_children=60)
                    cards = idx.load_child_cards(child, max_cards=40)
                    for card in cards[:10]:
                        try:
                            prepare_preview_image(card, self._preview_cache_dir, size=(400, 600), preserve_aspect=True)
                        except Exception:
                            pass
                    self._preload_deeper(child, depth + 1, max_depth)
                except Exception:
                    continue
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # Preview
    # ═══════════════════════════════════════════════════════════════

    def preview(self, card_id: str) -> dict:
        """Generate a thumbnail for *card_id*."""
        card = self.store.get_work(card_id) or self.store.get_library(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        try:
            r = prepare_preview_image(card, self._preview_cache_dir, size=(400, 600), preserve_aspect=True)
            if r.get("ok"):
                return {
                    "ok": True,
                    "url": f"/preview-file/{Path(r['path']).name}",
                }
            return {"ok": False, "error": r.get("error", "预览生成失败")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Translation
    # ═══════════════════════════════════════════════════════════════

    def translate(self, card_id: str) -> dict:
        card = self.store.get_work(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        s = self.get_settings()
        key = deepseek_api_key(s)
        if not key:
            return {"ok": False, "error": "未设置 API Key"}
        try:
            r = request_structured_card_suggestion(card, s)
            if r.get("ok") and r.get("suggestion"):
                sug = r["suggestion"]
                updates = {
                    "translated_name": sug.get("translated_name", ""),
                    "target_path": sug.get("target_path", ""),
                    "confidence": sug.get("confidence", ""),
                    "review_reason": sug.get("review_reason", ""),
                }
                # Update display name
                if sug.get("translated_name"):
                    name_mode = s.get("translation_name_mode", "zh_en")
                    original = card.get("display_name") or card.get("name", "")
                    if name_mode == "zh_en":
                        updates["display_name"] = f"{sug['translated_name']} {original}"
                    elif name_mode == "en_zh":
                        updates["display_name"] = f"{original} {sug['translated_name']}"
                    else:
                        updates["display_name"] = sug["translated_name"]
                self.store.update_work(card_id, updates)
                # Rename local folder if enabled
                if s.get("rename_local_after_translate") and sug.get("translated_name"):
                    src = card.get("source_path", "")
                    if src:
                        import traceback
                        try:
                            result = rename_folder(Path(src), sug["translated_name"], self.rename_log)
                            if result.get("ok"):
                                card["source_path"] = result.get("path", src)
                        except Exception as e:
                            traceback.print_exc()
                            warnings_list = r.get("_rename_warnings", [])
                            if not isinstance(warnings_list, list):
                                r["_rename_warnings"] = []
                                warnings_list = r["_rename_warnings"]
                            warnings_list.append(f"重命名失败: {e}")
                return {"ok": True, "suggestion": sug, "card_id": card_id}
            return {"ok": False, "error": r.get("error", "翻译失败")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def translate_all(self) -> dict:
        """Batch translate all work cards.  Runs async."""
        task = self.tasks.start(TaskKind.TRANSLATE_ALL, "批量翻译")

        def _run():
            order = list(self.store.work_order)
            total = len(order)
            ok_count = 0
            for i, cid in enumerate(order):
                if task.cancelled:
                    break
                r = self.translate(cid)
                if r.get("ok"):
                    ok_count += 1
                self.tasks.update_progress((i + 1) / total,
                                           f"已翻译 {i+1}/{total}")
            self.tasks.finish({"total": total, "ok": ok_count})

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "task": task.kind.value, "busy": True}

    # ═══════════════════════════════════════════════════════════════
    # Move
    # ═══════════════════════════════════════════════════════════════

    def plan_card_move(self, card_id: str, target_path: str) -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        src = Path(str(card.get("source_path", "")))
        if not src.exists():
            return {"ok": False, "error": "来源不存在: " + str(src)}
        s = self.get_settings()
        z_root_str = s.get("resource_root", "")
        z_root = Path(z_root_str) if z_root_str and Path(z_root_str).exists() else (self.data_root / "library")
        try: z_root.mkdir(parents=True, exist_ok=True)
        except Exception: pass
        try:
            move_card = dict(card)
            if target_path:
                move_card["user_target_path"] = target_path
            plan = plan_move(
                move_card,
                source_roots=[src.parent],
                destination_root=Path(target_path).parent if target_path else z_root,
                z_root=z_root,
                formal=True,
            )
            if plan.get("ok"):
                return {
                    "ok": True,
                    "detail": f"【预演】{src.name} → {target_path}",
                    "source": str(src),
                    "destination": plan.get("destination", ""),
                    "file_count": plan.get("file_count", 0),
                }
            return plan
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def execute_move(self, card_id: str, target_path: str) -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        src = Path(str(card.get("source_path", "")))
        s = self.get_settings()
        z_root = Path(s.get("resource_root", "")) or (self.data_root / "library")
        try:
            move_card = dict(card)
            if target_path:
                move_card["user_target_path"] = target_path
            plan = plan_move(
                move_card,
                source_roots=[src.parent],
                destination_root=Path(target_path).parent if target_path else z_root,
                z_root=z_root,
                formal=True,
            )
            if not plan.get("ok"):
                return plan
            result = execute_formal_move(
                move_card,
                source_roots=[src.parent],
                z_root=z_root,
                move_log=self.move_log,
            )
            if result.get("ok"):
                try:
                    self.review_queue.upsert(card, status="moved")
                except Exception:
                    pass
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Target Recommendation
    # ═══════════════════════════════════════════════════════════════

    def recommend_target(self, card_id: str) -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        s = self.get_settings()
        root = Path(s.get("resource_root", ""))
        if not root.exists():
            return {"ok": True, "recommendations": []}
        try:
            recs = recommend_target_folders(card, root, move_log=self.move_log)
            if recs.get("ok"):
                return {
                    "ok": True,
                    "recommendations": [
                        {"path": c["path"], "name": c["name"], "relative": c.get("relative", "")}
                        for c in recs.get("candidates", [])[:10]
                    ],
                }
            return {"ok": True, "recommendations": []}
        except Exception as e:
            return {"ok": True, "recommendations": [], "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Review Queue
    # ═══════════════════════════════════════════════════════════════

    def get_review_queue(self) -> dict:
        try:
            items = self.review_queue.list_items()
            return {"ok": True, "items": items, "total": len(items)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def update_review_item(self, card_id: str, status: str) -> dict:
        card = self.store.get_work(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        try:
            self.review_queue.upsert(card, status=status)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # History
    # ═══════════════════════════════════════════════════════════════

    def get_history(self) -> dict:
        """Return recent move + rename logs."""
        try:
            moves = self.move_log.list_records()[:50]
        except Exception:
            moves = []
        try:
            renames = self.rename_log.list_records()[:50]
        except Exception:
            renames = []
        return {"ok": True, "moves": moves, "renames": renames}

    # ═══════════════════════════════════════════════════════════════
    # Maintenance
    # ═══════════════════════════════════════════════════════════════

    def find_duplicates(self) -> dict:
        try:
            groups = _find_duplicates(self.project_root)
            return {"ok": True, "count": len(groups), "groups": groups[:20]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cleanup_empty_dirs(self) -> dict:
        try:
            r = _remove_empty_dirs(self.project_root)
            return {"ok": True, "removed": r.get("removed", []), "count": r.get("count", 0)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_folder(self, path_str: str) -> dict:
        import os
        p = Path(path_str)
        if p.exists():
            os.startfile(str(p))
            return {"ok": True}
        return {"ok": False, "error": "路径不存在"}

    # ═══════════════════════════════════════════════════════════════
    # Web Resource
    # ═══════════════════════════════════════════════════════════════

    def create_web_card(self, url: str) -> dict:
        """Create a resource card from a web URL."""
        try:
            cache_dir = self.data_root / "_web_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            card = create_web_resource_card(url, cache_dir)
            card["card_id"] = self.store.card_id(card)
            return {"ok": True, "card": self.store.serialise_list([card])[0]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Undo
    # ═══════════════════════════════════════════════════════════════

    def undo(self, kind: str, record_id: str) -> dict:
        if kind == "move":
            try:
                result = undo_move(record_id, self.move_log)
                return {"ok": result.get("ok", False), **(result if isinstance(result, dict) else {})}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        elif kind == "rename":
            return {"ok": False, "error": "重命名撤销暂未实现"}
        return {"ok": False, "error": f"未知操作类型: {kind}"}

    # ═══════════════════════════════════════════════════════════════
    # Format
    # ═══════════════════════════════════════════════════════════════

    def format_card(self, card_id: str, apply: bool = False) -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        src = card.get("source_path", "")
        if not src:
            return {"ok": False, "error": "无来源路径"}
        path = Path(src)
        if not path.exists():
            return {"ok": False, "error": "来源不存在"}
        try:
            if apply:
                result = apply_cover_project(path)
                return {"ok": result.get("ok", False), **(result if isinstance(result, dict) else {})}
            plan = plan_cover_project(path)
            return {"ok": True, "plan": plan}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Metadata
    # ═══════════════════════════════════════════════════════════════

    def save_metadata(self, card_id: str, tags: list, note: str = "") -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        try:
            store = CardMetadataStore(default_metadata_path(self.data_root))
            cid = card.get("card_id", card_id)
            if tags is not None:
                card["manual_tags"] = list(tags)
            if note is not None:
                card["manual_note"] = str(note)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def mark_review(self, card_id: str, note: str = "") -> dict:
        card = self.store.get_any(card_id)
        if card is None:
            return {"ok": False, "error": "卡片不存在"}
        card["needs_human_review"] = True
        if note:
            card["review_note"] = str(note)
        return {"ok": True}

    # ═══════════════════════════════════════════════════════════════
    # Test DeepSeek
    # ═══════════════════════════════════════════════════════════════

    def test_deepseek(self, api_key: str = "") -> dict:
        from ..deepseek import test_deepseek_connection
        s = self.get_settings()
        if api_key:
            s = dict(s)
            s["_secret_file"] = ""
            import os
            os.environ["DEEPSEEK_API_KEY"] = api_key
        try:
            result = test_deepseek_connection(s)
            return {"ok": result.get("ok", False), "error": result.get("error", "")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Overview
    # ═══════════════════════════════════════════════════════════════

    def get_overview(self) -> dict:
        return {
            "ok": True,
            "work_cards": self.store.work_count,
            "library_cards": self.store.library_count,
            "version": __version__,
        }

    # ═══════════════════════════════════════════════════════════════
    # Task status
    # ═══════════════════════════════════════════════════════════════

    def task_status(self) -> dict:
        return self.tasks.status_dict()

    def app_status(self) -> dict:
        return {
            "ok": True,
            "version": __version__,
            "work_cards": self.store.work_count,
            "library_cards": self.store.library_count,
        }


# Singleton
_service: ApplicationService | None = None


def get_service() -> ApplicationService:
    global _service
    if _service is None:
        _service = ApplicationService()
    return _service
