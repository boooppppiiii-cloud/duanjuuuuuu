from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from PIL import Image, ImageOps
from sqlmodel import Session

from ..config import get_settings
from ..models import Account, Clip, Drama, Post, PublishJob
from .credentials import resolve_account_secret
from .finalizer import finalize_video
from .publish import CHANNEL_REGISTRY
from .publish.base import PublishPayload
from .social_integrations import TIKTOK_API, _youtube_analytics, bearer_headers, graph_version, publish_first_comment, tiktok_access_token, youtube_access_token
from .radar_search import register_owned_video


def _first_comment_text(job: PublishJob) -> str:
    options = job.publish_options or {}
    comments = options.get("first_comments") or {}
    if isinstance(comments, dict):
        return str(comments.get(str(job.post_id)) or "").strip()
    return ""


def _set_first_comment_state(job: PublishJob, **updates: object) -> None:
    options = dict(job.publish_options or {})
    options.update(updates)
    job.publish_options = options


def _try_first_comment(job: PublishJob, account: Account) -> bool:
    text = _first_comment_text(job)
    if not text or (job.publish_options or {}).get("first_comment_status") == "published":
        return True
    attempts = int((job.publish_options or {}).get("first_comment_attempts") or 0) + 1
    try:
        comment_id = publish_first_comment(account, job.platform_video_id, text)
        _set_first_comment_state(job, first_comment_status="published", first_comment_id=comment_id, first_comment_attempts=attempts, first_comment_error="")
        job.result_log = f"{job.result_log.rstrip()}；首条评论已真实发布"
        return True
    except Exception as exc:
        _set_first_comment_state(job, first_comment_status="failed", first_comment_attempts=attempts, first_comment_error=str(exc)[:1000])
        job.result_log = f"{job.result_log.rstrip()}；视频已提交，但首条评论失败：{exc}"
        return False


def prepare_publish_cover(source: Path, target: Path) -> Path:
    """Create a YouTube-safe 16:9 JPEG below the official 2 MB limit."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1280, 720), "#111411")
        canvas.paste(image, ((1280 - image.width) // 2, (720 - image.height) // 2))
        for quality in (90, 82, 74, 66):
            canvas.save(target, "JPEG", quality=quality, optimize=True, progressive=True)
            if target.stat().st_size <= 2 * 1024 * 1024:
                return target
    raise RuntimeError("封面压缩后仍超过 YouTube 2MB 限制")


def notify_serverchan(message: str) -> None:
    key = get_settings().serverchan_key
    if key:
        try:
            httpx.post(f"https://sctapi.ftqq.com/{key}.send", data={"title": "短剧发布任务", "desp": message}, timeout=15)
        except Exception:
            pass


def execute_publish_job(session: Session, job: PublishJob) -> PublishJob:
    post = session.get(Post, job.post_id)
    account = session.get(Account, job.account_id)
    clip = session.get(Clip, post.clip_id) if post else None
    drama = session.get(Drama, clip.drama_id) if clip else None
    if not all((post, account, clip, drama)):
        raise RuntimeError("发布任务关联数据不完整")
    if account.status != "connected":
        job.status = "blocked"; job.result_log = "账号尚未通过真实连接检测，请先到账号矩阵完成连接"
        session.add(job); session.commit(); session.refresh(job)
        return job
    first_comment = _first_comment_text(job)
    if first_comment and account.platform == "tiktok":
        job.status = "blocked"
        job.result_log = "TikTok 当前官方商业 API 不支持创建评论，请清空首条评论后再发布"
        session.add(job); session.commit(); session.refresh(job)
        return job
    channel_cls = CHANNEL_REGISTRY.get(account.platform)
    if not channel_cls:
        job.status = "blocked"; job.result_log = f"平台 {account.platform} 没有可用的官方发布接口"
        session.add(job); session.commit(); session.refresh(job)
        return job
    if drama.is_ai_generated:
        job.ai_disclosure = True
        if "#aigc" not in post.caption.casefold():
            post.caption = f"{post.caption.rstrip()}\nAI-generated content #AIGC"
    settings = get_settings()
    job.status = "uploading"; job.result_log = "正在向平台官方接口上传"
    session.add(post); session.add(job); session.commit()
    session.refresh(job); session.refresh(post); session.refresh(account); session.refresh(clip)
    try:
        # Build a transient delivery copy rather than copying SQLAlchemy's
        # persistence state.  The latter becomes detached after commits and
        # can fail while a platform adapter reads the caption.
        delivery_post = Post.model_validate(post.model_dump())
        if "{app_link}" in delivery_post.caption:
            app_link = str(account.credentials_json.get("app_link") or "").strip()
            if not app_link:
                raise RuntimeError(f"账号“{account.name}”未配置官方观看链接，不能发布包含 {{app_link}} 占位符的文案")
            delivery_post.caption = delivery_post.caption.replace("{app_link}", app_link)
        video = finalize_video(settings.ffmpeg_binary, Path(clip.file_path), account.account_type, settings.media_root / "assets", settings.media_root / "posts" / "final_cache")
        job.final_video_path = str(video)
        session.add(job); session.commit(); session.refresh(job)
        cover_fields = {"vertical": drama.cover_vertical_path, "square": drama.cover_square_path, "horizontal": drama.cover_horizontal_path}
        cover_kind = str((job.publish_options or {}).get("cover_kind") or "")
        source_cover = Path(cover_fields.get(cover_kind) or "") if cover_kind else None
        cover = prepare_publish_cover(source_cover, settings.media_root / "posts" / "final_cache" / f"cover_job_{job.id}.jpg") if source_cover and source_cover.is_file() else None
        payload = PublishPayload(job=job, post=delivery_post, account=account, video=video, package_root=settings.media_root / "packages", cover=cover)
        result = channel_cls().publish(payload)
        if not result.success or not result.video_id:
            raise RuntimeError(result.log or "平台未返回可追踪的发布 ID")
        job.status = result.status
        job.platform_video_id = result.video_id
        job.platform_url = result.platform_url
        job.result_log = result.log
        job.submitted_at = datetime.now()
        if result.status == "published":
            job.completed_at = datetime.now()
            if first_comment and not _try_first_comment(job, account) and int((job.publish_options or {}).get("first_comment_attempts") or 0) < 3:
                job.status = "submitted"
        elif first_comment:
            _set_first_comment_state(job, first_comment_status="pending", first_comment_attempts=0, first_comment_error="")
    except Exception as exc:
        job.retry_count += 1
        job.status = "failed"
        job.result_log = str(exc)[:2000]
        notify_serverchan(f"任务 #{job.id} 发布失败：{job.result_log}")
    session.add(post); session.add(job); session.commit(); session.refresh(job)
    if job.platform_video_id and job.status in {"submitted", "published"}:
        try:
            register_owned_video(session, account.platform, job.platform_video_id, job.platform_url, account.platform_user_id, account.name, post.title, drama.id)
            session.commit()
        except Exception:
            # Radar indexing is secondary and must never turn a successful
            # platform upload into a failed publishing job.
            session.rollback()
        session.refresh(job)
    return job


def refresh_publish_status(session: Session, job: PublishJob) -> PublishJob:
    account = session.get(Account, job.account_id)
    if not account or not job.platform_video_id:
        return job
    job.status_checked_at = datetime.now()
    try:
        if account.platform == "tiktok":
            token = tiktok_access_token(account)
            response = httpx.post(f"{TIKTOK_API}/v2/post/publish/status/fetch/", headers=bearer_headers(token), json={"publish_id": job.platform_video_id}, timeout=30)
            response.raise_for_status(); body = response.json()
            if body.get("error", {}).get("code") != "ok":
                raise RuntimeError(body.get("error", {}).get("message") or body.get("error", {}).get("code"))
            data = body.get("data", {}); status = str(data.get("status") or "")
            if status == "PUBLISH_COMPLETE":
                ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
                if ids:
                    job.platform_video_id = str(ids[0])
                job.status = "published"; job.completed_at = datetime.now(); job.result_log = "TikTok 已发布完成"
            elif status == "FAILED":
                job.status = "failed"; job.result_log = f"TikTok 发布失败：{data.get('fail_reason') or '未知原因'}"
            else:
                job.status = "submitted"; job.result_log = f"TikTok 处理中：{status or '未知状态'}"
        elif account.platform == "youtube":
            service = build("youtube", "v3", credentials=Credentials(token=youtube_access_token(account)), cache_discovery=False)
            items = service.videos().list(part="status,processingDetails", id=job.platform_video_id).execute().get("items", [])
            if not items:
                raise RuntimeError("YouTube 中找不到该视频")
            status = str(items[0].get("status", {}).get("uploadStatus") or "")
            if status == "processed":
                job.status = "published"; job.completed_at = datetime.now(); job.result_log = "YouTube 处理完成"
            elif status in {"failed", "rejected", "deleted"}:
                job.status = "failed"; job.result_log = f"YouTube 处理失败：{status}"
            else:
                job.status = "submitted"; job.result_log = f"YouTube 处理中：{status or 'uploaded'}"
        elif account.platform == "facebook":
            response = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{job.platform_video_id}", params={"fields": "id,status", "access_token": resolve_account_secret(account, "access_token")}, timeout=30)
            response.raise_for_status(); status = str(response.json().get("status", {}).get("video_status") or response.json().get("status") or "")
            if status.casefold() in {"ready", "published", "complete"}:
                job.status = "published"; job.completed_at = datetime.now(); job.result_log = "Facebook 处理完成"
            else:
                job.status = "submitted"; job.result_log = f"Facebook 处理中：{status or 'uploaded'}"
        elif account.platform == "instagram":
            response = httpx.get(
                f"https://graph.facebook.com/{graph_version(account)}/{job.platform_video_id}",
                params={"fields": "id", "access_token": resolve_account_secret(account, "access_token")},
                timeout=30,
            )
            response.raise_for_status()
            job.status = "published"; job.completed_at = job.completed_at or datetime.now(); job.result_log = "Instagram Reel 已发布"
        if job.status == "published" and _first_comment_text(job):
            if not _try_first_comment(job, account) and int((job.publish_options or {}).get("first_comment_attempts") or 0) < 3:
                job.status = "submitted"
    except Exception as exc:
        job.result_log = f"状态查询失败：{exc}"
    session.add(job); session.commit(); session.refresh(job)
    return job


def fetch_metrics(account: Account, video_id: str) -> dict[str, int | float | None]:
    result: dict[str, int | float | None] = {
        "views": 0, "likes": 0, "comments": 0, "impressions": None, "clicks": None, "ctr": None,
        "watch_time_seconds": None, "estimated_revenue": None, "rpm": None, "subscribers_gained": None,
    }
    if account.platform == "youtube":
        token = youtube_access_token(account)
        response = build("youtube", "v3", credentials=Credentials(token=token), cache_discovery=False).videos().list(part="statistics", id=video_id).execute()
        if not response.get("items"):
            raise RuntimeError("YouTube 视频不存在或无权访问")
        stats = response["items"][0].get("statistics", {})
        result.update({"views": int(stats.get("viewCount", 0)), "likes": int(stats.get("likeCount", 0)), "comments": int(stats.get("commentCount", 0))})
        analytics = _youtube_analytics(token, [video_id]).get(video_id, {})
        result.update({
            "impressions": int(analytics["videoThumbnailImpressions"]) if "videoThumbnailImpressions" in analytics else None,
            "ctr": analytics.get("videoThumbnailImpressionsClickRate"),
            "watch_time_seconds": round(analytics["estimatedMinutesWatched"] * 60) if "estimatedMinutesWatched" in analytics else None,
            "estimated_revenue": analytics.get("estimatedRevenue"),
            "subscribers_gained": int(analytics["subscribersGained"]) if "subscribersGained" in analytics else None,
        })
        result["rpm"] = float(result["estimated_revenue"]) / int(result["views"] or 0) * 1000 if result["estimated_revenue"] is not None and result["views"] else None
        return result
    if account.platform == "tiktok":
        token = tiktok_access_token(account)
        response = httpx.post(f"{TIKTOK_API}/v2/video/query/", params={"fields": "id,view_count,like_count,comment_count"}, headers=bearer_headers(token), json={"filters": {"video_ids": [video_id]}}, timeout=30)
        response.raise_for_status(); videos = response.json().get("data", {}).get("videos", [])
        if not videos:
            raise RuntimeError("TikTok 视频不存在或 video.list 未授权")
        item = videos[0]
        result.update({"views": int(item.get("view_count") or 0), "likes": int(item.get("like_count") or 0), "comments": int(item.get("comment_count") or 0)})
        return result
    token = resolve_account_secret(account, "access_token")
    if account.platform == "facebook":
        response = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}", params={"fields": "likes.summary(true),comments.summary(true)", "access_token": token}, timeout=30)
        response.raise_for_status(); data = response.json()
        insight = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}/video_insights", params={"metric": "total_video_views", "access_token": token}, timeout=30)
        insight.raise_for_status(); metrics = insight.json().get("data") or []
        metric = metrics[0] if metrics else {}; values = metric.get("values") or []
        views = int((values[-1] if values else {}).get("value") or metric.get("value") or 0)
        result.update({"views": views, "likes": int(data.get("likes", {}).get("summary", {}).get("total_count", 0)), "comments": int(data.get("comments", {}).get("summary", {}).get("total_count", 0))})
        extra = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}/video_insights", params={"metric": "total_video_view_total_time,total_video_impressions", "access_token": token}, timeout=30)
        if not extra.is_error:
            values = {}
            for metric in extra.json().get("data") or []:
                samples = metric.get("values") or []; values[str(metric.get("name") or "")] = (samples[-1] if samples else {}).get("value") or metric.get("value")
            result["impressions"] = int(values["total_video_impressions"]) if values.get("total_video_impressions") is not None else None
            result["watch_time_seconds"] = round(float(values["total_video_view_total_time"]) / 1000) if values.get("total_video_view_total_time") is not None else None
        return result
    if account.platform == "instagram":
        response = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}", params={"fields": "like_count,comments_count", "access_token": token}, timeout=30)
        response.raise_for_status(); data = response.json(); views = 0
        insight = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}/insights", params={"metric": "views", "access_token": token}, timeout=30)
        if not insight.is_error:
            metric = (insight.json().get("data") or [{}])[0]; values = metric.get("values") or []
            views = int((values[-1] if values else {}).get("value") or metric.get("total_value", {}).get("value") or metric.get("value") or 0)
        result.update({"views": views, "likes": int(data.get("like_count") or 0), "comments": int(data.get("comments_count") or 0)})
        watch = httpx.get(f"https://graph.facebook.com/{graph_version(account)}/{video_id}/insights", params={"metric": "total_watch_time", "access_token": token}, timeout=30)
        if not watch.is_error:
            metric = (watch.json().get("data") or [{}])[0]; values = metric.get("values") or []
            total_ms = (values[-1] if values else {}).get("value") or metric.get("total_value", {}).get("value") or metric.get("value")
            result["watch_time_seconds"] = round(float(total_ms) / 1000) if total_ms is not None else None
        return result
    raise RuntimeError(f"平台 {account.platform} 不支持指标回收")
