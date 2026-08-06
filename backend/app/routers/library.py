from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import ContentExample, TagLibraryItem
from ..schemas import BatchExamplesRequest, LibraryItemPayload, TagItemPayload

router = APIRouter(prefix="/api/library", tags=["样本与标签库"])


@router.get("/examples", response_model=list[ContentExample])
def examples(session: Session = Depends(get_session)):
    return session.exec(select(ContentExample).order_by(ContentExample.id.desc())).all()


@router.post("/examples", response_model=ContentExample)
def create_example(payload: LibraryItemPayload, session: Session = Depends(get_session)):
    item = ContentExample(**payload.model_dump()); session.add(item); session.commit(); session.refresh(item); return item


@router.put("/examples/{item_id}", response_model=ContentExample)
def update_example(item_id: int, payload: LibraryItemPayload, session: Session = Depends(get_session)):
    item = session.get(ContentExample, item_id)
    if not item: raise HTTPException(404, "样本不存在")
    for key,value in payload.model_dump().items(): setattr(item,key,value)
    session.add(item); session.commit(); session.refresh(item); return item


@router.delete("/examples/{item_id}")
def delete_example(item_id: int, session: Session = Depends(get_session)):
    item=session.get(ContentExample,item_id)
    if not item: raise HTTPException(404,"样本不存在")
    session.delete(item);session.commit();return {"deleted":item_id}


@router.post("/examples/batch", response_model=list[ContentExample])
def batch_examples(payload: BatchExamplesRequest, session: Session = Depends(get_session)):
    made=[]
    for line in payload.text.splitlines():
        if line.strip(): made.append(ContentExample(content=line.strip(),genres=payload.genres,language=payload.language,platform=payload.platform))
    session.add_all(made);session.commit()
    for item in made: session.refresh(item)
    return made


@router.get("/tags", response_model=list[TagLibraryItem])
def tags(session: Session = Depends(get_session)):
    return session.exec(select(TagLibraryItem).order_by(TagLibraryItem.id.desc())).all()


@router.post("/tags", response_model=TagLibraryItem)
def create_tag(payload: TagItemPayload, session: Session = Depends(get_session)):
    tag=payload.tag if payload.tag.startswith("#") else f"#{payload.tag}"
    item=TagLibraryItem(**payload.model_dump(exclude={"tag"}),tag=tag);session.add(item);session.commit();session.refresh(item);return item


@router.put("/tags/{item_id}", response_model=TagLibraryItem)
def update_tag(item_id:int,payload:TagItemPayload,session:Session=Depends(get_session)):
    item=session.get(TagLibraryItem,item_id)
    if not item: raise HTTPException(404,"标签不存在")
    for key,value in payload.model_dump().items(): setattr(item,key,value)
    if not item.tag.startswith("#"):item.tag=f"#{item.tag}"
    session.add(item);session.commit();session.refresh(item);return item


@router.delete("/tags/{item_id}")
def delete_tag(item_id:int,session:Session=Depends(get_session)):
    item=session.get(TagLibraryItem,item_id)
    if not item: raise HTTPException(404,"标签不存在")
    session.delete(item);session.commit();return {"deleted":item_id}
