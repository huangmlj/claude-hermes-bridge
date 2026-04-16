#!/usr/bin/env python3
"""
secrets_manager.py - 安全密钥管理模块
提供加密存储和安全的API密钥管理
"""

import os
import json
import base64
import secrets
from pathlib import Path
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecretsError(Exception):
    """密钥管理错误"""
    pass

# 配置
BRIDGE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
SECRETS_DIR = BRIDGE_DIR / ".secrets"
SECRETS_FILE = SECRETS_DIR / "secrets.enc"
KEY_FILE = SECRETS_DIR / "key"

# 加密参数
SALT_SIZE = 32
KEY_ITERATIONS = 100000

def _ensure_secrets_dir() -> None:
    """确保密钥目录存在"""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)

def _generate_master_key() -> bytes:
    """生成或加载主密钥"""
    if KEY_FILE.exists():
        try:
            with open(KEY_FILE, 'rb') as f:
                return f.read()
        except IOError:
            pass

    # 生成新密钥
    key = secrets.token_bytes(32)
    try:
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        # 设置文件权限为600
        os.chmod(KEY_FILE, 0o600)
    except IOError as e:
        raise SecretsError(f"无法保存主密钥: {e}")

    return key

def _get_fernet() -> Fernet:
    """获取Fernet加密器"""
    master_key = _generate_master_key()
    return Fernet(base64.urlsafe_b64encode(master_key))

def _load_secrets() -> Dict[str, str]:
    """加载加密的密钥"""
    if not SECRETS_FILE.exists():
        return {}

    try:
        fernet = _get_fernet()
        with open(SECRETS_FILE, 'rb') as f:
            encrypted_data = f.read()

        decrypted_data = fernet.decrypt(encrypted_data)
        return json.loads(decrypted_data.decode('utf-8'))
    except Exception as e:
        raise SecretsError(f"无法解密密钥文件: {e}")

def _save_secrets(secrets: Dict[str, str]) -> None:
    """保存加密的密钥"""
    _ensure_secrets_dir()

    try:
        fernet = _get_fernet()
        secrets_json = json.dumps(secrets, ensure_ascii=False)
        encrypted_data = fernet.encrypt(secrets_json.encode('utf-8'))

        with open(SECRETS_FILE, 'wb') as f:
            f.write(encrypted_data)

        # 设置文件权限为600
        os.chmod(SECRETS_FILE, 0o600)
    except Exception as e:
        raise SecretsError(f"无法保存密钥文件: {e}")

def set_secret(key: str, value: str) -> None:
    """设置密钥

    Args:
        key: 密钥名称
        value: 密钥值

    Raises:
        SecretsError: 保存失败
    """
    secrets = _load_secrets()
    secrets[key] = value
    _save_secrets(secrets)

def get_secret(key: str, default: str = "") -> str:
    """获取密钥

    Args:
        key: 密钥名称
        default: 默认值

    Returns:
        str: 密钥值或默认值
    """
    try:
        secrets = _load_secrets()
        return secrets.get(key, default)
    except SecretsError:
        return default

def delete_secret(key: str) -> bool:
    """删除密钥

    Args:
        key: 密钥名称

    Returns:
        bool: 是否成功删除
    """
    try:
        secrets = _load_secrets()
        if key in secrets:
            del secrets[key]
            _save_secrets(secrets)
            return True
        return False
    except SecretsError:
        return False

def list_secrets() -> Dict[str, str]:
    """列出所有密钥（只返回密钥名，不返回值）

    Returns:
        dict: 密钥名到掩码值的映射
    """
    try:
        secrets = _load_secrets()
        return {key: _mask_secret_value(value) for key, value in secrets.items()}
    except SecretsError:
        return {}

def _mask_secret_value(value: str) -> str:
    """掩码密钥值用于显示

    Args:
        value: 原始密钥值

    Returns:
        str: 掩码后的值
    """
    if len(value) <= 8:
        return "*" * len(value)

    # 显示前4个和后4个字符，中间用*掩码
    return value[:4] + "*" * (len(value) - 8) + value[-4:]

# 便捷函数用于常见API密钥
def get_anthropic_key() -> str:
    """获取Anthropic API密钥"""
    # 优先从环境变量获取
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key

    # 从加密存储获取
    return get_secret("anthropic_api_key")

def set_anthropic_key(key: str) -> None:
    """设置Anthropic API密钥"""
    if not key or not key.startswith("sk-ant-"):
        raise SecretsError("无效的Anthropic API密钥格式")

    set_secret("anthropic_api_key", key)

def get_hermes_config() -> str:
    """获取Hermes配置"""
    return os.environ.get("HERMES_CONFIG", get_secret("hermes_config"))

def set_hermes_config(config: str) -> None:
    """设置Hermes配置"""
    set_secret("hermes_config", config)

# 初始化检查
def init_secrets() -> None:
    """初始化密钥管理系统"""
    try:
        _ensure_secrets_dir()
        _generate_master_key()

        # 如果有环境变量中的密钥，自动保存到加密存储
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                set_anthropic_key(os.environ.get("ANTHROPIC_API_KEY"))
                print("✅ Anthropic API密钥已保存到加密存储")
            except SecretsError:
                pass  # 忽略已存在的密钥

    except Exception as e:
        print(f"⚠️ 密钥管理系统初始化失败: {e}")

# 命令行工具
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python secrets_manager.py <command> [args...]")
        print("命令:")
        print("  init                    - 初始化密钥管理系统")
        print("  set <key> <value>       - 设置密钥")
        print("  get <key>               - 获取密钥")
        print("  delete <key>            - 删除密钥")
        print("  list                    - 列出所有密钥")
        print("  set-anthropic <key>     - 设置Anthropic API密钥")
        print("  get-anthropic           - 获取Anthropic API密钥")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "init":
            init_secrets()
            print("密钥管理系统已初始化")

        elif command == "set":
            if len(sys.argv) < 4:
                print("需要提供密钥名和值")
                sys.exit(1)
            key, value = sys.argv[2], sys.argv[3]
            set_secret(key, value)
            print(f"密钥 '{key}' 已设置")

        elif command == "get":
            if len(sys.argv) < 3:
                print("需要提供密钥名")
                sys.exit(1)
            key = sys.argv[2]
            value = get_secret(key)
            if value:
                print(f"{key}: {_mask_secret_value(value)}")
            else:
                print(f"密钥 '{key}' 不存在")

        elif command == "delete":
            if len(sys.argv) < 3:
                print("需要提供密钥名")
                sys.exit(1)
            key = sys.argv[2]
            if delete_secret(key):
                print(f"密钥 '{key}' 已删除")
            else:
                print(f"密钥 '{key}' 不存在")

        elif command == "list":
            secrets = list_secrets()
            if not secrets:
                print("没有存储的密钥")
            else:
                print("存储的密钥:")
                for key, masked_value in secrets.items():
                    print(f"  {key}: {masked_value}")

        elif command == "set-anthropic":
            if len(sys.argv) < 3:
                print("需要提供API密钥")
                sys.exit(1)
            key = sys.argv[2]
            set_anthropic_key(key)
            print("Anthropic API密钥已设置")

        elif command == "get-anthropic":
            key = get_anthropic_key()
            if key:
                print(f"Anthropic Key: {_mask_secret_value(key)}")
            else:
                print("Anthropic API密钥未设置")

        else:
            print(f"未知命令: {command}")
            sys.exit(1)

    except SecretsError as e:
        print(f"密钥管理错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)