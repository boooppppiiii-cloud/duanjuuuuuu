from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .base import PublishChannel, PublishPayload, PublishResult
from ..social_integrations import youtube_access_token


class YouTubeChannel(PublishChannel):
    def publish(self, payload: PublishPayload) -> PublishResult:
        from google.oauth2.credentials import Credentials
        token = youtube_access_token(payload.account)
        service = build("youtube", "v3", credentials=Credentials(token=token), cache_discovery=False)
        options = payload.job.publish_options or {}
        privacy = str(options.get("youtube_privacy") or payload.account.credentials_json.get("default_privacy") or "private")
        if privacy not in {"private", "unlisted", "public"}:
            raise RuntimeError("YouTube 可见性必须是 private、unlisted 或 public")
        body = {
            "snippet": {"title": payload.post.title[:100], "description": payload.post.caption, "tags": [x.lstrip("#") for x in payload.post.hashtags][:30], "categoryId": str(payload.account.credentials_json.get("category_id") or "24")},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(options.get("made_for_kids", False)), "containsSyntheticMedia": bool(payload.job.ai_disclosure)},
        }
        request = service.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(payload.video), mimetype="video/mp4", resumable=True))
        result = request.execute()
        video_id = str(result.get("id") or "")
        if not video_id:
            raise RuntimeError("YouTube 上传完成但未返回视频 ID")
        return PublishResult(success=True, video_id=video_id, log=f"YouTube 已接收视频，当前可见性：{privacy}", status="submitted", platform_url=f"https://www.youtube.com/watch?v={video_id}")
