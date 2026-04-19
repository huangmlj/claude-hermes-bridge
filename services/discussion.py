#!/usr/bin/env python3
"""
discussion.py - 讨论生命周期管理服务

职责：
- 创建新讨论（写入 archive + 初始化 state + 追加首条消息到 bridge.jsonl）
- 结束讨论（归档到 discussions/）
- 列出/删除讨论
- 加载讨论历史
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# 项目根目录
_BRIDGE_DIR = Path(__file__).parent.parent

import sys
sys.path.insert(0, str(_BRIDGE_DIR))

from services.bridge import (
    load_state, save_state,
    append_bridge, mark_processed,
    _update_checkpoint,
    generate_message_id as _generate_message_id,
    get_archive_dir,
)
from services.poll import stop_poll

ARCHIVE_DIR = _BRIDGE_DIR / "discussions"
BRIDGE_FILE = _BRIDGE_DIR / "bridge.jsonl"
STATE_FILE = _BRIDGE_DIR / "state.json"

# 确保 archive 目录存在
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 讨论创建
# ---------------------------------------------------------------------------

def start_discussion(topic: str) -> Dict[str, Any]:
    """开始新讨论

    1. 在 archive 目录创建讨论文件
    2. 初始化 state.json
    3. 写入首条用户消息到 bridge.jsonl

    Args:
        topic: 讨论话题

    Returns:
        dict: {success, filename, filepath, topic}
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # 生成安全的文件名
    safe_topic = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in topic[:20])
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{safe_topic}-{timestamp}.json"
    filepath = ARCHIVE_DIR / filename

    discussion = {
        'topic': topic,
        'started_at': datetime.now().isoformat(),
        'ended_at': None,
        'messages': [],
        'summary': None
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(discussion, f, ensure_ascii=False, indent=2)

    # 初始化 state
    state = {
        'current_discussion': filename,
        'current_topic': topic,
        'current_layer': 0,
        'last_write_by': 'user',
        'claude_last_read': 0,
        'hermes_last_read': 0,
        'bridge_line_count': 0,
        'discussion_id': timestamp,
        'discussion_started': False,
    }

    # 写入首条消息
    layer = 1
    timestamp_iso = datetime.now().isoformat()
    entry = {
        'layer': layer,
        'author': 'user',
        'content': topic,
        'timestamp': timestamp_iso,
        'id': _generate_message_id('user', topic, timestamp_iso)
    }

    new_offset = append_bridge(entry, update_checkpoint=True)
    if new_offset:
        mark_processed(new_offset)

    state['current_layer'] = layer
    state['bridge_line_count'] = new_offset if new_offset else 1

    save_state(state)

    return {
        'success': True,
        'filename': filename,
        'filepath': str(filepath),
        'topic': topic
    }


# ---------------------------------------------------------------------------
# 讨论结束 & 归档
# ---------------------------------------------------------------------------

def end_discussion(summary: str = "") -> Dict[str, Any]:
    """结束当前讨论并归档

    1. 停止轮询服务
    2. 从 bridge.jsonl 读取所有消息
    3. 写入 archive 文件
    4. 清空 bridge.jsonl 并重置 checkpoint
    5. 重置 state.json

    Args:
        summary: 可选的讨论总结

    Returns:
        dict: {success, archived, message_count}
    """
    # 限制 summary 长度
    if len(summary) > 5000:
        summary = summary[:5000]

    state = load_state()

    filename = state.get('current_discussion')
    if not filename:
        raise ValueError("No active discussion")

    # 停止轮询进程（使用精确 PID）
    stop_poll('hermes')
    stop_poll('claude')

    # 读取消息
    messages = []
    if BRIDGE_FILE.exists():
        with open(BRIDGE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    archived = False
    if messages:
        filepath = ARCHIVE_DIR / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                discussion = json.load(f)
        else:
            discussion = {'topic': state.get('current_topic', '未知主题'), 'started_at': datetime.now().isoformat()}

        discussion['ended_at'] = datetime.now().isoformat()
        discussion['messages'] = messages
        if summary:
            discussion['summary'] = summary

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(discussion, f, ensure_ascii=False, indent=2)
        archived = True

    # 清空 bridge.jsonl 并重置 checkpoint
    if BRIDGE_FILE.exists():
        open(BRIDGE_FILE, 'w').close()
    _update_checkpoint(0)

    # 重置 state
    new_state = {
        'current_discussion': None,
        'current_topic': None,
        'current_layer': 0,
        'last_write_by': None,
        'claude_last_read': 0,
        'hermes_last_read': 0,
        'bridge_line_count': 0,
        'discussion_id': None,
        'discussion_started': False,
    }
    save_state(new_state)

    return {
        'success': True,
        'archived': archived,
        'message_count': len(messages)
    }


# ---------------------------------------------------------------------------
# 消息发送
# ---------------------------------------------------------------------------

def send_message(content: str, author: str = "user") -> Dict[str, Any]:
    """发送消息（追加到 bridge.jsonl）

    Args:
        content: 消息内容
        author: 作者（默认为 user）

    Returns:
        dict: {success, entry}

    Raises:
        ValueError: 无活跃讨论
    """
    state = load_state()
    if not state.get('current_discussion'):
        raise ValueError("No active discussion")

    layer = state.get('current_layer', 0) + 1
    timestamp = datetime.now().isoformat()
    entry = {
        'layer': layer,
        'author': author,
        'content': content,
        'timestamp': timestamp,
        'id': _generate_message_id(author, content, timestamp)
    }

    new_offset = append_bridge(entry, update_checkpoint=True)
    if new_offset:
        mark_processed(new_offset)
        current_state = load_state()
        current_state['bridge_line_count'] = new_offset
        save_state(current_state)

    return {'success': True, 'entry': entry}


# ---------------------------------------------------------------------------
# 讨论列表
# ---------------------------------------------------------------------------

def list_discussions() -> List[Dict[str, Any]]:
    """列出所有已保存的讨论

    Returns:
        list: 讨论列表（按修改时间倒序）
    """
    discussions = []

    for filepath in ARCHIVE_DIR.glob("**/*.json"):
        try:
            stat = filepath.stat()
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            messages = data.get('messages', [])
            preview = ""
            if messages:
                preview = messages[-1].get('content', '')[:100]

            # 构建 sort_key = 修改时间（用于排序）
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

            discussions.append({
                'filename': filepath.name,
                'topic': data.get('topic', '未知话题'),
                'message_count': len(messages),
                'started_at': data.get('started_at', ''),
                'ended_at': data.get('ended_at'),
                'preview': preview,
                'size': stat.st_size,
                'modified': modified,
                'sort_key': modified,
                'duration_seconds': _calc_duration(data),
            })
        except (json.JSONDecodeError, IOError, OSError):
            continue

    # 按修改时间倒序
    discussions.sort(key=lambda d: d.get('sort_key', ''), reverse=True)
    return discussions


def _calc_duration(data: Dict) -> int:
    """计算讨论持续时间（秒）"""
    try:
        started = data.get('started_at', '')
        ended = data.get('ended_at', '')
        if started and ended:
            start_dt = datetime.fromisoformat(started)
            end_dt = datetime.fromisoformat(ended)
            return int((end_dt - start_dt).total_seconds())
    except (ValueError, TypeError):
        pass
    return 0


# ---------------------------------------------------------------------------
# 加载讨论
# ---------------------------------------------------------------------------

def _safe_filename(filename: str) -> str:
    """严格校验文件名，防止路径遍历攻击"""
    # 只允许字母、数字、短横线、下划线、点和空格
    safe = ''.join(c for c in filename if c.isalnum() or c in '.-_ ')
    if not safe or safe != filename:
        raise ValueError(f"Invalid filename: {filename}")
    return safe


def load_discussion(filename: str) -> Dict[str, Any]:
    """加载讨论文件并更新后端状态

    Args:
        filename: 讨论文件名

    Returns:
        dict: {topic, messages, started_at, ended_at}
    """
    safe_name = _safe_filename(filename)
    filepath = ARCHIVE_DIR / safe_name

    # 二次验证：确保解析后的路径仍在 ARCHIVE_DIR 内（防御符号链接攻击）
    if not filepath.exists():
        raise FileNotFoundError(f"Discussion file not found: {filename}")
    if not filepath.is_file():
        raise ValueError(f"Not a file: {filename}")

    # 使用 realpath 验证最终路径仍在 ARCHIVE_DIR 内
    if not filepath.resolve().parent == ARCHIVE_DIR.resolve():
        raise ValueError(f"Access denied: path outside discussions directory")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])

    # 更新后端状态（用于继续 AI 讨论）
    state = {
        'current_discussion': filename,
        'current_topic': data.get('topic', '未知话题'),
        'current_layer': messages[-1].get('layer', 0) if messages else 0,
        'last_write_by': messages[-1].get('author') if messages else None,
        'claude_last_read': len(messages),
        'hermes_last_read': len(messages),
        'bridge_line_count': 0,
        'discussion_id': filepath.stem,
        'discussion_started': False,
    }

    # 将历史消息写入 bridge.jsonl（用于 AI 继续讨论）
    if BRIDGE_FILE.exists():
        open(BRIDGE_FILE, 'w').close()
    _update_checkpoint(0)

    for msg in messages:
        append_bridge(msg, update_checkpoint=True)

    if messages:
        mark_processed(len(messages))

    state['bridge_line_count'] = len(messages)
    save_state(state)

    return {
        'topic': data.get('topic', '未知话题'),
        'messages': messages,
        'started_at': data.get('started_at', ''),
        'ended_at': data.get('ended_at'),
    }


# ---------------------------------------------------------------------------
# 删除讨论
# ---------------------------------------------------------------------------

def delete_discussion(filename: str) -> Dict[str, Any]:
    """删除讨论文件

    Args:
        filename: 讨论文件名

    Returns:
        dict: {success, filename}
    """
    # 验证文件名
    safe_name = ''.join(c for c in filename if c.isalnum() or c in '.-_')
    if not safe_name or safe_name != filename:
        raise ValueError(f"Invalid filename: {filename}")

    filepath = ARCHIVE_DIR / safe_name

    # 二次验证：确保解析后的路径仍在 ARCHIVE_DIR 内
    if not filepath.exists():
        raise FileNotFoundError(f"Discussion not found: {filename}")
    if not filepath.is_file():
        raise ValueError(f"Not a file: {filename}")
    if not filepath.resolve().parent == ARCHIVE_DIR.resolve():
        raise ValueError(f"Access denied: path outside discussions directory")

    # 不允许删除当前活跃讨论
    state = load_state()
    if state.get('current_discussion') == filepath.name:
        raise ValueError("Cannot delete active discussion")

    filepath.unlink()
    return {'success': True, 'filename': filepath.name}
