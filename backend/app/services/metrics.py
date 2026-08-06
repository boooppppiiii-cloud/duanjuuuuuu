from datetime import date

from sqlmodel import Session, select

from ..database import engine
from ..models import Account, MetricSnapshot, PublishJob
from .publisher import fetch_metrics


def collect_daily_metrics(refresh_existing: bool = False) -> dict:
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    today = date.today()
    with Session(engine) as session:
        jobs = session.exec(select(PublishJob).where(PublishJob.status == "published", PublishJob.platform_video_id != "")).all()
        for job in jobs:
            existing = session.exec(select(MetricSnapshot).where(MetricSnapshot.publish_job_id == job.id, MetricSnapshot.date == today)).first()
            if existing and not refresh_existing:
                skipped += 1
                continue
            account = session.get(Account, job.account_id)
            if not account:
                errors.append({"job_id": job.id, "account": "", "error": "发布账号不存在"})
                continue
            try:
                values = fetch_metrics(account, job.platform_video_id)
            except Exception as exc:
                errors.append({"job_id": job.id, "account": account.name, "error": str(exc)[:500]})
                continue
            if existing:
                existing.followers = account.follower_count
                for key, value in values.items():
                    setattr(existing, key, value)
                session.add(existing)
                updated += 1
            else:
                session.add(MetricSnapshot(publish_job_id=job.id, date=today, followers=account.follower_count, **values)); created += 1
        session.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}
