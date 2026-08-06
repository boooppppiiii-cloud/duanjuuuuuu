import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import Clip, Drama, VisualReview
from ..config import get_settings
from ..services.llm import assess_visual
from ..schemas import ClipReviewRequest, ClipView, TextModerationRequest, TextModerationResult
from ..services.moderation import check_text

router = APIRouter(prefix="/api/moderation", tags=["合规检测"])
DATA_ROOT = Path(__file__).parents[2] / "data"


@router.post("/text", response_model=TextModerationResult)
def moderate_text(payload: TextModerationRequest):
    title_hits, title_parts = check_text(payload.title, DATA_ROOT / "banned_words.txt")
    caption_hits, caption_parts = check_text(payload.caption, DATA_ROOT / "banned_words.txt")
    hits = list(dict.fromkeys(title_hits + caption_hits))
    return TextModerationResult(
        hit_words=hits,
        safe=not hits,
        highlighted_title=[{"text": part.text, "hit": part.hit} for part in title_parts],
        highlighted_caption=[{"text": part.text, "hit": part.hit} for part in caption_parts],
    )


@router.get("/config")
def moderation_config():
    path = DATA_ROOT / "moderation.json"
    return json.loads(path.read_text(encoding="utf-8"))


@router.put("/clips/{clip_id}/review", response_model=ClipView)
def review_clip(clip_id: int, payload: ClipReviewRequest, session: Session = Depends(get_session)):
    clip = session.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "切片不存在")
    if clip.current_step not in {"completed", "failed"}:
        raise HTTPException(409, "切片仍在处理中，不能复核")
    if payload.status == "approved" and clip.file_path:
        source = Path(clip.file_path)
        drama = session.get(Drama, clip.drama_id)
        if not drama or not source.is_file():
            raise HTTPException(422, "成品文件不存在，无法保存到剧库")
        target_dir = Path(drama.file_dir) / "generated"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"成品_{clip.id:04d}.mp4"
        temp = target.with_suffix(".mp4.saving")
        shutil.copy2(source, temp)
        temp.replace(target)
    clip.status = payload.status
    clip.review_note = payload.note.strip()
    clip.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(clip); session.commit(); session.refresh(clip)
    return clip


@router.get("/visual", response_model=list[VisualReview])
def visual_reviews(session:Session=Depends(get_session)):
    return session.exec(select(VisualReview).order_by(VisualReview.id.desc())).all()


@router.post("/visual/{clip_id}", response_model=VisualReview)
def scan_visual(clip_id:int,image_path:str="",session:Session=Depends(get_session)):
    from datetime import timedelta
    clip=session.get(Clip,clip_id)
    if not clip:raise HTTPException(404,"切片不存在")
    root=get_settings().media_root.resolve();path=Path(image_path or clip.preview_image).resolve()
    if root not in path.parents or not path.is_file():raise HTTPException(422,"抽帧图片不存在或不在 media 目录")
    since=datetime.now()-timedelta(days=1);used=len(session.exec(select(VisualReview).where(VisualReview.created_at>=since,VisualReview.provider=="gemini")).all())
    if used>=get_settings().visual_daily_limit:risk,reasons,provider="yellow",["今日视觉模型额度已用完，必须人工复核"],"manual-required"
    else:
        try:risk,reasons,provider=assess_visual(path)
        except Exception as exc:risk,reasons,provider="yellow",[f"无法完成智能检测，必须人工复核：{str(exc)[:120]}"],"manual-required"
    item=VisualReview(clip_id=clip_id,risk=risk,reasons=reasons,status="passed" if risk=="green" else "review",provider=provider,image_path=str(path));session.add(item);session.commit();session.refresh(item);return item


@router.put("/visual/{review_id}", response_model=VisualReview)
def decide_visual(review_id:int,status:str,session:Session=Depends(get_session)):
    if status not in {"approved","blocked"}:raise HTTPException(422,"复核状态不合法")
    item=session.get(VisualReview,review_id)
    if not item:raise HTTPException(404,"视觉复核项不存在")
    item.status=status;session.add(item);session.commit();session.refresh(item);return item


@router.get("/visual/quota")
def visual_quota(session:Session=Depends(get_session)):
    from datetime import timedelta
    since=datetime.now()-timedelta(days=1);used=len(session.exec(select(VisualReview).where(VisualReview.created_at>=since,VisualReview.provider=="gemini")).all());return {"used":used,"limit":get_settings().visual_daily_limit}
