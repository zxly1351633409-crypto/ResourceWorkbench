from __future__ import annotations

import json
import os
import sys
from pathlib import Path


APP_DATA_DIRNAME = "ResourceWorkbench"
PUBLIC_STABLE_PROFILE = Path("Profiles") / "Public" / "Stable"


DEFAULT_SETTINGS = {
    "resource_root": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_flash_model": "deepseek-v4-flash",
    "deepseek_pro_model": "deepseek-v4-pro",
    "deepseek_default_tier": "flash",
    "deepseek_api_key_env": "DEEPSEEK_API_KEY",
    "translation_name_mode": "zh_en",
    "auto_index_on_library_open": True,
    "auto_extract_archives_before_analysis": False,
    "quick_browse_max_cards": 120,
    "library_preload_depth": 2,
    "preview_cache_max_mb": 2048,
    "preview_cache_max_age_days": 180,
    "move_log_max_records": 10000,
    "move_log_max_age_days": 730,
    # 工作台运行数据保留策略。只清理派生缓存和已完成历史；活动队列、
    # 未撤销移动/重命名、失败记录及用户手工标签永远不按容量自动删除。
    "staging_max_age_days": 60,
    "staging_min_inactive_hours": 24,
    "resource_index_max_records": 250000,
    "resource_index_max_age_days": 365,
    "review_history_max_records": 20000,
    "review_history_max_age_days": 730,
    "rename_log_max_records": 20000,
    "rename_log_max_age_days": 730,
    "upload_log_max_records": 20000,
    "upload_log_max_age_days": 730,
    "sqlite_vacuum_min_reclaim_mb": 8,
    "enable_115": False,
    "p115_app_id": "",
    "remote_115_root": "",
    "auto_upload_after_move": False,
    "rename_local_after_translate": True,
    "cleanup_empty_source_parents_after_move": False,
    "ui_theme": "claude_light",
    "ui_accent_color": "#2563eb",
    # Blender 式语义主题：留空时跟随所选主题，填写后只覆盖对应角色。
    "ui_window_color": "",
    "ui_panel_color": "",
    "ui_canvas_color": "",
    "ui_sidebar_color": "",
    "ui_card_color": "",
    "ui_button_color": "",
    "ui_button_hover_color": "",
    "ui_button_selected_color": "",
    "ui_input_color": "",
    "ui_text_color": "",
    "ui_muted_text_color": "",
    "ui_border_color": "",
    "ui_icon_color": "",
    "use_qfluentwidgets": True,
}


def app_data_root(project_root: Path | None = None) -> Path:
    """Return the root for local runtime data.

    ``RESOURCE_WORKBENCH_HOME`` always wins so launchers and tests can select
    an explicit profile. Source runs otherwise keep the project-local location
    for backwards compatibility. A frozen public build deliberately uses a
    separate, deterministic ``Public/Stable`` profile: directly launching a
    distributed EXE must not inherit the developer's/personal formal profile,
    while later launches of that same EXE still retain the user's settings.
    """
    env_root = os.environ.get("RESOURCE_WORKBENCH_HOME", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base).expanduser() / APP_DATA_DIRNAME / PUBLIC_STABLE_PROFILE
        return Path.home() / ".resource_workbench" / PUBLIC_STABLE_PROFILE
    return Path(project_root or Path(__file__).resolve().parents[2])


def settings_path(project_root: Path) -> Path:
    return project_root / "workbench_data" / "settings.json"


def secret_path(project_root: Path) -> Path:
    """本地密钥文件；不进版本库（workbench_data 已在 .gitignore）。"""
    return project_root / "workbench_data" / "secret.json"


def load_settings(project_root: Path) -> dict:
    path = settings_path(project_root)
    if not path.exists():
        settings = dict(DEFAULT_SETTINGS)
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _with_runtime(dict(DEFAULT_SETTINGS), project_root)
        settings = dict(DEFAULT_SETTINGS)
        settings.update({key: value for key, value in loaded.items() if key in settings})
    settings["auto_extract_archives_before_analysis"] = False
    return _with_runtime(settings, project_root)


def _with_runtime(settings: dict, project_root: Path) -> dict:
    """注入运行期信息（不会被 save_settings 写回磁盘）。"""
    settings["_secret_file"] = str(secret_path(project_root))
    return settings


def save_settings(project_root: Path, settings: dict) -> None:
    path = settings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(DEFAULT_SETTINGS)
    payload.update({key: value for key, value in settings.items() if key in payload})
    payload["auto_extract_archives_before_analysis"] = False
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_secret(settings: dict) -> dict:
    secret_file = settings.get("_secret_file")
    if not secret_file:
        return {}
    path = Path(secret_file)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def deepseek_api_key(settings: dict) -> str:
    """读取 DeepSeek Key：环境变量优先，其次本地 secret.json。"""
    env_name = str(settings.get("deepseek_api_key_env") or "DEEPSEEK_API_KEY")
    env_value = os.environ.get(env_name, "")
    if env_value:
        return env_value
    return str(_read_secret(settings).get("deepseek_api_key", ""))


def deepseek_api_key_source(settings: dict) -> str:
    """返回 Key 来源说明：env / file / none。"""
    env_name = str(settings.get("deepseek_api_key_env") or "DEEPSEEK_API_KEY")
    if os.environ.get(env_name):
        return "env"
    if _read_secret(settings).get("deepseek_api_key"):
        return "file"
    return "none"


def save_deepseek_api_key(settings: dict, key: str) -> None:
    """把 Key 写入本地 secret.json；传空字符串则清除。"""
    secret_file = settings.get("_secret_file")
    if not secret_file:
        raise ValueError("缺少 _secret_file 路径，无法保存密钥。请用 load_settings 加载设置。")
    path = Path(secret_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_secret(settings)
    key = (key or "").strip()
    if key:
        data["deepseek_api_key"] = key
    else:
        data.pop("deepseek_api_key", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_115_credentials(settings: dict) -> dict:
    """读取 115 凭证：app_id 来自设置；app_secret/token 来自本地 secret.json。"""
    secret = _read_secret(settings)
    return {
        "app_id": str(settings.get("p115_app_id") or ""),
        "app_secret": str(secret.get("p115_app_secret", "")),
        "token": str(secret.get("p115_token", "")),
    }


def save_115_credentials(settings: dict, *, app_secret: str | None = None, token: str | None = None) -> None:
    """把 115 的 app_secret / token 写入本地 secret.json（不进版本库）。"""
    secret_file = settings.get("_secret_file")
    if not secret_file:
        raise ValueError("缺少 _secret_file 路径，无法保存 115 凭证。请用 load_settings 加载设置。")
    path = Path(secret_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_secret(settings)
    if app_secret is not None:
        app_secret = app_secret.strip()
        if app_secret:
            data["p115_app_secret"] = app_secret
        else:
            data.pop("p115_app_secret", None)
    if token is not None:
        token = token.strip()
        if token:
            data["p115_token"] = token
        else:
            data.pop("p115_token", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
