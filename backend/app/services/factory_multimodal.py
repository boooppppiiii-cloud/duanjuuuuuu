from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings


@dataclass(frozen=True)
class FrameSample:
    index: int
    second: float
    path: Path


class FactoryAIUnavailableError(RuntimeError):
    pass


def provider_name(settings: Settings) -> tuple[str, str]:
    if settings.gemini_api_key:
        return "gemini", settings.factory_analysis_model or settings.gemini_text_model
    if settings.qwen_api_key:
        return "qwen", settings.qwen_vision_model
    raise FactoryAIUnavailableError("内容识别需要多模态模型，请配置 GEMINI_API_KEY 或 QWEN_API_KEY")


def choose_frame_times(start: float, end: float, peaks: list[tuple[float, float]], maximum: int = 12) -> list[float]:
    """Uniform coverage catches quiet visual risks; loudness peaks add likely dramatic moments."""
    duration = max(0.0, end - start)
    if duration <= 0 or maximum <= 0:
        return []
    uniform_count = min(8, maximum, max(1, round(duration / 25)))
    uniform = [start + duration * (index + 0.5) / uniform_count for index in range(uniform_count)]
    ranked_peaks = [second for second, _ in sorted(peaks, key=lambda row: row[1], reverse=True) if start <= second < end]
    candidates = [*uniform, *ranked_peaks]
    result: list[float] = []
    for second in candidates:
        second = min(max(start + 0.05, second), max(start + 0.05, end - 0.05))
        if all(abs(second - existing) >= 1.5 for existing in result):
            result.append(second)
        if len(result) >= maximum:
            break
    return sorted(result)


def extract_frames(
    settings: Settings,
    video: Path,
    frame_dir: Path,
    episode_index: int,
    times: list[float],
) -> list[FrameSample]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    samples: list[FrameSample] = []
    for index, second in enumerate(times, start=1):
        target = frame_dir / f"E{episode_index:03d}_{round(second * 1000):010d}.jpg"
        result = subprocess.run(
            [
                settings.ffmpeg_binary, "-y", "-ss", f"{second:.3f}", "-i", str(video),
                "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "5", str(target),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and target.is_file() and target.stat().st_size:
            samples.append(FrameSample(index=index, second=round(second, 2), path=target))
    return samples


def _strip_fences(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _prompt(episode: str, window_start: float, window_end: float, transcript: list[dict[str, Any]], frames: list[FrameSample]) -> str:
    transcript_text = "\n".join(
        f"[{row['start']:.2f}-{row['end']:.2f}] {str(row.get('text', ''))[:400]}" for row in transcript
    )[:30000]
    frame_text = ", ".join(f"F{row.index}={row.second:.2f}s" for row in frames)
    return f"""你是短剧内容安全审核与增长剪辑专家。结合带时间戳的对白脚本和抽帧画面做判断，不得只看关键词。

剧集：{episode}
分析窗口：{window_start:.2f}s - {window_end:.2f}s
抽帧编号：{frame_text or '无可用画面'}
脚本：
{transcript_text or '该窗口没有可识别对白'}

任务：
1. sensitive：识别画面或剧情中需要剪除的色情裸露、明显性行为/性暗示、性暴力、血腥伤口、肢解、严重殴打、枪击/刀刺等。普通争吵、拥抱、接吻、仅对白提及暴力不要直接判为高风险；不确定时 confidence 低于 0.75。
2. high_energy：识别适合放在片头作为黄金 3 秒钩子的反转、身份揭晓、强冲突、强情绪、悬念或动作瞬间。每个候选应给出可直接裁剪的 2-8 秒范围，最多 5 个，避免纯对白铺垫。
3. 时间必须位于本窗口内；frame_indices 只能使用上面列出的 F 编号。

只输出严格 JSON：
{{"summary":"中文概括","sensitive":[{{"start":0,"end":0,"category":"色情|暴力|血腥|其他","confidence":0.0,"reasons":["中文依据"],"frame_indices":[1]}}],"high_energy":[{{"start":0,"end":0,"score":0,"reasons":["中文依据"],"frame_indices":[1]}}]}}"""


def _gemini(settings: Settings, prompt: str, frames: list[FrameSample]) -> tuple[dict[str, Any], str]:
    from google import genai
    from google.genai import types

    model = settings.factory_analysis_model or settings.gemini_text_model
    contents: list[Any] = [prompt]
    for frame in frames:
        contents.extend([
            f"F{frame.index} · {frame.second:.2f}s",
            types.Part.from_bytes(data=frame.path.read_bytes(), mime_type="image/jpeg"),
        ])
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(_strip_fences(response.text)), model


def _qwen(settings: Settings, prompt: str, frames: list[FrameSample]) -> tuple[dict[str, Any], str]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for frame in frames:
        encoded = base64.b64encode(frame.path.read_bytes()).decode("ascii")
        content.extend([
            {"type": "text", "text": f"F{frame.index} · {frame.second:.2f}s"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ])
    response = httpx.post(
        f"{settings.qwen_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.qwen_api_key}"},
        json={
            "model": settings.qwen_vision_model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        },
        timeout=180,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    return json.loads(_strip_fences(text)), settings.qwen_vision_model


def analyze_window(
    settings: Settings,
    episode: str,
    window_start: float,
    window_end: float,
    transcript: list[dict[str, Any]],
    frames: list[FrameSample],
) -> tuple[dict[str, Any], str, str]:
    prompt = _prompt(episode, window_start, window_end, transcript, frames)
    errors: list[str] = []
    if settings.gemini_api_key:
        try:
            data, model = _gemini(settings, prompt, frames)
            return data, "gemini", model
        except Exception as exc:
            errors.append(f"Gemini {type(exc).__name__}")
    if settings.qwen_api_key:
        try:
            data, model = _qwen(settings, prompt, frames)
            return data, "qwen", model
        except Exception as exc:
            errors.append(f"Qwen {type(exc).__name__}")
    if errors:
        raise RuntimeError("；".join(errors))
    raise FactoryAIUnavailableError("内容识别需要多模态模型，请配置 GEMINI_API_KEY 或 QWEN_API_KEY")
