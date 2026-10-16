"""品牌改造：ContextBuddy 对外名称统一。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fastapi_title_is_contextbuddy():
    from wechat_decrypt_tool.api import app

    assert app.title == "ContextBuddy"


def test_desktop_package_brand():
    pkg = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "context-buddy-desktop"
    assert pkg["build"]["productName"] == "ContextBuddy"
    assert pkg["build"]["appId"] == "com.lifearchive.contextbuddy"


def test_preload_brand_string():
    text = (ROOT / "desktop" / "src" / "preload.cjs").read_text(encoding="utf-8")
    assert '"ContextBuddyDesktop"' in text
    assert '"WeChatDataAnalysisDesktop"' not in text
