import json
from pathlib import Path

import httpx

from ..config import get_settings
from ..schemas import TitleCandidate, TitleCandidates
from .moderation import find_hits, load_banned_words

FORMULAS = """1.【剧名】+【热门 tag】
2.【剧名】+【人设反差】+【旁人衬托】+【剧集方 tag】
3.【emoji】+【剧名】+【身份反差】+【剧情反转】+【tag】
4.【剧名】+【知名演员名】+【剧情冲突】+【反转】+【冲突】+【tag】"""


class LLMUnavailableError(RuntimeError):
    pass


def assess_visual(image_path: Path) -> tuple[str, list[str], str]:
    """Use a real multimodal safety check; never report a synthetic green result."""
    settings = get_settings()
    if settings.gemini_api_key:
        from google import genai
        from google.genai import types
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(model=settings.gemini_text_model, contents=[types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime), "作为内容安全审核员，只输出严格 JSON：{\"risk\":\"green|yellow|red\",\"reasons\":[\"中文理由\"]}。红色代表明显裸露或性暗示，黄色代表不确定需人工复核，绿色代表正常剧情画面。"], config=types.GenerateContentConfig(response_mime_type="application/json"))
        data=json.loads(strip_fences(response.text));return data["risk"],data.get("reasons",[]),"gemini"
    raise LLMUnavailableError("未配置 GEMINI_API_KEY，无法执行智能画面安全检测；请人工复核")


def build_prompt(*, title: str, genres: list[str], actors: list[str], subtitles: str, account_type: str, target_language: str, formula: int | str, examples: str) -> str:
    return f"""系统人设：你是海外短剧达人运营专家。输出语言必须是 {target_language}，内容健康、禁止擦边和性暗示。
规则：生成恰好 3 组候选；标题短而有冲突；hashtags 不含空格；只输出严格 JSON，不要 Markdown 围栏。
标题四公式：
{FORMULAS}
指定公式：{formula}（auto 表示自行选择最合适公式）
账号类型：{account_type}。official 文案尾部必须自然包含 APP 引导和占位符 {{app_link}}；creator 文案尾部必须包含与“Full episodes 👉 link in comments”语义一致的目标语言话术。
已验证的 few-shot 样本（为空时不要自行假设样本）：
{examples}
本次输入：剧名={title}；题材={genres}；演员={actors}；字幕全文={subtitles}
输出结构：{{"candidates":[{{"formula":2,"title":"","caption":"","hashtags":[]}},{{...}},{{...}}]}}"""


def strip_fences(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"): clean = clean[:-3]
    return clean.strip()


def parse_candidates(text: str) -> TitleCandidates:
    return TitleCandidates.model_validate(json.loads(strip_fences(text)))


def _gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_text_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return response.text


def _qwen(prompt: str) -> str:
    settings = get_settings()
    response = httpx.post(
        f"{settings.qwen_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.qwen_api_key}"},
        json={"model": settings.qwen_model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}},
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def generate_candidates(prompt: str, *, is_ai_generated: bool, account_type: str, banned_words_path: Path) -> TitleCandidates:
    settings = get_settings()
    providers = []
    if settings.gemini_api_key: providers.append(_gemini)
    if settings.qwen_api_key: providers.append(_qwen)
    if not providers:
        raise LLMUnavailableError("未配置 GEMINI_API_KEY 或 QWEN_API_KEY，不能生成真实标题文案")
    last_error: Exception | None = None
    for provider in providers:
        for _ in range(2):
            try:
                result = parse_candidates(provider(prompt))
                words = load_banned_words(banned_words_path)
                updated: list[TitleCandidate] = []
                for item in result.candidates:
                    caption = item.caption
                    required = "{app_link}" if account_type == "official" else "Full episodes 👉 link in comments"
                    if required.casefold() not in caption.casefold(): caption = f"{caption.rstrip()}\n{required}"
                    if is_ai_generated and "#aigc" not in caption.casefold(): caption = f"{caption.rstrip()}\nAI-generated content #AIGC"
                    updated.append(item.model_copy(update={"caption": caption, "hit_words": find_hits(f"{item.title}\n{caption}", words)}))
                return TitleCandidates(candidates=updated, provider=provider.__name__.lstrip("_"))
            except Exception as exc:
                last_error = exc
    raise LLMUnavailableError(f"文本模型输出无效：{last_error}")
