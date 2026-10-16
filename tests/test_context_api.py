"""context 路由：源列表、设置、手动触发与本机限制。"""
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wechat_decrypt_tool.routers import context as context_router


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    return tmp_path


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(context_router.router)
    return TestClient(app, client=("127.0.0.1", 52310), base_url="http://localhost")


def test_sources_lists_all_five(client):
    resp = client.get("/api/context/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    ids = {s["source_id"] for s in body["sources"]}
    assert ids == {
        "wechat",
        "browser_history",
        "computer_activity",
        "mobile_upload",
        "custom_capture",
    }
    planned = {s["source_id"] for s in body["sources"] if s["planned"]}
    assert planned == {"browser_history", "computer_activity", "mobile_upload", "custom_capture"}


def test_settings_roundtrip(client):
    resp = client.get("/api/context/settings")
    assert resp.json()["settings"]["wechat"]["enabled"] is True

    resp = client.put("/api/context/settings", json={"wechat": {"enabled": False}})
    assert resp.status_code == 200
    assert resp.json()["settings"]["wechat"]["enabled"] is False

    resp = client.get("/api/context/settings")
    assert resp.json()["settings"]["wechat"]["enabled"] is False


def test_settings_ignores_unknown_source(client):
    resp = client.put("/api/context/settings", json={"evil": {"enabled": True}})
    assert resp.status_code == 200
    assert "evil" not in resp.json()["settings"]


def test_sync_now_success(client, monkeypatch):
    sync = mock.Mock(return_value={
        "status": 0,
        "errmsg": "ok",
        "state": "up_to_date",
        "summary": {"accounts": 1, "account": "wxid_test", "successful_databases": 3},
    })
    monkeypatch.setattr(context_router, "WECHAT_AUTOSAVE", mock.Mock(sync_now=sync))

    resp = client.post("/api/context/wechat/sync-now")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == 0
    assert body["summary"]["account"] == "wxid_test"
    assert sync.call_count == 1


def test_sync_now_error_is_generic(client, monkeypatch):
    sync = mock.Mock(return_value={"status": -1, "errmsg": "内部错误: 密钥失败", "state": "error"})
    monkeypatch.setattr(context_router, "WECHAT_AUTOSAVE", mock.Mock(sync_now=sync))

    resp = client.post("/api/context/wechat/sync-now")

    body = resp.json()
    assert body["status"] == -1
    assert "密钥" not in body["errmsg"]
    assert "解密" not in body["errmsg"]


def test_local_only_blocks_remote_client():
    app = FastAPI()
    app.include_router(context_router.router)
    remote = TestClient(app, client=("203.0.113.9", 52311))

    resp = remote.get("/api/context/sources")

    assert resp.status_code == 403
