#!/bin/bash
# Claude Bridge - Claude Code 调用入口
# 用法: ./claude_bridge.sh "消息内容" [layer]
# 或:   ./claude_bridge.sh --read  # 读取 Hermes 的最新回复

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$SCRIPT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Claude-Hermes Bridge"
    echo ""
    echo "用法:"
    echo "  $0 \"消息内容\" [layer]   发送消息并等待回复"
    echo "  $0 --read                读取最新消息"
    echo "  $0 --status              查看当前状态"
    echo "  $0 --tail                实时观看对话 (tail -f)"
    echo ""
    echo "示例:"
    echo "  $0 \"分析这段代码...\" 1"
    echo "  $0 --read"
}

# 读取最新消息
read_latest() {
    echo -e "${YELLOW}=== 最新消息 ===${NC}"
    python3 "$BRIDGE_DIR/read_messages.py" hermes 2>/dev/null || echo "无新消息"
}

# 查看状态
show_status() {
    echo -e "${YELLOW}=== Bridge 状态 ===${NC}"
    if [ -f "$BRIDGE_DIR/state.json" ]; then
        cat "$BRIDGE_DIR/state.json" | python3 -m json.tool
    else
        echo "state.json 不存在"
    fi
}

# 发送消息并等待 Hermes 回复
send_and_wait() {
    local content="$1"
    local layer="${2:-1}"

    if [ -z "$content" ]; then
        echo -e "${RED}错误: 消息内容不能为空${NC}"
        exit 1
    fi

    echo -e "${GREEN}📤 Claude 发送消息 (Layer $layer)${NC}"
    echo "内容: ${content:0:100}..."

    # 写入消息
    python3 "$BRIDGE_DIR/write_message.py" claude "$content" "$layer"

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ 写入失败${NC}"
        exit 1
    fi

    echo ""
    echo -e "${YELLOW}⏳ 等待 Hermes 回复...${NC}"

    # 轮询等待 Hermes 回复
    local max_wait=300  # 最多等 5 分钟
    local waited=0

    while [ $waited -lt $max_wait ]; do
        sleep 2
        waited=$((waited + 2))

        # 检查 last_write_by 是否变成 hermes
        last_writer=$(python3 -c "import json; print(json.load(open('$BRIDGE_DIR/state.json'))['last_write_by'])" 2>/dev/null)

        if [ "$last_writer" = "hermes" ]; then
            echo ""
            echo -e "${GREEN}✅ Hermes 已回复！${NC}"
            echo ""
            echo -e "${YELLOW}=== Hermes 的回复 ===${NC}"
            python3 "$BRIDGE_DIR/read_messages.py" hermes
            return 0
        fi

        if [ $((waited % 30)) -eq 0 ]; then
            echo "⏳ 等待中... (${waited}s)"
        fi
    done

    echo -e "${YELLOW}⚠️ 等待超时 (${max_wait}s)${NC}"
    return 1
}

# 主入口
case "${1:-}" in
    --help|-h)
        usage
        ;;
    --read)
        read_latest
        ;;
    --status)
        show_status
        ;;
    --tail)
        echo -e "${YELLOW}实时观看 bridge.jsonl (Ctrl+C 退出)${NC}"
        tail -f "$BRIDGE_DIR/bridge.jsonl"
        ;;
    *)
        if [ -z "$1" ]; then
            usage
            exit 1
        fi
        send_and_wait "$1" "${2:-1}"
        ;;
esac
