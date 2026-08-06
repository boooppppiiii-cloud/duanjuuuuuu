from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Drama, EmotionWord
from ..services.script_analysis import analyze_drama, read_analysis


router = APIRouter(prefix="/api/factory", tags=["内容工厂"])


def get_drama(drama_id: int, session: Session) -> Drama:
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return drama


@router.get("/{drama_id}/analysis")
def get_script_analysis(drama_id: int, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    result = read_analysis(Path(drama.file_dir))
    return result or {
        "status": "not_analyzed",
        "drama_id": drama.id,
        "title": drama.title,
        "episodes": [],
        "episode_count": drama.episode_count,
        "total_duration": 0,
        "segment_count": 0,
        "high_energy_count": 0,
        "sensitive_count": 0,
    }


@router.post("/{drama_id}/analyze")
def run_script_analysis(drama_id: int, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    words = [item.word for item in session.exec(select(EmotionWord).where(EmotionWord.enabled == True)).all()]  # noqa: E712
    try:
        return analyze_drama(Path(drama.file_dir), drama.id, drama.title, get_settings(), words)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
