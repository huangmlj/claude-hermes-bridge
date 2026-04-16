#!/usr/bin/env python3
"""
Claude 处理函数 - 被 poll_loop.py 调用
从 bridge.jsonl 读取新消息，调用 Claude CLI 处理，返回回复内容
"""

import json
import os
import sys
import subprocess

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")

# 导入 bridge_core 中的共享函数
sys.path.insert(0, BRIDGE_DIR)
from bridge_core import load_state, get_last_entry

# 导入 Token 预算控制
from token_budget import format_history_for_prompt, load_token_config


def build_prompt(last_entry, all_messages, current_topic):
    """构建发送给 Claude 的 prompt"""
    layer = last_entry.get("layer", 0)
    author = last_entry.get("author", "unknown")
    content = last_entry.get("content", "")

    # 加载 Token 预算配置
    config = load_token_config()

    # 使用 Token 预算策略格式化历史
    history = format_history_for_prompt(all_messages, current_topic, config)

    prompt = f"""你是 Claude，与 Hermes 进行一场深度思想对话。

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
2. 如果是 Hermes 的发言，思考 Hermes 的观点并给出有深度的回应
3. 直接回复内容，不需要"以下是回复"等额外说明
4. 保持对话的连贯性和思想深度
5. 回复会被追加到对话记录，Hermes 会看到你的回复
"""
    return prompt


def get_all_messages(count=20):
    """获取最近的消息（优化：只读最后 count 行）"""
    from collections import deque
    messages = []
    try:
        with open(BRIDGE_FILE, "r") as f:
            last_lines = deque(f, maxlen=count)
            for line in last_lines:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"⚠️ JSON 解析错误: {e}", file=sys.stderr)
    except (IOError, OSError) as e:
        print(f"⚠️ 读取消息失败: {e}", file=sys.stderr)
    return messages


def call_claude(prompt):
    """调用 Claude CLI"""
    try:
        result = subprocess.run(
            ["claude", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=BRIDGE_DIR
        )

        if result.returncode != 0:
            print(f"❌ claude CLI failed: {result.stderr}", file=sys.stderr)
            return None

        response = result.stdout.strip()
        if not response:
            return None

        return response

    except FileNotFoundError:
        print("❌ claude command not found", file=sys.stderr)
        return None
    except Exception as e:
        print(f"❌ Error calling claude: {e}", file=sys.stderr)
        return None


def claude_handler(last_entry):
    """Claude 处理函数 - 被 poll_loop 调用"""
    print(f"🤖 Claude handling Layer {last_entry['layer']} from {last_entry['author']}")

    # 获取原始话题
    state = load_state()
    current_topic = state.get('current_topic', '未知话题')

    # 获取对话历史
    all_messages = get_all_messages(10)

    # 构建 prompt
    prompt = build_prompt(last_entry, all_messages, current_topic)

    # 调用 Claude
    response = call_claude(prompt)

    if response:
        print(f"✅ Claude response preview: {response[:80]}...")
    else:
        print(f"⚠️ Claude returned no response")

    return response


if __name__ == "__main__":
    last_entry = get_last_entry()
    if last_entry:
        print(f"📖 Last message: Layer {last_entry['layer']} from {last_entry['author']}")
        response = claude_handler(last_entry)
        if response:
            print(f"\n📤 Response:\n{response}")
    else:
        print("No messages in bridge.jsonl")
