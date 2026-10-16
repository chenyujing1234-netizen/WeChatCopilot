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


@pytest.fixture
def quiet_autosave_services(monkeypatch):
    """切换保存位置会停/起自动保存服务，测试中全部 mock 掉避免真实线程。"""
    monkeypatch.setattr(context_router.WECHAT_AUTOSAVE, "start", mock.Mock())
    monkeypatch.setattr(context_router.WECHAT_AUTOSAVE, "stop", mock.Mock())
    monkeypatch.setattr(context_router.CHAT_REALTIME_AUTOSYNC, "stop", mock.Mock())


def test_settings_data_dir_roundtrip(client, monkeypatch, tmp_path, quiet_autosave_services):
    target = tmp_path / "custom_store"

    resp = client.put("/api/context/settings", json={"wechat": {"data_dir": str(target)}})

    assert resp.status_code == 200
    assert resp.json()["settings"]["wechat"]["data_dir"] == str(target)
    assert target.is_dir()

    from wechat_decrypt_tool.app_paths import get_output_databases_dir

    assert str(get_output_databases_dir()) == str(target)

    resp = client.get("/api/context/sources")
    wechat = [s for s in resp.json()["sources"] if s["source_id"] == "wechat"][0]
    assert wechat["data_dir"] == str(target)
    assert wechat["data_dir_effective"] == str(target)


def test_settings_data_dir_restore_default(client, monkeypatch, tmp_path, quiet_autosave_services):
    target = tmp_path / "custom_store"
    client.put("/api/context/settings", json={"wechat": {"data_dir": str(target)}})

    resp = client.put("/api/context/settings", json={"wechat": {"data_dir": ""}})

    assert resp.status_code == 200
    assert resp.json()["settings"]["wechat"]["data_dir"] == ""
    from wechat_decrypt_tool.app_paths import get_output_databases_dir

    assert str(get_output_databases_dir()) != str(target)


def test_settings_reject_relative_data_dir(client, quiet_autosave_services):
    resp = client.put("/api/context/settings", json={"wechat": {"data_dir": "relative/path"}})

    assert resp.status_code == 400
    resp = client.get("/api/context/settings")
    assert resp.json()["settings"]["wechat"]["data_dir"] == ""


def test_settings_data_dir_migrates_existing_data(client, monkeypatch, tmp_path, quiet_autosave_services):
    from wechat_decrypt_tool.app_paths import get_output_databases_dir

    default_dir = get_output_databases_dir()
    account_dir = default_dir / "wxid_test"
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / "Chat.db").write_bytes(b"fake-db-content")

    target = tmp_path / "custom_store"
    resp = client.put("/api/context/settings", json={"wechat": {"data_dir": str(target)}})

    assert resp.status_code == 200
    assert (target / "wxid_test" / "Chat.db").read_bytes() == b"fake-db-content"
    # 旧数据保留，不做删除
    assert (default_dir / "wxid_test" / "Chat.db").exists()


def test_settings_data_dir_ignored_for_other_sources(client, quiet_autosave_services):
    resp = client.put("/api/context/settings", json={"browser_history": {"data_dir": "C:\\somewhere"}})

    assert resp.status_code == 200
    assert "data_dir" not in resp.json()["settings"]["browser_history"]


def test_local_only_blocks_remote_client():
    app = FastAPI()
    app.include_router(context_router.router)
    remote = TestClient(app, client=("203.0.113.9", 52311))

    resp = remote.get("/api/context/sources")

    assert resp.status_code == 403
