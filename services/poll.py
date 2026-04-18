#!/usr/bin/env python3
"""
poll.py - AI 轮询服务（多进程架构）

合并自：
- poll_loop.py
- hermes_handler.py
- claude_handler.py

职责：
- 事件驱动的轮询循环（watchdog + debounce）
- AI handler：调用 Hermes/Claude CLI 处理消息
- 进程管理：启动/停止轮询子进程

保持多进程架构：每个 AI 独立子进程，通过 bridge.jsonl + checkpoint 协作。
"""

import json
import os
import sys
import time
import logging
import importlib.util
import hashlib
import subprocess
import tempfile
import random
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 项目根目录 = services/ 的父目录
_BRIDGE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BRIDGE_DIR))

from services.bridge import (
    load_state, save_state, get_true_line_count,
    acquire_processing_lock, release_processing_lock,
    append_bridge, mark_processed, _read_checkpoint,
    validate_and_repair_state, get_last_entry_from_offset
)
from token_budget import format_history_for_prompt, load_token_config

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BRIDGE_FILE = _BRIDGE_DIR / "bridge.jsonl"
POLL_INTERVAL = float(os.environ.get("BRIDGE_POLL_INTERVAL", "0.1"))
DEBOUNCE_MS = int(os.environ.get("BRIDGE_DEBOUNCE_MS", "200"))
AI_TIMEOUT = 180  # Hermes CLI 超时（秒）
CLAUDE_TIMEOUT = 120  # Claude CLI 超时（秒）

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(_BRIDGE_DIR / 'poll_loop.log'))
    ]
)
logger = logging.getLogger('poll_loop')


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def generate_message_id(author: str, content: str, timestamp: str) -> str:
    """生成消息幂等ID"""
    return hashlib.sha256(f"{author}:{content}:{timestamp}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Hermes Handler
# ---------------------------------------------------------------------------

def hermes_get_all_messages(count: int = 20):
    """获取最近的消息"""
    from collections import deque
    messages = []
    try:
        with open(str(BRIDGE_FILE), "r") as f:
            last_lines = deque(f, maxlen=count)
            for line in last_lines:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except (IOError, OSError):
        pass
    return messages


def hermes_build_prompt(last_entry, all_messages, current_topic):
    """构建 Hermes 的 prompt"""
    layer = last_entry.get("layer", 0)
    author = last_entry.get("author", "unknown")
    content = last_entry.get("content", "")
    config = load_token_config()
    history = format_history_for_prompt(all_messages, current_topic, config)

    return f"""你是 Hermes，与 Claude 进行一场深度思想对话。

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


def hermes_call(prompt, max_retries=3, base_delay=2.0, max_delay=30.0):
    """调用 hermes chat -q 处理 prompt"""
    for attempt in range(max_retries):
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(prompt)
                prompt_file = f.name

            try:
                result = subprocess.run(
                    ["hermes", "chat", "-q", f"@{prompt_file}", "-Q", "--source", "claude-hermes"],
                    capture_output=True,
                    text=True,
                    timeout=AI_TIMEOUT,
                    cwd=str(_BRIDGE_DIR)
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "unknown error"
                    logger.error(f"hermes failed (attempt {attempt+1}/{max_retries}): {error_msg}")
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, base_delay), max_delay)
                        time.sleep(delay)
                        continue
                    return None

                response = result.stdout.strip()
                if not response:
                    return None
                return response

            finally:
                if os.path.exists(prompt_file):
                    os.unlink(prompt_file)

        except subprocess.TimeoutExpired:
            logger.error(f"hermes timeout (>180s) (attempt {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(min(base_delay * (2 ** attempt), max_delay))
            else:
                return None
        except FileNotFoundError:
            logger.error("hermes command not found")
            return None
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"Error calling hermes (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(min(base_delay * (2 ** attempt), max_delay))
            else:
                return None

    return None


def hermes_handler(last_entry) -> str | None:
    """Hermes 处理函数"""
    logger.info(f"Hermes handling Layer {last_entry['layer']} from {last_entry['author']}")

    state = load_state()
    current_topic = state.get('current_topic', '未知话题')
    all_messages = hermes_get_all_messages(10)
    prompt = hermes_build_prompt(last_entry, all_messages, current_topic)
    response = hermes_call(prompt)

    if response:
        logger.info(f"Hermes response preview: {response[:80]}...")
    else:
        logger.warning("Hermes returned no response")

    return response


# ---------------------------------------------------------------------------
# Claude Handler
# ---------------------------------------------------------------------------

def claude_get_all_messages(count: int = 20):
    """获取最近的消息"""
    from collections import deque
    messages = []
    try:
        with open(str(BRIDGE_FILE), "r") as f:
            last_lines = deque(f, maxlen=count)
            for line in last_lines:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except (IOError, OSError):
        pass
    return messages


def claude_build_prompt(last_entry, all_messages, current_topic):
    """构建 Claude 的 prompt"""
    layer = last_entry.get("layer", 0)
    author = last_entry.get("author", "unknown")
    content = last_entry.get("content", "")
    config = load_token_config()
    history = format_history_for_prompt(all_messages, current_topic, config)

    return f"""你是 Claude，与 Hermes 进行一场深度思想对话。

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


def claude_call(prompt) -> str | None:
    """调用 Claude CLI"""
    try:
        result = subprocess.run(
            ["claude", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd=str(_BRIDGE_DIR)
        )

        if result.returncode != 0:
            logger.error(f"claude CLI failed: {result.stderr}")
            return None

        response = result.stdout.strip()
        if not response:
            return None
        return response

    except FileNotFoundError:
        logger.error("claude command not found")
        return None
    except Exception as e:
        logger.error(f"Error calling claude: {e}")
        return None


def claude_handler(last_entry) -> str | None:
    """Claude 处理函数"""
    logger.info(f"Claude handling Layer {last_entry['layer']} from {last_entry['author']}")

    state = load_state()
    current_topic = state.get('current_topic', '未知话题')
    all_messages = claude_get_all_messages(10)
    prompt = claude_build_prompt(last_entry, all_messages, current_topic)
    response = claude_call(prompt)

    if response:
        logger.info(f"Claude response preview: {response[:80]}...")
    else:
        logger.warning("Claude returned no response")

    return response


# ---------------------------------------------------------------------------
# 轮询循环
# ---------------------------------------------------------------------------

def default_handler(last_entry, agent_name: str) -> str:
    """默认处理函数（fallback）"""
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


# Handler 映射
_HANDLERS = {
    "hermes": hermes_handler,
    "claude": claude_handler,
}


def run_poll_loop(agent_name: str, poll_interval: float = POLL_INTERVAL) -> None:
    """事件驱动循环（watchdog + debounce）

    Args:
        agent_name: "hermes" 或 "claude"
        poll_interval: 备用轮询间隔（秒）
    """
    logger.info(f"{agent_name} poll_loop started (watchdog + {DEBOUNCE_MS}ms debounce)")
    logger.info(f"Bridge dir: {_BRIDGE_DIR}")

    # 启动时校验并修复 checkpoint
    is_valid, msg = validate_and_repair_state()
    logger.info(msg)

    handler_fn = _HANDLERS.get(agent_name, lambda e: default_handler(e, agent_name))

    def process_messages():
        """处理新消息"""
        try:
            # 1. 先抢锁，抢不到说明其他进程在处理，直接退出
            if not acquire_processing_lock():
                return

            try:
                # 2. 【核心修复】：拿到锁后，重新读取最新状态
                current_state = load_state()
                last_writer = current_state.get("last_write_by")

                # 如果最新状态已经是自己写的了，说明其他进程已处理过，跳过
                if last_writer == agent_name:
                    return

                current_offset = _read_checkpoint()
                if current_offset is None:
                    current_offset = get_true_line_count()

                last_entry = get_last_entry_from_offset(current_offset)

                if last_entry:
                    layer = last_entry.get('layer', 0)
                    logger.info(f"{agent_name} processing message from {last_writer}")
                    logger.debug(f"Layer {layer}: {last_entry['content'][:80]}...")

                    response = handler_fn(last_entry)

                    if response:
                        new_layer = last_entry['layer'] + 1
                        timestamp = datetime.now().isoformat()
                        entry = {
                            "layer": new_layer,
                            "author": agent_name,
                            "content": response,
                            "timestamp": timestamp,
                            "id": generate_message_id(agent_name, response, timestamp)
                        }

                        new_offset = append_bridge(entry, update_checkpoint=True)

                        if new_offset:
                            true_count = get_true_line_count()
                            current_state["current_layer"] = new_layer
                            current_state["last_write_by"] = agent_name
                            current_state["bridge_line_count"] = true_count
                            if agent_name == "claude":
                                current_state["claude_last_read"] = true_count
                            else:
                                current_state["hermes_last_read"] = true_count
                            save_state(current_state)
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
    observer.schedule(event_handler, str(_BRIDGE_DIR), recursive=False)
    observer.start()

    logger.info(f"Watching {_BRIDGE_DIR} for changes...")

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


# ---------------------------------------------------------------------------
# 进程管理（供 server.py 调用）
# ---------------------------------------------------------------------------

def start_poll(agent_name: str) -> dict:
    """启动轮询子进程

    Returns:
        dict: {success: bool, pid: int | None, message: str}
    """
    pid_file = _BRIDGE_DIR / f".poll_{agent_name}.pid"

    # 检查是否已在运行
    try:
        if pid_file.exists():
            old_pid = int(pid_file.read_text().strip())
            try:
                os.kill(old_pid, 0)  # 检查进程是否存在
                return {"success": False, "pid": old_pid, "message": f"{agent_name} poll 已在运行 (PID {old_pid})"}
            except OSError:
                pid_file.unlink()  # 进程已死，删除 PID 文件

        script = _BRIDGE_DIR / "services" / "poll.py"
        if not script.exists():
            # 兼容旧路径
            script = _BRIDGE_DIR / "poll_loop.py"

        proc = subprocess.Popen(
            [sys.executable, str(script), agent_name],
            cwd=str(_BRIDGE_DIR),
            stdout=open(str(_BRIDGE_DIR / f"poll_{agent_name}.log"), "w"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        pid_file.write_text(str(proc.pid))
        return {"success": True, "pid": proc.pid, "message": f"{agent_name} poll 已启动 (PID {proc.pid})"}

    except Exception as e:
        return {"success": False, "pid": None, "message": str(e)}


def stop_poll(agent_name: str) -> dict:
    """停止轮询子进程

    Returns:
        dict: {success: bool, message: str}
    """
    pid_file = _BRIDGE_DIR / f".poll_{agent_name}.pid"

    try:
        if pid_file.exists():
            old_pid = int(pid_file.read_text().strip())
            try:
                os.kill(old_pid, 15)  # SIGTERM
                time.sleep(0.5)
                os.kill(old_pid, 9)  # SIGKILL 如果还没停
            except OSError:
                pass
            pid_file.unlink()

        # 也用 pkill 作为备份
        subprocess.run(["pkill", "-f", f"poll_loop.py {agent_name}"], capture_output=True)
        subprocess.run(["pkill", "-f", f"poll.py {agent_name}"], capture_output=True)

        return {"success": True, "message": f"{agent_name} poll 已停止"}

    except Exception as e:
        return {"success": False, "message": str(e)}


def is_poll_running(agent_name: str) -> bool:
    """检查轮询进程是否在运行"""
    pid_file = _BRIDGE_DIR / f".poll_{agent_name}.pid"

    try:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
    except (ValueError, OSError):
        pass

    return False


def stop_all_polls() -> None:
    """停止所有轮询进程"""
    for agent in ("hermes", "claude"):
        stop_poll(agent)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: poll.py <hermes|claude> [poll_interval]")
        sys.exit(1)

    agent_name = sys.argv[1]
    if agent_name not in ("hermes", "claude"):
        logger.error(f"Unknown agent: {agent_name}")
        sys.exit(1)

    poll_interval = float(sys.argv[2]) if len(sys.argv) >= 3 else POLL_INTERVAL
    run_poll_loop(agent_name, poll_interval)
