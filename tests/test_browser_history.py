"""浏览器记录：扩展上传协议、归一化入库、去重检查与统计。"""
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wechat_decrypt_tool import browser_history as bh


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    return tmp_path


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(bh.upload_router)
    app.include_router(bh.manage_router)
    return TestClient(app, client=("127.0.0.1", 52310), base_url="http://localhost")


def _deepseek_single() -> dict:
    return {
        "data": {
            "biz_data": {
                "chat_session": {"title": "测试会话"},
                "chat_messages": [
                    {"message_id": 1, "role": "USER", "inserted_at": "2021-01-01 10:00:00", "fragments": [{"type": "REQUEST", "content": "你好"}]},
                    {"message_id": 2, "role": "ASSISTANT", "inserted_at": "2021-01-01 10:00:05", "fragments": [{"type": "THINK", "content": "思考中"}, {"type": "RESPONSE", "content": "你好！"}]},
                ],
            }
        }
    }


def _post_upload(c, platform, conversation, conversation_id="c1", title=None, token=bh.UPLOAD_TOKEN):
    return c.post(
        "/upload",
        json={
            "platform": platform,
            "conversation": conversation,
            "conversation_id": conversation_id,
            "title": title,
        },
        headers={"X-Upload-Token": token},
    )


def test_upload_rejects_bad_token(client):
    resp = _post_upload(client, "deepseek", _deepseek_single(), token="wrong")
    assert resp.status_code == 401


def test_upload_deepseek_and_summary(client):
    resp = _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["conversation_id"] == "ds-1"
    assert body["message_count"] == 2

    db = bh._get_db()
    rows = db.execute("SELECT * FROM conversations").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "测试会话"
    msgs = db.execute("SELECT * FROM messages ORDER BY seq").fetchall()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["thinking_content"] == "思考中"

    summary = bh._build_summary()
    assert summary["total_conversations"] == 1
    assert summary["total_messages"] == 2
    assert summary["platforms"][0]["code"] == "deepseek"


def test_upload_same_content_skips(client):
    _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")
    resp = _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")

    body = resp.json()
    assert body["ok"] is True
    assert body.get("skipped") is True

    db = bh._get_db()
    assert db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"] == 2


def test_upload_updated_content_replaces_messages(client):
    _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")
    updated = _deepseek_single()
    msgs = updated["data"]["biz_data"]["chat_messages"]
    msgs.append({"message_id": 3, "role": "USER", "fragments": [{"type": "REQUEST", "content": "再见"}]})
    resp = _post_upload(client, "deepseek", updated, conversation_id="ds-1")

    body = resp.json()
    assert body.get("skipped") is not True
    assert body["message_count"] == 3
    db = bh._get_db()
    assert db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"] == 3


def test_check_reports_what_needs_upload(client):
    _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")

    resp = client.post(
        "/check",
        json={
            "platform": "deepseek",
            "items": [
                {"conversation_id": "ds-1", "updated": "2020-01-01T00:00:00", "count": 2},
                {"conversation_id": "ds-new", "updated": "2030-01-01T00:00:00", "count": 5},
            ],
        },
        headers={"X-Upload-Token": bh.UPLOAD_TOKEN},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["need_upload"] == ["ds-new"]
    assert body["skipped_count"] == 1


def test_batch_log_roundtrip(client):
    resp = client.post(
        "/batch-log",
        json={"batch_no": "b1", "platform": "deepseek", "conversation_count": 3, "message_count": 30},
        headers={"X-Upload-Token": bh.UPLOAD_TOKEN},
    )
    assert resp.json()["ok"] is True
    # 幂等
    resp = client.post(
        "/batch-log",
        json={"batch_no": "b1", "platform": "deepseek", "conversation_count": 4, "message_count": 40},
        headers={"X-Upload-Token": bh.UPLOAD_TOKEN},
    )
    assert resp.json()["ok"] is True
    db = bh._get_db()
    row = db.execute("SELECT * FROM export_batches WHERE batch_no='b1'").fetchone()
    assert row["conversation_count"] == 4


def test_normalize_kimi_batch_item():
    conv = {
        "chat_id": "k1",
        "title": "Kimi标题",
        "messages": [
            {"id": "m1", "role": "user", "createTime": 1700000000000, "blocks": [{"text": {"content": "问题"}}]},
            {"id": "m2", "role": "assistant", "createTime": 1700000001000, "blocks": [{"think": {"content": "推理"}}, {"text": {"content": "回答"}}]},
        ],
    }
    n = bh.normalize_conversation("kimi", conv)
    assert n["conversation_id"] == "k1"
    assert n["title"] == "Kimi标题"
    assert [m["role"] for m in n["messages"]] == ["user", "assistant"]
    assert n["messages"][1]["thinking_content"] == "推理"
    assert n["messages"][0]["msg_time"] is not None


def test_normalize_doubao_batch_item():
    conv = {
        "conversation_id": "d1",
        "name": "豆包标题",
        "messages": [
            {"message_id": "a", "user_type": 1, "create_time": 1700000000, "content_type": 1, "content": '{"text":"提问"}'},
            {
                "message_id": "b",
                "user_type": 2,
                "create_time": 1700000001,
                "content_type": 9999,
                "content": json_dumps_if_needed([{"block_type": 10000, "content": {"text_block": {"text": "回答"}}}]),
                "thinking": "思考",
            },
        ],
    }
    n = bh.normalize_conversation("doubao", conv)
    assert n["conversation_id"] == "d1"
    assert [m["role"] for m in n["messages"]] == ["user", "assistant"]
    assert n["messages"][1]["content"] == "回答"
    assert n["messages"][1]["thinking_content"] == "思考"


def json_dumps_if_needed(v):
    import json

    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def test_upload_unknown_platform(client):
    resp = _post_upload(client, "unknown_platform", _deepseek_single())
    assert resp.status_code == 400
    assert "不支持的平台" in resp.json()["error"]


def test_manage_status_endpoint(client):
    _post_upload(client, "deepseek", _deepseek_single(), conversation_id="ds-1")

    resp = client.get("/api/context/browser-history/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["installed"] in (True, False)  # 取决于本机浏览器，不炸即可
    assert body["summary"]["total_conversations"] == 1


def test_prepare_extension_creates_patched_copy(client, tmp_path):
    vendor = Path(bh.__file__).parent / "browser_extension_src"
    if not vendor.is_dir():
        pytest.skip("vendor 扩展目录不存在")

    resp = client.post("/api/context/browser-history/extension/prepare")

    assert resp.status_code == 200
    ext_dir = Path(resp.json()["extension_dir"])
    assert (ext_dir / "manifest.json").exists()
    manifest = (ext_dir / "manifest.json").read_text(encoding="utf-8")
    assert "http://127.0.0.1/*" in manifest
    content = (ext_dir / "content.js").read_text(encoding="utf-8")
    assert f"http://127.0.0.1:{bh.BACKEND_PORT}" in content
    assert "114.55.254.123" not in content


def test_exe_from_command_extracts_quoted_path():
    assert bh._exe_from_command('"C:\\Apps\\chrome.exe" --single-argument') == "C:\\Apps\\chrome.exe"
    assert bh._exe_from_command("C:\\Apps\\chrome.exe --flag") == "C:\\Apps\\chrome.exe"
    assert bh._exe_from_command("") == ""


def test_open_extensions_page_launches_found_exe_directly(monkeypatch):
    """找到浏览器时直接以可执行文件 + URL 启动，绝不走系统默认打开（会弹选择应用框）。"""
    launched: list[list[str]] = []
    monkeypatch.setattr(bh, "_candidate_browser_exes", lambda kind: [r"C:\fake\chrome.exe"] if kind == "chrome" else [])
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: launched.append(args))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda *a, **kw: pytest.fail("不应调用 os.startfile"))

    result = bh.open_extensions_page("chrome")

    assert result["ok"] is True
    assert result["url"] == "chrome://extensions/"
    assert launched == [[r"C:\fake\chrome.exe", "chrome://extensions/"]]


def test_open_extensions_page_without_browser_returns_error(monkeypatch):
    """任何浏览器都找不到时返回引导手动打开的错误信息，不弹系统对话框。"""
    monkeypatch.setattr(bh, "_candidate_browser_exes", lambda kind: [])
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda *a, **kw: pytest.fail("不应调用 os.startfile"))

    result = bh.open_extensions_page("chrome")

    assert result["ok"] is False
    assert "chrome://extensions/" in result["error"]
