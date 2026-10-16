# 消息回复推荐功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在聊天界面为任意消息生成一条 AI 回复建议（依据最近聊天上下文 + 可选工作空间目录），并支持全局工作空间设置。

**Architecture:** 后端新增 `workspace_reader.py`（递归读文本文件）与 `routers/reply_suggestion.py`（生成 + 设置两个端点，复用 `ai/` 包的选中模型与调用通道，设置持久化在 AIStore）；前端新增 `ReplySuggestionDialog.vue` 弹窗、消息行 hover 按钮、设置页工作空间卡片，`useApi.js` 提供 API 封装。

**Tech Stack:** FastAPI + pydantic（后端）；Nuxt 3 + Vue 3 + Tailwind（前端）；pytest（后端测试）；vitest（前端测试）。

**Spec:** `docs/superpowers/specs/2026-10-09-reply-suggestion-design.md`

## Global Constraints

- 与用户中文交流；代码注释跟随现有风格（后端中文注释为主，前端中文注释）
- 后端测试运行：`uv run --no-sync python -m pytest tests/test_xxx.py -v`（在仓库根目录）
- 前端测试运行：`cd frontend && npx vitest run tests/<file>`；构建校验：`cd frontend && npm run build`
- 路由仅本机访问：复用 `routers/ai.py` 的 `local_only` 依赖
- 消息定位采用与 `/api/chat/messages/around` 相同的 anchor 三段式 `db_stem:table_name:local_id`（前端消息对象自带 `id` 字段即此格式，见 chat.py:5734）。spec 中的 "localId + messageId" 由该 anchor 统一承载（含 localId 且带库表消歧，更精确）
- 工作空间读取上限：单文件 100KB、总量 500KB、最多 100 个文件；文本扩展名集合与解码回退 utf-8→gbk；坏文件跳过不阻断
- LLM 调用超时 60s；无 AI 配置返回 400 + `code: 'ai_not_configured'`
- 不做：多条候选、流式、Agent 线程体系、向量检索、回复直达微信

---

### Task 1: workspace_reader 工作空间读取器

**Files:**
- Create: `src/wechat_decrypt_tool/workspace_reader.py`
- Test: `tests/test_workspace_reader.py`

**Interfaces:**
- Produces: `read_workspace(directory: str) -> dict`，返回 `{'files': [{'path': str, 'size': int}], 'digest': str, 'truncated': bool}`。`files` 为相对目录的 posix 路径；`digest` 为按文件分段的文本拼接（`----- <path> -----\n<content>` 块，空行分隔）；目录不存在/为空返回空结果且 `truncated=False`。Task 2 消费该函数。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workspace_reader.py
"""工作空间读取器：类型过滤、递归、三重上限、编码回退、坏文件跳过。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.workspace_reader import read_workspace, MAX_FILES


def _write(path: Path, text: str, encoding='utf-8'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def test_missing_directory_returns_empty(tmp_path):
    result = read_workspace(str(tmp_path / 'nope'))
    assert result == {'files': [], 'digest': '', 'truncated': False}


def test_filters_extensions_and_recurses(tmp_path):
    _write(tmp_path / 'a.md', '说明')
    _write(tmp_path / 'sub' / 'b.txt', '文本')
    _write(tmp_path / 'sub' / 'c.png', 'binary')
    _write(tmp_path / 'd.exe', 'nope')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['a.md', 'sub/b.txt']
    assert '说明' in result['digest'] and '文本' in result['digest']
    assert result['truncated'] is False


def test_file_count_cap_marks_truncated(tmp_path):
    for i in range(MAX_FILES + 5):
        _write(tmp_path / f'{i}.txt', str(i))
    result = read_workspace(str(tmp_path))
    assert len(result['files']) == MAX_FILES
    assert result['truncated'] is True


def test_oversize_file_skipped_and_marked(tmp_path):
    (tmp_path / 'big.txt').write_bytes(b'x' * (100 * 1024 + 1))
    _write(tmp_path / 'small.txt', 'ok')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['small.txt']
    assert result['truncated'] is True


def test_total_size_cap_stops_and_marks_truncated(tmp_path):
    # 6 个 99KB 文件共约 594KB，超过 500KB 总量上限
    for i in range(6):
        (tmp_path / f'{i}.txt').write_bytes(b'x' * (99 * 1024))
    result = read_workspace(str(tmp_path))
    assert len(result['files']) < 6
    assert result['truncated'] is True


def test_gbk_decoded_and_undecodable_skipped(tmp_path):
    _write(tmp_path / 'gbk.txt', '中文内容', encoding='gbk')
    (tmp_path / 'bad.txt').write_bytes(b'\xff\xfe\x00\xd8\x00\x00\xff')
    _write(tmp_path / 'ok.txt', '正常')
    result = read_workspace(str(tmp_path))
    assert [f['path'] for f in result['files']] == ['gbk.txt', 'ok.txt']
    assert '中文内容' in result['digest']
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --no-sync python -m pytest tests/test_workspace_reader.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'wechat_decrypt_tool.workspace_reader'`

- [ ] **Step 3: 实现 workspace_reader.py**

```python
# src/wechat_decrypt_tool/workspace_reader.py
"""回复推荐的工作空间读取：递归收集小文本文件拼接为参考资料。"""
from __future__ import annotations

from pathlib import Path

TEXT_EXTENSIONS = {
    '.txt', '.md', '.json', '.csv', '.py', '.js', '.ts', '.vue', '.html', '.xml',
    '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg',
}
MAX_FILE_BYTES = 100 * 1024
MAX_TOTAL_BYTES = 500 * 1024
MAX_FILES = 100


def _decode_text(raw: bytes) -> str | None:
    for encoding in ('utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def read_workspace(directory: str) -> dict:
    """递归读取目录下的小文本文件；单个坏文件不影响整体。

    返回 {files: [{path, size}], digest, truncated}；目录无效或无可用文件
    时返回空结果（truncated=False），由调用方决定是否提示。
    """
    result = {'files': [], 'digest': '', 'truncated': False}
    raw = str(directory or '').strip()
    if not raw:
        return result
    root = Path(raw).expanduser()
    if not root.is_dir():
        return result
    try:
        candidates = sorted(
            p for p in root.rglob('*')
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS
        )
    except OSError:
        return result

    parts: list[str] = []
    total = 0
    for path in candidates:
        if len(result['files']) >= MAX_FILES:
            result['truncated'] = True
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            # 超大文件直接跳过，不读入内存。
            result['truncated'] = True
            continue
        try:
            content = _decode_text(path.read_bytes())
        except OSError:
            continue
        if content is None:
            continue
        if total + size > MAX_TOTAL_BYTES:
            result['truncated'] = True
            break
        rel = path.relative_to(root).as_posix()
        result['files'].append({'path': rel, 'size': size})
        parts.append(f'----- {rel} -----\n{content}')
        total += size
    result['digest'] = '\n\n'.join(parts)
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run --no-sync python -m pytest tests/test_workspace_reader.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/wechat_decrypt_tool/workspace_reader.py tests/test_workspace_reader.py
git commit -m "feat: 工作空间文本读取器，供回复推荐参考"
```

---

### Task 2: reply_suggestion 路由（设置 + 生成）并注册

**Files:**
- Create: `src/wechat_decrypt_tool/routers/reply_suggestion.py`
- Modify: `src/wechat_decrypt_tool/api.py`（注册路由）
- Test: `tests/test_reply_suggestion.py`

**Interfaces:**
- Consumes: `read_workspace(directory) -> dict`（Task 1）；`get_ai_service()`（`ai/service.py`，`.models.resolve_turn(profile_id, model_id, reasoning_effort)`、`.models.invoke(profile, prompt)` 返回文本、`.store.get/put(kind, body, id)`）；`selected_model(store)`（`ai/model_selection.py`）；`_iter_rows_for_conversation(account_dir=, conv_username=, start_time=None, end_time=None, source='decrypted')`（`chat_export_service.py`，产出 `_Row{db_stem, table_name, local_id, local_type, create_time, raw_text, sender_username, is_sent}`，时间正序）；`_resolve_account_dir(account)`（`chat_helpers.py`）；`_structured_plain_text(local_type, raw_text)`、`_structured_time_text(ts)`、`_flatten_text_for_line(text)`（`routers/account_archive_export.py`，纯文本转写工具）；`local_only`、`account_name`（`routers/ai.py`）
- Produces:
  - `GET /api/reply-suggestions/settings` → `{'workspace_dir': str, 'enabled': bool}`
  - `PUT /api/reply-suggestions/settings`（body 同上）→ 保存后的值
  - `POST /api/reply-suggestions/generate`（body: `account, conversation, anchor_id, extra_instruction?, workspace_dir?`）→ `{'suggestion', 'model', 'filesConsidered', 'contextMessages', 'workspaceUsed', 'workspaceDir', 'workspaceTruncated', 'elapsedMs'}`；错误：400 `{'code': 'ai_not_configured'}`、400/404/504
  - Task 3 的前端封装消费这些端点

- [ ] **Step 1: 写失败测试**

```python
# tests/test_reply_suggestion.py
"""回复推荐生成：消息定位与窗口、工作空间注入、无 Key 错误路径。"""
import asyncio
import hashlib
import sqlite3
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.ai.service import AIService
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.ai.providers import ModelService
from wechat_decrypt_tool.routers import reply_suggestion


ACCOUNT = 'wxid_me'
FRIEND = 'wxid_friend'
TABLE = f"msg_{hashlib.md5(FRIEND.encode('utf-8')).hexdigest()}"


def _seed_account(account_dir: Path, count=5):
    account_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(account_dir / 'message_0.db'))
    try:
        conn.execute('CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY, user_name TEXT)')
        conn.execute('INSERT INTO Name2Id(rowid, user_name) VALUES (?, ?)', (1, ACCOUNT))
        conn.execute('INSERT INTO Name2Id(rowid, user_name) VALUES (?, ?)', (2, FRIEND))
        conn.execute(f"""CREATE TABLE {TABLE} (
            local_id INTEGER, server_id INTEGER, local_type INTEGER, sort_seq INTEGER,
            real_sender_id INTEGER, create_time INTEGER, message_content TEXT, compress_content BLOB)""")
        for i in range(1, count + 1):
            sent = 1 if i % 2 == 0 else 2
            conn.execute(
                f"INSERT INTO {TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (i, 1000 + i, 1, i, sent, 1735689600 + i, f'消息{i}'),
            )
        conn.commit()
    finally:
        conn.close()


def _make_router(tmp_path, monkeypatch, invoked):
    store = AIStore(tmp_path)
    store.put('profile', dict(name='test', model='fixture', protocol='openai',
        base_url='http://localhost:1/v1', api_key='secret', vision=False, revision=1,
        model_overrides={}), id='model')
    store.put('defaults', {'text': 'model'}, id='global')
    service = AIService(store, ModelService(store))

    async def fake_invoke(profile, prompt, *args, **kwargs):
        invoked.append(prompt)
        return '建议：好的，明天见。'

    monkeypatch.setattr(service.models, 'invoke', fake_invoke)
    monkeypatch.setattr(reply_suggestion, 'get_ai_service', lambda: service)
    app = FastAPI()
    app.include_router(reply_suggestion.router)
    return app, store


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1)),
                             base_url='http://localhost')


def test_generate_returns_suggestion_with_context_window(tmp_path, monkeypatch):
    account_dir = tmp_path / ACCOUNT
    _seed_account(account_dir)
    monkeypatch.setattr(reply_suggestion, '_resolve_account_dir', lambda _a: account_dir)
    prompts, app, store = [], None, None
    app, store = _make_router(tmp_path, monkeypatch, prompts)

    async def check():
        async with _client(app) as client:
            body = {'account': ACCOUNT, 'conversation': FRIEND,
                    'anchor_id': f'message_0:{TABLE}:3'}
            resp = await client.post('/api/reply-suggestions/generate', json=body)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data['suggestion'] == '建议：好的，明天见。'
            assert data['model'] == 'fixture'
            assert data['contextMessages'] == 3  # 前 30 条含自身，此处共 3 条
            assert data['workspaceUsed'] is False
            assert data['elapsedMs'] >= 0
            # 转写包含目标消息及其前文
            assert '消息1' in prompts[0] and '消息3' in prompts[0] and '消息4' not in prompts[0]
    asyncio.run(check())


def test_generate_without_ai_configured_returns_code(tmp_path, monkeypatch):
    store = AIStore(tmp_path / 'empty-ai')
    app = FastAPI()
    from wechat_decrypt_tool.ai.service import AIService
    monkeypatch.setattr(reply_suggestion, 'get_ai_service', lambda: AIService(store))
    async def check():
        async with _client(app) as client:
            app.include_router(reply_suggestion.router)
            resp = await client.post('/api/reply-suggestions/generate',
                json={'account': ACCOUNT, 'conversation': FRIEND, 'anchor_id': 'a:b:1'})
            assert resp.status_code == 400
            assert resp.json()['detail']['code'] == 'ai_not_configured'
    asyncio.run(check())


def test_generate_unknown_anchor_returns_404(tmp_path, monkeypatch):
    account_dir = tmp_path / ACCOUNT
    _seed_account(account_dir)
    monkeypatch.setattr(reply_suggestion, '_resolve_account_dir', lambda _a: account_dir)
    app, _ = _make_router(tmp_path, monkeypatch, [])
    async def check():
        async with _client(app) as client:
            resp = await client.post('/api/reply-suggestions/generate',
                json={'account': ACCOUNT, 'conversation': FRIEND, 'anchor_id': f'message_0:{TABLE}:99'})
            assert resp.status_code == 404
    asyncio.run(check())


def test_generate_uses_workspace_when_enabled(tmp_path, monkeypatch):
    account_dir = tmp_path / ACCOUNT
    _seed_account(account_dir)
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    (workspace / 'note.md').write_text('重要：周三体检', encoding='utf-8')
    prompts = []
    app, store = _make_router(tmp_path, monkeypatch, prompts)
    monkeypatch.setattr(reply_suggestion, '_resolve_account_dir', lambda _a: account_dir)

    async def check():
        async with _client(app) as client:
            saved = await client.put('/api/reply-suggestions/settings',
                json={'workspace_dir': str(workspace), 'enabled': True})
            assert saved.status_code == 200
            assert (await client.get('/api/reply-suggestions/settings')).json() == \
                {'workspace_dir': str(workspace), 'enabled': True}
            resp = await client.post('/api/reply-suggestions/generate',
                json={'account': ACCOUNT, 'conversation': FRIEND,
                      'anchor_id': f'message_0:{TABLE}:2'})
            assert resp.status_code == 200
            data = resp.json()
            assert data['workspaceUsed'] is True
            assert data['filesConsidered'] == ['note.md']
            assert '周三体检' in prompts[0]
            # 请求级覆盖优先于全局设置
            resp = await client.post('/api/reply-suggestions/generate',
                json={'account': ACCOUNT, 'conversation': FRIEND,
                      'anchor_id': f'message_0:{TABLE}:2', 'workspace_dir': str(tmp_path / 'none')})
            data = resp.json()
            assert data['workspaceUsed'] is False
    asyncio.run(check())


def test_generate_context_capped_at_30(tmp_path, monkeypatch):
    account_dir = tmp_path / ACCOUNT
    _seed_account(account_dir, count=45)
    monkeypatch.setattr(reply_suggestion, '_resolve_account_dir', lambda _a: account_dir)
    prompts = []
    app, _ = _make_router(tmp_path, monkeypatch, prompts)
    async def check():
        async with _client(app) as client:
            resp = await client.post('/api/reply-suggestions/generate',
                json={'account': ACCOUNT, 'conversation': FRIEND,
                      'anchor_id': f'message_0:{TABLE}:45'})
            data = resp.json()
            assert data['contextMessages'] == 30
            assert '消息15' in prompts[0] and '消息14' not in prompts[0]
    asyncio.run(check())
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --no-sync python -m pytest tests/test_reply_suggestion.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'wechat_decrypt_tool.routers.reply_suggestion'`（或路由不存在 404）

- [ ] **Step 3: 实现路由**

```python
# src/wechat_decrypt_tool/routers/reply_suggestion.py
"""消息回复推荐：依据聊天上下文与可选工作空间生成一条回复建议。"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .ai import account_name, local_only
from ..ai.model_selection import selected_model
from ..ai.providers import ProviderFailure
from ..ai.service import get_ai_service
from ..chat_export_service import _iter_rows_for_conversation
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
    return _settings(get_ai_service().store)


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
    from ..account_identity import resolve_account_self_username
    from ..chat_helpers import _resolve_account_dir

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
            service.models.invoke(profile, prompt, account=account_name(body.account or '')),
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
```

注意：`account_archive_export` 与本模块都在 `routers` 包内，函数导入放在 handler 内避免模块导入环（`account_archive_export` 导入了大量服务模块）。

- [ ] **Step 4: 在 api.py 注册路由**

`src/wechat_decrypt_tool/api.py` 第 135 行 `app.include_router(_ai_agent_router)` 之后追加：

```python
from .routers.reply_suggestion import router as _reply_suggestion_router
app.include_router(_reply_suggestion_router)
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run --no-sync python -m pytest tests/test_reply_suggestion.py -v`
Expected: 5 passed

再跑回归（确认路由注册未破坏应用导入）：
Run: `uv run --no-sync python -m pytest tests/test_ai_model_selection.py -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add src/wechat_decrypt_tool/routers/reply_suggestion.py src/wechat_decrypt_tool/api.py tests/test_reply_suggestion.py
git commit -m "feat: 回复推荐生成与工作空间设置 API"
```

---

### Task 3: 前端 API 封装 + 弹窗组件 + 消息行按钮 + 聊天页接线

**Files:**
- Modify: `frontend/composables/useApi.js`（约 359 行 `getChatMessagesAround` 之后加 3 个函数，并在约 1228 行 return 列表登记）
- Create: `frontend/components/chat/ReplySuggestionDialog.vue`
- Modify: `frontend/components/chat/MessageItem.vue`（消息气泡 `group` 容器内加 hover 按钮）
- Modify: `frontend/pages/chat/[[username]].vue`（chatState 增加 `openReplySuggestion`/`closeReplySuggestion`/`replySuggestionOpen`/`replySuggestionTarget`；模板挂弹窗）
- Test: `frontend/tests/reply-suggestion-dialog.test.js`

**Interfaces:**
- Consumes: Task 2 的三个端点；消息对象字段 `id`（anchor）、`content`、`sender`、`fullTime`、`renderType`；`selectedAccount`、`selectedContact`（chatState 内已有）；`useSettingsDialog().openDialog()` 打开设置
- Produces: `api.generateReplySuggestion({account, conversation, anchor_id, extra_instruction, workspace_dir})`、`api.getReplySuggestionSettings()`、`api.updateReplySuggestionSettings({workspace_dir, enabled})`；`ReplySuggestionDialog` props `{account: String, contact: Object, message: Object}` + emit `close`

- [ ] **Step 1: useApi.js 增加封装**

在 `getChatMessagesAround` 函数（约 349-359 行）后追加：

```js
  // 回复推荐：生成建议与工作空间设置
  const generateReplySuggestion = async (params = {}) => {
    return await request('/reply-suggestions/generate', {
      method: 'POST',
      body: {
        account: params.account || '',
        conversation: params.conversation || '',
        anchor_id: params.anchor_id || '',
        extra_instruction: params.extra_instruction || '',
        workspace_dir: params.workspace_dir ?? null
      },
      timeout: 90_000,
      retry: 0
    })
  }

  const getReplySuggestionSettings = async () => {
    return await request('/reply-suggestions/settings')
  }

  const updateReplySuggestionSettings = async (params = {}) => {
    return await request('/reply-suggestions/settings', {
      method: 'PUT',
      body: { workspace_dir: params.workspace_dir || '', enabled: !!params.enabled }
    })
  }
```

在文件末尾 return 列表中 `getChatMessagesAround,` 之后登记：

```js
    generateReplySuggestion,
    getReplySuggestionSettings,
    updateReplySuggestionSettings,
```

- [ ] **Step 2: ReplySuggestionDialog.vue 组件**

```vue
<!-- frontend/components/chat/ReplySuggestionDialog.vue -->
<template>
  <Teleport to="body">
    <div class="rsd-overlay" @click.self="$emit('close')">
      <section class="rsd-panel" role="dialog" aria-modal="true" aria-label="推荐回复">
        <header class="rsd-header">
          <div class="min-w-0">
            <h3>推荐回复</h3>
            <p class="rsd-muted">{{ headerHint }}</p>
          </div>
          <button type="button" class="rsd-icon-btn" aria-label="关闭" @click="$emit('close')">✕</button>
        </header>

        <div v-if="loading" class="rsd-body rsd-centered">
          <span class="rsd-spin" aria-hidden="true"></span> 正在结合聊天上下文{{ workspaceLabel }}生成建议...
        </div>

        <div v-else-if="error" class="rsd-body rsd-centered rsd-error" role="alert">
          <p>{{ error }}</p>
          <div class="rsd-actions">
            <button v-if="errorCode === 'ai_not_configured'" type="button" class="rsd-primary" @click="openSettings">去设置 AI 服务</button>
            <button v-else type="button" class="rsd-primary" @click="generate">重试</button>
            <button type="button" class="rsd-ghost" @click="$emit('close')">关闭</button>
          </div>
        </div>

        <template v-else>
          <div class="rsd-body">
            <div class="rsd-target">
              <div class="rsd-target-meta">{{ message?.sender }} · {{ message?.fullTime }}</div>
              <div class="rsd-target-text">{{ targetText }}</div>
            </div>
            <label class="rsd-extra">
              <span>补充要求（可选）</span>
              <input v-model="extraInstruction" type="text" maxlength="2000" placeholder="例如：语气轻松一点，确认时间地点" @keydown.enter.prevent="generate" />
            </label>
            <div class="rsd-suggestion">{{ suggestion }}</div>
            <details v-if="result" class="rsd-details">
              <summary>参考信息（{{ result.contextMessages }} 条上下文<template v-if="result.filesConsidered?.length">，{{ result.filesConsidered.length }} 个文件</template>）</summary>
              <p v-if="!result.workspaceUsed && workspaceRequested" class="rsd-warn">工作空间未生效：目录不存在或没有可读取的文本文件。</p>
              <p v-else-if="!result.workspaceUsed">未参考工作空间（可在设置中启用）。</p>
              <p v-if="result.workspaceTruncated" class="rsd-warn">工作空间内容超出上限，已截断。</p>
              <ul v-if="result.filesConsidered?.length" class="rsd-files">
                <li v-for="name in result.filesConsidered" :key="name">{{ name }}</li>
              </ul>
              <p class="rsd-muted">模型：{{ result.model }} · 耗时 {{ result.elapsedMs }}ms</p>
            </details>
          </div>
          <footer class="rsd-footer">
            <button type="button" class="rsd-primary" :disabled="loading" @click="generate">重新生成</button>
            <button type="button" class="rsd-ghost" :disabled="!suggestion || copied" @click="copy">{{ copied ? '已复制' : '复制' }}</button>
            <button type="button" class="rsd-ghost" @click="$emit('close')">关闭</button>
          </footer>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<script>
import { defineComponent, ref, computed, watch } from 'vue'

export default defineComponent({
  name: 'ReplySuggestionDialog',
  props: {
    account: { type: String, default: '' },
    contact: { type: Object, default: null },
    message: { type: Object, default: null }
  },
  emits: ['close'],
  setup(props) {
    const api = useApi()
    const settingsDialog = useSettingsDialog()
    const loading = ref(false)
    const error = ref('')
    const errorCode = ref('')
    const suggestion = ref('')
    const result = ref(null)
    const extraInstruction = ref('')
    const copied = ref(false)
    const workspaceDir = ref('')

    const targetText = computed(() => String(props.message?.content || '').slice(0, 120))
    const headerHint = computed(() => {
      const name = props.contact?.name || props.contact?.username || ''
      return name ? `会话：${name}` : ''
    })
    const workspaceRequested = computed(() => !!workspaceDir.value)
    const workspaceLabel = computed(() => (workspaceRequested.value ? '与工作空间' : ''))

    const generate = async () => {
      const anchorId = String(props.message?.id || '').trim()
      if (!anchorId) return
      loading.value = true
      error.value = ''
      errorCode.value = ''
      suggestion.value = ''
      result.value = null
      copied.value = false
      try {
        let settings = null
        try {
          settings = await api.getReplySuggestionSettings()
        } catch {}
        workspaceDir.value = String(settings?.workspace_dir || '').trim()
        const data = await api.generateReplySuggestion({
          account: props.account,
          conversation: props.contact?.username || '',
          anchor_id: anchorId,
          extra_instruction: extraInstruction.value.trim()
        })
        suggestion.value = String(data?.suggestion || '').trim()
        result.value = data
        if (!suggestion.value) {
          error.value = '模型未返回建议，请重试。'
        }
      } catch (err) {
        error.value = String(err?.message || '生成失败，请重试')
        errorCode.value = String(err?.code || '')
      } finally {
        loading.value = false
      }
    }

    const copy = async () => {
      try {
        await navigator.clipboard.writeText(suggestion.value)
        copied.value = true
        setTimeout(() => { copied.value = false }, 2000)
      } catch {}
    }

    const openSettings = () => {
      settingsDialog.openDialog()
    }

    watch(() => props.message, () => {
      if (props.message) generate()
    }, { immediate: true })

    return {
      loading, error, errorCode, suggestion, result, extraInstruction, copied,
      workspaceDir, workspaceRequested, workspaceLabel, targetText, headerHint,
      generate, copy, openSettings
    }
  }
})
</script>

<style scoped>
.rsd-overlay { position: fixed; inset: 0; z-index: 90; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.45); padding: 16px; }
.rsd-panel { width: 520px; max-width: 100%; max-height: 86vh; display: flex; flex-direction: column; border-radius: 12px; background: var(--app-surface-bg, #fff); box-shadow: 0 20px 50px rgba(0,0,0,.25); overflow: hidden; }
.rsd-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px 16px 10px; border-bottom: 1px solid var(--app-border-soft, #eee); }
.rsd-header h3 { margin: 0; font-size: 15px; color: var(--app-text-primary, #222); }
.rsd-muted { margin: 2px 0 0; font-size: 11px; color: var(--app-text-muted, #999); }
.rsd-body { padding: 14px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.rsd-centered { align-items: center; justify-content: center; min-height: 140px; text-align: center; color: var(--app-text-secondary, #666); font-size: 13px; }
.rsd-error { color: var(--danger-color, #dc2626); }
.rsd-target { border-left: 3px solid var(--app-accent, #07b75b); padding: 6px 10px; background: var(--app-surface-soft, #f7f7f7); border-radius: 6px; }
.rsd-target-meta { font-size: 11px; color: var(--app-text-muted, #999); margin-bottom: 2px; }
.rsd-target-text { font-size: 12px; color: var(--app-text-primary, #333); word-break: break-all; }
.rsd-extra { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--app-text-muted, #888); }
.rsd-extra input { border: 1px solid var(--app-border, #e2e2e2); border-radius: 6px; padding: 6px 8px; font-size: 12px; background: var(--app-surface-bg, #fff); color: var(--app-text-primary, #333); outline: none; }
.rsd-extra input:focus { border-color: var(--app-accent, #07b75b); }
.rsd-suggestion { white-space: pre-wrap; font-size: 13px; line-height: 1.7; color: var(--app-text-primary, #222); background: var(--app-surface-soft, #f7f7f7); border-radius: 8px; padding: 12px; }
.rsd-details { font-size: 11px; color: var(--app-text-secondary, #666); }
.rsd-details summary { cursor: pointer; user-select: none; }
.rsd-files { margin: 6px 0 0; padding-left: 18px; max-height: 120px; overflow-y: auto; }
.rsd-warn { color: var(--danger-color, #dc2626); margin: 4px 0 0; }
.rsd-footer { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 16px; border-top: 1px solid var(--app-border-soft, #eee); }
.rsd-primary, .rsd-ghost, .rsd-icon-btn { border-radius: 6px; font-size: 12px; cursor: pointer; transition: all .15s; }
.rsd-primary { background: var(--app-accent, #07b75b); color: #fff; border: none; padding: 6px 14px; }
.rsd-primary:hover { filter: brightness(1.05); }
.rsd-primary:disabled, .rsd-ghost:disabled { opacity: .5; cursor: not-allowed; }
.rsd-ghost { background: transparent; color: var(--app-text-secondary, #555); border: 1px solid var(--app-border, #e2e2e2); padding: 6px 14px; }
.rsd-ghost:hover { background: var(--app-surface-soft, #f7f7f7); }
.rsd-icon-btn { background: transparent; border: none; color: var(--app-text-muted, #999); font-size: 14px; padding: 2px 6px; }
.rsd-icon-btn:hover { color: var(--app-text-primary, #333); }
.rsd-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--app-border, #ddd); border-top-color: var(--app-accent, #07b75b); border-radius: 50%; animation: rsd-rotate .8s linear infinite; vertical-align: -2px; margin-right: 6px; }
@keyframes rsd-rotate { to { transform: rotate(360deg); } }
</style>
```

- [ ] **Step 3: MessageItem.vue 加 hover 按钮**

在 `MessageContent` 之前（时间 tooltip div 之后，约 76 行）加入按钮，与既有 `group`/`group-hover` 模式一致：

```html
          <button
            v-if="message.renderType !== 'system'"
            type="button"
            class="rs-reply-btn absolute -bottom-5 z-10 text-[10px] px-1.5 py-0.5 rounded border border-[var(--app-border)] bg-[var(--app-surface-bg)] text-[var(--app-text-secondary)] opacity-0 group-hover:opacity-100 transition-opacity"
            :class="message.isSent ? 'right-0' : 'left-0'"
            title="为这条消息生成推荐回复"
            @click.stop="openReplySuggestion(message)"
          >
            推荐回复
          </button>
```

`setup` 返回值来自 `...props.state`，无需改 script（`openReplySuggestion` 由 chatState 注入）。在文件 `<style scoped>` 末尾追加：

```css
.rs-reply-btn:hover {
  color: var(--app-accent);
  border-color: var(--app-accent);
}
```

- [ ] **Step 4: 聊天页 [[username]].vue 接线**

script 中 `const groupAnnouncement = ref('')` 之前加入：

```js
const replySuggestionOpen = ref(false)
const replySuggestionTarget = ref(null)
const openReplySuggestion = (message) => {
  if (!message || !message.id) return
  replySuggestionTarget.value = message
  replySuggestionOpen.value = true
}
const closeReplySuggestion = () => {
  replySuggestionOpen.value = false
  replySuggestionTarget.value = null
}
```

`chatState` 对象（约 1279 行）内 `groupMembersSidebarOpen,` 之前登记：

```js
  openReplySuggestion,
  closeReplySuggestion,
  replySuggestionOpen,
  replySuggestionTarget,
```

模板 `<ChatOverlays :state="chatState" />` 之后追加：

```html
    <ReplySuggestionDialog
      v-if="replySuggestionOpen && replySuggestionTarget"
      :account="selectedAccount"
      :contact="selectedContact"
      :message="replySuggestionTarget"
      @close="closeReplySuggestion"
    />
```

script 头部组件导入区加入（Nuxt 自动导入组件，但该页面其他组件未显式导入，遵循现状直接使用即可，无需 import）。

- [ ] **Step 5: 组件测试**

```js
// frontend/tests/reply-suggestion-dialog.test.js
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReplySuggestionDialog from '../components/chat/ReplySuggestionDialog.vue'

const api = {
  getReplySuggestionSettings: vi.fn(async () => ({ workspace_dir: '', enabled: false })),
  generateReplySuggestion: vi.fn(async () => ({
    suggestion: '建议内容', model: 'fixture', filesConsidered: [], contextMessages: 3,
    workspaceUsed: false, workspaceDir: '', workspaceTruncated: false, elapsedMs: 12
  }))
}
let wrapper
beforeEach(() => {
  vi.stubGlobal('useApi', () => api)
  vi.stubGlobal('useSettingsDialog', () => ({ openDialog: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.clearAllMocks() })

const mountDialog = (message = { id: 'message_0:msg_x:5', content: '在吗', sender: '对方', fullTime: '2026-01-01 10:00' }) => {
  wrapper = mount(defineComponent({
    setup() { return () => h(ReplySuggestionDialog, { account: 'acc', contact: { username: 'chat', name: '会话' }, message }) }
  }), { attachTo: document.body })
}

describe('ReplySuggestionDialog', () => {
  it('挂载后自动生成并展示建议', async () => {
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(api.generateReplySuggestion).toHaveBeenCalledWith({
      account: 'acc', conversation: 'chat', anchor_id: 'message_0:msg_x:5', extra_instruction: ''
    })
    expect(wrapper.text()).toContain('建议内容')
    expect(wrapper.text()).toContain('在吗')
  })

  it('无 AI 配置时展示错误与设置入口', async () => {
    api.generateReplySuggestion.mockRejectedValueOnce(Object.assign(
      new Error('尚未配置 AI 服务'), { code: 'ai_not_configured' }))
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(wrapper.text()).toContain('尚未配置 AI 服务')
    expect(wrapper.text()).toContain('去设置 AI 服务')
  })

  it('重新生成携带补充要求', async () => {
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    const input = wrapper.find('input')
    await input.setValue('语气轻松一点')
    await wrapper.findAll('button').find(b => b.text() === '重新生成').trigger('click')
    await new Promise(r => setTimeout(r, 0))
    expect(api.generateReplySuggestion).toHaveBeenLastCalledWith({
      account: 'acc', conversation: 'chat', anchor_id: 'message_0:msg_x:5', extra_instruction: '语气轻松一点'
    })
  })
})
```

Run: `cd frontend && npx vitest run tests/reply-suggestion-dialog.test.js`
Expected: 3 passed（若组件因 `useApi`/`useSettingsDialog` 为 Nuxt 自动导入而报错，确认 stubGlobal 生效；`Teleport to="body"` 需要 `attachTo`，已配置）

- [ ] **Step 6: Commit**

```bash
git add frontend/composables/useApi.js frontend/components/chat/ReplySuggestionDialog.vue frontend/components/chat/MessageItem.vue "frontend/pages/chat/[[username]].vue" frontend/tests/reply-suggestion-dialog.test.js
git commit -m "feat: 聊天消息行推荐回复入口与建议弹窗"
```

---

### Task 4: 设置页工作空间卡片

**Files:**
- Create: `frontend/components/ReplySuggestionSettings.vue`
- Modify: `frontend/components/SettingsDialog.vue`（AI section 之后挂载，约 255-257 行）

**Interfaces:**
- Consumes: `api.getReplySuggestionSettings()` / `api.updateReplySuggestionSettings()`（Task 3）；`window.wechatDesktop.chooseDirectory({title})` → `{canceled, filePaths}`（Electron 目录选择，见 useChatExport.js:399-404）
- Produces: 无下游依赖（叶子组件）

- [ ] **Step 1: ReplySuggestionSettings.vue**

```vue
<!-- frontend/components/ReplySuggestionSettings.vue -->
<template>
  <div class="divide-y divide-[var(--app-border-soft)] overflow-hidden rounded-[10px] border border-[var(--app-border)] bg-[var(--app-surface-bg)]">
    <div class="px-3.5 py-3">
      <div class="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-[var(--app-text-primary)]">回复推荐工作空间</div>
          <div class="mt-0.5 text-[11px] leading-relaxed text-[var(--app-text-muted)]">
            为"推荐回复"提供参考资料：递归读取该目录下的文本文件（txt/md/json/csv/py/js/ts/vue/html/xml/log/yaml/yml/toml/ini/cfg，单文件 100KB、总量 500KB、最多 100 个文件）。
          </div>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-[6px] border px-2.5 py-1.5 text-[12px] transition"
          :class="enabled ? 'border-[var(--app-accent)] bg-[var(--app-surface-muted)] text-[var(--app-accent)]' : 'border-[var(--app-border)] text-[var(--app-text-secondary)] hover:bg-[var(--app-neutral-btn-hover)]'"
          :aria-pressed="enabled"
          @click="toggleEnabled"
        >
          {{ enabled ? '已启用' : '已停用' }}
        </button>
      </div>

      <div class="mt-2.5 flex items-center gap-2">
        <input
          v-model.trim="dir"
          type="text"
          maxlength="1000"
          placeholder="选择或输入工作空间目录的绝对路径"
          class="min-w-0 flex-1 rounded-[6px] border border-[var(--app-border)] bg-[var(--app-surface-bg)] px-2 py-1.5 text-[12px] text-[var(--app-text-primary)] outline-none transition focus:border-[var(--app-accent)]"
          @keydown.enter.prevent="save"
        >
        <button
          type="button"
          class="shrink-0 rounded-[6px] border border-[#e2e2e2] bg-white px-2 py-1.5 text-[12px] text-[#222] transition hover:bg-[#f9f9f9] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canPickDirectory || saving"
          :title="canPickDirectory ? '选择目录' : '当前环境不支持目录选择，请手动输入'"
          @click="chooseDirectory"
        >
          浏览
        </button>
        <button
          type="button"
          class="shrink-0 rounded-[6px] bg-[var(--app-accent)] px-2.5 py-1.5 text-[12px] text-white transition disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="saving || !dirty"
          @click="save"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>

      <p v-if="notice" class="mt-1.5 text-[11px] text-[var(--app-accent)]">{{ notice }}</p>
      <p v-if="error" class="mt-1.5 text-[11px] text-[var(--danger-color)]">{{ error }}</p>
    </div>
  </div>
</template>

<script>
import { defineComponent, computed, onMounted, ref } from 'vue'

export default defineComponent({
  name: 'ReplySuggestionSettings',
  setup() {
    const api = useApi()
    const dir = ref('')
    const enabled = ref(false)
    const savedDir = ref('')
    const savedEnabled = ref(false)
    const saving = ref(false)
    const loading = ref(true)
    const notice = ref('')
    const error = ref('')

    const dirty = computed(() => dir.value !== savedDir.value || enabled.value !== savedEnabled.value)
    const canPickDirectory = () => !!(process.client && window?.wechatDesktop?.chooseDirectory)

    const load = async () => {
      loading.value = true
      error.value = ''
      try {
        const data = await api.getReplySuggestionSettings()
        dir.value = String(data?.workspace_dir || '')
        enabled.value = !!data?.enabled
        savedDir.value = dir.value
        savedEnabled.value = enabled.value
      } catch (err) {
        error.value = String(err?.message || '读取设置失败')
      } finally {
        loading.value = false
      }
    }

    const toggleEnabled = () => { enabled.value = !enabled.value }

    const chooseDirectory = async () => {
      if (!canPickDirectory()) return
      try {
        const result = await window.wechatDesktop.chooseDirectory({ title: '选择回复推荐工作空间目录' })
        if (result && !result.canceled && Array.isArray(result.filePaths) && result.filePaths.length > 0) {
          dir.value = String(result.filePaths[0] || '').trim()
        }
      } catch {}
    }

    const save = async () => {
      saving.value = true
      notice.value = ''
      error.value = ''
      try {
        const data = await api.updateReplySuggestionSettings({ workspace_dir: dir.value, enabled: enabled.value })
        dir.value = String(data?.workspace_dir ?? dir.value)
        enabled.value = !!data?.enabled
        savedDir.value = dir.value
        savedEnabled.value = enabled.value
        notice.value = '已保存'
        setTimeout(() => { notice.value = '' }, 2000)
      } catch (err) {
        error.value = String(err?.message || '保存失败，请重试')
      } finally {
        saving.value = false
      }
    }

    onMounted(load)

    return { dir, enabled, saving, loading, notice, error, dirty, canPickDirectory, toggleEnabled, chooseDirectory, save }
  }
})
</script>
```

- [ ] **Step 2: SettingsDialog.vue 挂载**

在 `<section ref="aiSectionRef">...</section>`（约 255-257 行）之后追加：

```html
          <section>
            <div class="mb-2.5 text-[12px] font-bold tracking-widest text-[var(--app-text-muted)]">回复推荐</div>
            <ReplySuggestionSettings v-if="open" />
          </section>
```

`SettingsDialog.vue` script 中无需手动 import（Nuxt 组件自动导入，同 `AiSettings` 用法——若该文件对 AiSettings 有显式导入则照做，以文件内现状为准）。

- [ ] **Step 3: 编译与交互验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无新增报错

- [ ] **Step 4: Commit**

```bash
git add frontend/components/ReplySuggestionSettings.vue frontend/components/SettingsDialog.vue
git commit -m "feat: 设置页回复推荐工作空间配置卡片"
```

---

### Task 5: 全量校验与收尾

**Files:**
- 无新增（验证 + 文档状态更新）

- [ ] **Step 1: 后端全量相关测试**

Run: `uv run --no-sync python -m pytest tests/test_workspace_reader.py tests/test_reply_suggestion.py tests/test_ai_model_selection.py tests/test_ai_api.py -v`
Expected: 全部 passed

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npm test`
Expected: 全部 passed（新增 reply-suggestion-dialog.test.js 3 条）

- [ ] **Step 3: 手动冒烟（可选，需用户重启应用）**

告知用户：双击项目根 `start_app.bat` 重启应用，进入聊天页，hover 消息 → 点击"推荐回复"。

- [ ] **Step 4: 汇总变更并提交（如前面各任务已提交则此步为空）**

```bash
git status
git log --oneline -5
```

Expected: 工作区干净，4 个功能提交（Task1/2/3/4 各一）

---

## Self-Review 结果

- **Spec 覆盖**：后端两文件（Task 1/2）、API 三个端点（Task 2）、前端弹窗/按钮/设置卡片/useApi（Task 3/4）、错误边界（无 Key 400、目录不存在→workspaceUsed=false+前端提示、超时 504、定位失败 404，Task 2/3）、测试计划（workspace_reader 单测、合成库+mock LLM、前端组件测试）均已对应。spec 中 `localId + messageId` 由 anchor 三段式承载（Global Constraints 已注明理由）。
- **占位符**：无 TBD/TODO；所有步骤含完整代码。
- **类型一致性**：`read_workspace` 返回结构（Task 1 定义、Task 2 消费）、`generate` 响应字段 camelCase（Task 2 定义、Task 3 前端消费 `suggestion/model/filesConsidered/contextMessages/workspaceUsed/workspaceDir/workspaceTruncated/elapsedMs`）、useApi 三个函数名（Task 3 定义、Task 3/4 消费）均已核对一致。
