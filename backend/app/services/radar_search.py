from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlmodel import Session, select

from ..config import get_settings
from ..models import (
    AppUser,
    Drama,
    DramaSearchProfile,
    ExternalVideo,
    ExternalVideoMetric,
    MonitoredAccount,
    PromotionDramaPool,
    RadarQuotaUsage,
    RadarEvent,
    RadarScanLease,
    SearchQuery,
    SearchResult,
    SearchSnapshot,
    VideoMatchEvidence,
)
from .radar_accounts import authorization_for, normalize_account_name, normalize_profile_url
from .radar_pool import ensure_promotion_drama
from .radar_scoring import GROWTH_ABSOLUTE_MIN, GROWTH_RATE_MIN, RANK_CHANGE_THRESHOLD, classify_candidate, episode_like


SCAN_LOCK = threading.Lock()
DEFAULT_QUERY_SUFFIXES = ["", "full movie", "full episodes", "complete series", "episode 1", "ending", "where to watch"]
DAILY_SCAN_INTERVAL = timedelta(days=1)


def _quota_day(now: datetime | None = None) -> str:
    value = (now or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()


def quota_status(session: Session) -> dict[str, int | str]:
    settings = get_settings()
    day = _quota_day()
    row = session.get(RadarQuotaUsage, day)
    return {
        "quota_day": day,
        "search_calls": row.search_calls if row else 0,
        "search_limit": settings.radar_youtube_daily_search_limit,
        "used_units": row.used_units if row else 0,
        "unit_budget": settings.radar_youtube_daily_quota_budget,
        "scan_count": row.scan_count if row else 0,
        "failed_scan_count": row.failed_scan_count if row else 0,
    }


def _reserve_quota(session: Session, search_calls: int, estimated_units: int) -> None:
    settings = get_settings()
    day = _quota_day()
    row = session.get(RadarQuotaUsage, day) or RadarQuotaUsage(quota_day=day)
    if row.search_calls + search_calls > settings.radar_youtube_daily_search_limit:
        raise RuntimeError("今日 YouTube 搜索调用额度已达到安全上限，系统将在下一个配额日继续")
    if row.used_units + estimated_units > settings.radar_youtube_daily_quota_budget:
        raise RuntimeError("今日 YouTube API 安全预算已用完，系统将在下一个配额日继续")
    row.search_calls += search_calls
    row.used_units += estimated_units
    row.scan_count += 1
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()


def _record_failed_scan(session: Session) -> None:
    row = session.get(RadarQuotaUsage, _quota_day())
    if row:
        row.failed_scan_count += 1
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()


def query_suggestions(official_title: str, aliases: list[str] | None = None, custom: list[str] | None = None) -> list[dict[str, str]]:
    title = official_title.strip()
    values: list[tuple[str, str]] = []
    if title:
        values.extend((f"{title} {suffix}".strip(), "official_title" if not suffix else ("where_to_watch" if suffix == "where to watch" else "full_series" if "full" in suffix or "complete" in suffix else "episode")) for suffix in DEFAULT_QUERY_SUFFIXES)
    values.extend((item.strip(), "alias") for item in (aliases or []) if item.strip())
    values.extend((item.strip(), "custom") for item in (custom or []) if item.strip())
    seen: set[str] = set(); result: list[dict[str, str]] = []
    for text, kind in values:
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key); result.append({"text": text, "type": kind})
    return result


def sync_queries(session: Session, profile: DramaSearchProfile) -> list[SearchQuery]:
    suggestions = query_suggestions(profile.official_title, profile.aliases, profile.custom_queries)
    existing = session.exec(select(SearchQuery).where(SearchQuery.drama_id == profile.drama_id)).all()
    by_text = {(row.query_text.casefold(), row.region, row.language): row for row in existing}
    desired: list[SearchQuery] = []
    desired_keys: set[tuple[str, str, str]] = set()
    index = 0
    for region in (profile.regions or ["US"]):
        for language in (profile.languages or ["en"]):
            for suggestion in suggestions:
                key = (suggestion["text"].casefold(), region, language)
                desired_keys.add(key)
                row = by_text.get(key) or SearchQuery(
                    drama_id=profile.drama_id, query_text=suggestion["text"], query_type=suggestion["type"],
                    region=region, language=language, enabled=index < 8,
                )
                row.query_type = suggestion["type"]
                row.weight = max(.25, 1 - index * .02)
                session.add(row); desired.append(row); index += 1
    for row in existing:
        if (row.query_text.casefold(), row.region, row.language) not in desired_keys:
            row.enabled = False; session.add(row)
    session.commit()
    return desired


def _duration(value: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    days, hours, minutes, seconds = [int(item or 0) for item in match.groups()]
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _youtube_search(youtube: Any, query: SearchQuery) -> list[str]:
    response = youtube.search().list(
        part="snippet", q=query.query_text, type="video", order="relevance", maxResults=10,
        regionCode=query.region or None, relevanceLanguage=query.language or None, safeSearch="none",
    ).execute(num_retries=2)
    return [item.get("id", {}).get("videoId", "") for item in response.get("items", []) if item.get("id", {}).get("videoId")]


def _youtube_details(youtube: Any, video_ids: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    videos: dict[str, dict] = {}; channels: dict[str, dict] = {}
    for start in range(0, len(video_ids), 50):
        response = youtube.videos().list(part="snippet,contentDetails,statistics,status", id=",".join(video_ids[start:start + 50])).execute(num_retries=2)
        for item in response.get("items", []): videos[item["id"]] = item
    channel_ids = list({item.get("snippet", {}).get("channelId", "") for item in videos.values()} - {""})
    for start in range(0, len(channel_ids), 50):
        response = youtube.channels().list(part="snippet,statistics", id=",".join(channel_ids[start:start + 50])).execute(num_retries=2)
        for item in response.get("items", []): channels[item["id"]] = item
    return videos, channels


def _match_account(session: Session, channel_id: str, channel_name: str, channel_url: str) -> MonitoredAccount | None:
    if channel_id:
        row = session.exec(select(MonitoredAccount).where(
            MonitoredAccount.platform == "youtube", MonitoredAccount.platform_account_id == channel_id,
            MonitoredAccount.active == True,  # noqa: E712
        )).first()
        if row: return row
    normalized_url = normalize_profile_url(channel_url)
    if normalized_url:
        row = session.exec(select(MonitoredAccount).where(
            MonitoredAccount.platform == "youtube", MonitoredAccount.normalized_profile_url == normalized_url,
            MonitoredAccount.active == True,  # noqa: E712
        )).first()
        if row: return row
    return session.exec(select(MonitoredAccount).where(
        MonitoredAccount.platform == "youtube", MonitoredAccount.normalized_name == normalize_account_name(channel_name),
        MonitoredAccount.active == True,  # noqa: E712
    )).first()


def ensure_owned_monitored_account(session: Session, platform: str, account_id: str, display_name: str, profile_url: str = "") -> MonitoredAccount | None:
    if platform != "youtube" or not account_id:
        return None
    row = session.exec(select(MonitoredAccount).where(
        MonitoredAccount.platform == platform, MonitoredAccount.platform_account_id == account_id,
    )).first()
    if not row:
        row = MonitoredAccount(platform=platform, platform_account_id=account_id, display_name=display_name, relationship_type="own_official", authorization_status="authorized", source="published_content")
    row.display_name = display_name or row.display_name
    row.profile_url = profile_url or row.profile_url
    row.normalized_profile_url = normalize_profile_url(row.profile_url)
    row.normalized_name = normalize_account_name(row.display_name)
    row.relationship_type = "own_official"; row.authorization_status = "authorized"; row.allowed_full_series = True; row.active = True; row.updated_at = datetime.utcnow()
    session.add(row); session.flush(); return row


def register_owned_video(session: Session, platform: str, video_id: str, video_url: str, account_id: str, account_name: str, title: str, drama_id: int | None) -> None:
    if platform != "youtube" or not video_id:
        return
    account = ensure_owned_monitored_account(session, platform, account_id, account_name)
    video = session.exec(select(ExternalVideo).where(ExternalVideo.platform == platform, ExternalVideo.platform_video_id == video_id)).first() or ExternalVideo(platform=platform, platform_video_id=video_id)
    video.video_url = video_url; video.title = title; video.channel_id = account_id; video.channel_name = account_name
    video.matched_account_id = account.id if account else None; video.classification = "own"; video.review_status = "reviewed"; video.last_seen_at = datetime.utcnow()
    session.add(video); session.flush()
    if drama_id and account:
        from ..models import MonitoredAccountDrama
        link = session.exec(select(MonitoredAccountDrama).where(MonitoredAccountDrama.account_id == account.id, MonitoredAccountDrama.drama_id == drama_id)).first()
        if not link: session.add(MonitoredAccountDrama(account_id=account.id, drama_id=drama_id, relationship_override="own_official", authorization_status_override="authorized", allowed_full_series_override=True))
        ensure_promotion_drama(session, drama_id, "owned_publish", account_id=account.id, video_id=video.id)


def _classification(relationship: str, authorized: bool) -> str:
    if relationship in {"own_official", "own_creator"}: return "own"
    if authorized: return "authorized"
    return "unknown"


def _acquire_lease(session: Session, name: str, ttl_minutes: int = 30) -> bool:
    now = datetime.utcnow()
    lease = session.get(RadarScanLease, name)
    if lease and lease.expires_at > now:
        return False
    if not lease:
        lease = RadarScanLease(name=name, expires_at=now)
    lease.acquired_at = now; lease.expires_at = now + timedelta(minutes=ttl_minutes)
    session.add(lease); session.commit()
    return True


def _release_lease(session: Session, name: str) -> None:
    lease = session.get(RadarScanLease, name)
    if lease:
        lease.expires_at = datetime.utcnow(); session.add(lease); session.commit()


def _event(session: Session, drama: Drama, video: ExternalVideo, result: SearchResult, view_growth: int | None = None, previous_views: int | None = None) -> None:
    if result.rank > 5:
        return
    event_type = "new_top_five"
    severity = "opportunity"
    title = f"新视频进入《{drama.title}》标准监测前五"
    if video.classification == "suspected_full_reupload" and result.rank <= 3:
        event_type = "suspected_full_top_three"; severity = "high"; title = f"《{drama.title}》疑似全集进入标准监测前三"
    elif video.classification == "suspected_external_redirect":
        event_type = "suspected_external_redirect"; severity = "high"; title = f"《{drama.title}》出现疑似外链截流"
    elif video.classification == "suspected_impersonation":
        event_type = "suspected_impersonation"; severity = "high"; title = f"《{drama.title}》出现疑似冒充官方账号"
    elif result.relationship_type in {"own_official", "own_creator"} and result.rank <= 3:
        event_type = "owned_top_three"; severity = "positive"; title = f"我方内容进入《{drama.title}》标准监测前三"
    elif result.authorization_status == "authorized" and result.rank <= 3:
        event_type = "authorized_top_three"; severity = "positive"; title = f"授权内容进入《{drama.title}》标准监测前三"
    elif result.previous_rank and result.previous_rank - result.rank >= RANK_CHANGE_THRESHOLD:
        event_type = "rank_growth"; severity = "opportunity"; title = f"《{drama.title}》外部视频排名明显上升"
    elif view_growth is not None and previous_views is not None and view_growth >= GROWTH_ABSOLUTE_MIN and view_growth / max(previous_views, 1) >= GROWTH_RATE_MIN:
        event_type = "view_growth"; severity = "opportunity"; title = f"《{drama.title}》外部视频播放增长加快"
    existing = session.exec(select(RadarEvent).where(
        RadarEvent.drama_id == drama.id, RadarEvent.external_video_id == video.id,
        RadarEvent.event_type == event_type, RadarEvent.status.in_(["new", "watching"]),
    )).first()
    evidence = {"rank": result.rank, "previous_rank": result.previous_rank, "view_growth": view_growth, "thumbnail_url": result.thumbnail_url, "video_url": result.video_url, "platform": "youtube", "classification": video.classification}
    if existing:
        existing.last_detected_at = datetime.utcnow(); existing.evidence_json = evidence; session.add(existing); return
    session.add(RadarEvent(drama_id=drama.id, external_video_id=video.id, event_type=event_type, severity=severity, title=title, summary=f"{result.channel_name} 发布的视频当前位于第 {result.rank} 位。", evidence_json=evidence))


def scan_drama(session: Session, drama_id: int, user: AppUser | None = None, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    if not settings.youtube_api_key:
        raise RuntimeError("尚未配置 YOUTUBE_API_KEY，系统不会生成模拟搜索结果")
    drama = session.get(Drama, drama_id)
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first()
    if not drama or not profile:
        raise ValueError("剧目搜索配置不存在")
    pool = session.exec(select(PromotionDramaPool).where(PromotionDramaPool.drama_id == drama_id, PromotionDramaPool.active == True)).first()  # noqa: E712
    if not pool:
        raise RuntimeError("该剧目不在推广剧目池中，请先确认加入后再监测")
    now = datetime.utcnow()
    if profile.last_scanned_at and now - profile.last_scanned_at < timedelta(minutes=15) and not (force and user and user.is_developer):
        remaining = 15 - int((now - profile.last_scanned_at).total_seconds() // 60)
        raise RuntimeError(f"同一剧目 15 分钟内不重复消耗搜索配额，请约 {max(1, remaining)} 分钟后重试")
    query_budget = max(1, min(8, settings.radar_youtube_queries_per_drama))
    queries = session.exec(select(SearchQuery).where(SearchQuery.drama_id == drama_id, SearchQuery.enabled == True).order_by(SearchQuery.weight.desc())).all()[:query_budget]  # noqa: E712
    if not queries:
        queries = [row for row in sync_queries(session, profile) if row.enabled][:query_budget]
    if not SCAN_LOCK.acquire(blocking=False):
        raise RuntimeError("传播雷达正在执行另一轮扫描，请稍后重试")
    lease_name = "youtube_global_scan"
    if not _acquire_lease(session, lease_name):
        SCAN_LOCK.release()
        raise RuntimeError("另一台服务实例正在执行传播扫描，请稍后重试")
    try:
        estimated_units = len(queries) + 2
        _reserve_quota(session, len(queries), estimated_units)
        youtube = build("youtube", "v3", developerKey=settings.youtube_api_key, cache_discovery=False)
        if hasattr(youtube, "_http"):
            youtube._http.timeout = 20
        ids_by_query: dict[int, list[str]] = {}
        for query in queries:
            ids_by_query[query.id] = _youtube_search(youtube, query)
        all_ids = list(dict.fromkeys(video_id for ids in ids_by_query.values() for video_id in ids))
        videos, channels = _youtube_details(youtube, all_ids)
        episode_counts: dict[str, int] = {}
        for item in videos.values():
            channel_id = item.get("snippet", {}).get("channelId", "")
            if channel_id and episode_like(item.get("snippet", {}).get("title", "")):
                episode_counts[channel_id] = episode_counts.get(channel_id, 0) + 1
        snapshots: list[int] = []
        for query in queries:
            previous = session.exec(select(SearchSnapshot).where(
                SearchSnapshot.query_id == query.id, SearchSnapshot.collection_status == "success",
            ).order_by(SearchSnapshot.captured_at.desc())).first()
            previous_ranks = {}
            if previous:
                previous_ranks = {row.platform_video_id: row.rank for row in session.exec(select(SearchResult).where(SearchResult.snapshot_id == previous.id)).all()}
            snapshot = SearchSnapshot(drama_id=drama_id, query_id=query.id, region=query.region, language=query.language, result_count=len(ids_by_query[query.id]))
            session.add(snapshot); session.flush(); snapshots.append(snapshot.id)
            for rank, video_id in enumerate(ids_by_query[query.id], start=1):
                item = videos.get(video_id, {}); snippet = item.get("snippet", {}); stats = item.get("statistics", {}); content = item.get("contentDetails", {})
                channel_id = snippet.get("channelId", ""); channel = channels.get(channel_id, {}); channel_snippet = channel.get("snippet", {}); channel_stats = channel.get("statistics", {})
                channel_name = snippet.get("channelTitle", channel_snippet.get("title", "")); channel_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
                account = _match_account(session, channel_id, channel_name, channel_url)
                published_at = _published(snippet.get("publishedAt")); duration_seconds = _duration(content.get("duration", ""))
                full_candidate = duration_seconds >= 20 * 60 and bool(re.search(r"\b(full|complete|all episodes?)\b", snippet.get("title", ""), re.I))
                authorization = authorization_for(session, account, drama_id, query.region, published_at, full_candidate)
                thumbnail = (snippet.get("thumbnails", {}).get("high") or snippet.get("thumbnails", {}).get("medium") or snippet.get("thumbnails", {}).get("default") or {}).get("url", "")
                external = session.exec(select(ExternalVideo).where(ExternalVideo.platform == "youtube", ExternalVideo.platform_video_id == video_id)).first()
                if not external:
                    external = ExternalVideo(platform_video_id=video_id)
                previous_metric = session.exec(select(ExternalVideoMetric).where(ExternalVideoMetric.external_video_id == external.id).order_by(ExternalVideoMetric.captured_at.desc())).first() if external.id else None
                external.video_url=f"https://www.youtube.com/watch?v={video_id}"; external.channel_id=channel_id; external.channel_name=channel_name
                external.title=snippet.get("title", ""); external.description=snippet.get("description", ""); external.thumbnail_url=thumbnail
                external.published_at=published_at; external.duration_seconds=duration_seconds; external.last_seen_at=now
                external.current_views=int(stats.get("viewCount", 0)); external.current_likes=int(stats.get("likeCount", 0)); external.current_comments=int(stats.get("commentCount", 0))
                external.matched_account_id=account.id if account else None
                decision = classify_candidate(
                    title=external.title, description=external.description, channel_name=external.channel_name,
                    duration_seconds=duration_seconds, authorized=authorization["authorized"], relationship_type=authorization["relationship_type"],
                    approved_domains=settings.radar_approved_redirect_domain_list, same_channel_episode_count=episode_counts.get(channel_id, 0),
                )
                if external.review_status != "reviewed":
                    external.classification = decision.classification
                session.add(external); session.flush()
                result = SearchResult(
                    snapshot_id=snapshot.id, drama_id=drama_id, platform_video_id=video_id, rank=rank, previous_rank=previous_ranks.get(video_id),
                    title=external.title, description=external.description, video_url=external.video_url, embed_url=f"https://www.youtube.com/embed/{video_id}", thumbnail_url=thumbnail,
                    channel_id=channel_id, channel_name=channel_name, channel_url=channel_url,
                    channel_avatar_url=(channel_snippet.get("thumbnails", {}).get("default") or {}).get("url", ""), channel_subscribers=int(channel_stats.get("subscriberCount", 0)) if channel_stats.get("subscriberCount") else None,
                    published_at=published_at, duration_seconds=duration_seconds, views=external.current_views, likes=external.current_likes, comments=external.current_comments,
                    tags=snippet.get("tags", []), matched_account_id=external.matched_account_id, relationship_type=authorization["relationship_type"], authorization_status=authorization["authorization_status"],
                )
                session.add(result); session.flush()
                session.add(ExternalVideoMetric(external_video_id=external.id, views=external.current_views, likes=external.current_likes, comments=external.current_comments, search_rank=rank, query_id=query.id))
                view_growth = max(0, external.current_views - previous_metric.views) if previous_metric else None
                _event(session, drama, external, result, view_growth, previous_metric.views if previous_metric else None)
                if decision.score and not session.exec(select(VideoMatchEvidence).where(VideoMatchEvidence.external_video_id == external.id, VideoMatchEvidence.drama_id == drama_id, VideoMatchEvidence.match_method == "metadata_rules")).first():
                    session.add(VideoMatchEvidence(external_video_id=external.id, drama_id=drama_id, match_method="metadata_rules", confidence=decision.score / 100, matched_seconds=duration_seconds, is_full_series_candidate=decision.classification == "suspected_full_reupload", evidence_json={"risk_score": decision.score, "reasons": decision.reasons}, analysis_status="completed"))
        profile.last_scanned_at = now; profile.next_scan_at = now + DAILY_SCAN_INTERVAL; profile.scan_interval_hours = 24; profile.last_error = ""; profile.consecutive_failures = 0
        pool.last_scanned_at = now; pool.next_scan_at = now + DAILY_SCAN_INTERVAL; pool.updated_at = now
        session.add(profile); session.add(pool); session.commit()
        return {"drama_id": drama_id, "captured_at": now, "snapshot_ids": snapshots, "query_count": len(queries), "unique_video_count": len(all_ids), "collection_source": "youtube_data_api", "quota": quota_status(session)}
    except (HttpError, OSError) as exc:
        session.rollback()
        _record_failed_scan(session)
        for query in queries:
            session.add(SearchSnapshot(drama_id=drama_id, query_id=query.id, region=query.region, language=query.language, result_count=0, collection_status="failed", error_message=str(exc)[:1000]))
        profile.last_error = str(exc)[:1000]; profile.consecutive_failures += 1
        delay = min(24, max(2, 2 ** profile.consecutive_failures))
        profile.next_scan_at = now + timedelta(hours=delay); session.add(profile); session.commit()
        raise RuntimeError(f"YouTube 官方接口请求失败：{exc}") from exc
    finally:
        _release_lease(session, lease_name)
        SCAN_LOCK.release()


def scan_due_profiles(session: Session) -> None:
    now = datetime.utcnow()
    pool_rows = session.exec(select(PromotionDramaPool).where(
        PromotionDramaPool.active == True,  # noqa: E712
        (PromotionDramaPool.next_scan_at == None) | (PromotionDramaPool.next_scan_at <= now),  # noqa: E711
    ).order_by(PromotionDramaPool.pinned.desc(), PromotionDramaPool.priority, PromotionDramaPool.next_scan_at)).all()
    for pool in pool_rows:
        try:
            scan_drama(session, pool.drama_id)
        except (RuntimeError, ValueError) as exc:
            if "额度" in str(exc) or "预算" in str(exc):
                break
            continue
