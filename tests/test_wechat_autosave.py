"""wechat_autosave：微信上下文自动保存服务的状态机与保存链路。"""
import threading
import time
from unittest import mock

import pytest

from wechat_decrypt_tool import context_registry
from wechat_decrypt_tool import wechat_autosave


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    return tmp_path


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr(wechat_autosave, "_wechat_running", mock.Mock(return_value=True))
    monkeypatch.setattr(
        wechat_autosave,
        "_resolve_current_account_context",
        mock.Mock(return_value={
            "account": "wxid_test",
            "db_storage_path": r"D:\wechat\xwechat_files\wxid_test\db_storage",
            "wechat_install_path": r"D:\wechat",
        }),
    )
    service = wechat_autosave.WechatAutosaveService()
    monkeypatch.setattr(wechat_autosave.CHAT_REALTIME_AUTOSYNC, "start", mock.Mock())
    return service


def _patch_decrypt_ok(monkeypatch, successful_count=3):
    decrypt = mock.Mock(return_value={
        "status": "success",
        "message": "ok",
        "successful_count": successful_count,
        "account_results": {"wxid_test": {"success": successful_count}},
    })
    monkeypatch.setattr(wechat_autosave, "decrypt_wechat_databases", decrypt)
    return decrypt


def test_realtime_autosync_enabled_by_default(monkeypatch):
    monkeypatch.delenv("WECHAT_TOOL_REALTIME_AUTOSYNC", raising=False)
    from wechat_decrypt_tool.chat_realtime_autosync import ChatRealtimeAutoSyncService

    assert ChatRealtimeAutoSyncService()._enabled is True


def test_run_once_success_with_stored_key(svc, monkeypatch, isolated_data_dir):
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={"db_key": "a" * 64}),
    )
    acquire = mock.Mock(return_value=[])
    release = mock.Mock()
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", acquire)
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", release)
    decrypt = _patch_decrypt_ok(monkeypatch)
    persist = mock.Mock(return_value=(True, []))
    monkeypatch.setattr(wechat_autosave, "_persist_db_keys", persist)
    get_key = mock.Mock()
    monkeypatch.setattr(wechat_autosave, "get_db_key_workflow", get_key)

    result = svc._run_once()

    assert result["status"] == 0
    assert svc.get_state()["state"] == "up_to_date"
    assert decrypt.call_args.kwargs["key"] == "a" * 64
    assert decrypt.call_args.kwargs["db_storage_path"].endswith("db_storage")
    assert get_key.call_count == 0
    assert persist.call_count == 1
    assert acquire.call_count == 1
    assert release.call_count == 1

    manifest = context_registry.read_manifest("wechat")
    assert manifest["summary"]["account"] == "wxid_test"
    assert manifest["summary"]["successful_databases"] == 3
    assert manifest["summary"]["accounts"] == 1
    assert manifest["data_ref"]


def test_run_once_acquires_key_when_store_empty(svc, monkeypatch):
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={}),
    )
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", mock.Mock(return_value=[]))
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", mock.Mock())
    _patch_decrypt_ok(monkeypatch)
    monkeypatch.setattr(wechat_autosave, "_persist_db_keys", mock.Mock(return_value=(True, [])))
    get_key = mock.Mock(return_value={"db_key": "b" * 64})
    monkeypatch.setattr(wechat_autosave, "get_db_key_workflow", get_key)

    result = svc._run_once()

    assert result["status"] == 0
    assert get_key.call_count == 1
    assert get_key.call_args.kwargs["db_storage_path"].endswith("db_storage")


def test_run_once_waiting_wechat_when_process_missing(monkeypatch):
    monkeypatch.setattr(wechat_autosave, "_wechat_running", mock.Mock(return_value=False))
    service = wechat_autosave.WechatAutosaveService()

    result = service._run_once()

    assert result["status"] == -1
    assert service.get_state()["state"] == "waiting_wechat"


def test_run_once_waiting_wechat_when_no_account(svc):
    wechat_autosave._resolve_current_account_context.return_value = {}

    result = svc._run_once()

    assert result["status"] == -1
    assert svc.get_state()["state"] == "waiting_wechat"


def test_run_once_error_when_decrypt_fails(svc, monkeypatch):
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={"db_key": "a" * 64}),
    )
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", mock.Mock(return_value=[]))
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", mock.Mock())
    monkeypatch.setattr(
        wechat_autosave,
        "decrypt_wechat_databases",
        mock.Mock(return_value={"status": "error", "message": "failed", "successful_count": 0}),
    )

    result = svc._run_once()

    assert result["status"] == -1
    assert svc.get_state()["state"] == "error"
    # 对外错误信息不透出内部细节
    assert "密钥" not in result["errmsg"]
    assert "解密" not in result["errmsg"]


def test_stored_key_failure_reacquires(svc, monkeypatch):
    """存储凭据连续保存失败达到上限后，应重新采集。"""
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={"db_key": "a" * 64}),
    )
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", mock.Mock(return_value=[]))
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", mock.Mock())
    monkeypatch.setattr(
        wechat_autosave,
        "decrypt_wechat_databases",
        mock.Mock(return_value={"status": "error", "message": "failed", "successful_count": 0}),
    )
    get_key = mock.Mock(return_value={"db_key": "b" * 64})
    monkeypatch.setattr(wechat_autosave, "get_db_key_workflow", get_key)

    svc._run_once()
    svc._run_once()
    assert get_key.call_count == 0

    _patch_decrypt_ok(monkeypatch, successful_count=2)
    monkeypatch.setattr(wechat_autosave, "_persist_db_keys", mock.Mock(return_value=(True, [])))
    svc._run_once()

    assert get_key.call_count == 1
    assert svc.get_state()["state"] == "up_to_date"


def _patch_save_dependencies(monkeypatch, successful_count=3):
    """为成功保存路径打全依赖补丁，返回 decrypt mock。"""
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={"db_key": "a" * 64}),
    )
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", mock.Mock(return_value=[]))
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", mock.Mock())
    decrypt = _patch_decrypt_ok(monkeypatch, successful_count)
    monkeypatch.setattr(wechat_autosave, "_persist_db_keys", mock.Mock(return_value=(True, [])))
    return decrypt


def test_sync_now_busy(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(wechat_autosave, "_SYNC_NOW_WAIT_SECONDS", 0.05)
    wechat_autosave._wechat_running  # 确认模块可导入
    service = wechat_autosave.WechatAutosaveService()
    service._sync_lock.acquire()
    try:
        result = service.sync_now()
        assert result["status"] == -1
        assert "稍候" in result["errmsg"]
    finally:
        service._sync_lock.release()


def test_sync_now_waits_for_inflight_round(svc, monkeypatch):
    """在途轮持锁时，sync_now 等待其完成后执行，而不是立即报忙。"""
    monkeypatch.setattr(wechat_autosave, "_SYNC_NOW_WAIT_SECONDS", 5.0)
    decrypt = _patch_save_dependencies(monkeypatch)

    svc._sync_lock.acquire()

    def release_later():
        time.sleep(0.1)
        svc._sync_lock.release()

    holder = threading.Thread(target=release_later)
    holder.start()
    try:
        result = svc.sync_now()
        assert result["status"] == 0
        assert decrypt.call_count == 1
    finally:
        holder.join()


def test_sync_now_reuses_recent_success(svc, monkeypatch):
    """近期已成功保存时，sync_now 直接复用最近结果，不重复保存。"""
    decrypt = _patch_save_dependencies(monkeypatch)

    assert svc._run_once()["status"] == 0

    result = svc.sync_now()

    assert result["status"] == 0
    assert result["summary"]["account"] == "wxid_test"
    assert decrypt.call_count == 1


def test_sync_now_reruns_after_success_window(svc, monkeypatch):
    """超过近期成功窗口后，sync_now 重新执行一轮保存。"""
    monkeypatch.setattr(wechat_autosave, "_RECENT_SUCCESS_SKIP_SECONDS", -1.0)
    decrypt = _patch_save_dependencies(monkeypatch)

    assert svc._run_once()["status"] == 0

    result = svc.sync_now()

    assert result["status"] == 0
    assert decrypt.call_count == 2


def test_disabled_reflects_settings(isolated_data_dir):
    context_registry.save_settings({"wechat": {"enabled": False}})
    service = wechat_autosave.WechatAutosaveService()
    assert service._enabled() is False


def test_start_stop_thread(monkeypatch, isolated_data_dir):
    monkeypatch.setattr(wechat_autosave, "_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(wechat_autosave, "_wechat_running", mock.Mock(return_value=False))
    service = wechat_autosave.WechatAutosaveService()
    service.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline and service.get_state()["state"] == "idle":
            time.sleep(0.02)
        assert service.get_state()["state"] == "waiting_wechat"
    finally:
        service.stop()


def test_tick_skipped_while_sync_lock_held(svc, monkeypatch):
    """tick 与 sync_now 互斥：手动保存持锁期间，后台 tick 跳过保存。"""
    monkeypatch.setattr(wechat_autosave, "_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(
        wechat_autosave,
        "get_account_keys_from_store",
        mock.Mock(return_value={"db_key": "a" * 64}),
    )
    monkeypatch.setattr(wechat_autosave, "_acquire_decrypt_account_guards", mock.Mock(return_value=[]))
    monkeypatch.setattr(wechat_autosave, "_release_decrypt_account_guards", mock.Mock())
    decrypt = _patch_decrypt_ok(monkeypatch)
    monkeypatch.setattr(wechat_autosave, "_persist_db_keys", mock.Mock(return_value=(True, [])))
    monkeypatch.setattr(wechat_autosave, "get_db_key_workflow", mock.Mock())

    svc._sync_lock.acquire()
    svc.start()
    try:
        time.sleep(0.2)  # 覆盖约 10 个 tick 周期
        assert decrypt.call_count == 0
        assert svc.get_state()["state"] == "idle"
    finally:
        svc.stop()
        svc._sync_lock.release()
