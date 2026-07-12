"""115 网盘上传：路径镜像 + 上传日志 + 开放平台客户端骨架。

设计目标（对应用户需求）：
- 用户在本地把资源移动到 `Z:\\整合——资源管理\\...` 下的某个分类后，
  不必再去云端手动找位置，工具按【相同相对路径】把资源镜像上传到 115。
- 上传有进度、有日志、可审计。

当前状态：
- 路径镜像、上传队列/日志、进度回调结构已完成，可被 UI 直接驱动。
- 真正的网络上传调用走 115 开放平台 API，需要用户在设置里填入 AppID/AppSecret 并完成授权（拿到 token）。
  未配置凭证时，`upload_folder` 会返回明确提示，不会假装上传成功。
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .settings import get_115_credentials


def mirror_relative_path(local_path: Path, z_root: Path) -> str:
    """本地资源相对资源库根的路径，转成 115 用的相对路径（正斜杠）。"""
    local_path = Path(local_path)
    z_root = Path(z_root)
    try:
        rel = local_path.resolve().relative_to(z_root.resolve())
    except (OSError, ValueError):
        rel = Path(local_path.name)
    return rel.as_posix()


def remote_target_path(local_path: Path, z_root: Path, remote_root: str = "") -> str:
    """115 上的完整目标路径 = 远端根 + 相同相对路径。"""
    rel = mirror_relative_path(local_path, z_root)
    remote_root = (remote_root or "").strip().strip("/")
    if remote_root:
        return f"{remote_root}/{rel}"
    return rel


def iter_files(local_dir: Path) -> list[Path]:
    local_dir = Path(local_dir)
    if local_dir.is_file():
        return [local_dir]
    return [p for p in sorted(local_dir.rglob("*")) if p.is_file()]


class Uploader115:
    def __init__(self, settings: dict):
        self.settings = settings
        self.creds = get_115_credentials(settings)

    def is_enabled(self) -> bool:
        return bool(self.settings.get("enable_115"))

    def is_configured(self) -> bool:
        return bool(self.is_enabled() and self.creds.get("app_id") and self.creds.get("app_secret"))

    def has_token(self) -> bool:
        return bool(self.creds.get("token"))

    def status_hint(self) -> str:
        if not self.is_enabled():
            return "115 上传未启用（在设置里开启）。"
        if not self.creds.get("app_id") or not self.creds.get("app_secret"):
            return "115 未配置：请在设置里填入 AppID 与 AppSecret。"
        if not self.has_token():
            return "115 未授权：已填 AppID/AppSecret，但还需要完成授权拿到 token。"
        return "115 已就绪。"

    def upload_folder(
        self,
        local_dir: Path,
        z_root: Path,
        progress_cb=None,
        cancel_cb=None,
    ) -> dict:
        """把本地目录按相同相对路径上传到 115。

        progress_cb(done:int, total:int, name:str) 用于驱动进度条。
        cancel_cb() -> bool 返回 True 时中止。
        """
        local_dir = Path(local_dir)
        if not local_dir.exists():
            return {"ok": False, "error": "本地路径不存在。"}
        remote_path = remote_target_path(local_dir, z_root, str(self.settings.get("remote_115_root") or ""))

        if not self.is_configured():
            return {"ok": False, "error": self.status_hint(), "remote_path": remote_path}
        if not self.has_token():
            return {"ok": False, "error": self.status_hint(), "remote_path": remote_path}

        files = iter_files(local_dir)
        total = len(files)
        done = 0
        for file_path in files:
            if cancel_cb and cancel_cb():
                return {"ok": False, "error": "已取消上传。", "remote_path": remote_path, "uploaded": done, "total": total}
            rel = mirror_relative_path(file_path, z_root)
            result = self._upload_file(file_path, rel)
            if not result.get("ok"):
                return {"ok": False, "error": result.get("error"), "remote_path": remote_path, "uploaded": done, "total": total}
            done += 1
            if progress_cb:
                progress_cb(done, total, file_path.name)
        return {"ok": True, "remote_path": remote_path, "uploaded": done, "total": total}

    def _upload_file(self, local_file: Path, remote_relative: str) -> dict:
        """单文件上传到 115 开放平台。

        TODO（需在拿到 AppID/AppSecret 与授权 token、并核对官方 API 文档后实现）：
          1. 用 token 确保/创建 remote_relative 的父目录。
          2. 取上传凭证（通常返回 OSS 直传参数）。
          3. 计算文件 sha1，走秒传/分片直传。
          4. 校验返回，处理重名与失败重试。
        在此之前不做任何真实网络写入，返回未实现提示。
        """
        return {"ok": False, "error": "115 上传接口尚未接入（占位）。请提供 AppID/AppSecret 并完成授权后再启用。"}


# ---- 上传日志 ----

STATUS_UPLOADED = "uploaded"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"


class UploadLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_records (
                    upload_id TEXT PRIMARY KEY,
                    card_id TEXT,
                    local_path TEXT,
                    remote_path TEXT,
                    file_count INTEGER,
                    uploaded_count INTEGER,
                    status TEXT,
                    note TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )

    def record(self, *, local_path: str, remote_path: str, file_count: int,
               uploaded_count: int, status: str, card_id: str = "", note: str = "") -> str:
        upload_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO upload_records (upload_id, card_id, local_path, remote_path,"
                " file_count, uploaded_count, status, note, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (upload_id, card_id, local_path, remote_path, file_count,
                 uploaded_count, status, note, now, now),
            )
        return upload_id

    def list_records(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM upload_records ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM upload_records WHERE status = ? ORDER BY created_at DESC", (status,)
                ).fetchall()
            return [dict(r) for r in rows]


def default_upload_log_path(project_root: Path) -> Path:
    return Path(project_root) / "workbench_data" / "upload_log.sqlite"
