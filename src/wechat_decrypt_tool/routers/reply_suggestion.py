"""消息回复推荐：依据聊天上下文与可选工作空间生成一条回复建议。"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .ai import local_only
from ..account_identity import resolve_account_self_username
from ..ai.model_selection import selected_model
from ..ai.providers import ProviderFailure
from ..ai.service import get_ai_service
from ..chat_export_service import _iter_rows_for_conversation
from ..chat_helpers import _resolve_account_dir
from ..workspace_reader import read_workspace

router = APIRouter(prefix='/api/reply-suggestions', dependencies=[Depends(local_only)])

CONTEXT_MESSAGES = 30
LLM_TIMEOUT_SECONDS = 60.0
SETTINGS_KIND = 'reply_suggestion_settings'
DEFAULT_SETTINGS = {'workspace_dir': '', 'enabled': False}


class ReplySuggestionSettings(BaseModel):
    workspace_dir: str = Field('', max_length=1000)
    enabled: bool = False


class ReplySuggestionRequest(BaseModel):
    account: str = Field('', max_length=200)
    conversation: str = Field(..., max_length=200)
    anchor_id: str = Field(..., max_length=300)
    extra_instruction: str = Field('', max_length=2000)
    workspace_dir: str | None = Field(None, max_length=1000)


def _settings(store) -> dict:
    return store.get(SETTINGS_KIND, 'global') or dict(DEFAULT_SETTINGS)


@router.get('/settings')
def get_reply_suggestion_settings():
    return {k: v for k, v in _settings(get_ai_service().store).items() if k != 'id'}


@router.put('/settings')
def update_reply_suggestion_settings(body: ReplySuggestionSettings):
    get_ai_service().store.put(SETTINGS_KIND, body.model_dump(), id='global')
    return body.model_dump()


def _parse_anchor(anchor_id: str) -> tuple[str, str, int]:
    parts = str(anchor_id or '').split(':', 2)
    if len(parts) != 3:
        raise HTTPException(400, 'Invalid anchor_id.')
    db_stem, table_name = parts[0].strip(), parts[1].strip()
    try:
        local_id = int(parts[2])
    except ValueError:
        raise HTTPException(400, 'Invalid anchor_id.') from None
    if not db_stem or local_id <= 0:
        raise HTTPException(400, 'Invalid anchor_id.')
    return db_stem, table_name, local_id


def _load_context(account_dir, conversation: str, anchor: tuple[str, str, int]):
    """取目标消息前 CONTEXT_MESSAGES 条（含自身）；未命中返回 (None, 0)。"""
    db_stem, table_name, local_id = anchor
    window: deque = deque(maxlen=CONTEXT_MESSAGES)
    for row in _iter_rows_for_conversation(
        account_dir=account_dir, conv_username=conversation,
        start_time=None, end_time=None, source='decrypted',
    ):
        if (int(row.local_id or 0) == local_id
                and str(row.db_stem or '').lower() == db_stem.lower()
                and (not table_name or not str(row.table_name or '').strip()
                     or str(row.table_name).lower() == table_name.lower())):
            window.append(row)
            return list(window), len(window)
        window.append(row)
    return None, 0


@router.post('/generate')
async def generate_reply_suggestion(body: ReplySuggestionRequest):
    from .account_archive_export import _flatten_text_for_line, _structured_plain_text, _structured_time_text

    service = get_ai_service()
    choice = selected_model(service.store)
    if choice.get('unavailable') or not choice.get('profile_id'):
        raise HTTPException(400, detail={'code': 'ai_not_configured',
            'message': '尚未配置 AI 服务，请先在设置 → AI 服务中添加并选择模型'})
    try:
        profile = service.models.resolve_turn(
            choice.get('profile_id'), choice.get('model_id'), choice.get('reasoning_effort'))
    except ProviderFailure as exc:
        raise HTTPException(400, str(exc)) from None

    started = time.monotonic()
    anchor = _parse_anchor(body.anchor_id)
    account_dir = _resolve_account_dir(body.account or None)
    window, context_count = _load_context(account_dir, body.conversation, anchor)
    if window is None:
        raise HTTPException(404, '目标消息不存在或已不在当前数据源中。')

    conversation_display = body.conversation
    self_username = resolve_account_self_username(account_dir)
    lines = []
    for row in window:
        sender = self_username if row.is_sent else (str(row.sender_username or '').strip() or conversation_display)
        label = f'{sender}（我）' if row.is_sent else sender
        content = _flatten_text_for_line(_structured_plain_text(int(row.local_type or 0), row.raw_text))
        lines.append(f'[{_structured_time_text(row.create_time)}] {label}: {content}')
    transcript = '\n'.join(lines)

    settings = _settings(service.store)
    override = body.workspace_dir if body.workspace_dir is not None else None
    workspace_dir = str(override if override is not None else settings.get('workspace_dir', '')).strip()
    workspace_enabled = override is not None or bool(settings.get('enabled'))
    workspace = {'files': [], 'digest': '', 'truncated': False}
    if workspace_dir and workspace_enabled:
        workspace = read_workspace(workspace_dir)
    workspace_used = bool(workspace_dir) and workspace_enabled and bool(workspace['files'])

    parts = [
        f'以下是「{conversation_display}」会话的最近 {context_count} 条聊天记录（时间正序，"（我）"表示本机账号发送）：',
        transcript,
    ]
    if workspace_used:
        parts.append(f'参考资料（来自工作空间目录 {workspace_dir}）：\n{workspace["digest"]}')
    parts.append('请针对聊天记录中最后一条消息，撰写一条可以直接发送的中文回复。'
                 '只输出回复内容本身，不要解释、不要引号。')
    if body.extra_instruction:
        parts.append(f'用户补充要求：{body.extra_instruction}')
    prompt = '\n\n'.join(parts)

    try:
        suggestion = await asyncio.wait_for(
            service.models.invoke(profile, prompt, account=account_dir.name),
            timeout=LLM_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(504, '模型响应超时，请重试') from None
    except ProviderFailure as exc:
        raise HTTPException(502, str(exc)) from None

    return {
        'suggestion': str(suggestion or '').strip(),
        'model': profile.get('model', ''),
        'filesConsidered': [item['path'] for item in workspace['files']],
        'contextMessages': context_count,
        'workspaceUsed': workspace_used,
        'workspaceDir': workspace_dir if workspace_enabled else '',
        'workspaceTruncated': bool(workspace.get('truncated')),
        'elapsedMs': int((time.monotonic() - started) * 1000),
    }
