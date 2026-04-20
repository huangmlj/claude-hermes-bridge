# Claude-Hermes Bridge

AI 思想碰撞平台 - Claude 与 Hermes 的深度对话系统

## 功能特性

- 🌐 Web UI 实时展示对话（SSE 推送）
- 🔄 双向 AI 对话（Claude × Hermes）
- 💾 历史讨论保存与加载
- 📊 Token 预算控制
- 🎨 动态 AI 名称配置

## 更新日志

### 2026-04-20 - 导出功能优化

- 移除导出时的浏览器下载，仅保留后端保存到 `output/` 目录

### 2026-04-19 v2.3 - 安全与质量修复

**前端修复**（P0/P1）：
- 修复 Message 类型缺少 id 字段问题，导致代码复制功能失效
  - `types.ts` 添加 id 字段
  - `utils.ts` 添加 generateMessageId()
  - `App.tsx` 修复所有消息创建处添加 id
- 修复 handleEnd 不重置状态问题，结束讨论后 UI 混乱
  - 重置 currentTopic, discussionFilename, viewingHistory
  - 清空消息和 lastEventId
- 前端 API URL 改为环境变量配置，便于部署到非 localhost 环境
  - 创建 `web/.env.local.example`
  - `api.ts` 添加 getApiBase()
  - 更新所有 service 文件和 vite.config.ts
- createSSE 添加 JSON.parse try-catch 保护，避免非 JSON 数据导致崩溃
- MessageInput 添加实际 maxLength 限制（默认 2000），超过 90% 显示红色警告

**后端修复**（P0/P1/P2）：
- .env 从 Git 历史中完全移除，防止 API Key 泄露
- 添加 API 认证中间件（可选），通过 BRIDGE_API_KEY 环境变量启用
  - 保护除静态文件和健康检查外的所有 API 端点
  - 支持 Authorization: Bearer YOUR_API_KEY 认证
- 移除 pkill，改用精确 PID 管理进程，避免误杀风险
  - `poll.py` stop_poll 使用 PID 文件
  - `discussion.py` end_discussion 调用 stop_poll
- init_files() 改为原子操作，避免崩溃时 bridge.jsonl 被清空
  - 先写入临时文件，再使用 os.replace() 原子替换
  - 添加异常清理逻辑
- requirements.txt 补全缺失依赖：httpx, cryptography, python-dotenv

**环境变量配置更新**（.env.example）：
- 添加 BRIDGE_API_KEY 配置说明（可选 API 认证）

---

### 2026-04-18 v2.2 - FastAPI 重构（可选）

**架构升级**（server_fastapi.py）：
- 路由层全面拥抱 FastAPI 装饰器，告别意大利面条式 `if self.path == ...`
- SSE 改为 `sse-starlette` 异步生成器，彻底解决长连接线程瓶颈
- Pydantic Schemas 替代手动 JSON 校验，输入验证更可靠
- CORS/生命周期/限速全部中间件化

**SSE 重写**：
- 旧版：每个 SSE 连接一个线程 + `threading.Event` 等待
- 新版：协程 + `asyncio.Event` 等待 + `watchdog` 文件变化回调唤醒，无线程阻塞
- `EventSourceResponse` + `asyncio.to_thread` 包装所有同步文件 I/O

**新增依赖**：`fastapi`, `uvicorn[standard]`, `pydantic>=2.0`, `sse-starlette`

**启动方式**：
```bash
# FastAPI 版本（推荐）
python3 -m uvicorn server_fastapi:app --host 0.0.0.0 --port 8765

# 或使用启动脚本（已更新）
bash start.sh
```

### 2026-04-18 v2.1 - 性能优化

**WAL 增量读取优化**（services/bridge.py）：
- 引入 Byte Offset 缓存，`get_true_line_count()` 只需读取增量部分，十万行对话瞬间完成
- 文件增长时从缓存指针位置增量累加，非增长/首次时全量读取
- 移除写后 O(N) 验证扫描，追加即原子

**锁重试逻辑 DRY 化**（services/bridge.py）：
- 合并 BlockingIOError 和 IOError/OSError 为统一异常处理
- 用 `isinstance()` 判断抖动因子，代码更简洁

**SSE 连接鲁棒性增强**（server.py）：
- 写入循环内单独 try...except 捕获网络断开，干净 break 退出
- 心跳/消息推送异常不影响主循环，ConnectionAbortedError 单独处理
- 外层统一捕获意外异常并记录日志

### 2026-04-18 v2.0 - 重构

**后端分层架构**：
- `server.py` 重写为薄 HTTP 路由层（1415行 → 585行）
- `services/bridge.py` - WAL + Checkpoint + 锁（原 bridge_core.py）
- `services/poll.py` - AI 轮询（合并自 poll_loop.py + handlers）
- `services/discussion.py` - 讨论生命周期管理
- `services/export.py` - 导出/总结服务
- `services/handlers.py` - SSE 连接管理

**前端 Service 层**：
- `web/src/services/discussionService.ts` - 讨论 CRUD
- `web/src/services/messageService.ts` - 消息发送
- `web/src/services/exportService.ts` - 导出/总结
- `web/src/hooks/useDiscussion.ts` - 讨论状态管理
- `App.tsx` 重构为组合层

**已删除**：`bridge_core.py`, `poll_loop.py`, `hermes_handler.py`, `claude_handler.py`

**API 端点**：所有按钮功能通过 services 层调用，逻辑清晰完整。

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
├── server_fastapi.py      # FastAPI HTTP 服务器（推荐）
├── server.py              # 旧版 http.server（已废弃）
├── services/              # 业务逻辑层
│   ├── bridge.py          # WAL + Checkpoint + 锁
│   ├── poll.py            # AI 轮询进程管理
│   ├── discussion.py      # 讨论生命周期
│   ├── export.py          # 导出/总结
│   └── handlers.py        # SSE 连接管理（仅旧版server.py使用）
├── validators.py          # 输入验证
├── token_budget.py        # Token 预算控制
├── bridge.jsonl           # WAL 日志
├── state.json             # UI 元数据
├── discussions/            # 历史讨论存档
└── web/                  # React 前端
    └── src/
        ├── services/         # 前端服务层
        ├── hooks/            # 状态 hooks
        └── components/       # UI 组件
```
```

## 导出功能

- 📄 导出对话：导出全部对话内容到 `output/` 文件夹
- 📝 Claude/Hermes 总结：调用对应 AI 对话内容进行总结并导出

---
