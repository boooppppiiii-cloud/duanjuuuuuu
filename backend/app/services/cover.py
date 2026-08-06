import json
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont


def load_style(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_font(style: dict, project_root: Path) -> Path:
    for value in style["font_paths"]:
        path = Path(value)
        if not path.is_absolute(): path = project_root / path
        if path.exists(): return path
    raise FileNotFoundError("未找到中文/西文字体，请按 media/assets/README.md 放置字体")


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    ratio = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
    left, top = (resized.width - size[0]) // 2, (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def wrap_title(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, current = [], ""
    for char in title:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current); current = char
        else: current = candidate
    if current: lines.append(current)
    return lines[:2]


def render_cover(source: Path, output: Path, title: str, account_type: str, size: tuple[int, int], style_path: Path, project_root: Path) -> Path:
    style = load_style(style_path)
    canvas = fit_cover(Image.open(source).convert("RGB"), size)
    draw = ImageDraw.Draw(canvas)
    font_path = resolve_font(style, project_root)
    safe = int(min(size) * float(style["safe_zone_ratio"]))
    max_width = size[0] - safe * 2
    font_size = int(min(style["font_size_max"], max(style["font_size_min"], size[0] * 0.072)))
    font = ImageFont.truetype(str(font_path), font_size)
    lines = wrap_title(draw, title, font, max_width)
    line_height = font_size * 1.25
    y = safe
    shadow = tuple(style["shadow_offset"])
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font, stroke_width=style["stroke_width"])
        x = (size[0] - (box[2] - box[0])) / 2
        draw.text((x + shadow[0], y + shadow[1]), line, font=font, fill=style["shadow_color"], stroke_width=style["stroke_width"], stroke_fill=style["shadow_color"])
        draw.text((x, y), line, font=font, fill=style["text_color"], stroke_width=style["stroke_width"], stroke_fill=style["stroke_color"])
        y += line_height
    badge = "OFFICIAL" if account_type == "official" else "HOT  CREATOR"
    badge_font = ImageFont.truetype(str(font_path), max(24, font_size // 3))
    badge_box = draw.textbbox((0, 0), badge, font=badge_font)
    bx, by = size[0] - safe - (badge_box[2] - badge_box[0]) - 28, size[1] - safe - 58
    draw.rounded_rectangle((bx - 14, by - 8, size[0] - safe, size[1] - safe), radius=12, fill="#D71920" if account_type == "creator" else "#111827")
    draw.text((bx, by), badge, font=badge_font, fill="white")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=94)
    return output

