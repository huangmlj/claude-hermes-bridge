#!/usr/bin/env python3
"""
Token 预算控制模块
根据 Layer 层级和配置决定消息保留策略
"""

import os

# 自动加载 .env 文件
try:
    from dotenv import load_dotenv
    # 在 BRIDGE_DIR 下查找 .env 文件
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

# 默认配置
DEFAULT_CONFIG = {
    "layer_1_full": True,
    "user_msg_full_count": 1,
    "layer_2to4_full": True,
    "layer_5to10_truncate": 0.5,
    "layer_over_10_summary": True,
    "max_chars": 10000,
}


def load_token_config():
    """从环境变量加载 Token 预算配置"""
    config = DEFAULT_CONFIG.copy()

    # Layer 1 全量保留用户话题
    config["layer_1_full"] = os.environ.get("LAYER_1_FULL", "true").lower() == "true"

    # 用户消息保留最近几条
    config["user_msg_full_count"] = int(os.environ.get("USER_MSG_FULL_COUNT", "1"))

    # Layer 2-4 全量
    config["layer_2to4_full"] = os.environ.get("LAYER_2to4_FULL", "true").lower() == "true"

    # Layer 5-10 截断比例
    config["layer_5to10_truncate"] = float(os.environ.get("LAYER_5to10_TRUNCATE", "0.5"))

    # >Layer 10 摘要
    config["layer_over_10_summary"] = os.environ.get("LAYER_OVER_10_SUMMARY", "true").lower() == "true"

    # 最大字符数
    config["max_chars"] = int(os.environ.get("MAX_CHARS", "10000"))

    return config


def get_message_retention(msg, config):
    """根据消息层级和配置决定保留策略

    Returns:
        tuple: (should_include, truncation_ratio)
        - should_include: 是否包含这条消息
        - truncation_ratio: 截断比例 (0.0-1.0)，1.0=完整保留，0.5=截断一半
    """
    layer = msg.get("layer", 0)
    author = msg.get("author", "")

    if layer == 1:
        # Layer 1 全量保留
        return (True, 1.0) if config["layer_1_full"] else (False, 0)

    if layer <= 4:
        # Layer 2-4 全量
        return (True, 1.0) if config["layer_2to4_full"] else (False, 0)

    if layer <= 10:
        # Layer 5-10 按比例截断
        return (True, 1.0 - config["layer_5to10_truncate"])

    # > Layer 10
    if config["layer_over_10_summary"]:
        return (True, 0.3)  # 摘要保留30%
    else:
        return (False, 0)


def truncate_content(content, ratio):
    """按比例截断内容

    Args:
        content: 原始内容
        ratio: 保留比例 (0.0-1.0)
    """
    if ratio >= 1.0:
        return content
    if ratio <= 0:
        return ""

    # 按句子截断，避免截断在单词中间
    chars_to_keep = int(len(content) * ratio)

    # 尝试在句号或换行处截断
    truncated = content[:chars_to_keep]
    last_period = max(truncated.rfind("。"), truncated.rfind("\n"))
    if last_period > chars_to_keep * 0.7:  # 如果在70%位置之后有句子结束
        return truncated[:last_period + 1]

    # 否则在空格处截断
    last_space = truncated.rfind(" ")
    if last_space > chars_to_keep * 0.8:
        return truncated[:last_space]

    return truncated


def apply_token_budget(messages, config=None):
    """对消息列表应用 Token 预算策略

    Args:
        messages: 消息列表（已按时间排序）
        config: 配置字典，None 则使用默认配置

    Returns:
        list: 处理后的消息列表，每项为 (author, content, truncated_content)
    """
    if config is None:
        config = load_token_config()

    result = []
    user_msg_count = 0

    for msg in messages:
        layer = msg.get("layer", 0)
        author = msg.get("author", "")
        content = msg.get("content", "")

        should_include, ratio = get_message_retention(msg, config)

        if not should_include:
            continue

        # 用户消息特殊处理：只保留最近的 N 条
        if author == "user":
            user_msg_count += 1
            if user_msg_count > config["user_msg_full_count"]:
                continue

        # 应用截断
        if ratio < 1.0:
            content = truncate_content(content, ratio)

        result.append((author, content))

    return result


def format_history_for_prompt(messages, current_topic, config=None):
    """格式化消息历史为 prompt 字符串

    Args:
        messages: 消息列表
        current_topic: 当前话题
        config: Token 预算配置

    Returns:
        str: 格式化的历史字符串
    """
    if config is None:
        config = load_token_config()

    # 应用预算策略
    processed = apply_token_budget(messages, config)

    # 构建历史字符串
    history = ""
    for author, content in processed:
        if author == "user":
            history += f"【用户】: {content}\n\n"
        elif author == "hermes":
            history += f"【Hermes】: {content}\n\n"
        elif author == "claude":
            history += f"【Claude】: {content}\n\n"
        else:
            history += f"【{author}】: {content}\n\n"

    # 强制截断到最大字符数
    if len(history) > config["max_chars"]:
        history = history[-config["max_chars"]:]
        # 找回句子边界
        first_newline = history.find("\n")
        if first_newline > 0 and first_newline < config["max_chars"] * 0.1:
            history = history[first_newline:]

    return history
