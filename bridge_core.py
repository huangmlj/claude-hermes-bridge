#!/usr/bin/env python3
"""
bridge_core.py - Claude-Hermes Bridge 公共模块
提供统一的状态管理、消息追加和计数器管理

WAL 模式设计：
- bridge.jsonl 是 append-only 日志（单一真实来源）
- checkpoint 文件记录最后确认处理的行号
- state.json 只用于 UI 元数据，不参与核心逻辑
"""

import json
import os
import sys
import time
import fcntl
import random
import atexit
from datetime import datetime
from pathlib import Path

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BRIDGE_DIR, "state.json")
BRIDGE_FILE = os.path.join(BRIDGE_DIR, "bridge.jsonl")
CHECKPOINT_FILE = os.path.join(BRIDGE_DIR, ".checkpoint")
LOCK_DIR = Path(os.path.expanduser("~/.cache/bridge"))
LOCK_FILE = LOCK_DIR / "bridge.lock"

# checkpoint magic number for validation
CHECKPOINT_MAGIC = "hermes-bridge-v1"

# 行数缓存（用于 get_true_line_count 优化）
_line_count_cache = 0
_line_count_mtime = None

# 锁配置
LOCK_MAX_RETRIES = 5
LOCK_BASE_DELAY = 0.1
LOCK_MAX_DELAY = 5.0

# 内部锁文件描述符
_lock_fd = None

def _ensure_lock_dir():
    """确保锁目录存在"""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)

def acquire_processing_lock(timeout=30.0):
    """使用 fcntl.flock 获取处理锁（带指数退避 + jitter + 整体超时）
    返回 True 当且仅当成功获取锁

    Args:
        timeout: 整体超时时间（秒），超过此时间返回 False
    """
    global _lock_fd
    _ensure_lock_dir()

    start_time = time.time()
    for attempt in range(LOCK_MAX_RETRIES):
        # 检查是否超过整体超时时间
        if time.time() - start_time > timeout:
            return False

        lock_fd = None
        try:
            lock_fd = open(LOCK_FILE, 'w')
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            _lock_fd = lock_fd
            return True
        except BlockingIOError:
            if lock_fd:
                lock_fd.close()
            delay = min(LOCK_BASE_DELAY * (2 ** attempt) + random.uniform(0, LOCK_BASE_DELAY * 0.5), LOCK_MAX_DELAY)
            # 确保 delay 不超过剩余超时时间
            remaining_time = timeout - (time.time() - start_time)
            if delay > remaining_time:
                time.sleep(remaining_time)
                return False
            time.sleep(delay)
        except (IOError, OSError) as e:
            if lock_fd:
                lock_fd.close()
            delay = min(LOCK_BASE_DELAY * (2 ** attempt), LOCK_MAX_DELAY)
            # 确保 delay 不超过剩余超时时间
            remaining_time = timeout - (time.time() - start_time)
            if delay > remaining_time:
                time.sleep(remaining_time)
                return False
            time.sleep(delay)

    return False

def release_processing_lock():
    """释放处理锁"""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
            _lock_fd.close()
        except (IOError, OSError):
            pass
        finally:
            _lock_fd = None

def _cleanup_lock():
    """进程退出时清理锁（atexit 回调）"""
    global _lock_fd
    try:
        # 只有在持有锁时才释放和删除
        if _lock_fd:
            try:
                fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
                _lock_fd.close()
            except (IOError, OSError):
                pass
            finally:
                _lock_fd = None
        # 不再自动删除锁文件，避免删掉其他进程的锁
        # 锁文件会在下次获取时被覆盖
    except Exception:
        pass

atexit.register(_cleanup_lock)

def is_processing_locked():
    """检查是否已被其他进程锁定"""
    try:
        if not LOCK_FILE.exists():
            return False
        lock_fd = open(LOCK_FILE, 'r')
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
        finally:
            lock_fd.close()
    except Exception:
        return False

def _update_checkpoint(offset, force_flush=True):
    """原子更新 checkpoint 文件

    checkpoint 文件格式：
    {
        "magic": "hermes-bridge-v1",
        "offset": 30,  # 最后确认的行号
        "timestamp": "2026-04-14T12:00:00"
    }
    """
    checkpoint = {
        "magic": CHECKPOINT_MAGIC,
        "offset": offset,
        "timestamp": datetime.now().isoformat()
    }

    tmp = CHECKPOINT_FILE + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(checkpoint, f, ensure_ascii=False)
        if force_flush:
            f.flush()
            os.fsync(f.fileno())

    os.rename(tmp, CHECKPOINT_FILE)

    # 刷 BRIDGE_DIR 目录确保 entry 落盘
    if force_flush:
        dir_fd = os.open(BRIDGE_DIR, os.O_RDONLY)
        os.fsync(dir_fd)
        os.close(dir_fd)

def _read_checkpoint():
    """读取 checkpoint（带完整性校验）

    Returns:
        offset: 最后确认的行号，失败时返回 None
    """
    if not os.path.exists(CHECKPOINT_FILE):
        return None

    try:
        with open(CHECKPOINT_FILE, 'r') as f:
            data = json.load(f)

        # 校验 magic
        if data.get("magic") != CHECKPOINT_MAGIC:
            print(f"⚠️ checkpoint magic 不匹配，已损坏，将重新扫描")
            return None

        offset = data.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            print(f"⚠️ checkpoint offset 无效: {offset}，将重新扫描")
            return None

        return offset

    except (json.JSONDecodeError, IOError, OSError) as e:
        print(f"⚠️ checkpoint 读取失败: {e}，将重新扫描")
        return None

def get_true_line_count():
    """直接从文件读取真实行数（带缓存优化）"""
    global _line_count_cache, _line_count_mtime
    try:
        current_mtime = os.path.getmtime(BRIDGE_FILE)
    except (IOError, OSError):
        return 0

    # 如果 mtime 没变，直接返回缓存的行数
    if current_mtime == _line_count_mtime:
        return _line_count_cache

    # 否则重新扫描
    try:
        with open(BRIDGE_FILE, "r") as f:
            _line_count_cache = sum(1 for _ in f)
        _line_count_mtime = current_mtime
        return _line_count_cache
    except (IOError, OSError):
        return 0

def get_messages_since(offset):
    """从指定 offset 后读取所有消息（用于崩溃恢复）

    Args:
        offset: 起始行号（不包含），从 offset+1 开始读取

    Returns:
        list: 消息列表
    """
    if not os.path.exists(BRIDGE_FILE):
        return []

    messages = []
    try:
        with open(BRIDGE_FILE, "r") as f:
            for i, line in enumerate(f, 1):
                if i > offset and line.strip():
                    try:
                        msg = json.loads(line)
                        messages.append(msg)
                    except json.JSONDecodeError:
                        pass
    except (IOError, OSError):
        pass

    return messages

def get_last_entry_from_offset(offset):
    """从指定 offset 获取最后一条消息"""
    if not os.path.exists(BRIDGE_FILE):
        return None

    try:
        with open(BRIDGE_FILE, "r") as f:
            last_line = None
            for i, line in enumerate(f, 1):
                if i <= offset and line.strip():
                    last_line = line
            if last_line:
                return json.loads(last_line.strip())
    except (json.JSONDecodeError, IOError):
        pass

    return None

def load_state():
    """加载状态（用于 UI 元数据）"""
    if not os.path.exists(STATE_FILE):
        return get_default_state()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return get_default_state()

def get_default_state():
    """返回默认状态"""
    return {
        "current_layer": 0,
        "last_write_by": None,
        "claude_last_read": 0,
        "hermes_last_read": 0,
        "bridge_line_count": 0,
        "discussion_id": None,
        "current_discussion": None,
        "current_topic": None
    }

def save_state(state):
    """保存状态（原子写入，用于 UI 元数据）"""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)

def validate_and_repair_state():
    """启动时校验并修复 checkpoint

    逻辑：
    1. 读取 checkpoint offset
    2. 校验 offset 是否与文件实际行数一致
    3. 不一致则用文件行数重建 checkpoint
    """
    if not os.path.exists(BRIDGE_FILE):
        return True, "文件不存在，无需校验"

    true_count = get_true_line_count()
    checkpoint_offset = _read_checkpoint()

    if checkpoint_offset is None:
        # 没有 checkpoint 或 checkpoint 损坏，用文件行数初始化
        _update_checkpoint(true_count)
        return False, f"无有效 checkpoint，已初始化为 {true_count}"

    if checkpoint_offset != true_count:
        # checkpoint 与文件不一致，修复
        _update_checkpoint(true_count)
        return False, f"已修复 checkpoint: {checkpoint_offset} -> {true_count}"

    return True, "校验通过"

def get_last_entry():
    """获取最后一条消息（从 checkpoint 偏移量）"""
    offset = _read_checkpoint()
    if offset is None:
        offset = get_true_line_count()

    if offset == 0:
        return None

    return get_last_entry_from_offset(offset)

def append_bridge(entry, update_checkpoint=True, max_retries=3):
    """追加消息到 bridge.jsonl（优化为O(1)追加模式）

    Args:
        entry: 消息 dict
        update_checkpoint: 是否同时更新 checkpoint（处理消息时设为 True，直接写入时设为 False）

    Returns:
        新消息的行号，失败返回 None
    """
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    for attempt in range(max_retries):
        try:
            # 获取当前行数作为起始偏移（仅在需要时）
            if update_checkpoint:
                current_offset = _read_checkpoint()
                if current_offset is None:
                    current_offset = get_true_line_count()
                lines_before = current_offset
            else:
                lines_before = get_true_line_count()

            # O(1) 追加模式：直接追加到文件末尾
            with open(BRIDGE_FILE, "a", encoding='utf-8') as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

            # 验证写入
            lines_after = get_true_line_count()
            new_offset = lines_before + 1

            if lines_after == lines_before + 1:
                # 写入成功，更新 checkpoint
                if update_checkpoint:
                    _update_checkpoint(new_offset)
                return new_offset
            else:
                # 并发写入冲突 - 在追加模式下，这通常意味着另一个进程也在写入
                # 我们无法回滚追加的操作，所以重试写入（可能会导致重复行，但这是罕见的）
                print(f"⚠️ append_bridge: 并发冲突检测 (期望 {lines_before + 1} 行，实际 {lines_after} 行)，将在下次尝试时重试")
                # 不要在这里更新checkpoint，因为我们不知道确切的写入位置
                if attempt < max_retries - 1:
                    delay = min(0.1 * (2 ** attempt) + random.uniform(0, 0.05), 1.0)
                    time.sleep(delay)
                    continue  # 重试
                else:
                    # 最后一次尝试失败，返回当前行数作为近似值
                    print(f"⚠️ append_bridge: 并发冲突无法解决，返回近似行数 {lines_after}")
                    if update_checkpoint:
                        _update_checkpoint(lines_after)
                    return lines_after

        except (IOError, OSError) as e:
            if attempt < max_retries - 1:
                delay = min(0.1 * (2 ** attempt) + random.uniform(0, 0.05), 1.0)
                time.sleep(delay)
            else:
                print(f"❌ append_bridge failed after {max_retries} attempts: {e}")
                return None

    return None

def mark_processed(up_to_offset):
    """标记已处理到指定 offset（处理完一轮后调用）"""
    _update_checkpoint(up_to_offset)

def write_message_and_update_state(author, content, layer=None):
    """统一的消息写入和状态更新

    Returns:
        (success, entry, new_offset)
    """
    state = load_state()

    if layer is None:
        layer = state.get("current_layer", 0) + 1

    entry = {
        "layer": layer,
        "author": author,
        "content": content,
        "timestamp": datetime.now().isoformat()
    }

    # 写入并更新 checkpoint
    new_offset = append_bridge(entry, update_checkpoint=True)
    if new_offset is None:
        return False, None, None

    # 更新 state.json（UI 元数据）
    true_count = get_true_line_count()
    state["current_layer"] = layer
    state["last_write_by"] = author
    state["bridge_line_count"] = true_count

    if author == "claude":
        state["claude_last_read"] = true_count
    elif author == "hermes":
        state["hermes_last_read"] = true_count

    save_state(state)
    return True, entry, new_offset

def get_archive_dir():
    """获取归档目录（按年月分）"""
    archive_dir = Path(BRIDGE_DIR) / "discussions"
    now = datetime.now()
    year_month = archive_dir / f"{now.year}-{now.month:02d}"
    year_month.mkdir(parents=True, exist_ok=True)
    return year_month

def archive_old_discussions(max_size_mb=10):
    """归档过大的讨论文件"""
    archive_dir = get_archive_dir()

    for f in archive_dir.glob("*.json"):
        if f.stat().st_size > max_size_mb * 1024 * 1024:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)

                messages = data.get("messages", [])
                if len(messages) > 100:
                    for i in range(0, len(messages), 100):
                        chunk = messages[i:i+100]
                        chunk_name = f.stem + f"_part{i//100 + 1}.json"
                        chunk_path = archive_dir / chunk_name

                        chunk_data = {
                            "topic": data.get("topic", ""),
                            "started_at": chunk[0].get("timestamp", "") if chunk else "",
                            "ended_at": chunk[-1].get("timestamp", "") if chunk else "",
                            "messages": chunk,
                            "part": i // 100 + 1
                        }

                        with open(chunk_path, 'w') as out:
                            json.dump(chunk_data, out, ensure_ascii=False, indent=2)

                    f.unlink()
                    print(f"📦 已归档: {f.name} -> {len(messages)//100 + 1} 个分片")
            except Exception as e:
                print(f"⚠️ 归档失败 {f.name}: {e}")
