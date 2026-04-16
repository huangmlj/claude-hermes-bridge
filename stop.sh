#!/bin/bash
# 停止 Claude-Hermes Bridge 服务

echo "🛑 停止 Claude-Hermes Bridge..."

# 停止 Python 进程
pkill -f "python3.*server.py" 2>/dev/null
pkill -f "python3.*poll_loop.py" 2>/dev/null

sleep 1
pkill -9 -f "poll_loop.py"
# 检查是否还有进程
if pgrep -f "python3.*(server|poll_loop)" > /dev/null 2>&1; then
    echo "⚠️  还有进程在运行，强制终止..."
    pkill -9 -f "python3.*server.py" 2>/dev/null
    pkill -9 -f "python3.*poll_loop.py" 2>/dev/null
fi

echo "✅ 服务已停止"
