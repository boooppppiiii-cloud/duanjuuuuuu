from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from ..models import Drama, DramaSearchProfile, PromotionDramaPool


VALID_POOL_SOURCES = {"manual_confirmed", "owned_publish", "external_market"}


def ensure_promotion_drama(
    session: Session,
    drama_id: int,
    source: str,
    *,
    account_id: int | None = None,
    video_id: int | None = None,
    note: str = "",
) -> PromotionDramaPool:
    if source not in VALID_POOL_SOURCES:
        raise ValueError("推广剧目来源无效")
    drama = session.get(Drama, drama_id)
    if not drama:
        raise ValueError("剧目不存在")
    row = session.exec(select(PromotionDramaPool).where(PromotionDramaPool.drama_id == drama_id)).first()
    if not row:
        row = PromotionDramaPool(drama_id=drama_id)
    row.active = True
    row.sources = list(dict.fromkeys([*(row.sources or []), source]))
    row.note = note or row.note
    row.discovered_from_account_id = account_id or row.discovered_from_account_id
    row.discovered_from_video_id = video_id or row.discovered_from_video_id
    row.updated_at = datetime.utcnow()
    session.add(row)
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first()
    if not profile:
        profile = DramaSearchProfile(drama_id=drama_id, official_title=drama.title)
    profile.enabled = True
    profile.scan_interval_hours = 24
    profile.updated_at = datetime.utcnow()
    session.add(profile)
    session.flush()
    return row


def deactivate_promotion_drama(session: Session, drama_id: int) -> PromotionDramaPool:
    row = session.exec(select(PromotionDramaPool).where(PromotionDramaPool.drama_id == drama_id)).first()
    if not row:
        raise ValueError("剧目不在推广剧目池")
    row.active = False
    row.updated_at = datetime.utcnow()
    session.add(row)
    profile = session.exec(select(DramaSearchProfile).where(DramaSearchProfile.drama_id == drama_id)).first()
    if profile:
        profile.enabled = False
        session.add(profile)
    return row
