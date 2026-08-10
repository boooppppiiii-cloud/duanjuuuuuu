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


def test_read_analysis_keeps_only_top_ten_high_energy_candidates(tmp_path: Path):
    script_analysis.write_analysis(tmp_path, {
        "status": "completed",
        "high_energy_count": 12,
        "episodes": [{
            "episode": "Episode1.mp4", "segments": [], "sensitive": [],
            "high_energy": [{"start": score, "end": score + 1, "energy_score": score} for score in range(1, 13)],
        }],
    })

    result = script_analysis.read_analysis(tmp_path)

    assert result is not None
    scores = [row["energy_score"] for row in result["episodes"][0]["high_energy"]]
    assert len(scores) == 10
    assert min(scores) == 3
    assert result["high_energy_count"] == 10


def test_evidence_frames_are_repaired_to_candidate_start_and_end(tmp_path: Path):
    frame_dir = tmp_path / "analysis_frames"; frame_dir.mkdir()
    for milliseconds in (1000, 5000, 9000):
        (frame_dir / f"E001_{milliseconds:010d}.jpg").write_bytes(b"jpeg")
    script_analysis.write_analysis(tmp_path, {
        "status": "completed", "high_energy_count": 1,
        "episodes": [{
            "episode": "Episode1.mp4", "segments": [], "sensitive": [],
            "high_energy": [{"start": 1.2, "end": 8.8, "energy_score": 90, "frame_files": ["E001_0000005000.jpg"]}],
        }],
    })

    result = script_analysis.read_analysis(tmp_path)

    assert result is not None
    assert result["episodes"][0]["high_energy"][0]["frame_files"] == ["E001_0000001000.jpg", "E001_0000009000.jpg"]


def test_manual_sensitive_range_is_persistent_and_always_removed(tmp_path: Path):
    script_analysis.write_analysis(tmp_path, {
        "status": "completed", "sensitive_count": 0,
        "episodes": [{
            "episode": "Episode5.mp4", "duration": 180, "segments": [], "high_energy": [], "sensitive": [],
        }],
    })

    result = script_analysis.add_manual_sensitive(
        tmp_path, "Episode5.mp4", 60, 115, "色情", "人工确认色情内容，必须剪除",
    )

    risk = result["episodes"][0]["sensitive"][0]
    assert risk["start"] == 60
    assert risk["end"] == 115
    assert risk["review_status"] == "approved"
    assert risk["overall_risk_score"] == 100
    assert risk["source"] == "manual"
    assert script_analysis.manual_sensitive_file(tmp_path).is_file()


def test_analysis_windows_overlap_scene_boundaries():
    windows = script_analysis._analysis_windows(180, 60, 15)

    assert windows == [(0.0, 60.0), (45.0, 105.0), (90.0, 150.0), (135.0, 180.0)]
    assert any(start <= 85 and end >= 105 for start, end in windows)
    assert any(start <= 105 and end >= 129 for start, end in windows)


def test_sexual_candidates_are_conservatively_expanded_and_merged():
    rows = [{
        "start": 64, "end": 78, "sensitive": {"性暗示": ["可疑身体接触"]},
        "confidence": .35, "overall_risk_score": 35,
        "risk_scores": {"action": 35}, "review_status": "pending",
        "evidence": ["可疑身体接触"], "frame_files": ["first.jpg"],
    }, {
        "start": 88, "end": 108, "sensitive": {"软色情": ["连续撞击动作"]},
        "confidence": .82, "overall_risk_score": 82,
        "risk_scores": {"action": 90}, "review_status": "approved",
        "evidence": ["连续撞击动作"], "frame_files": ["last.jpg"],
    }]

    merged = script_analysis._merge_sensitive_candidates(rows, 180, [])

    assert len(merged) == 1
    assert merged[0]["start"] == 59
    assert merged[0]["end"] == 123
    assert merged[0]["review_status"] == "approved"
    assert merged[0]["overall_risk_score"] == 82
    assert set(merged[0]["sensitive"]) == {"性暗示", "软色情"}
    assert merged[0]["frame_files"] == ["first.jpg", "last.jpg"]
