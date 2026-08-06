from datetime import datetime
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Account, MetricSnapshot, PublishJob
from app.services.metrics import collect_daily_metrics


def test_daily_metrics_is_idempotent(monkeypatch, tmp_path: Path):
    import app.services.metrics as module
    engine = create_engine(f"sqlite:///{tmp_path / 'metrics.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(module, "fetch_metrics", lambda account, video_id: {"views": 100, "likes": 10, "comments": 2, "watch_time_seconds": 3600, "estimated_revenue": 4.5, "rpm": 45.0})
    with Session(engine) as session:
        account = Account(platform="youtube", name="数据号", account_type="official")
        session.add(account); session.commit(); session.refresh(account)
        session.add(PublishJob(post_id=1, account_id=account.id, scheduled_at=datetime.now(), status="published", platform_video_id="video1")); session.commit()
    assert collect_daily_metrics()["created"] == 1
    second = collect_daily_metrics()
    assert second["created"] == 0 and second["skipped"] == 1 and not second["errors"]
    with Session(engine) as session:
        row = session.exec(select(MetricSnapshot)).one()
        assert (row.views, row.likes, row.comments, row.watch_time_seconds, row.estimated_revenue) == (100, 10, 2, 3600, 4.5)
