# ContextBuddy 应用设计（复制自 WeChatDataAnalysis 工程）

- 日期：2026-10-14
- 状态：已获用户逐项批准
- 原工程：`e:\Source\WeChatDataAnalysis`（保持不动，不做任何修改）

## 1. 背景与目标

复制现有微信数据解密分析工程，新建独立应用 **ContextBuddy**：一个本地上下文收集与保存应用。各类上下文数据保存到本地文件夹，为将来的多端同步、上下文管理、分享给其他 WorkBuddy 或第三方应用打基础。

数据源规划：

| # | 数据源 | 本次范围 |
|---|--------|----------|
| 1 | 浏览器浏览记录（豆包、Qwen 等，浏览器插件方式，随应用安装、可更新） | 接口 stub |
| 2 | 个微数据（聊天数据等） | **完整实现**（自动保存） |
| 3 | 电脑操作记录 | 接口 stub |
| 4 | 手机端手动上传（配合手机 App：NextCloud） | 接口 stub |
| 5 | 自动写浏览器插件抓取定制浏览器数据 | 接口 stub |

## 2. 已确认决策

- 新工程位置 `e:\Source\ContextBuddy`，**全新 git 仓库**；原工程不动
- 界面形态：**上下文中心首页 + 保留原有功能**（聊天分析界面作为微信上下文的查看入口）
- 内部 Python 包名 `wechat_decrypt_tool` **保留不改**；仅用户可见品牌改为 ContextBuddy
- 微信自动保存：**总开关（默认开启）+ 后台自动检测**；编排服务为后端常驻线程
- **隐藏解密**：UI 与 context API 不出现"密钥/解密"字样，对用户只呈现"微信上下文自动保存"

## 3. 工程复制与品牌改造

### 复制
- `robocopy e:\Source\WeChatDataAnalysis e:\Source\ContextBuddy /E`，排除：`.git`、`node_modules`、`.venv`、`.output`、`.nuxt`、`dist`、`output`、`__pycache__`、`.pytest_cache`、`.ruff_cache` 等产物目录
- 复制后在新工程 `git init`，随首个提交一并提交本设计文档

### 品牌改造（用户可见处）
| 位置 | 改为 |
|------|------|
| `desktop/package.json` | name=`context-buddy-desktop`，productName=`ContextBuddy`，appId 同步改 |
| `desktop/src/main.cjs` 托盘标题 | ContextBuddy |
| `src/wechat_decrypt_tool/api.py` FastAPI title | ContextBuddy |
| `frontend/nuxt.config.ts` 页面标题 | ContextBuddy |
| `start_app.bat` 提示文案 | ContextBuddy |
| 前端 UI 内应用名文案 | ContextBuddy（不重新制作 logo 图片，仅改文字文案） |

### 数据目录隔离
- ContextBuddy 使用独立数据目录（`%APPDATA%/ContextBuddy`），由桌面端启动后端时通过 `WECHAT_TOOL_DATA_DIR` 环境变量传入；dev 模式下 cwd 不同亦不冲突
- 密钥存储、output 数据均落在新工程自己的数据目录，与原工程互不干扰

## 4. 上下文存储（`context_registry.py`）

- 根目录 `<data_dir>/contexts/`，每个数据源一个子目录
- 每源目录含 `manifest.json`：`{source_id, last_saved_at, summary, data_ref}`；微信源 `data_ref` 指向现有 `output/databases/`（解密库位置不搬动）
- 各源开关的唯一权威存储为 `contexts/settings.json`（manifest 不存 enabled，避免双写不一致）
- **源适配器接口**（统一接入方式，为浏览器插件等未来源预留）：

```python
class ContextSource(Protocol):
    source_id: str
    display_name: str
    def status(self) -> dict: ...   # {enabled, state, last_saved_at, summary, planned}
    def start(self) -> None: ...
    def stop(self) -> None: ...
```

- 注册 5 个源：`wechat`（真实实现）、`browser_history` / `computer_activity` / `mobile_upload` / `custom_capture`（stub：status 返回 planned=true，目录与 API 位置就位，无采集逻辑）
- `mobile_upload` stub 预留 NextCloud server 配置字段；`browser_history` stub 预留插件版本/安装/更新接口占位

## 5. 微信自动保存服务（`wechat_autosave.py`）

- 后端常驻线程（模式复用 `CHAT_REALTIME_AUTOSYNC`），随 FastAPI 启动，默认开启
- 轮询循环（约 30s 一轮）：
  1. psutil 扫描 `Weixin.exe / WeChat.exe`（复用 `wechat_detection` 现有逻辑）
  2. 检测到登录账号 → 调现有密钥采集（进程内存读取，复用原工程实现，不新写）→ 写入 key store
  3. 密钥就绪 → 调 `decrypt_wechat_databases()` 落盘 `output/databases/<wxid>`
  4. 完成后启动 `CHAT_REALTIME_AUTOSYNC` 实时同步；后续轮次仅增量同步
  5. 更新 `contexts/wechat/manifest.json`（账号数、最后保存时间）
- 状态机：`idle → wechat_detected → saving → up_to_date / waiting_wechat / error`；异常记日志回到 idle，不崩线程
- 停止条件：总开关关闭时线程暂停轮询（保留线程可恢复）

## 6. API（`routers/context.py`，`local_only` 依赖）

| 端点 | 说明 |
|------|------|
| `GET /api/context/sources` | 源列表：`source_id, name, enabled, state, last_saved_at, summary, planned` |
| `GET /api/context/settings` | 各源开关；本次仅 `wechat.enabled` 实际生效 |
| `PUT /api/context/settings` | 保存开关 |
| `POST /api/context/wechat/sync-now` | 手动触发一轮"立即保存" |

- 响应统一 snake_case；错误信息不出现密钥/解密字样

## 7. 前端

- 新增**上下文中心**首页（`pages/index.vue`，替换现有首页角色）：
  - 微信卡片：自动保存总开关、已保存账号数、最后保存时间、实时同步状态、"立即保存"按钮、"查看微信上下文"入口 → 原聊天分析界面
  - 其余 4 源卡片：名称 + 说明 + "规划中"标记（浏览器记录卡片注明"将以浏览器插件方式接入"）
- `SidebarRail` 置顶新增"上下文"入口；原有聊天/联系人/朋友圈等入口保留
- 品牌与隐藏解密：首页空状态文案重写（不再引导"完成解密"）；导航/首页不出现"解密/密钥"字样（保留入口的改名收纳，具体清单在实现计划阶段逐一定位）
- `useApi.js` 新增 4 个封装：`getContextSources` / `getContextSettings` / `updateContextSettings` / `triggerWechatSync`

## 8. 测试

- 后端 pytest（新工程内）：
  - `context_registry`：stub 源状态、manifest 读写、settings 持久化
  - `wechat_autosave`：monkeypatch 进程扫描/密钥采集/解密函数，断言状态机流转与 manifest 更新
  - context 路由：httpx ASGITransport 测试
- 前端 vitest：上下文首页组件测试（卡片渲染、开关调用 API、stub 标记）
- 全量回归：新工程全部 pytest + `npm test` + `npm run build`；桌面端 `npm run dev` 冒烟

## 9. 实施顺序

1. 复制工程（排除产物）→ 依赖重建（`uv sync`、frontend/desktop `npm install`）→ `git init` 首个提交（含本 spec）
2. 品牌改造提交
3. context 存储 + 源注册 + 4 个 stub 提交
4. 微信自动保存服务提交
5. context API 提交
6. 前端上下文中心 + 品牌落地提交
7. 全量测试与收尾提交

## 10. 风险与计划阶段核实项

- 密钥采集的具体入口函数（原工程进程内存读取实现）在写实现计划时核实对接
- `desktop/src/main.cjs` 启动后端时的环境变量传递方式需核实，确保数据目录隔离落地
- 前端导航中"解密"字样清理清单在计划阶段逐一定位
