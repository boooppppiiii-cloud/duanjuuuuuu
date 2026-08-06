from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from .database import engine
from .models import PublishJob
from .services.publisher import execute_publish_job, refresh_publish_status
from .services.metrics import collect_daily_metrics


def scan_publish_jobs() -> None:
    with Session(engine) as session:
        jobs = session.exec(select(PublishJob).where(PublishJob.status == "queued", PublishJob.scheduled_at <= datetime.now()).order_by(PublishJob.scheduled_at)).all()
        for job in jobs:
            execute_publish_job(session, job)


def scan_submitted_jobs() -> None:
    with Session(engine) as session:
        jobs = session.exec(select(PublishJob).where(PublishJob.status == "submitted").order_by(PublishJob.submitted_at)).all()
        for job in jobs[:50]:
            refresh_publish_status(session, job)


scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
scheduler.add_job(scan_publish_jobs, "interval", minutes=1, id="publish_scan", replace_existing=True)
scheduler.add_job(scan_submitted_jobs, "interval", minutes=2, id="publish_status_scan", replace_existing=True)
scheduler.add_job(collect_daily_metrics, "cron", hour=3, minute=0, id="daily_metrics", replace_existing=True)
