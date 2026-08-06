from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Drama, EmotionWord, HookSuggestion
from ..schemas import Highlight
from ..services.drama_library import episode_files, read_highlights, write_highlights
from ..services.hook_recommender import loudness_peaks, media_duration, subtitle_emotions

router=APIRouter(prefix="/api/hooks",tags=["钩子推荐"])
DEFAULT_WORDS=["打脸","滚","离婚","竟然","居然","背叛","真相","复仇","后悔","秘密"]

def ensure_words(session:Session):
    existing={x.word for x in session.exec(select(EmotionWord)).all()}
    for word in DEFAULT_WORDS:
        if word not in existing: session.add(EmotionWord(word=word))
    session.commit()

@router.get("/words",response_model=list[EmotionWord])
def words(session:Session=Depends(get_session)):
    ensure_words(session);return session.exec(select(EmotionWord).order_by(EmotionWord.id)).all()

@router.post("/words",response_model=EmotionWord)
def add_word(word:str,session:Session=Depends(get_session)):
    item=EmotionWord(word=word.strip());session.add(item);session.commit();session.refresh(item);return item

@router.put("/words/{word_id}",response_model=EmotionWord)
def toggle_word(word_id:int,enabled:bool,session:Session=Depends(get_session)):
    item=session.get(EmotionWord,word_id)
    if not item:raise HTTPException(404,"情绪词不存在")
    item.enabled=enabled;session.add(item);session.commit();session.refresh(item);return item

@router.get("/{drama_id}",response_model=list[HookSuggestion])
def suggestions(drama_id:int,session:Session=Depends(get_session)):
    return session.exec(select(HookSuggestion).where(HookSuggestion.drama_id==drama_id).order_by(HookSuggestion.score.desc())).all()

@router.post("/{drama_id}/analyze",response_model=list[HookSuggestion])
def analyze(drama_id:int,session:Session=Depends(get_session)):
    drama=session.get(Drama,drama_id)
    if not drama:raise HTTPException(404,"剧目不存在")
    ensure_words(session);active=[x.word for x in session.exec(select(EmotionWord).where(EmotionWord.enabled==True)).all()]  # noqa:E712
    old=session.exec(select(HookSuggestion).where(HookSuggestion.drama_id==drama_id)).all()
    for x in old:session.delete(x)
    cfg=get_settings();made=[]
    for episode in episode_files(Path(drama.file_dir)):
        duration=media_duration(cfg.ffprobe_binary,episode);points=[]
        for second,jump in loudness_peaks(cfg.ffmpeg_binary,episode):points.append((second,jump,[f"音量突增 +{jump:.1f} LU"]))
        try:
            for second,count,hits in subtitle_emotions(episode,active,cfg.whisper_model,cfg.whisper_device,cfg.whisper_compute_type):points.append((second,8+count,[f"情绪词：{'、'.join(hits)}"]))
        except Exception as exc:
            points.append((0,0,[f"字幕信号不可用：{str(exc)[:80]}"]))
        for i in range(5):points.append((duration*(i+1)/6,0.1-i*0.01,["均匀补位：等待人工判断"]))
        chosen=[]
        for second,score,reasons in sorted(points,key=lambda x:x[1],reverse=True):
            start=max(0,min(second,duration-1))
            if any(abs(start-x[0])<1 for x in chosen):continue
            chosen.append((start,score,reasons))
            if len(chosen)>=5:break
        for start,score,reasons in chosen:
            item=HookSuggestion(drama_id=drama_id,episode=episode.name,start=round(start,2),end=round(min(duration,start+10),2),score=round(score,2),reasons=reasons);session.add(item);made.append(item)
    session.commit()
    for item in made:session.refresh(item)
    return made

@router.post("/suggestions/{suggestion_id}/{action}",response_model=HookSuggestion)
def decide(suggestion_id:int,action:str,session:Session=Depends(get_session)):
    if action not in {"adopt","ignore"}:raise HTTPException(422,"动作只能采纳或忽略")
    item=session.get(HookSuggestion,suggestion_id)
    drama=session.get(Drama,item.drama_id) if item else None
    if not item or not drama:raise HTTPException(404,"建议不存在")
    item.status="adopted" if action=="adopt" else "ignored"
    if action=="adopt":
        current=read_highlights(Path(drama.file_dir));current.append(Highlight(episode=item.episode,start=item.start,end=item.end,note="自动建议："+"；".join(item.reasons)));write_highlights(Path(drama.file_dir),current,{x.name for x in episode_files(Path(drama.file_dir))})
    session.add(item);session.commit();session.refresh(item);return item
