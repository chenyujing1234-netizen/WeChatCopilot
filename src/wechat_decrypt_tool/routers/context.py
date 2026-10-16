"""上下文中心 API：源状态、开关、保存位置与手动触发保存（仅本机访问）。"""

from __future__ import annotations

import asyncio
import ipaddress
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..app_paths import get_output_databases_dir
from ..chat_realtime_autosync import CHAT_REALTIME_AUTOSYNC
from ..context_registry import list_sources, load_settings, save_settings
from ..logging_config import get_logger
from ..wechat_autosave import WECHAT_AUTOSAVE

logger = get_logger(__name__)


def local_only(request: Request):
    """仅允许本机访问（与 AI 路由同规则）。"""
    try:
        if not ipaddress.ip_address(request.client.host).is_loopback:
            raise ValueError()
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError()
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(403, "上下文服务仅允许本机应用访问") from None


router = APIRouter(prefix="/api/context", dependencies=[Depends(local_only)])


class SourceSettingUpdate(BaseModel):
    enabled: Optional[bool] = None
    data_dir: Optional[str] = None


class ContextSettingsUpdate(BaseModel):
    wechat: Optional[SourceSettingUpdate] = None
    browser_history: Optional[SourceSettingUpdate] = None
    computer_activity: Optional[SourceSettingUpdate] = None
    mobile_upload: Optional[SourceSettingUpdate] = None
    custom_capture: Optional[SourceSettingUpdate] = None


def _copy_existing_wechat_data(old_dir: Path, new_dir: Path) -> int:
    """把旧位置已保存的账号数据复制到新位置。

    新位置已存在的账号目录跳过，避免覆盖新位置上更新的数据。
    """
    if not old_dir.is_dir():
        return 0
    try:
        if old_dir.resolve() == new_dir.resolve():
            return 0
    except Exception:
        return 0
    copied = 0
    for account_dir in old_dir.iterdir():
        if not account_dir.is_dir():
            continue
        target = new_dir / account_dir.name
        if target.exists():
            continue
        try:
            shutil.copytree(account_dir, target)
            copied += 1
        except Exception:
            logger.exception(
                "[context] 迁移账号数据失败 account=%s", account_dir.name
            )
    return copied


async def _apply_wechat_data_dir(data_dir: str) -> None:
    """切换微信数据保存位置：校验路径、停服务、迁移已保存数据、恢复服务。"""
    if data_dir:
        path = Path(data_dir)
        if not path.is_absolute():
            raise HTTPException(400, "保存位置必须是绝对路径")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:
            raise HTTPException(400, "保存位置无法创建，请检查权限后重试") from None

    old_dir = get_output_databases_dir()
    # 停自动保存与实时同步，避免迁移期间写入旧位置的数据文件
    WECHAT_AUTOSAVE.stop()
    CHAT_REALTIME_AUTOSYNC.stop()
    try:
        save_settings({"wechat": {"data_dir": data_dir}})
        new_dir = get_output_databases_dir()
        new_dir.mkdir(parents=True, exist_ok=True)
        copied = await asyncio.to_thread(_copy_existing_wechat_data, old_dir, new_dir)
        logger.info(
            "[context] 微信数据保存位置已切换 old=%s new=%s copied_accounts=%s",
            old_dir,
            new_dir,
            copied,
        )
    finally:
        if load_settings().get("wechat", {}).get("enabled", True):
            WECHAT_AUTOSAVE.start()


@router.get("/sources", summary="上下文源列表")
async def get_context_sources():
    return {"status": "ok", "sources": list_sources()}


@router.get("/settings", summary="各源开关设置")
async def get_context_settings():
    return {"status": "ok", "settings": load_settings()}


@router.put("/settings", summary="保存各源开关设置")
async def update_context_settings(payload: ContextSettingsUpdate):
    updates = payload.model_dump(exclude_none=True)
    wechat_update = updates.get("wechat") or {}
    if "data_dir" in wechat_update:
        await _apply_wechat_data_dir(str(wechat_update["data_dir"] or "").strip())
        updates["wechat"] = {
            key: value for key, value in wechat_update.items() if key != "data_dir"
        }
    settings = save_settings(updates)
    return {"status": "ok", "settings": settings}


@router.post("/wechat/sync-now", summary="立即保存微信上下文")
async def trigger_wechat_sync():
    result = await asyncio.to_thread(WECHAT_AUTOSAVE.sync_now)
    if result.get("status") != 0:
        # 不透出内部处理细节，只保留通用提示（隐藏解密）
        logger.warning("[context] sync-now 未完成: state=%s", result.get("state"))
        result = {**result, "errmsg": "本轮保存未完成，微信保持登录后稍后会自动重试"}
    return result
