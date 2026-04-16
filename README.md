# Claude-Hermes Bridge

AI 思想碰撞平台 - Claude 与 Hermes 的深度对话系统

## 功能特性

- 🌐 Web UI 实时展示对话（SSE 推送）
- 🔄 双向 AI 对话（Claude × Hermes）
- 💾 历史讨论保存与加载
- 📊 Token 预算控制
- 🎨 动态 AI 名称配置

## 更新日志

### 2026-04-15 v1.2

**按钮显示逻辑修复**：
1. 修复 AI 对话启动后出现两个"结束讨论"按钮的问题
2. 修复页面刷新后显示两个"结束讨论"按钮的问题
3. 修复无活跃讨论时点击"结束讨论"按钮报"No active discussion"错误

### 2026-04-15 v1.1

**历史讨论功能修复**：
1. 修复 `GET /discussions` API 路由问题 → 改为 `POST /api/discussion/list`
2. 修复 `handle_list_discussions` 返回格式 → `{discussions: [...]}` 包装
3. 修复中文文件名 URL 编码问题 → 添加 `unquote()` 解码
4. 修复历史讨论加载时消息区域未清空问题（`loadDiscussion` 添加 `clearMessages()` 调用）
5. 修复 `hideAIThinking()` 函数 null check 问题

**项目初始化**：
- 初始化 git 仓库
- 添加 .env.example 配置模板

## AI 名称配置

界面上的 AI 名称可通过 `.env` 文件配置：

```bash
AI_NAME_CLAUDE=Claude        # 显示的 Claude AI 名称
AI_NAME_HERMES=MiniMax-M2.7  # 显示的 Hermes AI 名称
```

修改后刷新页面即可生效。

## Token 预算配置

在 `.env` 中配置消息保留策略：

```
LAYER_1_FULL=true            # Layer 1 用户话题全量保留
USER_MSG_FULL_COUNT=1         # 用户发言保留最近几条
LAYER_2to4_FULL=true         # Layer 2-4 全量保留
LAYER_5to10_TRUNCATE=0.5     # Layer 5-10 截断50%
LAYER_OVER_10_SUMMARY=true   # >Layer 10 只留摘要
MAX_CHARS=10000              # 强制截断字符数上限
```

## 启动服务

```bash
# 方式1：直接运行
python3 bridge_core.py

# 方式2：使用启动脚本
bash claude_bridge.sh
```

服务启动后访问 http://localhost:PORT（参见 .env 中的 PORT 配置）

## 项目结构

```
claude-hermes-bridge/
├── index.html           # Web UI 前端
├── bridge_core.py       # 核心桥接逻辑 + HTTP server
├── claude_handler.py    # Claude API 处理模块
├── hermes_handler.py    # Hermes API 处理模块
├── discussions/         # 历史讨论存储目录
├── .env                 # 配置文件
├── .env.example         # 配置模板
└── claude_bridge.sh     # 启动脚本
```

## Token 消耗说明

- **Layer 1（用户原始输入）**：完整保留
- **Layer 2-4（AI 对话层）**：完整保留
- **Layer 5-10（更深层推理）**：按配置比例截断
- **Layer >10（极深层推理）**：仅保留摘要
- **MAX_CHARS**：硬截断上限（默认 10000）

## 相关文档

- [AI_INTEGRATION.md](./AI_INTEGRATION.md) — AI 集成就餐详情

AI 思想碰撞平台 - Claude 与 Hermes 的深度对话系统

## 功能特性

- 🌐 Web UI 实时展示对话（SSE 推送）
- 🔄 双向 AI 对话（Claude × Hermes）
- 💾 历史讨论保存与加载
- 📊 Token 预算控制
- 🎨 动态 AI 名称配置

## 更新日志

### 2026-04-15 修复

**历史讨论功能修复**：
1. 修复 `GET /discussions` API 路由问题 → 改为 `POST /api/discussion/list`
2. 修复 `handle_list_discussions` 返回格式 → `{discussions: [...]}` 包装
3. 修复中文文件名 URL 编码问题 → 添加 `unquote()` 解码
4. 修复历史讨论加载时消息区域未清空问题
5. 修复 `hideAIThinking()` 函数 null check 问题

## AI 名称配置

界面上的 AI 名称可通过 `.env` 文件配置：

```bash
AI_NAME_CLAUDE=Claude        # 显示的 Claude AI 名称
AI_NAME_HERMES=MiniMax-M2.7  # 显示的 Hermes AI 名称
```

修改后刷新页面即可生效。

## Token 预算配置

在 `.env` 中配置消息保留策略：

```
LAYER_1_FULL=true            # Layer 1 用户话题全量保留
USER_MSG_FULL_COUNT=1         # 用户发言保留最近几条
LAYER_2to4_FULL=true         # Layer 2-4 全量保留
LAYER_5to10_TRUNCATE=0.5     # Layer 5-10 截断50%
LAYER_OVER_10_SUMMARY=true   # >Layer 10 只留摘要
MAX_CHARS=10000              # 强制截断字符数上限
```

## 启动服务

```bash
./start.sh
```

访问 http://localhost:8765

## 项目结构

```
claude-hermes-bridge/
├── server.py           # HTTP 服务器
├── poll_loop.py        # 消息轮询处理
├── bridge.jsonl        # 统一消息文件
├── state.json          # 状态文件
├── index.html          # Web UI
├── claude_handler.py   # Claude 处理函数
├── hermes_handler.py   # Hermes 处理函数
├── token_budget.py     # Token 预算控制
└── output/             # 导出文件夹
```

## 导出功能

- 📄 导出对话：导出全部对话内容到 `output/` 文件夹
- 📝 Claude/Hermes 总结：调用对应 AI 对话内容进行总结并导出

---
