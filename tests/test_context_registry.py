"""context_registry：源注册表、settings 持久化与 manifest 读写。"""
import pytest

from wechat_decrypt_tool import context_registry as cr


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR", raising=False)
    return tmp_path


def test_list_sources_registers_five_sources():
    sources = {s["source_id"]: s for s in cr.list_sources()}
    assert set(sources) == {
        "wechat",
        "browser_history",
        "computer_activity",
        "mobile_upload",
        "custom_capture",
    }


def test_stub_sources_report_planned_and_create_dirs(tmp_path):
    cr.list_sources()
    for sid in ("browser_history", "computer_activity", "mobile_upload", "custom_capture"):
        status = cr.SOURCES[sid].status()
        assert status["planned"] is True
        assert status["state"] == "planned"
        assert status["last_saved_at"] is None
        assert (tmp_path / "contexts" / sid).is_dir()


def test_stub_sources_carry_config_placeholders():
    browser = cr.SOURCES["browser_history"].status()
    assert browser["summary"]["plugin"] == {"install": "planned", "update": "planned"}
    mobile = cr.SOURCES["mobile_upload"].status()
    assert mobile["summary"]["nextcloud"] == {"server_url": "", "configured": False}


def test_wechat_source_defaults():
    status = cr.SOURCES["wechat"].status()
    assert status["planned"] is False
    assert status["enabled"] is True
    assert status["state"] in {"idle", "up_to_date"}


def test_settings_roundtrip(tmp_path):
    settings = cr.load_settings()
    assert settings["wechat"]["enabled"] is True
    assert settings["browser_history"]["enabled"] is False

    saved = cr.save_settings({"wechat": {"enabled": False}})
    assert saved["wechat"]["enabled"] is False
    assert cr.load_settings()["wechat"]["enabled"] is False
    assert (tmp_path / "contexts" / "settings.json").is_file()


def test_save_settings_ignores_unknown_source_and_keys():
    saved = cr.save_settings({"evil": {"enabled": True}, "wechat": {"hacked": True}})
    assert "evil" not in saved
    assert "hacked" not in saved["wechat"]


def test_manifest_roundtrip():
    manifest = cr.write_manifest("wechat", summary={"accounts": 1}, data_ref="X:/out/databases")
    assert manifest["source_id"] == "wechat"
    assert manifest["summary"] == {"accounts": 1}
    assert manifest["last_saved_at"]

    assert cr.read_manifest("wechat") == manifest
    assert cr.read_manifest("browser_history") == {}


def test_wechat_status_reads_manifest():
    cr.write_manifest("wechat", summary={"accounts": 2}, data_ref="X:/out")
    status = cr.SOURCES["wechat"].status()
    assert status["summary"] == {"accounts": 2}
    assert status["last_saved_at"] == cr.read_manifest("wechat")["last_saved_at"]
