#!/usr/bin/env python3
"""
HTTP Server for Claude-Hermes Bridge
- 每个讨论保存为独立 JSON 文件
- 提供 Web UI 和 API
- 管理后台服务进程
"""

import http.server
import socketserver
import os
import sys
import json
import re
import subprocess
import signal
import atexit
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

PORT = 8765
BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = BASE_DIR / "state.json"
BRIDGE_FILE = BASE_DIR / "bridge.jsonl"
ARCHIVE_DIR = BASE_DIR / "discussions"

# 加载 .env 配置
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    # 如果没有 python-dotenv，手动加载
    env_file = BASE_DIR / '.env'
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

# 导入 bridge_core
sys.path.insert(0, str(BASE_DIR))
try:
    from bridge_core import (
        load_state, save_state, get_true_line_count, append_bridge,
        acquire_processing_lock, release_processing_lock, is_processing_locked,
        validate_and_repair_state, mark_processed, get_messages_since,
        _read_checkpoint, _update_checkpoint
    )
    from validators import validate_message_data, validate_discussion_request, validate_json_request, ValidationError, sanitize_error_message
except ImportError as e:
    # 导入失败时记录严重日志后立即终止进程，绝不允许带安全降级的静默启动
    import sys as _sys
    _sys.stderr.write(f"FATAL: Failed to import required modules: {e}\n")
    _sys.stderr.write("Cannot start server with reduced security. Please install dependencies.\n")
    _sys.exit(1)

# 安全配置
ALLOWED_ORIGINS = [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "https://localhost:8765",
    "https://127.0.0.1:8765"
]

# 后台进程管理
processes = {
    'hermes_poll': None,
    'claude_poll': None
}


def cleanup_processes():
    """退出时清理子进程"""
    for name, proc in processes.items():
        if proc and proc.poll() is None:
            print(f"Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


atexit.register(cleanup_processes)


def start_hermes_poll():
    """启动 Hermes 轮询进程（完全后台运行）"""
    global processes
    if processes['hermes_poll'] and processes['hermes_poll'].poll() is None:
        return {'success': True, 'message': 'Hermes poll already running'}

    try:
        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "poll_loop.py"), "hermes"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR),
            start_new_session=True
        )
        processes['hermes_poll'] = proc
        return {'success': True, 'message': 'Hermes poll started', 'pid': proc.pid}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def is_poll_running(name):
    """检查指定轮询进程是否在运行"""
    proc = processes.get(name)
    if proc is None:
        return False
    if proc.poll() is not None:
        # Process has exited, clean up the reference
        processes[name] = None
        return False
    # Double-check with ps that the process really exists
    try:
        result = subprocess.run(['ps', '-p', str(proc.pid), '-o', 'pid='], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            processes[name] = None
            return False
    except Exception:
        return False
    return True

def start_claude_poll():
    """启动 Claude 轮询进程（完全后台运行）"""
    global processes
    if processes['claude_poll'] and processes['claude_poll'].poll() is None:
        return {'success': True, 'message': 'Claude poll already running'}

    try:
        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "poll_loop.py"), "claude"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR),
            start_new_session=True
        )
        processes['claude_poll'] = proc
        return {'success': True, 'message': 'Claude poll started', 'pid': proc.pid}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def stop_hermes_poll():
    """停止 Hermes 轮询进程"""
    global processes
    if processes['hermes_poll']:
        proc = processes['hermes_poll']
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        processes['hermes_poll'] = None
    return {'success': True, 'message': 'Hermes poll stopped'}


def stop_claude_poll():
    """停止 Claude 轮询进程"""
    global processes
    if processes['claude_poll']:
        proc = processes['claude_poll']
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        processes['claude_poll'] = None
    return {'success': True, 'message': 'Claude poll stopped'}

def stop_all_polls():
    """停止所有轮询进程"""
    stop_hermes_poll()
    stop_claude_poll()
    print("🛑 All poll processes stopped")


def get_services_status():
    """获取服务状态"""
    return {
        'hermes_poll': {
            'running': processes['hermes_poll'] is not None and processes['hermes_poll'].poll() is None,
            'pid': processes['hermes_poll'].pid if processes['hermes_poll'] else None
        },
        'claude_poll': {
            'running': processes['claude_poll'] is not None and processes['claude_poll'].poll() is None,
            'pid': processes['claude_poll'].pid if processes['claude_poll'] else None
        },
        'server': {
            'running': True,
            'pid': os.getpid()
        }
    }


class BridgeHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        # 安全的CORS设置 - 只允许信任的源
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
        else:
            # 对于不信任的源，不设置CORS头
            pass

        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        # 主题映射（key 是 URL 编码后的名称）
        theme_map = {
            '%E6%9A%97%E5%A2%83': '/暗境.html',   # 暗境
            '%E6%B5%81%E5%BD%A9': '/流彩.html',   # 流彩
            '%E6%9A%96%E5%A2%A8': '/暖墨.html',   # 暖墨
            '%E9%9C%9C%E7%92%83': '/霜璃.html',   # 霜璃
            '%E7%B4%A0%E5%AE%A3': '/素宣.html',   # 素宣
            '%E9%9B%85%E9%9F%B5': '/雅韵.html',   # 雅韵
        }

        # 处理查询参数
        path = self.path
        if '?' in path:
            base_path, query = path.split('?', 1)
            if base_path == '/' and 'theme=' in query:
                # 提取 theme 值并查找
                for item in query.split('&'):
                    if item.startswith('theme='):
                        theme = item.split('=')[1]
                        if theme in theme_map:
                            self.send_response(302)
                            self.send_header('Location', theme_map[theme])
                            self.send_header('Cache-Control', 'no-cache')
                            self.end_headers()
                            return
            self.path = base_path
        else:
            query = None

        if self.path == '/' or self.path == '/index.html':
            self.path = '/index.html'
            return super().do_GET()
        elif self.path == '/ui-options' or self.path == '/ui-options.html':
            self.path = '/ui-options.html'
            return super().do_GET()
        elif self.path == '/current.json' or self.path == '/messages' or self.path == '/api/messages':
            self.serve_current_discussion()
        elif self.path == '/discussions':
            self.list_discussions()
        elif self.path.startswith('/discussions/'):
            filename = unquote(self.path[len('/discussions/'):])
            self.serve_discussion_file(filename)
        elif self.path == '/api/status':
            self.serve_api_status()
        elif self.path == '/api/models':
            self.serve_models()
        elif self.path == '/api/services':
            self.serve_services_status()
        elif self.path == '/api/events':
            self.handle_sse_stream()
        elif self.path == '/themes':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
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
            html += '<h2 style="text-align:center; margin-bottom:30px;">🎨 选择主题风格</h2>'
            html += '<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; max-width: 800px; margin: 0 auto;">'
            for theme, desc in themes:
                url = f'/?theme={theme}'
                bg_colors = {
                    '暗境': '#1a1a2e',
                    '流彩': 'linear-gradient(135deg, #667eea, #764ba2)',
                    '暖墨': '#2d2a32',
                    '霜璃': '#e8f4f8',
                    '素宣': '#f5f5f0',
                    '雅韵': '#2c1810',
                }
                text_colors = {
                    '暗境': '#fff',
                    '流彩': '#fff',
                    '暖墨': '#e8d5c4',
                    '霜璃': '#2a6496',
                    '素宣': '#333',
                    '雅韵': '#d4a574',
                }
                bg = bg_colors.get(theme, '#333')
                color = text_colors.get(theme, '#fff')
                html += f'''<a href="{url}" style="
                    display: block;
                    background: {bg};
                    color: {color};
                    padding: 30px 20px;
                    border-radius: 15px;
                    text-decoration: none;
                    text-align: center;
                    font-size: 18px;
                    transition: transform 0.2s;
                " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
                    <div style="font-size: 32px; margin-bottom: 10px;">🎨</div>
                    <div style="font-weight: bold; margin-bottom: 5px;">{theme}</div>
                    <div style="font-size: 12px; opacity: 0.8;">{desc}</div>
                </a>'''
            html += '</div>'
            html += '<div style="text-align:center; margin-top:30px;"><a href="/index.html" style="color:#888;">← 返回主页面</a></div>'
            html += '</body></html>'
            self.wfile.write(html.encode('utf-8'))
            return
        else:
            return super().do_GET()

    def do_POST(self):

        if self.path == '/api/discussion/start':
            self.handle_start_discussion()
        elif self.path == '/api/discussion/start-ai':
            self.handle_start_ai_conversation()
        elif self.path == '/api/discussion/end':
            self.handle_end_discussion()
        elif self.path == '/api/message':
            self.handle_send_message()
        elif self.path == '/api/discussion/list':
            self.handle_list_discussions()
        elif self.path == '/api/discussion/load':
            self.handle_load_discussion()
        elif self.path == '/api/discussion/delete':
            self.handle_delete_discussion()
        elif self.path == '/api/services/start':
            self.handle_start_services()
        elif self.path == '/api/services/stop':
            self.handle_stop_services()
        elif self.path == '/api/services/hermes/start':
            self.handle_start_hermes()
        elif self.path == '/api/services/hermes/stop':
            self.handle_stop_hermes()
        elif self.path == '/api/services/claude/start':
            self.handle_start_claude()
        elif self.path == '/api/services/claude/stop':
            self.handle_stop_claude()
        elif self.path == '/save-selection':
            self.handle_save_selection()
        elif self.path == '/api/export':
            self.handle_export()
        elif self.path == '/api/summary':
            self.handle_summary()
        else:
            self.send_error(404, 'Not Found')

    def handle_export(self):
        """导出对话到 output 文件夹"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')

            import json
            data = json.loads(post_data)
            topic = data.get('topic', '')
            content = data.get('content', '')

            # 如果 topic 为空或默认，从 state.json 获取
            if not topic or topic == '未命名话题':
                state = load_state()
                topic = state.get('current_topic', '未命名话题')

            # 清理话题名称，移除非法字符
            import re
            topic = re.sub(r'[\\/:*?"<>|]', '_', topic)
            if len(topic) > 50:
                topic = topic[:50]
            
            # 生成文件名
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{topic}_{timestamp}.md"
            
            # 创建 output 文件夹
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
            os.makedirs(output_dir, exist_ok=True)
            
            # 保存文件
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'path': filepath}).encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def handle_summary(self):
        """AI 总结对话内容并导出到 output 文件夹"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')

            import json
            data = json.loads(post_data)
            topic = data.get('topic', '')
            ai_type = data.get('ai_type', 'claude')  # 'claude' or 'hermes'
            messages_content = data.get('messages_content', '')

            # 如果 topic 为空或默认，从 state.json 获取
            if not topic or topic == '未命名话题':
                state = load_state()
                topic = state.get('current_topic', '未命名话题')

            # 清理话题名称
            import re
            topic = re.sub(r'[\\/:*?"<>|]', '_', topic)
            if len(topic) > 50:
                topic = topic[:50]

            # 生成文件名
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            ai_label = 'Claude总结' if ai_type == 'claude' else 'Hermes总结'
            filename = f"{ai_label}-{topic}_{timestamp}.md"

            # 构建总结 prompt
            if ai_type == 'claude':
                prompt = f"""你是 Claude，请对以下对话内容进行深度总结。

对话内容：
---
{messages_content}
---

请从以下角度进行总结：
1. 讨论的核心主题和观点
2. 主要的分析思路和论证过程
3. 产生的关键洞见或结论
4. 讨论的局限性或未解决的问题

请用简洁有条理的方式输出总结。"""
            else:
                prompt = f"""你是 Hermes，请对以下对话内容进行深度总结。

对话内容：
---
{messages_content}
---

请从以下角度进行总结：
1. 讨论的核心主题和观点
2. 主要的分析思路和论证过程
3. 产生的关键洞见或结论
4. 讨论的局限性或未解决的问题

请用简洁有条理的方式输出总结。"""

            # 调用对应的 AI
            if ai_type == 'claude':
                result = subprocess.run(
                    ["claude", "-p", "-"],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(BASE_DIR)
                )
            else:
                # Hermes
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(prompt)
                    prompt_file = f.name
                try:
                    result = subprocess.run(
                        ["hermes", "chat", "-q", f"@{prompt_file}", "-Q", "--source", "claude-hermes"],
                        capture_output=True,
                        text=True,
                        timeout=180,
                        cwd=str(BASE_DIR)
                    )
                finally:
                    if os.path.exists(prompt_file):
                        os.unlink(prompt_file)

            if result.returncode != 0:
                raise Exception(result.stderr or 'AI 调用失败')

            summary = result.stdout.strip()
            if not summary:
                raise Exception('AI 返回空内容')

            # 写入文件
            output_dir = BASE_DIR / 'output'
            output_dir.mkdir(exist_ok=True)
            filepath = output_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# {ai_label}\n\n**话题**: {topic}\n\n---\n\n{summary}")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'path': str(filepath), 'summary': summary}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

    def serve_current_discussion(self):
        """返回当前讨论内容 - 从 bridge.jsonl 读取"""
        try:
            BRIDGE_FILE = BASE_DIR / "bridge.jsonl"
            state = {}
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

            discussion_id = state.get('discussion_id', '')

            messages = []
            if BRIDGE_FILE.exists():
                with open(BRIDGE_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                msg = json.loads(line)
                                messages.append(msg)
                            except json.JSONDecodeError as e:
                                import sys
                                print(f"⚠️ JSON 解析错误 in serve_current_discussion: {e}", file=sys.stderr)

            # 只返回最近的消息（最后50条）
            messages = messages[-50:]
            content = '\n'.join(json.dumps(m, ensure_ascii=False) for m in messages)

            self.send_response(200)
            self.send_header('Content-Type', 'application/jsonl; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def list_discussions(self):
        """列出所有已保存的讨论"""
        try:
            files = []
            if ARCHIVE_DIR.exists():
                for f in ARCHIVE_DIR.iterdir():
                    if f.suffix == '.json':
                        stat = f.stat()
                        files.append({
                            'name': f.name,
                            'size': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
            files.sort(key=lambda x: x['modified'], reverse=True)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(files, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def serve_discussion_file(self, filename):
        """返回指定的讨论文件"""
        try:
            # 安全文件名验证 - 只允许字母数字和安全字符
            if not filename or not all(c.isalnum() or c in '._-' for c in filename):
                self.send_error(400, 'Invalid filename')
                return

            # 防止路径遍历攻击
            filepath = (ARCHIVE_DIR / filename).resolve()
            if not filepath.is_relative_to(ARCHIVE_DIR.resolve()):
                self.send_error(403, 'Forbidden: Path traversal detected')
                return

            if not filepath.exists():
                self.send_error(404, 'Not Found')
                return

            # 检查文件大小（防止DoS）
            file_size = filepath.stat().st_size
            if file_size > 10 * 1024 * 1024:  # 10MB 限制
                self.send_error(413, 'File too large')
                return

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content.encode('utf-8'))))
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))

        except Exception as e:
            self.send_error(500, f'Error serving file: {sanitize_error_message(e)}')

    def serve_api_status(self):
        """返回状态信息"""
        try:
            state = {}
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

            current_lines = 0
            if BRIDGE_FILE.exists():
                with open(BRIDGE_FILE, 'r', encoding='utf-8') as f:
                    current_lines = sum(1 for line in f if line.strip())

            discussions_count = 0
            if ARCHIVE_DIR.exists():
                discussions_count = len([f for f in ARCHIVE_DIR.iterdir() if f.suffix == '.json'])

            # 启动时校验状态
            is_valid, repair_msg = validate_and_repair_state()
            if not is_valid:
                print(f"🔧 {repair_msg}")

            # 检查 poll 进程是否在运行（使用 ps 直接检查，因为进程由 start.sh 管理）
            poll_running = False
            try:
                result = subprocess.run(['pgrep', '-f', 'poll_loop.py'], capture_output=True, text=True)
                poll_running = result.returncode == 0 and bool(result.stdout.strip())
            except Exception:
                pass

            status = {
                'online': True,
                'current_messages': current_lines,
                'current_layer': state.get('current_layer', 0),
                'current_topic': state.get('current_topic'),
                'last_write_by': state.get('last_write_by', None),
                'discussions_count': discussions_count,
                'discussion_active': state.get('current_discussion') is not None,
                'discussion_started': state.get('discussion_started', False),
                'poll_running': poll_running,
                'timestamp': datetime.now().isoformat()
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def serve_models(self):
        """返回 AI 模型名称配置"""
        ai_name_claude = os.getenv('AI_NAME_CLAUDE', 'Claude')
        ai_name_hermes = os.getenv('AI_NAME_HERMES', 'Hermes')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'claude': ai_name_claude,
            'hermes': ai_name_hermes
        }, ensure_ascii=False).encode('utf-8'))

    def serve_services_status(self):
        """返回服务状态"""
        status = get_services_status()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(status, ensure_ascii=False).encode('utf-8'))

    def handle_sse_stream(self):
        """SSE 实时消息流"""
        import time

        # 获取 Last-Event-ID（上次已发送的消息偏移）
        last_event_id = self.headers.get('Last-Event-Id', self.headers.get('lastEventId', '0'))
        try:
            last_offset = int(last_event_id)
        except ValueError:
            last_offset = 0

        # 发送 SSE 头
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        # 发送初始消息（追赶阶段）
        try:
            initial_messages = get_messages_since(last_offset)
            for i, msg in enumerate(initial_messages):
                msg_offset = last_offset + i + 1
                event_id = str(msg_offset)
                data = json.dumps(msg, ensure_ascii=False)
                self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode('utf-8'))
                self.wfile.flush()

            if initial_messages:
                last_offset = last_offset + len(initial_messages)
        except Exception as e:
            print(f"SSE initial send error: {e}", file=sys.stderr)
            return

        # 保持连接并推送新消息
        while True:
            try:
                current_offset = _read_checkpoint()
                if current_offset is None:
                    current_offset = 0

                if current_offset > last_offset:
                    new_messages = get_messages_since(last_offset)
                    for msg in new_messages:
                        last_offset += 1
                        event_id = str(last_offset)
                        data = json.dumps(msg, ensure_ascii=False)
                        self.wfile.write(f"id: {event_id}\ndata: {data}\n\n".encode('utf-8'))
                        self.wfile.flush()

                time.sleep(0.5)  # 500ms 检查一次
            except Exception as e:
                # 客户端断开连接
                break

    def handle_start_services(self):
        """启动所有服务"""
        hermes_result = start_hermes_poll()
        claude_result = start_claude_poll()

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'success': True,
            'hermes': hermes_result,
            'claude': claude_result
        }, ensure_ascii=False).encode('utf-8'))

    def handle_stop_services(self):
        """停止所有轮询服务"""
        import subprocess

        # 使用 pkill 停止 poll 进程（因为进程是通过 start.sh 独立启动的）
        hermes_result = {'success': False, 'message': ''}
        claude_result = {'success': False, 'message': ''}

        try:
            subprocess.run(['pkill', '-f', 'poll_loop.py hermes'], capture_output=True)
            hermes_result = {'success': True, 'message': 'Hermes poll stopped'}
        except Exception as e:
            hermes_result = {'success': False, 'message': str(e)}

        try:
            subprocess.run(['pkill', '-f', 'poll_loop.py claude'], capture_output=True)
            claude_result = {'success': True, 'message': 'Claude poll stopped'}
        except Exception as e:
            claude_result = {'success': False, 'message': str(e)}

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'success': True,
            'hermes': hermes_result,
            'claude': claude_result
        }, ensure_ascii=False).encode('utf-8'))

    def handle_start_hermes(self):
        result = start_hermes_poll()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def handle_stop_hermes(self):
        result = stop_hermes_poll()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def handle_start_claude(self):
        result = start_claude_poll()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def handle_stop_claude(self):
        result = stop_claude_poll()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def handle_start_discussion(self):
        """开始新讨论"""
        try:
            # 使用验证器解析和验证JSON请求
            data = validate_json_request(self, ['topic'])
            if data is None:
                return

            # 验证讨论请求数据
            try:
                validated_data = validate_discussion_request(data)
            except ValidationError as e:
                self.send_error(400, f'Invalid discussion data: {str(e)}')
                return

            topic = validated_data['topic']

            if not ARCHIVE_DIR.exists():
                ARCHIVE_DIR.mkdir(parents=True)

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

            state = {
                'current_discussion': filename,
                'current_topic': topic,
                'current_layer': 0,
                'last_write_by': 'user',
                'claude_last_read': 0,
                'hermes_last_read': 0,
                'bridge_line_count': 0,
                'discussion_id': timestamp,
                'discussion_started': False  # AI 对话未开始，需手动点击开始
            }

            # 写入第一条消息（用户的问题）
            layer = 1
            entry = {
                'layer': layer,
                'author': 'user',
                'content': topic,
                'timestamp': datetime.now().isoformat()
            }

            # 使用 bridge_core 写入第一条消息（同时更新 checkpoint）
            new_offset = append_bridge(entry, update_checkpoint=True)
            if new_offset:
                mark_processed(new_offset)

            state['current_layer'] = layer
            state['bridge_line_count'] = new_offset if new_offset else 1

            save_state(state)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'filename': filename,
                'filepath': str(filepath),
                'topic': topic
            }, ensure_ascii=False).encode('utf-8'))

        except json.JSONDecodeError:
            self.send_error(400, 'Invalid JSON')
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_start_ai_conversation(self):
        """开始 AI 对话交流（启动两个 poll 进程）"""
        try:
            state = load_state()

            if not state.get('current_discussion'):
                self.send_error(400, 'No active discussion. Start one first.')
                return

            # 检查进程是否真的在运行
            hermes_running = is_poll_running('hermes_poll')
            claude_running = is_poll_running('claude_poll')
            
            if hermes_running and claude_running:
                self.send_error(400, 'AI conversation already started.')
                return

            # 启动 Claude 和 Hermes 的轮询进程
            if not hermes_running:
                start_hermes_poll()
            if not claude_running:
                start_claude_poll()

            # 更新状态，标记 AI 对话已开始
            state['discussion_started'] = True
            save_state(state)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'message': 'AI conversation started'
            }, ensure_ascii=False).encode('utf-8'))

        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_end_discussion(self):
        """结束当前讨论并保存"""
        try:
            # 使用验证器解析和验证JSON请求
            data = validate_json_request(self)
            if data is None:
                return

            # 验证并限制 summary 长度
            summary = data.get('summary', '')
            if len(summary) > 5000:
                summary = summary[:5000]

            state = {}
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

            filename = state.get('current_discussion')
            if not filename:
                self.send_error(400, 'No active discussion')
                return

            # 停止轮询服务
            subprocess.run(['pkill', '-f', 'poll_loop.py hermes'], capture_output=True)
            subprocess.run(['pkill', '-f', 'poll_loop.py claude'], capture_output=True)

            # 读取消息
            messages = []
            if BRIDGE_FILE.exists():
                with open(BRIDGE_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                messages.append(json.loads(line))
                            except json.JSONDecodeError as e:
                                import sys
                                print(f"⚠️ JSON 解析错误 in handle_end_discussion: {e}", file=sys.stderr)

            # 只有当 bridge.jsonl 有内容时才归档
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

            # 重置状态
            state = {
                'current_discussion': None,
                'current_topic': None,
                'current_layer': 0,
                'last_write_by': None,
                'claude_last_read': 0,
                'hermes_last_read': 0,
                'bridge_line_count': 0,
                'discussion_id': None,
                'discussion_started': False
            }
            save_state(state)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'archived': archived,
                'message_count': len(messages)
            }, ensure_ascii=False).encode('utf-8'))

        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_send_message(self):
        """发送消息"""
        try:
            # 使用验证器解析和验证JSON请求
            data = validate_json_request(self, ['content'])
            if data is None:
                return

            # 验证消息数据
            try:
                validated_data = validate_message_data(data)
            except ValidationError as e:
                self.send_error(400, f'Invalid message data: {str(e)}')
                return

            # 检查是否有活跃讨论
            state = load_state()
            if not state.get('current_discussion'):
                self.send_error(400, 'No active discussion. Start one first.')
                return

            # 构建消息条目（author 默认为 'user'）
            author = validated_data.get('author', 'user')
            layer = state.get('current_layer', 0) + 1
            entry = {
                'layer': layer,
                'author': author,
                'content': validated_data['content'],
                'timestamp': datetime.now().isoformat()
            }

            # 使用 bridge_core 追加消息（同时更新 checkpoint）
            new_offset = append_bridge(entry, update_checkpoint=True)
            if new_offset:
                mark_processed(new_offset)
                state = load_state()
                state['bridge_line_count'] = new_offset
            else:
                state = load_state()

            save_state(state)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'entry': entry}, ensure_ascii=False).encode('utf-8'))

        except json.JSONDecodeError:
            self.send_error(400, 'Invalid JSON')
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_list_discussions(self):
        """列出所有已保存的讨论"""
        try:
            def strip_session_id(content):
                if not content:
                    return ''
                lines = []
                for line in str(content).splitlines():
                    if not re.match(r'^session_id:\s*\d{8}_\d{6}_[a-f0-9]+$', line.strip(), re.IGNORECASE):
                        lines.append(line)
                return '\n'.join(lines).strip()

            def build_preview(data):
                summary = strip_session_id(data.get('summary', ''))
                if summary:
                    return summary.replace('\n', ' ')[:140]

                for msg in data.get('messages', []):
                    content = strip_session_id(msg.get('content', ''))
                    if content:
                        return content.replace('\n', ' ')[:140]
                return ''

            files = []
            if ARCHIVE_DIR.exists():
                for f in ARCHIVE_DIR.iterdir():
                    if f.suffix == '.json':
                        stat = f.stat()
                        try:
                            with open(f, 'r', encoding='utf-8') as fp:
                                data = json.load(fp)
                                topic = data.get('topic', '未知主题')
                                msg_count = len(data.get('messages', []))
                                started_raw = data.get('started_at') or ''
                                ended_raw = data.get('ended_at') or ''
                                started = started_raw[:16]
                                ended = ended_raw[:16]
                                preview = build_preview(data)
                                duration_seconds = None
                                if started_raw and ended_raw:
                                    try:
                                        start_dt = datetime.fromisoformat(started_raw)
                                        end_dt = datetime.fromisoformat(ended_raw)
                                        duration_seconds = max(0, int((end_dt - start_dt).total_seconds()))
                                    except ValueError:
                                        duration_seconds = None
                                # 使用 started_at 作为排序键
                                sort_key = started_raw
                        except json.JSONDecodeError as e:
                            import sys
                            print(f"⚠️ JSON 解析错误 in handle_list_discussions: {e}", file=sys.stderr)
                            topic = '解析失败'
                            msg_count = 0
                            started = ''
                            ended = ''
                            preview = ''
                            duration_seconds = None
                            sort_key = ''
                        files.append({
                            'filename': f.name,
                            'topic': topic,
                            'message_count': msg_count,
                            'started_at': started,
                            'ended_at': ended,
                            'preview': preview,
                            'duration_seconds': duration_seconds,
                            'size': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            'sort_key': sort_key
                        })

            # 按 sort_key 降序排序（最新的在前面）
            files.sort(key=lambda x: x.get('sort_key', ''), reverse=True)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'discussions': files}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_load_discussion(self):
        """加载指定讨论"""
        try:
            # 使用验证器解析和验证JSON请求
            data = validate_json_request(self)
            if data is None:
                return

            filename = data.get('filename', '')

            if not filename:
                self.send_error(400, 'Filename is required')
                return

            filepath = ARCHIVE_DIR / filename
            # 防止路径遍历攻击，使用 resolve() 和 is_relative_to() 进行安全检查
            try:
                resolved_path = filepath.resolve()
                if not resolved_path.is_relative_to(ARCHIVE_DIR.resolve()):
                    self.send_error(403, 'Forbidden: Path traversal detected')
                    return
            except (ValueError, OSError):
                self.send_error(403, 'Forbidden')
                return

            if not resolved_path.exists():
                self.send_error(404, 'Not Found')
                return

            with open(resolved_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def handle_delete_discussion(self):
        """删除指定讨论"""
        def json_error(code, msg):
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': msg}, ensure_ascii=False).encode('utf-8'))

        try:
            # 直接解析 JSON 请求（不使用验证器，避免返回 HTML 错误）
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
            except (ValueError, json.JSONDecodeError):
                json_error(400, 'Invalid JSON data')
                return

            filename = data.get('filename', '')

            if not filename:
                json_error(400, 'Filename is required')
                return

            filepath = ARCHIVE_DIR / filename
            # 防止路径遍历攻击，使用 resolve() 和 is_relative_to() 进行安全检查
            try:
                resolved_path = filepath.resolve()
                if not resolved_path.is_relative_to(ARCHIVE_DIR.resolve()):
                    json_error(403, 'Forbidden: Path traversal detected')
                    return
            except (ValueError, OSError):
                json_error(403, 'Forbidden')
                return

            if not resolved_path.exists():
                json_error(404, 'Not Found')
                return

            # 删除文件
            resolved_path.unlink()

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'filename': filename}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            json_error(500, sanitize_error_message(e))

    def handle_save_selection(self):
        """保存UI方案选择"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)

            selection_file = BASE_DIR / 'ui-selection.json'
            with open(selection_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self.send_error(500, sanitize_error_message(e))

    def log_message(self, format, *args):
        if args[1] != '200':
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}")


if __name__ == '__main__':
    # 确保目录和文件存在
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for f in [STATE_FILE]:
        if not f.exists():
            f.touch()

    if STATE_FILE.stat().st_size == 0:
        state = {
            'current_discussion': None,
            'current_topic': None,
            'current_layer': 0,
            'last_write_by': None,
            'claude_last_read': 0,
            'hermes_last_read': 0,
            'bridge_line_count': 0,
            'discussion_id': None,
            'discussion_started': False
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"🚀 Bridge Server running at http://localhost:{PORT}")
    print(f"📁 Base: {BASE_DIR}")
    print(f"📁 Archive: {ARCHIVE_DIR}")
    print(f"")
    print(f"🌐 打开浏览器访问: http://localhost:{PORT}")
    print(f"")
    print(f"💡 在网页端点击「启动服务」按钮来启动 Hermes/Claude 轮询")
    print(f"")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), BridgeHTTPHandler) as httpd:
        httpd.serve_forever()
