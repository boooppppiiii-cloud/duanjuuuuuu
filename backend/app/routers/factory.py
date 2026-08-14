from pathlib import Path
from datetime import datetime
import base64
import binascii
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import threading
import time
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import AppUser, Clip, CloudAsset, Drama, EmotionWord, FactoryJob, GeneratedAsset, HookAsset, MetricSnapshot, Post, PublishJob
from ..schemas import CloudAssetView, FactoryAnalysisFrameRequest, FactoryAnalysisReviewRequest, FactoryAnalysisStartRequest, FactoryAnalysisWindowRequest, FactoryJobView, FactoryManualSensitiveRequest, FactoryProcessRequest, GeneratedAssetView, HookAssetView
from ..services.factory_multimodal import FactoryAIUnavailableError, FrameSample, analyze_window, provider_name
from ..services.script_analysis import ANALYSIS_VERSION, add_manual_sensitive, factory_analysis_pipeline, queued_analysis, queued_resume_analysis, read_analysis, update_review, write_analysis
from ..services.drama_library import episode_files
from ..services.factory_processing import factory_pipeline, sync_hook_assets
from ..services.auth import bind_current_user, get_current_user, reset_current_user
from ..services.usage import record_usage


router = APIRouter(prefix="/api/factory", tags=["内容工厂"])


def _run_analysis_as_user(user_id: int, *args, ai_analyzer=None) -> None:
    token = bind_current_user(user_id)
    try:
        factory_analysis_pipeline.run_with_analyzer(*args, ai_analyzer=ai_analyzer)
    finally:
        reset_current_user(token)


def _analysis_token(user_id: int, expires_at: int) -> str:
    secret = get_settings().credential_secret.encode("utf-8")
    if not secret:
        raise HTTPException(503, "服务器尚未启用模型代理签名")
    payload = base64.urlsafe_b64encode(f"{user_id}:{expires_at}".encode()).decode().rstrip("=")
    signature = hmac.new(secret, f"factory-analysis:{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _analysis_token_user(authorization: str) -> int:
    raw = authorization.removeprefix("Bearer ").strip()
    secret = get_settings().credential_secret.encode()
    if not secret:
        raise HTTPException(503, "服务器尚未启用模型代理签名")
    try:
        payload, signature = raw.split(".", 1)
        expected = hmac.new(
            secret, f"factory-analysis:{payload}".encode(), hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        user_id, expires_at = decoded.split(":", 1)
        if int(expires_at) < int(time.time()):
            raise ValueError
        return int(user_id)
    except (ValueError, TypeError, binascii.Error):
        raise HTTPException(401, "模型代理授权已失效，请重新开始识别")


def _proxy_analyzer(origin: str, token: str):
    allowed = {
        "https://app.duanju.chat",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }
    origin = origin.rstrip("/")
    if origin not in allowed or not token:
        raise HTTPException(422, "本地识别缺少有效的服务器模型授权")

    def call(episode: str, window_start: float, window_end: float, transcript: list[dict], frames: list[FrameSample]):
        payload = {
            "episode": episode, "window_start": window_start, "window_end": window_end,
            "transcript": transcript,
            "frames": [{
                "index": frame.index, "second": frame.second,
                "data": base64.b64encode(frame.path.read_bytes()).decode("ascii"),
            } for frame in frames],
        }
        response = httpx.post(
            f"{origin}/api/factory/analysis-window", json=payload,
            headers={"Authorization": f"Bearer {token}"}, timeout=180,
        )
        if response.status_code == 401:
            raise RuntimeError("服务器模型授权已失效，请重新开始识别")
        response.raise_for_status()
        data = response.json()
        return data["result"], data["provider"], data["model"]

    return call


def get_drama(drama_id: int, session: Session) -> Drama:
    drama = session.get(Drama, drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    return drama


@router.post("/analysis-access")
def create_analysis_access(user: AppUser = Depends(get_current_user)):
    settings = get_settings()
    try:
        provider, model = provider_name(settings)
    except FactoryAIUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    expires_at = int(time.time()) + 24 * 60 * 60
    return {
        "token": _analysis_token(int(user.id), expires_at),
        "expires_at": expires_at,
        "provider": provider,
        "model": model,
    }


@router.post("/analysis-window")
def analyze_local_window(payload: FactoryAnalysisWindowRequest, authorization: str = Header(default="")):
    if payload.window_end <= payload.window_start:
        raise HTTPException(422, "分析窗口结束时间必须晚于开始时间")
    user_id = _analysis_token_user(authorization)
    settings = get_settings()
    token = bind_current_user(user_id)
    try:
        with tempfile.TemporaryDirectory(prefix="jushu-analysis-") as directory:
            root = Path(directory)
            frames: list[FrameSample] = []
            for item in payload.frames:
                try:
                    data = base64.b64decode(item.data, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise HTTPException(422, "抽帧数据不合法") from exc
                if not data or len(data) > 1_500_000:
                    raise HTTPException(413, "单张抽帧不能超过 1.5MB")
                path = root / f"frame-{item.index:03d}.jpg"
                path.write_bytes(data)
                frames.append(FrameSample(index=item.index, second=item.second, path=path))
            try:
                result, provider, model = analyze_window(
                    settings, payload.episode, payload.window_start, payload.window_end,
                    payload.transcript, frames,
                )
            except FactoryAIUnavailableError as exc:
                raise HTTPException(503, str(exc)) from exc
            return {"result": result, "provider": provider, "model": model}
    finally:
        reset_current_user(token)


@router.get("/{drama_id}/analysis")
def get_script_analysis(drama_id: int, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    result = read_analysis(Path(drama.file_dir))
    settings = get_settings()
    try:
        provider, model = provider_name(settings)
        ai_ready = True
    except FactoryAIUnavailableError:
        if settings.factory_model_proxy_enabled:
            provider, model, ai_ready = "server_proxy", "server_managed", True
        else:
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
    requires_reanalysis = bool(
        base.get("status") == "completed"
        and (base.get("provider") not in {"gemini", "qwen"} or int(base.get("analysis_version", 0)) != ANALYSIS_VERSION)
    )
    return {
        **base, "ai_ready": ai_ready, "configured_provider": provider, "configured_model": model,
        "requires_reanalysis": requires_reanalysis, "is_active": factory_analysis_pipeline.is_active(drama_id),
    }


@router.put("/{drama_id}/analysis/local")
def import_local_analysis(
    drama_id: int,
    payload: dict,
    session: Session = Depends(get_session),
    user: AppUser = Depends(get_current_user),
):
    """Persist the small reusable analysis result while keeping source videos on the operator's PC."""
    drama = get_drama(drama_id, session)
    if payload.get("status") != "completed" or int(payload.get("drama_id", -1)) != drama_id:
        raise HTTPException(422, "只能同步当前剧目已完成的本地识别结果")
    episodes = payload.get("episodes")
    if not isinstance(episodes, list) or not episodes or len(episodes) > 5000:
        raise HTTPException(422, "本地识别结果的剧集清单不合法")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 25 * 1024 * 1024:
        raise HTTPException(413, "识别结果超过 25MB，请减少冗余脚本后重试")
    cleaned = dict(payload)
    cleaned["drama_id"] = drama_id
    cleaned["title"] = drama.title
    cleaned["storage_mode"] = "local_workspace"
    cleaned["synced_by_user_id"] = user.id
    cleaned["source_files"] = [str(item.get("episode", ""))[:500] for item in episodes if isinstance(item, dict)]
    result = write_analysis(Path(drama.file_dir), cleaned)
    drama.episode_count = len(episodes)
    session.add(drama)
    session.commit()
    sync_hook_assets(session, drama)
    record_usage(
        "内容识别",
        user_id=user.id,
        event_kind="feature",
        success=True,
        client_event_id=f"local-analysis:{user.id}:{drama_id}:{payload.get('generated_at') or payload.get('updated_at') or 'completed'}",
        details={"drama_id": drama_id, "storage_mode": "local_workspace", "episodes": len(episodes)},
    )
    return result


@router.post("/{drama_id}/analyze")
def run_script_analysis(
    drama_id: int, payload: FactoryAnalysisStartRequest | None = None,
    session: Session = Depends(get_session), user: AppUser = Depends(get_current_user),
):
    drama = get_drama(drama_id, session)
    settings = get_settings()
    analyzer = None
    if payload and payload.proxy_origin and payload.proxy_token:
        analyzer = _proxy_analyzer(payload.proxy_origin, payload.proxy_token)
    else:
        try:
            provider_name(settings)
        except FactoryAIUnavailableError as exc:
            raise HTTPException(422, str(exc)) from exc
    if factory_analysis_pipeline.is_active(drama_id):
        return read_analysis(Path(drama.file_dir))
    words = [item.word for item in session.exec(select(EmotionWord).where(EmotionWord.enabled == True)).all()]  # noqa: E712
    previous = read_analysis(Path(drama.file_dir)) or {}
    if previous.get("status") == "completed" and int(previous.get("analysis_version", 0)) == ANALYSIS_VERSION:
        record_usage("内容识别", user_id=user.id, event_kind="feature", cache_hit=True, details={"drama_id": drama_id})
        return previous
    resume = (
        previous.get("status") in {"queued", "processing", "failed"}
        and int(previous.get("analysis_version", 0)) == ANALYSIS_VERSION
    )
    result = (
        queued_resume_analysis(Path(drama.file_dir), drama.id, drama.title, drama.episode_count)
        if resume else queued_analysis(Path(drama.file_dir), drama.id, drama.title, drama.episode_count)
    )
    # The local assistant must keep the analysis alive after the HTTP response has
    # completed. FastAPI response background tasks could be lost when the browser
    # retried or the helper request was cancelled, leaving a permanent "queued"
    # record with no worker. A daemon worker is owned by the helper process instead.
    threading.Thread(
        target=_run_analysis_as_user,
        args=(user.id, Path(drama.file_dir), drama.id, drama.title, settings, words, resume),
        kwargs={"ai_analyzer": analyzer},
        name=f"factory-analysis-{drama.id}",
        daemon=True,
    ).start()
    record_usage("内容识别", user_id=user.id, event_kind="feature", cache_hit=False, details={"drama_id": drama_id, "resume": resume})
    return {**result, "is_active": True}


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


@router.post("/{drama_id}/analysis/sensitive/manual")
def mark_manual_sensitive(drama_id: int, payload: FactoryManualSensitiveRequest, session: Session = Depends(get_session)):
    drama = get_drama(drama_id, session)
    try:
        return add_manual_sensitive(
            Path(drama.file_dir), payload.episode, payload.start, payload.end, payload.category, payload.note,
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


@router.get("/{drama_id}/analysis/video/{episode}")
def analysis_video(drama_id: int, episode: str, session: Session = Depends(get_session)):
    """Stream an original episode inline so the review timeline can seek without copying it."""
    drama = get_drama(drama_id, session)
    path = next((item for item in episode_files(Path(drama.file_dir)) if item.name == episode), None)
    if path is None or not path.is_file():
        raise HTTPException(404, "原片视频不存在")
    media_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name, content_disposition_type="inline")


@router.post("/{drama_id}/process", response_model=FactoryJobView)
def start_processing(drama_id: int, payload: FactoryProcessRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    drama = get_drama(drama_id, session)
    sources = episode_files(Path(drama.file_dir))
    if not sources:
        raise HTTPException(422, "请先导入原片视频")
    analysis = read_analysis(Path(drama.file_dir))
    if payload.remove_sensitive and set(payload.output_modes) & {"clean_full", "hook_variants"} and (
        not analysis or analysis.get("status") != "completed" or analysis.get("provider") not in {"gemini", "qwen"}
    ):
        raise HTTPException(422, "请先完成脚本与敏感内容识别，再生成净化版或高能片头版")
    active = session.exec(select(FactoryJob).where(FactoryJob.drama_id == drama_id, FactoryJob.owner_user_id == user.id, FactoryJob.status.in_(["queued", "processing"]))).first()
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
        owner_user_id=user.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(factory_pipeline.process_queued)
    return job


@router.get("/{drama_id}/jobs", response_model=list[FactoryJobView])
def list_jobs(drama_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    get_drama(drama_id, session)
    return session.exec(select(FactoryJob).where(FactoryJob.drama_id == drama_id, FactoryJob.owner_user_id == user.id).order_by(FactoryJob.id.desc())).all()


@router.get("/jobs/{job_id}", response_model=FactoryJobView)
def get_job(job_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    job = session.get(FactoryJob, job_id)
    if not job or job.owner_user_id != user.id:
        raise HTTPException(404, "加工任务不存在")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=FactoryJobView)
def cancel_job(job_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    job = session.get(FactoryJob, job_id)
    if not job or job.owner_user_id != user.id:
        raise HTTPException(404, "加工任务不存在")
    if job.status == "queued":
        job.status = "cancelled"
        job.current_step = "已取消"
        job.completed_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        # Cover the small race in which the worker has already selected the
        # queued row but has not committed its processing state yet.
        factory_pipeline.request_cancel(job_id)
        return job
    if job.status in {"processing", "cancel_requested"}:
        if job.status == "processing":
            job.status = "cancel_requested"
            job.current_step = "正在取消并清理中间文件"
            session.add(job)
            session.commit()
            session.refresh(job)
        factory_pipeline.request_cancel(job_id)
        return job
    return job


@router.get("/{drama_id}/assets", response_model=list[GeneratedAssetView])
def list_assets(drama_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    get_drama(drama_id, session)
    return session.exec(select(GeneratedAsset).where(GeneratedAsset.drama_id == drama_id, GeneratedAsset.owner_user_id == user.id).order_by(GeneratedAsset.id.desc())).all()


@router.get("/assets/{asset_id}/download")
def download_asset(asset_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    asset = session.get(GeneratedAsset, asset_id)
    if not asset or asset.owner_user_id != user.id:
        raise HTTPException(404, "成品不存在")
    drama = get_drama(asset.drama_id, session)
    path = Path(asset.file_path).resolve()
    root = (Path(drama.file_dir) / "generated").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "成品文件不存在")
    return FileResponse(path, filename=asset.filename)


def cloud_view(item: CloudAsset, session: Session) -> CloudAssetView:
    drama = session.get(Drama, item.drama_id)
    uploader = session.get(AppUser, item.uploader_user_id)
    return CloudAssetView(
        id=item.id, drama_id=item.drama_id, drama_title=drama.title if drama else "",
        uploader_email=uploader.email if uploader else "已删除用户", kind=item.kind, filename=item.filename,
        size_bytes=item.size_bytes, duration=item.duration, download_count=item.download_count,
        storage_backend=item.storage_backend, created_at=item.created_at,
    )


@router.post("/assets/{asset_id}/cloud", response_model=CloudAssetView)
def upload_to_cloud_library(asset_id: int, session: Session = Depends(get_session), user: AppUser = Depends(get_current_user)):
    asset = session.get(GeneratedAsset, asset_id)
    if not asset or asset.owner_user_id != user.id:
        raise HTTPException(404, "成品不存在")
    existing = session.exec(select(CloudAsset).where(CloudAsset.source_asset_id == asset.id)).first()
    if existing:
        record_usage("上传云剧库", user_id=user.id, event_kind="feature", cache_hit=True, details={"asset_id": asset.id})
        return cloud_view(existing, session)
    source = Path(asset.file_path).resolve()
    if not source.is_file():
        raise HTTPException(404, "成品文件不存在")
    settings = get_settings()
    root = settings.cloud_storage_root.resolve()
    target_dir = root / str(asset.drama_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}_{Path(asset.filename).name}"
    backend = "local_hardlink"
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
        backend = "local_copy"
    item = CloudAsset(
        drama_id=asset.drama_id, source_asset_id=asset.id, uploader_user_id=user.id, kind=asset.kind,
        filename=asset.filename, storage_backend=backend, storage_key=str(target), size_bytes=asset.size_bytes,
        duration=asset.duration, created_at=datetime.utcnow(),
    )
    session.add(item); session.commit(); session.refresh(item)
    record_usage("上传云剧库", user_id=user.id, event_kind="feature", details={"asset_id": asset.id, "storage_backend": backend})
    return cloud_view(item, session)


@router.get("/cloud-assets", response_model=list[CloudAssetView])
def list_cloud_assets(session: Session = Depends(get_session)):
    rows = session.exec(select(CloudAsset).order_by(CloudAsset.created_at.desc())).all()
    return [cloud_view(row, session) for row in rows]


@router.get("/cloud-assets/{cloud_id}/download")
def download_cloud_asset(cloud_id: int, session: Session = Depends(get_session)):
    item = session.get(CloudAsset, cloud_id)
    if not item:
        raise HTTPException(404, "云剧库文件不存在")
    path = Path(item.storage_key).resolve()
    root = get_settings().cloud_storage_root.resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "云剧库文件不存在")
    item.download_count += 1; session.add(item); session.commit()
    return FileResponse(path, filename=item.filename)


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
