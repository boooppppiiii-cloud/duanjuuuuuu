from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_session
from ..models import Account, Clip, Drama, MetricSnapshot, Post, PublishJob
from ..services.metrics import collect_daily_metrics

router=APIRouter(prefix="/api/metrics",tags=["数据回收"])

@router.get("")
def metrics(session:Session=Depends(get_session)):
    rows=[]
    for snapshot in session.exec(select(MetricSnapshot).order_by(MetricSnapshot.date.desc(),MetricSnapshot.views.desc())).all():
        job=session.get(PublishJob,snapshot.publish_job_id);post=session.get(Post,job.post_id) if job else None;clip=session.get(Clip,post.clip_id) if post else None;account=session.get(Account,job.account_id) if job else None
        rows.append({"id":snapshot.id,"date":snapshot.date,"views":snapshot.views,"likes":snapshot.likes,"comments":snapshot.comments,"followers":snapshot.followers,"impressions":snapshot.impressions,"clicks":snapshot.clicks,"ctr":snapshot.ctr,"watch_time_seconds":snapshot.watch_time_seconds,"estimated_revenue":snapshot.estimated_revenue,"rpm":snapshot.rpm,"subscribers_gained":snapshot.subscribers_gained,"post_title":post.title if post else "","account_name":account.name if account else "","account_type":account.account_type if account else "","cover_fallback":post.cover_fallback if post else False,"clip_id":clip.id if clip else None})
    return rows

@router.post("/collect")
def collect_now():return collect_daily_metrics()

@router.get("/dashboard")
def dashboard(start:date|None=None,end:date|None=None,session:Session=Depends(get_session)):
    filters=[]
    if start:filters.append(MetricSnapshot.date>=start)
    if end:filters.append(MetricSnapshot.date<=end)
    account_rows=session.exec(select(Account.name,MetricSnapshot.date,func.sum(MetricSnapshot.views),func.sum(MetricSnapshot.followers)).join(PublishJob,PublishJob.account_id==Account.id).join(MetricSnapshot,MetricSnapshot.publish_job_id==PublishJob.id).where(*filters).group_by(Account.name,MetricSnapshot.date).order_by(MetricSnapshot.date)).all()
    template_rows=session.exec(select(Clip.template_name,func.avg(MetricSnapshot.views),func.count(MetricSnapshot.id)).join(Post,Post.clip_id==Clip.id).join(PublishJob,PublishJob.post_id==Post.id).join(MetricSnapshot,MetricSnapshot.publish_job_id==PublishJob.id).where(*filters).group_by(Clip.template_name)).all()
    drama_rows=session.exec(select(Drama.title,func.sum(MetricSnapshot.views),func.max(MetricSnapshot.views)).join(Clip,Clip.drama_id==Drama.id).join(Post,Post.clip_id==Clip.id).join(PublishJob,PublishJob.post_id==Post.id).join(MetricSnapshot,MetricSnapshot.publish_job_id==PublishJob.id).where(*filters).group_by(Drama.title)).all()
    cover_rows=session.exec(select(Post.cover_fallback,func.avg(MetricSnapshot.views),func.avg(MetricSnapshot.likes),func.count(MetricSnapshot.id)).join(PublishJob,PublishJob.post_id==Post.id).join(MetricSnapshot,MetricSnapshot.publish_job_id==PublishJob.id).where(*filters).group_by(Post.cover_fallback)).all()
    return {"account_trends":[{"account":r[0],"date":r[1],"views":r[2] or 0,"followers":r[3] or 0} for r in account_rows],"templates":[{"template":r[0],"avg_views":round(r[1] or 0,1),"count":r[2]} for r in template_rows],"dramas":[{"drama":r[0],"total_views":r[1] or 0,"best_views":r[2] or 0} for r in drama_rows],"covers":[{"kind":"视频帧封面" if r[0] else "AI 创意底图","avg_views":round(r[1] or 0,1),"avg_likes":round(r[2] or 0,1),"count":r[3]} for r in cover_rows]}
