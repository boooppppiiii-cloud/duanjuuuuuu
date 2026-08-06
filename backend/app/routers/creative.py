from pathlib import Path
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..database import get_session
from ..models import Account, AccountStrategy, Basemap, Clip, ContentExample, Drama, HotNote, ImageQuota, Post, TagLibraryItem
from ..schemas import BasemapGenerateRequest, BasemapReviewRequest, CoverCreateRequest, PostCreateRequest, TitleCandidates, TitleGenerationRequest
from ..services.cover import render_cover
from ..services.imagegen import QuotaExceededError, generate_image
from ..services.llm import LLMUnavailableError, build_prompt, generate_candidates
from ..services.moderation import find_hits, load_banned_words

router = APIRouter(prefix="/api/creative", tags=["标题与封面"])
DATA_ROOT = Path(__file__).parents[2] / "data"
PROJECT_ROOT = Path(__file__).parents[3]


@router.post("/titles", response_model=TitleCandidates)
def titles(payload: TitleGenerationRequest, session: Session = Depends(get_session)):
    clip = session.get(Clip, payload.clip_id)
    drama = session.get(Drama, clip.drama_id) if clip else None
    if not clip or not drama:
        raise HTTPException(404, "切片或剧目不存在")
    account = session.get(Account, payload.account_id) if payload.account_id else None
    strategy = session.get(AccountStrategy, account.strategy_id) if account and account.strategy_id else None
    account_type = account.account_type if account else payload.account_type
    platform = account.platform if account else "all"
    all_examples = session.exec(select(ContentExample).where(ContentExample.enabled == True)).all()  # noqa: E712
    matched_examples = [item for item in all_examples if item.language.casefold() == payload.target_language.casefold() and item.platform in {"all", platform} and (not item.genres or bool(set(item.genres) & set(drama.genres)))][:5]
    examples = "\n".join(item.content for item in matched_examples)
    all_tags = session.exec(select(TagLibraryItem).where(TagLibraryItem.enabled == True)).all()  # noqa: E712
    matched_tags = [item.tag for item in all_tags if item.language.casefold() == payload.target_language.casefold() and item.platform in {"all", platform} and (not item.genres or bool(set(item.genres) & set(drama.genres)))]
    active_hot={item.content for item in session.exec(select(HotNote)).all() if item.expires_at>=date.today() and item.platform in {platform,"all"}}
    hot_tags=[tag if tag.startswith("#") else "#"+tag.replace(" ","") for tag in payload.hot_tags if tag in active_hot]
    formula = strategy.title_formula_preference if strategy and payload.formula == "auto" else payload.formula
    strategy_context = ""
    if strategy:
        strategy_context = f"\n账号策略：定位={strategy.positioning}；人设={strategy.persona_keywords}；口吻={strategy.tone_examples}；标签池={strategy.tag_pool}"
    prompt = build_prompt(title=drama.title, genres=drama.genres, actors=drama.actor_names, subtitles=clip.subtitle_text, account_type=account_type, target_language=payload.target_language, formula=formula, examples=examples + strategy_context)
    try:
        result = generate_candidates(prompt, is_ai_generated=drama.is_ai_generated, account_type=account_type, banned_words_path=DATA_ROOT / "banned_words.txt")
        if account and account_type == "official" and account.credentials_json.get("app_link"):
            result = result.model_copy(update={"candidates": [item.model_copy(update={"caption": item.caption.replace("{app_link}", str(account.credentials_json["app_link"]))}) for item in result.candidates]})
        if strategy:
            candidates = []
            for item in result.candidates:
                tags = list(dict.fromkeys(strategy.tag_pool + item.hashtags))
                candidates.append(item.model_copy(update={"hashtags": tags}))
            result = result.model_copy(update={"candidates": candidates})
        if matched_examples or matched_tags:
            influenced = []
            for item in result.candidates:
                influenced.append(item.model_copy(update={"hashtags": list(dict.fromkeys(matched_tags + hot_tags + item.hashtags))}))
            result = result.model_copy(update={"candidates": influenced, "context_used": [f"样本:{x.content}" for x in matched_examples] + [f"标签:{x}" for x in matched_tags] + [f"热点:{x}" for x in hot_tags]})
        elif hot_tags:
            result = result.model_copy(update={"candidates":[item.model_copy(update={"hashtags":list(dict.fromkeys(hot_tags+item.hashtags))}) for item in result.candidates],"context_used":[f"热点:{x}" for x in hot_tags]})
        return result
    except LLMUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/posts", response_model=Post)
def create_post(payload: PostCreateRequest, session: Session = Depends(get_session)):
    clip = session.get(Clip, payload.clip_id)
    if not clip:
        raise HTTPException(404, "切片不存在")
    hits = find_hits(f"{payload.candidate.title}\n{payload.candidate.caption}", load_banned_words(DATA_ROOT / "banned_words.txt"))
    if hits:
        raise HTTPException(422, f"标题或文案命中禁词：{', '.join(hits)}")
    drama = session.get(Drama, clip.drama_id)
    caption = payload.candidate.caption
    if drama and drama.is_ai_generated and "#aigc" not in caption.casefold():
        caption = f"{caption.rstrip()}\nAI-generated content #AIGC"
    post = Post(clip_id=clip.id, title=payload.candidate.title, caption=caption, hashtags=payload.candidate.hashtags, title_formula=payload.candidate.formula)
    session.add(post); session.commit(); session.refresh(post)
    return post


@router.get("/posts", response_model=list[Post])
def list_posts(session: Session = Depends(get_session)):
    return session.exec(select(Post).order_by(Post.id.desc())).all()


@router.post("/basemaps", response_model=list[Basemap])
def create_basemaps(payload: BasemapGenerateRequest, session: Session = Depends(get_session)):
    drama = session.get(Drama, payload.drama_id)
    if not drama:
        raise HTTPException(404, "剧目不存在")
    stills = (Path(drama.file_dir) / "stills").resolve()
    source = (stills / Path(payload.still_filename).name).resolve()
    if source.parent != stills or not source.is_file():
        raise HTTPException(404, "剧照不存在")
    created: list[Basemap] = []
    try:
        for _ in range(2):
            basemap = Basemap(drama_id=drama.id, file_path="", source="still", status="pending")
            session.add(basemap); session.commit(); session.refresh(basemap)
            output = Path(drama.file_dir) / "basemaps" / f"ai_basemap_{basemap.id}.png"
            generate_image(session, source, output, kind="basemap")
            basemap.file_path = str(output)
            session.add(basemap); session.commit(); session.refresh(basemap)
            created.append(basemap)
        return created
    except QuotaExceededError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"底图生成失败：{exc}") from exc


@router.get("/basemaps", response_model=list[Basemap])
def list_basemaps(drama_id: int, session: Session = Depends(get_session)):
    return session.exec(select(Basemap).where(Basemap.drama_id == drama_id).order_by(Basemap.id.desc())).all()


@router.put("/basemaps/{basemap_id}", response_model=Basemap)
def review_basemap(basemap_id: int, payload: BasemapReviewRequest, session: Session = Depends(get_session)):
    item = session.get(Basemap, basemap_id)
    if not item:
        raise HTTPException(404, "底图不存在")
    item.status = payload.status
    session.add(item); session.commit(); session.refresh(item)
    return item


@router.get("/basemaps/{basemap_id}/image")
def basemap_image(basemap_id: int, session: Session = Depends(get_session)):
    item = session.get(Basemap, basemap_id)
    path = Path(item.file_path) if item and item.file_path else None
    if not path or not path.is_file():
        raise HTTPException(404, "底图文件不存在")
    return FileResponse(path)


@router.post("/covers", response_model=Post)
def create_covers(payload: CoverCreateRequest, session: Session = Depends(get_session)):
    post = session.get(Post, payload.post_id)
    clip = session.get(Clip, post.clip_id) if post else None
    drama = session.get(Drama, clip.drama_id) if clip else None
    if not post or not clip or not drama:
        raise HTTPException(404, "成品、切片或剧目不存在")
    approved = session.exec(select(Basemap).where(Basemap.drama_id == drama.id, Basemap.status == "approved").order_by(Basemap.id.desc())).first()
    source = Path(approved.file_path) if approved and Path(approved.file_path).is_file() else None
    if not source:
        candidates = [Path(payload.fallback_image)] if payload.fallback_image else []
        if clip.preview_image: candidates.append(Path(clip.preview_image))
        source = next((path for path in candidates if path.is_file()), None)
        post.cover_fallback = True
    if not source:
        raise HTTPException(422, "没有 approved 底图或可用高能帧，无法生成降级封面")
    output_dir = get_media_posts_root() / f"post_{post.id}"
    try:
        path169 = render_cover(source, output_dir / "cover_16x9.jpg", post.title, payload.account_type, (1920, 1080), DATA_ROOT / "cover_style.json", PROJECT_ROOT)
        path916 = render_cover(source, output_dir / "cover_9x16.jpg", post.title, payload.account_type, (1080, 1920), DATA_ROOT / "cover_style.json", PROJECT_ROOT)
    except Exception as exc:
        raise HTTPException(500, f"封面压字失败：{exc}") from exc
    post.basemap_id = approved.id if approved else None
    post.cover_path_169, post.cover_path_916 = str(path169), str(path916)
    session.add(post); session.commit(); session.refresh(post)
    return post


def get_media_posts_root() -> Path:
    from ..config import get_settings
    return get_settings().media_root / "posts"


@router.get("/posts/{post_id}/cover/{ratio}")
def cover_image(post_id: int, ratio: str, session: Session = Depends(get_session)):
    post = session.get(Post, post_id)
    value = post.cover_path_169 if post and ratio == "169" else post.cover_path_916 if post and ratio == "916" else ""
    path = Path(value) if value else None
    if not path or not path.is_file():
        raise HTTPException(404, "封面不存在")
    return FileResponse(path)


@router.get("/quotas")
def quotas(session: Session = Depends(get_session)):
    from datetime import datetime
    month = datetime.now().strftime("%Y-%m")
    rows = session.exec(select(ImageQuota).where(ImageQuota.month == month)).all()
    values = {row.kind: row.count for row in rows}
    return {"month": month, "basemap": {"used": values.get("basemap", 0), "limit": 120}, "direct": {"used": values.get("direct", 0), "limit": 50}}
