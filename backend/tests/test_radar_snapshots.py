from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AppUser, Drama, ExternalVideo, MonitoredAccount, RadarEvent, SearchQuery, SearchResult, SearchSnapshot
from app.routers.radar import search_live


def test_snapshot_allows_history_but_not_duplicate_video_in_one_snapshot(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshots.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drama = Drama(title="Snapshot Drama", file_dir="snapshot"); session.add(drama); session.commit(); session.refresh(drama)
        query = SearchQuery(drama_id=drama.id, query_text="Snapshot Drama"); session.add(query); session.commit(); session.refresh(query)
        first = SearchSnapshot(drama_id=drama.id, query_id=query.id); second = SearchSnapshot(drama_id=drama.id, query_id=query.id)
        session.add(first); session.add(second); session.commit(); session.refresh(first); session.refresh(second)
        session.add(SearchResult(snapshot_id=first.id, drama_id=drama.id, platform_video_id="v1", rank=1))
        session.add(SearchResult(snapshot_id=second.id, drama_id=drama.id, platform_video_id="v1", rank=2, previous_rank=1)); session.commit()
        assert len(session.exec(select(SearchSnapshot)).all()) == 2
        assert session.exec(select(SearchResult).where(SearchResult.snapshot_id == second.id)).one().previous_rank == 1


def test_active_event_can_be_reused_instead_of_spammed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drama = Drama(title="Event Drama", file_dir="event"); session.add(drama); session.commit(); session.refresh(drama)
        video = ExternalVideo(platform_video_id="v1", channel_name="Channel"); session.add(video); session.commit(); session.refresh(video)
        first = RadarEvent(drama_id=drama.id, external_video_id=video.id, event_type="new_top_five", severity="opportunity", title="first", last_detected_at=datetime.utcnow())
        session.add(first); session.commit()
        existing = session.exec(select(RadarEvent).where(RadarEvent.drama_id == drama.id, RadarEvent.external_video_id == video.id, RadarEvent.event_type == "new_top_five", RadarEvent.status.in_(["new", "watching"]))).first()
        assert existing.id == first.id


def test_existing_snapshot_backfills_theater_official_identity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'theater-backfill.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = AppUser(email="viewer@example.com", password_hash="x")
        drama = Drama(title="Existing Drama", theater="DramaBox", file_dir="existing")
        session.add(user); session.add(drama); session.commit(); session.refresh(user); session.refresh(drama)
        query = SearchQuery(drama_id=drama.id, query_text=drama.title, region="US")
        session.add(query); session.commit(); session.refresh(query)
        snapshot = SearchSnapshot(drama_id=drama.id, query_id=query.id)
        session.add(snapshot); session.commit(); session.refresh(snapshot)
        session.add(SearchResult(
            snapshot_id=snapshot.id,
            drama_id=drama.id,
            platform_video_id="brand-video",
            rank=1,
            channel_id="UC-DRAMABOX",
            channel_name="DramaBox - Stream Drama Shorts",
            channel_url="https://youtube.com/channel/UC-DRAMABOX",
            relationship_type="unknown",
            authorization_status="unknown",
        ))
        session.add(ExternalVideo(platform_video_id="brand-video", channel_id="UC-DRAMABOX", channel_name="DramaBox - Stream Drama Shorts"))
        session.commit()

        payload = search_live(drama.id, query.id, snapshot.id, user, session)

        assert payload["results"][0]["relationship_type"] == "own_official"
        assert payload["results"][0]["authorization_status"] == "authorized"
        assert payload["summary"]["own"] == 1
        assert session.exec(select(MonitoredAccount).where(MonitoredAccount.platform_account_id == "UC-DRAMABOX")).one()
