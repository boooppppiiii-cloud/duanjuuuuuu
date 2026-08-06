"""Encrypted credential storage and environment-variable resolution.

Secrets are never returned by API responses. Direct secret storage is available only
when CREDENTIAL_SECRET is configured; otherwise account records may reference an
environment variable by name.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings
from ..models import Account


class CredentialError(RuntimeError):
    pass


def _fernet() -> Fernet:
    secret = get_settings().credential_secret.strip()
    if not secret:
        raise CredentialError("尚未配置 CREDENTIAL_SECRET，不能在应用内安全保存凭证；可先填写环境变量名")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialError("已保存凭证无法解密，请确认 CREDENTIAL_SECRET 未发生变化") from exc


def resolve_account_secret(account: Account, name: str, *, required: bool = True) -> str:
    encrypted = str(account.credentials_json.get(f"{name}_encrypted") or "")
    env_name = str(account.credentials_json.get(f"{name}_env") or "")
    value = decrypt_secret(encrypted) if encrypted else os.getenv(env_name, "") if env_name else ""
    if required and not value:
        hint = f"环境变量 {env_name}" if env_name else f"账号的 {name}"
        raise CredentialError(f"{hint} 尚未配置")
    return value


def store_secret_fields(current: dict, secrets: dict[str, str], secret_envs: dict[str, str]) -> dict:
    result = dict(current)
    for name, env_name in secret_envs.items():
        env_name = env_name.strip()
        if env_name:
            result[f"{name}_env"] = env_name
            result.pop(f"{name}_encrypted", None)
    for name, value in secrets.items():
        if value:
            result[f"{name}_encrypted"] = encrypt_secret(value)
            result.pop(f"{name}_env", None)
    return result


def sanitized_credentials(account: Account) -> dict:
    result: dict[str, object] = {}
    for key, value in account.credentials_json.items():
        if key.endswith("_encrypted"):
            result[key.removesuffix("_encrypted") + "_set"] = bool(value)
        elif not any(word in key.casefold() for word in ("token", "secret")) or key.endswith("_env"):
            result[key] = value
    return result
