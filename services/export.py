#!/usr/bin/env python3
"""
export.py - 导出/总结服务

职责：
- 导出讨论为 Markdown 文件
- AI 总结讨论内容并导出
"""

import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# 项目根目录
_BRIDGE_DIR = Path(__file__).parent.parent

import sys
sys.path.insert(0, str(_BRIDGE_DIR))

from services.bridge import load_state

OUTPUT_DIR = _BRIDGE_DIR / "output"
AI_TIMEOUT = 180

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(topic: str) -> str:
    """清理话题名称，移除非法文件名字符"""
    topic = re.sub(r'[\\/:*?"<>|]', '_', topic)
    if len(topic) > 50:
        topic = topic[:50]
    return topic


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def export_discussion(topic: str, content: str) -> Dict[str, Any]:
    """导出讨论为 Markdown 文件

    Args:
        topic: 讨论话题
        content: Markdown 格式的讨论内容

    Returns:
        dict: {success, path}
    """
    if not topic or topic == '未命名话题':
        state = load_state()
        topic = state.get('current_topic', '未命名话题')

    topic = _sanitize_filename(topic)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{topic}_{timestamp}.md"
    filepath = OUTPUT_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return {'success': True, 'path': str(filepath)}


# ---------------------------------------------------------------------------
# AI 总结
# ---------------------------------------------------------------------------

def summarize_discussion(topic: str, ai_type: str, messages_content: str) -> Dict[str, Any]:
    """AI 总结讨论内容并导出

    Args:
        topic: 讨论话题
        ai_type: "claude" 或 "hermes"
        messages_content: 消息内容

    Returns:
        dict: {success, path, summary}

    Raises:
        ValueError: 无效的 ai_type
    """
    if not topic or topic == '未命名话题':
        state = load_state()
        topic = state.get('current_topic', '未命名话题')

    topic = _sanitize_filename(topic)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ai_label = 'Claude总结' if ai_type == 'claude' else 'Hermes总结'
    filename = f"{ai_label}-{topic}_{timestamp}.md"
    filepath = OUTPUT_DIR / filename

    # 构建总结 prompt
    prompt = _build_summary_prompt(ai_type, topic, messages_content)

    # 调用 AI
    if ai_type == 'claude':
        result = _call_claude(prompt)
    elif ai_type == 'hermes':
        result = _call_hermes(prompt)
    else:
        raise ValueError(f"Invalid ai_type: {ai_type}. Must be 'claude' or 'hermes'.")

    if not result:
        raise RuntimeError(f"{ai_type} returned empty response")

    # 写入文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# {ai_label}\n\n**话题**: {topic}\n\n---\n\n{result}")

    return {'success': True, 'path': str(filepath), 'summary': result}


def _build_summary_prompt(ai_type: str, topic: str, messages_content: str) -> str:
    """构建总结 prompt"""
    role = "Claude" if ai_type == "claude" else "Hermes"

    return f"""你是 {role}，请对以下对话内容进行深度总结。

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


def _call_claude(prompt: str) -> str | None:
    """调用 Claude CLI"""
    try:
        result = subprocess.run(
            ["claude", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=AI_TIMEOUT,
            cwd=str(_BRIDGE_DIR)
        )

        if result.returncode != 0:
            raise Exception(result.stderr or 'Claude 调用失败')

        response = result.stdout.strip()
        if not response:
            return None
        return response

    except FileNotFoundError:
        raise RuntimeError("claude command not found")
    except Exception as e:
        raise RuntimeError(f"Error calling claude: {e}")


def _call_hermes(prompt: str) -> str | None:
    """调用 Hermes CLI"""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            result = subprocess.run(
                ["hermes", "chat", "-q", f"@{prompt_file}", "-Q", "--source", "claude-hermes"],
                capture_output=True,
                text=True,
                timeout=AI_TIMEOUT,
                cwd=str(_BRIDGE_DIR)
            )

            if result.returncode != 0:
                raise Exception(result.stderr or 'Hermes 调用失败')

            response = result.stdout.strip()
            if not response:
                return None
            return response

        finally:
            if os.path.exists(prompt_file):
                os.unlink(prompt_file)

    except FileNotFoundError:
        raise RuntimeError("hermes command not found")
    except Exception as e:
        raise RuntimeError(f"Error calling hermes: {e}")
