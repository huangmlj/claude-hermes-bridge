#!/usr/bin/env python3
"""
handlers.py - SSE 客户端连接管理

职责：
- SSEEventHandler: watchdog 文件变化通知
- SSEClient: 单个 SSE 连接封装
- _get_sse_observer: 全局 SSE 观察者（单例）
"""

import threading
import time
from pathlib import Path
from typing import Optional, List
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 项目根目录
_BRIDGE_DIR = Path(__file__).parent.parent


class SSEEventHandler(FileSystemEventHandler):
    """SSE 事件处理器 - bridge.jsonl 文件变化时通知所有等待的客户端"""

    def __init__(self):
        super().__init__()
        self._clients: List = []
        self._lock = threading.Lock()

    def register_client(self, client) -> None:
        with self._lock:
            self._clients.append(client)

    def unregister_client(self, client) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def on_modified(self, event) -> None:
        if not event.src_path.endswith("bridge.jsonl"):
            return
        self._notify_clients()

    def on_created(self, event) -> None:
        if not event.src_path.endswith("bridge.jsonl"):
            return
        self._notify_clients()

    def _notify_clients(self) -> None:
        with self._lock:
            for client in self._clients:
                client.notify()


class SSEClient:
    """SSE 客户端连接封装"""

    def __init__(self, handler):
        self._handler = handler
        self._event = threading.Event()

    def wait_for_event(self, timeout: float = 60) -> bool:
        """等待文件变化事件"""
        return self._event.wait(timeout=timeout)

    def clear_event(self) -> None:
        """清除事件标志"""
        self._event.clear()

    def notify(self) -> None:
        """通知客户端"""
        self._event.set()


# 全局 SSE 观察者（单例）
_sse_observer: Optional[Observer] = None
_sse_handler: Optional[SSEEventHandler] = None
_observer_lock = threading.Lock()


def _get_sse_observer() -> tuple[SSEEventHandler, Observer]:
    """获取或创建全局 SSE 观察者

    Returns:
        (handler, observer): SSE 事件处理器和观察者
    """
    global _sse_observer, _sse_handler

    with _observer_lock:
        if _sse_handler is None:
            _sse_handler = SSEEventHandler()
            _sse_observer = Observer()
            _sse_observer.schedule(_sse_handler, str(_BRIDGE_DIR), recursive=False)
            _sse_observer.start()

        return _sse_handler, _sse_observer


def register_sse_client(client: SSEClient) -> None:
    """注册 SSE 客户端"""
    handler, _ = _get_sse_observer()
    handler.register_client(client)


def unregister_sse_client(client: SSEClient) -> None:
    """注销 SSE 客户端"""
    if _sse_handler:
        _sse_handler.unregister_client(client)
