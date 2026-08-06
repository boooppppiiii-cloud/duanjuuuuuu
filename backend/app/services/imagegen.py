import threading
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from ..config import get_settings
from ..models import ImageQuota

BASEMAP_PROMPT = """结合输入图片生成 1920x1080 超高清短剧封面底图，严格保留原图人物五官、脸型、表情、肢体动作与中心构图完全不变，大幅重构升级同风格全新背景，深度重塑场景层次与空间氛围，强化电影级景深虚化、冷暖氛围光影、镜头光晕、散景光斑，叠加同风格精致装饰元素与朦胧前景，整体高级精致有辨识度，8K 超写实、胶片电影质感，女主占据中心主要位置。画面中不得出现任何文字、字母、水印，画面顶部与底部各预留约 15% 的简洁净空区域用于后期排版。"""
DIRECT_PROMPT = BASEMAP_PROMPT + " 标题使用加粗超大字体、白色或深色粗描边与立体浮雕、超高对比，1至2行规整排版，避开人脸，边缘锐利。标题文字：{title}"
LIMITS = {"basemap": 120, "direct": 50}
_quota_lock = threading.Lock()


class QuotaExceededError(RuntimeError):
    pass


def consume_quota(session: Session, kind: str) -> ImageQuota:
    if kind not in LIMITS:
        raise ValueError("未知图像生成类型")
    month = datetime.now().strftime("%Y-%m")
    with _quota_lock:
        quota = session.exec(select(ImageQuota).where(ImageQuota.month == month, ImageQuota.kind == kind)).first()
        quota = quota or ImageQuota(month=month, kind=kind, count=0)
        if quota.count >= LIMITS[kind]:
            raise QuotaExceededError(f"{kind} 本月配额已用完（{LIMITS[kind]} 张）")
        quota.count += 1
        session.add(quota); session.commit(); session.refresh(quota)
        return quota


def generate_image(session: Session, source: Path, output: Path, *, kind: str = "basemap", title: str = "") -> Path:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("未配置 GEMINI_API_KEY")
    from google import genai
    from google.genai import types

    prompt = BASEMAP_PROMPT if kind == "basemap" else DIRECT_PROMPT.format(title=title)
    mime = "image/png" if source.suffix.lower() == ".png" else "image/jpeg"
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_image_model,
        contents=[types.Part.from_bytes(data=source.read_bytes(), mime_type=mime), prompt],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for part in response.parts:
        if getattr(part, "inline_data", None):
            consume_quota(session, kind)
            output.parent.mkdir(parents=True, exist_ok=True)
            image = part.as_image()
            image.save(output)
            return output
    raise RuntimeError("Gemini 未返回图像")
