import time

import httpx

from ..credentials import resolve_account_secret
from ..social_integrations import graph_version
from ..public_media import build_public_video_url
from .base import PublishChannel, PublishPayload, PublishResult


class InstagramChannel(PublishChannel):
    def publish(self, payload: PublishPayload) -> PublishResult:
        options = payload.job.publish_options or {}
        urls = options.get("instagram_video_urls") or {}
        video_url = str(urls.get(str(payload.post.id)) or "").strip() if isinstance(urls, dict) else ""
        video_url = video_url or str(options.get("instagram_video_url") or "").strip() or build_public_video_url(payload.job.id)
        if not video_url.startswith("https://"):
            raise RuntimeError("Instagram 官方接口要求公网 HTTPS 视频地址，请在发布确认中填写 instagram_video_url")
        ig_user_id = str(payload.account.credentials_json.get("ig_user_id") or payload.account.platform_user_id)
        token = resolve_account_secret(payload.account, "access_token")
        version = graph_version(payload.account)
        caption = f"{payload.post.title}\n\n{payload.post.caption}".strip()
        create = httpx.post(f"https://graph.facebook.com/{version}/{ig_user_id}/media", params={"access_token": token, "media_type": "REELS", "video_url": video_url, "caption": caption}, timeout=60)
        create.raise_for_status(); creation_id = str(create.json().get("id") or "")
        if not creation_id:
            raise RuntimeError("Instagram 未返回媒体容器 ID")
        status = ""
        for _ in range(30):
            check = httpx.get(f"https://graph.facebook.com/{version}/{creation_id}", params={"access_token": token, "fields": "id,status,status_code"}, timeout=30)
            check.raise_for_status(); data = check.json(); status = str(data.get("status_code") or data.get("status") or "")
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                raise RuntimeError(f"Instagram 视频处理失败：{data.get('status') or status}")
            time.sleep(3)
        else:
            raise RuntimeError(f"Instagram 媒体容器仍在处理中：{status or '未知'}")
        publish = httpx.post(f"https://graph.facebook.com/{version}/{ig_user_id}/media_publish", params={"access_token": token, "creation_id": creation_id}, timeout=60)
        publish.raise_for_status(); media_id = str(publish.json().get("id") or "")
        if not media_id:
            raise RuntimeError("Instagram 发布接口未返回媒体 ID")
        details = httpx.get(f"https://graph.facebook.com/{version}/{media_id}", params={"access_token": token, "fields": "permalink"}, timeout=30)
        permalink = str(details.json().get("permalink") or "") if not details.is_error else ""
        return PublishResult(success=True, video_id=media_id, log="Instagram Reel 已发布", status="published", platform_url=permalink)
