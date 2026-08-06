from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..database import get_session
from ..models import Clip, Drama
from ..schemas import ClipCreateRequest, ClipView
from ..services.pipeline import create_clip_records, pipeline

router = APIRouter(prefix="/api/clips", tags=["剪辑流水线"])


@router.post("/batch", response_model=list[ClipView])
def create_batch(payload: ClipCreateRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    try:
        clips = create_clip_records(session, drama, payload.template_name)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    if not clips:
        raise HTTPException(422, "请先为剧目标注高能点")
    background_tasks.add_task(pipeline.process_queued)
    return clips


@router.get("", response_model=list[ClipView])
def list_clips(drama_id: int | None = None, session: Session = Depends(get_session)):
    statement = select(Clip).order_by(Clip.id.desc())
    if drama_id is not None:
        statement = statement.where(Clip.drama_id == drama_id)
    return session.exec(statement).all()


@router.get("/{clip_id}/preview")
def clip_preview(clip_id: int, session: Session = Depends(get_session)):
    clip = session.get(Clip, clip_id)
    path = Path(clip.preview_image) if clip and clip.preview_image else None
    if not path or not path.is_file():
        raise HTTPException(404, "预览图尚未生成")
    return FileResponse(path)


@router.get("/{clip_id}/video")
def clip_video(clip_id: int, session: Session = Depends(get_session)):
    clip = session.get(Clip, clip_id)
    path = Path(clip.file_path) if clip and clip.file_path else None
    if not path or not path.is_file():
        raise HTTPException(404, "干净版视频尚未生成")
    return FileResponse(path, media_type="video/mp4")
