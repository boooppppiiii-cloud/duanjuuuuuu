from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..database import get_session
from ..config import get_settings
from ..models import (
    AppUser,
    Account,
    Drama,
    DramaSearchProfile,
    ExternalVideo,
    ExternalVideoMetric,
    MonitoredAccount,
    PromotionDramaPool,
    RadarEvent,
    RightsCase,
    SearchQuery,
    SearchResult,
    SearchSnapshot,
    VideoMatchEvidence,
    SocialComment,
)
from ..services.auth import get_current_user
from ..services.radar_accounts import authorization_for, normalize_account_name, normalize_profile_url
from ..services.radar_evidence import build_evidence_package
from ..services.radar_pool import deactivate_promotion_drama, ensure_promotion_drama
from ..services.radar_content_analysis import CONTENT_STRUCTURE_METHOD
from ..services.radar_search import _recognize_theater_official, query_suggestions, quota_status, scan_drama, sync_queries
from ..services.social_integrations import list_platform_media, youtube_traffic_sources


router = APIRouter(prefix="/api/radar", tags=["传播雷达"])
_BRIEFING_TTL_SECONDS = 300
_briefing_cache: tuple[float, dict[str, Any]] | None = None
_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def _platform_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_BUSINESS_TZ)


def _traffic_label(source: str) -> str:
    return {
        "SHORTS": "Shorts 信息流",
        "YT_SEARCH": "YouTube 搜索",
        "RELATED_VIDEO": "推荐视频",
        "BROWSE": "浏览功能",
        "SUBSCRIBER": "订阅信息流",
        "NOTIFICATION": "通知",
        "EXT_URL": "外部网站",
        "PLAYLIST": "播放列表",
        "END_SCREEN": "片尾画面",
        "HASHTAGS": "话题标签",
        "ADVERTISING": "广告推广",
        "NO_LINK_OTHER": "其他 YouTube 功能",
    }.get(source, source.replace("_", " ").title())


def _full_episode_request(comment: SocialComment) -> bool:
    text = f"{comment.text_original} {comment.text_zh}".lower()
    phrases = (
        "全集", "完整版", "完整剧", "哪里看", "在哪看", "后续在哪", "下一集",
        "full episode", "full episodes", "full series", "complete series", "complete episode",
        "where can i watch", "where to watch", "watch the full", "all episodes", "next episode",
    )
    return any(phrase in text for phrase in phrases)


class AccountCreate(BaseModel):
    platform: Literal["youtube", "facebook", "instagram", "tiktok"] = "youtube"
    display_name: str = Field(min_length=1, max_length=200)
    platform_account_id: str = Field(default="", max_length=255)
    profile_url: str = Field(default="", max_length=500)
    relationship_type: Literal["own_creator", "own_official"] = "own_creator"
    notes: str = Field(default="", max_length=1000)


class AccountUpdate(BaseModel):
    platform: Literal["youtube", "facebook", "instagram", "tiktok"] | None = None
    display_name: str | None = None
    platform_account_id: str | None = None
    profile_url: str | None = None
    relationship_type: Literal["own_creator", "own_official"] | None = None
    notes: str | None = None
    active: bool | None = None


class SearchProfileUpdate(BaseModel):
    enabled: bool = True
    official_title: str = ""
    aliases: list[str] = Field(default_factory=list)
    disabled_aliases: list[str] = Field(default_factory=list)
    misspellings: list[str] = Field(default_factory=list)
    character_names: list[str] = Field(default_factory=list)
    custom_queries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=lambda: ["US"])
    languages: list[str] = Field(default_factory=lambda: ["en"])
    scan_interval_hours: int = Field(default=12, ge=4, le=168)
    priority: Literal["high", "normal", "low", "paused"] = "normal"
    queries: list[dict[str, Any]] = Field(default_factory=list)


class ClassificationUpdate(BaseModel):
    classification: Literal["own", "authorized", "external_promotion", "suspected_full_reupload", "suspected_episode_reupload", "suspected_impersonation", "suspected_external_redirect", "unknown"]
    note: str = ""


class EventUpdate(BaseModel):
    status: Literal["new", "watching", "confirmed_authorized", "dismissed", "sent_to_factory", "evidence_prepared", "resolved"]
    resolution_note: str = ""


class RightsCaseCreate(BaseModel):
    drama_id: int
    external_video_id: int
    rights_owner: str = ""
    notes: str = ""


class PromotionPoolUpsert(BaseModel):
    source: Literal["manual_confirmed", "owned_publish", "external_market"] = "manual_confirmed"
    note: str = ""
    pinned: bool = False
    priority: Literal["normal", "low"] = "normal"
    external_video_id: int | None = None


class FactoryHandoffCreate(BaseModel):
    drama_id: int
    episode: str = ""
    source_start: float = Field(default=0, ge=0)
    source_end: float = Field(default=0, ge=0)
    opening_structure: str = ""
    reference_note: str = ""


def _apply_owned_account(row: MonitoredAccount, payload: AccountCreate | AccountUpdate) -> None:
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, key, value.strip() if isinstance(value, str) else value)
    row.display_name = row.display_name.strip()
    row.platform_account_id = row.platform_account_id.strip()
    row.profile_url = row.profile_url.strip()
    row.handle = row.display_name.lstrip("@")
    row.normalized_name = normalize_account_name(row.display_name)
    row.normalized_profile_url = normalize_profile_url(row.profile_url)
    row.authorization_status = "authorized"
    row.allowed_full_series = True
    row.authorized_regions = []
    row.authorization_start = None
    row.authorization_end = None
    row.company_name = ""
    row.source = "manual"
    row.updated_at = datetime.utcnow()


def _account_duplicate(session: Session, row: MonitoredAccount, exclude_id: int | None = None) -> MonitoredAccount | None:
    candidates = session.exec(select(MonitoredAccount).where(MonitoredAccount.platform == row.platform)).all()
    for candidate in candidates:
        if candidate.id == exclude_id:
            continue
        if row.platform_account_id and candidate.platform_account_id == row.platform_account_id:
            return candidate
        if row.normalized_profile_url and candidate.normalized_profile_url == row.normalized_profile_url:
            return candidate
    return None


@router.post("/accounts", status_code=201)
def create_account(payload: AccountCreate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = MonitoredAccount(platform=payload.platform, display_name=payload.display_name)
    _apply_owned_account(row, payload)
    if not row.platform_account_id and not row.profile_url:
        raise HTTPException(422, "平台账号 ID 和账号主页至少填写一项")
    duplicate = _account_duplicate(session, row)
    if duplicate and duplicate.source == "removed":
        _apply_owned_account(duplicate, payload)
        duplicate.active = True
        session.add(duplicate); session.commit(); session.refresh(duplicate)
        return {**duplicate.model_dump(), "dramas": []}
    if duplicate:
        raise HTTPException(409, "该监测账号已经存在")
    session.add(row); session.commit(); session.refresh(row)
    return {**row.model_dump(), "dramas": []}


@router.get("/accounts")
def accounts(
    platform: str = "", relationship_type: str = "", query: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    _: AppUser = Depends(get_current_user), session: Session = Depends(get_session),
):
    rows = session.exec(select(MonitoredAccount).where(
        MonitoredAccount.source != "removed",
    ).order_by(MonitoredAccount.updated_at.desc())).all()
    if platform: rows = [row for row in rows if row.platform == platform]
    if relationship_type: rows = [row for row in rows if row.relationship_type == relationship_type]
    if query:
        needle = query.casefold(); rows = [row for row in rows if needle in row.display_name.casefold() or needle in row.platform_account_id.casefold() or needle in row.profile_url.casefold()]
    total = len(rows); sliced = rows[(page - 1) * page_size:page * page_size]
    items = []
    for row in sliced:
        items.append({**row.model_dump(), "dramas": []})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.put("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountUpdate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = session.get(MonitoredAccount, account_id)
    if not row: raise HTTPException(404, "监测账号不存在")
    _apply_owned_account(row, payload)
    if not row.display_name:
        raise HTTPException(422, "账号名称不能为空")
    if not row.platform_account_id and not row.profile_url:
        raise HTTPException(422, "平台账号 ID 和账号主页至少填写一项")
    if _account_duplicate(session, row, row.id):
        raise HTTPException(409, "该监测账号已经存在")
    session.add(row); session.commit(); session.refresh(row); return {**row.model_dump(), "dramas": []}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = session.get(MonitoredAccount, account_id)
    if not row: raise HTTPException(404, "监测账号不存在")
    row.active = False
    row.source = "removed"
    row.updated_at = datetime.utcnow()
    session.add(row); session.commit(); return {"ok": True}


@router.get("/dramas")
def radar_dramas(include_all: bool = False, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    pool = session.exec(select(PromotionDramaPool).where(PromotionDramaPool.active == True)).all()  # noqa: E712
    pool_by_drama = {row.drama_id: row for row in pool}
    dramas = session.exec(select(Drama).order_by(Drama.created_at.desc())).all()
    if not include_all:
        dramas = [drama for drama in dramas if drama.id in pool_by_drama]
    output = []
    for drama in dramas:
        profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama.id)).first()
        pool_row = pool_by_drama.get(drama.id)
        output.append({"id": drama.id, "title": drama.title, "theater": drama.theater, "language": drama.language, "monitoring_enabled": bool(profile and profile.enabled and pool_row), "in_promotion_pool": bool(pool_row), "pool_sources": pool_row.sources if pool_row else [], "last_scanned_at": profile.last_scanned_at if profile else None, "last_error": profile.last_error if profile else ""})
    return output


@router.get("/promotion-pool")
def promotion_pool(_: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(PromotionDramaPool).order_by(PromotionDramaPool.pinned.desc(), PromotionDramaPool.updated_at.desc())).all()
    return [{**row.model_dump(), "drama_title": (session.get(Drama, row.drama_id).title if session.get(Drama, row.drama_id) else "")} for row in rows]


@router.put("/promotion-pool/{drama_id}")
def upsert_promotion_pool(drama_id: int, payload: PromotionPoolUpsert, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    try:
        row = ensure_promotion_drama(session, drama_id, payload.source, video_id=payload.external_video_id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    row.pinned = payload.pinned; row.priority = payload.priority
    session.add(row); session.commit(); session.refresh(row)
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first()
    if profile:
        sync_queries(session, profile)
    return row


@router.delete("/promotion-pool/{drama_id}")
def remove_promotion_pool(drama_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    try:
        row = deactivate_promotion_drama(session, drama_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return {"ok": True, "id": row.id}


@router.get("/quota")
def radar_quota(_: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    return quota_status(session)


def _profile_payload(session: Session, drama: Drama, profile: DramaSearchProfile) -> dict:
    queries = session.exec(select(SearchQuery).where(SearchQuery.drama_id == drama.id).order_by(SearchQuery.weight.desc())).all()
    latest = session.exec(select(SearchSnapshot).where(SearchSnapshot.drama_id == drama.id, SearchSnapshot.collection_status == "success").order_by(SearchSnapshot.captured_at.desc())).first()
    top = session.exec(select(SearchResult).where(SearchResult.snapshot_id == latest.id).order_by(SearchResult.rank).limit(5)).all() if latest else []
    return {**profile.model_dump(), "drama_title": drama.title, "queries": queries, "suggestions": query_suggestions(profile.official_title or drama.title, profile.aliases, profile.custom_queries), "top_five": top}


@router.get("/dramas/{drama_id}/profile")
def get_profile(drama_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    drama = session.get(Drama, drama_id)
    if not drama: raise HTTPException(404, "剧目不存在")
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first()
    if not profile:
        profile = DramaSearchProfile(drama_id=drama_id, official_title=drama.title)
        session.add(profile); session.commit(); session.refresh(profile); sync_queries(session, profile)
    return _profile_payload(session, drama, profile)


@router.put("/dramas/{drama_id}/profile")
def update_profile(drama_id: int, payload: SearchProfileUpdate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    drama = session.get(Drama, drama_id)
    if not drama: raise HTTPException(404, "剧目不存在")
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first() or DramaSearchProfile(drama_id=drama_id)
    values = payload.model_dump(exclude={"queries"})
    for key, value in values.items(): setattr(profile, key, value)
    profile.updated_at = datetime.utcnow()
    profile.scan_interval_hours = 24
    session.add(profile); session.commit(); session.refresh(profile)
    if payload.enabled and payload.priority != "paused":
        pool = ensure_promotion_drama(session, drama_id, "manual_confirmed")
        pool.priority = "low" if payload.priority == "low" else "normal"
        session.add(pool)
        session.commit()
    else:
        pool = session.exec(select(PromotionDramaPool).where(PromotionDramaPool.drama_id == drama_id)).first()
        if pool:
            deactivate_promotion_drama(session, drama_id); session.commit()
    generated = sync_queries(session, profile)
    if payload.queries:
        enabled_ids = {int(item["id"]) for item in payload.queries if item.get("id") and item.get("enabled", True)}
        for row in session.exec(select(SearchQuery).where(SearchQuery.drama_id == drama_id)).all():
            row.enabled = row.id in enabled_ids; session.add(row)
        session.commit()
    return _profile_payload(session, drama, profile)


@router.post("/dramas/{drama_id}/scan")
def scan(drama_id: int, force: bool = False, user: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    try: return scan_drama(session, drama_id, user, force)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/dramas/{drama_id}/snapshots")
def snapshots(drama_id: int, query_id: int | None = None, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    statement = select(SearchSnapshot).where(SearchSnapshot.drama_id == drama_id)
    if query_id: statement = statement.where(SearchSnapshot.query_id == query_id)
    return session.exec(statement.order_by(SearchSnapshot.captured_at.desc()).limit(100)).all()


@router.get("/dramas/{drama_id}/search-live")
def search_live(drama_id: int, query_id: int | None = None, snapshot_id: int | None = None, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    drama = session.get(Drama, drama_id)
    if not drama: raise HTTPException(404, "剧目不存在")
    query = session.get(SearchQuery, query_id) if query_id else session.exec(select(SearchQuery).where(SearchQuery.drama_id == drama_id, SearchQuery.enabled == True).order_by(SearchQuery.weight.desc())).first()  # noqa: E712
    snapshot = session.get(SearchSnapshot, snapshot_id) if snapshot_id else (session.exec(select(SearchSnapshot).where(SearchSnapshot.drama_id == drama_id, SearchSnapshot.query_id == query.id, SearchSnapshot.collection_status == "success").order_by(SearchSnapshot.captured_at.desc())).first() if query else None)
    results = session.exec(select(SearchResult).where(SearchResult.snapshot_id == snapshot.id).order_by(SearchResult.rank)).all() if snapshot else []
    items = []
    theater_matches_updated = False
    for result in results:
        video = session.exec(select(ExternalVideo).where(ExternalVideo.platform == result.platform, ExternalVideo.platform_video_id == result.platform_video_id)).first()
        account = session.get(MonitoredAccount, video.matched_account_id) if video and video.matched_account_id else None
        recognized = _recognize_theater_official(session, drama, account, result.channel_id, result.channel_name, result.channel_url) if result.relationship_type not in {"own_official", "own_creator"} else account
        if recognized and result.relationship_type not in {"own_official", "own_creator"}:
            authorization = authorization_for(session, recognized, drama.id, query.region if query else "US", result.published_at, False)
            result.matched_account_id = recognized.id
            result.relationship_type = authorization["relationship_type"]
            result.authorization_status = authorization["authorization_status"]
            session.add(result)
            if video:
                video.matched_account_id = recognized.id
                session.add(video)
            theater_matches_updated = True
        latest_metric = session.exec(select(ExternalVideoMetric).where(ExternalVideoMetric.external_video_id == video.id).order_by(ExternalVideoMetric.captured_at.desc())).first() if video else None
        previous_metric = session.exec(select(ExternalVideoMetric).where(ExternalVideoMetric.external_video_id == video.id, ExternalVideoMetric.id != latest_metric.id).order_by(ExternalVideoMetric.captured_at.desc())).first() if video and latest_metric else None
        content_evidence = session.exec(select(VideoMatchEvidence).where(
            VideoMatchEvidence.external_video_id == video.id,
            VideoMatchEvidence.match_method == CONTENT_STRUCTURE_METHOD,
        ).order_by(VideoMatchEvidence.created_at.desc())).first() if video else None
        content_payload = content_evidence.evidence_json if content_evidence else {}
        items.append({
            **result.model_dump(),
            "external_video_id": video.id if video else None,
            "classification": video.classification if video else "unknown",
            "review_status": video.review_status if video else "pending",
            "view_growth": max(0, latest_metric.views - previous_metric.views) if latest_metric and previous_metric else None,
            "content_structure": content_payload.get("structure", "not_analyzed"),
            "content_analysis_status": content_evidence.analysis_status if content_evidence else "not_analyzed",
            "content_structure_confidence": content_evidence.confidence if content_evidence else 0,
            "continuous_story_ratio": content_payload.get("continuous_story_ratio", 0),
            "repetition_ratio": content_payload.get("repetition_ratio", 0),
            "content_structure_reason": content_payload.get("reason", ""),
            "content_structure_evidence": {
                "sequence": content_payload.get("sequence_evidence", []),
                "repetition": content_payload.get("repetition_evidence", []),
            },
        })
    if theater_matches_updated:
        session.commit()
    counts = {"own": 0, "authorized": 0, "unknown": 0, "risk": 0}
    for item in items[:10]:
        if item["relationship_type"] in {"own_official", "own_creator"}: counts["own"] += 1
        elif item["authorization_status"] == "authorized": counts["authorized"] += 1
        else: counts["unknown"] += 1
        counts["risk"] += int(str(item["classification"]).startswith("suspected_"))
    return {"drama": {"id": drama.id, "title": drama.title}, "query": query, "snapshot": snapshot, "results": items, "summary": {**counts, "first_owner": items[0]["relationship_type"] if items else "none"}, "standard_notice": "标准监测结果，实际用户结果可能受个性化影响", "stale": bool(snapshot and snapshot.collection_status != "success")}


@router.get("/videos/{video_id}")
def video_detail(video_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    video = session.get(ExternalVideo, video_id)
    if not video: raise HTTPException(404, "外部视频不存在")
    metrics = session.exec(select(ExternalVideoMetric).where(ExternalVideoMetric.external_video_id == video_id).order_by(ExternalVideoMetric.captured_at)).all()
    appearances = session.exec(select(SearchResult).where(SearchResult.platform_video_id == video.platform_video_id).order_by(SearchResult.created_at.desc())).all()
    content_evidence = session.exec(select(VideoMatchEvidence).where(
        VideoMatchEvidence.external_video_id == video_id,
        VideoMatchEvidence.match_method == CONTENT_STRUCTURE_METHOD,
    ).order_by(VideoMatchEvidence.created_at.desc())).first()
    return {
        **video.model_dump(), "metrics": metrics, "appearances": appearances,
        "content_analysis": ({
            **content_evidence.evidence_json,
            "analysis_status": content_evidence.analysis_status,
            "confidence": content_evidence.confidence,
            "created_at": content_evidence.created_at,
        } if content_evidence else None),
    }


@router.put("/videos/{video_id}/classification")
def classify_video(video_id: int, payload: ClassificationUpdate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    video = session.get(ExternalVideo, video_id)
    if not video: raise HTTPException(404, "外部视频不存在")
    video.classification = payload.classification; video.review_status = "reviewed"; video.review_note = payload.note
    session.add(video); session.commit(); session.refresh(video); return video


@router.post("/videos/{video_id}/send-to-factory")
def send_video_to_factory(video_id: int, payload: FactoryHandoffCreate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    video = session.get(ExternalVideo, video_id)
    drama = session.get(Drama, payload.drama_id)
    if not video or not drama:
        raise HTTPException(404, "外部视频或剧目不存在")
    if payload.source_end and payload.source_end <= payload.source_start:
        raise HTTPException(422, "原片结束时间必须晚于开始时间")
    evidence = VideoMatchEvidence(
        external_video_id=video.id, drama_id=drama.id, match_method="manual_factory_handoff",
        confidence=1 if payload.episode else .5, matched_seconds=max(0, payload.source_end - payload.source_start),
        episode_ranges=[{"episode": payload.episode, "start": payload.source_start, "end": payload.source_end}] if payload.episode else [],
        source_ranges=[{"start": payload.source_start, "end": payload.source_end}] if payload.source_end else [],
        evidence_json={"opening_structure": payload.opening_structure, "reference_note": payload.reference_note, "source_video_url": video.video_url},
        analysis_status="manual_confirmed" if payload.episode else "pending",
    )
    session.add(evidence)
    event = session.exec(select(RadarEvent).where(RadarEvent.external_video_id == video.id, RadarEvent.drama_id == drama.id, RadarEvent.status.in_(["new", "watching"]))).first()
    if event:
        event.status = "sent_to_factory"; session.add(event)
    session.commit(); session.refresh(evidence)
    params = {"drama": drama.id, "radar_video": video.id, "episode": payload.episode, "start": payload.source_start, "end": payload.source_end, "reference": video.title}
    from urllib.parse import urlencode
    return {"ok": True, "handoff_id": evidence.id, "factory_url": f"/factory?{urlencode(params)}", "source_video_url": video.video_url}


@router.get("/briefing")
def briefing(refresh: bool = False, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    """Team-shared daily operating brief built only from real platform and comment data."""
    global _briefing_cache
    if not refresh and _briefing_cache and monotonic() - _briefing_cache[0] < _BRIEFING_TTL_SECONDS:
        return _briefing_cache[1]

    now = datetime.now(_BUSINESS_TZ)
    yesterday = now.date() - timedelta(days=1)
    traffic_end = now.date() - timedelta(days=2)
    traffic_start = traffic_end - timedelta(days=6)
    accounts = session.exec(
        select(Account)
        .where(Account.status == "connected", Account.removed_at.is_(None))
        .order_by(Account.id)
    ).all()
    account_names = {int(item.id or 0): item.name for item in accounts}
    media_rows: list[dict[str, Any]] = []
    traffic_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def load_account(account: Account) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        account_errors: list[str] = []
        try:
            media = list_platform_media(account, 50, refresh)
        except Exception as exc:
            media = []
            account_errors.append(str(exc))
        traffic: list[dict[str, Any]] = []
        if account.platform == "youtube":
            try:
                traffic = youtube_traffic_sources(account, traffic_start, traffic_end, refresh)
            except Exception as exc:
                account_errors.append(str(exc))
        return media, traffic, account_errors

    if accounts:
        with ThreadPoolExecutor(max_workers=min(4, len(accounts))) as executor:
            jobs = {executor.submit(load_account, account): account for account in accounts}
            for future in as_completed(jobs):
                account = jobs[future]
                media, traffic, account_errors = future.result()
                media_rows.extend({
                    **item,
                    "account_id": account.id,
                    "account_name": account.name,
                    "platform": account.platform,
                } for item in media)
                traffic_rows.extend({**item, "account_id": account.id, "account_name": account.name} for item in traffic)
                if account_errors:
                    errors.append({"account_id": account.id, "account_name": account.name, "messages": account_errors})

    recent = []
    for item in media_rows:
        published = _platform_time(item.get("published_at"))
        if not published or published > now or published < now - timedelta(days=7):
            continue
        age_hours = max(1.0, (now - published).total_seconds() / 3600)
        recent.append((float(item.get("views") or 0) / age_hours, published, item))
    fastest = None
    if recent:
        speed, published, item = max(recent, key=lambda row: row[0])
        fastest = {
            "account_id": item["account_id"], "account_name": item["account_name"], "platform": item["platform"],
            "video_id": str(item.get("id") or ""), "title": item.get("title") or "未命名视频",
            "url": item.get("url") or "", "thumbnail_url": item.get("thumbnail_url") or "",
            "published_at": published.isoformat(), "views": int(item.get("views") or 0),
            "likes": int(item.get("likes") or 0), "comments": int(item.get("comments") or 0),
            "subscribers_gained": int(item.get("subscribers_gained") or 0),
            "views_per_hour": round(speed, 1), "metric_label": "近 7 日播放增速最快",
        }

    week_items = []
    for speed, published, item in recent:
        views = int(item.get("views") or 0)
        likes = int(item.get("likes") or 0)
        comments_count = int(item.get("comments") or 0)
        week_items.append({
            "account_id": item["account_id"], "account_name": item["account_name"], "platform": item["platform"],
            "video_id": str(item.get("id") or ""), "title": item.get("title") or "未命名视频",
            "url": item.get("url") or "", "thumbnail_url": item.get("thumbnail_url") or "",
            "published_at": published.isoformat(), "views": views, "likes": likes, "comments": comments_count,
            "subscribers_gained": int(item.get("subscribers_gained") or 0),
            "views_per_hour": round(speed, 1),
            "engagement_rate": round((likes + comments_count) / views * 100, 2) if views else 0,
        })
    week_items.sort(key=lambda item: item["published_at"], reverse=True)
    engagement_leader = max(week_items, key=lambda item: item["engagement_rate"], default=None)
    subscriber_candidates = [item for item in week_items if item["subscribers_gained"] > 0]
    subscriber_leader = max(subscriber_candidates, key=lambda item: item["subscribers_gained"], default=None)

    yesterday_items = []
    for item in media_rows:
        published = _platform_time(item.get("published_at"))
        if not published or published.date() != yesterday:
            continue
        yesterday_items.append({
            "account_id": item["account_id"], "account_name": item["account_name"], "platform": item["platform"],
            "video_id": str(item.get("id") or ""), "title": item.get("title") or "未命名视频",
            "url": item.get("url") or "", "thumbnail_url": item.get("thumbnail_url") or "",
            "published_at": published.isoformat(), "views": int(item.get("views") or 0),
            "likes": int(item.get("likes") or 0), "comments": int(item.get("comments") or 0),
            "subscribers_gained": int(item.get("subscribers_gained") or 0),
        })
    yesterday_items.sort(key=lambda item: item["views"], reverse=True)

    traffic_by_source: dict[str, dict[str, Any]] = {}
    for item in traffic_rows:
        source = str(item.get("source") or "")
        bucket = traffic_by_source.setdefault(source, {"source": source, "views": 0, "watch_time_seconds": 0})
        bucket["views"] += int(item.get("views") or 0)
        bucket["watch_time_seconds"] += int(item.get("watch_time_seconds") or 0)
    traffic_total = sum(item["views"] for item in traffic_by_source.values())
    traffic_sources = []
    if traffic_by_source and traffic_total:
        for item in sorted(traffic_by_source.values(), key=lambda row: row["views"], reverse=True)[:3]:
            traffic_sources.append({
                **item,
                "label": _traffic_label(item["source"]),
                "share": round(item["views"] / traffic_total * 100, 1),
                "range_start": traffic_start.isoformat(), "range_end": traffic_end.isoformat(),
            })
    traffic_source = traffic_sources[0] if traffic_sources else None

    comments = session.exec(
        select(SocialComment).order_by(SocialComment.published_at.desc(), SocialComment.id.desc()).limit(1000)
    ).all()
    full_episode_comments = [item for item in comments if _full_episode_request(item)]
    comment_payload = [{
        "id": item.id, "platform": item.platform, "account_id": item.account_id,
        "account_name": account_names.get(int(item.account_id or 0), ""),
        "author_name": item.author_name or item.author_handle or "观众",
        "text": item.text_zh or item.text_original, "text_original": item.text_original,
        "video_title": item.video_title, "video_url": item.video_url,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "like_count": item.like_count,
    } for item in full_episode_comments[:5]]

    alert_rows = session.exec(
        select(RadarEvent)
        .where(RadarEvent.severity == "high", RadarEvent.status.in_(["new", "watching"]))
        .order_by(RadarEvent.last_detected_at.desc())
        .limit(4)
    ).all()
    alerts = []
    for item in alert_rows:
        drama = session.get(Drama, item.drama_id)
        video = session.get(ExternalVideo, item.external_video_id) if item.external_video_id else None
        alerts.append({
            **item.model_dump(), "drama_title": drama.title if drama else "",
            "thumbnail_url": video.thumbnail_url if video else item.evidence_json.get("thumbnail_url", ""),
            "video_url": video.video_url if video else item.evidence_json.get("video_url", ""),
        })

    result = {
        "generated_at": now.isoformat(),
        "fastest_growth": fastest,
        "yesterday": {
            "date": yesterday.isoformat(), "publish_count": len(yesterday_items),
            "views": sum(item["views"] for item in yesterday_items),
            "likes": sum(item["likes"] for item in yesterday_items),
            "comments": sum(item["comments"] for item in yesterday_items),
            "items": yesterday_items[:4],
        },
        "traffic_source": traffic_source,
        "traffic_sources": traffic_sources,
        "week": {
            "publish_count": len(week_items),
            "active_accounts": len({item["account_id"] for item in week_items}),
            "views": sum(item["views"] for item in week_items),
            "likes": sum(item["likes"] for item in week_items),
            "comments": sum(item["comments"] for item in week_items),
            "average_views": round(sum(item["views"] for item in week_items) / len(week_items)) if week_items else 0,
            "engagement_rate": round(
                (sum(item["likes"] + item["comments"] for item in week_items) / sum(item["views"] for item in week_items) * 100), 2
            ) if sum(item["views"] for item in week_items) else 0,
            "engagement_leader": engagement_leader,
            "subscriber_leader": subscriber_leader,
        },
        "full_episode_requests": {"count": len(full_episode_comments), "items": comment_payload},
        "alerts": alerts,
        "coverage": {
            "connected_accounts": len(accounts), "media_count": len(media_rows),
            "traffic_range_start": traffic_start.isoformat(), "traffic_range_end": traffic_end.isoformat(),
            "errors": errors,
        },
    }
    _briefing_cache = (monotonic(), result)
    return result


@router.get("/events")
def events(status: str = "", limit: int = Query(10, ge=1, le=100), _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    statement = select(RadarEvent)
    if status: statement = statement.where(RadarEvent.status == status)
    rows = session.exec(statement.order_by(RadarEvent.last_detected_at.desc()).limit(200)).all()
    priority = {
        "suspected_full_top_three": 0, "suspected_compilation_top_three": 1,
        "suspected_impersonation": 2, "owned_rank_drop": 3,
        "new_top_five": 4, "shared_plot_growth": 5, "owned_top_three": 6, "authorized_top_three": 7,
    }
    rows = sorted(rows, key=lambda row: (priority.get(row.event_type, 99), -row.last_detected_at.timestamp()))[:limit]
    output = []
    for row in rows:
        drama = session.get(Drama, row.drama_id); video = session.get(ExternalVideo, row.external_video_id) if row.external_video_id else None
        output.append({**row.model_dump(), "drama_title": drama.title if drama else "", "thumbnail_url": video.thumbnail_url if video else row.evidence_json.get("thumbnail_url", ""), "video_url": video.video_url if video else row.evidence_json.get("video_url", "")})
    return output


@router.put("/events/{event_id}")
def update_event(event_id: int, payload: EventUpdate, user: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = session.get(RadarEvent, event_id)
    if not row: raise HTTPException(404, "传播事件不存在")
    row.status = payload.status; row.resolution_note = payload.resolution_note
    if payload.status in {"resolved", "dismissed", "confirmed_authorized"}: row.resolved_at = datetime.utcnow(); row.resolved_by = user.id
    session.add(row); session.commit(); session.refresh(row); return row


@router.get("/cases")
def cases(_: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(RightsCase).order_by(RightsCase.created_at.desc())).all()
    output = []
    for row in rows:
        drama = session.get(Drama, row.drama_id); video = session.get(ExternalVideo, row.external_video_id)
        payload = row.model_dump(exclude={"evidence_package_path"})
        output.append({**payload, "evidence_ready": bool(row.evidence_package_path), "drama_title": drama.title if drama else "", "video_title": video.title if video else "", "video_url": video.video_url if video else "", "channel_name": video.channel_name if video else "", "classification": video.classification if video else "unknown"})
    return output


@router.post("/cases")
def create_case(payload: RightsCaseCreate, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if not session.get(Drama, payload.drama_id) or not session.get(ExternalVideo, payload.external_video_id): raise HTTPException(404, "剧目或视频不存在")
    row = RightsCase(**payload.model_dump()); session.add(row); session.commit(); session.refresh(row); return row


@router.post("/cases/{case_id}/evidence")
def generate_case_evidence(case_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = session.get(RightsCase, case_id)
    if not row: raise HTTPException(404, "案件不存在")
    try:
        path = build_evidence_package(session, row)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    event = session.exec(select(RadarEvent).where(RadarEvent.external_video_id == row.external_video_id, RadarEvent.drama_id == row.drama_id, RadarEvent.status.in_(["new", "watching"]))).first()
    if event:
        event.status = "evidence_prepared"; session.add(event); session.commit()
    return {"ok": True, "filename": path.name, "download_url": f"/api/radar/cases/{case_id}/download"}


@router.get("/cases/{case_id}/download")
def download_case_evidence(case_id: int, _: AppUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = session.get(RightsCase, case_id)
    path = Path(row.evidence_package_path).resolve() if row and row.evidence_package_path else None
    base = (get_settings().media_root / "radar-evidence").resolve()
    if not path or not path.is_file() or base not in path.parents:
        raise HTTPException(404, "证据包尚未生成")
    return FileResponse(path, media_type="application/zip", filename=path.name)
