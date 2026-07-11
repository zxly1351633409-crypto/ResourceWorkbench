from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from .move_log import (
    STATUS_REVERT_FAILED,
    STATUS_REVERTED,
    MoveLog,
    count_tree,
)


def plan_move(
    card: dict,
    source_roots: Iterable[Path],
    destination_root: Path,
    z_root: Path,
    *,
    formal: bool = False,
) -> dict:
    """Build a safe move plan without touching files."""
    source = Path(str(card.get("source_path") or ""))
    if not source.exists():
        return {"ok": False, "error": "来源路径不存在。"}

    source_resolved = source.resolve()
    allowed_roots = [Path(root).resolve() for root in source_roots if str(root).strip()]
    if not allowed_roots:
        return {"ok": False, "error": "安全限制/瀹夊叏闄愬埗：没有配置允许移动的来源根目录。"}
    if not any(_within_or_equal(source_resolved, root) for root in allowed_roots):
        roots = "\n".join(str(root) for root in allowed_roots)
        return {
            "ok": False,
            "error": f"安全限制/瀹夊叏闄愬埗：来源不在允许移动的根目录内。\n允许来源：\n{roots}",
        }

    destination_root = Path(destination_root).resolve()
    z_root = Path(z_root).resolve()
    try:
        target_dir = _target_dir_for_card(
            card,
            destination_root,
            z_root,
            require_z_target=formal,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    target_resolved = target_dir.resolve()
    required_root = z_root if formal else destination_root
    if not _within_or_equal(target_resolved, required_root):
        return {
            "ok": False,
            "error": f"安全限制/瀹夊叏闄愬埗：目标目录越界。\n目标：{target_resolved}\n根目录：{required_root}",
        }
    try:
        source_parent = source_resolved.parent.resolve()
    except OSError:
        source_parent = source_resolved.parent
    if formal and target_resolved == source_parent:
        return {
            "ok": False,
            "error": f"来源已经位于目标目录内，无需正式移动。\n目标：{target_resolved}",
        }

    pre_files, pre_bytes = count_tree(source_resolved)
    destination = _unique_destination(target_dir / source.name)
    learning_target = _target_dir_for_card(card, z_root, z_root)
    return {
        "ok": True,
        "dry_run": True,
        "formal": formal,
        "source": str(source_resolved),
        "destination": str(destination),
        "target_dir": str(target_dir),
        # 测试移动的真实落点在 test_moves 下，但学习系统应记住用户选择的资源库分类。
        "learning_target": str(learning_target),
        "file_count": pre_files,
        "byte_count": pre_bytes,
        "allowed_roots": [str(root) for root in allowed_roots],
    }


def execute_move(
    card: dict,
    source_roots: Iterable[Path],
    destination_root: Path,
    z_root: Path,
    *,
    move_log: MoveLog | None = None,
    dry_run: bool = False,
    formal: bool = False,
) -> dict:
    """Move a resource using the same plan that can be previewed in the UI."""
    plan = plan_move(
        card,
        source_roots,
        destination_root,
        z_root,
        formal=formal,
    )
    if not plan.get("ok"):
        return plan
    if dry_run:
        return plan

    source_resolved = Path(plan["source"])
    target_dir = Path(plan["target_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(target_dir / source_resolved.name)
    try:
        shutil.move(str(source_resolved), str(destination))
    except (OSError, shutil.Error) as exc:
        return {"ok": False, "error": f"移动失败：{exc}"}

    post_files, post_bytes = count_tree(destination)
    verified = int(plan["file_count"]) == post_files and int(plan["byte_count"]) == post_bytes

    move_id = None
    if move_log is not None:
        note_prefix = "formal" if formal else "test"
        note = "" if verified else "数量/容量校验不一致，请人工复核。"
        move_id = move_log.record_move(
            source=str(source_resolved),
            destination=str(destination),
            file_count=int(plan["file_count"]),
            byte_count=int(plan["byte_count"]),
            dest_file_count=post_files,
            dest_byte_count=post_bytes,
            verified=verified,
            card_id=str(card.get("card_id") or ""),
            note=f"[{note_prefix}] {note}".strip(),
            card=card,
            target_directory=str(plan.get("learning_target") or target_dir),
            move_kind=note_prefix,
        )

    result = dict(plan)
    result.update(
        {
            "ok": True,
            "dry_run": False,
            "move_id": move_id,
            "destination": str(destination),
            "dest_file_count": post_files,
            "dest_byte_count": post_bytes,
            "verified": verified,
        }
    )
    return result


def execute_test_move(
    card: dict,
    source_root: Path,
    test_move_root: Path,
    z_root: Path,
    move_log: MoveLog | None = None,
) -> dict:
    """Move into the test landing root with rollback logging."""
    return execute_move(
        card,
        [source_root],
        test_move_root,
        z_root,
        move_log=move_log,
        formal=False,
    )


def execute_formal_move(
    card: dict,
    source_roots: Iterable[Path],
    z_root: Path,
    move_log: MoveLog | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Move directly into the resource library root with safety checks."""
    return execute_move(
        card,
        source_roots,
        z_root,
        z_root,
        move_log=move_log,
        dry_run=dry_run,
        formal=True,
    )


def undo_move(move_id: str, move_log: MoveLog) -> dict:
    """Undo one logged move by moving the destination back to the source path."""
    record = move_log.get(move_id)
    if record is None:
        return {"ok": False, "error": f"找不到移动记录：{move_id}"}
    if record.get("status") != "moved":
        return {"ok": False, "error": f"该记录状态为 {record.get('status')}，不可撤销。"}

    destination = Path(record["destination"])
    source = Path(record["source"])
    if not destination.exists():
        move_log.set_status(move_id, STATUS_REVERT_FAILED, note="目标已不存在，无法撤销。")
        return {"ok": False, "error": "目标路径已不存在，无法撤销。"}
    if source.exists():
        move_log.set_status(move_id, STATUS_REVERT_FAILED, note="原来源已被占用，无法撤销。")
        return {"ok": False, "error": "原来源路径已存在，撤销会覆盖，已中止。"}

    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))
    except (OSError, shutil.Error) as exc:
        move_log.set_status(move_id, STATUS_REVERT_FAILED, note=f"撤销失败：{exc}")
        return {"ok": False, "error": f"撤销失败：{exc}"}

    post_files, post_bytes = count_tree(source)
    verified = post_files == record["file_count"] and post_bytes == record["byte_count"]
    move_log.set_status(
        move_id,
        STATUS_REVERTED,
        note="" if verified else "撤销后数量/容量校验不一致，请人工复核。",
    )
    return {
        "ok": True,
        "move_id": move_id,
        "restored_to": str(source),
        "verified": verified,
    }


def _target_dir_for_card(
    card: dict,
    destination_root: Path,
    z_root: Path,
    *,
    require_z_target: bool = False,
) -> Path:
    target = str(card.get("user_target_path") or "")
    if not target:
        hints = card.get("target_path_hints") or []
        target = str(hints[0]) if hints else ""
    if target:
        target_path = Path(target)
        if target_path.is_absolute():
            try:
                relative = target_path.resolve().relative_to(z_root)
                return destination_root / relative
            except (OSError, ValueError):
                relative_parts = _library_relative_parts(target_path, z_root)
                if relative_parts:
                    return destination_root.joinpath(*relative_parts)
                if require_z_target:
                    raise ValueError(f"正式移动目标必须位于资源库根路径内：{z_root}") from None
                return destination_root / target_path.name
        return destination_root / target_path
    suggested_type = str(card.get("suggested_type") or "未分类")
    return destination_root / suggested_type


def _library_relative_parts(target_path: Path, z_root: Path) -> list[str]:
    """Accept shortened library paths such as Z:\\M 模型\\K 科幻.

    DeepSeek or manual text may omit the configured library root folder name
    ("整合——资源管理"). In formal move mode we still keep the destination inside
    z_root by treating known top-level library sections as relative paths.
    """
    parts = [part for part in target_path.parts if part and part != target_path.anchor]
    if not parts:
        return []
    root_name = Path(z_root).name
    if root_name in parts:
        index = parts.index(root_name)
        return parts[index + 1 :]
    first = parts[0].lower()
    prefixes = ("a ", "b ", "c ", "j ", "m ", "u ", "z ")
    if first.startswith(prefixes) or parts[0] in {"A", "B", "C", "J", "M", "U", "Z"}:
        return parts
    return []


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    if path.is_dir():
        stem = path.name
        suffix = ""
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _within_or_equal(path: Path, root: Path) -> bool:
    return path == root or _is_relative_to(path, root)
