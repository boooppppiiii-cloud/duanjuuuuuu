import math
import httpx

from .base import PublishChannel,PublishPayload,PublishResult
from ..social_integrations import tiktok_access_token, tiktok_creator_info

class TikTokChannel(PublishChannel):
    INIT_URL="https://open.tiktokapis.com/v2/post/publish/video/init/"
    def publish(self,payload:PublishPayload)->PublishResult:
        token=tiktok_access_token(payload.account)
        options=payload.job.publish_options or {};creator=tiktok_creator_info(payload.account)
        privacy=str(options.get("tiktok_privacy") or "")
        if not privacy or privacy not in creator["privacy_level_options"]:
            raise RuntimeError("TikTok 发布前必须从 Creator Info 返回的可见性选项中明确选择")
        size=payload.video.stat().st_size;chunk=size if size<=64*1024*1024 else 10*1024*1024;total=max(1,math.ceil(size/chunk))
        caption=payload.post.caption.strip();caption_folded=caption.casefold()
        missing_tags=[tag for tag in payload.post.hashtags if tag.casefold() not in caption_folded]
        title="\n".join(part for part in [caption," ".join(missing_tags)] if part).strip()
        body={"post_info":{"title":title[:2200],"privacy_level":privacy,"disable_duet":bool(options.get("disable_duet",False) or creator["duet_disabled"]),"disable_comment":bool(options.get("disable_comment",False) or creator["comment_disabled"]),"disable_stitch":bool(options.get("disable_stitch",False) or creator["stitch_disabled"]),"video_cover_timestamp_ms":int(options.get("cover_timestamp_ms",1000)),"brand_content_toggle":bool(options.get("brand_content",False)),"brand_organic_toggle":bool(options.get("brand_organic",False)),"is_aigc":bool(payload.job.ai_disclosure)},"source_info":{"source":"FILE_UPLOAD","video_size":size,"chunk_size":chunk,"total_chunk_count":total}}
        response=httpx.post(self.INIT_URL,headers={"Authorization":f"Bearer {token}","Content-Type":"application/json; charset=UTF-8"},json=body,timeout=60);response.raise_for_status();data=response.json()
        if data.get("error",{}).get("code")!="ok":raise RuntimeError(f"TikTok 初始化失败：{data.get('error')}")
        upload=data["data"]["upload_url"]
        with payload.video.open("rb") as stream:
            offset=0
            while offset<size:
                raw=stream.read(min(chunk,size-offset));end=offset+len(raw)-1
                put=httpx.put(upload,headers={"Content-Type":"video/mp4","Content-Length":str(len(raw)),"Content-Range":f"bytes {offset}-{end}/{size}"},content=raw,timeout=300);put.raise_for_status();offset=end+1
        return PublishResult(success=True,video_id=data["data"]["publish_id"],log="TikTok Direct Post 已提交，等待平台处理",status="submitted")
