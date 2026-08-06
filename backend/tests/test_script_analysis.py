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
