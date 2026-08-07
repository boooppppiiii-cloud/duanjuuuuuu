from datetime import datetime
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, Clip, Drama, Post, PublishJob
from app.routers import publish as publish_router
from app.services import social_integrations


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.is_error = False
        self.text = ""

    def json(self):
        return self._payload


def test_youtube_calendar_prefers_publish_at_and_hides_private_upload_time(monkeypatch):
    monkeypatch.setattr(social_integrations, "youtube_access_token", lambda account: "token")
    monkeypatch.setattr(social_integrations, "_youtube_analytics", lambda token, ids: {})

    def fake_get(url, **kwargs):
        if url.endswith("/channels"):
            return FakeResponse({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]})
        if url.endswith("/playlistItems"):
            return FakeResponse({"items": [
                {"contentDetails": {"videoId": "scheduled"}},
                {"contentDetails": {"videoId": "private"}},
                {"contentDetails": {"videoId": "public"}},
            ]})
        return FakeResponse({"items": [
            {
                "id": "scheduled",
                "snippet": {"title": "Scheduled", "publishedAt": "2026-08-07T03:29:00Z"},
                "status": {"privacyStatus": "private", "publishAt": "2026-08-09T10:00:00Z"},
                "statistics": {},
                "contentDetails": {},
            },
            {
                "id": "private",
                "snippet": {"title": "Private", "publishedAt": "2026-08-07T03:30:00Z"},
                "status": {"privacyStatus": "private"},
                "statistics": {},
                "contentDetails": {},
            },
            {
                "id": "public",
                "snippet": {"title": "Public", "publishedAt": "2026-08-06T10:00:00Z"},
                "status": {"privacyStatus": "public"},
                "statistics": {},
                "contentDetails": {},
            },
        ]})

    monkeypatch.setattr(social_integrations.httpx, "get", fake_get)
    rows = social_integrations.list_platform_media(Account(platform="youtube", name="Channel"), 10)
    indexed = {row["id"]: row for row in rows}

    assert indexed["scheduled"]["calendar_at"] == "2026-08-09T10:00:00Z"
    assert indexed["scheduled"]["time_source"] == "scheduled"
    assert indexed["private"]["calendar_at"] is None
    assert indexed["public"]["calendar_at"] == "2026-08-06T10:00:00Z"


def test_calendar_includes_local_job_at_its_scheduled_time(monkeypatch, tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'calendar.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(publish_router, "list_platform_media", lambda account, limit: [])

    with Session(engine) as session:
        account = Account(platform="youtube", name="Channel", account_type="creator", status="connected")
        drama = Drama(title="Drama", file_dir=str(tmp_path), source_note="test")
        session.add(account); session.add(drama); session.commit(); session.refresh(account); session.refresh(drama)
        clip = Clip(drama_id=drama.id, template_name="hook", file_path=str(tmp_path / "video.mp4"))
        session.add(clip); session.commit(); session.refresh(clip)
        post = Post(clip_id=clip.id, title="Scheduled title", caption="Caption")
        session.add(post); session.commit(); session.refresh(post)
        scheduled_at = datetime(2026, 8, 9, 18, 0)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=scheduled_at)
        session.add(job); session.commit(); session.refresh(job)

        rows = publish_router.account_calendar(account.id, 50, session)

    assert len(rows) == 1
    assert rows[0]["id"] == f"job-{job.id}"
    assert rows[0]["title"] == "Scheduled title"
    assert rows[0]["calendar_at"] == scheduled_at
    assert rows[0]["time_source"] == "scheduled"
