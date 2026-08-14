from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from ..config import Settings
from .usage import record_model_usage


CONTENT_STRUCTURE_METHOD = "gemini_youtube_structure_v1"
STRUCTURE_VALUES = {
    "true_full_series",
    "fragment_compilation",
    "repeated_compilation",
    "single_excerpt",
    "uncertain",
}


@dataclass(frozen=True)
class ContentStructureDecision:
    structure: str
    confidence: float
    continuous_story_ratio: float
    repetition_ratio: float
    reason: str
    evidence: dict[str, Any]


def build_content_structure_prompt(title: str, duration_seconds: int) -> str:
    minutes = max(0, duration_seconds) / 60
    return f"""你是短剧传播监测中的视频结构审核员。请实际检查这条公开视频的画面、音频、字幕和时间顺序，不要只依据标题或视频时长。

视频标题：{title[:500]}
平台记录时长：{minutes:.1f} 分钟

目标：区分真正连续播放的完整短剧，与通过复制粘贴、循环重复、无关片段或零散剧情拼接而成的伪全集长视频。

判定标准：
1. true_full_series：剧情从开端持续推进到主要结局；人物关系和冲突具有连续因果；多集标题卡或转场顺序合理；主体内容不是重复填充。回顾、闪回或片头重复不能单独判成伪全集。
2. repeated_compilation：同一段画面、对白、镜头组合或剧情块在视频不同位置明显重复，存在循环播放、复制粘贴或为拉长时长而重复填充。
3. fragment_compilation：由不连续片段、预告、解说、不同来源或无关剧情块拼接；缺少从开端到结局的连续覆盖，即使标题写有 full/complete 也不是全集。
4. single_excerpt：主要是一段连续但不完整的单集、节选或推广片段，没有明显重复拼接。
5. uncertain：视频无法读取、证据不足或结构介于多个类别之间。

必须检查视频前段、中段、后段，并给出能复核的时间点。估计 continuous_story_ratio（连续剧情覆盖比例）和 repetition_ratio（重复内容比例），范围均为 0-1。不要判断是否侵权，只判断视频内容结构。

只输出严格 JSON：
{{"structure":"true_full_series|fragment_compilation|repeated_compilation|single_excerpt|uncertain","confidence":0.0,"continuous_story_ratio":0.0,"repetition_ratio":0.0,"unique_plot_sections":0,"sequence_evidence":["00:00-03:00 开端"],"repetition_evidence":["12:00-13:00 与 28:00-29:00 重复"],"reason":"中文简明结论"}}"""


def _ratio(value: Any) -> float:
    try:
        return round(min(1.0, max(0.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


def normalize_content_structure(payload: dict[str, Any]) -> ContentStructureDecision:
    raw_structure = str(payload.get("structure") or "uncertain").strip()
    structure = raw_structure if raw_structure in STRUCTURE_VALUES else "uncertain"
    confidence = _ratio(payload.get("confidence"))
    continuity = _ratio(payload.get("continuous_story_ratio"))
    repetition = _ratio(payload.get("repetition_ratio"))

    # Repetition is objective counter-evidence to a claimed full series. Keep the
    # high-recall safety net here instead of trusting one model label blindly.
    if repetition >= 0.35:
        structure = "repeated_compilation"
    elif structure == "true_full_series" and continuity < 0.60:
        structure = "uncertain"
    elif structure == "true_full_series" and repetition > 0.20:
        structure = "uncertain"

    sequence = [str(item).strip() for item in payload.get("sequence_evidence", []) if str(item).strip()][:12]
    repeated = [str(item).strip() for item in payload.get("repetition_evidence", []) if str(item).strip()][:12]
    try:
        unique_sections = max(0, min(500, int(payload.get("unique_plot_sections") or 0)))
    except (TypeError, ValueError):
        unique_sections = 0
    reason = str(payload.get("reason") or "未提供内容结构说明").strip()[:1000]
    evidence = {
        "structure": structure,
        "confidence": confidence,
        "continuous_story_ratio": continuity,
        "repetition_ratio": repetition,
        "unique_plot_sections": unique_sections,
        "sequence_evidence": sequence,
        "repetition_evidence": repeated,
        "reason": reason,
    }
    return ContentStructureDecision(structure, confidence, continuity, repetition, reason, evidence)


def analyze_youtube_content(settings: Settings, video_url: str, title: str, duration_seconds: int) -> ContentStructureDecision:
    if not getattr(settings, "gemini_api_key", ""):
        raise RuntimeError("尚未配置 GEMINI_API_KEY，无法执行视频内容结构核验")
    model = getattr(settings, "radar_content_analysis_model", "") or getattr(settings, "gemini_text_model", "gemini-2.5-flash")
    timeout_ms = max(30, int(getattr(settings, "radar_content_analysis_timeout_seconds", 180))) * 1000
    client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    video_part = types.Part(
        file_data=types.FileData(file_uri=video_url),
        media_resolution=types.PartMediaResolution(level=types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW),
    )
    response = client.models.generate_content(
        model=model,
        contents=types.Content(parts=[video_part, types.Part(text=build_content_structure_prompt(title, duration_seconds))]),
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    record_model_usage("gemini", model, response, feature="平台动态内容结构核验")
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return normalize_content_structure(json.loads(text))


def classification_for_structure(decision: ContentStructureDecision) -> tuple[str, int, list[str]]:
    reason = [decision.reason]
    if decision.structure == "true_full_series":
        return "suspected_full_reupload", max(85, round(decision.confidence * 100)), reason
    if decision.structure in {"fragment_compilation", "repeated_compilation"}:
        return "suspected_compilation_reupload", max(70, round(decision.confidence * 100)), reason
    if decision.structure == "single_excerpt":
        return "unknown", 0, reason
    return "full_verification_pending", 30, reason
