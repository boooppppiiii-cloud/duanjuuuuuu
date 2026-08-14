import json
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Drama, ExternalVideo, VideoMatchEvidence
from app.services import radar_content_analysis, radar_search
from app.services.radar_content_analysis import (
    CONTENT_STRUCTURE_METHOD,
    ContentStructureDecision,
    analyze_youtube_content,
    classification_for_structure,
    normalize_content_structure,
)


def test_prompt_requires_actual_timeline_and_distinguishes_repetition():
    prompt = radar_content_analysis.build_content_structure_prompt("Full Drama", 3600)
    assert "画面、音频、字幕和时间顺序" in prompt
    assert "不要只依据标题或视频时长" in prompt
    assert "repeated_compilation" in prompt
    assert "前段、中段、后段" in prompt


def test_normalization_prevents_repeated_or_discontinuous_video_from_being_full():
    repeated = normalize_content_structure({
        "structure": "true_full_series", "confidence": .94,
        "continuous_story_ratio": .9, "repetition_ratio": .42,
        "reason": "多个剧情块循环出现",
    })
    assert repeated.structure == "repeated_compilation"
    discontinuous = normalize_content_structure({
        "structure": "true_full_series", "confidence": .9,
        "continuous_story_ratio": .48, "repetition_ratio": .08,
        "reason": "缺少中段",
    })
    assert discontinuous.structure == "uncertain"


def test_structure_maps_to_separate_risk_labels():
    full = ContentStructureDecision("true_full_series", .92, .88, .05, "剧情连续", {})
    repeated = ContentStructureDecision("repeated_compilation", .89, .25, .53, "循环拼接", {})
    excerpt = ContentStructureDecision("single_excerpt", .87, .9, .02, "单一节选", {})
    assert classification_for_structure(full)[0] == "suspected_full_reupload"
    assert classification_for_structure(repeated)[0] == "suspected_compilation_reupload"
    assert classification_for_structure(excerpt)[0] == "unknown"


def test_gemini_receives_public_youtube_video_and_returns_structured_result(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text=json.dumps({
                "structure": "fragment_compilation", "confidence": .91,
                "continuous_story_ratio": .31, "repetition_ratio": .12,
                "sequence_evidence": ["00:00-01:00 开场"],
                "repetition_evidence": [], "reason": "片段之间缺少连续因果",
            }))

    monkeypatch.setattr(radar_content_analysis.genai, "Client", lambda **kwargs: SimpleNamespace(models=FakeModels()))
    monkeypatch.setattr(radar_content_analysis, "record_model_usage", lambda *args, **kwargs: None)
    settings = SimpleNamespace(
        gemini_api_key="test-key", radar_content_analysis_model="gemini-2.5-flash",
        radar_content_analysis_timeout_seconds=60, gemini_text_model="gemini-2.5-flash",
    )
    result = analyze_youtube_content(settings, "https://www.youtube.com/watch?v=abc", "Full Drama", 3600)
    assert result.structure == "fragment_compilation"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["contents"].parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=abc"


def test_verification_is_cached_and_stored_once(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'content-cache.db'}")
    SQLModel.metadata.create_all(engine)
    calls = []
    monkeypatch.setattr(radar_search, "analyze_youtube_content", lambda *args: (
        calls.append(args[1]) or ContentStructureDecision(
            "repeated_compilation", .9, .32, .48, "同一剧情块在后半段再次出现",
            {"structure": "repeated_compilation", "confidence": .9, "continuous_story_ratio": .32,
             "repetition_ratio": .48, "reason": "同一剧情块在后半段再次出现",
             "sequence_evidence": [], "repetition_evidence": ["05:00 与 35:00 重复"]},
        )
    ))
    settings = SimpleNamespace(
        gemini_api_key="test-key", radar_content_analysis_daily_video_limit=3,
        radar_content_analysis_daily_minutes_limit=360,
    )
    with Session(engine) as session:
        drama = Drama(title="Drama", file_dir="drama")
        video = ExternalVideo(platform_video_id="v1", video_url="https://youtube.com/watch?v=v1", title="Full", duration_seconds=3600)
        session.add(drama); session.add(video); session.commit(); session.refresh(drama); session.refresh(video)
        cache = {}
        first = radar_search._verify_content_structure(session, settings, video, drama.id, cache)
        second = radar_search._verify_content_structure(session, settings, video, drama.id, cache)
        assert first["structure"] == second["structure"] == "repeated_compilation"
        assert len(calls) == 1
        rows = session.exec(select(VideoMatchEvidence).where(VideoMatchEvidence.match_method == CONTENT_STRUCTURE_METHOD)).all()
        assert len(rows) == 1 and rows[0].analysis_status == "completed"


def test_daily_budget_defers_without_calling_model(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'content-budget.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(radar_search, "analyze_youtube_content", lambda *args: (_ for _ in ()).throw(AssertionError("must not call")))
    settings = SimpleNamespace(
        gemini_api_key="test-key", radar_content_analysis_daily_video_limit=1,
        radar_content_analysis_daily_minutes_limit=360,
    )
    with Session(engine) as session:
        drama = Drama(title="Drama", file_dir="drama")
        prior = ExternalVideo(platform_video_id="v1", duration_seconds=1800)
        candidate = ExternalVideo(platform_video_id="v2", video_url="https://youtube.com/watch?v=v2", title="Full", duration_seconds=3600)
        session.add(drama); session.add(prior); session.add(candidate); session.commit()
        session.refresh(drama); session.refresh(prior); session.refresh(candidate)
        session.add(VideoMatchEvidence(
            external_video_id=prior.id, drama_id=drama.id, match_method=CONTENT_STRUCTURE_METHOD,
            analysis_status="completed", evidence_json={"structure": "true_full_series"},
        ))
        session.commit()
        result = radar_search._verify_content_structure(session, settings, candidate, drama.id, {})
        assert result["analysis_status"] == "deferred"
        assert "今日" in result["reason"]
