from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from ..config import get_settings
from .credentials import CredentialError


def _key() -> bytes:
    secret = get_settings().credential_secret.strip()
    if not secret:
        raise CredentialError("尚未配置 CREDENTIAL_SECRET，不能生成 Instagram 临时媒体地址")
    return secret.encode("utf-8")


def _signature(job_id: int, expires: int) -> str:
    return hmac.new(_key(), f"{job_id}:{expires}".encode("utf-8"), hashlib.sha256).hexdigest()


def build_public_video_url(job_id: int, lifetime_seconds: int = 6 * 60 * 60) -> str:
    base = get_settings().public_media_base_url.strip().rstrip("/")
    if not base.startswith("https://"):
        raise CredentialError("Instagram 发布需要 PUBLIC_MEDIA_BASE_URL 指向可公网访问的 HTTPS 后端地址，或在发布页填写视频 HTTPS 地址")
    expires = int(time.time()) + lifetime_seconds
    query = urlencode({"expires": expires, "signature": _signature(job_id, expires)})
    return f"{base}/api/publish/media/{job_id}?{query}"


def verify_public_video_signature(job_id: int, expires: int, signature: str) -> bool:
    if expires < int(time.time()) or expires > int(time.time()) + 24 * 60 * 60:
        return False
    return hmac.compare_digest(_signature(job_id, expires), signature)
