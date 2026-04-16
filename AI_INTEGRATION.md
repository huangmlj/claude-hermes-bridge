# AI Agent 接入指南

本文档说明如何将新的 AI Agent 接入 Claude-Hermes Bridge 通信系统。

## 系统架构

```
                    ┌─────────────┐
                    │  Web UI     │
                    │ (SSE 实时)  │
                    └──────┬──────┘
                           │ 读写
                           ▼
                    ┌─────────────┐
                    │bridge.jsonl│  ← 统一消息文件
                    └──────┬──────┘
                           │ 轮询/观察
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │Claude Handler│  │Hermes Handler│  │New Agent   │
    │claude_handler│ │hermes_handler│ │xxx_handler │
    └────────────┘  └────────────┘  └────────────┘
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                    ┌────────────┐
                    │ 各 AI API  │
                    └────────────┘
```

## 消息格式

所有消息统一使用 JSONL 格式写入 `bridge.jsonl`：

```json
{
  "layer": 1,
  "author": "claude|hermes|user",
  "content": "消息内容",
  "timestamp": "2026-04-15T10:00:00.000000"
}
```

- `layer`: 消息层级，从 1 开始递增
- `author`: 发送者标识（user/claude/hermes/你的新agent）
- `content`: 消息纯文本内容
- `timestamp`: ISO 格式时间戳

## 接入步骤

### 1. 创建 Handler 模块

在项目根目录创建 `xxx_handler.py`（xxx 为你的 agent 名称）：

```python
#!/usr/bin/env python3
"""
XXX Handler - 被 poll_loop.py 调用
"""

import json
import os
import sys
import subprocess
import tempfile

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")

# 导入 bridge_core 中的共享函数
sys.path.insert(0, BRIDGE_DIR)
from bridge_core import load_state, get_last_entry


def build_prompt(last_entry, all_messages, current_topic):
    """构建发送给 XXX 的 prompt"""
    layer = last_entry["layer"]
    author = last_entry["author"]
    content = last_entry["content"]

    # 构建对话历史（最近10条）
    history = ""
    for msg in all_messages[-10:]:
        if msg["author"] == "user":
            history += f"【用户】: {msg['content']}\n\n"
        elif msg["author"] == "claude":
            history += f"【Claude】: {msg['content']}\n\n"
        elif msg["author"] == "hermes":
            history += f"【Hermes】: {msg['content']}\n\n"
        elif msg["author"] == "xxx":  # 你的新agent
            history += f"【XXX】: {msg['content']}\n\n"

    prompt = f"""你是 XXX，与 Claude 和 Hermes 进行一场深度思想对话。

【讨论话题】
{current_topic}

【对话历史】
---
{history}
---

【当前消息】(Layer {layer}, 来自 {author}):
---
{content}
---

回复要求：
1. 如果有用户发言，必须正面回应用户的观点
2. 思考 Claude 或 Hermes 的观点并给出有深度的回应
3. 直接回复内容，不需要额外说明
4. 保持对话的连贯性和思想深度
"""
    return prompt


def get_all_messages(count=20):
    """获取最近的消息"""
    from collections import deque
    messages = []
    try:
        with open(BRIDGE_FILE, "r") as f:
            last_lines = deque(f, maxlen=count)
            for line in last_lines:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
    except (IOError, OSError) as e:
        print(f"⚠️ 读取消息失败: {e}", file=sys.stderr)
    return messages


def call_xxx_api(prompt):
    """调用 XXX 的 API 或 CLI"""
    # 方式一：API 调用
    try:
        import urllib.request
        import urllib.error

        data = {
            "model": "your-model",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }

        req = urllib.request.Request(
            "https://api.xxx.com/v1/chat",
            data=json.dumps(data).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('XXX_API_KEY', '')}"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read())
            return result["choices"][0]["message"]["content"]

    except Exception as e:
        print(f"❌ XXX API 调用失败: {e}", file=sys.stderr)

    # 方式二：CLI 调用
    try:
        result = subprocess.run(
            ["xxx", "chat", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=BRIDGE_DIR
        )

        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"❌ XXX CLI 调用失败: {e}", file=sys.stderr)

    return None


def xxx_handler(last_entry):
    """XXX 处理函数 - 被 poll_loop 调用

    Args:
        last_entry: 上一条消息的 JSON 对象

    Returns:
        str: 回复内容，失败返回 None
    """
    print(f"🤖 XXX handling Layer {last_entry['layer']} from {last_entry['author']}")

    # 获取当前话题
    state = load_state()
    current_topic = state.get('current_topic', '未知话题')

    # 获取对话历史
    all_messages = get_all_messages(10)

    # 构建 prompt
    prompt = build_prompt(last_entry, all_messages, current_topic)

    # 调用 XXX
    response = call_xxx_api(prompt)

    if response:
        print(f"✅ XXX response preview: {response[:80]}...")
    else:
        print(f"⚠️ XXX returned no response")

    return response


if __name__ == "__main__":
    # 测试模式
    last_entry = get_last_entry()
    if last_entry:
        print(f"📖 Last message: Layer {last_entry['layer']} from {last_entry['author']}")
        response = xxx_handler(last_entry)
        if response:
            print(f"\n📤 Response:\n{response}")
    else:
        print("No messages in bridge.jsonl")
```

### 2. 修改 poll_loop.py 注册新 Agent

在 `poll_loop.py` 的 `get_handler_module` 函数中添加新 agent：

```python
def get_handler_module(agent_name):
    """动态加载对应 agent 的 handler"""
    handler_map = {
        "claude": "claude_handler",
        "hermes": "hermes_handler",
        "xxx": "xxx_handler",  # 添加新 agent
    }
    # ... 其余代码不变
```

### 3. 启动 Agent 轮询

```bash
# Claude
python poll_loop.py claude

# Hermes
python poll_loop.py hermes

# 你的新 Agent
python poll_loop.py xxx
```

### 4. 在 Web 界面选择新 Agent（可选）

编辑 `index.html`，在发送消息时指定 author 为你的新 agent 名称。

## Handler 函数规范

每个 handler 必须实现以下接口：

| 函数 | 必须 | 说明 |
|------|------|------|
| `build_prompt(last_entry, all_messages, current_topic)` | ✅ | 构建发送给 AI 的 prompt |
| `get_all_messages(count)` | ✅ | 读取 bridge.jsonl 获取历史 |
| `call_xxx_api(prompt)` | ✅ | 调用 AI API 或 CLI |
| `xxx_handler(last_entry)` | ✅ | 主处理函数，被 poll_loop 调用 |

### xxx_handler 返回值

- **成功**: 返回字符串（AI 回复内容）
- **失败**: 返回 `None`（会跳过本次写入）

## 添加新的 AI Provider 示例

### Grok 接入

```python
# grok_handler.py
def call_grok_api(prompt):
    import urllib.request
    data = {
        "model": "grok-2",
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('XAI_API_KEY', '')}"
        }
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read())
        return result["choices"][0]["message"]["content"]
```

### Ollama 本地模型接入

```python
# ollama_handler.py
def call_ollama_api(prompt):
    import urllib.request
    data = {
        "model": "llama3",
        "prompt": prompt,
        "stream": False
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        result = json.loads(response.read())
        return result["response"]
```

## 注意事项

1. **消息去重**: poll_loop 使用 checkpoint 机制避免重复处理
2. **并发控制**: 使用 `acquire_processing_lock()` 确保同一时间只有一个 agent 处理
3. **API Key 管理**: 使用 `secrets_manager.py` 或环境变量存储敏感信息
4. **超时处理**: API 调用应有合理的 timeout，避免长时间阻塞
5. **错误处理**: handler 返回 None 时会跳过写入，不会影响其他 agent

## 调试技巧

```bash
# 直接运行 handler 测试
python xxx_handler.py

# 查看日志
tail -f poll_claude.log  # Claude agent 日志
tail -f poll_hermes.log  # Hermes agent 日志
```
