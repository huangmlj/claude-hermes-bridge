#!/usr/bin/env python3
"""
server.py - Claude-Hermes Bridge HTTP 服务器

架构：薄薄的 HTTP 路由层，所有业务逻辑委托给 services/

职责：
- HTTP 协议处理（读取请求、发送响应）
- 路由分发
- 调用 services 层
- CORS / 速率限制

services 层（无 HTTP 依赖）：
- services/bridge.py    - WAL + Checkpoint + 锁
- services/poll.py      - 轮询进程管理
- services/discussion.py - 讨论生命周期
- services/export.py    - 导出/总结
- services/handlers.py - SSE 连接管理
"""

import http.server
import socketserver
import os
import sys
import json
import re
import logging
import subprocess
import signal
import atexit
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

# 项目根目录
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# 导入 services 层
# ---------------------------------------------------------------------------
from services.bridge import (
    load_state, save_state,
    generate_message_id,
    get_messages_since, _read_checkpoint,
    validate_and_repair_state,
    get_archive_dir,
    BRIDGE_FILE, STATE_FILE, ARCHIVE_DIR,
)
from services.discussion import (
    start_discussion, end_discussion, send_message,
    list_discussions, load_discussion, delete_discussion,
)
from services.export import export_discussion, summarize_discussion
from services.poll import (
    start_poll, stop_poll, is_poll_running, stop_all_polls,
)
from services.handlers import (
    SSEClient, register_sse_client, unregister_sse_client,
    _get_sse_observer,
)
from validators import (
    validate_json_request, validate_discussion_request,
    validate_message_data, ValidationError, sanitize_error_message,
)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
PORT = 8765
BRIDGE_FILE = BASE_DIR / "bridge.jsonl"
STATE_FILE = BASE_DIR / "state.json"
ARCHIVE_DIR = BASE_DIR / "discussions"
OUTPUT_DIR = BASE_DIR / "output"
AI_TIMEOUT = 180

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger('server')

# 速率限制配置
_rate_limit: dict = {}
_RATE_LIMIT_WINDOW = 60  # 秒
_RATE_LIMIT_MAX = 100    # 每窗口最大请求数

# 全局子进程管理（仅用于 cleanup）
_processes: dict = {}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def check_rate_limit(client_ip: str) -> bool:
    """检查客户端IP是否超过速率限制"""
    now = datetime.now().timestamp()
    if client_ip not in _rate_limit:
        _rate_limit[client_ip] = []
    _rate_limit[client_ip] = [t for t in _rate_limit[client_ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_limit[client_ip]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit[client_ip].append(now)
    return True


def cleanup_processes():
    """退出时清理子进程"""
    stop_all_polls()


def _send_json(self, data: dict, status: int = 200):
    """发送 JSON 响应"""
    self.send_response(status)
    self.send_header('Content-Type', 'application/json; charset=utf-8')
    self.end_headers()
    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def _send_error(self, code: int, message: str):
    """发送错误响应"""
    self.send_error(code, message)


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class BridgeHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP 请求处理"""

    def end_headers(self):
        # CORS
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # -------------------------------------------------------------------------
    # GET 路由
    # -------------------------------------------------------------------------
    def do_GET(self):
        try:
            if self.path == '/' or self.path == '/index.html':
                self.path = '/index.html'
                return super().do_GET()
            elif self.path == '/ui-options' or self.path == '/ui-options.html':
                self.path = '/ui-options.html'
                return super().do_GET()
            elif self.path == '/current.json' or self.path == '/messages' or self.path == '/api/messages':
                self._serve_current_discussion()
            elif self.path == '/discussions':
                self._list_discussions()
            elif self.path.startswith('/discussions/'):
                filename = unquote(self.path[len('/discussions/'):])
                self._serve_discussion_file(filename)
            elif self.path == '/api/status':
                self._serve_api_status()
            elif self.path == '/api/models':
                self._serve_models()
            elif self.path == '/api/services':
                self._serve_services_status()
            elif self.path == '/api/events':
                self._handle_sse_stream()
            elif self.path == '/themes':
                self._serve_themes()
            else:
                return super().do_GET()
        except Exception as e:
            logger.error(f"do_GET error: {e}")
            _send_error(self, 500, sanitize_error_message(e))

    # -------------------------------------------------------------------------
    # POST 路由
    # -------------------------------------------------------------------------
    def do_POST(self):
        client_ip = self.client_address[0]
        if not check_rate_limit(client_ip):
            _send_error(self, 429, 'Too Many Requests')
            return

        try:
            if self.path == '/api/discussion/start':
                self._handle_start_discussion()
            elif self.path == '/api/discussion/start-ai':
                self._handle_start_ai_conversation()
            elif self.path == '/api/discussion/end':
                self._handle_end_discussion()
            elif self.path == '/api/message':
                self._handle_send_message()
            elif self.path == '/api/discussion/list':
                self._handle_list_discussions()
            elif self.path == '/api/discussion/delete':
                self._handle_delete_discussion()
            elif self.path == '/api/services/start':
                self._handle_start_services()
            elif self.path == '/api/services/stop':
                self._handle_stop_services()
            elif self.path == '/api/services/hermes/start':
                self._handle_start_hermes()
            elif self.path == '/api/services/hermes/stop':
                self._handle_stop_hermes()
            elif self.path == '/api/services/claude/start':
                self._handle_start_claude()
            elif self.path == '/api/services/claude/stop':
                self._handle_stop_claude()
            elif self.path == '/save-selection':
                self._handle_save_selection()
            elif self.path == '/api/export':
                self._handle_export()
            elif self.path == '/api/summary':
                self._handle_summary()
            else:
                _send_error(self, 404, 'Not Found')
        except Exception as e:
            logger.error(f"do_POST error: {e}")
            _send_error(self, 500, sanitize_error_message(e))

    # -------------------------------------------------------------------------
    # SSE
    # -------------------------------------------------------------------------
    def _handle_sse_stream(self):
        """SSE 实时消息流"""
        last_event_id = self.headers.get('Last-Event-Id', self.headers.get('lastEventId', '0'))
        try:
            last_offset = int(last_event_id)
        except ValueError:
            last_offset = 0

        handler, _ = _get_sse_observer()

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        sse_client = SSEClient(self)
        register_sse_client(sse_client)

        try:
            # 追赶阶段：发送从 last_offset 之后的所有消息
            initial_messages = get_messages_since(last_offset)
            for i, msg in enumerate(initial_messages):
                msg_offset = last_offset + i + 1
                data = json.dumps(msg, ensure_ascii=False)
                self.wfile.write(f"id: {msg_offset}\ndata: {data}\n\n".encode('utf-8'))
                self.wfile.flush()

            if initial_messages:
                last_offset = last_offset + len(initial_messages)

            # 事件驱动推送
            heartbeat_count = 0
            while True:
                if sse_client.wait_for_event(timeout=25):
                    sse_client.clear_event()

                try:
                    # 心跳
                    heartbeat_count += 1
                    self.wfile.write(f": heartbeat {heartbeat_count}\n\n".encode('utf-8'))
                    self.wfile.flush()

                    # 推送新消息
                    current_offset = _read_checkpoint() or 0
                    if current_offset > last_offset:
                        new_messages = get_messages_since(last_offset)
                        for msg in new_messages:
                            last_offset += 1
                            data = json.dumps(msg, ensure_ascii=False)
                            self.wfile.write(f"id: {last_offset}\ndata: {data}\n\n".encode('utf-8'))
                            self.wfile.flush()

                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    # 客户端主动断开连接，属于正常现象，干净退出循环
                    logger.info("SSE client gracefully disconnected.")
                    break

        except Exception as e:
            logger.error(f"SSE stream encountered an unexpected error: {e}")
        finally:
            unregister_sse_client(sse_client)

    # -------------------------------------------------------------------------
    # 讨论相关
    # -------------------------------------------------------------------------
    def _handle_start_discussion(self):
        """开始新讨论"""
        data = validate_json_request(self, ['topic'])
        if data is None:
            return

        try:
            validated = validate_discussion_request(data)
        except ValidationError as e:
            _send_error(self, 400, f'Invalid discussion data: {str(e)}')
            return

        result = start_discussion(validated['topic'])
        _send_json(self, result)

    def _handle_end_discussion(self):
        """结束讨论"""
        data = validate_json_request(self) or {}
        summary = data.get('summary', '')[:5000]

        try:
            result = end_discussion(summary)
            _send_json(self, result)
        except ValueError as e:
            _send_error(self, 400, str(e))
        except Exception as e:
            _send_error(self, 500, sanitize_error_message(e))

    def _handle_send_message(self):
        """发送消息"""
        data = validate_json_request(self, ['content'])
        if data is None:
            return

        try:
            validated = validate_message_data(data)
        except ValidationError as e:
            _send_error(self, 400, f'Invalid message data: {str(e)}')
            return

        author = validated.get('author', 'user')

        try:
            result = send_message(validated['content'], author)
            _send_json(self, result)
        except ValueError as e:
            _send_error(self, 400, str(e))
        except Exception as e:
            _send_error(self, 500, sanitize_error_message(e))

    def _handle_start_ai_conversation(self):
        """启动 AI 对话"""
        state = load_state()
        if not state.get('current_discussion'):
            _send_error(self, 400, 'No active discussion')
            return

        hermes_ok = start_poll('hermes')
        claude_ok = start_poll('claude')

        state['discussion_started'] = True
        save_state(state)

        _send_json(self, {
            'success': True,
            'message': 'AI conversation started',
            'hermes': hermes_ok,
            'claude': claude_ok,
        })

    def _list_discussions(self):
        """列出讨论（GET 版本）"""
        discussions = list_discussions()
        _send_json(self, {'discussions': discussions})

    def _handle_list_discussions(self):
        """列出讨论（POST 版本）"""
        self._list_discussions()

    def _serve_discussion_file(self, filename: str):
        """加载讨论文件"""
        try:
            result = load_discussion(filename)
            _send_json(self, result)
        except FileNotFoundError as e:
            _send_error(self, 404, str(e))
        except Exception as e:
            _send_error(self, 500, sanitize_error_message(e))

    def _handle_delete_discussion(self):
        """删除讨论"""
        data = validate_json_request(self, ['filename'])
        if data is None:
            return

        try:
            result = delete_discussion(data['filename'])
            _send_json(self, result)
        except (FileNotFoundError, ValueError) as e:
            _send_error(self, 400, str(e))
        except Exception as e:
            _send_error(self, 500, sanitize_error_message(e))

    # -------------------------------------------------------------------------
    # 服务管理
    # -------------------------------------------------------------------------
    def _handle_start_services(self):
        """启动所有服务"""
        r1 = start_poll('hermes')
        r2 = start_poll('claude')
        _send_json(self, {'success': True, 'hermes': r1, 'claude': r2})

    def _handle_stop_services(self):
        """停止所有服务"""
        stop_all_polls()
        _send_json(self, {'success': True})

    def _handle_start_hermes(self):
        r = start_poll('hermes')
        _send_json(self, r)

    def _handle_stop_hermes(self):
        r = stop_poll('hermes')
        _send_json(self, r)

    def _handle_start_claude(self):
        r = start_poll('claude')
        _send_json(self, r)

    def _handle_stop_claude(self):
        r = stop_poll('claude')
        _send_json(self, r)

    def _serve_services_status(self):
        """服务状态"""
        _send_json(self, {
            'hermes': {'running': is_poll_running('hermes')},
            'claude': {'running': is_poll_running('claude')},
        })

    # -------------------------------------------------------------------------
    # 状态 & 模型
    # -------------------------------------------------------------------------
    def _serve_api_status(self):
        """返回状态信息"""
        state = load_state()

        current_lines = 0
        if BRIDGE_FILE.exists():
            with open(BRIDGE_FILE, 'r') as f:
                current_lines = sum(1 for line in f if line.strip())

        discussions_count = 0
        if ARCHIVE_DIR.exists():
            discussions_count = len(list(ARCHIVE_DIR.glob('*.json')))

        # 检查 poll 进程
        try:
            result = subprocess.run(['pgrep', '-f', 'poll.py'], capture_output=True, text=True)
            poll_running = result.returncode == 0 and bool(result.stdout.strip())
        except subprocess.SubprocessError:
            poll_running = False

        _send_json(self, {
            'online': True,
            'current_messages': current_lines,
            'current_layer': state.get('current_layer', 0),
            'current_topic': state.get('current_topic'),
            'last_write_by': state.get('last_write_by'),
            'discussions_count': discussions_count,
            'discussion_active': state.get('current_discussion') is not None,
            'discussion_started': state.get('discussion_started', False),
            'poll_running': poll_running,
            'timestamp': datetime.now().isoformat(),
        })

    def _serve_models(self):
        """返回 AI 模型名称"""
        _send_json(self, {'claude': 'Claude', 'hermes': 'Hermes'})

    # -------------------------------------------------------------------------
    # 导出 & 总结
    # -------------------------------------------------------------------------
    def _handle_export(self):
        """导出讨论"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            topic = data.get('topic', '')
            content = data.get('content', '')

            result = export_discussion(topic, content)
            _send_json(self, result)
        except Exception as e:
            _send_error(self, 500, str(e))

    def _handle_summary(self):
        """AI 总结"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            topic = data.get('topic', '')
            ai_type = data.get('ai_type', 'claude')
            messages_content = data.get('messages_content', '')

            result = summarize_discussion(topic, ai_type, messages_content)
            _send_json(self, result)
        except ValueError as e:
            _send_error(self, 400, str(e))
        except Exception as e:
            _send_error(self, 500, str(e))

    # -------------------------------------------------------------------------
    # 其他
    # -------------------------------------------------------------------------
    def _serve_current_discussion(self):
        """返回当前讨论"""
        messages = []
        if BRIDGE_FILE.exists():
            with open(BRIDGE_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        messages = messages[-50:]

        self.send_response(200)
        self.send_header('Content-Type', 'application/jsonl; charset=utf-8')
        self.end_headers()
        content = '\n'.join(json.dumps(m, ensure_ascii=False) for m in messages)
        self.wfile.write(content.encode('utf-8'))

    def _serve_themes(self):
        """主题选择页面"""
        themes = [
            ('暗境', '深色沉浸风格'),
            ('流彩', '渐变流彩风格'),
            ('暖墨', '暖色调水墨风格'),
            ('霜璃', '冷色清透风格'),
            ('素宣', '简约素雅风格'),
            ('雅韵', '典雅韵味风格'),
        ]
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>选择主题</title></head>'
        html += '<body style="font-family: sans-serif; background: #1a1a2e; color: #fff; padding: 40px;">'
        html += '<h2 style="text-align:center; margin-bottom:30px;">选择主题风格</h2>'
        html += '<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; max-width: 800px; margin: 0 auto;">'
        for theme, desc in themes:
            bg_colors = {'暗境': '#1a1a2e', '流彩': 'linear-gradient(135deg, #667eea, #764ba2)', '暖墨': '#2d2a32', '霜璃': '#e8f4f8', '素宣': '#f5f5f0', '雅韵': '#2c1810'}
            text_colors = {'暗境': '#fff', '流彩': '#fff', '暖墨': '#e8d5c4', '霜璃': '#2a6496', '素宣': '#333', '雅韵': '#d4a574'}
            html += f'<a href="/?theme={theme}" style="display: block; background: {bg_colors.get(theme)}; color: {text_colors.get(theme)}; padding: 30px 20px; border-radius: 15px; text-decoration: none; text-align: center; font-size: 18px;">'
            html += f'<div style="font-size: 32px; margin-bottom: 10px;"></div>'
            html += f'<div style="font-weight: bold; margin-bottom: 5px;">{theme}</div>'
            html += f'<div style="font-size: 12px; opacity: 0.8;">{desc}</div></a>'
        html += '</div><div style="text-align:center; margin-top:30px;"><a href="/index.html" style="color:#888;">← 返回主页面</a></div></body></html>'

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _handle_save_selection(self):
        """保存 UI 选择"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            json.loads(self.rfile.read(content_length).decode('utf-8'))
            _send_json(self, {'success': True})
        except Exception as e:
            _send_error(self, 500, str(e))

    def log_message(self, format, *args):
        logger.info(format % args)


# ---------------------------------------------------------------------------
# 服务器启动
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    # 校验 bridge 状态
    ok, msg = validate_and_repair_state()
    logger.info(f"Bridge state: {msg}")

    # 启动服务器
    server = ThreadedHTTPServer(('0.0.0.0', PORT), BridgeHTTPHandler)
    logger.info(f"Server running on http://localhost:{PORT}")

    # 注册清理
    atexit.register(cleanup_processes)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *a: sys.exit(0))

    server.serve_forever()


if __name__ == '__main__':
    main()
