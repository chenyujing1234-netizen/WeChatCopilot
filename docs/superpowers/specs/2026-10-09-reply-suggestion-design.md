# 消息回复推荐功能设计

日期：2026-10-09
状态：已批准（方案 A：轻量独立路由 + 复用现有基础设施）

## 需求

在聊天界面为选中的消息生成回复建议。生成依据：聊天上下文 + 用户指定的工作空间目录（递归读取全部文本文件）综合分析。

已确认的决策：
- 模型：复用项目"AI 设置"中已配置的模型与 API Key（`src/wechat_decrypt_tool/ai/` 包）
- 入口：聊天消息行 hover 显示"推荐回复"按钮
- 工作空间：设置页配置全局固定目录（含启用开关），聊天页可临时覆盖
- 形式：弹窗展示 1 条建议，可一键复制、可重新生成

## 后端设计

### 新增文件

1. `src/wechat_decrypt_tool/routers/reply_suggestion.py` — 路由
2. `src/wechat_decrypt_tool/workspace_reader.py` — 工作空间文件读取工具

### API

- `POST /api/reply-suggestions/generate`
  - 入参：`account`（账号目录名）、`conversation`（会话 username）、`localId` + `messageId`（目标消息定位）、`extraInstruction`（可选附加指示）、`workspaceDir`（可选，覆盖全局设置）
  - 流程：
    1. 校验 AI 设置；未配置 API Key → 400，返回可识别错误码供前端引导
    2. 取聊天上下文：目标消息前 30 条（含自身），复用现有聊天消息查询服务（与聊天页 `getChatMessagesAround` 同源的服务层，实现时定位具体函数）
    3. 读取工作空间：`workspace_reader.read_workspace(dir)` 递归收集文本文件
    4. 组装提示词（系统提示 + 聊天记录转写 + 工作空间摘要 + 待回复消息 + 用户附加指示）
    5. 调用现有 OpenAI 兼容客户端（非流式，复用 `ai/` 包的请求通道与所选模型配置）
    6. 返回：`{ suggestion, model, filesConsidered, contextMessages, workspaceUsed, elapsedMs }`
- `GET /api/reply-suggestions/settings` / `PUT`：工作空间全局设置（`{ workspaceDir, enabled }`），复用项目现有设置持久化模式（与其他设置 JSON 一致的存储位置）

### workspace_reader 规则

- 递归遍历目录；仅读取文本扩展名：txt md json csv py js ts vue html xml log yaml yml toml ini cfg
- 上限：单文件 100KB、总量 500KB、最多 100 个文件（超出截断并在返回中注明 `truncated`）
- 解码尝试 utf-8 → gbk，失败跳过该文件；跳过二进制/超大文件；读取失败的单文件不阻断整体
- 输出：`{ files: [{path, size}], digest: "按文件路径分段的文本拼接", truncated }`

## 前端设计

- 聊天消息列表组件（解密聊天查看页）：消息行 hover 出现"推荐回复"按钮（仅对可回复的普通消息显示）
- 新组件 `frontend/components/ReplySuggestionDialog.vue`：
  - 加载态 → 建议正文展示 + 复制按钮 + 重新生成按钮
  - 折叠面板：参考的文件列表（`filesConsidered`）
  - 错误态：无 Key（引导到设置页）/ 目录不存在（提示）/ LLM 超时或失败（可重试）
- 设置页新增"回复推荐工作空间"卡片：目录输入（Electron 目录选择器，回退手动输入）+ 启用开关
- `frontend/composables/useApi.js` 增加对应 API 封装

## 错误与边界

- LLM 请求超时 60s；失败返回可重试错误
- 工作空间禁用或无可用文本文件：仍生成，`workspaceUsed=false` 并在弹窗注明"未参考工作空间"
- 上下文超长按消息条数（30）截断；提示词总量超模型窗口由现有客户端处理
- 账号未解密 / 消息定位失败：返回 404 语义错误

## 测试计划

- `workspace_reader`：类型过滤、递归、三重上限、编码回退、坏文件跳过（单测，临时目录）
- 生成接口：合成解密数据库验证消息选取（前 30 条、定位目标消息）；无 Key 错误路径；mock LLM 客户端验证提示词组装与返回结构
- 前端：组件编译校验 + 弹窗错误态展示逻辑

## 不做的事（YAGNI）

- 不做多条候选、不接 Agent 线程体系、不做流式输出、不做工作空间索引/向量检索（直接拼接文本）、不做回复直达微信发送
