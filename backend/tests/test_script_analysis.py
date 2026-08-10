from pathlib import Path
from types import SimpleNamespace

from app.services import script_analysis


class FakeModel:
    def transcribe(self, _source: str, vad_filter: bool = True):
        assert vad_filter is True
        return iter([
            SimpleNamespace(start=0.0, end=3.0, text="他竟然说出了秘密"),
            SimpleNamespace(start=3.0, end=7.0, text="随后发生暴力冲突，有人流血"),
        ]), {}


class CountingModel:
    def __init__(self):
        self.calls: list[str] = []

    def transcribe(self, source: str, **_kwargs):
        self.calls.append(Path(source).name)
        return iter([SimpleNamespace(start=0.0, end=3.0, text="突然揭晓身份")]), {}


def test_script_analysis_is_saved_from_real_signals(monkeypatch, tmp_path: Path):
    episode = tmp_path / "01.mp4"
    episode.write_bytes(b"video")
    monkeypatch.setattr(script_analysis, "episode_files", lambda _folder: [episode])
    monkeypatch.setattr(script_analysis, "media_duration", lambda _ffprobe, _source: 7.0)
    monkeypatch.setattr(script_analysis, "loudness_peaks", lambda _ffmpeg, _source: [(1.0, 4.5)])
    settings = SimpleNamespace(ffprobe_binary="ffprobe", ffmpeg_binary="ffmpeg")

    result = script_analysis.analyze_drama(tmp_path, 1, "测试剧", settings, [], model=FakeModel())

    assert result["status"] == "completed"
    assert result["segment_count"] == 2
    assert result["high_energy_count"] >= 1
    assert result["sensitive_count"] == 1
    assert result["episodes"][0]["sensitive"][0]["sensitive"]["暴力"]
    assert script_analysis.read_analysis(tmp_path)["title"] == "测试剧"


def test_interrupted_analysis_resumes_without_repeating_completed_episode(monkeypatch, tmp_path: Path):
    first = tmp_path / "Episode1.mp4"; second = tmp_path / "Episode2.mp4"
    first.write_bytes(b"first"); second.write_bytes(b"second")
    monkeypatch.setattr(script_analysis, "episode_files", lambda _folder: [first, second])
    monkeypatch.setattr(script_analysis, "media_duration", lambda *_: 3.0)
    monkeypatch.setattr(script_analysis, "loudness_peaks", lambda *_: [])
    existing_episode = {
        "episode": first.name, "duration": 3.0, "segment_count": 1,
        "segments": [{"start": 0, "end": 3, "text": "已完成", "energy_score": 0, "energy_reasons": [], "high_energy": False, "sensitive": {}}],
        "high_energy": [], "sensitive": [], "summary": "已完成第一集",
    }
    script_analysis.write_analysis(tmp_path, {
        "status": "processing", "progress": 50, "episodes": [existing_episode],
        "sampled_frame_count": 0, "api_call_count": 0, "resume_count": 0,
        "analysis_version": script_analysis.ANALYSIS_VERSION,
    })
    model = CountingModel()
    settings = SimpleNamespace(ffprobe_binary="ffprobe", ffmpeg_binary="ffmpeg")

    result = script_analysis.analyze_drama(tmp_path, 1, "测试剧", settings, [], model=model, resume=True)

    assert model.calls == [second.name]
    assert [item["episode"] for item in result["episodes"]] == [first.name, second.name]
    assert result["resume_count"] == 1
    assert result["status"] == "completed"


def test_old_detection_version_is_reanalyzed_from_the_start(monkeypatch, tmp_path: Path):
    first = tmp_path / "Episode1.mp4"; second = tmp_path / "Episode2.mp4"
    first.write_bytes(b"first"); second.write_bytes(b"second")
    monkeypatch.setattr(script_analysis, "episode_files", lambda _folder: [first, second])
    monkeypatch.setattr(script_analysis, "media_duration", lambda *_: 3.0)
    monkeypatch.setattr(script_analysis, "loudness_peaks", lambda *_: [])
    script_analysis.write_analysis(tmp_path, {
        "status": "processing", "progress": 50, "episodes": [{"episode": first.name}],
        "analysis_version": script_analysis.ANALYSIS_VERSION - 1,
    })
    model = CountingModel()
    settings = SimpleNamespace(ffprobe_binary="ffprobe", ffmpeg_binary="ffmpeg")

    result = script_analysis.analyze_drama(tmp_path, 1, "测试剧", settings, [], model=model, resume=True)

    assert model.calls == [first.name, second.name]
    assert result["analysis_version"] == script_analysis.ANALYSIS_VERSION


def test_episode_files_use_natural_number_order(tmp_path: Path):
    from app.services.drama_library import episode_files

    episodes = tmp_path / "episodes"; episodes.mkdir()
    for name in ("Episode1.mp4", "Episode10.mp4", "Episode2.mp4"):
        (episodes / name).write_bytes(b"video")

    assert [item.name for item in episode_files(tmp_path)] == ["Episode1.mp4", "Episode2.mp4", "Episode10.mp4"]


def test_read_analysis_repairs_character_split_reasons(tmp_path: Path):
    script_analysis.write_analysis(tmp_path, {
        "status": "completed",
        "episodes": [{
            "episode": "Episode2.mp4",
            "segments": [],
            "high_energy": [{
                "energy_reasons": list("红衣女子冷酷宣称牺牲百年换取预言"),
                "evidence": list("红衣女子冷酷宣称牺牲百年换取预言"),
                "sensitive": {},
            }],
            "sensitive": [{
                "energy_reasons": [],
                "evidence": list("人物反复身体撞击"),
                "sensitive": {"性暗示": list("人物反复身体撞击")},
            }],
        }],
    })

    result = script_analysis.read_analysis(tmp_path)

    assert result is not None
    high = result["episodes"][0]["high_energy"][0]
    risk = result["episodes"][0]["sensitive"][0]
    assert high["energy_reasons"] == ["红衣女子冷酷宣称牺牲百年换取预言"]
    assert high["evidence"] == ["红衣女子冷酷宣称牺牲百年换取预言"]
    assert risk["evidence"] == ["人物反复身体撞击"]
    assert risk["sensitive"]["性暗示"] == ["人物反复身体撞击"]
    persisted = script_analysis.analysis_file(tmp_path).read_text(encoding="utf-8")
    assert '"红衣女子冷酷宣称牺牲百年换取预言"' in persisted
