from __future__ import annotations

import base64
import json
import math
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from .usage import record_model_usage


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


def choose_frame_times(start: float, end: float, peaks: list[tuple[float, float]], maximum: int = 36) -> list[float]:
    """Dense chronological coverage plus short peak bursts supports action-aware review."""
    duration = max(0.0, end - start)
    if duration <= 0 or maximum <= 0:
        return []
    ranked_peaks = [second for second, _ in sorted(peaks, key=lambda row: row[1], reverse=True) if start <= second < end]
    burst_reserve = min(maximum // 3 * 3, len(ranked_peaks[:2]) * 3)
    # Quiet sexualized actions are easy to miss when sampling is driven by audio peaks.
    # Keep chronological coverage close to one frame every two seconds and use the
    # remaining budget for short motion bursts around loudness peaks.
    uniform_count = min(maximum - burst_reserve, max(1, math.ceil(duration / 2)))
    uniform = [start + duration * (index + 0.5) / uniform_count for index in range(uniform_count)]
    peak_bursts = [nearby for second in ranked_peaks for nearby in (second - .8, second, second + .8)]
    candidates = [*peak_bursts, *uniform]
    result: list[float] = []
    for second in candidates:
        second = min(max(start + 0.05, second), max(start + 0.05, end - 0.05))
        if all(abs(second - existing) >= .65 for existing in result):
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
                "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "4", str(target),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and target.is_file() and target.stat().st_size:
            samples.append(FrameSample(index=index, second=round(second, 2), path=target))
    return samples


def extract_frame_pool(
    settings: Settings,
    video: Path,
    frame_dir: Path,
    episode_index: int,
    duration: float,
    interval_seconds: float = 2.0,
) -> list[FrameSample]:
    """Decode one dense frame pool with a single FFmpeg process.

    The previous implementation started FFmpeg once for every requested frame.
    A 60-second analysis window could therefore start 30 processes.  This pool
    keeps equivalent chronological coverage while paying decoder startup only
    once per episode.  Persisted, timestamped JPEGs are also reusable after a
    task interruption.
    """
    frame_dir.mkdir(parents=True, exist_ok=True)
    marker = frame_dir / f".E{episode_index:03d}_pool_complete"
    if marker.is_file():
        existing = sorted(
            (
                FrameSample(index=index, second=int(path.stem.rsplit("_", 1)[1]) / 1000, path=path)
                for index, path in enumerate(frame_dir.glob(f"E{episode_index:03d}_*.jpg"), start=1)
                if "_pool_" not in path.stem
            ),
            key=lambda item: item.second,
        )
        if existing:
            return existing

    interval_seconds = max(1.0, min(5.0, float(interval_seconds)))
    temporary = frame_dir / f".E{episode_index:03d}_pool"
    if temporary.is_dir():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)
    pattern = temporary / "frame_%06d.jpg"
    result = subprocess.run(
        [
            settings.ffmpeg_binary, "-y", "-i", str(video),
            "-vf", f"fps=1/{interval_seconds:.3f},scale=512:-2",
            "-q:v", "4", str(pattern),
        ],
        capture_output=True,
        timeout=max(120, int(max(1.0, duration) * 2)),
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="ignore")[-600:]
        shutil.rmtree(temporary, ignore_errors=True)
        raise RuntimeError(f"批量抽帧失败：{detail or 'FFmpeg 未生成画面'}")

    samples: list[FrameSample] = []
    raw_frames = sorted(temporary.glob("frame_*.jpg"))
    for index, source in enumerate(raw_frames, start=1):
        second = min(max(0.05, (index - 1) * interval_seconds), max(0.05, duration - 0.05))
        target = frame_dir / f"E{episode_index:03d}_{round(second * 1000):010d}.jpg"
        if target.exists():
            target.unlink()
        source.replace(target)
        if target.stat().st_size:
            samples.append(FrameSample(index=index, second=round(second, 2), path=target))
    shutil.rmtree(temporary, ignore_errors=True)
    if not samples:
        raise RuntimeError("批量抽帧完成，但没有得到可用画面")
    marker.write_text(str(len(samples)), encoding="ascii")
    return samples


def select_frames(frame_pool: list[FrameSample], times: list[float]) -> list[FrameSample]:
    """Select the nearest unique pool frames and re-index for model prompts."""
    if not frame_pool or not times:
        return []
    selected: list[FrameSample] = []
    used: set[Path] = set()
    for second in times:
        nearest = min(frame_pool, key=lambda item: abs(item.second - second))
        if nearest.path in used:
            continue
        used.add(nearest.path)
        selected.append(nearest)
    selected.sort(key=lambda item: item.second)
    return [FrameSample(index=index, second=item.second, path=item.path) for index, item in enumerate(selected, start=1)]


def _strip_fences(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _decode_json_object(value: str) -> dict[str, Any]:
    """Decode a model JSON object while tolerating harmless prose/fence suffixes."""
    text = _strip_fences(value)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(payload, dict):
        raise ValueError("模型返回的内容不是 JSON 对象")
    return payload


def _evenly_sample_frames(frames: list[FrameSample], maximum: int) -> list[FrameSample]:
    """Keep chronological coverage while reducing retry upload size."""
    if maximum <= 0 or len(frames) <= maximum:
        return list(frames)
    if maximum == 1:
        return [frames[len(frames) // 2]]
    indices = [round(index * (len(frames) - 1) / (maximum - 1)) for index in range(maximum)]
    return [frames[index] for index in dict.fromkeys(indices)]


_FACTORY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "sensitive", "high_energy"],
    "properties": {
        "summary": {"type": "string"},
        "sensitive": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "category", "confidence", "overall_risk_score", "risk_scores", "reasons", "frame_indices"],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number"},
                    "overall_risk_score": {"type": "number"},
                    "risk_scores": {
                        "type": "object",
                        "properties": {
                            key: {"type": "number"} for key in (
                                "body_focus", "action", "dialogue_context", "expression_audio",
                                "scene_context", "religious_context",
                            )
                        },
                    },
                    "religions": {"type": "array", "items": {"type": "string"}},
                    "taboo_types": {"type": "array", "items": {"type": "string"}},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "frame_indices": {"type": "array", "items": {"type": "integer"}},
                },
            },
        },
        "high_energy": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["start", "end", "score", "reasons", "frame_indices"],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "score": {"type": "number"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "frame_indices": {"type": "array", "items": {"type": "integer"}},
                },
            },
        },
    },
}


def build_window_prompt(episode: str, window_start: float, window_end: float, transcript: list[dict[str, Any]], frames: list[FrameSample]) -> str:
    transcript_text = "\n".join(
        f"[{row['start']:.2f}-{row['end']:.2f}] {str(row.get('text', ''))[:400]}" for row in transcript
    )[:30000]
    frame_text = ", ".join(f"F{row.index}={row.second:.2f}s" for row in frames)
    return f"""你是短剧内容安全审核与增长剪辑专家。结合带时间戳的 ASR 对白和按时间顺序排列的连续抽帧做判断，不得只看关键词，也不得只按裸露程度判断。

剧集：{episode}
分析窗口：{window_start:.2f}s - {window_end:.2f}s
抽帧编号：{frame_text or '无可用画面'}
脚本：
{transcript_text or '该窗口没有可识别对白'}

任务：
1. sensitive：重点检测软色情、性暗示、性行为、性暴力、血腥伤口、肢解、严重殴打、枪击/刀刺，以及宗教禁忌。按以下 6 个维度联合评分（每项 0-100）：
   - body_focus：镜头是否持续聚焦胸部、臀部、胯部、大腿或裙底；泳装/比基尼、情趣内衣、低领或过度暴露服装、贴身衣物、睡衣、湿身、换衣、床上场景均要按暴露程度和镜头意图评分。男性裸露上半身的近景、慢镜头或肌肉聚焦同样必须输出供人工复核，不因角色性别降低标准。
   - action：是否出现抚摸敏感部位、拉扯衣物、压床、贴身控制、暧昧距离、反复身体/骨盆撞击等动作；必须比较相邻 F 帧理解动作变化。
   - dialogue_context：把 ASR 台词与人物位置、服装和动作结合判断；单独无害的台词在暧昧情境中可以构成风险。
   - expression_audio：是否出现色情化表情、喘息/呻吟语义、挑逗姿态或明显暧昧氛围。
   - scene_context：床、浴室、裙底、封闭空间、强迫控制关系，以及尾巴/触手/棍状物伸入裙底或接触胯部等性暗示道具互动。
   - religious_context：判断是否存在针对宗教信仰、信徒、神圣人物、经书、符号、服饰、仪式、场所、葬仪或饮食禁忌的侮辱、亵渎、性化、仇恨、暴力煽动或强迫违反。必须同时结合 ASR、符号/服饰/场所和人物动作，不得仅因出现宗教元素就判风险。
   特别规则：尾巴、触手或其他物体伸入裙底，人物反复身体撞击/骨盆运动，伴随色情化面部表情时，即使没有裸露也必须报为“性暗示”或“软色情”，action 与 scene_context 应为高分。
   色情内容采用高召回策略：胸臀胯/裙底聚焦、比基尼或情趣内衣、过度暴露服装、男女裸露或近裸、男性裸上身聚焦、床上或换衣、贴身衣物、挑逗姿态、压床、衣物拉扯、敏感部位接触、骨盆运动、呻吟喘息等只要存在合理怀疑，即使画面不清晰或置信度较低也必须输出；裸体、疑似裸体、性爱或疑似床戏必须完整标记删除范围。色情、软色情、低俗擦边、暴露、性暗示、性行为、性暴力的总风险达到 10 就输出，宁可交给人工排除，不得漏报。其他类别总风险达到 30 输出；60-100 为高风险。
   片头字幕、标题卡或画面内文案若利用色情暗示、低俗词汇或暴露画面吸引点击，也要以“低俗擦边”输出；不能因为内容服务剧情或仅短暂出现就忽略。
   必须按“完整风险场景”标注时间：从最早出现暧昧铺垫、身体聚焦、强迫控制或可疑道具接触开始，直到人物完全停止相关动作或镜头切离为止。不得只截取最露骨的几秒。若风险场景在本窗口开始前已经发生，start 必须等于窗口起点；若窗口结束时仍未停止，end 必须等于窗口终点，系统会与相邻重叠窗口合并。
   连续帧中即使单帧看不出裸露，也要比较人物/尾巴/触手/衣物的位置变化来判断插入、撞击、抚摸、拉扯等动作。动画、特效、奇幻生物和非真人画面使用同一标准。
   每个存在合理怀疑的时间段都要逐一输出，不得用 summary 代替 sensitive 候选，也不得因为已经输出一个候选而省略同一窗口内的其他风险段。
   普通争吵、普通拥抱、普通接吻、仅对白提及暴力且画面无对应行为时不要判成高风险；但只要同时出现身体聚焦、性姿态或暧昧动作，仍按色情高召回规则输出。
   宗教禁忌必须跨信仰考虑，包括但不限于：故意毁损或侵渎古兰经、圣经、托拉、印度教/佛教/锡克教经文与神圣符号；侮辱或性化神灵、先知、圣人、僧侣、宗教服饰与仪式；毁坏教堂、清真寺、犹太会堂、寺庙、神龛、墓地或葬仪；强迫穆斯林食用猪肉/酒精、故意以牛肉/伤害圣牛侮辱印度教信徒、故意违反犹太洁食/清真饮食并以此羞辱信徒；针对信徒的贬损、仇恨、强迫改教、驱逐或暴力煽动；以及对穆罕默等高敏感宗教人物的冒犯性描绘。
   以上只是风险示例，不得将某种服饰、食物、祈祷、节日、寺庙镜头、不同信仰人物共处、学术/新闻讨论或虚构宗教本身视为违规。religions 必须列出实际涉及的信仰，taboo_types 必须列出可验证的具体禁忌类型；证据不足时保持低分或不输出。普通宗教表达为 0-20，疑似冒犯为 30-59 交人工复核，明确亵渎、仇恨或强迫违反为 60-100。
2. high_energy：识别适合放在片头的反转、身份揭晓、强冲突、强情绪、悬念或动作场景。每个候选必须给出可直接裁剪的完整 15-30 秒范围，包含必要铺垫、爆发点和结果，最多 5 个；不得只截取 2-8 秒的单一瞬间，也不要选择只有普通对白的片段。
3. sensitive 的 start/end 要覆盖完整风险动作；frame_indices 提供最能证明风险的 1-4 帧。时间必须位于本窗口内；frame_indices 只能使用上面列出的 F 编号。

只输出严格 JSON：
{{"summary":"中文概括","sensitive":[{{"start":0,"end":0,"category":"软色情|低俗擦边|暴露|性暗示|色情|性行为|性暴力|暴力|血腥|宗教禁忌|宗教亵渎|宗教仇恨|其他","confidence":0.0,"overall_risk_score":0,"risk_scores":{{"body_focus":0,"action":0,"dialogue_context":0,"expression_audio":0,"scene_context":0,"religious_context":0}},"religions":["伊斯兰教|基督宗教|犹太教|印度教|佛教|锡克教|原住民信仰|其他"],"taboo_types":["神圣符号/经书亵渎|宗教仇恨|强迫违反饮食/仪式|性化|场所/葬仪冒犯|强迫改教|其他"],"reasons":["必须同时描述画面/服装/动作与台词上下文"],"frame_indices":[1]}}],"high_energy":[{{"start":0,"end":0,"score":0,"reasons":["中文依据"],"frame_indices":[1]}}]}}"""


# Keep the former private helper available for older integrations and tests.
def _prompt(
    episode: str,
    window_start: float,
    window_end: float,
    transcript: list[dict[str, Any]],
    frames: list[FrameSample],
) -> str:
    return build_window_prompt(episode, window_start, window_end, transcript, frames)


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
    timeout_ms = max(15, int(getattr(settings, "factory_analysis_request_timeout_seconds", 120))) * 1000
    client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=timeout_ms))
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=_FACTORY_RESPONSE_SCHEMA,
            max_output_tokens=8192,
            temperature=0.1,
        ),
    )
    record_model_usage("gemini", model, response, feature="内容识别")
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed, model
    if hasattr(parsed, "model_dump"):
        dumped = parsed.model_dump()
        if isinstance(dumped, dict):
            return dumped, model
    return _decode_json_object(response.text), model


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
        timeout=max(15, int(getattr(settings, "factory_analysis_request_timeout_seconds", 120))),
    )
    response.raise_for_status()
    payload = response.json()
    record_model_usage("qwen", settings.qwen_vision_model, payload, feature="内容识别")
    text = payload["choices"][0]["message"]["content"]
    return _decode_json_object(text), settings.qwen_vision_model


def _is_non_retryable_provider_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    if status in {400, 401, 403}:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "invalid api key", "api key not valid", "unauthorized", "permission denied",
        "authentication failed", "incorrect api key",
    ))


def _manual_review_fallback(
    window_start: float,
    window_end: float,
    frames: list[FrameSample],
) -> dict[str, Any]:
    frame_indices = [frame.index for frame in _evenly_sample_frames(frames, 4)]
    return {
        "summary": "模型服务在该窗口暂时不可用，系统已保留完整窗口供人工复核，并继续识别后续内容。",
        "sensitive": [{
            "start": window_start,
            "end": window_end,
            "category": "其他",
            "confidence": 0.59,
            "overall_risk_score": 59,
            "risk_scores": {
                "body_focus": 0,
                "action": 0,
                "dialogue_context": 59,
                "expression_audio": 0,
                "scene_context": 59,
                "religious_context": 0,
            },
            "religions": [],
            "taboo_types": [],
            "reasons": ["AI 临时未完成该窗口的多模态判断；为避免漏审，必须人工复核完整窗口。"],
            "frame_indices": frame_indices,
        }],
        "high_energy": [],
    }


def analyze_window(
    settings: Settings,
    episode: str,
    window_start: float,
    window_end: float,
    transcript: list[dict[str, Any]],
    frames: list[FrameSample],
) -> tuple[dict[str, Any], str, str]:
    errors: list[str] = []
    retries = max(1, min(3, int(getattr(settings, "factory_analysis_api_retries", 2))))
    for attempt in range(retries):
        frame_limit = len(frames) if attempt == 0 else max(8, min(16, math.ceil(len(frames) / 2)))
        attempt_frames = _evenly_sample_frames(frames, frame_limit)
        prompt = build_window_prompt(episode, window_start, window_end, transcript, attempt_frames)
        if settings.gemini_api_key:
            try:
                data, model = _gemini(settings, prompt, attempt_frames)
                return data, "gemini", model
            except Exception as exc:
                if _is_non_retryable_provider_error(exc):
                    raise RuntimeError(f"Gemini 凭证或权限错误：{exc}") from exc
                errors.append(f"Gemini {type(exc).__name__}")
        if settings.qwen_api_key:
            try:
                qwen_frames = _evenly_sample_frames(attempt_frames, 10)
                qwen_prompt = build_window_prompt(episode, window_start, window_end, transcript, qwen_frames)
                data, model = _qwen(settings, qwen_prompt, qwen_frames)
                return data, "qwen", model
            except Exception as exc:
                if _is_non_retryable_provider_error(exc):
                    raise RuntimeError(f"Qwen 凭证或权限错误：{exc}") from exc
                errors.append(f"Qwen {type(exc).__name__}")
        if attempt + 1 < retries:
            time.sleep(1.5 * (attempt + 1))
    if errors:
        return _manual_review_fallback(window_start, window_end, frames), "manual_review_fallback", "transient_model_failure"
    raise FactoryAIUnavailableError("内容识别需要多模态模型，请配置 GEMINI_API_KEY 或 QWEN_API_KEY")
