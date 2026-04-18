#!/bin/bash
BRIDGE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BRIDGE_DIR"

# 停止旧进程
pkill -f "python3.*server.py" 2>/dev/null
pkill -f "python3.*poll.py" 2>/dev/null
pkill -f "python3.*poll_loop.py" 2>/dev/null
pkill -f "vite" 2>/dev/null
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

# 启动 Vite 开发服务器（后台）
cd web && nohup npm run dev > ../vite.log 2>&1 &
cd ..

# 等待 Vite 启动
sleep 3

# 检查 Vite
if ! curl -s http://localhost:5173 > /dev/null 2>&1; then
    echo "❌ Vite 启动失败，请查看 vite.log"
else
    echo "✅ Vite 已启动"
fi

# 后台启动 Hermes 和 Claude 轮询（不显示终端窗口）
nohup python3 services/poll.py hermes >> poll_hermes.log 2>&1 &
nohup python3 services/poll.py claude >> poll_claude.log 2>&1 &

sleep 1

echo ""
echo "✅ 全部启动完成!"
echo "🌐 访问 React 前端: http://localhost:5173"
echo "🌐 访问旧版页面:    http://localhost:8765"
echo "📝 日志文件: poll_hermes.log, poll_claude.log, vite.log"
