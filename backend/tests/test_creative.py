from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import ImageQuota
from app.services.cover import render_cover
from app.services.imagegen import QuotaExceededError, consume_quota
from app.services.llm import apply_theater_tag, build_prompt, generate_candidates, parse_candidates, strip_fences


def test_json_fence_cleanup_and_strict_three_candidates():
    text = '```json\n{"candidates":[' + ','.join(
        f'{{"formula":{i},"title":"t{i}","caption":"c{i}","hashtags":["#x"]}}' for i in (1, 2, 3)
    ) + ']}\n```'
    assert strip_fences(text).startswith('{')
    assert len(parse_candidates(text).candidates) == 3


def test_ai_caption_and_account_suffix_are_forced(monkeypatch, tmp_path: Path):
    import app.services.llm as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(gemini_api_key="key", qwen_api_key=""))
    raw = '{"candidates":[' + ','.join(
        f'{{"formula":{i},"title":"title{i}","caption":"caption{i}","hashtags":[]}}' for i in (1, 2, 3)
    ) + ']}'
    monkeypatch.setattr(module, "_gemini", lambda _: raw)
    banned = tmp_path / "banned.txt"; banned.write_text("", encoding="utf-8")
    result = generate_candidates("prompt", is_ai_generated=True, account_type="official", banned_words_path=banned)
    assert all("{app_link}" in item.caption for item in result.candidates)
    assert all("#AIGC" in item.caption for item in result.candidates)


def test_theater_tag_can_be_forced_or_removed():
    raw = '{"candidates":[' + ','.join(
        f'{{"formula":2,"title":"{("A dramatic secret " * 10).strip()}","caption":"Watch now #FlickReels","hashtags":["#Drama","#FlickReels"]}}' for _ in range(3)
    ) + ']}'
    result = parse_candidates(raw)
    included = apply_theater_tag(result, "Flick Reels", True)
    assert all(item.title.endswith("#FlickReels") and len(item.title) < 100 for item in included.candidates)
    assert all("#FlickReels" in item.hashtags for item in included.candidates)

    excluded = apply_theater_tag(result, "FlickReels", False)
    assert all("#flickreels" not in item.title.casefold() and "#flickreels" not in item.caption.casefold() for item in excluded.candidates)
    assert all("#FlickReels" not in item.hashtags for item in excluded.candidates)


def test_prompt_uses_saved_history_and_drama_synopsis():
    prompt = build_prompt(title="The Name We Buried", synopsis="A mother returns with a sick child.", theater_tag="#FlickReels", include_theater_tag=True, genres=["Romance"], actors=[], subtitles="", account_type="creator", target_language="English", formula="auto", reference_content="I faked death seven years ago")
    assert "A mother returns with a sick child." in prompt
    assert "I faked death seven years ago" in prompt
    assert "#FlickReels" in prompt


def test_basemap_quota_refuses_at_limit(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ImageQuota(month=__import__('datetime').datetime.now().strftime('%Y-%m'), kind="basemap", count=119)); session.commit()
        assert consume_quota(session, "basemap").count == 120
        with pytest.raises(QuotaExceededError): consume_quota(session, "basemap")


def test_pillow_outputs_both_cover_ratios(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (800, 450), "#34506f").save(source)
    style = Path(__file__).parents[1] / "data" / "cover_style.json"
    root = Path(__file__).parents[2]
    out169, out916 = tmp_path / "169.jpg", tmp_path / "916.jpg"
    render_cover(source, out169, "复仇女王归来", "official", (1920, 1080), style, root)
    render_cover(source, out916, "Revenge Queen Returns", "creator", (1080, 1920), style, root)
    assert Image.open(out169).size == (1920, 1080)
    assert Image.open(out916).size == (1080, 1920)
