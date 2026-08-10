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
    assert "参考样本只决定“怎么写”" in prompt
    assert "source_facts" in prompt
    assert "不得编造婚姻、怀孕、失忆、死亡、身份或反转" in prompt


def test_generic_copy_is_rewritten_with_story_facts(monkeypatch, tmp_path: Path):
    import app.services.llm as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(gemini_api_key="key", qwen_api_key=""))
    generic = '{"candidates":[' + ','.join(
        f'{{"formula":2,"title":"A shocking secret changes everything {i}","caption":"Watch now for an unbelievable story.","hashtags":["#Drama"]}}'
        for i in (1, 2, 3)
    ) + ']}'
    facts = [
        ("Emily Hid Her Identity—Now Logan Must Save Their Daughter", "Emily hid her identity and raised Sophie alone for seven years. When Sophie needs urgent heart treatment, Emily has no choice but to ask cardiac surgeon Logan for help. Logan does not know that the sick child is his daughter, and every medical decision pulls their buried past closer to the truth. Will he save Sophie before he discovers what Emily kept from him?"),
        ("The Surgeon Treating Sophie Has No Idea He Is Her Father", "Cardiac surgeon Logan believes this is another difficult case until Emily walks back into his life with her daughter Sophie. Emily has protected her identity for seven years, but Sophie's illness forces her to trust the one man who can expose everything. The operation could save their child while destroying the secret that kept Emily away. What will Logan do when the truth reaches the operating room?"),
        ("Seven Years Later, Their Daughter Brings Emily Back to Logan", "For seven years Emily raised Sophie alone and kept Logan outside their lives. Now Sophie's heart condition is getting worse, and the only surgeon who may save her is the father who never knew she existed. Emily must choose between protecting her hidden identity and giving her daughter a chance to live. The closer Logan gets to the truth, the more their old choices return to hurt them."),
    ]
    grounded = {"candidates": [
        {"formula": 2, "title": title, "caption": caption, "hashtags": ["#ShortDrama", "#SecretChild"], "source_facts": ["Emily hides her identity and raises daughter Sophie alone", "cardiac surgeon Logan must save Sophie"]}
        for title, caption in facts
    ]}
    calls: list[str] = []
    def fake_gemini(prompt: str):
        calls.append(prompt)
        return generic if len(calls) == 1 else __import__('json').dumps(grounded)
    monkeypatch.setattr(module, "_gemini", fake_gemini)
    banned = tmp_path / "banned.txt"; banned.write_text("", encoding="utf-8")
    synopsis = "Emily hides her identity and raises daughter Sophie alone. Seven years later she asks cardiac surgeon Logan to save Sophie, revealing Logan is the father."
    result = generate_candidates(
        "original prompt",
        is_ai_generated=False,
        account_type="creator",
        banned_words_path=banned,
        quality_context={"synopsis": synopsis, "subtitles": "", "reference_content": "A long reference copy " * 40},
    )
    assert len(calls) == 2
    assert "未通过发布质量校验" in calls[1]
    assert "质量校验后重写" in result.context_used
    assert all(len(item.source_facts) >= 2 for item in result.candidates)
    assert not result.degraded


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
