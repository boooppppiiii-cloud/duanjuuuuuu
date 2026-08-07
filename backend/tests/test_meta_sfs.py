import csv
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.models import Drama
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
        "include_thumbnails": True,
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

    output, _ = meta_sfs.build_package(drama, request(include_thumbnails=False), output_parent=selected)

    assert output.parent == selected
    assert next(output.rglob("*_series.csv")).is_file()
