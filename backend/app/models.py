from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class AppUser(SQLModel, table=True):
    """Application user. Shared business data deliberately does not reference this table."""

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_developer: bool = False
    is_active: bool = True
    email_verified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_login_at: Optional[datetime] = None


class UserSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    user_agent: str = ""
    ip_address: str = ""


class UsageEvent(SQLModel, table=True):
    """Immutable, server-observed usage ledger used by the developer dashboard."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="appuser.id", index=True)
    event_kind: str = Field(index=True)
    feature: str = Field(index=True)
    endpoint: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    success: bool = True
    cache_hit: bool = False
    duration_ms: int = 0
    client_event_id: Optional[str] = Field(default=None, index=True, unique=True)
    details_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str
    name: str
    account_type: str
    is_new: bool = True
    credentials_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "not_connected"
    strategy_id: Optional[int] = Field(default=None, foreign_key="accountstrategy.id")
    auto_publish: bool = False
    platform_user_id: str = Field(default="", index=True)
    avatar_url: str = ""
    profile_url: str = ""
    follower_count: int = 0
    last_checked_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    removed_at: Optional[datetime] = None
    last_error: str = ""
    capabilities: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class PlatformApp(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str = Field(index=True, unique=True)
    client_id: str = ""
    client_secret_encrypted: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AccountStrategy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    history_text: str = ""
    positioning: str = "女频"
    persona_keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tone_examples: str = ""
    daily_posts: int = 1
    posting_times: list[str] = Field(default_factory=lambda: ["20:00"], sa_column=Column(JSON))
    tag_pool: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    default_clip_template: str = "suspense_hook"
    title_formula_preference: int = 2
    builtin: bool = False
    confirmed: bool = True


class Drama(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True, unique=True)
    theater: str = ""
    description: str = ""
    genres: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    is_ai_generated: bool = False
    is_dubbed_content: bool = False
    source_note: str = "待补充"
    actor_names: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    file_dir: str = Field(unique=True)
    episode_count: int = 0
    language: str = "en_US"
    promotion_episode_count: int = 1
    total_episode_count: int = 1
    cover_vertical_path: str = ""
    cover_square_path: str = ""
    cover_horizontal_path: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Basemap(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    file_path: str
    source: str
    status: str = "pending"


class Clip(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    template_name: str
    source_eps: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_start: float = 0
    source_end: float = 0
    duration: float = 0
    file_path: str = ""
    subtitle_text: str = ""
    status: str = "pending"
    preview_image: str = ""
    audio_replaced: bool = False
    progress: int = 0
    current_step: str = "queued"
    error_message: str = ""
    hit_words: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    review_note: str = ""
    reviewed_at: Optional[datetime] = None
    error_advice: str = ""
    hook_asset_id: Optional[int] = Field(default=None, foreign_key="hookasset.id", index=True)
    factory_job_id: Optional[int] = Field(default=None, foreign_key="factoryjob.id", index=True)
    asset_kind: str = "legacy"
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class FactoryJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    status: str = Field(default="queued", index=True)
    current_step: str = "queued"
    progress: int = 0
    max_duration_seconds: int = 180
    hook_duration_seconds: float = 3
    publish_variant_count: int = 5
    remove_sensitive: bool = True
    compression_profile: str = "balanced"
    output_modes: list[str] = Field(default_factory=lambda: ["clean_full", "hook_variants"], sa_column=Column(JSON))
    hooks_per_variant: int = 1
    selected_hook_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    source_files: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    clean_count: int = 0
    publish_count: int = 0
    meta_count: int = 0
    total_duration: float = 0
    removed_seconds: float = 0
    output_bytes: int = 0
    output_dir: str = ""
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    error_message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class GeneratedAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    factory_job_id: int = Field(foreign_key="factoryjob.id", index=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    kind: str = Field(index=True)
    sequence: int = 1
    file_path: str = Field(unique=True)
    filename: str
    duration: float = 0
    size_bytes: int = 0
    hook_asset_id: Optional[int] = Field(default=None, foreign_key="hookasset.id", index=True)
    hook_asset_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    clip_id: Optional[int] = Field(default=None, foreign_key="clip.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class CloudAsset(SQLModel, table=True):
    """An explicitly shared copy of a generated asset."""

    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    source_asset_id: Optional[int] = Field(default=None, foreign_key="generatedasset.id", index=True)
    uploader_user_id: int = Field(foreign_key="appuser.id", index=True)
    kind: str = Field(index=True)
    filename: str
    storage_backend: str = "local"
    storage_key: str = Field(unique=True)
    size_bytes: int = 0
    duration: float = 0
    download_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class HookAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    episode: str
    start: float
    end: float
    note: str = ""
    source: str = "manual"
    energy_score: float = 0
    file_path: str = ""
    active: bool = True
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Post(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    clip_id: int = Field(foreign_key="clip.id", index=True)
    title: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    basemap_id: Optional[int] = Field(default=None, foreign_key="basemap.id")
    cover_path_169: str = ""
    cover_path_916: str = ""
    title_formula: int = 1
    status: str = "draft"
    cover_fallback: bool = False
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class PublishJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="post.id", index=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    scheduled_at: datetime
    channel: str = "auto"
    status: str = "queued"
    ai_disclosure: bool = False
    result_log: str = ""
    platform_video_id: str = ""
    retry_count: int = 0
    final_video_path: str = ""
    publish_options: dict = Field(default_factory=dict, sa_column=Column(JSON))
    platform_url: str = ""
    status_checked_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class MetricSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    publish_job_id: int = Field(foreign_key="publishjob.id", index=True)
    date: date
    views: int = 0
    likes: int = 0
    comments: int = 0
    followers: int = 0
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    ctr: Optional[float] = None
    watch_time_seconds: Optional[int] = None
    estimated_revenue: Optional[float] = None
    rpm: Optional[float] = None
    subscribers_gained: Optional[int] = None


class ImageQuota(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    month: str = Field(index=True)
    kind: str = Field(index=True)
    count: int = 0


class ContentExample(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    genres: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    language: str = "English"
    platform: str = "all"
    enabled: bool = True


class TagLibraryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tag: str
    genres: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    language: str = "English"
    platform: str = "all"
    enabled: bool = True


class EmotionWord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(index=True, unique=True)
    enabled: bool = True


class HookSuggestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    episode: str
    start: float
    end: float
    score: float = 0
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "pending"


class VisualReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    clip_id: int = Field(foreign_key="clip.id", index=True)
    risk: str = "yellow"
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "review"
    provider: str = "local"
    image_path: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class HotNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str
    platform: str = "tiktok"
    expires_at: date
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MetaDeliveryPackage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    drama_id: int = Field(foreign_key="drama.id", index=True)
    series_slug: str = Field(index=True)
    output_dir: str
    status: str = "ready"
    validation_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    drive_folder_id: str = ""
    drive_folder_url: str = ""
    last_error: str = ""
    uploaded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="appuser.id", index=True)


class SocialComment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: str = Field(index=True, unique=True)
    platform: str = Field(default="youtube", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True)
    video_id: str = Field(default="", index=True)
    video_title: str = ""
    video_url: str = ""
    author_name: str = ""
    author_handle: str = ""
    text_original: str
    text_zh: str = ""
    like_count: int = 0
    published_at: Optional[datetime] = Field(default=None, index=True)
    sentiment: str = Field(default="unanalyzed", index=True)
    user_status: str = Field(default="neutral_browser", index=True)
    keyword_category: str = "other"
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    summary: str = ""
    ticket_type: str = "none"
    severity: str = Field(default="none", index=True)
    needs_human: bool = False
    status: str = Field(default="pending", index=True)
    suggested_replies: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    analysis_source: str = "pending"
    reply_id: str = ""
    reply_text: str = ""
    replied_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow, index=True)
