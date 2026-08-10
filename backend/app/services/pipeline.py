import shutil
import threading
import logging
from pathlib import Path

from sqlmodel import Session, select

from ..config import get_settings
from ..database import engine
from ..models import Clip, Drama
from ..schemas import Highlight
from .audio import replace_background_music
from .clipper import cut_hook_and_body, load_template, make_preview, normalize_vertical
from .drama_library import read_highlights
from .subtitles import burn_subtitles, transcribe
from .moderation import check_text

STEPS = {"cutting": 10, "audio": 30, "subtitles": 50, "formatting": 75, "preview": 90, "completed": 100}
logger = logging.getLogger(__name__)


def advice_for_error(error: Exception) -> str:
    text = str(error).casefold()
    if "ffmpeg" in text or "no such file" in text: return "请运行 python scripts/doctor.py，按提示安装 ffmpeg 并确认视频路径存在。"
    if "whisper" in text or "model" in text: return "请按 doctor 提示下载 Whisper 模型，确认服务器可访问模型源。"
    if "subtitle" in text or "font" in text: return "请检查字幕内容和中文字体文件，然后重试任务。"
    return "请展开详细日志，修复首个报错后重新创建切片；如无法判断，请提供 logs/app.log。"


class SerialPipeline:
    """进程内单消费者锁，确保 Demucs 不会并发吃满 CPU。"""

    def __init__(self):
        self._lock = threading.Lock()

    def process_queued(self) -> None:
        # 后到的批次等待前一消费者结束，避免极窄竞争窗口造成任务遗留。
        self._lock.acquire()
        try:
            while True:
                with Session(engine) as session:
                    clip = session.exec(select(Clip).where(Clip.current_step == "queued").order_by(Clip.id)).first()
                    if not clip:
                        break
                    clip.current_step = "starting"
                    clip.progress = 1
                    session.add(clip); session.commit()
                    clip_id = clip.id
                self.process_one(clip_id)
        finally:
            self._lock.release()

    def _update(self, session: Session, clip: Clip, step: str) -> None:
        clip.current_step = step
        clip.progress = STEPS.get(step, clip.progress)
        session.add(clip); session.commit(); session.refresh(clip)

    def process_one(self, clip_id: int) -> None:
        settings = get_settings()
        with Session(engine) as session:
            clip = session.get(Clip, clip_id)
            if not clip:
                return
            drama = session.get(Drama, clip.drama_id)
            try:
                if not drama:
                    raise ValueError("剧目不存在")
                highlight = Highlight(episode=clip.source_eps[0], start=clip.source_start, end=clip.source_end, note="")
                source = Path(drama.file_dir) / "episodes" / highlight.episode
                template_path = Path(__file__).parents[2] / "data" / "templates" / f"{clip.template_name}.json"
                template = load_template(template_path)
                work = settings.media_root / "clips" / f"clip_{clip.id}_work"
                work.mkdir(parents=True, exist_ok=True)
                raw, audio, captioned, clean = (work / name for name in ("cut.mp4", "audio.mp4", "captioned.mp4", "clean.mp4"))

                self._update(session, clip, "cutting")
                clip.duration = cut_hook_and_body(settings.ffmpeg_binary, source, highlight.start, template, raw, work / "parts")
                self._update(session, clip, "audio")
                _, vocal_track, clip.audio_replaced = replace_background_music(settings.ffmpeg_binary, raw, drama.genres, settings.media_root, audio, work)
                self._update(session, clip, "subtitles")
                srt = work / "subtitles.srt"
                clip.subtitle_text = transcribe(vocal_track or audio, settings.whisper_model, settings.whisper_device, settings.whisper_compute_type, srt)
                clip.hit_words, _ = check_text(clip.subtitle_text, Path(__file__).parents[2] / "data" / "banned_words.txt")
                burn_subtitles(settings.ffmpeg_binary, audio, srt, captioned)
                self._update(session, clip, "formatting")
                normalize_vertical(settings.ffmpeg_binary, captioned, clean, template)
                final_dir = settings.media_root / "clips"
                final_dir.mkdir(parents=True, exist_ok=True)
                final = final_dir / f"clip_{clip.id}_clean.mp4"
                shutil.copy2(clean, final)
                self._update(session, clip, "preview")
                preview = final_dir / f"clip_{clip.id}_preview.jpg"
                make_preview(settings.ffmpeg_binary, final, preview, clip.duration)
                clip.file_path, clip.preview_image = str(final), str(preview)
                clip.status = "blocked" if clip.hit_words else "pending"
                clip.error_message = ""
                self._update(session, clip, "completed")
            except Exception as exc:
                logger.exception("剪辑任务失败 clip_id=%s step=%s", clip.id, clip.current_step)
                clip.status = "blocked"
                clip.current_step = "failed"
                clip.error_message = str(exc)[-2000:]
                clip.error_advice = advice_for_error(exc)
                session.add(clip); session.commit()


pipeline = SerialPipeline()


def create_clip_records(session: Session, drama: Drama, template_name: str, owner_user_id: int | None = None) -> list[Clip]:
    highlights = read_highlights(Path(drama.file_dir))
    clips: list[Clip] = []
    for item in highlights:
        clip = Clip(drama_id=drama.id, template_name=template_name, source_eps=[item.episode], source_start=item.start, source_end=item.end, owner_user_id=owner_user_id)
        session.add(clip); clips.append(clip)
    session.commit()
    for clip in clips: session.refresh(clip)
    return clips
