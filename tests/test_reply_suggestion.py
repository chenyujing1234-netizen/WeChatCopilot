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
    prompts = []
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
            # 转写包含目标消息及其前文，不含后续消息
            assert '消息1' in prompts[0] and '消息3' in prompts[0] and '消息4' not in prompts[0]
    asyncio.run(check())


def test_generate_without_ai_configured_returns_code(tmp_path, monkeypatch):
    store = AIStore(tmp_path / 'empty-ai')
    app = FastAPI()
    monkeypatch.setattr(reply_suggestion, 'get_ai_service', lambda: AIService(store))
    app.include_router(reply_suggestion.router)

    async def check():
        async with _client(app) as client:
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
            assert '消息16' in prompts[0] and '消息15' not in prompts[0]
    asyncio.run(check())
