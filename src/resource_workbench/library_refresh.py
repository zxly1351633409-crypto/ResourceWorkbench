"""Small, Qt-free helpers for refreshing and editing a resource library tree.

The UI may call these helpers from a worker or a debounced timer.  They avoid
walking descendants and convert expected filesystem failures into stable,
comparable result objects instead of leaking exceptions into Qt callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ntpath
import os
from pathlib import Path
import posixpath
import stat as stat_module
from typing import Iterable, TypeAlias


PathLike: TypeAlias = str | os.PathLike[str]

_WINDOWS_INVALID_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    "CONIN$",
    "CONOUT$",
}
_WINDOWS_RESERVED_NAMES.update(f"COM{digit}" for digit in "123456789¹²³")
_WINDOWS_RESERVED_NAMES.update(f"LPT{digit}" for digit in "123456789¹²³")


@dataclass(frozen=True, slots=True)
class NameValidationResult:
    ok: bool
    name: str = ""
    error_code: str = ""
    error_message: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class LibraryChildResult:
    ok: bool
    parent: Path | None = None
    target: Path | None = None
    library_root: Path | None = None
    error_code: str = ""
    error_message: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class DirectChildState:
    name: str
    is_dir: bool
    mtime_ns: int
    size: int


@dataclass(frozen=True, slots=True)
class DirectorySignature:
    path: str
    status: str
    entries: tuple[DirectChildState, ...] = ()
    error_message: str = field(default="", compare=False)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True, slots=True)
class MkdirResult:
    ok: bool
    created: bool = False
    path: Path | None = None
    library_root: Path | None = None
    error_code: str = ""
    error_message: str = field(default="", compare=False)


def validate_windows_directory_name(name: object) -> NameValidationResult:
    """Validate one Windows path component without silently rewriting it."""

    if not isinstance(name, str):
        return NameValidationResult(False, error_code="not_text", error_message="文件夹名称必须是文本。")
    if not name or not name.strip():
        return NameValidationResult(False, name=name, error_code="empty", error_message="文件夹名称不能为空。")
    if name in {".", ".."}:
        return NameValidationResult(False, name=name, error_code="relative_component", error_message="不能使用 . 或 ..。")
    if len(name) > 255:
        return NameValidationResult(False, name=name, error_code="too_long", error_message="文件夹名称不能超过 255 个字符。")
    if name[-1] in {" ", "."}:
        return NameValidationResult(
            False,
            name=name,
            error_code="trailing_dot_or_space",
            error_message="文件夹名称不能以空格或句点结尾。",
        )
    if any(character in _WINDOWS_INVALID_CHARS or ord(character) < 32 for character in name):
        return NameValidationResult(
            False,
            name=name,
            error_code="invalid_character",
            error_message='文件夹名称不能包含 < > : " / \\ | ? * 或控制字符。',
        )

    # Windows reserves device names even when an extension is appended, e.g.
    # ``CON.txt``.  Rstrip also covers spellings Windows normalizes itself.
    device_stem = name.split(".", 1)[0].rstrip(" .").upper()
    if device_stem in _WINDOWS_RESERVED_NAMES:
        return NameValidationResult(
            False,
            name=name,
            error_code="reserved_name",
            error_message=f"{name} 是 Windows 保留名称。",
        )
    return NameValidationResult(True, name=name)


def resolve_library_child(
    parent: PathLike,
    name: object,
    library_roots: Iterable[PathLike],
) -> LibraryChildResult:
    """Resolve a prospective child and prove its parent is inside a root.

    The prospective child need not exist.  Existing local path prefixes are
    resolved so junction/symlink escapes are not accepted.  UNC paths are
    normalized lexically to avoid blocking on a disconnected NAS merely to
    perform the containment check.
    """

    validated = validate_windows_directory_name(name)
    if not validated.ok:
        return LibraryChildResult(
            False,
            error_code=validated.error_code,
            error_message=validated.error_message,
        )

    try:
        parent_text, windows_style = _canonical_path(parent)
    except (TypeError, ValueError, OSError) as exc:
        return LibraryChildResult(False, error_code="invalid_parent", error_message=str(exc))

    roots: list[tuple[str, bool]] = []
    for raw_root in library_roots:
        if not str(raw_root).strip():
            continue
        try:
            root_text, root_windows_style = _canonical_path(raw_root)
        except (TypeError, ValueError, OSError):
            continue
        if root_windows_style == windows_style:
            roots.append((root_text, root_windows_style))

    if not roots:
        return LibraryChildResult(
            False,
            parent=Path(parent_text),
            error_code="no_library_roots",
            error_message="没有可用于校验的资源库根目录。",
        )

    matching = [root for root, _style in roots if _is_within(parent_text, root, windows_style)]
    if not matching:
        return LibraryChildResult(
            False,
            parent=Path(parent_text),
            error_code="outside_library_roots",
            error_message="目标父目录不在已配置的资源库根目录内。",
        )

    # Prefer the most specific configured root when roots are nested.
    matched_root = max(matching, key=lambda value: len(_path_parts(value, windows_style)))
    path_module = ntpath if windows_style else posixpath
    target_text = path_module.normpath(path_module.join(parent_text, validated.name))
    return LibraryChildResult(
        True,
        parent=Path(parent_text),
        target=Path(target_text),
        library_root=Path(matched_root),
    )


def direct_child_signature(directory: PathLike) -> DirectorySignature:
    """Return a deterministic, non-recursive signature for one directory."""

    raw_path = os.fspath(directory)
    try:
        canonical, _windows_style = _canonical_path(directory)
    except (TypeError, ValueError, OSError):
        canonical = str(raw_path)

    entries: list[DirectChildState] = []
    try:
        with os.scandir(raw_path) as iterator:
            for entry in iterator:
                try:
                    item_stat = entry.stat(follow_symlinks=False)
                except FileNotFoundError as exc:
                    return DirectorySignature(canonical, "changed_during_scan", error_message=str(exc))
                except PermissionError as exc:
                    return DirectorySignature(canonical, "permission_denied", error_message=str(exc))
                except OSError as exc:
                    return DirectorySignature(
                        canonical,
                        _os_error_status(exc),
                        error_message=str(exc),
                    )
                entries.append(
                    DirectChildState(
                        name=entry.name,
                        is_dir=stat_module.S_ISDIR(item_stat.st_mode),
                        mtime_ns=getattr(item_stat, "st_mtime_ns", int(item_stat.st_mtime * 1_000_000_000)),
                        size=item_stat.st_size,
                    )
                )
    except FileNotFoundError as exc:
        return DirectorySignature(canonical, "missing", error_message=str(exc))
    except NotADirectoryError as exc:
        return DirectorySignature(canonical, "not_directory", error_message=str(exc))
    except PermissionError as exc:
        return DirectorySignature(canonical, "permission_denied", error_message=str(exc))
    except OSError as exc:
        return DirectorySignature(canonical, _os_error_status(exc), error_message=str(exc))

    entries.sort(key=lambda item: (item.name.casefold(), item.name))
    return DirectorySignature(canonical, "ok", tuple(entries))


def safe_mkdir(
    parent: PathLike,
    name: object,
    library_roots: Iterable[PathLike],
) -> MkdirResult:
    """Create exactly one validated child directory with ``exist_ok=False``."""

    checked = resolve_library_child(parent, name, library_roots)
    if not checked.ok or checked.target is None:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code=checked.error_code,
            error_message=checked.error_message,
        )

    try:
        checked.target.mkdir(exist_ok=False)
    except FileExistsError as exc:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code="already_exists",
            error_message=str(exc),
        )
    except FileNotFoundError as exc:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code="parent_missing",
            error_message=str(exc),
        )
    except NotADirectoryError as exc:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code="parent_not_directory",
            error_message=str(exc),
        )
    except PermissionError as exc:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code="permission_denied",
            error_message=str(exc),
        )
    except OSError as exc:
        return MkdirResult(
            False,
            path=checked.target,
            library_root=checked.library_root,
            error_code=_os_error_status(exc),
            error_message=str(exc),
        )
    return MkdirResult(True, created=True, path=checked.target, library_root=checked.library_root)


def _canonical_path(path: PathLike) -> tuple[str, bool]:
    raw = os.path.expandvars(os.path.expanduser(os.fspath(path))).strip()
    if not raw:
        raise ValueError("路径不能为空。")

    windows_style = os.name == "nt" or _looks_like_windows_absolute(raw)
    if windows_style:
        normalized = ntpath.normpath(raw.replace("/", "\\"))
        if not ntpath.isabs(normalized):
            raise ValueError("资源库路径必须是绝对路径。")
        # Avoid touching a potentially disconnected NAS during a UI refresh.
        # Local existing prefixes still get realpath/junction resolution.
        if os.name == "nt" and not _is_unc_path(normalized):
            normalized = ntpath.normpath(str(Path(normalized).resolve(strict=False)))
        return normalized, True

    normalized = posixpath.normpath(raw)
    if not posixpath.isabs(normalized):
        raise ValueError("资源库路径必须是绝对路径。")
    return str(Path(normalized).resolve(strict=False)), False


def _looks_like_windows_absolute(path: str) -> bool:
    drive, _tail = ntpath.splitdrive(path)
    return bool(drive) or _is_unc_path(path)


def _is_unc_path(path: str) -> bool:
    return path.startswith(("\\\\", "//"))


def _is_within(path: str, root: str, windows_style: bool) -> bool:
    path_module = ntpath if windows_style else posixpath
    path_key = path_module.normcase(path) if windows_style else path
    root_key = path_module.normcase(root) if windows_style else root
    try:
        return path_module.commonpath((path_key, root_key)) == root_key
    except ValueError:
        return False


def _path_parts(path: str, windows_style: bool) -> tuple[str, ...]:
    if windows_style:
        drive, tail = ntpath.splitdrive(path)
        parts = tuple(part for part in tail.replace("/", "\\").split("\\") if part)
        return ((drive.casefold(),) + parts) if drive else parts
    return tuple(part for part in path.split("/") if part)


def _os_error_status(exc: OSError) -> str:
    return f"os_error:{exc.errno}" if exc.errno is not None else "os_error"
