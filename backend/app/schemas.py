from pathlib import Path
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class DramaCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    total_episode_count: int = Field(ge=1, le=999)
    genres: list[str] = Field(min_length=1)
    is_ai_generated: bool = False
    is_dubbed_content: bool = False


class DramaUpdate(BaseModel):
    genres: list[str] = Field(default_factory=list)
    actor_names: list[str] = Field(default_factory=list)
    source_note: str = Field(min_length=1)
    is_ai_generated: bool = False

    @field_validator("source_note")
    @classmethod
    def source_note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("素材来源不能为空")
        return value.strip()


class Highlight(BaseModel):
    episode: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    note: str = ""


class HighlightsPayload(BaseModel):
    highlights: list[Highlight]


class GeneratedFile(BaseModel):
    name: str
    size: int
    created_at: datetime


class DramaDetail(BaseModel):
    id: int
    title: str
    description: str
    genres: list[str]
    is_ai_generated: bool
    is_dubbed_content: bool
    source_note: str
    actor_names: list[str]
    file_dir: str
    episode_count: int
    language: str
    promotion_episode_count: int
    total_episode_count: int
    episodes: list[str]
    stills: list[str]
    highlights: list[Highlight]
    generated_files: list[GeneratedFile]

    @staticmethod
    def safe_relative(path: Path, root: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()


class ScanLogEntry(BaseModel):
    path: str
    status: str
    message: str


class ScanResult(BaseModel):
    scan_root: str
    logs: list[ScanLogEntry]
    dramas: list[DramaDetail]


class ManualRegisterRequest(BaseModel):
    title: str = Field(min_length=1)
    absolute_path: str = Field(min_length=1)
    source_note: str = Field(min_length=1)


class UploadInitRequest(BaseModel):
    drama_title: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    total_size: int = Field(gt=0)
    total_chunks: int = Field(gt=0)
    source_note: str = Field(min_length=1)
    destination: Literal["episodes", "stills"] = "episodes"


class UploadInitResult(BaseModel):
    upload_id: str
    received_chunks: list[int]


class ClipCreateRequest(BaseModel):
    drama_id: int
    template_name: str = "suspense_hook"

    @field_validator("template_name")
    @classmethod
    def safe_template_name(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("模板名称只能包含字母、数字、下划线和短横线")
        return value


class ClipView(BaseModel):
    id: int
    drama_id: int
    template_name: str
    source_eps: list[str]
    source_start: float
    source_end: float
    duration: float
    file_path: str
    subtitle_text: str
    status: str
    preview_image: str
    audio_replaced: bool
    progress: int
    current_step: str
    error_message: str
    hit_words: list[str]
    review_note: str
    reviewed_at: Optional[datetime]
    error_advice: str
    hook_asset_id: Optional[int] = None
    factory_job_id: Optional[int] = None
    asset_kind: str = "legacy"


class FactoryProcessRequest(BaseModel):
    max_duration_seconds: int = Field(default=180, ge=60, le=180)
    hook_duration_seconds: float = Field(default=3, ge=1, le=5)
    publish_variant_count: int = Field(default=5, ge=0, le=50)
    remove_sensitive: bool = True
    compression_profile: Literal["balanced", "small"] = "balanced"
    hook_ids: list[int] = Field(default_factory=list)


class FactoryJobView(BaseModel):
    id: int
    drama_id: int
    status: str
    current_step: str
    progress: int
    max_duration_seconds: int
    hook_duration_seconds: float
    publish_variant_count: int
    remove_sensitive: bool
    compression_profile: str
    selected_hook_ids: list[int]
    source_files: list[str]
    clean_count: int
    publish_count: int
    total_duration: float
    removed_seconds: float
    output_bytes: int
    output_dir: str
    warnings: list[str]
    error_message: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class GeneratedAssetView(BaseModel):
    id: int
    factory_job_id: int
    drama_id: int
    kind: str
    sequence: int
    filename: str
    duration: float
    size_bytes: int
    hook_asset_id: Optional[int]
    clip_id: Optional[int]
    created_at: datetime


class HookAssetView(BaseModel):
    id: int
    drama_id: int
    drama_title: str
    episode: str
    start: float
    end: float
    note: str
    source: str
    energy_score: float
    active: bool
    use_count: int
    published_count: int
    views: int
    likes: int
    comments: int
    heat_score: int
    last_used_at: Optional[datetime]
    preview_ready: bool


class ClipReviewRequest(BaseModel):
    status: str
    note: str = ""

    @field_validator("status")
    @classmethod
    def review_status_only(cls, value: str) -> str:
        if value not in {"approved", "blocked"}:
            raise ValueError("人工复核只能选择通过或拦截")
        return value


class TextModerationRequest(BaseModel):
    title: str = ""
    caption: str = ""


class TextModerationResult(BaseModel):
    hit_words: list[str]
    safe: bool
    highlighted_title: list[dict]
    highlighted_caption: list[dict]


class TitleGenerationRequest(BaseModel):
    clip_id: int
    account_type: str
    account_id: Optional[int] = None
    target_language: str = "English"
    formula: int | str = "auto"
    hot_tags: list[str] = Field(default_factory=list)

    @field_validator("account_type")
    @classmethod
    def account_type_valid(cls, value: str) -> str:
        if value not in {"official", "creator"}:
            raise ValueError("账号类型必须是 official 或 creator")
        return value


class HotNotePayload(BaseModel):
    content: str = Field(min_length=1)
    platform: str = "tiktok"
    expires_at: datetime

class TitleCandidate(BaseModel):
    formula: int = Field(ge=1, le=4)
    title: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    hashtags: list[str]
    hit_words: list[str] = Field(default_factory=list)


class TitleCandidates(BaseModel):
    candidates: list[TitleCandidate] = Field(min_length=3, max_length=3)
    degraded: bool = False
    provider: str = "remote"
    context_used: list[str] = Field(default_factory=list)


class LibraryItemPayload(BaseModel):
    content: str = Field(min_length=1)
    genres: list[str] = Field(default_factory=list)
    language: str = "English"
    platform: str = "all"
    enabled: bool = True


class TagItemPayload(BaseModel):
    tag: str = Field(min_length=1)
    genres: list[str] = Field(default_factory=list)
    language: str = "English"
    platform: str = "all"
    enabled: bool = True


class BatchExamplesRequest(BaseModel):
    text: str = Field(min_length=1)
    genres: list[str] = Field(default_factory=list)
    language: str = "English"
    platform: str = "all"


class PostCreateRequest(BaseModel):
    clip_id: int
    account_type: str
    candidate: TitleCandidate


class BasemapGenerateRequest(BaseModel):
    drama_id: int
    still_filename: str


class BasemapReviewRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def basemap_status_valid(cls, value: str) -> str:
        if value not in {"approved", "rejected"}:
            raise ValueError("底图只能批准或拒绝")
        return value


class CoverCreateRequest(BaseModel):
    post_id: int
    account_type: str
    fallback_image: str = ""


class AccountCreateRequest(BaseModel):
    platform: str
    name: str
    account_type: str
    is_new: bool = True
    credentials_json: dict = Field(default_factory=dict)
    strategy_id: Optional[int] = None


class AccountConfigureRequest(BaseModel):
    platform: str
    name: str = ""
    account_type: str = "official"
    strategy_id: Optional[int] = None
    public_config: dict[str, str | bool | int] = Field(default_factory=dict)
    secret_envs: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class PlatformAppConfigRequest(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class AccountStrategyPayload(BaseModel):
    name: str
    positioning: str
    persona_keywords: list[str] = Field(default_factory=list)
    tone_examples: str = ""
    daily_posts: int = Field(default=1, ge=1, le=10)
    posting_times: list[str] = Field(default_factory=lambda: ["20:00"])
    tag_pool: list[str] = Field(default_factory=list)
    default_clip_template: str = "suspense_hook"
    title_formula_preference: int = Field(default=2, ge=1, le=4)
    confirmed: bool = True


class StrategySummaryRequest(BaseModel):
    name: str
    history_text: str = Field(min_length=10)


class PublishJobCreateRequest(BaseModel):
    post_id: int
    account_id: int
    scheduled_at: datetime
    channel: str = "auto"
    ai_disclosure: bool = False
    publish_options: dict = Field(default_factory=dict)


class PublishJobUpdateRequest(BaseModel):
    scheduled_at: Optional[datetime] = None
    ai_disclosure: Optional[bool] = None


class RecurringPublishRequest(BaseModel):
    post_ids: list[int]
    account_id: int
    start_at: datetime
    times: list[str]


class MetaSFSRequest(BaseModel):
    drama_id: int
    series_slug: str = ""
    description: str = Field(min_length=1)
    locale: str = "en_US"
    genres: list[str] = Field(default_factory=lambda: ["Drama"])
    release_date: str
    cast_list: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    geogating: list[str] = Field(default_factory=list)
    ai_content: bool = False
    dubbed_content: bool = False
    include_episode_csv: bool = True
    include_thumbnails: bool = True

    @field_validator("locale")
    @classmethod
    def locale_format(cls, value: str) -> str:
        if len(value) != 5 or value[2] != "_" or not value[:2].islower() or not value[3:].isupper():
            raise ValueError("Locale 必须使用 language_REGION 格式，例如 en_US")
        return value


class CommentImportItem(BaseModel):
    external_id: str = ""
    platform: str = "youtube"
    account_id: Optional[int] = None
    video_id: str = ""
    video_title: str = ""
    video_url: str = ""
    author_name: str = ""
    author_handle: str = ""
    text_original: str = Field(min_length=1)
    text_zh: str = ""
    like_count: int = 0
    published_at: Optional[datetime] = None


class CommentImportRequest(BaseModel):
    items: list[CommentImportItem] = Field(min_length=1, max_length=1000)


class CommentAnalyzeRequest(BaseModel):
    comment_ids: list[int] = Field(default_factory=list)
    use_ai: bool = False


class CommentStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def comment_status(cls, value: str) -> str:
        allowed = {"pending", "following", "resolved", "ignored", "replied"}
        if value not in allowed:
            raise ValueError("评论状态不合法")
        return value


class YouTubeSyncRequest(BaseModel):
    account_ids: list[int] = Field(default_factory=list)
    max_videos: int = Field(default=10, ge=1, le=50)


class BatchPublishRequest(BaseModel):
    post_ids: list[int] = Field(min_length=1, max_length=100)
    account_ids: list[int] = Field(min_length=1, max_length=100)
    scheduled_at: datetime
    ai_disclosure: bool = False
    run_now: bool = False
    publish_options: dict = Field(default_factory=dict)


class CommentSyncRequest(BaseModel):
    account_ids: list[int] = Field(default_factory=list)
    max_comments: int = Field(default=100, ge=1, le=500)


class CommentReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
