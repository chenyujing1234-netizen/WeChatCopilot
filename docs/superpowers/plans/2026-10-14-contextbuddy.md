# ContextBuddy 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复制 WeChatDataAnalysis 工程为独立应用 ContextBuddy，实现微信上下文自动保存（隐藏解密细节），并预留 4 类数据源接口。

**Architecture:** 新工程 `e:\Source\ContextBuddy`（全新 git 仓库，原工程零改动）。后端新增 `context_registry.py`（源注册表 + settings/manifest 持久化）与 `wechat_autosave.py`（常驻线程：进程检测 → 账号检测 → 密钥就绪 → 落盘 → 实时同步 → 更新 manifest），通过 `routers/context.py` 暴露本机 API；前端将 `pages/index.vue` 替换为上下文中心首页。品牌与数据目录全面隔离。

**Tech Stack:** FastAPI + pytest（后端，包名 `wechat_decrypt_tool` 保留）；Nuxt 3 + vitest（前端）；Electron（桌面端）。

## Global Constraints

- 原工程 `e:\Source\WeChatDataAnalysis` 任何文件不得修改；新工程位于 `e:\Source\ContextBuddy`
- 用户可见品牌一律 ContextBuddy；内部 Python 包名 `wechat_decrypt_tool` 保留不改
- UI 与 context API 不出现"密钥/解密"字样；错误信息对外只给通用提示（内部日志可含细节）
- ContextBuddy 数据目录为 `%APPDATA%/ContextBuddy`，由桌面端通过 `WECHAT_TOOL_DATA_DIR` 传入；后端 `app_paths.get_data_dir()` 已支持该环境变量
- 各源开关的唯一权威存储为 `contexts/settings.json`（manifest 不存 enabled，避免双写不一致）
- 微信自动保存总开关默认开启；后端常驻线程，异常只记日志不崩线程
- 后端测试命令：`uv run --no-sync python -m pytest tests/<file>.py -v`（在新工程根目录执行；PowerShell 无 `&&`，用 `;` 或分行）
- 前端测试命令：在 `frontend` 目录 `npx vitest run tests/<file>.test.js`；构建 `npm run build`
- 提交信息格式：`feat: 中文描述`
- 已核实的复用接口（勿重写）：
  - `key_service.get_db_key_workflow(wechat_install_path=None, *, db_storage_path=None, internal_db_key=None, key_mode="auto", ...)` — Windows auto 模式：V4 内存扫描优先、失败回退 Hook；返回含 `db_key` 的 dict；**不自动写 key store**
  - `wechat_decrypt.decrypt_wechat_databases(db_storage_path, key)` — 落盘 `get_output_databases_dir()`（`output/databases/`），返回含 `status/successful_count/account_results`
  - `routers/decrypt.py` 的 `_acquire_decrypt_account_guards(accounts, reason)` / `_release_decrypt_account_guards(guards, reason)`（解密期间暂停实时同步的守卫）与 `_persist_db_keys(account_results, key) -> (bool, list[str])`（校验 session+message 角色后写 key store）
  - `wechat_detection.detect_current_logged_in_account()` → `{"current_account": wxid, ...}`；`detect_wechat_installation()` → `info["accounts"] = [{account_name, data_dir, ...}]`；matched_folder 规则：`name == wxid or name.startswith(f"{wxid}_")`；`db_storage_path = data_dir/db_storage`
  - `wechat_detection.get_process_list()` + `_wechat_process_targets()`（进程扫描）
  - `CHAT_REALTIME_AUTOSYNC`（`chat_realtime_autosync.py:398` 单例，`start()/stop()` 幂等；启用开关 env `WECHAT_TOOL_REALTIME_AUTOSYNC`，原默认 False）

---

### Task 1: 复制工程、依赖重建与仓库初始化

**Files:**
- Create: `e:\Source\ContextBuddy\`（整个工程树）
- 已存在于目标：`docs/superpowers/specs/2026-10-14-contextbuddy-design.md`、`docs/superpowers/plans/2026-10-14-contextbuddy.md`（robocopy 不删除目标独有文件）

**Interfaces:**
- Produces: 可运行的后端 + 前端 + 桌面端代码树；git 仓库含首个提交（spec + plan + 全部代码）

- [ ] **Step 1: robocopy 复制工程（排除产物目录）**

```powershell
robocopy e:\Source\WeChatDataAnalysis e:\Source\ContextBuddy /E /XD .git node_modules .venv .output .nuxt dist output __pycache__ .pytest_cache .ruff_cache
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }
```

预期：退出码 0-7 皆成功（1=有文件复制）。注意 robocopy /E 合并目录，目标已有的 docs/specs、docs/plans 不会被覆盖删除。

- [ ] **Step 2: 验证关键文件已复制**

用 Glob 检查以下文件存在：`pyproject.toml`、`src/wechat_decrypt_tool/api.py`、`frontend/package.json`、`desktop/package.json`、`start_app.bat`、`frontend/tests/` 目录。缺任一文件则排查 robocopy 排除项。

- [ ] **Step 3: 重建依赖**

```powershell
uv sync
```
（在 `e:\Source\ContextBuddy` 根目录执行；预计数分钟，超时设置 600000）

```powershell
npm install
```
（分别在 `e:\Source\ContextBuddy\frontend` 与 `e:\Source\ContextBuddy\desktop` 执行）

- [ ] **Step 4: 后端冒烟：应用可导入**

```powershell
uv run --no-sync python -c "from wechat_decrypt_tool.api import app; print('OK', app.title)"
```
预期输出：`OK 微信数据库解密工具`（品牌在 Task 2 修改）。

- [ ] **Step 5: git init 与首个提交**

```powershell
git init
git add -A
git status
```
确认 `git status` 中**没有** `node_modules/`、`.venv/`、`output/`、`.nuxt/`、`dist/`（.gitignore 已随工程复制，应已忽略）。若有，检查 .gitignore 是否缺失对应条目并补充后再 add。

```powershell
git commit -m "feat: 初始化 ContextBuddy 工程（复制自 WeChatDataAnalysis）"
```

首个提交必须包含 `docs/superpowers/specs/2026-10-14-contextbuddy-design.md` 与 `docs/superpowers/plans/2026-10-14-contextbuddy.md`。

---

### Task 2: 品牌改造与数据目录隔离

**Files:**
- Modify: `desktop/package.json:2,32,33`
- Modify: `desktop/src/main.cjs`（resolveDataDir fallback 约 :382-388；品牌字符串 :814,:1816,:1845,:2540,:3569 等）
- Modify: `desktop/src/preload.cjs:65`
- Modify: `src/wechat_decrypt_tool/api.py:57-61`
- Modify: `frontend/nuxt.config.ts:86,90`
- Modify: `frontend/app.vue:235`
- Modify: `start_app.bat`
- Test: `tests/test_brand.py`

**Interfaces:**
- Consumes: Task 1 的代码树
- Produces: `app.title == "ContextBuddy"`；preload `__brand == "ContextBuddyDesktop"`；桌面数据目录 fallback `%APPDATA%/ContextBuddy`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_brand.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --no-sync python -m pytest tests/test_brand.py -v
```
预期：3 个测试 FAIL（title 为 微信数据库解密工具，品牌字符串未改）。

- [ ] **Step 3: 修改 desktop/package.json**

```json
  "name": "context-buddy-desktop",
```
```json
    "appId": "com.lifearchive.contextbuddy",
    "productName": "ContextBuddy",
```

- [ ] **Step 4: 修改 desktop/src/main.cjs**

(a) 品牌字符串：在 main.cjs 内将 `WeChatDataAnalysis` 全部替换为 `ContextBuddy`（涉及托盘 tooltip :1845、错误对话框 :1816/:3569、托盘气泡 :2540、output-location.txt 文案 :814 及注释；共约 39 处命中，用 Edit 的 replace_all）。注意 `WECHAT_TOOL_*` 环境变量名不含该词，不受影响。

(b) 数据目录 fallback（resolveDataDir，约 :382-388）改为固定 `%APPDATA%/ContextBuddy`：

```js
  const fromEnv = String(process.env.WECHAT_TOOL_DATA_DIR || "").trim();
  const fallback = (() => {
    try {
      return path.join(app.getPath("appData") || "", "ContextBuddy");
    } catch {
      return null;
    }
  })();
```
（仅替换 fallback 内部实现，函数其余部分不动；`startBackend` 约 :2125 已把 `WECHAT_TOOL_DATA_DIR` 传给后端进程，无需改动。）

- [ ] **Step 5: 修改 desktop/src/preload.cjs:65**

```js
  __brand: "ContextBuddyDesktop",
```

- [ ] **Step 6: 修改 src/wechat_decrypt_tool/api.py:57-61**

```python
app = FastAPI(
    title="ContextBuddy",
    description="本地上下文收集与保存工具，自动保存微信等上下文数据",
    version=APP_VERSION,
)
```

- [ ] **Step 7: 修改 frontend/nuxt.config.ts:86,90**

```ts
      title: 'ContextBuddy',
```
```ts
        { name: 'description', content: '本地上下文收集与保存工具' }
```

- [ ] **Step 8: 修改 frontend/app.vue:235（品牌校验）**

```js
  const brandOk = !api?.__brand || api.__brand === 'ContextBuddyDesktop'
```

- [ ] **Step 9: 重写 start_app.bat**

```bat
@echo off
rem ContextBuddy desktop launcher
rem Sets a longer backend startup timeout, then runs the full dev stack
rem (frontend :3000 + backend :10392 + Electron window).

cd /d e:\Source\ContextBuddy\desktop
if errorlevel 1 (
  echo [ERROR] Cannot find e:\Source\ContextBuddy\desktop
  pause
  exit /b 1
)

set WECHAT_TOOL_BACKEND_STARTUP_TIMEOUT_MS=180000
echo Starting ContextBuddy (frontend + backend + Electron)...
echo Press Ctrl+C in this window to stop the app.
echo.

call npm run dev

echo.
echo App stopped.
pause
```

- [ ] **Step 10: 运行测试确认通过**

```powershell
uv run --no-sync python -m pytest tests/test_brand.py -v
```
预期：3 个 PASS。若 `test_fastapi_title_is_contextbuddy` 因导入失败（环境缺可选二进制依赖），改为断言源码：`(ROOT / "src" / "wechat_decrypt_tool" / "api.py").read_text(encoding="utf-8")` 包含 `title="ContextBuddy"`。

- [ ] **Step 11: 全局品牌残留检查**

用 Grep 在 `desktop/src/`、`desktop/package.json`、`start_app.bat` 搜索 `WeChatDataAnalysis`，预期 0 命中。

- [ ] **Step 12: Commit**

```powershell
git add desktop/package.json desktop/src/main.cjs desktop/src/preload.cjs src/wechat_decrypt_tool/api.py frontend/nuxt.config.ts frontend/app.vue start_app.bat tests/test_brand.py
git commit -m "feat: 品牌改造为 ContextBuddy 并隔离数据目录到 %APPDATA%/ContextBuddy"
```

---

### Task 3: context_registry.py — 上下文源注册表与 4 个 stub

**Files:**
- Create: `src/wechat_decrypt_tool/context_registry.py`
- Test: `tests/test_context_registry.py`

**Interfaces:**
- Consumes: `app_paths.get_data_dir()`（读 `WECHAT_TOOL_DATA_DIR`）
- Produces（后续任务依赖，名称精确）:
  - `load_settings() -> dict`（如 `{"wechat": {"enabled": True}, ...}`）
  - `save_settings(settings: dict) -> dict`（合并已知源，忽略未知源，仅接受 `enabled` 键）
  - `read_manifest(source_id: str) -> dict`（不存在返回 `{}`）
  - `write_manifest(source_id: str, *, summary: dict, data_ref: str) -> dict`（返回 `{source_id, last_saved_at, summary, data_ref}`）
  - `list_sources() -> list[dict]`（每项 `{source_id, name, enabled, state, last_saved_at, summary, planned}`）
  - `SOURCES: dict[str, ContextSource]`；`ContextSource` Protocol：`source_id`、`display_name`、`status() -> dict`、`start()`、`stop()`
  - 5 个源：`wechat`（真实）、`browser_history` / `computer_activity` / `mobile_upload` / `custom_capture`（stub，`planned=True`）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_context_registry.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --no-sync python -m pytest tests/test_context_registry.py -v
```
预期：全部 FAIL（ModuleNotFoundError: context_registry）。

- [ ] **Step 3: 实现 context_registry.py**

创建 `src/wechat_decrypt_tool/context_registry.py`：

```python
"""上下文源注册表：统一管理各数据源的状态、开关与元数据。

目录结构（<data_dir>/contexts/）：
- settings.json             各源开关的唯一权威存储（manifest 不存 enabled）
- <source_id>/manifest.json {source_id, last_saved_at, summary, data_ref}
"""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .app_paths import get_data_dir
from .logging_config import get_logger

logger = get_logger(__name__)

_SETTINGS_LOCK = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "wechat": {"enabled": True},
    "browser_history": {"enabled": False},
    "computer_activity": {"enabled": False},
    "mobile_upload": {"enabled": False},
    "custom_capture": {"enabled": False},
}


def get_contexts_root() -> Path:
    root = get_data_dir() / "contexts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_settings_path() -> Path:
    return get_contexts_root() / "settings.json"


def _ensure_source_dir(source_id: str) -> Path:
    path = get_contexts_root() / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict[str, Any]:
    try:
        data = json.loads(get_settings_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception:
        logger.exception("[context] settings.json 解析失败，回退默认设置")
        data = {}
    if not isinstance(data, dict):
        data = {}
    merged = {source_id: dict(item) for source_id, item in DEFAULT_SETTINGS.items()}
    for source_id, overrides in data.items():
        if source_id not in merged or not isinstance(overrides, dict):
            continue
        merged[source_id].update(overrides)
    return merged


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = load_settings()
    for source_id, overrides in (settings or {}).items():
        if source_id not in normalized or not isinstance(overrides, dict):
            continue
        normalized[source_id].update(
            {key: value for key, value in overrides.items() if key == "enabled"}
        )
    with _SETTINGS_LOCK:
        get_settings_path().write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return normalized


def get_manifest_path(source_id: str) -> Path:
    return get_contexts_root() / source_id / "manifest.json"


def read_manifest(source_id: str) -> dict[str, Any]:
    try:
        return json.loads(get_manifest_path(source_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("[context] manifest 读取失败: source=%s", source_id)
        return {}


def write_manifest(source_id: str, *, summary: dict[str, Any], data_ref: str) -> dict[str, Any]:
    manifest = {
        "source_id": source_id,
        "last_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "data_ref": data_ref,
    }
    path = get_manifest_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return manifest


@runtime_checkable
class ContextSource(Protocol):
    """上下文源适配器接口：浏览器插件等未来数据源按此接口接入。"""

    source_id: str
    display_name: str

    def status(self) -> dict[str, Any]: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...


class PlannedStubSource:
    """规划中的数据源占位：目录与 API 位置就位，无采集逻辑。"""

    planned = True

    def __init__(
        self,
        source_id: str,
        display_name: str,
        description: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.source_id = source_id
        self.display_name = display_name
        self.description = description
        self.extra = dict(extra or {})

    def status(self) -> dict[str, Any]:
        _ensure_source_dir(self.source_id)
        settings = load_settings()
        return {
            "source_id": self.source_id,
            "name": self.display_name,
            "enabled": bool(settings.get(self.source_id, {}).get("enabled")),
            "state": "planned",
            "last_saved_at": None,
            "summary": {"description": self.description, **self.extra},
            "planned": True,
        }

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class WechatContextSource:
    """微信上下文源：真实实现，状态来自自动保存服务与 manifest。"""

    planned = False
    source_id = "wechat"
    display_name = "微信数据"

    def status(self) -> dict[str, Any]:
        settings = load_settings()
        manifest = read_manifest("wechat")
        state = "up_to_date" if manifest else "idle"
        try:
            from .wechat_autosave import WECHAT_AUTOSAVE

            state = str(WECHAT_AUTOSAVE.get_state().get("state") or state)
        except Exception:
            # wechat_autosave 尚未就绪（Task 4 前回退 manifest）
            pass
        return {
            "source_id": self.source_id,
            "name": self.display_name,
            "enabled": bool(settings.get("wechat", {}).get("enabled", True)),
            "state": state,
            "last_saved_at": manifest.get("last_saved_at"),
            "summary": manifest.get("summary") or {},
            "planned": False,
        }

    def start(self) -> None:
        from .wechat_autosave import WECHAT_AUTOSAVE

        WECHAT_AUTOSAVE.start()

    def stop(self) -> None:
        from .wechat_autosave import WECHAT_AUTOSAVE

        WECHAT_AUTOSAVE.stop()


BROWSER_HISTORY_SOURCE = PlannedStubSource(
    "browser_history",
    "浏览器记录",
    "将以浏览器插件方式接入（豆包、Qwen 等浏览记录），插件随应用安装并可更新。",
    extra={"plugin": {"install": "planned", "update": "planned"}},
)
COMPUTER_ACTIVITY_SOURCE = PlannedStubSource(
    "computer_activity",
    "电脑操作记录",
    "记录本机操作行为，辅助回顾电脑上的工作上下文。",
)
MOBILE_UPLOAD_SOURCE = PlannedStubSource(
    "mobile_upload",
    "手机上传",
    "配合手机端 NextCloud 应用，手动上传手机上的上下文数据。",
    extra={"nextcloud": {"server_url": "", "configured": False}},
)
CUSTOM_CAPTURE_SOURCE = PlannedStubSource(
    "custom_capture",
    "定制浏览器抓取",
    "自动生成定制浏览器插件，抓取指定浏览器中的数据。",
)

SOURCES: dict[str, ContextSource] = {
    "wechat": WechatContextSource(),
    "browser_history": BROWSER_HISTORY_SOURCE,
    "computer_activity": COMPUTER_ACTIVITY_SOURCE,
    "mobile_upload": MOBILE_UPLOAD_SOURCE,
    "custom_capture": CUSTOM_CAPTURE_SOURCE,
}


def list_sources() -> list[dict[str, Any]]:
    return [source.status() for source in SOURCES.values()]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
uv run --no-sync python -m pytest tests/test_context_registry.py -v
```
预期：8 个 PASS。

- [ ] **Step 5: Commit**

```powershell
git add src/wechat_decrypt_tool/context_registry.py tests/test_context_registry.py
git commit -m "feat: 上下文源注册表与四个规划源 stub"
```

---

### Task 4: wechat_autosave.py — 微信上下文自动保存服务

**Files:**
- Create: `src/wechat_decrypt_tool/wechat_autosave.py`
- Modify: `src/wechat_decrypt_tool/chat_realtime_autosync.py:108`（默认启用）
- Modify: `src/wechat_decrypt_tool/api.py`（import + startup/shutdown 接线）
- Test: `tests/test_wechat_autosave.py`

**Interfaces:**
- Consumes: Task 3 的 `load_settings/write_manifest/read_manifest`；Global Constraints 列出的复用函数（`get_db_key_workflow`、`decrypt_wechat_databases`、`_persist_db_keys`、`_acquire_decrypt_account_guards`、`_release_decrypt_account_guards`、`detect_current_logged_in_account`、`detect_wechat_installation`、`get_process_list`、`_wechat_process_targets`、`get_account_keys_from_store`、`CHAT_REALTIME_AUTOSYNC.start`、`get_output_databases_dir`）
- Produces:
  - 模块级函数 `_wechat_running() -> bool`、`_resolve_current_account_context() -> dict`（返回 `{"account", "db_storage_path", "wechat_install_path"}` 或 `{}`）
  - 类 `WechatAutosaveService`：`start()`、`stop()`、`get_state() -> {"state", "last_error"}`、`sync_now() -> {"status", "errmsg", "state", ...}`
  - 单例 `WECHAT_AUTOSAVE`
  - 状态机：`idle → wechat_detected → saving → up_to_date / waiting_wechat / error / disabled`
  - manifest summary 结构：`{"accounts": int, "account": str, "successful_databases": int}`；`data_ref = str(get_output_databases_dir())`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_wechat_autosave.py`：

```python
"""wechat_autosave：微信上下文自动保存服务的状态机与保存链路。"""
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
    return monkeypatch.setattr(
        wechat_autosave,
        "decrypt_wechat_databases",
        mock.Mock(return_value={
            "status": "success",
            "message": "ok",
            "successful_count": successful_count,
            "account_results": {"wxid_test": {"success": successful_count}},
        }),
    )


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


def test_sync_now_busy(isolated_data_dir):
    wechat_autosave._wechat_running  # 确认模块可导入
    service = wechat_autosave.WechatAutosaveService()
    service._sync_lock.acquire()
    try:
        result = service.sync_now()
        assert result["status"] == -1
        assert "稍候" in result["errmsg"]
    finally:
        service._sync_lock.release()


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
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --no-sync python -m pytest tests/test_wechat_autosave.py -v
```
预期：全部 FAIL（ModuleNotFoundError: wechat_autosave；`_enabled` 默认值测试也 FAIL）。

- [ ] **Step 3: 实时同步默认启用**

`src/wechat_decrypt_tool/chat_realtime_autosync.py:108`：

```python
        self._enabled = _env_bool("WECHAT_TOOL_REALTIME_AUTOSYNC", True)
```
（ContextBuddy 的核心是自动保存，实时同步随应用默认开启；`api.py` startup 已有 `CHAT_REALTIME_AUTOSYNC.start()`，无需改。）

- [ ] **Step 4: 实现 wechat_autosave.py**

创建 `src/wechat_decrypt_tool/wechat_autosave.py`：

```python
"""微信上下文自动保存服务。

后台常驻线程（模式参考 CHAT_REALTIME_AUTOSYNC），约 30s 一轮：
1. 进程扫描（复用 wechat_detection）
2. 检测当前登录账号 → 解析 db_storage 路径
3. 凭据就绪（key store 或重新采集）→ 落盘 output/databases/<wxid>
4. 启动实时同步；更新 contexts/wechat/manifest.json
状态机：idle → wechat_detected → saving → up_to_date / waiting_wechat / error / disabled
对外错误信息不透出内部处理细节（隐藏解密）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from .app_paths import get_output_databases_dir
from .chat_realtime_autosync import CHAT_REALTIME_AUTOSYNC
from .context_registry import load_settings, write_manifest
from .key_store import get_account_keys_from_store
from .key_service import get_db_key_workflow
from .logging_config import get_logger
from .routers.decrypt import (
    _acquire_decrypt_account_guards,
    _persist_db_keys,
    _release_decrypt_account_guards,
)
from .wechat_decrypt import decrypt_wechat_databases
from .wechat_detection import (
    _wechat_process_targets,
    detect_current_logged_in_account,
    detect_wechat_installation,
    get_process_list,
)

logger = get_logger(__name__)

_INTERVAL_SECONDS = 30.0
_STORED_KEY_FAILURE_LIMIT = 2


def _wechat_running() -> bool:
    """复用 wechat_detection 的进程扫描：Weixin.exe / WeChat.exe。"""
    try:
        targets = _wechat_process_targets()
        return any(
            str(name or "").lower() in targets
            for _, name in get_process_list()
        )
    except Exception:
        logger.exception("[wechat-autosave] 微信进程扫描失败")
        return False


def _resolve_current_account_context() -> dict[str, Any]:
    """检测当前登录账号，解析 {"account", "db_storage_path", "wechat_install_path"}。

    matched_folder 规则与 /api/wechat-detection 一致：
    目录名 wxid_xxxx_yyyy 归属真实 wxid_xxxx。
    """
    account_info = detect_current_logged_in_account()
    wxid = str(account_info.get("current_account") or "").strip()
    if not wxid:
        return {}

    installation = detect_wechat_installation()
    account = ""
    data_dir = ""
    for acc in installation.get("accounts", []):
        name = str(acc.get("account_name") or "")
        if name == wxid or name.startswith(f"{wxid}_"):
            account = name
            data_dir = str(acc.get("data_dir") or "")
            break
    if not account or not data_dir:
        return {}

    db_storage_path = os.path.join(data_dir, "db_storage")
    if not os.path.isdir(db_storage_path):
        return {}
    return {
        "account": account,
        "db_storage_path": db_storage_path,
        "wechat_install_path": installation.get("wechat_install_path"),
    }


class WechatAutosaveService:
    """微信上下文自动保存：常驻线程轮询，异常只记日志不崩线程。"""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sync_lock = threading.Lock()
        self._state = "idle"
        self._last_error = ""
        self._stored_key_failures = 0

    def get_state(self) -> dict[str, Any]:
        with self._mu:
            return {"state": self._state, "last_error": self._last_error}

    def _set_state(self, state: str, last_error: str = "") -> None:
        with self._mu:
            self._state = state
            self._last_error = str(last_error or "")
        logger.info("[wechat-autosave] state=%s", state)

    def start(self) -> None:
        with self._mu:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="wechat-autosave", daemon=True
            )
            self._thread.start()
        logger.info("[wechat-autosave] started interval_s=%s", _INTERVAL_SECONDS)

    def stop(self) -> None:
        with self._mu:
            thread = self._thread
            self._thread = None
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout=5.0)
        logger.info("[wechat-autosave] stopped")

    def _enabled(self) -> bool:
        return bool(load_settings().get("wechat", {}).get("enabled", True))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._enabled():
                    self._set_state("disabled")
                else:
                    self._run_once()
            except Exception:
                logger.exception("[wechat-autosave] tick failed")
                self._set_state("error", "内部错误")
            self._stop_event.wait(_INTERVAL_SECONDS)

    def sync_now(self) -> dict[str, Any]:
        """手动触发一轮保存；与后台线程互斥，重入返回忙。"""
        if not self._sync_lock.acquire(blocking=False):
            return {
                "status": -1,
                "errmsg": "正在保存中，请稍候",
                "state": self.get_state()["state"],
            }
        try:
            summary = self._run_once()
            result = dict(summary)
            result.setdefault("state", self.get_state()["state"])
            return result
        finally:
            self._sync_lock.release()

    def _run_once(self) -> dict[str, Any]:
        try:
            return self._save_pass()
        except Exception as exc:
            logger.exception("[wechat-autosave] 保存失败")
            self._set_state("error", str(exc))
            # 对外错误不透出内部处理细节（隐藏解密）
            return {
                "status": -1,
                "errmsg": "本轮保存未完成，微信保持登录后稍后会自动重试",
                "state": self.get_state()["state"],
            }

    def _save_pass(self) -> dict[str, Any]:
        if not _wechat_running():
            self._set_state("waiting_wechat")
            return {"status": -1, "errmsg": "未检测到微信客户端"}

        context = _resolve_current_account_context()
        account = str(context.get("account") or "")
        db_storage_path = str(context.get("db_storage_path") or "")
        if not account or not db_storage_path:
            self._set_state("waiting_wechat")
            return {"status": -1, "errmsg": "微信已运行，但尚未识别到已登录账号"}

        self._set_state("wechat_detected")

        used_stored_key = False
        key = ""
        stored = get_account_keys_from_store(account)
        if (
            isinstance(stored, dict)
            and str(stored.get("db_key") or "").strip()
            and self._stored_key_failures < _STORED_KEY_FAILURE_LIMIT
        ):
            key = str(stored["db_key"]).strip()
            used_stored_key = True
        if not key:
            key = self._acquire_key(context)

        self._set_state("saving")
        guards = _acquire_decrypt_account_guards([account], reason="wechat-autosave")
        try:
            results = decrypt_wechat_databases(
                db_storage_path=db_storage_path, key=key
            )
        finally:
            _release_decrypt_account_guards(guards, reason="wechat-autosave")

        successful_count = int(results.get("successful_count") or 0)
        if results.get("status") != "success" or successful_count <= 0:
            if used_stored_key:
                self._stored_key_failures += 1
                logger.warning(
                    "[wechat-autosave] 使用已保存凭据保存失败 account=%s failures=%s",
                    account,
                    self._stored_key_failures,
                )
            raise RuntimeError(str(results.get("message") or "本轮保存没有成功数据"))

        _persist_db_keys(results.get("account_results"), key)
        self._stored_key_failures = 0

        try:
            CHAT_REALTIME_AUTOSYNC.start()
        except Exception:
            logger.exception("[wechat-autosave] 启动实时同步失败")

        manifest = write_manifest(
            "wechat",
            summary={
                "accounts": 1,
                "account": account,
                "successful_databases": successful_count,
            },
            data_ref=str(get_output_databases_dir()),
        )
        self._set_state("up_to_date")
        logger.info(
            "[wechat-autosave] saved account=%s databases=%s",
            account,
            successful_count,
        )
        return {
            "status": 0,
            "errmsg": "ok",
            "state": "up_to_date",
            "summary": manifest["summary"],
            "last_saved_at": manifest["last_saved_at"],
        }

    def _acquire_key(self, context: dict[str, Any]) -> str:
        result = get_db_key_workflow(
            wechat_install_path=context.get("wechat_install_path"),
            db_storage_path=context.get("db_storage_path"),
        )
        key = str(result.get("db_key") or "").strip()
        if not key:
            raise RuntimeError("本轮凭据采集没有结果")
        return key


WECHAT_AUTOSAVE = WechatAutosaveService()
```

- [ ] **Step 5: api.py 接线**

(a) import 区（`from .sns_realtime_autosync import SNS_REALTIME_AUTOSYNC` 之后，约 :24）加：

```python
from .wechat_autosave import WECHAT_AUTOSAVE
```

(b) `_startup_background_jobs`（SNS 启动块之后，约 :303）加：

```python
    try:
        WECHAT_AUTOSAVE.start()
    except Exception:
        logger.exception("Failed to start wechat autosave service")
```

(c) `_shutdown_wcdb_realtime`（`CHAT_REALTIME_AUTOSYNC.stop()` 块之后，约 :313）加：

```python
    try:
        WECHAT_AUTOSAVE.stop()
    except Exception:
        pass
```

- [ ] **Step 6: 运行测试确认通过**

```powershell
uv run --no-sync python -m pytest tests/test_wechat_autosave.py -v
```
预期：10 个 PASS。

- [ ] **Step 7: 回归 Task 3 测试**

```powershell
uv run --no-sync python -m pytest tests/test_context_registry.py -v
```
预期：仍全部 PASS（WechatContextSource 现在能导入 WECHAT_AUTOSAVE，`test_wechat_source_defaults` 的 state 断言集合包含 "idle"，兼容）。

- [ ] **Step 8: Commit**

```powershell
git add src/wechat_decrypt_tool/wechat_autosave.py src/wechat_decrypt_tool/chat_realtime_autosync.py src/wechat_decrypt_tool/api.py tests/test_wechat_autosave.py
git commit -m "feat: 微信上下文自动保存服务"
```

---

### Task 5: routers/context.py — 上下文 API

**Files:**
- Create: `src/wechat_decrypt_tool/routers/context.py`
- Modify: `src/wechat_decrypt_tool/api.py`（import + include_router）
- Test: `tests/test_context_api.py`

**Interfaces:**
- Consumes: Task 3 的 `list_sources/load_settings/save_settings`；Task 4 的 `WECHAT_AUTOSAVE.sync_now`
- Produces（前端 Task 6 依赖，路径精确）:
  - `GET /api/context/sources` → `{"status": "ok", "sources": [{source_id, name, enabled, state, last_saved_at, summary, planned}, ...]}`
  - `GET /api/context/settings` → `{"status": "ok", "settings": {...}}`
  - `PUT /api/context/settings`（body 如 `{"wechat": {"enabled": false}}`）→ `{"status": "ok", "settings": {...}}`
  - `POST /api/context/wechat/sync-now` → `{"status": 0/-1, "errmsg", "state", "summary", "last_saved_at"}`；错误信息不出现"密钥/解密"
  - 全部端点仅本机访问（local_only，403 拒绝远端）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_context_api.py`：

```python
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
    return TestClient(app, client=("127.0.0.1", 52310))


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
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --no-sync python -m pytest tests/test_context_api.py -v
```
预期：全部 FAIL（routers.context 不存在）。

- [ ] **Step 3: 实现 routers/context.py**

创建 `src/wechat_decrypt_tool/routers/context.py`：

```python
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
```

- [ ] **Step 4: api.py 注册路由**

(a) import 区（`from .routers.cdn import router as _cdn_router` 之后，约 :54）加：

```python
from .routers.context import router as _context_router
```

(b) `app.include_router(_cdn_router)`（约 :162）之后加：

```python
app.include_router(_context_router)
```

- [ ] **Step 5: 运行测试确认通过**

```powershell
uv run --no-sync python -m pytest tests/test_context_api.py tests/test_wechat_autosave.py tests/test_context_registry.py -v
```
预期：24 个 PASS。

- [ ] **Step 6: Commit**

```powershell
git add src/wechat_decrypt_tool/routers/context.py src/wechat_decrypt_tool/api.py tests/test_context_api.py
git commit -m "feat: 上下文中心 API"
```

---

### Task 6: 前端上下文中心

**Files:**
- Modify: `frontend/composables/useApi.js`（新增 4 个函数 + return 列表，约 :1226 前）
- Replace: `frontend/pages/index.vue`（整文件替换为上下文中心首页）
- Modify: `frontend/app.vue:26-35,151-154`（GuideDialog 文案与跳转）
- Modify: `frontend/components/SidebarRail.vue`（新增"上下文中心"入口 + 两处文案）
- Test: `frontend/tests/context-center.test.js`

**Interfaces:**
- Consumes: Task 5 的 4 个 API（`/context/sources`、`/context/settings` PUT、`/context/wechat/sync-now`）；`request()` 直接返回解析后的 JSON body，路径不带 `/api` 前缀（`request('/context/sources')` → `/api/context/sources`）
- Produces: `useApi()` 新增 `getContextSources() / getContextSettings() / updateContextSettings(data) / triggerWechatSync()`

- [ ] **Step 1: 写失败测试**

创建 `frontend/tests/context-center.test.js`：

```js
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ContextHome from '../pages/index.vue'

const api = {
  getContextSources: vi.fn(),
  getContextSettings: vi.fn(),
  updateContextSettings: vi.fn(),
  triggerWechatSync: vi.fn()
}
let wrapper

const sourcesPayload = () => ({
  status: 'ok',
  sources: [
    { source_id: 'wechat', name: '微信数据', enabled: true, state: 'up_to_date', last_saved_at: '2026-10-14T10:00:00', summary: { accounts: 1, account: 'wxid_a', successful_databases: 12 }, planned: false },
    { source_id: 'browser_history', name: '浏览器记录', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '将以浏览器插件方式接入（豆包、Qwen 等浏览记录），插件随应用安装并可更新。' }, planned: true },
    { source_id: 'computer_activity', name: '电脑操作记录', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '记录本机操作行为' }, planned: true },
    { source_id: 'mobile_upload', name: '手机上传', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '配合手机端 NextCloud 应用' }, planned: true },
    { source_id: 'custom_capture', name: '定制浏览器抓取', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '自动生成定制浏览器插件' }, planned: true }
  ]
})

beforeEach(() => {
  vi.stubGlobal('useApi', () => api)
  vi.stubGlobal('navigateTo', vi.fn())
  api.getContextSources.mockReset().mockImplementation(async () => sourcesPayload())
  api.getContextSettings.mockReset().mockResolvedValue({ status: 'ok', settings: { wechat: { enabled: true } } })
  api.updateContextSettings.mockReset().mockResolvedValue({ status: 'ok', settings: { wechat: { enabled: false } } })
  api.triggerWechatSync.mockReset().mockResolvedValue({ status: 0, errmsg: 'ok', state: 'up_to_date', summary: { accounts: 1 } })
})

afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

const mountHome = async () => {
  wrapper = mount(ContextHome, { global: { stubs: { GlobalExportDialog: true } } })
  await flushPromises()
  return wrapper
}

describe('上下文中心首页', () => {
  it('渲染微信卡片与四个规划中的数据源', async () => {
    const w = await mountHome()
    expect(w.text()).toContain('微信数据')
    expect(w.text()).toContain('已是最新')
    expect(w.text()).toContain('2026-10-14T10:00:00')
    expect(w.text()).toContain('浏览器记录')
    expect(w.text()).toContain('将以浏览器插件方式接入')
    const plannedBadges = w.findAll('.rounded-full').filter(b => b.text() === '规划中')
    expect(plannedBadges).toHaveLength(4)
  })

  it('切换自动保存开关调用设置接口', async () => {
    const w = await mountHome()
    await w.find('input[type=checkbox]').setValue(false)
    await flushPromises()
    expect(api.updateContextSettings).toHaveBeenCalled()
    expect(api.updateContextSettings.mock.calls[0][0]).toEqual({ wechat: { enabled: false } })
  })

  it('立即保存调用触发接口并展示结果', async () => {
    const w = await mountHome()
    await w.findAll('button').find(b => b.text() === '立即保存').trigger('click')
    await flushPromises()
    expect(api.triggerWechatSync).toHaveBeenCalledTimes(1)
    expect(w.text()).toContain('本轮保存已完成。')
  })

  it('页面文案不出现解密与密钥字样', async () => {
    const w = await mountHome()
    expect(w.text()).not.toContain('解密')
    expect(w.text()).not.toContain('密钥')
  })
})
```

- [ ] **Step 2: 运行确认失败**

```powershell
cd frontend
npx vitest run tests/context-center.test.js
```
预期：FAIL（旧 index.vue 无微信卡片/开关，找不到相应元素）。

- [ ] **Step 3: useApi.js 新增 4 个封装**

(a) 在 `return {`（约 :1226）之前加入：

```js
  // 上下文中心API
  const getContextSources = async () => {
    return await request('/context/sources')
  }

  const getContextSettings = async () => {
    return await request('/context/settings')
  }

  const updateContextSettings = async (data) => {
    return await request('/context/settings', {
      method: 'PUT',
      body: data
    })
  }

  const triggerWechatSync = async () => {
    return await request('/context/wechat/sync-now', {
      method: 'POST'
    })
  }
```

(b) 在 return 列表（`pickSystemDirectory,` 之后）加入 4 项：`getContextSources,`、`getContextSettings,`、`updateContextSettings,`、`triggerWechatSync,`

- [ ] **Step 4: 整文件替换 pages/index.vue**

```vue
<template>
  <div class="min-h-screen px-6 py-10 md:px-10">
    <div class="mx-auto w-full max-w-[980px]">
      <header class="flex items-center gap-4">
        <img src="/logo.png" alt="ContextBuddy Logo" class="h-16 w-16 shrink-0 object-contain" />
        <div>
          <h1 class="text-2xl font-bold text-[#000000e6]">ContextBuddy</h1>
          <p class="mt-1 text-[13px] leading-6 text-[#7F7F7F]">把你的上下文自动保存在本地，需要时随时查看。</p>
        </div>
      </header>

      <div v-if="error" class="mt-6 rounded-[10px] border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-600">
        {{ error }}
      </div>

      <!-- 微信上下文卡片 -->
      <section class="mt-8 rounded-[14px] border border-[#e8e8e8] bg-white p-6 shadow-[0_10px_40px_-24px_rgba(0,0,0,0.35)]">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h2 class="text-[16px] font-semibold text-[#000000e6]">{{ wechatSource?.name || '微信数据' }}</h2>
              <span class="rounded-full px-2 py-0.5 text-[11px] font-medium" :class="stateBadgeClass">{{ stateText }}</span>
            </div>
            <p class="mt-2 text-[13px] leading-6 text-[#7F7F7F]">微信登录后自动保存聊天等数据到本机，并保持实时更新。</p>
          </div>
          <label class="flex shrink-0 cursor-pointer items-center gap-2 text-[12px] text-[#5f5f5f]" title="自动保存总开关">
            <span>自动保存</span>
            <input
              type="checkbox"
              class="h-[18px] w-[18px] accent-[#07c160]"
              :checked="wechatEnabled"
              :disabled="loading || toggling"
              @change="toggleWechatEnabled"
            />
          </label>
        </div>

        <div class="mt-5 grid grid-cols-2 gap-3 rounded-[10px] bg-[#fafafa] px-4 py-3 text-[12px] text-[#5f5f5f] md:grid-cols-3">
          <div>
            <div class="text-[#8a8a8a]">已保存账号</div>
            <div class="mt-1 font-medium text-[#222]">{{ wechatSummary.accounts ?? '—' }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">最近保存</div>
            <div class="mt-1 font-medium text-[#222]">{{ wechatSource?.last_saved_at || '尚未保存' }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">当前账号</div>
            <div class="mt-1 truncate font-medium text-[#222]">{{ wechatSummary.account || '—' }}</div>
          </div>
        </div>

        <div class="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="rounded-[8px] bg-[#07c160] px-4 py-2 text-[13px] font-medium text-white transition hover:bg-[#06ad56] disabled:opacity-60"
            :disabled="syncing"
            @click="syncNow"
          >
            {{ syncing ? '正在保存…' : '立即保存' }}
          </button>
          <button
            type="button"
            class="rounded-[8px] border border-[#e4e4e4] bg-white px-4 py-2 text-[13px] font-medium text-[#333] transition hover:border-[#07c160] hover:text-[#07c160]"
            @click="viewWechatContext"
          >
            查看微信上下文
          </button>
          <div class="ml-auto flex items-center gap-4 text-[12px] text-[#8a8a8a]">
            <a class="cursor-pointer hover:text-[#07c160]" title="导入已有备份" @click="goImport">导入备份</a>
            <a class="cursor-pointer hover:text-[#07c160]" title="检测本机微信数据" @click="goDetection">账号检测</a>
            <a class="cursor-pointer hover:text-[#07c160]" title="导出已保存数据" @click="openExportDialog">导出</a>
          </div>
        </div>
        <p v-if="syncMessage" class="mt-3 text-[12px] leading-5" :class="syncMessageOk ? 'text-[#07964c]' : 'text-red-500'">{{ syncMessage }}</p>
      </section>

      <!-- 规划中的数据源 -->
      <section class="mt-8">
        <h3 class="text-[14px] font-semibold text-[#000000e6]">更多上下文来源（规划中）</h3>
        <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div
            v-for="source in plannedSources"
            :key="source.source_id"
            class="rounded-[12px] border border-dashed border-[#dcdcdc] bg-white/70 px-5 py-4"
          >
            <div class="flex items-center justify-between gap-3">
              <span class="text-[14px] font-medium text-[#000000e6]">{{ source.name }}</span>
              <span class="rounded-full bg-[#f2f2f2] px-2 py-0.5 text-[11px] text-[#8a8a8a]">规划中</span>
            </div>
            <p class="mt-2 text-[12px] leading-5 text-[#7F7F7F]">{{ source.summary?.description || '即将接入。' }}</p>
          </div>
        </div>
      </section>
    </div>

    <GlobalExportDialog :open="exportDialogOpen" @close="closeExportDialog" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useApi } from '~/composables/useApi'

const { getContextSources, getContextSettings, updateContextSettings, triggerWechatSync } = useApi()

const sources = ref([])
const wechatEnabled = ref(true)
const loading = ref(true)
const toggling = ref(false)
const syncing = ref(false)
const error = ref('')
const syncMessage = ref('')
const syncMessageOk = ref(true)
const exportDialogOpen = ref(false)

const wechatSource = computed(() => sources.value.find(s => s.source_id === 'wechat') || null)
const plannedSources = computed(() => sources.value.filter(s => s.source_id !== 'wechat'))
const wechatSummary = computed(() => wechatSource.value?.summary || {})

const STATE_TEXT = {
  idle: '待自动保存',
  wechat_detected: '已检测到微信',
  saving: '正在保存',
  up_to_date: '已是最新',
  waiting_wechat: '等待微信登录',
  error: '保存出错，稍后重试',
  disabled: '已暂停'
}

const stateText = computed(() => STATE_TEXT[wechatSource.value?.state || 'idle'] || '待自动保存')

const stateBadgeClass = computed(() => {
  const state = wechatSource.value?.state || 'idle'
  if (state === 'up_to_date') return 'bg-[#eefbf4] text-[#07964c]'
  if (state === 'saving' || state === 'wechat_detected') return 'bg-[#fff7e6] text-[#b7791f]'
  if (state === 'error') return 'bg-[#fdecec] text-[#c53030]'
  return 'bg-[#f2f2f2] text-[#8a8a8a]'
})

const reload = async () => {
  try {
    const [sourcesResp, settingsResp] = await Promise.all([
      getContextSources(),
      getContextSettings()
    ])
    sources.value = sourcesResp?.sources || []
    wechatEnabled.value = !!(settingsResp?.settings?.wechat?.enabled)
  } catch (e) {
    error.value = e?.message || '加载上下文状态失败'
  } finally {
    loading.value = false
  }
}

const toggleWechatEnabled = async (event) => {
  const enabled = !!event?.target?.checked
  toggling.value = true
  wechatEnabled.value = enabled
  try {
    await updateContextSettings({ wechat: { enabled } })
    await reload()
  } catch (e) {
    wechatEnabled.value = !enabled
    error.value = e?.message || '保存开关失败'
  } finally {
    toggling.value = false
  }
}

const syncNow = async () => {
  syncing.value = true
  syncMessage.value = ''
  try {
    const resp = await triggerWechatSync()
    if (resp?.status === 0) {
      syncMessageOk.value = true
      syncMessage.value = '本轮保存已完成。'
    } else {
      syncMessageOk.value = false
      syncMessage.value = resp?.errmsg || '本轮保存未完成，稍后会自动重试。'
    }
    await reload()
  } catch (e) {
    syncMessageOk.value = false
    syncMessage.value = e?.message || '触发保存失败'
  } finally {
    syncing.value = false
  }
}

const viewWechatContext = async () => { await navigateTo('/chat') }
const goImport = async () => { await navigateTo('/import') }
const goDetection = async () => { await navigateTo('/detection-result') }

const openExportDialog = () => { exportDialogOpen.value = true }
const closeExportDialog = () => { exportDialogOpen.value = false }

onMounted(() => { void reload() })
</script>
```

说明：旧首页的"启动时自动跳转 /chat"逻辑移除（上下文中心即首页）；`GlobalExportDialog` 保留并由"导出"链接触发。

- [ ] **Step 5: 修改 app.vue（GuideDialog 文案隐藏解密 + 跳转上下文中心）**

(a) :26-35 的 GuideDialog 属性改为：

```vue
    <GuideDialog
      :open="noAccountGuideOpen"
      eyebrow="数据准备提示"
      title="还没有可查看的微信数据"
      description="当前没有已保存的微信上下文。您仍然可以留在此页面，但聊天、联系人、朋友圈和其他记录暂时无法加载。"
      :details="[
        '微信上下文会在微信登录后自动保存到本机',
        '也可以从上下文中心导入已有备份',
        '完成保存后再返回当前页面即可查看对应数据'
      ]"
      note="这个提示不会强制跳转，选择“暂时留在此页”可以继续浏览当前界面。"
      primary-label="去上下文中心"
      secondary-label="暂时留在此页"
      tone="info"
      @primary="goToAccountSetup"
      @secondary="dismissNoAccountGuide"
      @close="dismissNoAccountGuide"
    />
```

(b) `goToAccountSetup`（:151-154）改为：

```js
const goToAccountSetup = async () => {
  noAccountGuideOpen.value = false
  await navigateTo('/')
}
```

- [ ] **Step 6: 修改 SidebarRail.vue**

(a) 在 `      <!-- Chat -->` 之前插入导航入口：

```html
      <!-- Context Center -->
      <div
        class="sidebar-rail-action w-full h-[var(--sidebar-rail-step)] flex items-center justify-center cursor-pointer group"
        title="上下文中心"
        @click="goContextHome"
      >
        <div class="sidebar-rail-plate w-[var(--sidebar-rail-btn)] h-[var(--sidebar-rail-btn)] rounded-md flex items-center justify-center transition-colors bg-transparent">
          <div class="sidebar-rail-icon w-[var(--sidebar-rail-icon)] h-[var(--sidebar-rail-icon)]" :class="{ 'sidebar-rail-icon-active': isContextRoute }">
            <svg class="w-full h-full" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 10.5 12 4l9 6.5" />
              <path d="M5 9.5V20h14V9.5" />
              <path d="M9.5 20v-5.5h5V20" />
            </svg>
          </div>
        </div>
      </div>
```

(b) 脚本区：`const isSnsRoute = ...`（:781）之后加：

```js
const isContextRoute = computed(() => route.path === '/')
```

`const goChat = ...`（:790）之前加：

```js
const goContextHome = async () => { await navigateTo('/') }
```

(c) :390 文案改为：

```html
              微信上下文保存完成后即可切换账号，也可以到上下文中心导入已有备份。
```

(d) :461 文案改为：

```html
              <span class="text-[#8a8a8a] shrink-0">本地上下文库数量</span>
```

- [ ] **Step 7: 运行前端测试确认通过**

```powershell
cd frontend
npx vitest run tests/context-center.test.js
```
预期：4 个 PASS。

- [ ] **Step 8: 运行前端全量测试与构建**

```powershell
cd frontend
npx vitest run
npm run build
```
预期：既有测试全部 PASS（若旧测试依赖旧 index.vue 行为——如启动跳转 /chat——按新首页行为修正该测试）；构建成功。

- [ ] **Step 9: 隐藏解密字样检查**

用 Grep 在 `frontend/app.vue`、`frontend/components/SidebarRail.vue`、`frontend/pages/index.vue`、`frontend/nuxt.config.ts` 搜索 `解密|密钥`，预期 0 命中（detection-result.vue、decrypt-result.vue、import.vue、agreement.vue、SettingsDialog.vue 等深层功能页面的字样保留，不在本次范围）。

- [ ] **Step 10: Commit**

```powershell
git add frontend/composables/useApi.js frontend/pages/index.vue frontend/app.vue frontend/components/SidebarRail.vue frontend/tests/context-center.test.js
git commit -m "feat: 前端上下文中心首页"
```

---

### Task 7: 全量回归与收尾

**Files:**
- 无新增文件；修复回归问题时改动对应文件

**Interfaces:**
- Consumes: Task 1-6 的全部产出

- [ ] **Step 1: 后端全量测试**

```powershell
uv run --no-sync python -m pytest -q
```
（超时 600000；若既有测试因品牌/默认值变更失败，仅修与本次变更相关的断言，不做无关重构。）

预期：全部 PASS。已知需关注的点：chat_realtime_autosync 默认启用后，个别依赖"默认未启用"的既有测试需同步更新断言。

- [ ] **Step 2: 前端全量测试与构建（若 Task 6 已通过可跳过重复）**

```powershell
cd frontend
npx vitest run
npm run build
```
预期：全部 PASS、构建成功。

- [ ] **Step 3: 桌面端冒烟（手动）**

运行 `e:\Source\ContextBuddy\start_app.bat`（或 `cd desktop; npm run dev`），人工确认：
1. 应用窗口标题与托盘 tooltip 为 ContextBuddy；
2. 首页为上下文中心：微信卡片 + 4 个"规划中"卡片；
3. 若本机已登录微信：约 30s 内状态从"待自动保存"流转到"已是最新"，`%APPDATA%/ContextBuddy/contexts/wechat/manifest.json` 生成；若无微信则显示"等待微信登录"；
4. "立即保存"按钮可用；开关关闭后状态显示"已暂停"；
5. 侧边栏"聊天"等原功能入口可用，"查看微信上下文"能进入聊天分析页；
6. 原 WeChatDataAnalysis 应用的数据目录（`%APPDATA%/WeChatDataAnalysis*`）未被写入新文件。

- [ ] **Step 4: 收尾提交**

```powershell
git add -A
git commit -m "test: 全量回归修复与收尾"
```
（若无改动则跳过提交。）

---

## 任务依赖关系

- Task 1（复制+仓库）→ Task 2（品牌）→ Task 3（注册表）→ Task 4（自动保存，依赖 3）→ Task 5（API，依赖 3+4）→ Task 6（前端，依赖 5）→ Task 7（回归，依赖全部）
- Task 2 与 Task 3 无依赖，可并行；Task 3 与 Task 4 亦可由同一执行者连续完成（Task 4 的实现依赖 Task 3 的接口签名）

## 风险与注意

- `get_db_key_workflow` 在 Windows 上的采集耗时可达 120s（内存扫描+Hook 回退），仅在后台线程或 `asyncio.to_thread` 中调用，勿在事件循环内同步调用
- `_persist_db_keys` 内含角色校验（session+message 须验证通过才落 key store），保存失败时凭据不落库，服务下一轮重试——这是预期行为
- 旧首页"启动自动跳转 /chat"与 `?guide=1` 引导逻辑随替换移除；侧边栏"引导页"按钮现跳转到上下文中心首页（可接受的行为变化）
- 打包产物目录（desktop/dist、frontend/.output 等）已在 robocopy 排除，后续如需打包在 Task 7 之后按 desktop/package.json scripts 执行
