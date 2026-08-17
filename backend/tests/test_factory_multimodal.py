from pathlib import Path
from types import SimpleNamespace

import json
import pytest

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

    assert len(values) == 36
    assert max(right - left for left, right in zip(values, values[1:])) <= 3.5


def test_prompt_requires_contextual_soft_sexual_review():
    prompt = factory_multimodal._prompt("01.mp4", 0, 120, [], [])

    assert "尾巴、触手或其他物体伸入裙底" in prompt
    assert "body_focus" in prompt
    assert "相邻 F 帧理解动作变化" in prompt
    assert "ASR 台词与人物位置" in prompt
    assert "不得只截取最露骨的几秒" in prompt
    assert "动画、特效、奇幻生物和非真人画面使用同一标准" in prompt
    assert "泳装/比基尼" in prompt
    assert "男性裸露上半身" in prompt
    assert "低俗擦边" in prompt
    assert "完整 15-30 秒范围" in prompt
    assert "religious_context" in prompt
    assert "宗教禁忌必须跨信仰考虑" in prompt
    assert "不得将某种服饰、食物、祈祷" in prompt


def test_religious_taboo_candidate_keeps_faith_and_evidence_metadata():
    _, sensitive = script_analysis._model_candidates({
        "sensitive": [{
            "start": 4,
            "end": 12,
            "category": "宗教禁忌",
            "confidence": .82,
            "overall_risk_score": 78,
            "risk_scores": {"religious_context": 78, "dialogue_context": 65, "scene_context": 70},
            "religions": ["伊斯兰教"],
            "taboo_types": ["强迫违反饮食/仪式"],
            "reasons": ["人物在明确拒绝后被强迫饮酒，台词以宗教信仰为羞辱目标"],
            "frame_indices": [],
        }],
    }, [], [], 0, 20, "gemini")

    assert len(sensitive) == 1
    risk = sensitive[0]
    assert risk["sensitive"]["宗教禁忌"]
    assert risk["risk_scores"]["religious_context"] == 78
    assert risk["religions"] == ["伊斯兰教"]
    assert risk["taboo_types"] == ["强迫违反饮食/仪式"]
    assert risk["review_status"] == "approved"


def test_ambiguous_religious_context_is_kept_for_manual_review():
    _, sensitive = script_analysis._model_candidates({
        "sensitive": [{
            "start": 4,
            "end": 12,
            "category": "宗教禁忌",
            "confidence": .9,
            "overall_risk_score": 45,
            "risk_scores": {"religious_context": 45},
            "religions": ["基督宗教"],
            "taboo_types": ["场所/葬仪冒犯"],
            "reasons": ["场所和动作存在冒犯嫌疑，但证据不足"],
        }],
    }, [], [], 0, 20, "gemini")

    assert len(sensitive) == 1
    assert sensitive[0]["review_status"] == "pending"


def test_normal_religious_expression_below_threshold_is_not_reported():
    _, sensitive = script_analysis._model_candidates({
        "sensitive": [{
            "start": 4,
            "end": 12,
            "category": "宗教禁忌",
            "confidence": .9,
            "overall_risk_score": 20,
            "risk_scores": {"religious_context": 20},
            "religions": ["佛教"],
            "reasons": ["人物正常进入寺庙参拜，无侮辱或破坏行为"],
        }],
    }, [], [], 0, 20, "gemini")

    assert sensitive == []


def test_revealing_clothing_is_treated_as_high_recall_sexual_risk():
    row = {
        "sensitive": {"其他": ["镜头长时间聚焦比基尼与胸部"]},
        "risk_scores": {"body_focus": 70, "action": 20, "expression_audio": 10, "scene_context": 30},
    }

    assert script_analysis._is_sexual_candidate(row) is True


def test_body_focus_plus_context_is_not_dropped_when_provider_uses_other_category():
    row = {
        "sensitive": {"其他": ["人物服装与动作存在风险，交由人工复核"]},
        "risk_scores": {"body_focus": 45, "action": 30, "expression_audio": 20, "scene_context": 35},
    }

    assert script_analysis._is_sexual_candidate(row) is True


def test_analysis_falls_back_to_qwen_when_gemini_fails(monkeypatch):
    settings = SimpleNamespace(gemini_api_key="gemini", qwen_api_key="qwen")
    monkeypatch.setattr(factory_multimodal, "_gemini", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(factory_multimodal, "_qwen", lambda *_: ({"summary": "ok"}, "qwen3-vl-plus"))

    data, provider, model = factory_multimodal.analyze_window(settings, "episode", 0, 10, [], [])

    assert data == {"summary": "ok"}
    assert provider == "qwen"
    assert model == "qwen3-vl-plus"


def test_model_json_decoder_tolerates_fences_and_trailing_prose():
    payload = factory_multimodal._decode_json_object(
        '```json\n{"summary":"ok","sensitive":[],"high_energy":[]}\n```\ncompleted'
    )

    assert payload["summary"] == "ok"


def test_analysis_retry_reduces_frame_payload(monkeypatch, tmp_path: Path):
    settings = SimpleNamespace(
        gemini_api_key="gemini", qwen_api_key="", factory_analysis_api_retries=2,
    )
    frames = [FrameSample(index=index, second=float(index), path=tmp_path / f"{index}.jpg") for index in range(30)]
    frame_counts: list[int] = []

    def fake_gemini(_settings, _prompt, attempt_frames):
        frame_counts.append(len(attempt_frames))
        if len(frame_counts) == 1:
            raise json.JSONDecodeError("truncated", "{", 1)
        return {"summary": "ok", "sensitive": [], "high_energy": []}, "gemini-test"

    monkeypatch.setattr(factory_multimodal, "_gemini", fake_gemini)
    monkeypatch.setattr(factory_multimodal.time, "sleep", lambda *_: None)

    data, provider, _ = factory_multimodal.analyze_window(settings, "episode", 0, 60, [], frames)

    assert data["summary"] == "ok"
    assert provider == "gemini"
    assert frame_counts == [30, 15]


def test_transient_provider_failure_marks_full_window_for_manual_review(monkeypatch, tmp_path: Path):
    settings = SimpleNamespace(
        gemini_api_key="gemini", qwen_api_key="qwen", factory_analysis_api_retries=2,
    )
    frames = [FrameSample(index=index, second=float(index), path=tmp_path / f"{index}.jpg") for index in range(20)]
    monkeypatch.setattr(factory_multimodal, "_gemini", lambda *_: (_ for _ in ()).throw(TimeoutError("timeout")))
    monkeypatch.setattr(factory_multimodal, "_qwen", lambda *_: (_ for _ in ()).throw(TimeoutError("timeout")))
    monkeypatch.setattr(factory_multimodal.time, "sleep", lambda *_: None)

    data, provider, model = factory_multimodal.analyze_window(settings, "episode", 15, 75, [], frames)

    assert provider == "manual_review_fallback"
    assert model == "transient_model_failure"
    assert data["sensitive"][0]["start"] == 15
    assert data["sensitive"][0]["end"] == 75
    assert data["sensitive"][0]["overall_risk_score"] == 59
    assert "人工复核" in data["sensitive"][0]["reasons"][0]


def test_provider_authentication_failure_is_not_silently_downgraded(monkeypatch):
    settings = SimpleNamespace(
        gemini_api_key="invalid", qwen_api_key="qwen", factory_analysis_api_retries=2,
    )

    class AuthenticationError(RuntimeError):
        status_code = 401

    monkeypatch.setattr(factory_multimodal, "_gemini", lambda *_: (_ for _ in ()).throw(AuthenticationError("invalid api key")))

    with pytest.raises(RuntimeError, match="Gemini"):
        factory_multimodal.analyze_window(settings, "episode", 0, 60, [], [])


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
    assert len(result["episodes"][0]["sensitive"]) == 1
    assert risk["review_status"] == "approved"
    assert risk["overall_risk_score"] == 86
    assert risk["risk_scores"]["action"] == 92
    assert risk["sensitive"]["性暗示"] == ["连续画面出现裙底接触与身体撞击"]
    assert risk["sensitive"]["软色情"] == ["低置信色情风险也交给人工复核"]
    assert risk["frame_files"] == [frame.name]

    updated = script_analysis.update_review(
        tmp_path, "01.mp4", "sensitive", risk["start"], risk["end"], "rejected",
    )
    assert updated["episodes"][0]["sensitive"][0]["review_status"] == "rejected"
