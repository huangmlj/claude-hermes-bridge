#!/usr/bin/env python3
"""写入消息到 bridge.jsonl，并更新 state.json"""

import json
import sys
import os
from datetime import datetime

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")

def init_files():
    """确保文件存在，必要时初始化（原子操作）"""
    # 确保 bridge.jsonl 存在且没有空行
    if not os.path.exists(BRIDGE_FILE):
        with open(BRIDGE_FILE, "w") as f:
            pass
        return 0

    # 清理空行并计数（原子操作：先写临时文件再替换）
    with open(BRIDGE_FILE, "r") as f:
        lines = [line.strip() for line in f if line.strip()]

    tmp_file = BRIDGE_FILE + ".tmp"
    try:
        with open(tmp_file, "w") as f:
            for line in lines:
                f.write(line + "\n")

        # 原子替换（os.replace 是原子操作）
        os.replace(tmp_file, BRIDGE_FILE)
    except Exception as e:
        # 清理临时文件
        if os.path.exists(tmp_file):
            os.unlink(tmp_file)
        raise e

    return len(lines)

def load_state():
    """加载状态文件，必要时初始化"""
    if not os.path.exists(STATE_FILE):
        return {
            "current_layer": 0,
            "last_write_by": None,
            "claude_last_read": 0,
            "hermes_last_read": 0,
            "bridge_line_count": 0,
            "conversation_id": f"conv-{datetime.now().strftime('%Y%m%d')}-001"
        }

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        # 确保所有必要字段存在
        defaults = {
            "current_layer": 0,
            "last_write_by": None,
            "claude_last_read": 0,
            "hermes_last_read": 0,
            "bridge_line_count": 0,
            "conversation_id": f"conv-{datetime.now().strftime('%Y%m%d')}-001"
        }
        for key, val in defaults.items():
            if key not in state:
                state[key] = val
        return state
    except (json.JSONDecodeError, IOError):
        return defaults

def save_state(state):
    """保存状态文件（原子写入）"""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)

def append_bridge(entry):
    """追加消息到 bridge.jsonl"""
    with open(BRIDGE_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def write_message(author, content, layer):
    """写入消息并更新状态"""
    if not content or not content.strip():
        print(f"❌ {author}: 内容不能为空")
        return False

    # 初始化文件（清理空行）
    line_count = init_files()

    # 构建消息
    entry = {
        "layer": layer,
        "author": author,
        "content": content.strip(),
        "timestamp": datetime.now().isoformat()
    }

    # 追加写入
    append_bridge(entry)

    # 更新状态
    state = load_state()
    state["current_layer"] = layer
    state["last_write_by"] = author
    state["bridge_line_count"] = line_count + 1

    if author == "claude":
        state["claude_last_read"] = state["bridge_line_count"]
    else:
        state["hermes_last_read"] = state["bridge_line_count"]

    save_state(state)

    print(f"✅ {author} wrote Layer {layer}")
    print(f"📝 Content preview: {content[:80]}...")
    return True

def main():
    if len(sys.argv) < 4:
        print("Usage: write_message.py <author> <content> <layer>")
        print("Example: write_message.py claude '分析这段代码' 1")
        sys.exit(1)

    author = sys.argv[1]
    content = sys.argv[2]
    layer = int(sys.argv[3])

    success = write_message(author, content, layer)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
