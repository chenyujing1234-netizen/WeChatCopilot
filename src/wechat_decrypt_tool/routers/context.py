"""上下文中心 API：源状态、开关与手动触发保存（仅本机访问）。"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

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
    enabled: bool


class ContextSettingsUpdate(BaseModel):
    wechat: Optional[SourceSettingUpdate] = None
    browser_history: Optional[SourceSettingUpdate] = None
    computer_activity: Optional[SourceSettingUpdate] = None
    mobile_upload: Optional[SourceSettingUpdate] = None
    custom_capture: Optional[SourceSettingUpdate] = None


@router.get("/sources", summary="上下文源列表")
async def get_context_sources():
    return {"status": "ok", "sources": list_sources()}


@router.get("/settings", summary="各源开关设置")
async def get_context_settings():
    return {"status": "ok", "settings": load_settings()}


@router.put("/settings", summary="保存各源开关设置")
async def update_context_settings(payload: ContextSettingsUpdate):
    settings = save_settings(payload.model_dump(exclude_none=True))
    return {"status": "ok", "settings": settings}


@router.post("/wechat/sync-now", summary="立即保存微信上下文")
async def trigger_wechat_sync():
    result = await asyncio.to_thread(WECHAT_AUTOSAVE.sync_now)
    if result.get("status") != 0:
        # 不透出内部处理细节，只保留通用提示（隐藏解密）
        logger.warning("[context] sync-now 未完成: state=%s", result.get("state"))
        result = {**result, "errmsg": "本轮保存未完成，微信保持登录后稍后会自动重试"}
    return result
