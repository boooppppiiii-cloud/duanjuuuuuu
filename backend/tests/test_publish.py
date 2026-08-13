from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine

from app.models import Account, Clip, Drama, Post, PublishJob
from app.routers.publish import create_job, update_job
from app.schemas import PublishJobCreateRequest, PublishJobUpdateRequest
from app.services.publish.base import PublishResult
from app.services.publisher import execute_publish_job, prepare_publish_cover


def test_library_cover_is_converted_to_youtube_safe_thumbnail(tmp_path: Path):
    source = tmp_path / "vertical.png"
    target = tmp_path / "ready.jpg"
    Image.new("RGB", (1440, 1920), "#20422f").save(source)
    prepared = prepare_publish_cover(source, target)
    assert prepared == target
    assert target.stat().st_size <= 2 * 1024 * 1024
    with Image.open(target) as image:
        assert image.size == (1280, 720)


def seed(session: Session, root: Path, ai: bool = True):
    video = root / "clean.mp4"; video.write_bytes(b"video")
    cover = root / "horizontal.jpg"; Image.new("RGB", (1920, 1080), "#20422f").save(cover)
    drama = Drama(title="AI 发布剧", file_dir=str(root), source_note="测试", is_ai_generated=ai, cover_horizontal_path=str(cover))
    session.add(drama); session.commit(); session.refresh(drama)
    clip = Clip(drama_id=drama.id, template_name="suspense_hook", file_path=str(video), current_step="completed")
    session.add(clip); session.commit(); session.refresh(clip)
    post = Post(clip_id=clip.id, title="标题", caption="正文", hashtags=["#Drama"])
    account = Account(platform="tiktok", name="达人号", account_type="creator", status="connected")
    session.add(post); session.add(account); session.commit(); session.refresh(post); session.refresh(account)
    return drama, clip, post, account


def test_ai_disclosure_cannot_be_created_or_updated_false(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ai.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path)
        with pytest.raises(HTTPException):
            create_job(PublishJobCreateRequest(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), ai_disclosure=False, publish_options={"cover_kind": "horizontal"}), session)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), ai_disclosure=True, publish_options={"cover_kind": "horizontal"})
        session.add(job); session.commit(); session.refresh(job)
        with pytest.raises(HTTPException):
            update_job(job.id, PublishJobUpdateRequest(ai_disclosure=False), session)


def test_disconnected_account_is_blocked_without_fake_success(monkeypatch, tmp_path: Path):
    import app.services.publisher as module
    engine = create_engine(f"sqlite:///{tmp_path / 'blocked.db'}")
    SQLModel.metadata.create_all(engine)
    settings = SimpleNamespace(ffmpeg_binary="ffmpeg", media_root=tmp_path / "media", serverchan_key="")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path)
        account.status = "not_connected"; session.add(account)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), ai_disclosure=True, publish_options={"cover_kind": "horizontal"})
        session.add(job); session.commit(); session.refresh(job)
        result = execute_publish_job(session, job)
        assert result.status == "blocked"
        assert result.platform_video_id == ""
        assert not (tmp_path / "media" / "packages").exists()


def test_platform_response_is_required_for_success(monkeypatch, tmp_path: Path):
    import app.services.publisher as module

    class VerifiedChannel:
        def publish(self, payload):
            assert payload.video.exists()
            return PublishResult(success=True, video_id="real-platform-id", status="published", platform_url="https://platform.example/real-platform-id")

    engine = create_engine(f"sqlite:///{tmp_path / 'real.db'}")
    SQLModel.metadata.create_all(engine)
    settings = SimpleNamespace(ffmpeg_binary="ffmpeg", media_root=tmp_path / "media", serverchan_key="")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "finalize_video", lambda *args: Path(args[1]))
    monkeypatch.setitem(module.CHANNEL_REGISTRY, "facebook", VerifiedChannel)
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path)
        account.platform = "facebook"; session.add(account)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), ai_disclosure=True, publish_options={"cover_kind": "horizontal"})
        session.add(job); session.commit(); session.refresh(job)
        result = execute_publish_job(session, job)
        assert result.status == "published"
        assert result.platform_video_id == "real-platform-id"
        assert result.platform_url.endswith("real-platform-id")


def test_unresolved_app_link_is_never_sent(monkeypatch, tmp_path: Path):
    import app.services.publisher as module

    class MustNotRun:
        def publish(self, payload):
            raise AssertionError("包含占位链接时不应调用平台接口")

    engine = create_engine(f"sqlite:///{tmp_path / 'link.db'}")
    SQLModel.metadata.create_all(engine)
    settings = SimpleNamespace(ffmpeg_binary="ffmpeg", media_root=tmp_path / "media", serverchan_key="")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setitem(module.CHANNEL_REGISTRY, "youtube", MustNotRun)
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path, ai=False)
        account.platform = "youtube"; account.account_type = "official"
        post.caption = "Watch now: {app_link}"
        session.add(account); session.add(post)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), publish_options={"cover_kind": "horizontal"})
        session.add(job); session.commit(); session.refresh(job)
        result = execute_publish_job(session, job)
        assert result.status == "failed"
        assert "官方观看链接" in result.result_log


def test_first_comment_is_posted_after_real_platform_publish(monkeypatch, tmp_path: Path):
    import app.services.publisher as module

    class VerifiedChannel:
        def publish(self, payload):
            return PublishResult(success=True, video_id="published-video", status="published", platform_url="https://platform.example/published-video")

    engine = create_engine(f"sqlite:///{tmp_path / 'first-comment.db'}")
    SQLModel.metadata.create_all(engine)
    settings = SimpleNamespace(ffmpeg_binary="ffmpeg", media_root=tmp_path / "media", serverchan_key="")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "finalize_video", lambda *args: Path(args[1]))
    monkeypatch.setitem(module.CHANNEL_REGISTRY, "facebook", VerifiedChannel)
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(module, "publish_first_comment", lambda account, video_id, text: calls.append((account.platform, video_id, text)) or "comment-1")
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path, ai=False)
        account.platform = "facebook"; session.add(account)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), publish_options={"cover_kind": "horizontal", "first_comments": {str(post.id): "Watch here: https://example.com"}})
        session.add(job); session.commit(); session.refresh(job)
        result = execute_publish_job(session, job)
        assert calls == [("facebook", "published-video", "Watch here: https://example.com")]
        assert result.publish_options["first_comment_status"] == "published"
        assert result.publish_options["first_comment_id"] == "comment-1"
        assert "首条评论已真实发布" in result.result_log


def test_tiktok_first_comment_is_blocked_before_video_upload(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tiktok-comment.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, post, account = seed(session, tmp_path, ai=False)
        job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), publish_options={"cover_kind": "horizontal", "first_comments": {str(post.id): "A real first comment"}})
        session.add(job); session.commit(); session.refresh(job)
        result = execute_publish_job(session, job)
        assert result.status == "blocked"
        assert result.platform_video_id == ""
        assert "TikTok" in result.result_log and "不支持创建评论" in result.result_log


def test_youtube_first_comment_uses_top_level_comment_api(monkeypatch):
    from app.services import social_integrations as module

    captured: dict = {}
    class Response:
        is_error = False
        def json(self): return {"id": "youtube-comment-id"}
    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()
    monkeypatch.setattr(module, "youtube_access_token", lambda account: "token")
    monkeypatch.setattr(module.httpx, "post", fake_post)
    comment_id = module.publish_first_comment(Account(platform="youtube", name="Channel"), "video-1", "Pinned link")
    assert comment_id == "youtube-comment-id"
    assert captured["url"].endswith("/commentThreads")
    assert captured["json"]["snippet"]["videoId"] == "video-1"
    assert captured["json"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Pinned link"
