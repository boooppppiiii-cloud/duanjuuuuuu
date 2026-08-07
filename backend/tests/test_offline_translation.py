from app.services import offline_translation


def test_detect_language_handles_chinese_and_url_heavy_english():
    assert offline_translation.detect_language("这部剧太好看了") == "zh"
    assert offline_translation.detect_language("Watch the full episode: https://example.com/show") == "en"


def test_local_translation_preserves_links_and_handles(monkeypatch):
    monkeypatch.setattr(offline_translation, "_ensure_pair", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        offline_translation.translate,
        "translate",
        lambda text, _source, _target: text.replace("Watch the full episode", "观看完整剧集"),
    )

    result = offline_translation.translate_to_chinese(
        "Watch the full episode https://example.com/show @DramaBox"
    )

    assert "观看完整剧集" in result
    assert "https://example.com/show" in result
    assert "@DramaBox" in result


def test_chinese_comment_is_returned_without_model(monkeypatch):
    monkeypatch.setattr(
        offline_translation,
        "_ensure_pair",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model should not be used")),
    )
    assert offline_translation.translate_to_chinese("已经看到第十集了") == "已经看到第十集了"
