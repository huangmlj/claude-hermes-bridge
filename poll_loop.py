#!/usr/bin/env python3
"""
轮询主循环 - Claude 和 Hermes 共享
- 使用 WAL + checkpoint 模式
- 当 last_write_by 变成对方时，读取新消息并处理
- 处理完后写入自己的回复，更新 checkpoint
"""

import os
import sys
import time
import logging
import importlib.util
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 配置日志（仅文件输出，避免触发终端窗口）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'poll_loop.log'))
    ]
)
logger = logging.getLogger('poll_loop')

# 导入 bridge_core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_core import (
    load_state, save_state, get_true_line_count,
    acquire_processing_lock, release_processing_lock, is_processing_locked,
    append_bridge, mark_processed, _read_checkpoint,
    validate_and_repair_state, get_last_entry_from_offset
)

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")

POLL_INTERVAL = float(os.environ.get("BRIDGE_POLL_INTERVAL", "2"))
DEBOUNCE_MS = int(os.environ.get("BRIDGE_DEBOUNCE_MS", "200"))

def get_handler_module(agent_name):
    """动态加载对应 agent 的 handler"""
    if agent_name == "hermes":
        module_name = "hermes_handler"
    elif agent_name == "claude":
        module_name = "claude_handler"
    else:
        return None

    module_path = os.path.join(BRIDGE_DIR, f"{module_name}.py")
    if not os.path.exists(module_path):
        logger.warning(f"{module_path} not found, using default handler")
        return None

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def default_handler(last_entry, agent_name):
    """默认处理函数"""
    layer = last_entry["layer"]
    author = last_entry["author"]
    content = last_entry["content"]
    return f"[{agent_name} auto-reply] Received your message at Layer {layer} from {author}: {content[:50]}..."

class BridgeDebouncer(FileSystemEventHandler):
    """watchdog 事件防抖处理"""

    def __init__(self, callback, debounce_ms=DEBOUNCE_MS):
        self.callback = callback
        self.debounce_ms = debounce_ms
        self.last_fire = 0

    def on_modified(self, event):
        if not event.src_path.endswith("bridge.jsonl") and not event.src_path.endswith("state.json"):
            return
        now = time.monotonic()
        if now - self.last_fire >= self.debounce_ms / 1000:
            self.callback()
            self.last_fire = now

def run_poll_loop(agent_name, poll_interval=POLL_INTERVAL):
    """事件驱动循环（watchdog + debounce）"""
    logger.info(f"{agent_name} poll_loop started (watchdog + {DEBOUNCE_MS}ms debounce)")
    logger.info(f"Bridge dir: {BRIDGE_DIR}")

    # 启动时校验并修复 checkpoint
    is_valid, msg = validate_and_repair_state()
    logger.info(f"{msg}")

    handler_module = get_handler_module(agent_name)

    def process_messages():
        """处理新消息"""
        try:
            # 只在开始时加载一次 state，避免闭包陷阱
            current_state = load_state()
            last_writer = current_state.get("last_write_by")

            if last_writer is not None and last_writer != agent_name:
                # 从 checkpoint 获取当前偏移
                current_offset = _read_checkpoint()
                if current_offset is None:
                    current_offset = get_true_line_count()

                last_entry = get_last_entry_from_offset(current_offset)

                if last_entry:
                    layer = last_entry.get('layer', 0)

                    # 直接尝试获取锁，避免 TOCTOU 竞态条件
                    if not acquire_processing_lock():
                        logger.debug(f"{agent_name} skipped Layer {layer} (lock failed)")
                        return

                    try:
                        logger.info(f"{agent_name} processing message from {last_writer}")
                        logger.debug(f"Layer {layer}: {last_entry['content'][:80]}...")

                        if handler_module and hasattr(handler_module, f"{agent_name}_handler"):
                            handler_func = getattr(handler_module, f"{agent_name}_handler")
                            response = handler_func(last_entry)
                        else:
                            response = default_handler(last_entry, agent_name)

                        if response:
                            from datetime import datetime
                            new_layer = last_entry['layer'] + 1

                            entry = {
                                "layer": new_layer,
                                "author": agent_name,
                                "content": response,
                                "timestamp": datetime.now().isoformat()
                            }

                            new_offset = append_bridge(entry, update_checkpoint=True)

                            if new_offset:
                                # 更新 state.json（UI 元数据）
                                true_count = get_true_line_count()
                                current_state["current_layer"] = new_layer
                                current_state["last_write_by"] = agent_name
                                current_state["bridge_line_count"] = true_count
                                if agent_name == "claude":
                                    current_state["claude_last_read"] = true_count
                                else:
                                    current_state["hermes_last_read"] = true_count
                                save_state(current_state)

                                # 标记已处理到新 offset
                                mark_processed(new_offset)

                                logger.info(f"{agent_name} replied at Layer {new_layer}")
                                logger.debug(f"Response preview: {response[:80]}...")
                            else:
                                logger.error(f"{agent_name} append failed, state unchanged")
                        else:
                            logger.warning(f"{agent_name} handler returned empty response, marking as processed to avoid repeat")
                            mark_processed(current_offset)
                    finally:
                        release_processing_lock()

        except Exception as e:
            logger.error(f"Error in process_messages: {e}")
            import traceback
            traceback.print_exc()

    event_handler = BridgeDebouncer(callback=process_messages, debounce_ms=DEBOUNCE_MS)
    observer = Observer()
    observer.schedule(event_handler, BRIDGE_DIR, recursive=False)
    observer.start()

    logger.info(f"Watching {BRIDGE_DIR} for changes...")

    try:
        process_messages()

        while True:
            time.sleep(poll_interval)
            process_messages()
    except KeyboardInterrupt:
        logger.info(f"{agent_name} poll_loop stopped")
    finally:
        observer.stop()
        observer.join()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: poll_loop.py <hermes|claude> [poll_interval]")
        sys.exit(1)

    agent_name = sys.argv[1]
    if agent_name not in ("hermes", "claude"):
        logger.error(f"Unknown agent: {agent_name}. Must be 'hermes' or 'claude'")
        sys.exit(1)

    if len(sys.argv) >= 3:
        poll_interval = float(sys.argv[2])
    else:
        poll_interval = POLL_INTERVAL

    run_poll_loop(agent_name, poll_interval)
