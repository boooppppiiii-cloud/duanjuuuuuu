from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Clip, Drama, EmotionWord, FactoryJob, GeneratedAsset, HookAsset, MetricSnapshot, Post, PublishJob
from ..schemas import FactoryAnalysisReviewRequest, FactoryJobView, FactoryProcessRequest, GeneratedAssetView, HookAssetView
from ..services.factory_multimodal import FactoryAIUnavailableError, provider_name
from ..services.script_analysis import factory_analysis_pipeline, queued_analysis, queued_resume_analysis, read_analysis, update_review
from ..services.drama_library import episode_files
from ..services.factory_processing import factory_pipeline, sync_hook_assets


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
    settings = get_settings()
    try:
        provider, model = provider_name(settings)
        ai_ready = True
    except FactoryAIUnavailableError:
        provider, model, ai_ready = "", "", False
    base = result or {
        "status": "not_analyzed",
        "progress": 0,
        "current_step": "等待识别",
        "error_message": "",
        "drama_id": drama.id,
        "title": drama.title,
        "episodes": [],
        "episode_count": drama.episode_count,
        "total_duration": 0,
        "segment_count": 0,
        "high_energy_count": 0,
        "sensitive_count": 0,
        "sampled_frame_count": 0,
        "api_call_count": 0,
    }
    requires_reanalysis = bool(base.get("status") == "completed" and base.get("provider") not in {"gemini", "qwen"})
    return {
        **base, "ai_ready": ai_ready, "configured_provider": provider, "configured_model": model,
        "requires_reanalysis": requires_reanalysis, "is_active": factory_analysis_pipeline.is_active(drama_id),
    }


@router.post("/{drama_id}/analyze")
def run_script_analysis(drama_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    settings = get_settings()
    try:
        provider_name(settings)
    except FactoryAIUnavailableError as exc:
        raise HTTPException(422, str(exc)) from exc
    if factory_analysis_pipeline.is_active(drama_id):
        return read_analysis(Path(drama.file_dir))
    words = [item.word for item in session.exec(select(EmotionWord).where(EmotionWord.enabled == True)).all()]  # noqa: E712
    previous = read_analysis(Path(drama.file_dir)) or {}
    resume = previous.get("status") in {"queued", "processing", "failed"}
    result = (
        queued_resume_analysis(Path(drama.file_dir), drama.id, drama.title, drama.episode_count)
        if resume else queued_analysis(Path(drama.file_dir), drama.id, drama.title, drama.episode_count)
    )
    background_tasks.add_task(factory_analysis_pipeline.run, Path(drama.file_dir), drama.id, drama.title, settings, words, resume)
    return result


@router.patch("/{drama_id}/analysis/review")
def review_analysis(drama_id: int, payload: FactoryAnalysisReviewRequest, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    try:
        return update_review(
            Path(drama.file_dir), payload.episode, payload.kind, payload.start, payload.end,
            payload.decision, payload.new_start, payload.new_end,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{drama_id}/analysis/frames/{filename}")
def analysis_frame(drama_id: int, filename: str, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    root = (Path(drama.file_dir) / "analysis_frames").resolve()
    path = (root / Path(filename).name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "证据帧不存在")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.post("/{drama_id}/process", response_model=FactoryJobView)
def start_processing(drama_id: int, payload: FactoryProcessRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    sources = episode_files(Path(drama.file_dir))
    if not sources:
        raise HTTPException(422, "请先导入原片视频")
    analysis = read_analysis(Path(drama.file_dir))
    if payload.remove_sensitive and set(payload.output_modes) & {"clean_full", "hook_variants"} and (
        not analysis or analysis.get("status") != "completed" or analysis.get("provider") not in {"gemini", "qwen"}
    ):
        raise HTTPException(422, "请先完成脚本与敏感内容识别，再生成净化版或高能片头版")
    active = session.exec(select(FactoryJob).where(FactoryJob.drama_id == drama_id, FactoryJob.status.in_(["queued", "processing"]))).first()
    if active:
        raise HTTPException(409, f"该剧已有加工任务 #{active.id} 正在运行")
    sync_hook_assets(session, drama)
    valid_ids = {row.id for row in session.exec(select(HookAsset).where(HookAsset.active == True)).all()}  # noqa: E712
    invalid = [hook_id for hook_id in payload.hook_ids if hook_id not in valid_ids]
    if invalid:
        raise HTTPException(422, f"高能点不可用：{invalid[:5]}")
    job = FactoryJob(
        drama_id=drama_id,
        max_duration_seconds=payload.max_duration_seconds,
        hook_duration_seconds=payload.hook_duration_seconds,
        publish_variant_count=payload.publish_variant_count,
        remove_sensitive=payload.remove_sensitive,
        compression_profile=payload.compression_profile,
        output_modes=payload.output_modes,
        hooks_per_variant=payload.hooks_per_variant,
        selected_hook_ids=list(dict.fromkeys(payload.hook_ids)),
        source_files=[path.name for path in sources],
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(factory_pipeline.process_queued)
    return job


@router.get("/{drama_id}/jobs", response_model=list[FactoryJobView])
def list_jobs(drama_id: int, session: Session = Depends(get_session)):
    get_drama(drama_id, session)
    return session.exec(select(FactoryJob).where(FactoryJob.drama_id == drama_id).order_by(FactoryJob.id.desc())).all()


@router.get("/jobs/{job_id}", response_model=FactoryJobView)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(FactoryJob, job_id)
    if not job:
        raise HTTPException(404, "加工任务不存在")
    return job


@router.get("/{drama_id}/assets", response_model=list[GeneratedAssetView])
def list_assets(drama_id: int, session: Session = Depends(get_session)):
    get_drama(drama_id, session)
    return session.exec(select(GeneratedAsset).where(GeneratedAsset.drama_id == drama_id).order_by(GeneratedAsset.id.desc())).all()


@router.get("/assets/{asset_id}/download")
def download_asset(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(GeneratedAsset, asset_id)
    if not asset:
        raise HTTPException(404, "成品不存在")
    drama = get_drama(asset.drama_id, session)
    path = Path(asset.file_path).resolve()
    root = (Path(drama.file_dir) / "generated").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "成品文件不存在")
    return FileResponse(path, filename=asset.filename)


def hook_view(item: HookAsset, session: Session) -> HookAssetView:
    drama = session.get(Drama, item.drama_id)
    clips = session.exec(select(Clip).where(Clip.hook_asset_id == item.id)).all()
    clip_ids = [row.id for row in clips]
    posts = session.exec(select(Post).where(Post.clip_id.in_(clip_ids))).all() if clip_ids else []
    post_ids = [row.id for row in posts]
    jobs = session.exec(select(PublishJob).where(PublishJob.post_id.in_(post_ids))).all() if post_ids else []
    totals = {"views": 0, "likes": 0, "comments": 0}
    for job in jobs:
        latest = session.exec(select(MetricSnapshot).where(MetricSnapshot.publish_job_id == job.id).order_by(MetricSnapshot.date.desc())).first()
        if latest:
            totals["views"] += latest.views
            totals["likes"] += latest.likes
            totals["comments"] += latest.comments
    return HookAssetView(
        id=item.id, drama_id=item.drama_id, drama_title=drama.title if drama else "", episode=item.episode,
        start=item.start, end=item.end, note=item.note, source=item.source, energy_score=item.energy_score,
        active=item.active, use_count=item.use_count, published_count=sum(row.status == "published" for row in jobs),
        views=totals["views"], likes=totals["likes"], comments=totals["comments"],
        heat_score=totals["views"] + totals["likes"] * 3 + totals["comments"] * 5,
        last_used_at=item.last_used_at, preview_ready=bool(item.file_path and Path(item.file_path).is_file()),
    )


@router.post("/{drama_id}/hooks/sync", response_model=list[HookAssetView])
def sync_hooks(drama_id: int, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    return [hook_view(row, session) for row in sync_hook_assets(session, drama)]


@router.get("/hooks", response_model=list[HookAssetView])
def list_hooks(drama_id: int | None = None, active_only: bool = False, session: Session = Depends(get_session)):
    statement = select(HookAsset).order_by(HookAsset.id.desc())
    if drama_id is not None:
        statement = statement.where(HookAsset.drama_id == drama_id)
    if active_only:
        statement = statement.where(HookAsset.active == True)  # noqa: E712
    rows = [hook_view(item, session) for item in session.exec(statement).all()]
    return sorted(rows, key=lambda row: (row.heat_score, row.energy_score, row.id), reverse=True)


@router.patch("/hooks/{hook_id}", response_model=HookAssetView)
def set_hook_active(hook_id: int, active: bool, session: Session = Depends(get_session)):
    hook = session.get(HookAsset, hook_id)
    if not hook:
        raise HTTPException(404, "高能点不存在")
    hook.active = active
    session.add(hook)
    session.commit()
    session.refresh(hook)
    return hook_view(hook, session)


@router.get("/hooks/{hook_id}/video")
def hook_video(hook_id: int, session: Session = Depends(get_session)):
    hook = session.get(HookAsset, hook_id)
    path = Path(hook.file_path) if hook and hook.file_path else None
    if not path or not path.is_file():
        raise HTTPException(404, "该高能点尚未生成预览")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
