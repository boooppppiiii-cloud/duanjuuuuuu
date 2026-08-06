from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from sqlmodel import Session,select
from ..database import get_session
from ..models import HotNote
from ..schemas import HotNotePayload

router=APIRouter(prefix="/api/hot-notes",tags=["热点记事本"])

@router.get("",response_model=list[HotNote])
def notes(active_only:bool=False,platform:str="",session:Session=Depends(get_session)):
    items=session.exec(select(HotNote).order_by(HotNote.expires_at.desc())).all()
    return [x for x in items if (not active_only or x.expires_at>=date.today()) and (not platform or x.platform==platform)]

@router.post("",response_model=HotNote)
def create_note(payload:HotNotePayload,session:Session=Depends(get_session)):
    item=HotNote(content=payload.content.strip(),platform=payload.platform,expires_at=payload.expires_at.date());session.add(item);session.commit();session.refresh(item);return item

@router.put("/{note_id}",response_model=HotNote)
def update_note(note_id:int,payload:HotNotePayload,session:Session=Depends(get_session)):
    item=session.get(HotNote,note_id)
    if not item:raise HTTPException(404,"热点不存在")
    item.content=payload.content.strip();item.platform=payload.platform;item.expires_at=payload.expires_at.date();session.add(item);session.commit();session.refresh(item);return item

@router.delete("/{note_id}")
def delete_note(note_id:int,session:Session=Depends(get_session)):
    item=session.get(HotNote,note_id)
    if not item:raise HTTPException(404,"热点不存在")
    session.delete(item);session.commit();return {"deleted":note_id}
