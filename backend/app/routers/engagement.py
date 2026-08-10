from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Account, SocialComment
from ..schemas import CommentAnalyzeRequest, CommentImportRequest, CommentReplyRequest, CommentStatusRequest, CommentSyncRequest, YouTubeSyncRequest
from ..services.sentiment import ai_analysis, local_analysis
from ..services.llm import LLMUnavailableError
from ..services.social_integrations import list_comments, reply_to_comment
from ..services.offline_translation import translate_to_chinese, translation_status

router = APIRouter(prefix="/api/engagement", tags=["评论舆情"])


def _external_id(value: str, *parts: str) -> str:
    if value.strip(): return f"{parts[0]}:{value.strip()}"
    return "local-" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _refresh_local_translation(item: SocialComment, previous_text: str = "") -> None:
    if item.text_zh and previous_text == item.text_original:
        return
    translated = translate_to_chinese(item.text_original)
    if translated:
        item.text_zh = translated


@router.get("/comments", response_model=list[SocialComment])
def comments(platform: str = "", status: str = "", severity: str = "", session: Session = Depends(get_session)):
    statement = select(SocialComment)
    if platform: statement = statement.where(SocialComment.platform == platform)
    if status: statement = statement.where(SocialComment.status == status)
    if severity: statement = statement.where(SocialComment.severity == severity)
    return session.exec(statement.order_by(SocialComment.published_at.desc(), SocialComment.id.desc())).all()


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    rows = session.exec(select(SocialComment)).all()
    analyzed = [item for item in rows if item.sentiment != "unanalyzed"]
    sentiment = {key: sum(item.sentiment == key for item in analyzed) for key in ("positive", "negative", "neutral")}
    return {
        "total": len(rows), "analyzed": len(analyzed), "pending": sum(item.status == "pending" for item in rows),
        "needs_human": sum(item.needs_human and item.status not in {"resolved", "ignored"} for item in rows),
        "high_risk": sum(item.severity == "high" and item.status not in {"resolved", "ignored"} for item in rows),
        "buyer_intent": sum(item.user_status in {"potential_buyer", "dm_intent"} for item in rows),
        "sentiment": sentiment,
        "health": "urgent" if sentiment["negative"] > max(3, len(analyzed) * .3) else "watch" if sentiment["negative"] > max(1, len(analyzed) * .15) else "healthy",
    }


@router.get("/translation/status")
def local_translation_status():
    return translation_status()


@router.post("/comments/import")
def import_comments(payload: CommentImportRequest, session: Session = Depends(get_session)):
    created = 0; updated = 0
    for raw in payload.items:
        external_id = _external_id(raw.external_id, raw.platform, raw.video_id, raw.author_handle, raw.text_original)
        item = session.exec(select(SocialComment).where(SocialComment.external_id == external_id)).first()
        data = raw.model_dump(exclude={"external_id"})
        if item:
            previous_text = item.text_original
            for key, value in data.items(): setattr(item, key, value)
            updated += 1
        else:
            previous_text = ""
            item = SocialComment(external_id=external_id, **data); created += 1
        _refresh_local_translation(item, previous_text)
        session.add(item)
    session.commit()
    return {"created": created, "updated": updated}


@router.post("/comments/analyze")
def analyze_comments(payload: CommentAnalyzeRequest, session: Session = Depends(get_session)):
    statement = select(SocialComment)
    if payload.comment_ids: statement = statement.where(SocialComment.id.in_(payload.comment_ids))
    else: statement = statement.where(SocialComment.sentiment == "unanalyzed")
    rows = session.exec(statement.order_by(SocialComment.id).limit(500)).all()
    for item in rows:
        try:
            result = ai_analysis(item.text_original) if payload.use_ai else local_analysis(item.text_original)
        except LLMUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc
        for key, value in result.items(): setattr(item, key, value)
        session.add(item)
    session.commit()
    for item in rows: session.refresh(item)
    return {"analyzed": len(rows), "source": "ai-requested" if payload.use_ai else "local", "items": rows}


@router.post("/sync")
def sync_connected_accounts(payload: CommentSyncRequest, session: Session = Depends(get_session)):
    statement = select(Account).where(Account.status == "connected", Account.removed_at.is_(None))
    accounts = session.exec(statement.order_by(Account.id)).all()
    if payload.account_ids:
        accounts = [item for item in accounts if item.id in payload.account_ids]
    accounts = [item for item in accounts if item.platform in {"youtube", "facebook", "instagram", "tiktok"}]
    if not accounts:
        raise HTTPException(422, "没有已连接的可同步账号")
    result = {"created": 0, "updated": 0, "accounts": [], "errors": []}
    per_account = max(1, payload.max_comments // len(accounts))
    for account in accounts:
        try:
            rows = list_comments(account, per_account)
            created = 0; updated = 0
            for raw in rows:
                external_id = _external_id(raw["external_id"], account.platform, raw["video_id"], raw["author_handle"], raw["text_original"])
                item = session.exec(select(SocialComment).where(SocialComment.external_id == external_id)).first()
                values = {**raw, "platform": account.platform, "account_id": account.id, "published_at": _youtube_datetime(raw.get("published_at"))}
                values.pop("external_id", None)
                if item:
                    previous_text = item.text_original
                    for key, value in values.items(): setattr(item, key, value)
                    updated += 1
                else:
                    previous_text = ""
                    item = SocialComment(external_id=external_id, **values); created += 1
                _refresh_local_translation(item, previous_text)
                session.add(item)
            session.commit()
            result["created"] += created; result["updated"] += updated
            result["accounts"].append({"account_id": account.id, "name": account.name, "platform": account.platform, "fetched": len(rows)})
        except Exception as exc:
            result["errors"].append({"account_id": account.id, "name": account.name, "platform": account.platform, "error": str(exc)})
    if not result["accounts"]:
        raise HTTPException(422, {"message": "所有账号同步失败", "errors": result["errors"]})
    return result


@router.post("/comments/{comment_id}/reply", response_model=SocialComment)
def reply_comment(comment_id: int, payload: CommentReplyRequest, session: Session = Depends(get_session)):
    item = session.get(SocialComment, comment_id)
    if not item or not item.account_id:
        raise HTTPException(404, "评论或关联账号不存在")
    account = session.get(Account, item.account_id)
    if not account or account.status != "connected":
        raise HTTPException(422, "关联账号未连接")
    platform_id = item.external_id.split(":", 1)[1] if item.external_id.startswith(f"{item.platform}:") else item.external_id
    try:
        reply_id = reply_to_comment(account, platform_id, payload.message.strip())
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    item.reply_id = reply_id; item.reply_text = payload.message.strip(); item.replied_at = datetime.now(); item.status = "replied"
    session.add(item); session.commit(); session.refresh(item)
    return item


@router.patch("/comments/{comment_id}", response_model=SocialComment)
def update_status(comment_id: int, payload: CommentStatusRequest, session: Session = Depends(get_session)):
    item = session.get(SocialComment, comment_id)
    if not item: raise HTTPException(404, "评论不存在")
    item.status = payload.status; session.add(item); session.commit(); session.refresh(item)
    return item


def _youtube_datetime(value: str | None) -> datetime | None:
    if not value: return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError: return None


@router.post("/sync-youtube")
def sync_youtube(payload: YouTubeSyncRequest, session: Session = Depends(get_session)):
    settings = get_settings()
    if not settings.youtube_api_key:
        raise HTTPException(422, "尚未配置 YOUTUBE_API_KEY；可先使用评论文件导入，不影响其他功能")
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", developerKey=settings.youtube_api_key, cache_discovery=False)
    accounts = session.exec(select(Account).where(Account.platform == "youtube", Account.removed_at.is_(None))).all()
    if payload.account_ids: accounts = [item for item in accounts if item.id in payload.account_ids]
    channels: list[tuple[int | None, str]] = []
    for account in accounts:
        channel_id = str(account.credentials_json.get("channel_id") or "").strip()
        if channel_id: channels.append((account.id, channel_id))
    if not channels: channels = [(None, item) for item in settings.youtube_channel_id_list]
    if not channels: raise HTTPException(422, "没有可同步的 YouTube channel_id；请在账号非密钥信息或 YOUTUBE_CHANNEL_IDS 中填写")
    created = 0; updated = 0; videos_processed = 0
    for account_id, channel_id in channels:
        response = youtube.search().list(part="snippet", channelId=channel_id, type="video", order="date", maxResults=payload.max_videos).execute()
        for video in response.get("items", []):
            video_id = video.get("id", {}).get("videoId", "")
            if not video_id: continue
            videos_processed += 1
            token = None
            while True:
                try:
                    page = youtube.commentThreads().list(part="snippet", videoId=video_id, order="time", maxResults=100, pageToken=token).execute()
                except Exception:
                    break
                for thread in page.get("items", []):
                    top = thread.get("snippet", {}).get("topLevelComment", {})
                    snippet = top.get("snippet", {})
                    external_id = f"youtube:{str(top.get('id') or '')}"
                    if not external_id: continue
                    item = session.exec(select(SocialComment).where(SocialComment.external_id == external_id)).first()
                    values = {
                        "platform": "youtube", "account_id": account_id, "video_id": video_id,
                        "video_title": video.get("snippet", {}).get("title", ""), "author_name": snippet.get("authorDisplayName", ""),
                        "video_url": f"https://www.youtube.com/watch?v={video_id}",
                        "author_handle": snippet.get("authorChannelId", {}).get("value", ""),
                        "text_original": snippet.get("textOriginal") or snippet.get("textDisplay") or "",
                        "like_count": int(snippet.get("likeCount") or 0), "published_at": _youtube_datetime(snippet.get("publishedAt")),
                    }
                    if item:
                        previous_text = item.text_original
                        for key, value in values.items(): setattr(item, key, value)
                        updated += 1
                    else:
                        previous_text = ""
                        item = SocialComment(external_id=external_id, **values); created += 1
                    _refresh_local_translation(item, previous_text)
                    session.add(item)
                session.commit()
                token = page.get("nextPageToken")
                if not token: break
    return {"created": created, "updated": updated, "videos_processed": videos_processed}
