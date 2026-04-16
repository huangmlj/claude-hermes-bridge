#!/usr/bin/env python3
"""读取未读消息"""

import json
import os

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")

def load_state():
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def read_new_messages(reader):
    state = load_state()
    
    if reader == "claude":
        last_read = state["claude_last_read"]
    else:
        last_read = state["hermes_last_read"]
    
    line_count = state["bridge_line_count"]
    
    if last_read >= line_count:
        return []
    
    messages = []
    with open(BRIDGE_FILE, "r") as f:
        for i, line in enumerate(f, 1):
            if i > last_read:
                messages.append(json.loads(line.strip()))
    
    return messages

def get_latest_message():
    state = load_state()
    line_count = state["bridge_line_count"]
    
    if line_count == 0:
        return None
    
    with open(BRIDGE_FILE, "r") as f:
        for i, line in enumerate(f, 1):
            if i == line_count:
                return json.loads(line.strip())
    
    return None

def get_last_writer():
    state = load_state()
    return state["last_write_by"]

def get_current_layer():
    state = load_state()
    return state["current_layer"]

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        # 默认读取 hermes 的未读消息
        messages = read_new_messages("hermes")
    else:
        messages = read_new_messages(sys.argv[1])
    
    if not messages:
        print("No new messages")
    else:
        for msg in messages:
            print(f"[Layer {msg['layer']}] {msg['author']}: {msg['content'][:100]}...")
