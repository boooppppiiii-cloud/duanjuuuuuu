from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from sqlmodel import Session

from .database import create_db_and_tables, engine
from .routers.dramas import router as dramas_router
from .routers.clips import router as clips_router
from .routers.moderation import router as moderation_router
from .routers.creative import router as creative_router
from .routers.publish import router as publish_router
from .routers.metrics import router as metrics_router
from .routers.library import router as library_router
from .routers.hooks import router as hooks_router
from .routers.notes import router as notes_router
from .routers.meta_sfs import router as meta_sfs_router
from .routers.engagement import router as engagement_router
from .routers.workspace import router as workspace_router
from .routers.integrations import router as integrations_router
from .routers.factory import router as factory_router
from .routers.auth import router as auth_router
from .routers.admin import router as admin_router
from .routers.radar import router as radar_router
from .scheduler import scheduler
from .logging_config import configure_logging
from .services.factory_processing import resume_factory_jobs
from .services.meta_package_processing import resume_meta_packages
from .services.script_analysis import resume_factory_analyses
from .services.offline_translation import start_translation_worker
from .services.storage_paths import reconcile_database_media_paths
from .services.auth import bind_current_user, initialize_auth, reset_current_user, resolve_user
from .services.usage import feature_for, record_usage
import time

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    initialize_auth()
    with Session(engine) as session:
        repaired = reconcile_database_media_paths(session, get_settings().media_root)
        if repaired:
            logger.info("已修复 %s 个迁移后的媒体路径", repaired)
    resume_factory_jobs()
    resume_meta_packages()
    resumed_analyses = resume_factory_analyses()
    if resumed_analyses:
        logger.info("已恢复 %s 个内容识别任务", resumed_analyses)
    start_translation_worker()
    if not scheduler.running:
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="剧枢", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dramas_router)
app.include_router(clips_router)
app.include_router(moderation_router)
app.include_router(creative_router)
app.include_router(publish_router)
app.include_router(metrics_router)
app.include_router(library_router)
app.include_router(hooks_router)
app.include_router(notes_router)
app.include_router(meta_sfs_router)
app.include_router(engagement_router)
app.include_router(workspace_router)
app.include_router(integrations_router)
app.include_router(factory_router)
app.include_router(radar_router)


@app.middleware("http")
async def authentication_and_metering(request: Request, call_next):
    path = request.url.path
    public = (
        request.method == "OPTIONS"
        or path in {"/api/health", "/api/auth/login", "/api/auth/register", "/api/factory/analysis-window", "/docs", "/openapi.json", "/favicon.ico"}
        or path.startswith("/api/publish/media/")
        or path.startswith("/api/meta-sfs/legacy-assets/")
    )
    user = None
    login = None
    user_id = None
    if not public:
        raw_token = request.cookies.get(get_settings().auth_cookie_name, "")
        with Session(engine) as session:
            resolved = resolve_user(session, raw_token)
            if resolved:
                user, login = resolved
                # Keep primitive values before the session closes. Middleware
                # logging must never trigger lazy loading on a detached model.
                user_id = int(user.id)
        if path.startswith("/api/") and not user:
            return JSONResponse(status_code=401, content={"detail": "登录已过期，请重新登录"})
    request.state.user = user
    request.state.login_session = login
    context_token = bind_current_user(user_id)
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        if user_id is not None and path.startswith("/api/") and path not in {"/api/auth/me", "/api/auth/logout"}:
            record_usage(
                feature_for(request.method, path), user_id=user_id, event_kind="api_request",
                endpoint=path, api_calls=1, success=bool(response and response.status_code < 400), duration_ms=duration_ms,
                details={"method": request.method, "status_code": response.status_code if response else 500},
            )
        reset_current_user(context_token)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("未处理请求错误 method=%s path=%s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器处理失败", "advice": "请查看 logs/app.log 最近错误，修复后重试", "error": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}
