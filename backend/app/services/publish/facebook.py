import httpx

from .base import PublishChannel, PublishPayload, PublishResult
from ..credentials import resolve_account_secret
from ..social_integrations import graph_version


class FacebookChannel(PublishChannel):
    def publish(self, payload: PublishPayload) -> PublishResult:
        if payload.job.ai_disclosure and "#aigc" not in payload.post.caption.casefold():
            payload.post.caption = f"{payload.post.caption.rstrip()}\nAI-generated content #AIGC"
        page_id = payload.account.credentials_json.get("page_id", "")
        token = resolve_account_secret(payload.account, "access_token")
        if not token or not page_id:
            raise RuntimeError("Facebook 凭证缺失：请连接 Page 并配置 page_id")
        published = bool((payload.job.publish_options or {}).get("facebook_published", True))
        with payload.video.open("rb") as video:
            response = httpx.post(f"https://graph-video.facebook.com/{graph_version(payload.account)}/{page_id}/videos", data={"access_token": token, "title": payload.post.title[:255], "description": f"{payload.post.title}\n\n{payload.post.caption}", "published": str(published).lower()}, files={"source": (payload.video.name, video, "video/mp4")}, timeout=600)
        response.raise_for_status()
        video_id = str(response.json().get("id") or "")
        if not video_id:
            raise RuntimeError("Facebook 上传完成但未返回视频 ID")
        return PublishResult(success=True, video_id=video_id, log="Facebook 已接收视频，等待平台处理", status="submitted", platform_url=f"https://www.facebook.com/{page_id}/videos/{video_id}")
