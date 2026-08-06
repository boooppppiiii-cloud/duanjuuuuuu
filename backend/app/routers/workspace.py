import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import Session, select

from ..database import get_session
from ..models import Account, Clip, Drama, MetricSnapshot, Post, PublishJob, SocialComment, VisualReview

router = APIRouter(prefix="/api/workspace", tags=["运营工作台"])


def account_matrix_rows(session: Session) -> list[dict]:
    cutoff = date.today() - timedelta(days=6)
    result = []
    for account in session.exec(select(Account).order_by(Account.platform, Account.name)).all():
        jobs = session.exec(select(PublishJob).where(PublishJob.account_id == account.id)).all()
        job_ids = [job.id for job in jobs]
        snapshots = session.exec(select(MetricSnapshot).where(MetricSnapshot.publish_job_id.in_(job_ids), MetricSnapshot.date >= cutoff)).all() if job_ids else []
        result.append({
            "id": account.id, "platform": account.platform, "name": account.name, "account_type": account.account_type,
            "status": account.status, "strategy_id": account.strategy_id,
            "avatar_url": account.avatar_url, "profile_url": account.profile_url, "last_error": account.last_error,
            "last_checked_at": account.last_checked_at, "capabilities": account.capabilities,
            "configured": bool(account.credentials_json.get("access_token_encrypted") or account.credentials_json.get("access_token_env") or account.credentials_json.get("refresh_token_encrypted") or account.credentials_json.get("refresh_token_env")),
            "posts_7d": sum(job.scheduled_at.date() >= cutoff for job in jobs), "published_total": sum(job.status == "published" for job in jobs),
            "failed_total": sum(job.status in {"failed", "partial"} for job in jobs), "views_7d": sum(item.views for item in snapshots),
            "likes_7d": sum(item.likes for item in snapshots), "comments_7d": sum(item.comments for item in snapshots),
            "followers": max((item.followers for item in snapshots), default=account.follower_count),
            "last_publish_at": max((job.scheduled_at for job in jobs), default=None),
        })
    return result


@router.get("/account-matrix")
def account_matrix(session: Session = Depends(get_session)):
    return account_matrix_rows(session)


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    accounts = session.exec(select(Account)).all(); dramas = session.exec(select(Drama)).all(); clips = session.exec(select(Clip)).all(); posts = session.exec(select(Post)).all(); jobs = session.exec(select(PublishJob)).all()
    comments = session.exec(select(SocialComment)).all(); visual = session.exec(select(VisualReview)).all(); metrics = session.exec(select(MetricSnapshot).where(MetricSnapshot.date >= date.today() - timedelta(days=6))).all()
    return {
        "kpis": {"accounts": len(accounts), "connected_accounts": sum(item.status == "connected" for item in accounts), "dramas": len(dramas), "ready_posts": sum(item.status == "ready" for item in posts), "scheduled_jobs": sum(item.status == "queued" for item in jobs), "views_7d": sum(item.views for item in metrics), "comments_7d": sum(item.comments for item in metrics)},
        "workflow": {"source": sum(item.episode_count for item in dramas), "processing": sum(item.status in {"pending", "processing"} for item in clips), "review": sum(item.status in {"review", "yellow"} for item in visual), "ready": sum(item.status in {"ready", "approved"} for item in posts), "published": sum(item.status == "published" for item in jobs)},
        "alerts": {"failed_jobs": sum(item.status in {"failed", "partial"} for item in jobs), "visual_risk": sum(item.risk == "red" and item.status != "approved" for item in visual), "comment_tickets": sum(item.needs_human and item.status not in {"resolved", "ignored"} for item in comments)},
        "matrix": account_matrix_rows(session),
        "generated_at": datetime.now(),
    }


@router.get("/weekly.csv")
def export_weekly(session: Session = Depends(get_session)):
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["平台", "账号", "账号类型", "状态", "近7天发布", "累计成功发布", "近7天播放", "近7天点赞", "近7天评论", "当前粉丝", "失败任务", "最后排期时间"])
    for item in account_matrix_rows(session):
        writer.writerow([item["platform"], item["name"], item["account_type"], item["status"], item["posts_7d"], item["published_total"], item["views_7d"], item["likes_7d"], item["comments_7d"], item["followers"], item["failed_total"], item["last_publish_at"] or ""])
    content = "\ufeff" + output.getvalue()
    return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="account-matrix-{date.today().isoformat()}.csv"'})
