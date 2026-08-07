from functools import lru_cache
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_translation_model_dir() -> Path:
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Jushu" / "argos" / "packages"
    return Path("backend/data/argos/packages")


class Settings(BaseSettings):
    """集中读取环境变量，避免在业务代码中散落路径配置。"""

    database_url: str = "sqlite:///./backend/data/app.db"
    media_root: Path = Path("media")
    max_upload_file_bytes: int = 50 * 1024 * 1024 * 1024
    upload_free_space_reserve_bytes: int = 1024 * 1024 * 1024
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174"
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-2.5-flash"
    gemini_image_model: str = "gemini-3.1-flash-image"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    youtube_api_key: str = ""
    youtube_channel_ids: str = ""
    public_api_origin: str = "http://127.0.0.1:8000"
    public_ui_origin: str = "http://127.0.0.1:5174"
    credential_secret: str = ""
    meta_graph_version: str = "v24.0"
    public_media_base_url: str = ""
    google_drive_service_account_file: str = ""
    google_drive_parent_folder_id: str = ""
    serverchan_key: str = ""
    visual_daily_limit: int = 200
    log_dir: Path = Path("logs")
    offline_translation_enabled: bool = True
    offline_translation_languages: str = "auto"
    offline_translation_target: str = "zh"
    offline_translation_auto_install: bool = True
    offline_translation_model_dir: Path = _default_translation_model_dir()
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def youtube_channel_id_list(self) -> list[str]:
        return [item.strip() for item in self.youtube_channel_ids.split(",") if item.strip()]

    @property
    def api_origin(self) -> str:
        return self.public_api_origin.rstrip("/")

    @property
    def offline_translation_language_list(self) -> list[str]:
        return [item.strip().lower() for item in self.offline_translation_languages.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
