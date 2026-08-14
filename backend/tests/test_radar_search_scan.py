from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    AppUser,
    Drama,
    DramaSearchProfile,
    ExternalVideo,
    MonitoredAccount,
    MonitoredAccountDrama,
    PromotionDramaPool,
    RadarEvent,
    SearchQuery,
    SearchResult,
    SearchSnapshot,
    VideoMatchEvidence,
)
from app.services import radar_search
from app.services.radar_content_analysis import CONTENT_STRUCTURE_METHOD, ContentStructureDecision


class FakeCall:
    def __init__(self, payload): self.payload = payload
    def execute(self, **kwargs): return self.payload


class FakeSearch:
    def list(self, **kwargs):
        assert kwargs["type"] == "video" and kwargs["order"] == "relevance" and kwargs["maxResults"] == 10
        return FakeCall({"items": [{"id": {"videoId": "video-1"}}, {"id": {"videoId": "video-2"}}]})


class FakeVideos:
    def list(self, **kwargs):
        items = []
        for index, video_id in enumerate(kwargs["id"].split(","), start=1):
            items.append({
                "id": video_id,
                "snippet": {"title": f"Result {index}", "description": "real result", "channelId": "UC-OFFICIAL", "channelTitle": "Official Channel", "publishedAt": "2026-08-01T10:00:00Z", "tags": ["drama"], "thumbnails": {"high": {"url": f"https://img/{video_id}.jpg"}}},
                "contentDetails": {"duration": "PT2M30S"},
                "statistics": {"viewCount": str(index * 1000), "likeCount": "20", "commentCount": "3"},
                "status": {"privacyStatus": "public"},
            })
        return FakeCall({"items": items})


class FakeChannels:
    def list(self, **kwargs):
        assert kwargs["id"] == "UC-OFFICIAL"
        return FakeCall({"items": [{"id": "UC-OFFICIAL", "snippet": {"title": "Official Channel", "thumbnails": {"default": {"url": "https://img/channel.jpg"}}}, "statistics": {"subscriberCount": "5000"}}]})


class FakeYouTube:
    _http = SimpleNamespace(timeout=None)
    def search(self): return FakeSearch()
    def videos(self): return FakeVideos()
    def channels(self): return FakeChannels()


class TheaterFakeVideos(FakeVideos):
    def list(self, **kwargs):
        payload = super().list(**kwargs).payload
        for item in payload["items"]:
            item["snippet"]["channelId"] = "UC-DRAMABOX"
            item["snippet"]["channelTitle"] = "DramaBox - Stream Drama Shorts"
        return FakeCall(payload)


class TheaterFakeChannels:
    def list(self, **kwargs):
        assert kwargs["id"] == "UC-DRAMABOX"
        return FakeCall({"items": [{
            "id": "UC-DRAMABOX",
            "snippet": {"title": "DramaBox - Stream Drama Shorts", "thumbnails": {"default": {"url": "https://img/dramabox.jpg"}}},
            "statistics": {"subscriberCount": "15300000"},
        }]})


class TheaterFakeYouTube(FakeYouTube):
    def videos(self): return TheaterFakeVideos()
    def channels(self): return TheaterFakeChannels()


class FullCandidateSearch:
    def list(self, **kwargs):
        return FakeCall({"items": [{"id": {"videoId": "full-video"}}]})


class FullCandidateVideos:
    def list(self, **kwargs):
        return FakeCall({"items": [{
            "id": "full-video",
            "snippet": {
                "title": "Radar Drama Full Movie Complete Series", "description": "",
                "channelId": "UC-UNKNOWN", "channelTitle": "Unknown Uploads",
                "publishedAt": "2026-08-01T10:00:00Z", "tags": ["drama"],
                "thumbnails": {"high": {"url": "https://img/full-video.jpg"}},
            },
            "contentDetails": {"duration": "PT1H"},
            "statistics": {"viewCount": "3000", "likeCount": "20", "commentCount": "3"},
            "status": {"privacyStatus": "public"},
        }]})


class FullCandidateChannels:
    def list(self, **kwargs):
        return FakeCall({"items": [{
            "id": "UC-UNKNOWN", "snippet": {"title": "Unknown Uploads", "thumbnails": {}},
            "statistics": {"subscriberCount": "100"},
        }]})


class FullCandidateYouTube(FakeYouTube):
    def search(self): return FullCandidateSearch()
    def videos(self): return FullCandidateVideos()
    def channels(self): return FullCandidateChannels()


def test_official_youtube_scan_saves_real_snapshots_and_matches_account(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scan.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(radar_search, "get_settings", lambda: SimpleNamespace(youtube_api_key="real-key", radar_youtube_queries_per_drama=3, radar_youtube_daily_search_limit=60, radar_youtube_daily_quota_budget=5000, radar_approved_redirect_domain_list=["youtube.com"]))
    monkeypatch.setattr(radar_search, "build", lambda *args, **kwargs: FakeYouTube())
    with Session(engine) as session:
        user = AppUser(email="dev@example.com", password_hash="x", is_developer=True)
        drama = Drama(title="Radar Drama", file_dir="radar")
        account = MonitoredAccount(platform="youtube", platform_account_id="UC-OFFICIAL", display_name="Official Channel", normalized_name="officialchannel", relationship_type="own_official")
        session.add(user); session.add(drama); session.add(account); session.commit(); session.refresh(user); session.refresh(drama); session.refresh(account)
        session.add(MonitoredAccountDrama(account_id=account.id, drama_id=drama.id));
        profile = DramaSearchProfile(drama_id=drama.id, enabled=True, official_title="Radar Drama")
        session.add(profile); session.commit(); session.refresh(profile)
        session.add(PromotionDramaPool(drama_id=drama.id, sources=["manual_confirmed"])); session.commit()
        session.add(SearchQuery(drama_id=drama.id, query_text="Radar Drama", enabled=True)); session.commit()
        result = radar_search.scan_drama(session, drama.id, user)
        assert result["unique_video_count"] == 2
        assert len(session.exec(select(SearchSnapshot)).all()) == 1
        rows = session.exec(select(SearchResult).order_by(SearchResult.rank)).all()
        assert [row.rank for row in rows] == [1, 2]
        assert all(row.relationship_type == "own_official" and row.authorization_status == "authorized" for row in rows)
        assert len(session.exec(select(ExternalVideo)).all()) == 2
        events = session.exec(select(RadarEvent)).all()
        assert len(events) == 2 and all(event.event_type == "owned_top_three" for event in events)


def test_missing_youtube_key_creates_no_fake_snapshot(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'no-key.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(radar_search, "get_settings", lambda: SimpleNamespace(youtube_api_key="", radar_youtube_queries_per_drama=3, radar_youtube_daily_search_limit=60, radar_youtube_daily_quota_budget=5000, radar_approved_redirect_domain_list=[]))
    with Session(engine) as session:
        drama = Drama(title="No Key Drama", file_dir="none"); session.add(drama); session.commit(); session.refresh(drama)
        session.add(DramaSearchProfile(drama_id=drama.id, official_title=drama.title)); session.commit()
        try:
            radar_search.scan_drama(session, drama.id)
            assert False, "scan should be blocked"
        except RuntimeError as exc:
            assert "YOUTUBE_API_KEY" in str(exc)
        assert session.exec(select(SearchSnapshot)).first() is None


def test_theater_brand_match_recognizes_official_traffic_account(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'theater-match.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(radar_search, "get_settings", lambda: SimpleNamespace(youtube_api_key="real-key", radar_youtube_queries_per_drama=3, radar_youtube_daily_search_limit=60, radar_youtube_daily_quota_budget=5000, radar_approved_redirect_domain_list=["youtube.com"]))
    monkeypatch.setattr(radar_search, "build", lambda *args, **kwargs: TheaterFakeYouTube())
    with Session(engine) as session:
        user = AppUser(email="dev@example.com", password_hash="x", is_developer=True)
        drama = Drama(title="Brand Match Drama", theater="DramaBox", file_dir="brand-match")
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        session.add(DramaSearchProfile(drama_id=drama.id, enabled=True, official_title=drama.title))
        session.add(PromotionDramaPool(drama_id=drama.id, sources=["manual_confirmed"]))
        session.add(SearchQuery(drama_id=drama.id, query_text=drama.title, enabled=True))
        session.commit()

        radar_search.scan_drama(session, drama.id, user)

        account = session.exec(select(MonitoredAccount).where(MonitoredAccount.platform_account_id == "UC-DRAMABOX")).one()
        assert account.relationship_type == "own_official"
        assert account.source == "theater_match"
        link = session.exec(select(MonitoredAccountDrama).where(
            MonitoredAccountDrama.account_id == account.id,
            MonitoredAccountDrama.drama_id == drama.id,
        )).one()
        assert link.relationship_override == "own_official"
        rows = session.exec(select(SearchResult)).all()
        assert rows and all(row.relationship_type == "own_official" for row in rows)
        assert all(row.authorization_status == "authorized" for row in rows)


def test_scan_relabels_fake_full_video_as_repeated_compilation(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'content-verified-scan.db'}")
    SQLModel.metadata.create_all(engine)
    settings = SimpleNamespace(
        youtube_api_key="real-key", gemini_api_key="gemini-key",
        radar_youtube_queries_per_drama=1, radar_youtube_daily_search_limit=60,
        radar_youtube_daily_quota_budget=5000, radar_approved_redirect_domain_list=["youtube.com"],
        radar_content_analysis_auto_rank_limit=5, radar_content_analysis_daily_video_limit=3,
        radar_content_analysis_daily_minutes_limit=360,
    )
    monkeypatch.setattr(radar_search, "get_settings", lambda: settings)
    monkeypatch.setattr(radar_search, "build", lambda *args, **kwargs: FullCandidateYouTube())
    monkeypatch.setattr(radar_search, "analyze_youtube_content", lambda *args: ContentStructureDecision(
        "repeated_compilation", .91, .28, .52, "前后出现相同剧情块",
        {"structure": "repeated_compilation", "confidence": .91, "continuous_story_ratio": .28,
         "repetition_ratio": .52, "reason": "前后出现相同剧情块", "sequence_evidence": [],
         "repetition_evidence": ["03:00 与 37:00 重复"]},
    ))
    with Session(engine) as session:
        user = AppUser(email="dev@example.com", password_hash="x", is_developer=True)
        drama = Drama(title="Radar Drama", file_dir="radar")
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        session.add(DramaSearchProfile(drama_id=drama.id, enabled=True, official_title=drama.title))
        session.add(PromotionDramaPool(drama_id=drama.id, sources=["manual_confirmed"]))
        session.add(SearchQuery(drama_id=drama.id, query_text=drama.title, enabled=True))
        session.commit()

        radar_search.scan_drama(session, drama.id, user)

        video = session.exec(select(ExternalVideo)).one()
        assert video.classification == "suspected_compilation_reupload"
        content = session.exec(select(VideoMatchEvidence).where(
            VideoMatchEvidence.match_method == CONTENT_STRUCTURE_METHOD,
        )).one()
        assert content.evidence_json["structure"] == "repeated_compilation"
        event = session.exec(select(RadarEvent)).one()
        assert event.event_type == "suspected_compilation_top_three"
