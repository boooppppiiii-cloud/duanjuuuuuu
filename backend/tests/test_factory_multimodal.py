from pathlib import Path
from types import SimpleNamespace

from app.services import script_analysis
from app.services.factory_multimodal import FrameSample, choose_frame_times


class FakeWhisper:
    def transcribe(self, _source: str, vad_filter: bool = True):
        assert vad_filter
        return iter([
            SimpleNamespace(start=0.0, end=4.0, text="她发现了真正身份"),
            SimpleNamespace(start=4.0, end=8.0, text="冲突突然爆发"),
        ]), {}


def test_frame_sampling_combines_coverage_and_loudness_peaks():
    values = choose_frame_times(0, 120, [(13, 8.0), (61, 4.0)], maximum=8)
    assert any(abs(value - 13) <= 1.5 for value in values)
    assert len(values) <= 8
    assert values == sorted(values)


def test_script_and_frames_are_merged_into_reviewable_candidates(monkeypatch, tmp_path: Path):
    episode = tmp_path / "01.mp4"
    episode.write_bytes(b"video")
    frame = tmp_path / "analysis_frames" / "E001_0000013000.jpg"
    frame.parent.mkdir()
    frame.write_bytes(b"jpeg")
    monkeypatch.setattr(script_analysis, "episode_files", lambda _folder: [episode])
    monkeypatch.setattr(script_analysis, "media_duration", lambda *_: 8.0)
    monkeypatch.setattr(script_analysis, "loudness_peaks", lambda *_: [(5.0, 6.0)])
    monkeypatch.setattr(script_analysis, "extract_frames", lambda *_: [FrameSample(index=1, second=5.0, path=frame)])

    def fake_ai(*_):
        return {
            "summary": "身份揭晓后发生肢体冲突",
            "high_energy": [{"start": 1, "end": 4, "score": 92, "reasons": ["身份反转"], "frame_indices": [1]}],
            "sensitive": [{"start": 5, "end": 7, "category": "暴力", "confidence": .88, "reasons": ["画面出现严重殴打"], "frame_indices": [1]}],
        }

    settings = SimpleNamespace(
        ffprobe_binary="ffprobe", ffmpeg_binary="ffmpeg",
        factory_analysis_window_seconds=600, factory_analysis_frames_per_window=12,
    )
    result = script_analysis.analyze_drama(tmp_path, 1, "测试剧", settings, [], model=FakeWhisper(), ai_analyzer=fake_ai)

    assert result["source"].endswith("+test")
    assert result["sampled_frame_count"] == 1
    assert result["api_call_count"] == 1
    assert result["episodes"][0]["high_energy"][0]["review_status"] == "pending"
    risk = result["episodes"][0]["sensitive"][0]
    assert risk["review_status"] == "approved"
    assert risk["frame_files"] == [frame.name]

    updated = script_analysis.update_review(tmp_path, "01.mp4", "sensitive", 5, 7, "rejected")
    assert updated["episodes"][0]["sensitive"][0]["review_status"] == "rejected"
