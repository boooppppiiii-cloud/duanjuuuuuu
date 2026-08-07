from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import create_db_and_tables
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
from .scheduler import scheduler
from .logging_config import configure_logging
from .services.factory_processing import resume_factory_jobs
from .services.offline_translation import start_translation_worker

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    resume_factory_jobs()
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


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("未处理请求错误 method=%s path=%s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器处理失败", "advice": "请查看 logs/app.log 最近错误，修复后重试", "error": str(exc)})


@app.get("/api/health")
def health():
    return {"status": "ok"}
