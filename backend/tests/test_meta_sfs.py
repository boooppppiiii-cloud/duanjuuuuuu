from pathlib import Path

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
    stills = tmp_path / "stills"
    episodes.mkdir()
    stills.mkdir()
    (episodes / "episode 1.mp4").write_bytes(b"video")
    Image.new("RGB", (1000, 1500), "#20422f").save(stills / "cover.jpg")
    return Drama(id=7, title="午夜契约", file_dir=str(tmp_path), source_note="test")


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
