# Claude-Hermes Bridge

AI 思想碰撞平台 - Claude 与 Hermes 的深度对话系统

## 概述

Claude-Hermes Bridge 是一个双向 AI 对话系统，允许两个 AI（Claude 和 Hermes）在用户引导下进行深度讨论。通过 Web UI 实时展示对话过程，支持消息分层、Token 预算控制、历史讨论管理等功能。

### 核心特性

- **双向 AI 对话**：Claude × Hermes 交替讨论，相互回应
- **实时 SSE 推送**：Web UI 通过 Server-Sent Events 实时接收消息
- **消息分层机制**：Layer 1-4 全量保留，Layer 5-10 按策略截断，更深层仅保留摘要
- **Token 预算控制**：可配置的 Token 消耗策略，避免单次对话过长
- **历史讨论管理**：自动保存讨论到文件，支持加载历史继续
- **导出与总结**：导出对话为 Markdown，调用 AI 生成讨论总结

## 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web UI (React)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐│
│  │  ChatInterface │  │  Sidebar   │  │  Header / StatusBar   ││
│  └─────────────┘  └─────────────┘  └─────────────────────────┘│
│                            │                                     │
│         ┌──────────────────┼──────────────────┐                 │
│         ▼                  ▼                  ▼                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ useSSE       │  │ useMessages │  │ useHistory  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│         │                  │                                    │
│         ▼                  ▼                                    │
│  ┌─────────────────────────────────────────┐                    │
│  │          services/ (API Layer)           │                    │
│  │  discussionService | messageService | exportService         │
│  └─────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
                              │ HTTP/REST + SSE
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Server (server_fastapi.py)           │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Routes: /api/discussion/* | /api/message | /api/export    │ │
│  │  SSE: /api/events (watchdog 驱动的发布-订阅模式)            │ │
│  │  Auth: Bearer Token Middleware (可选)                       │ │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ services/    │      │ services/    │      │ services/   │
│ bridge.py    │      │ discussion.py│      │ poll.py     │
│ - WAL        │      │ - 生命周期   │      │ - AI 轮询   │
│ - 锁机制     │      │ - 历史存档   │      │ - Claude   │
│ - Checkpoint │      │              │      │ - Hermes   │
└─────────────┘      └─────────────┘      └─────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ bridge.jsonl│      │ discussions/│      │ subprocess  │
│ (WAL 日志)  │      │ (JSON 存档) │      │ (CLI 调用)  │
└─────────────┘      └─────────────┘      └─────────────┘
```

## 项目结构

```
claude-hermes-bridge/
├── server_fastapi.py          # FastAPI HTTP 服务器（主入口）
├── requirements.txt           # Python 依赖
│
├── services/                  # 业务逻辑层
│   ├── __init__.py
│   ├── bridge.py             # WAL 日志 + 锁 + Checkpoint
│   ├── discussion.py         # 讨论生命周期管理
│   ├── poll.py               # AI 轮询进程管理
│   └── export.py             # 导出/总结服务
│
├── token_budget.py           # Token 预算控制
├── validators.py             # 输入验证
│
├── discussions/              # 历史讨论存档目录
├── output/                   # 导出文件目录
│
├── web/                      # React 前端
│   ├── src/
│   │   ├── App.tsx           # 根组件（组合层）
│   │   ├── main.tsx          # 入口点
│   │   ├── index.css         # 全局样式
│   │   │
│   │   ├── components/       # UI 组件
│   │   │   ├── chat/         # 聊天相关
│   │   │   │   ├── ChatInterface.tsx    # 聊天主界面
│   │   │   │   ├── MessageInput.tsx      # 消息输入框
│   │   │   │   ├── MessageList.tsx       # 消息列表（虚拟滚动）
│   │   │   │   ├── MessageBubble.tsx     # 消息气泡
│   │   │   │   └── AThinkingIndicator.tsx # AI 思考指示器
│   │   │   │
│   │   │   ├── header/       # 头部
│   │   │   │   ├── Header.tsx            # 标题栏
│   │   │   │   └── ServiceStatus.tsx    # 服务状态
│   │   │   │
│   │   │   ├── sidebar/       # 侧边栏
│   │   │   │   ├── Sidebar.tsx          # 侧边栏容器
│   │   │   │   ├── HistoryPanel.tsx     # 历史讨论面板
│   │   │   │   └── StatusBar.tsx        # 状态栏
│   │   │   │
│   │   │   ├── modals/       # 对话框
│   │   │   │   ├── StartDiscussionDialog.tsx  # 开始讨论
│   │   │   │   └── ConfirmDeleteDialog.tsx    # 删除确认
│   │   │   │
│   │   │   └── ui/           # 基础 UI 组件
│   │   │       ├── button.tsx
│   │   │       ├── input.tsx
│   │   │       ├── textarea.tsx
│   │   │       ├── dialog.tsx
│   │   │       ├── dropdown-menu.tsx
│   │   │       ├── toast.tsx
│   │   │       └── ...
│   │   │
│   │   ├── hooks/            # React Hooks
│   │   │   ├── useSSE.ts     # SSE 连接管理
│   │   │   ├── useMessages.ts # 消息状态管理
│   │   │   ├── useHistory.ts  # 历史讨论管理
│   │   │   ├── useDiscussion.ts # 讨论状态
│   │   │   └── useStatus.ts   # 服务状态
│   │   │
│   │   ├── services/         # API 服务层
│   │   │   ├── discussionService.ts  # 讨论 CRUD
│   │   │   ├── messageService.ts     # 消息发送
│   │   │   └── exportService.ts       # 导出/总结
│   │   │
│   │   └── lib/              # 工具库
│   │       ├── api.ts        # API 基础配置 + SSE
│   │       ├── types.ts      # TypeScript 类型定义
│   │       └── utils.ts      # 工具函数
│   │
│   ├── package.json
│   ├── vite.config.ts
│   └── dist/                 # 构建产物
│
├── .env                      # 环境配置（实际值）
├── .env.example              # 环境配置示例
└── start.sh                  # 启动脚本
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- npm

### 安装依赖

```bash
# Python 依赖
pip install -r requirements.txt

# 前端依赖
cd web && npm install && cd ..
```

### 配置

复制 `.env.example` 为 `.env` 并根据需要修改：

```bash
cp .env.example .env
```

主要配置项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `BRIDGE_API_KEY` | API 认证密钥（可选） | 无 |
| `AI_NAME_CLAUDE` | 界面显示的 Claude 名称 | Claude |
| `AI_NAME_HERMES` | 界面显示的 Hermes 名称 | MiniMax-M2.7 |
| `CLAUDE_MODEL` | Claude 模型 | claude-opus-4-6 |
| `LAYER_1_FULL` | Layer 1 全量保留 | true |
| `USER_MSG_FULL_COUNT` | 额外保留用户消息数 | 3 |
| `LAYER_2to4_FULL` | Layer 2-4 全量保留 | true |
| `LAYER_5to10_TRUNCATE` | Layer 5-10 截断比例 | 0.3 |
| `LAYER_OVER_10_SUMMARY` | >Layer 10 只留摘要 | true |
| `MAX_CHARS` | 最大字符数 | 25000 |
| `POLL_INTERVAL` | AI 轮询间隔(秒) | 2 |
| `SSE_TIMEOUT` | SSE 超时时间(秒) | 300 |

### 启动服务

```bash
bash start.sh
```

启动后访问：
- **React 前端**：http://localhost:5173
- **API 状态**：http://localhost:8765/api/status

## 功能说明

### 创建讨论

1. 在输入框输入话题，按回车或点击发送
2. 系统自动创建讨论，启动两个 AI 的对话
3. 消息通过 SSE 实时推送到界面

### 消息分层机制

系统根据消息的 `layer` 字段进行分层处理：

| Layer | 来源 | 保留策略 |
|-------|------|----------|
| 1 | 用户原始话题 | 全量保留 |
| 2-4 | AI 讨论层 | 全量保留（可配置） |
| 5-10 | 深层推理 | 按 `LAYER_5to10_TRUNCATE` 截断 |
| >10 | 极深层推理 | 仅保留摘要（可配置） |

### 历史讨论

- 侧边栏切换到"历史"视图
- 显示所有存档的讨论列表
- 点击讨论可加载继续
- 支持删除历史讨论

### 导出与总结

- **导出**：将当前讨论保存为 Markdown 文件到 `output/` 目录
- **Claude 总结**：调用 Claude 生成讨论摘要
- **Hermes 总结**：调用 Hermes 生成讨论摘要

### Token 预算控制

系统通过 `token_budget.py` 控制 Token 消耗：

1. **字符数限制**：`MAX_CHARS` 强制截断
2. **分层截断**：按层级应用不同保留策略
3. **摘要生成**：深层消息生成摘要替代原文

## API 参考

### 讨论管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/discussion/start` | 创建新讨论 |
| POST | `/api/discussion/start-ai` | 启动 AI 轮询 |
| POST | `/api/discussion/end` | 结束讨论 |
| GET | `/api/discussion/list` | 获取讨论列表 |
| GET | `/discussions/{filename}` | 加载讨论文件 |
| POST | `/api/discussion/delete` | 删除讨论 |

### 消息

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/message` | 发送消息 |
| GET | `/messages` | 获取当前讨论消息 |

### 导出

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/export` | 导出讨论到 Markdown |
| POST | `/api/summary` | 生成 AI 总结 |

### 服务控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/services` | 获取服务状态 |
| POST | `/api/services/start` | 启动所有服务 |
| POST | `/api/services/stop` | 停止所有服务 |

### SSE 事件

```
GET /api/events?lastEventId={n}
```

SSE 事件格式：

```json
{
  "id": "消息ID",
  "layer": 2,
  "author": "claude",
  "content": "消息内容",
  "timestamp": "2026-04-20T12:00:00.000Z"
}
```

## 数据存储

### bridge.jsonl (WAL 日志)

追加写入的日志文件，记录所有消息：

```json
{"author": "user", "content": "话题", "timestamp": "...", "layer": 1}
{"author": "claude", "content": "...", "timestamp": "...", "layer": 2}
{"author": "hermes", "content": "...", "timestamp": "...", "layer": 2}
```

### state.json (状态文件)

UI 元数据：

```json
{
  "current_topic": "当前话题",
  "discussion_active": true,
  "poll_running": true,
  "current_layer": 3
}
```

### discussions/ (讨论存档)

JSON 格式的讨论文件，包含消息列表和元数据。

### output/ (导出目录)

导出的 Markdown 文件和 AI 总结。

## 安全机制

### 输入验证

- `validators.py` 提供全面的输入验证
- Pydantic 模型验证 API 请求
- 路径遍历防护（`load_discussion` 等）

### API 认证（可选）

设置 `BRIDGE_API_KEY` 环境变量后，所有 API 请求需要携带：

```
Authorization: Bearer YOUR_API_KEY
```

### 进程锁

使用 `fcntl.flock` 防止多进程并发写入 WAL 日志。

### 原子写入

状态文件使用临时文件 + `os.replace()` 实现原子写入。

## 故障排除

### 服务无法启动

1. 检查端口占用：`lsof -i :8765`
2. 查看日志：`tail -f server.log`

### SSE 连接失败

1. 确认后端运行：`curl http://localhost:8765/api/status`
2. 检查前端 API 配置：`.env.local` 中的 `VITE_BACKEND_URL`

### AI 无响应

1. 检查 AI CLI 是否可用：`claude --version` / `hermes --version`
2. 查看轮询日志：`tail -f poll_loop.log`

### 消息丢失

1. 检查 WAL 完整性：`python3 -c "from services.bridge import get_true_line_count; print(get_true_line_count())"`
2. 验证 checkpoint：`cat .checkpoint`

## 更新日志

### 2026-04-20

- 导出功能优化：移除浏览器下载，仅保留后端保存

### 2026-04-20

**SSE 重构**：
- 引入 watchdog 文件变化监控 + asyncio.Event 发布-订阅模式
- 消除 SSE "惊群" 问题（thundering herd）
- 连接超时 10 秒自动断开 + lastEventId 断点续传

**前端优化**：
- MessageList 虚拟滚动（TanStack Virtual）处理大量消息
- MessageBubble Markdown 渲染 + 代码块复制按钮
- MessageInput 自动高度调整 + maxLength 限制
- 修复乐观更新去重逻辑

### 2026-04-19 v2.3 - 安全与质量修复

**前端修复**：
- 修复 Message 类型缺少 id 字段问题
- 修复 handleEnd 不重置状态问题
- 前端 API URL 改为环境变量配置

**后端修复**：
- .env 从 Git 历史完全移除
- 添加可选 API 认证中间件
- 移除 pkill，改用精确 PID 管理
- init_files() 原子操作

### 2026-04-18 v2.2 - FastAPI 重构

- 路由层全面拥抱 FastAPI 装饰器
- SSE 改为 sse-starlette 异步生成器
- Pydantic Schemas 替代手动 JSON 校验

### 2026-04-18 v2.1 - 性能优化

- WAL 增量读取（Byte Offset 缓存）
- 移除写后 O(N) 验证扫描
- 锁重试逻辑 DRY 化

### 2026-04-18 v2.0 - 重构

- 后端分层：bridge.py, poll.py, discussion.py, export.py
- 前端 Service 层拆分
- 删除旧文件：bridge_core.py, poll_loop.py 等

## 许可证

MIT
