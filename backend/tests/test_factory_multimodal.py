from pathlib import Path
from types import SimpleNamespace

from app.services import factory_multimodal, script_analysis
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


def test_default_sampling_is_dense_enough_for_short_actions():
    values = choose_frame_times(0, 120, [], maximum=36)

    assert len(values) == 30
    assert max(right - left for left, right in zip(values, values[1:])) <= 4.1


def test_prompt_requires_contextual_soft_sexual_review():
    prompt = factory_multimodal._prompt("01.mp4", 0, 120, [], [])

    assert "尾巴、触手或其他物体伸入裙底" in prompt
    assert "body_focus" in prompt
    assert "相邻 F 帧理解动作变化" in prompt
    assert "ASR 台词与人物位置" in prompt


def test_analysis_falls_back_to_qwen_when_gemini_fails(monkeypatch):
    settings = SimpleNamespace(gemini_api_key="gemini", qwen_api_key="qwen")
    monkeypatch.setattr(factory_multimodal, "_gemini", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(factory_multimodal, "_qwen", lambda *_: ({"summary": "ok"}, "qwen3-vl-plus"))

    data, provider, model = factory_multimodal.analyze_window(settings, "episode", 0, 10, [], [])

    assert data == {"summary": "ok"}
    assert provider == "qwen"
    assert model == "qwen3-vl-plus"


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
            "high_energy": [{"start": 1, "end": 4, "score": 92, "reasons": "身份反转", "frame_indices": [1]}],
            "sensitive": [{
                "start": 5, "end": 7, "category": "性暗示", "confidence": .7,
                "overall_risk_score": 86,
                "risk_scores": {"body_focus": 55, "action": 92, "dialogue_context": 60, "expression_audio": 72, "scene_context": 88},
                "reasons": "连续画面出现裙底接触与身体撞击", "frame_indices": [1],
            }, {
                "start": 1, "end": 2, "category": "其他", "confidence": .15,
                "overall_risk_score": 15,
                "risk_scores": {"body_focus": 0, "action": 10, "dialogue_context": 15, "expression_audio": 0, "scene_context": 0},
                "reasons": ["仅有侮辱性台词，无违规行为"], "frame_indices": [],
            }, {
                "start": 2, "end": 3, "category": "软色情", "confidence": .15,
                "overall_risk_score": 15,
                "risk_scores": {"body_focus": 20, "action": 10, "dialogue_context": 5, "expression_audio": 0, "scene_context": 10},
                "reasons": ["低置信色情风险也交给人工复核"], "frame_indices": [],
            }],
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
    assert result["episodes"][0]["high_energy"][0]["energy_reasons"] == ["身份反转"]
    risk = result["episodes"][0]["sensitive"][0]
    assert len(result["episodes"][0]["sensitive"]) == 2
    assert risk["review_status"] == "approved"
    assert risk["overall_risk_score"] == 86
    assert risk["risk_scores"]["action"] == 92
    assert risk["sensitive"]["性暗示"] == ["连续画面出现裙底接触与身体撞击"]
    assert risk["frame_files"] == [frame.name]
    assert result["episodes"][0]["sensitive"][1]["overall_risk_score"] == 15

    updated = script_analysis.update_review(tmp_path, "01.mp4", "sensitive", 5, 7, "rejected")
    assert updated["episodes"][0]["sensitive"][0]["review_status"] == "rejected"
