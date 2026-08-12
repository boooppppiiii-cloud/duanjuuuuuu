import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine

from app.models import AppUser, Drama, FactoryJob, GeneratedAsset
from app.routers import meta_sfs as meta_sfs_router
from app.schemas import MetaSFSRequest
from app.services import meta_sfs


def request(**overrides) -> MetaSFSRequest:
    values = {
        "drama_id": 7,
        "series_slug": "midnight-contract",
        "description": "A short drama for the Meta SFS catalog.",
        "locale": "en_US",
        "genres": ["Drama", "Romance"],
        "release_date": "06/26/2026",
        "cast_list": [],
        "tags": ["shortdrama"],
        "geogating": [],
        "ai_content": False,
        "dubbed_content": False,
        "include_episode_csv": True,
        "include_thumbnails": False,
    }
    values.update(overrides)
    return MetaSFSRequest(**values)


def make_drama(tmp_path: Path) -> Drama:
    episodes = tmp_path / "episodes"
    covers = tmp_path / "covers"
    episodes.mkdir()
    covers.mkdir()
    (episodes / "episode 1.mp4").write_bytes(b"video")
    vertical = covers / "vertical.jpg"; square = covers / "square.jpg"
    Image.new("RGB", (1440, 1920), "#20422f").save(vertical)
    Image.new("RGB", (1200, 1200), "#20422f").save(square)
    return Drama(id=7, title="午夜契约", file_dir=str(tmp_path), source_note="test", cover_vertical_path=str(vertical), cover_square_path=str(square))


def compliant_video(**overrides) -> dict:
    result = {
        "duration": 90.0,
        "size": 200_000_000,
        "format": "mov,mp4",
        "width": 1080,
        "height": 1920,
        "video_codec": "h264",
        "video_bitrate": 3_000_000,
        "audio_codec": "aac",
        "audio_channels": 2,
        "has_audio": True,
    }
    result.update(overrides)
    return result


def test_slug_is_predictable_and_has_chinese_fallback():
    assert meta_sfs.suggest_slug("My Drama 2026", 1) == "my-drama-2026"
    assert meta_sfs.suggest_slug("午夜契约", 7) == "short-drama-7"


def test_legacy_asset_ticket_is_bound_to_user_asset_and_expiry(monkeypatch):
    monkeypatch.setattr(meta_sfs_router, "get_settings", lambda: SimpleNamespace(credential_secret="fixed-test-secret"))
    user = AppUser(id=9, email="owner@example.com", password_hash="test")
    asset = GeneratedAsset(
        id=17, factory_job_id=3, drama_id=7, kind="meta_episode", sequence=1,
        file_path="episode.mp4", filename="episode.mp4", owner_user_id=9,
    )
    expires_at = int(meta_sfs_router.time.time()) + 600
    ticket = meta_sfs_router._legacy_ticket(asset, user, expires_at)

    meta_sfs_router._validate_legacy_ticket(asset, ticket)

    other_asset = asset.model_copy(update={"owner_user_id": 10})
    with pytest.raises(Exception, match="过期"):
        meta_sfs_router._validate_legacy_ticket(other_asset, ticket)
    expired = meta_sfs_router._legacy_ticket(asset, user, int(meta_sfs_router.time.time()) - 1)
    with pytest.raises(Exception, match="过期"):
        meta_sfs_router._validate_legacy_ticket(asset, expired)


def test_legacy_server_source_only_lists_owned_existing_meta_assets(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs_router, "get_settings", lambda: SimpleNamespace(credential_secret="fixed-test-secret"))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    drama_root = tmp_path / "drama"
    output = drama_root / "generated" / "meta" / "J0042"
    output.mkdir(parents=True)
    episode = output / "J0042_E001.mp4"
    episode.write_bytes(b"legacy-meta-video")

    with Session(engine) as session:
        user = AppUser(email="owner@example.com", password_hash="test")
        drama = Drama(id=7, title="Legacy Drama", file_dir=str(drama_root))
        session.add(user); session.add(drama); session.commit(); session.refresh(user)
        job = FactoryJob(drama_id=7, status="completed", meta_count=1, owner_user_id=user.id)
        session.add(job); session.commit(); session.refresh(job)
        asset = GeneratedAsset(
            factory_job_id=job.id, drama_id=7, kind="meta_episode", sequence=1,
            file_path=str(episode), filename=episode.name, size_bytes=episode.stat().st_size,
            owner_user_id=user.id,
        )
        session.add(asset); session.commit(); session.refresh(asset)

        source = meta_sfs_router.legacy_server_source(7, session, user)
        assert source["ready"] is True
        assert source["factory_job_id"] == job.id
        assert source["total_bytes"] == episode.stat().st_size
        assert source["files"][0]["url"].startswith(f"/api/meta-sfs/legacy-assets/{asset.id}?ticket=")

        ticket = source["files"][0]["url"].split("ticket=", 1)[1]
        response = meta_sfs_router.download_legacy_asset(asset.id, ticket, session)
        assert Path(response.path) == episode


def test_preflight_builds_official_three_digit_filename(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    result = meta_sfs.preflight(make_drama(tmp_path), request())

    assert result["ready"] is True
    assert result["assets"][0]["target"] == "midnight-contract_ep001_001.mp4"
    assert result["blockers"] == []


def test_preflight_blocks_noncompliant_duration(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video(duration=42.0))
    result = meta_sfs.preflight(make_drama(tmp_path), request())

    assert result["ready"] is False
    assert any("60 秒到 3 分钟" in item for item in result["blockers"])


def test_quick_preflight_registers_files_without_synchronous_media_probe(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: (_ for _ in ()).throw(AssertionError("must run in background")))

    result = meta_sfs.preflight(make_drama(tmp_path), request(), inspect_media=False)

    assert result["ready"] is True
    assert result["assets"][0]["target"] == "midnight-contract_ep001_001.mp4"
    assert any("后台校验" in item for item in result["automatic_fixes"])


def test_normalize_video_copies_already_compliant_streams(monkeypatch, tmp_path: Path):
    commands = []
    monkeypatch.setattr(meta_sfs, "_binary", lambda _: "ffmpeg")
    monkeypatch.setattr(meta_sfs.subprocess, "run", lambda command, **_: commands.append(command) or SimpleNamespace(returncode=0, stderr=""))

    meta_sfs._normalize_video(tmp_path / "source.mp4", tmp_path / "target.mp4", compliant_video())

    command = commands[0]
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "copy"


def test_normalize_video_only_reencodes_noncompliant_audio(monkeypatch, tmp_path: Path):
    commands = []
    monkeypatch.setattr(meta_sfs, "_binary", lambda _: "ffmpeg")
    monkeypatch.setattr(meta_sfs.subprocess, "run", lambda command, **_: commands.append(command) or SimpleNamespace(returncode=0, stderr=""))

    meta_sfs._normalize_video(
        tmp_path / "source.mp4",
        tmp_path / "target.mp4",
        compliant_video(audio_codec="mp3"),
    )

    command = commands[0]
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-c:a") + 1] == "aac"


def test_verify_output_rejects_low_resolution_and_bitrate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        meta_sfs,
        "inspect_video",
        lambda _: compliant_video(width=720, height=1280, video_bitrate=1_800_000),
    )

    errors = meta_sfs._verify_output(tmp_path / "target.mp4")
    assert "视频分辨率不是 1080x1920" in errors
    assert "视频码率低于 2.5Mbps" in errors


def test_normalize_video_uses_fast_server_preset_for_noncompliant_video(monkeypatch, tmp_path: Path):
    commands = []
    monkeypatch.setattr(meta_sfs, "_binary", lambda _: "ffmpeg")
    monkeypatch.setattr(meta_sfs.subprocess, "run", lambda command, **_: commands.append(command) or SimpleNamespace(returncode=0, stderr=""))

    meta_sfs._normalize_video(
        tmp_path / "source.mp4",
        tmp_path / "target.mp4",
        compliant_video(width=640, height=1136),
    )

    command = commands[0]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-preset") + 1] == "veryfast"


def test_preflight_prefers_factory_meta_split_outputs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video(duration=120.0))
    drama = make_drama(tmp_path)
    output = tmp_path / "generated" / "meta" / "J0008"
    output.mkdir(parents=True)
    files = [output / "J0008_E001_P01.mp4", output / "J0008_E001_P02.mp4"]
    for path in files:
        path.write_bytes(b"video")
    (tmp_path / "generated" / "meta_current.json").write_text(json.dumps({"factory_job_id": 8, "files": [str(path) for path in files]}), encoding="utf-8")

    result = meta_sfs.preflight(drama, request())

    assert result["ready"] is True
    assert result["source_mode"] == "factory_meta_split"
    assert result["episode_count"] == 2
    assert result["assets"][1]["target"] == "midnight-contract_ep002_002.mp4"


def test_preflight_requires_factory_outputs_when_delivery_route_has_none(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())

    result = meta_sfs.preflight(make_drama(tmp_path), request(), ([], "factory_meta_split"))

    assert result["ready"] is False
    assert result["episode_count"] == 0
    assert any("内容工厂" in item and "Meta 逐集切分" in item for item in result["blockers"])


def test_preflight_rejects_invalid_genre_and_date(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    result = meta_sfs.preflight(make_drama(tmp_path), request(genres=["Urban Fantasy"], release_date="2026-06-26"))

    assert result["ready"] is False
    assert any("Genre" in item for item in result["blockers"])
    assert any("MM/DD/YYYY" in item for item in result["blockers"])


def test_preflight_uses_task_total_for_names_and_blocks_missing_episodes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    drama = make_drama(tmp_path); drama.total_episode_count = 3
    result = meta_sfs.preflight(drama, request())

    assert result["ready"] is False
    assert result["assets"][0]["target"] == "midnight-contract_ep001_003.mp4"
    assert any("登记为 3 集" in item for item in result["blockers"])


def test_build_package_inherits_task_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    monkeypatch.setattr(meta_sfs, "_verify_output", lambda _: [])
    monkeypatch.setattr(meta_sfs, "_normalize_video", lambda source, target, has_audio: target.write_bytes(b"normalized"))
    monkeypatch.setattr(meta_sfs, "_render_cover", lambda source, target, size: target.write_bytes(b"cover"))
    monkeypatch.setattr(meta_sfs, "get_settings", lambda: SimpleNamespace(media_root=tmp_path / "output"))
    drama = make_drama(tmp_path); drama.description = "Task synopsis"; drama.genres = ["Drama", "Romance"]; drama.is_ai_generated = True; drama.is_dubbed_content = True; drama.total_episode_count = 1
    horizontal = tmp_path / "covers" / "horizontal.jpg"; Image.new("RGB", (1920, 1080), "#20422f").save(horizontal); drama.cover_horizontal_path = str(horizontal)

    output, _ = meta_sfs.build_package(drama, request(description="Ignored synopsis", genres=["Comedy"], ai_content=False, dubbed_content=False, include_thumbnails=False))
    with next(output.rglob("*_series.csv")).open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["Description"] == "Task synopsis"
    assert row["Total Number of Episodes"] == "1"
    assert row["Genre"] == "Drama,Romance"
    assert row["AI Content"] == "yes"
    assert row["Dubbed Content"] == "yes"
    assert next(output.rglob("*_background.jpg")).is_file()


def test_build_package_writes_to_selected_local_directory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    monkeypatch.setattr(meta_sfs, "_verify_output", lambda _: [])
    monkeypatch.setattr(meta_sfs, "_normalize_video", lambda source, target, has_audio: target.write_bytes(b"normalized"))
    monkeypatch.setattr(meta_sfs, "_render_cover", lambda source, target, size: target.write_bytes(b"cover"))
    monkeypatch.setattr(meta_sfs, "get_settings", lambda: SimpleNamespace(media_root=tmp_path / "default-output"))
    drama = make_drama(tmp_path); drama.description = "Task synopsis"; drama.genres = ["Drama"]; drama.total_episode_count = 1
    selected = tmp_path / "selected-output"; selected.mkdir()

    # Even an older caller requesting thumbnails must not recreate this
    # retired optional output.
    output, _ = meta_sfs.build_package(drama, request(include_thumbnails=True), output_parent=selected)

    assert output.parent == selected
    assert next(output.rglob("*_series.csv")).is_file()
    assert [path.name for path in output.iterdir()] == ["midnight-contract"]
    series = output / "midnight-contract"
    assert (series / "midnight-contract_ep001_001.mp4").is_file()
    assert (series / "midnight-contract_cover.jpg").is_file()
    assert (series / "midnight-contract_cover_square.jpg").is_file()
    assert (series / "midnight-contract_series.csv").is_file()
    assert not list(series.glob("*_thumbnail.jpg"))
    assert not (output / "validation-report.json").exists()


def test_build_package_removes_partial_staging_directory_on_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(meta_sfs, "inspect_video", lambda _: compliant_video())
    monkeypatch.setattr(meta_sfs, "_normalize_video", lambda *_: (_ for _ in ()).throw(RuntimeError("conversion stopped")))
    monkeypatch.setattr(meta_sfs, "get_settings", lambda: SimpleNamespace(media_root=tmp_path / "output"))
    drama = make_drama(tmp_path); drama.description = "Task synopsis"; drama.genres = ["Drama"]; drama.total_episode_count = 1

    with pytest.raises(RuntimeError, match="conversion stopped"):
        meta_sfs.build_package(drama, request(include_thumbnails=False))

    package_parent = tmp_path / "output" / "packages" / "meta_sfs"
    assert package_parent.is_dir()
    assert list(package_parent.iterdir()) == []
