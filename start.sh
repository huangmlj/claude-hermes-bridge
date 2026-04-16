#!/bin/bash
# Claude-Hermes Bridge 启动器（后台模式）

cd "$(dirname "$0")"

# 停止旧进程
pkill -f "python3.*server.py" 2>/dev/null
pkill -f "python3.*poll_loop.py" 2>/dev/null
sleep 1

echo "🚀 启动 Claude-Hermes Bridge..."

# 启动 HTTP 服务器（后台）
nohup python3 server.py > server.log 2>&1 &
sleep 2

# 检查服务器
if ! curl -s http://localhost:8765/api/status > /dev/null 2>&1; then
    echo "❌ 服务器启动失败"
    exit 1
fi

sleep 1

echo ""
echo "✅ 全部启动完成!"
echo "🌐 访问: http://localhost:8765"
echo "📝 日志: server.log, poll_hermes.log, poll_claude.log"
