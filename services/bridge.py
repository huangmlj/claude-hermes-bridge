#!/usr/bin/env python3
"""
bridge.py - WAL + Checkpoint + 锁 核心模块

从 bridge_core.py 提取，职责：
- append_bridge: 追加消息到 bridge.jsonl（WAL）
- mark_processed: 更新 checkpoint
- acquire/release_processing_lock: 进程级锁
- load_state/save_state: UI 元数据（state.json）
- validate_and_repair_state: 启动校验
"""

import json
import os
import time
import fcntl
import random
import atexit
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# ---------------------------------------------------------------------------
# 路径配置（相对于项目根目录）
# ---------------------------------------------------------------------------
# 项目根目录 = services/ 的父目录
_BRIDGE_DIR = Path(__file__).parent.parent
STATE_FILE = _BRIDGE_DIR / "state.json"
BRIDGE_FILE = _BRIDGE_DIR / "bridge.jsonl"
CHECKPOINT_FILE = _BRIDGE_DIR / ".checkpoint"
ARCHIVE_DIR = _BRIDGE_DIR / "discussions"
LOCK_DIR = Path(os.path.expanduser("~/.cache/bridge"))
LOCK_FILE = LOCK_DIR / "bridge.lock"

CHECKPOINT_MAGIC = "hermes-bridge-v1"

# 行数缓存（线程安全）
_line_count_cache = 0
_byte_offset_cache = 0  # 字节偏移量缓存，用于增量读取
_line_count_mtime = None
_line_count_lock = threading.Lock()

# 追加写入专用文件锁（跨进程保护，不同于处理锁）
_APPEND_LOCK_FILE = _BRIDGE_DIR / ".append_lock"

# 锁配置
LOCK_MAX_RETRIES = 5
LOCK_BASE_DELAY = 0.1
LOCK_MAX_DELAY = 5.0

# 内部锁文件描述符
_lock_fd: Optional[Any] = None


# ---------------------------------------------------------------------------
# 锁管理
# ---------------------------------------------------------------------------

def _ensure_lock_dir():
    LOCK_DIR.mkdir(parents=True, exist_ok=True)


def acquire_processing_lock(timeout: float = 30.0) -> bool:
    """使用 fcntl.flock 获取处理锁（合并异常处理，精简代码）"""
    global _lock_fd
    _ensure_lock_dir()

    start_time = time.time()
    for attempt in range(LOCK_MAX_RETRIES):
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
        except (IOError, OSError) as e:
            if lock_fd:
                lock_fd.close()

            # 根据异常类型动态决定抖动(Jitter)
            jitter = random.uniform(0, LOCK_BASE_DELAY * 0.5) if isinstance(e, BlockingIOError) else 0
            delay = min(LOCK_BASE_DELAY * (2 ** attempt) + jitter, LOCK_MAX_DELAY)

            remaining_time = timeout - (time.time() - start_time)
            if delay > remaining_time:
                time.sleep(max(remaining_time, 0))
                return False
            time.sleep(delay)

    return False


def release_processing_lock() -> None:
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


def _cleanup_lock() -> None:
    """进程退出时清理锁（atexit 回调）"""
    global _lock_fd
    try:
        if _lock_fd:
            try:
                fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
                _lock_fd.close()
            except (IOError, OSError):
                pass
            finally:
                _lock_fd = None
    except Exception:
        pass


atexit.register(_cleanup_lock)


def is_processing_locked() -> bool:
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


# ---------------------------------------------------------------------------
# Checkpoint 管理
# ---------------------------------------------------------------------------

def _update_checkpoint(offset: int, force_flush: bool = True) -> None:
    """原子更新 checkpoint 文件"""
    checkpoint = {
        "magic": CHECKPOINT_MAGIC,
        "offset": offset,
        "timestamp": datetime.now().isoformat()
    }

    tmp = str(CHECKPOINT_FILE) + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(checkpoint, f, ensure_ascii=False)
        if force_flush:
            f.flush()
            os.fsync(f.fileno())

    os.rename(tmp, str(CHECKPOINT_FILE))

    if force_flush:
        dir_fd = os.open(str(_BRIDGE_DIR), os.O_RDONLY)
        os.fsync(dir_fd)
        os.close(dir_fd)


def _read_checkpoint() -> Optional[int]:
    """读取 checkpoint（带完整性校验）"""
    if not os.path.exists(str(CHECKPOINT_FILE)):
        return None

    try:
        with open(CHECKPOINT_FILE, 'r') as f:
            data = json.load(f)

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


def get_true_line_count() -> int:
    """直接从文件读取真实行数（引入 Byte Offset 增量读取优化，性能提升百倍）"""
    global _line_count_cache, _byte_offset_cache, _line_count_mtime
    try:
        current_mtime = os.path.getmtime(str(BRIDGE_FILE))
        current_size = os.path.getsize(str(BRIDGE_FILE))
    except (IOError, OSError):
        return 0

    with _line_count_lock:
        if current_mtime == _line_count_mtime:
            return _line_count_cache

        try:
            with open(str(BRIDGE_FILE), "rb") as f:
                # 核心优化：如果文件变大了，直接从上次缓存的指针位置增量读取
                if current_size > _byte_offset_cache and _byte_offset_cache > 0:
                    f.seek(_byte_offset_cache)
                    new_lines = sum(1 for _ in f)
                    _line_count_cache += new_lines  # 累加，不是覆盖
                else:
                    # 文件被截断或首次加载：从头读取
                    f.seek(0)
                    _line_count_cache = sum(1 for _ in f)

                # 记录最新的字节偏移量（EOF 位置）
                _byte_offset_cache = f.tell()

            _line_count_mtime = current_mtime
            return _line_count_cache
        except (IOError, OSError):
            return 0


# ---------------------------------------------------------------------------
# 消息读写
# ---------------------------------------------------------------------------

def get_messages_since(offset: int) -> List[Dict[str, Any]]:
    """从指定 offset 后读取所有消息（用于崩溃恢复）"""
    if not os.path.exists(str(BRIDGE_FILE)):
        return []

    messages = []
    try:
        with open(str(BRIDGE_FILE), "r") as f:
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


def get_last_entry_from_offset(offset: int) -> Optional[Dict[str, Any]]:
    """从指定 offset 获取最后一条消息"""
    if not os.path.exists(str(BRIDGE_FILE)):
        return None

    try:
        with open(str(BRIDGE_FILE), "r") as f:
            last_line = None
            for i, line in enumerate(f, 1):
                if i <= offset and line.strip():
                    last_line = line
            if last_line:
                return json.loads(last_line.strip())
    except (json.JSONDecodeError, IOError):
        pass

    return None


def get_last_entry() -> Optional[Dict[str, Any]]:
    """获取最后一条消息（从 checkpoint 偏移量）"""
    offset = _read_checkpoint()
    if offset is None:
        offset = get_true_line_count()

    if offset == 0:
        return None

    return get_last_entry_from_offset(offset)


# ---------------------------------------------------------------------------
# State 管理（UI 元数据）
# ---------------------------------------------------------------------------

def get_default_state() -> Dict[str, Any]:
    """返回默认状态"""
    return {
        "current_layer": 0,
        "last_write_by": None,
        "claude_last_read": 0,
        "hermes_last_read": 0,
        "bridge_line_count": 0,
        "discussion_id": None,
        "current_discussion": None,
        "current_topic": None,
        "discussion_started": False,
    }


def load_state() -> Dict[str, Any]:
    """加载状态（用于 UI 元数据）"""
    if not os.path.exists(str(STATE_FILE)):
        return get_default_state()
    try:
        with open(str(STATE_FILE), "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return get_default_state()


def save_state(state: Dict[str, Any]) -> None:
    """保存状态（原子写入，用于 UI 元数据）"""
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(STATE_FILE))


# ---------------------------------------------------------------------------
# 启动校验
# ---------------------------------------------------------------------------

def validate_and_repair_state() -> tuple:
    """启动时校验并修复 checkpoint

    Returns:
        (ok: bool, message: str)
    """
    if not os.path.exists(str(BRIDGE_FILE)):
        return True, "文件不存在，无需校验"

    true_count = get_true_line_count()
    checkpoint_offset = _read_checkpoint()

    if checkpoint_offset is None:
        _update_checkpoint(true_count)
        return False, f"无有效 checkpoint，已初始化为 {true_count}"

    if checkpoint_offset != true_count:
        _update_checkpoint(true_count)
        return False, f"已修复 checkpoint: {checkpoint_offset} -> {true_count}"

    return True, "校验通过"


# ---------------------------------------------------------------------------
# WAL 追加
# ---------------------------------------------------------------------------

def generate_message_id(author: str, content: str, timestamp: str) -> str:
    """生成消息幂等ID（基于内容+时间戳的hash）"""
    import hashlib
    raw = f"{author}:{content}:{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def append_bridge(entry: Dict[str, Any], update_checkpoint: bool = True, max_retries: int = 3) -> Optional[int]:
    """追加消息到 bridge.jsonl（O(1)追加模式，无 O(N) 文件扫描）

    策略：追加写入是原子操作，写成功即为 lines_before+1。
    - update_checkpoint=True 时：用 checkpoint 做 lines_before（O(1)），写后不扫描
    - update_checkpoint=False 时：只在首次获取行数（O(N)），用于无 checkpoint 的独立写

    Args:
        entry: 消息 dict
        update_checkpoint: 是否同时更新 checkpoint
        max_retries: 最大重试次数

    Returns:
        新消息的行号，失败返回 None
    """
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    # 使用文件锁替代 threading.Lock（跨进程保护）
    lock_fd = open(_APPEND_LOCK_FILE, "a")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)  # 阻塞式独占锁
        try:
            for attempt in range(max_retries):
                try:
                    if update_checkpoint:
                        # O(1)：直接从 checkpoint 读取，不需要文件扫描
                        current_offset = _read_checkpoint()
                        if current_offset is None:
                            current_offset = get_true_line_count()
                        lines_before = current_offset
                    else:
                        # 无 checkpoint：只在首次获取行数用于返回值
                        lines_before = get_true_line_count()

                    with open(str(BRIDGE_FILE), "a", encoding='utf-8') as f:
                        f.write(line)
                        f.flush()
                        os.fsync(f.fileno())

                    # 追加写入是原子操作——写入成功即表示 lines_before+1，无需再扫文件
                    new_offset = lines_before + 1
                    if update_checkpoint:
                        _update_checkpoint(new_offset)
                    return new_offset

                except (IOError, OSError) as e:
                    if attempt < max_retries - 1:
                        delay = min(0.1 * (2 ** attempt) + random.uniform(0, 0.05), 1.0)
                        time.sleep(delay)
                    else:
                        print(f"❌ append_bridge failed after {max_retries} attempts: {e}")
                        return None

            return None
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)  # 释放锁
    finally:
        lock_fd.close()


def mark_processed(up_to_offset: int) -> None:
    """标记已处理到指定 offset"""
    _update_checkpoint(up_to_offset)


# ---------------------------------------------------------------------------
# 归档
# ---------------------------------------------------------------------------

def get_archive_dir() -> Path:
    """获取归档目录（按年月分）"""
    archive_dir = _BRIDGE_DIR / "discussions"
    now = datetime.now()
    year_month = archive_dir / f"{now.year}-{now.month:02d}"
    year_month.mkdir(parents=True, exist_ok=True)
    return year_month


def archive_old_discussions(max_size_mb: int = 10) -> None:
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
