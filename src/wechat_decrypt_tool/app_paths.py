from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR_KEY = "WECHAT_TOOL_DATA_DIR"
ENV_OUTPUT_DIR_KEY = "WECHAT_TOOL_OUTPUT_DIR"


def get_data_dir() -> Path:
    """Base writable directory for all runtime output (logs, databases, key store).

    - Desktop (Electron) should set `WECHAT_TOOL_DATA_DIR` to a per-user directory
      (e.g. `%APPDATA%/WeChatDataAnalysis`).
    - Dev defaults to the current working directory (repo root).
    """

    v = os.environ.get(ENV_DATA_DIR_KEY, "").strip()
    if v:
        return Path(v).expanduser()
    return Path.cwd()


def get_output_dir() -> Path:
    v = os.environ.get(ENV_OUTPUT_DIR_KEY, "").strip()
    if v:
        return Path(v).expanduser()
    return get_data_dir() / "output"


# 微信数据保存位置的覆盖缓存：(settings.json mtime, data_dir 覆盖值)
# 读写端（保存、查看聊天、语音转写等）都经由 get_output_databases_dir 汇聚，
# 覆盖值来自 settings.json 的 wechat.data_dir（见 context_registry）。
_wechat_data_dir_cache: tuple[float, str] | None = None


def _wechat_data_dir_override() -> str:
    """读取用户设置的微信数据保存位置；空串表示使用默认路径。"""
    global _wechat_data_dir_cache
    try:
        from .context_registry import get_settings_path

        settings_path = get_settings_path()
        mtime = settings_path.stat().st_mtime
        cached = _wechat_data_dir_cache
        if cached is not None and cached[0] == mtime:
            return cached[1]
        from .context_registry import load_settings

        value = str(load_settings().get("wechat", {}).get("data_dir") or "").strip()
        _wechat_data_dir_cache = (mtime, value)
        return value
    except Exception:
        # 设置不可用时回退默认路径，不阻塞调用方
        return ""


def get_output_databases_dir() -> Path:
    override = _wechat_data_dir_override()
    if override:
        return Path(override)
    return get_output_dir() / "databases"


def get_account_keys_path() -> Path:
    return get_output_dir() / "account_keys.json"
