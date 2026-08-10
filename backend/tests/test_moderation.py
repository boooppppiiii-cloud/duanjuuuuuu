from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import AppUser, Clip, Drama
from app.routers.moderation import review_clip
from app.schemas import ClipReviewRequest
from app.services.moderation import check_text, load_banned_words


def test_banned_words_ignore_comments_and_highlight(tmp_path: Path):
    word_file = tmp_path / "words.txt"
    word_file.write_text("# 注释\n测试词\n风险\n", encoding="utf-8")
    assert load_banned_words(word_file) == ["测试词", "风险"]
    hits, parts = check_text("普通内容包含测试词", word_file)
    assert hits == ["测试词"]
    assert any(part.hit and part.text == "测试词" for part in parts)


def test_manual_review_can_override_automatic_block(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = AppUser(email="reviewer@example.com", password_hash="test")
        session.add(user); session.commit(); session.refresh(user)
        drama = Drama(title="合规测试剧", file_dir=str(tmp_path), source_note="测试")
        session.add(drama); session.commit(); session.refresh(drama)
        clip = Clip(drama_id=drama.id, template_name="suspense_hook", status="blocked", current_step="completed", hit_words=["测试词"], owner_user_id=user.id)
        session.add(clip); session.commit(); session.refresh(clip)
        result = review_clip(clip.id, ClipReviewRequest(status="approved", note="人工确认语境安全"), session, user)
        assert result.status == "approved"
        assert result.reviewed_at is not None
