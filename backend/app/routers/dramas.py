from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Drama
from ..schemas import DramaCreateRequest, DramaDetail, DramaUpdate, GeneratedFile, HighlightsPayload, ManualRegisterRequest, ScanResult, UploadInitRequest, UploadInitResult
from ..services.drama_library import IMAGE_SUFFIXES, VIDEO_SUFFIXES, episode_files, files_with_suffix, read_highlights, scan_dramas_with_logs, write_highlights
from ..services.uploads import UploadStore, validate_title

router = APIRouter(prefix="/api/dramas", tags=["剧库"])


def get_drama_or_404(drama_id: int, session: Session) -> Drama:
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return drama


def to_detail(drama: Drama) -> DramaDetail:
    media_root = get_settings().media_root
    folder = Path(drama.file_dir)
    episodes = episode_files(folder)
    stills = files_with_suffix(folder / "stills", IMAGE_SUFFIXES)
    generated = files_with_suffix(folder / "generated", VIDEO_SUFFIXES)
    data = drama.model_dump()
    data["episode_count"] = len(episodes)
    data["total_episode_count"] = max(drama.total_episode_count, len(episodes), 1)
    return DramaDetail(
        **data,
        episodes=[path.name for path in episodes],
        stills=[DramaDetail.safe_relative(path, media_root) for path in stills],
        highlights=read_highlights(folder),
        generated_files=[GeneratedFile(name=path.name, size=path.stat().st_size, created_at=datetime.fromtimestamp(path.stat().st_mtime)) for path in generated],
    )


@router.post("", response_model=DramaDetail)
def create_drama_task(payload: DramaCreateRequest, session: Session = Depends(get_session)):
    try:
        title = validate_title(payload.title)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if session.exec(select(Drama).where(Drama.title == title)).first():
        raise HTTPException(409, "已存在同名剧目任务")
    folder = (get_settings().media_root / "dramas" / title).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise HTTPException(409, "本地已有同名素材文件夹，请使用“登记现有文件夹”")
    for name in ("episodes", "stills", "generated"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    drama = Drama(
        title=title,
        file_dir=str(folder),
        source_note="剧目任务",
        language=payload.language,
        promotion_episode_count=payload.promotion_episode_count,
        total_episode_count=payload.total_episode_count,
    )
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.post("/scan", response_model=ScanResult)
def scan(session: Session = Depends(get_session)):
    items, logs = scan_dramas_with_logs(session, get_settings().media_root)
    return ScanResult(scan_root=str((get_settings().media_root / "dramas").resolve()), logs=logs, dramas=[to_detail(item) for item in items])


@router.post("/register", response_model=DramaDetail)
def manual_register(payload: ManualRegisterRequest, session: Session = Depends(get_session)):
    try: title = validate_title(payload.title)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    source = Path(payload.absolute_path).expanduser().resolve()
    folder = source.parent if source.is_file() else source
    if not source.exists(): raise HTTPException(422, f"路径不存在：{source}")
    videos = [source] if source.is_file() and source.suffix.lower() in VIDEO_SUFFIXES else episode_files(folder)
    if not videos: raise HTTPException(422, "路径存在，但没有找到支持的视频文件")
    existing = session.exec(select(Drama).where(Drama.title == title)).first()
    if existing and Path(existing.file_dir).resolve() != folder: raise HTTPException(409, f"已存在同名剧：{existing.file_dir}")
    drama = existing or Drama(title=title, file_dir=str(folder), source_note=payload.source_note)
    drama.file_dir, drama.source_note, drama.episode_count = str(folder), payload.source_note.strip(), len(videos)
    drama.total_episode_count = max(drama.total_episode_count, len(videos))
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.post("/uploads/init", response_model=UploadInitResult)
def upload_init(payload: UploadInitRequest):
    try:
        upload_id, received = UploadStore(get_settings().media_root).init(payload)
        return UploadInitResult(upload_id=upload_id, received_chunks=received)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.put("/uploads/{upload_id}/chunks/{index}")
def upload_chunk(upload_id: str, index: int, data: bytes = Body(..., media_type="application/octet-stream")):
    try: return {"received_chunks": UploadStore(get_settings().media_root).write_chunk(upload_id, index, data)}
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/uploads/{upload_id}/complete", response_model=DramaDetail)
def upload_complete(upload_id: str, session: Session = Depends(get_session)):
    try: _, manifest = UploadStore(get_settings().media_root).complete(upload_id)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    scan_dramas_with_logs(session, get_settings().media_root)
    drama = session.exec(select(Drama).where(Drama.title == manifest["drama_title"])).first()
    if not drama: raise HTTPException(500, "文件已落盘，但剧目入库失败，请点击目录扫描查看原因")
    drama.source_note = manifest["source_note"]
    drama.episode_count = len(episode_files(Path(drama.file_dir)))
    drama.total_episode_count = max(drama.total_episode_count, drama.episode_count, 1)
    session.add(drama); session.commit(); session.refresh(drama)
    return to_detail(drama)


@router.get("", response_model=list[DramaDetail])
def list_dramas(session: Session = Depends(get_session)):
    return [to_detail(item) for item in session.exec(select(Drama).order_by(Drama.id.desc())).all()]


@router.get("/{drama_id}", response_model=DramaDetail)
def get_drama(drama_id: int, session: Session = Depends(get_session)):
    return to_detail(get_drama_or_404(drama_id, session))


@router.get("/{drama_id}/generated/{filename}")
def get_generated_video(drama_id: int, filename: str, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    generated_dir = (Path(drama.file_dir) / "generated").resolve()
    target = (generated_dir / Path(filename).name).resolve()
    if target.parent != generated_dir or not target.is_file() or target.suffix.lower() not in VIDEO_SUFFIXES:
        raise HTTPException(404, "成品不存在")
    return FileResponse(target, media_type="video/mp4", filename=target.name)


@router.put("/{drama_id}", response_model=DramaDetail)
def update_drama(drama_id: int, payload: DramaUpdate, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    for key, value in payload.model_dump().items():
        setattr(drama, key, value)
    session.add(drama)
    session.commit()
    session.refresh(drama)
    return to_detail(drama)


@router.put("/{drama_id}/highlights", response_model=DramaDetail)
def update_highlights(drama_id: int, payload: HighlightsPayload, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    folder = Path(drama.file_dir)
    episodes = {path.name for path in episode_files(folder)}
    try:
        write_highlights(folder, payload.highlights, episodes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return to_detail(drama)


@router.get("/{drama_id}/stills/{filename}")
def get_still(drama_id: int, filename: str, session: Session = Depends(get_session)):
    drama = get_drama_or_404(drama_id, session)
    stills_dir = (Path(drama.file_dir) / "stills").resolve()
    target = (stills_dir / Path(filename).name).resolve()
    if target.parent != stills_dir or not target.is_file() or target.suffix.lower() not in IMAGE_SUFFIXES:
        raise HTTPException(404, "剧照不存在")
    return FileResponse(target)
