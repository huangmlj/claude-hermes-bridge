#!/usr/bin/env python3
"""
validators.py - 输入验证模块
提供安全的输入验证和清理功能
"""

import re
import json
from typing import Optional, Dict, Any

class ValidationError(Exception):
    """验证错误异常"""
    pass

# 验证规则常量
MAX_TOPIC_LENGTH = 500
MAX_CONTENT_LENGTH = 50000
MAX_FILENAME_LENGTH = 255

# 安全字符模式 - 允许大多数可打印字符，只禁止控制字符
SAFE_TOPIC_PATTERN = re.compile(r'^[\u0021-\u007E\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\s]+$', re.UNICODE)
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9\-_.]+$')

def validate_topic(topic: str) -> str:
    """验证和清理讨论主题

    Args:
        topic: 原始主题字符串

    Returns:
        str: 清理后的主题

    Raises:
        ValidationError: 验证失败
    """
    if not topic:
        raise ValidationError("Topic cannot be empty")

    if len(topic) > MAX_TOPIC_LENGTH:
        raise ValidationError(f"Topic too long (max {MAX_TOPIC_LENGTH} characters)")

    # 移除前后空白
    topic = topic.strip()

    # 检查是否只包含安全字符
    if not SAFE_TOPIC_PATTERN.match(topic):
        raise ValidationError("Topic contains invalid characters")

    return topic

def validate_content(content: str) -> str:
    """验证和清理消息内容

    Args:
        content: 原始内容字符串

    Returns:
        str: 清理后的内容

    Raises:
        ValidationError: 验证失败
    """
    if not content:
        raise ValidationError("Content cannot be empty")

    if len(content) > MAX_CONTENT_LENGTH:
        raise ValidationError(f"Content too long (max {MAX_CONTENT_LENGTH} characters)")

    # 移除前后空白
    content = content.strip()

    # 基本的安全检查 - 移除潜在的控制字符
    content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

    return content

def validate_filename(filename: str) -> str:
    """验证文件名

    Args:
        filename: 原始文件名

    Returns:
        str: 验证后的文件名

    Raises:
        ValidationError: 验证失败
    """
    if not filename:
        raise ValidationError("Filename cannot be empty")

    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError(f"Filename too long (max {MAX_FILENAME_LENGTH} characters)")

    # 检查是否只包含安全字符
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise ValidationError("Filename contains invalid characters")

    return filename

def validate_message_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """验证完整的消息数据

    Args:
        data: 消息数据字典

    Returns:
        dict: 验证和清理后的数据

    Raises:
        ValidationError: 验证失败
    """
    if not isinstance(data, dict):
        raise ValidationError("Message data must be a dictionary")

    # 验证必需字段
    required_fields = ['author', 'content']
    for field in required_fields:
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")

    # 验证作者
    author = data.get('author', '').strip()
    if author not in ['claude', 'hermes', 'user']:
        raise ValidationError("Invalid author. Must be 'claude', 'hermes', or 'user'")

    # 验证和清理内容
    content = validate_content(data['content'])

    # 验证可选字段
    layer = data.get('layer')
    if layer is not None:
        if not isinstance(layer, int) or layer < 0:
            raise ValidationError("Layer must be a non-negative integer")

    # 返回清理后的数据
    cleaned_data = {
        'author': author,
        'content': content
    }

    if layer is not None:
        cleaned_data['layer'] = layer

    return cleaned_data

def validate_discussion_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """验证讨论创建请求

    Args:
        data: 请求数据

    Returns:
        dict: 验证后的数据

    Raises:
        ValidationError: 验证失败
    """
    if not isinstance(data, dict):
        raise ValidationError("Request data must be a dictionary")

    # 验证主题
    topic = data.get('topic', '').strip()
    if not topic:
        raise ValidationError("Topic is required")

    topic = validate_topic(topic)

    return {'topic': topic}

def sanitize_error_message(error: Exception) -> str:
    """清理错误消息，防止信息泄露

    Args:
        error: 原始异常

    Returns:
        str: 清理后的错误消息
    """
    error_msg = str(error)

    # 移除潜在的敏感信息
    # 移除文件路径
    error_msg = re.sub(r'/[^\s]+', '[PATH]', error_msg)
    # 移除API密钥模式
    error_msg = re.sub(r'sk-[a-zA-Z0-9]+', '[API_KEY]', error_msg)
    # 移除令牌模式
    error_msg = re.sub(r'[a-zA-Z0-9_-]{40,}', '[TOKEN]', error_msg)

    return error_msg

# 便捷函数用于HTTP处理
def validate_json_request(handler, required_fields: list = None) -> Dict[str, Any]:
    """验证JSON请求数据（用于HTTP处理器）

    Args:
        handler: HTTP处理器实例
        required_fields: 必需字段列表

    Returns:
        dict: 解析后的JSON数据

    Raises:
        None: 直接发送HTTP错误响应
    """
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length > 1024 * 1024:  # 1MB 限制
            handler.send_error(413, 'Request too large')
            return None

        body = handler.rfile.read(content_length)
        if not body:
            data = {}
        else:
            data = json.loads(body.decode('utf-8'))

        if required_fields:
            for field in required_fields:
                if field not in data:
                    handler.send_error(400, f'Missing required field: {field}')
                    return None

        return data

    except (ValueError, json.JSONDecodeError) as e:
        handler.send_error(400, 'Invalid JSON data')
        return None
    except Exception as e:
        error_msg = sanitize_error_message(e)
        handler.send_error(500, f'Request validation failed: {error_msg}')
        return None