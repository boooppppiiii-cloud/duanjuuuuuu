from __future__ import annotations

import html
import json
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
from sqlmodel import Session, select

from ..config import get_settings
from ..models import Drama, ExternalVideo, ExternalVideoMetric, RightsCase, SearchResult, VideoMatchEvidence


def _safe_name(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "-_ ").strip()
    return cleaned[:80] or "radar-case"


def build_evidence_package(session: Session, case: RightsCase) -> Path:
    drama = session.get(Drama, case.drama_id)
    video = session.get(ExternalVideo, case.external_video_id)
    if not drama or not video:
        raise ValueError("案件关联的剧目或视频不存在")
    metrics = session.exec(select(ExternalVideoMetric).where(ExternalVideoMetric.external_video_id == video.id).order_by(ExternalVideoMetric.captured_at)).all()
    appearances = session.exec(select(SearchResult).where(SearchResult.platform_video_id == video.platform_video_id).order_by(SearchResult.created_at)).all()
    matches = session.exec(select(VideoMatchEvidence).where(VideoMatchEvidence.external_video_id == video.id, VideoMatchEvidence.drama_id == drama.id)).all()
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "drama": {"id": drama.id, "title": drama.title, "episode_count": drama.total_episode_count},
        "rights_owner": case.rights_owner,
        "authorization_review": case.authorization_review,
        "suspected_video": {
            "platform": video.platform, "url": video.video_url, "video_id": video.platform_video_id,
            "channel_id": video.channel_id, "channel_name": video.channel_name, "title": video.title,
            "description": video.description, "published_at": video.published_at.isoformat() if video.published_at else None,
            "first_seen_at": video.first_seen_at.isoformat(), "last_seen_at": video.last_seen_at.isoformat(),
            "classification": video.classification, "review_status": video.review_status, "review_note": video.review_note,
        },
        "metrics": [row.model_dump(mode="json") for row in metrics],
        "search_appearances": [{"rank": row.rank, "previous_rank": row.previous_rank, "query_snapshot_id": row.snapshot_id, "captured_at": row.created_at.isoformat()} for row in appearances],
        "matches": [row.model_dump(mode="json") for row in matches],
        "manual_notes": case.notes,
        "legal_notice": "本证据包仅供人工核验，不代表系统已作出侵权法律结论，也不会自动提交平台投诉。",
    }
    title = html.escape(video.title)
    body = f"""<!doctype html><meta charset=\"utf-8\"><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;max-width:920px;margin:40px auto;line-height:1.6;color:#172019}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}h1{{font-size:24px}}.notice{{padding:12px;background:#fff8db}}</style>
<h1>{html.escape(drama.title)} · 传播证据记录</h1><p class=\"notice\">{html.escape(report['legal_notice'])}</p>
<table><tr><th>涉嫌视频</th><td><a href=\"{html.escape(video.video_url)}\">{title}</a></td></tr><tr><th>发布账号</th><td>{html.escape(video.channel_name)}</td></tr><tr><th>首次发现</th><td>{video.first_seen_at.isoformat()}</td></tr><tr><th>最近发现</th><td>{video.last_seen_at.isoformat()}</td></tr><tr><th>人工分类</th><td>{html.escape(video.classification)}</td></tr><tr><th>权利主体</th><td>{html.escape(case.rights_owner)}</td></tr></table>
<h2>描述</h2><pre>{html.escape(video.description)}</pre><h2>人工备注</h2><p>{html.escape(case.notes)}</p>"""
    settings = get_settings()
    folder = settings.media_root / "radar-evidence" / f"case-{case.id}"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{_safe_name(drama.title)}-evidence.zip"
    thumbnail = b""
    if video.thumbnail_url:
        try:
            response = httpx.get(video.thumbnail_url, timeout=10, follow_redirects=True)
            if response.is_success and response.headers.get("content-type", "").startswith("image/") and len(response.content) <= 5 * 1024 * 1024:
                thumbnail = response.content
        except httpx.HTTPError:
            pass
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("evidence.json", json.dumps(report, ensure_ascii=False, indent=2, default=str))
        archive.writestr("report.html", body)
        if thumbnail:
            archive.writestr("platform-thumbnail.jpg", thumbnail)
    case.evidence_package_path = str(target)
    case.case_status = "evidence_ready"
    session.add(case)
    session.commit()
    return target
