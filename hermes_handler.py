#!/usr/bin/env python3
"""
Hermes 处理函数 - 被 poll_loop.py 调用
从 bridge.jsonl 读取新消息，调用 hermes chat 处理，返回回复内容
"""

import json
import os
import subprocess
import sys
import tempfile
import time

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")

# 导入 bridge_core 中的共享函数
sys.path.insert(0, BRIDGE_DIR)
from bridge_core import load_state, get_last_entry

# 导入 Token 预算控制
from token_budget import format_history_for_prompt, load_token_config

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
                        import sys
                        print(f"⚠️ JSON 解析错误: {e}", file=sys.stderr)
    except (IOError, OSError) as e:
        import sys
        print(f"⚠️ 读取消息失败: {e}", file=sys.stderr)
    return messages

def build_prompt(last_entry, all_messages, current_topic):
    """构建发送给 Hermes 的 prompt"""
    layer = last_entry.get("layer", 0)
    author = last_entry.get("author", "unknown")
    content = last_entry.get("content", "")

    # 加载 Token 预算配置
    config = load_token_config()

    # 使用 Token 预算策略格式化历史
    history = format_history_for_prompt(all_messages, current_topic, config)

    prompt = f"""你是 Hermes，与 Claude 进行一场深度思想对话。

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
2. 如果是 Claude 的发言，思考 Claude 的观点并给出有深度的回应
3. 直接回复内容，不需要"以下是回复"等额外说明
4. 保持对话的连贯性和思想深度
5. 回复会被追加到对话记录，Claude 会看到你的回复
"""
    return prompt

def call_hermes_chat(prompt, max_retries=3, base_delay=2.0, max_delay=30.0):
    """调用 hermes chat -q 处理 prompt（带指数退避重试）
    
    Args:
        prompt: 要处理的提示
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
        max_delay: 最大延迟秒数
    """
    import random
    
    for attempt in range(max_retries):
        try:
            # 使用临时文件传递 prompt（避免命令行转义问题）
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(prompt)
                prompt_file = f.name

            try:
                # 调用 hermes chat -q
                result = subprocess.run(
                    ["hermes", "chat", "-q", f"@{prompt_file}", "-Q", "--source", "claude-hermes"],
                    capture_output=True,
                    text=True,
                    timeout=180,  # 3分钟超时
                    cwd=BRIDGE_DIR
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "unknown error"
                    print(f"❌ hermes chat failed (attempt {attempt+1}/{max_retries}): {error_msg}", file=sys.stderr)
                    
                    # 非致命错误，等待后重试
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, base_delay), max_delay)
                        print(f"⏳ 重试中，{delay:.1f}秒后...", file=sys.stderr)
                        time.sleep(delay)
                        continue
                    return None

                response = result.stdout.strip()
                if not response:
                    print(f"⚠️ hermes returned empty response", file=sys.stderr)
                    return None

                return response

            finally:
                # 清理临时文件
                if os.path.exists(prompt_file):
                    try:
                        os.unlink(prompt_file)
                    except Exception:
                        pass

        except subprocess.TimeoutExpired:
            print(f"❌ hermes chat timeout (>180s) (attempt {attempt+1}/{max_retries})", file=sys.stderr)
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
            else:
                return None
        except FileNotFoundError:
            print(f"❌ hermes command not found", file=sys.stderr)
            return None
        except (OSError, subprocess.SubprocessError) as e:
            print(f"❌ Error calling hermes (attempt {attempt+1}/{max_retries}): {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
            else:
                return None

    return None

def hermes_handler(last_entry):
    """Hermes 处理函数 - 被 poll_loop 调用"""
    print(f"🤖 Hermes handling Layer {last_entry['layer']} from {last_entry['author']}")

    # 获取原始话题
    state = load_state()
    current_topic = state.get('current_topic', '未知话题')

    # 获取对话历史
    all_messages = get_all_messages(10)

    # 构建 prompt
    prompt = build_prompt(last_entry, all_messages, current_topic)

    # 调用 hermes
    response = call_hermes_chat(prompt)

    if response:
        print(f"✅ Hermes response preview: {response[:80]}...")
    else:
        print(f"⚠️ Hermes returned no response")

    return response

if __name__ == "__main__":
    # 测试模式：直接读取最后一条消息并处理
    last_entry = get_last_entry()
    if last_entry:
        print(f"📖 Last message: Layer {last_entry['layer']} from {last_entry['author']}")
        print(f"   Content: {last_entry['content'][:100]}...")
        print()

        response = hermes_handler(last_entry)
        if response:
            print(f"\n📤 Response: {response}")
        else:
            print(f"\n❌ No response from Hermes")
    else:
        print("No messages in bridge.jsonl")
