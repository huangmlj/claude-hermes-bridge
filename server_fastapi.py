#!/usr/bin/env python3
"""
server_fastapi.py - FastAPI 重构版本

基于原有 server.py 重写为 ASGI + FastAPI 架构：
- 路由层全面拥抱 FastAPI 装饰器
- SSE 改为 sse-starlette 异步生成器，彻底解决线程瓶颈
- Pydantic Schemas 替代手动 JSON 校验
- CORS/生命周期/限速全部中间件化

业务逻辑层（services/）完全不动。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import fcntl
import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
BRIDGE_FILE = BASE_DIR / "bridge.jsonl"
STATE_FILE = BASE_DIR / "state.json"
OUTPUT_DIR = BASE_DIR / "output"
DISCUSSIONS_DIR = BASE_DIR / "discussions"

PORT = int(os.environ.get("BRIDGE_PORT", "8765"))

# API 认证配置（可选）
API_KEY = os.environ.get("BRIDGE_API_KEY")
# 不需要认证的路径（通配符匹配）
_AUTH_EXEMPT_PATHS = {
    "/",
    "/index.html",
    "/ui-options",
    "/ui-options.html",
    "/themes",
    "/api/events",  # SSE 连接
    "/api/status",  # 健康检查
    "/api/models",  # 模型信息
    "/static/",
}

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("bridge")

# ---------------------------------------------------------------------------
# 业务逻辑层导入（同步模块，原有 services/ 保持不动）
# ---------------------------------------------------------------------------
sys.path.insert(0, str(BASE_DIR))

from services.bridge import (
    load_state,
    save_state,
    append_bridge,
    mark_processed,
    _read_checkpoint,
    get_true_line_count,
    get_messages_since,
    get_last_entry,
    validate_and_repair_state,
    generate_message_id,
    acquire_processing_lock,
    release_processing_lock,
    get_archive_dir,
)
from services.poll import (
    start_poll,
    stop_poll,
    stop_all_polls,
    is_poll_running,
)
from services.discussion import (
    start_discussion as svc_start_discussion,
    end_discussion as svc_end_discussion,
    send_message as svc_send_message,
    list_discussions as svc_list_discussions,
    load_discussion as svc_load_discussion,
    delete_discussion as svc_delete_discussion,
)
from services.export import (
    export_discussion as svc_export_discussion,
    summarize_discussion as svc_summarize_discussion,
)

# ---------------------------------------------------------------------------
# Pydantic Schemas（替换手动 JSON 校验）
# ---------------------------------------------------------------------------


class DiscussionStartRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1)
    author: str = Field(default="user")

    @field_validator("author")
    @classmethod
    def validate_author(cls, v: str) -> str:
        allowed = {"user", "hermes", "claude"}
        if v not in allowed:
            raise ValueError(f"author must be one of {allowed}")
        return v


class DeleteDiscussionRequest(BaseModel):
    filename: str = Field(..., min_length=1)


class ExportRequest(BaseModel):
    topic: str = Field(...)
    content: str = Field(...)


class SummaryRequest(BaseModel):
    topic: str = Field(...)
    ai_type: str = Field(...)

    @field_validator("ai_type")
    @classmethod
    def validate_ai_type(cls, v: str) -> str:
        allowed = {"claude", "hermes"}
        if v not in allowed:
            raise ValueError(f"ai_type must be one of {allowed}")
        return v

    messages_content: str = Field(...)


class DiscussionEndRequest(BaseModel):
    summary: Optional[str] = None


# ---------------------------------------------------------------------------
# 限速中间件（asyncio.Lock 保护，应对异步并发）
# ---------------------------------------------------------------------------
_rate_limit: Dict[str, List[float]] = {}
_rate_lock = asyncio.Lock()
RATE_WINDOW = 60.0
RATE_MAX = 100


async def check_rate_limit(request: Request) -> bool:
    """异步限速检查"""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    async with _rate_lock:
        if client_ip not in _rate_limit:
            _rate_limit[client_ip] = []

        # 清理过期记录
        _rate_limit[client_ip] = [
            t for t in _rate_limit[client_ip] if now - t < RATE_WINDOW
        ]

        # 列表为空时释放字典内存，防止无限膨胀
        if not _rate_limit[client_ip]:
            del _rate_limit[client_ip]
            return True

        if len(_rate_limit[client_ip]) >= RATE_MAX:
            return False

        _rate_limit[client_ip].append(now)
        return True


# ---------------------------------------------------------------------------
# SSE 全局异步事件（替代 threading.Event 的 watchdog 通知机制）
# ---------------------------------------------------------------------------

# 全局 asyncio.Event：watchdog 检测到文件变化时设置，所有 SSE 连接共享
_file_changed_event: Optional[asyncio.Event] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None  # 保存主线程 Event Loop（跨线程安全访问）
_watchdog_started = False

# 发布-订阅：每个 SSE 客户端独立的通知队列（替代共享 Event，避免惊群效应）
_clients: List[asyncio.Queue] = []


def _on_bridge_file_changed() -> None:
    """watchdog 回调：向所有 SSE 协程广播（发布-订阅模式）"""
    global _file_changed_event, _main_loop, _clients
    if _main_loop is not None and not _main_loop.is_closed():
        for q in _clients:
            _main_loop.call_soon_threadsafe(q.put_nowait, True)


class _WatchdogHandler:
    """转发 watchdog 事件到 asyncio.Event"""

    def on_modified(self, event):
        if event.src_path.endswith("bridge.jsonl"):
            _on_bridge_file_changed()

    def on_created(self, event):
        if event.src_path.endswith("bridge.jsonl"):
            _on_bridge_file_changed()


def _start_watchdog() -> None:
    """在独立 daemon 线程中启动 watchdog Observer"""
    global _watchdog_started
    if _watchdog_started:
        return

    from watchdog.observers import Observer

    observer = Observer()
    handler = _WatchdogHandler()
    observer.schedule(handler, str(BASE_DIR), recursive=False)
    observer.daemon = True
    observer.start()
    _watchdog_started = True
    logger.info("Watchdog Observer started (daemon thread)")


# ---------------------------------------------------------------------------
# SSE 异步生成器
# ---------------------------------------------------------------------------


async def sse_event_generator(request: Request):
    """SSE 异步生成器：替代原来的 _handle_sse_stream + SSEClient 线程模型"""
    global _clients

    # 获取客户端 last_event_id
    last_event_id = request.headers.get("Last-Event-Id", "0")
    try:
        last_offset = int(last_event_id)
    except ValueError:
        last_offset = 0

    # 确保 watchdog 已启动
    if not _watchdog_started:
        _start_watchdog()

    # 为当前客户端创建独立的通知队列（发布-订阅）
    client_queue: asyncio.Queue = asyncio.Queue()
    _clients.append(client_queue)

    # 追赶阶段：发送从 last_offset 之后的所有消息
    messages = await asyncio.to_thread(get_messages_since, last_offset)
    for i, msg in enumerate(messages):
        msg_offset = last_offset + i + 1
        yield {
            "event": "message",
            "id": str(msg_offset),
            "data": json.dumps(msg, ensure_ascii=False),
        }
    if messages:
        last_offset = last_offset + len(messages)

    heartbeat_count = 0

    try:
        while True:
            # 等待自己的队列收到通知（25秒超时）
            try:
                await asyncio.wait_for(client_queue.get(), timeout=25)
                # 清空队列中可能堆积的多余通知（防抖）
                while not client_queue.empty():
                    client_queue.get_nowait()
            except asyncio.TimeoutError:
                pass  # 超时，继续发心跳

            # 心跳
            heartbeat_count += 1
            yield {"event": "comment", "data": f": heartbeat {heartbeat_count}"}

            # 检查连接是否断开
            if await request.is_disconnected():
                logger.info("SSE client disconnected")
                break

            # 推送新消息（通过 checkpoint 判断）
            current_offset = await asyncio.to_thread(_read_checkpoint) or 0
            if current_offset > last_offset:
                new_messages = await asyncio.to_thread(get_messages_since, last_offset)
                for msg in new_messages:
                    last_offset += 1
                    yield {
                        "event": "message",
                        "id": str(last_offset),
                        "data": json.dumps(msg, ensure_ascii=False),
                    }

    except asyncio.CancelledError:
        logger.debug("SSE generator cancelled")
    finally:
        # 客户端断开时，从全局列表中移除自己的队列
        if client_queue in _clients:
            _clients.remove(client_queue)


# ---------------------------------------------------------------------------
# FastAPI 生命周期
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：启动时校验状态，关闭时清理进程"""
    # 启动时
    logger.info("Validating bridge state...")
    ok, msg = await asyncio.to_thread(validate_and_repair_state)
    logger.info(f"Bridge state: {msg}")

    # 启动 watchdog
    _start_watchdog()

    # 初始化全局 SSE 事件，并捕获主事件循环供 watchdog 线程回调使用
    global _file_changed_event, _main_loop
    _main_loop = asyncio.get_running_loop()
    _file_changed_event = asyncio.Event()

    # 注册信号处理
    loop = asyncio.get_event_loop()

    def graceful_shutdown(*args):
        logger.info("Received shutdown signal, cleaning up...")
        stop_all_polls()
        sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, graceful_shutdown)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            signal.signal(sig, graceful_shutdown)

    yield

    # 关闭时
    logger.info("Shutting down...")
    await asyncio.to_thread(stop_all_polls)


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(title="Claude-Hermes Bridge", lifespan=lifespan)

# CORS 中间件（替代原来的手动 end_headers）
# 生产环境应通过 CORS_ORIGINS 环境变量配置白名单，不用 "*"
_cors_origins = os.environ.get("CORS_ORIGINS", "").split(",") if os.environ.get("CORS_ORIGINS") else []
if not _cors_origins:
    # 默认仅允许同源请求，拒绝 wildcard
    _cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else ["http://localhost:5173", "http://localhost:8765"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# API 认证中间件
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件（可选启用）"""

    async def dispatch(self, request: Request, call_next):
        # 如果未配置 API_KEY，跳过认证
        if not API_KEY:
            return await call_next(request)

        # 检查路径是否豁免认证
        path = request.url.path
        for exempt in _AUTH_EXEMPT_PATHS:
            if path == exempt or path.startswith(exempt):
                return await call_next(request)

        # 检查 Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                content={"error": "Missing or invalid Authorization header", "success": False},
                status_code=401
            )

        token = auth_header[7:]  # 移除 "Bearer " 前缀
        if token != API_KEY:
            return JSONResponse(
                content={"error": "Invalid API key", "success": False},
                status_code=403
            )

        return await call_next(request)


# 添加认证中间件
app.add_middleware(AuthMiddleware)

# ---------------------------------------------------------------------------
# 辅助函数（async wrappers 包装同步 services）
# ---------------------------------------------------------------------------


def _json_response(data: Dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status)


def _error_response(message: str, status: int = 400) -> JSONResponse:
    # 清理敏感信息
    clean = re.sub(r"sk-[a-zA-Z0-9]+", "[API_KEY]", message)
    clean = re.sub(r"/[^\s]+", "[PATH]", clean)
    return JSONResponse(content={"error": clean, "success": False}, status_code=status)


# ---------------------------------------------------------------------------
# SSE 端点（最关键的重构点）
# ---------------------------------------------------------------------------


@app.get("/api/events")
async def events_endpoint(request: Request):
    """SSE 实时消息流 - 异步生成器，无线程阻塞"""

    async def generator(request: Request):
        try:
            async for event in sse_event_generator(request):
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            pass

    return EventSourceResponse(
        generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# 讨论相关路由
# ---------------------------------------------------------------------------


@app.post("/api/discussion/start")
async def discussion_start(req: DiscussionStartRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    topic = req.topic.strip()
    if not topic:
        return _error_response("Topic cannot be empty")

    try:
        result = await asyncio.to_thread(svc_start_discussion, topic)
        return _json_response(result)
    except Exception as e:
        logger.error(f"start_discussion error: {e}")
        return _error_response(str(e), 500)


@app.post("/api/discussion/start-ai")
async def discussion_start_ai(req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    state = await asyncio.to_thread(load_state)
    if not state.get("current_discussion"):
        return _error_response("No active discussion", 400)

    state["discussion_started"] = True
    await asyncio.to_thread(save_state, state)

    hermes_ok = await asyncio.to_thread(start_poll, "hermes")
    claude_ok = await asyncio.to_thread(start_poll, "claude")

    return _json_response({
        "success": True,
        "message": "AI conversation started",
        "hermes": hermes_ok,
        "claude": claude_ok,
    })


@app.post("/api/discussion/end")
async def discussion_end(req: DiscussionEndRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    summary = req.summary
    try:
        result = await asyncio.to_thread(svc_end_discussion, summary)
        return _json_response(result)
    except Exception as e:
        logger.error(f"end_discussion error: {e}")
        return _error_response(str(e), 500)


@app.post("/api/message")
async def send_message(req: MessageRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    content = req.content.strip()
    author = req.author or "user"

    if not content:
        return _error_response("Content cannot be empty")

    try:
        result = await asyncio.to_thread(svc_send_message, content, author)
        return _json_response(result)
    except Exception as e:
        logger.error(f"send_message error: {e}")
        return _error_response(str(e), 500)


@app.post("/api/discussion/list")
async def discussion_list(req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    result = await asyncio.to_thread(svc_list_discussions)
    return _json_response({"discussions": result})


@app.get("/api/discussion/list")
async def discussion_list_get(req_ctx: Request):
    result = await asyncio.to_thread(svc_list_discussions)
    return _json_response({"discussions": result})


@app.get("/discussions/{filename}")
async def load_discussion(filename: str, req_ctx: Request):
    # 防御性 URL 解码
    from urllib.parse import unquote
    filename = unquote(filename)

    result = await asyncio.to_thread(svc_load_discussion, filename)
    if result is None:
        return _error_response("Discussion not found", 404)
    return _json_response(result)


@app.post("/api/discussion/delete")
async def discussion_delete(req: DeleteDiscussionRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    filename = req.filename.strip()
    if not filename:
        return _error_response("Filename cannot be empty")

    try:
        result = await asyncio.to_thread(svc_delete_discussion, filename)
        return _json_response(result)
    except Exception as e:
        logger.error(f"delete_discussion error: {e}")
        return _error_response(str(e), 500)


# ---------------------------------------------------------------------------
# 消息历史
# ---------------------------------------------------------------------------


@app.get("/messages")
async def current_discussion(req_ctx: Request):
    """返回当前讨论最近50条消息"""
    messages = await asyncio.to_thread(get_messages_since, 0)
    # 返回最近50条
    recent = messages[-50:] if len(messages) > 50 else messages
    return Response(
        content="\n".join(json.dumps(m, ensure_ascii=False) for m in recent),
        media_type="application/json",
    )


@app.get("/current.json")
async def current_json(req_ctx: Request):
    messages = await asyncio.to_thread(get_messages_since, 0)
    recent = messages[-50:] if len(messages) > 50 else messages
    return JSONResponse(content={"messages": recent})


# ---------------------------------------------------------------------------
# 服务管理
# ---------------------------------------------------------------------------


@app.post("/api/services/start")
async def services_start(req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    h = await asyncio.to_thread(start_poll, "hermes")
    c = await asyncio.to_thread(start_poll, "claude")
    return _json_response({"success": True, "hermes": h, "claude": c})


@app.post("/api/services/stop")
async def services_stop(req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    await asyncio.to_thread(stop_all_polls)
    return _json_response({"success": True})


@app.post("/api/services/hermes/start")
async def hermes_start(req_ctx: Request):
    ok = await asyncio.to_thread(start_poll, "hermes")
    return _json_response({"success": ok, "running": ok})


@app.post("/api/services/hermes/stop")
async def hermes_stop(req_ctx: Request):
    await asyncio.to_thread(stop_poll, "hermes")
    running = await asyncio.to_thread(is_poll_running, "hermes")
    return _json_response({"success": True, "running": running})


@app.post("/api/services/claude/start")
async def claude_start(req_ctx: Request):
    ok = await asyncio.to_thread(start_poll, "claude")
    return _json_response({"success": ok, "running": ok})


@app.post("/api/services/claude/stop")
async def claude_stop(req_ctx: Request):
    await asyncio.to_thread(stop_poll, "claude")
    running = await asyncio.to_thread(is_poll_running, "claude")
    return _json_response({"success": True, "running": running})


@app.get("/api/services")
async def services_status():
    hermes_running = await asyncio.to_thread(is_poll_running, "hermes")
    claude_running = await asyncio.to_thread(is_poll_running, "claude")
    return JSONResponse(content={
        "hermes": {"running": hermes_running},
        "claude": {"running": claude_running},
    })


# ---------------------------------------------------------------------------
# 状态与模型信息
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status():
    state = await asyncio.to_thread(load_state)
    offset = await asyncio.to_thread(_read_checkpoint) or 0
    line_count = await asyncio.to_thread(get_true_line_count)
    hermes_running = await asyncio.to_thread(is_poll_running, "hermes")
    claude_running = await asyncio.to_thread(is_poll_running, "claude")

    return _json_response({
        "online": True,
        "current_layer": state.get("current_layer", 0),
        "current_topic": state.get("current_topic", ""),
        "last_write_by": state.get("last_write_by", ""),
        "discussion_started": state.get("discussion_started", False),
        "offset": offset,
        "line_count": line_count,
        "poll_running": hermes_running or claude_running,
        "hermes_running": hermes_running,
        "claude_running": claude_running,
    })


@app.get("/api/models")
async def models():
    return JSONResponse(content={
        "claude": os.environ.get("AI_NAME_CLAUDE", "Claude"),
        "hermes": os.environ.get("AI_NAME_HERMES", "Hermes"),
    })


# ---------------------------------------------------------------------------
# 导出与总结
# ---------------------------------------------------------------------------


@app.post("/api/export")
async def export_content(req: ExportRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    result = await asyncio.to_thread(svc_export_discussion, req.topic, req.content)
    return _json_response(result)


@app.post("/api/summary")
async def summarize_content(req: SummaryRequest, req_ctx: Request):
    if not await check_rate_limit(req_ctx):
        return _error_response("Too Many Requests", 429)

    result = await asyncio.to_thread(
        svc_summarize_discussion, req.topic, req.ai_type, req.messages_content
    )
    return _json_response(result)


# ---------------------------------------------------------------------------
# 主题选择（HTML）
# ---------------------------------------------------------------------------


def _build_themes_html() -> str:
    """构建主题选择页面 HTML"""
    themes = [
        ("#0a0a0f", "#1e1e2e", "Midnight Dark"),
        ("#1a1a2e", "#16213e", "Deep Ocean"),
        ("#0d1117", "#161b22", "GitHub Dark"),
        ("#1a0a2e", "#2d1b4e", "Royal Purple"),
        ("#0a1628", "#0f3460", "Midnight Blue"),
        ("#2d3436", "#636e72", "Charcoal Grey"),
    ]
    options = "".join(
        f'<option value="{bg}|{accent}">{name}</option>'
        for bg, accent, name in themes
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Theme</title>
<style>
body{{font-family:system-ui;background:#0a0a0f;color:#e0e0e0;padding:2rem}}
h2{{color:#8b5cf6}}
select{{width:100%;padding:.75rem;background:#1e1e2e;color:#fff;border:1px solid #333;border-radius:8px;margin:1rem 0}}
button{{background:#8b5cf6;color:#fff;border:none;padding:.75rem 2rem;border-radius:8px;cursor:pointer;font-size:1rem}}
button:hover{{background:#7c3aed}}
.current{{background:#1e1e2e;padding:1rem;border-radius:8px;margin-top:1rem}}
</style></head><body>
<h2>🎨 选择主题颜色</h2>
<select id="theme">
<option value="">-- 选择主题 --</option>
{options}
</select>
<button onclick="apply()">应用</button>
<div class="current" id="preview"></div>
<script>
function apply(){{
  const v=document.getElementById('theme').value;
  if(!v)return;
  const[bg,accent]=v.split('|');
  localStorage.setItem('chat_theme',JSON.stringify({{bg,accent}}));
  document.getElementById('preview').textContent='已应用: '+v;
}}
</script></body></html>"""


@app.get("/themes")
async def themes():
    return HTMLResponse(content=_build_themes_html())


@app.post("/save-selection")
async def save_selection(req: Request, req_ctx: Request):
    """保存 UI 选择（主题等）"""
    try:
        body = await req.json()
        # 简单存储到 state.json（扩展用）
        state = await asyncio.to_thread(load_state)
        state.setdefault("ui_selections", {}).update(body)
        await asyncio.to_thread(save_state, state)
        return _json_response({"success": True})
    except Exception as e:
        logger.error(f"save_selection error: {e}")
        return _error_response(str(e), 500)


# ---------------------------------------------------------------------------
# 静态文件（前端）
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "index.html"))


@app.get("/index.html")
async def index_html():
    return FileResponse(str(BASE_DIR / "index.html"))


@app.get("/ui-options")
async def ui_options():
    return FileResponse(str(BASE_DIR / "ui-options.html"))


@app.get("/ui-options.html")
async def ui_options_html():
    return FileResponse(str(BASE_DIR / "ui-options.html"))


# ---------------------------------------------------------------------------
# 启动入口（开发用：uvicorn server_fastapi:app --reload --port 8765）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server_fastapi:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )
