"""上下文源注册表：统一管理各数据源的状态、开关与元数据。

目录结构（<data_dir>/contexts/）：
- settings.json             各源开关的唯一权威存储（manifest 不存 enabled）
- <source_id>/manifest.json {source_id, last_saved_at, summary, data_ref}
"""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .app_paths import get_data_dir
from .logging_config import get_logger

logger = get_logger(__name__)

_SETTINGS_LOCK = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "wechat": {"enabled": True, "data_dir": "", "archive_content": "structured"},
    "browser_history": {"enabled": True},
    "computer_activity": {"enabled": False},
    "mobile_upload": {"enabled": False},
    "custom_capture": {"enabled": False},
}


def get_contexts_root() -> Path:
    root = get_data_dir() / "contexts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_settings_path() -> Path:
    return get_contexts_root() / "settings.json"


def _ensure_source_dir(source_id: str) -> Path:
    path = get_contexts_root() / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict[str, Any]:
    try:
        data = json.loads(get_settings_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception:
        logger.exception("[context] settings.json 解析失败，回退默认设置")
        data = {}
    if not isinstance(data, dict):
        data = {}
    merged = {source_id: dict(item) for source_id, item in DEFAULT_SETTINGS.items()}
    for source_id, overrides in data.items():
        if source_id not in merged or not isinstance(overrides, dict):
            continue
        merged[source_id].update(overrides)
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = load_settings()
    for source_id, overrides in (settings or {}).items():
        if source_id not in normalized or not isinstance(overrides, dict):
            continue
        # 各源仅允许更新自己的设置键：开关通用，保存位置与归档内容仅微信数据源支持
        allowed_keys = {"enabled"} | (
            {"data_dir", "archive_content"} if source_id == "wechat" else set()
        )
        normalized[source_id].update(
            {key: value for key, value in overrides.items() if key in allowed_keys}
        )
    with _SETTINGS_LOCK:
        get_settings_path().write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return normalized


def get_manifest_path(source_id: str) -> Path:
    return get_contexts_root() / source_id / "manifest.json"


def read_manifest(source_id: str) -> dict[str, Any]:
    try:
        return json.loads(get_manifest_path(source_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("[context] manifest 读取失败: source=%s", source_id)
        return {}


def write_manifest(source_id: str, *, summary: dict[str, Any], data_ref: str) -> dict[str, Any]:
    manifest = {
        "source_id": source_id,
        "last_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "data_ref": data_ref,
    }
    path = get_manifest_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return manifest


@runtime_checkable
class ContextSource(Protocol):
    """上下文源适配器接口：浏览器插件等未来数据源按此接口接入。"""

    source_id: str
    display_name: str

    def status(self) -> dict[str, Any]: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PlannedStubSource:
    """规划中的数据源占位：目录与 API 位置就位，无采集逻辑。"""

    planned = True

    def __init__(
        self,
        source_id: str,
        display_name: str,
        description: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.source_id = source_id
        self.display_name = display_name
        self.description = description
        self.extra = dict(extra or {})

    def status(self) -> dict[str, Any]:
        _ensure_source_dir(self.source_id)
        settings = load_settings()
        return {
            "source_id": self.source_id,
            "name": self.display_name,
            "enabled": bool(settings.get(self.source_id, {}).get("enabled")),
            "state": "planned",
            "last_saved_at": None,
            "summary": {"description": self.description, **self.extra},
            "planned": True,
        }

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class WechatContextSource:
    """微信上下文源：真实实现，状态来自自动保存服务与 manifest。"""

    planned = False
    source_id = "wechat"
    display_name = "微信数据"

    def status(self) -> dict[str, Any]:
        settings = load_settings()
        manifest = read_manifest("wechat")
        state = "up_to_date" if manifest else "idle"
        try:
            from .wechat_autosave import WECHAT_AUTOSAVE

            state = str(WECHAT_AUTOSAVE.get_state().get("state") or state)
        except Exception:
            # wechat_autosave 尚未就绪（Task 4 前回退 manifest）
            pass
        from .app_paths import get_output_databases_dir

        return {
            "source_id": self.source_id,
            "name": self.display_name,
            "enabled": bool(settings.get("wechat", {}).get("enabled", True)),
            "state": state,
            "last_saved_at": manifest.get("last_saved_at"),
            "summary": manifest.get("summary") or {},
            "planned": False,
            "data_dir": str(settings.get("wechat", {}).get("data_dir") or ""),
            "data_dir_effective": str(get_output_databases_dir()),
            "archive_content": str(
                settings.get("wechat", {}).get("archive_content") or "structured"
            ),
        }

    def start(self) -> None:
        from .wechat_autosave import WECHAT_AUTOSAVE

        WECHAT_AUTOSAVE.start()

    def stop(self) -> None:
        from .wechat_autosave import WECHAT_AUTOSAVE

        WECHAT_AUTOSAVE.stop()


from .browser_history import BROWSER_HISTORY_SOURCE
COMPUTER_ACTIVITY_SOURCE = PlannedStubSource(
    "computer_activity",
    "电脑操作记录",
    "记录本机操作行为，辅助回顾电脑上的工作上下文。",
)
MOBILE_UPLOAD_SOURCE = PlannedStubSource(
    "mobile_upload",
    "手机上传",
    "配合手机端 NextCloud 应用，手动上传手机上的上下文数据。",
    extra={"nextcloud": {"server_url": "", "configured": False}},
)
CUSTOM_CAPTURE_SOURCE = PlannedStubSource(
    "custom_capture",
    "定制浏览器抓取",
    "自动生成定制浏览器插件，抓取指定浏览器中的数据。",
)

SOURCES: dict[str, ContextSource] = {
    "wechat": WechatContextSource(),
    "browser_history": BROWSER_HISTORY_SOURCE,
    "computer_activity": COMPUTER_ACTIVITY_SOURCE,
    "mobile_upload": MOBILE_UPLOAD_SOURCE,
    "custom_capture": CUSTOM_CAPTURE_SOURCE,
}


def list_sources() -> list[dict[str, Any]]:
    return [source.status() for source in SOURCES.values()]
