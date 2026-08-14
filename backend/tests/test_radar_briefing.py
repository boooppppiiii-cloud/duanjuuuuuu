from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, AppUser, SocialComment
from app.routers import radar


def test_briefing_uses_real_media_traffic_and_comments(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'briefing.db'}")
    SQLModel.metadata.create_all(engine)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    yesterday = now - timedelta(days=1)

    with Session(engine) as session:
        account = Account(platform="youtube", name="Drama Hub", account_type="official", status="connected")
        session.add(account)
        session.commit()
        session.refresh(account)
        session.add(SocialComment(
            external_id="youtube:comment-1",
            platform="youtube",
            account_id=account.id,
            video_id="video-1",
            video_title="Episode 1",
            video_url="https://youtube.test/video-1",
            author_name="Viewer",
            text_original="Where can I watch the full series?",
            text_zh="在哪里看全集？",
            published_at=now.replace(tzinfo=None),
        ))
        session.commit()

        monkeypatch.setattr(radar, "list_platform_media", lambda *_args, **_kwargs: [{
            "id": "video-1", "title": "Yesterday's release", "published_at": yesterday.isoformat(),
            "views": 2400, "likes": 120, "comments": 30, "url": "https://youtube.test/video-1",
            "thumbnail_url": "https://img.test/video-1.jpg",
        }])
        monkeypatch.setattr(radar, "youtube_traffic_sources", lambda *_args, **_kwargs: [
            {"source": "YT_SEARCH", "views": 700, "watch_time_seconds": 3600},
            {"source": "RELATED_VIDEO", "views": 300, "watch_time_seconds": 1200},
        ])

        result = radar.briefing(True, AppUser(email="dev@example.com", password_hash="x"), session)

    assert result["fastest_growth"]["video_id"] == "video-1"
    assert result["fastest_growth"]["views_per_hour"] > 0
    assert result["yesterday"]["publish_count"] == 1
    assert result["yesterday"]["views"] == 2400
    assert result["traffic_source"]["label"] == "YouTube 搜索"
    assert result["traffic_source"]["share"] == 70.0
    assert [item["label"] for item in result["traffic_sources"]] == ["YouTube 搜索", "推荐视频"]
    assert result["week"]["publish_count"] == 1
    assert result["week"]["average_views"] == 2400
    assert result["week"]["engagement_leader"]["video_id"] == "video-1"
    assert result["full_episode_requests"]["count"] == 1
    assert result["full_episode_requests"]["items"][0]["account_name"] == "Drama Hub"


def test_full_episode_request_does_not_match_unrelated_comment():
    comment = SocialComment(external_id="x", text_original="Great acting!", text_zh="演得很好")
    assert radar._full_episode_request(comment) is False
