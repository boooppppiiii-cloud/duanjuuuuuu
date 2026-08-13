from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Drama, ExternalVideo, PromotionDramaPool, RadarQuotaUsage, RightsCase
from app.services import radar_search
from app.services.radar_evidence import build_evidence_package
from app.services.radar_pool import ensure_promotion_drama
from app.services.radar_scoring import classify_candidate


def test_risk_rules_are_explainable_and_unknown_is_not_infringement():
    unknown = classify_candidate(title="Episode clip", description="", channel_name="new channel", duration_seconds=120, authorized=False, relationship_type="unknown", approved_domains=[])
    assert unknown.classification == "unknown" and unknown.score == 0
    full = classify_candidate(title="Drama Full Movie Complete Series", description="", channel_name="new channel", duration_seconds=3600, authorized=False, relationship_type="unknown", approved_domains=[])
    assert full.classification == "suspected_full_reupload" and full.score >= 90 and len(full.reasons) == 2
    redirect = classify_candidate(title="Drama clip", description="watch https://unknown-pay.example/buy", channel_name="channel", duration_seconds=120, authorized=False, relationship_type="unknown", approved_domains=["dramabox.com"])
    assert redirect.classification == "suspected_external_redirect" and "unknown-pay.example" in redirect.reasons[0]
    episodes = classify_candidate(title="Episode 3", description="", channel_name="channel", duration_seconds=120, authorized=False, relationship_type="unknown", approved_domains=[], same_channel_episode_count=4)
    assert episodes.classification == "suspected_episode_reupload"


def test_promotion_pool_merges_three_discovery_sources(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pool.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drama = Drama(title="Pool Drama", file_dir="pool"); session.add(drama); session.commit(); session.refresh(drama)
        ensure_promotion_drama(session, drama.id, "manual_confirmed")
        ensure_promotion_drama(session, drama.id, "owned_publish")
        row = ensure_promotion_drama(session, drama.id, "external_market")
        session.commit(); session.refresh(row)
        assert row.active is True
        assert row.sources == ["manual_confirmed", "owned_publish", "external_market"]


def test_quota_reservation_stops_before_daily_limit(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(radar_search, "get_settings", lambda: SimpleNamespace(radar_youtube_daily_search_limit=3, radar_youtube_daily_quota_budget=5))
    with Session(engine) as session:
        radar_search._reserve_quota(session, 3, 5)
        row = session.exec(select(RadarQuotaUsage)).one()
        assert row.search_calls == 3 and row.used_units == 5
        try:
            radar_search._reserve_quota(session, 1, 1)
            assert False, "quota should block"
        except RuntimeError as exc:
            assert "安全上限" in str(exc)


def test_evidence_zip_contains_no_secret_or_local_source_path(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    SQLModel.metadata.create_all(engine)
    media = tmp_path / "media"
    monkeypatch.setattr("app.services.radar_evidence.get_settings", lambda: SimpleNamespace(media_root=media))
    with Session(engine) as session:
        drama = Drama(title="Evidence Drama", file_dir=r"C:\private\source"); session.add(drama); session.commit(); session.refresh(drama)
        video = ExternalVideo(platform_video_id="video", video_url="https://youtube.com/watch?v=video", title="Full Drama", channel_name="channel", classification="suspected_full_reupload"); session.add(video); session.commit(); session.refresh(video)
        case = RightsCase(drama_id=drama.id, external_video_id=video.id, rights_owner="Owner", notes="manual review"); session.add(case); session.commit(); session.refresh(case)
        path = build_evidence_package(session, case)
        with ZipFile(path) as archive:
            payload = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist() if name.endswith((".json", ".html")))
        assert "C:\\private\\source" not in payload
        assert "AIza" not in payload and "YOUTUBE_API_KEY" not in payload
        assert "youtube.com/watch?v=video" in payload
