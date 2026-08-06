#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts"))
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"): sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def step(name): print(f"\n▶ {name}", flush=True)


def require(condition, message):
    if not condition: raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--fast", action="store_true", help="跳过 Demucs 和 Whisper 模型，仅验证其余真实媒体链路")
    args = parser.parse_args()
    from doctor import find_binary
    ffmpeg = find_binary("ffmpeg"); require(ffmpeg, "找不到 ffmpeg，请先运行 scripts/doctor.py")
    ffprobe = find_binary("ffprobe"); require(ffprobe, "找不到 ffprobe")
    workspace = ROOT / "media" / "smoke_workspace"
    if workspace.exists(): shutil.rmtree(workspace)
    media = workspace / "media"; drama_dir = media / "dramas" / "冒烟测试剧"; episodes = drama_dir / "episodes"; episodes.mkdir(parents=True)
    db_path = workspace / "smoke.db"
    os.environ["MEDIA_ROOT"] = str(media); os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"; os.environ["FFMPEG_BINARY"] = ffmpeg; os.environ["FFPROBE_BINARY"] = ffprobe
    try:
        from sqlmodel import Session, SQLModel, create_engine
        from app.models import Account, Clip, Drama, Post, PublishJob
        from app.schemas import Highlight
        from app.services.audio import replace_background_music
        from app.services.clipper import cut_hook_and_body, make_preview, normalize_vertical
        from app.services.cover import render_cover
        from app.services.drama_library import scan_dramas_with_logs, write_highlights
        from app.services.moderation import check_text
        from app.services.publisher import execute_publish_job
        from app.services.subtitles import burn_subtitles, transcribe
        engine = create_engine(f"sqlite:///{db_path.as_posix()}"); SQLModel.metadata.create_all(engine)

        step("1/9 用真实 ffmpeg 生成 18 秒彩条 + 英文语音测试视频")
        source = episodes / "01.mp4"
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=18", "-f", "lavfi", "-i", "flite=text='She must leave now. Everyone betrayed her. The truth changes everything.'", "-filter_complex", "[1:a]apad=pad_dur=18[a]", "-map", "0:v", "-map", "[a]", "-t", "18", "-c:v", "libx264", "-c:a", "aac", str(source)], check=True, capture_output=True)
        require(source.stat().st_size > 100_000, "测试视频生成失败")

        step("2/9 目录扫描入库并检查可见日志")
        with Session(engine) as session:
            dramas, logs = scan_dramas_with_logs(session, media); require(len(dramas) == 1, f"入库数量错误，日志={logs}")
            require(any(x["status"] == "imported" for x in logs), f"缺少入库日志：{logs}")
            drama = dramas[0]; drama.genres = ["测试"]; drama.source_note = "ffmpeg 自动生成，无版权素材"; session.add(drama); session.commit(); session.refresh(drama)

            step("3/9 写入一个高能点")
            highlight = Highlight(episode="01.mp4", start=1, end=16, note="冒烟测试冲突点")
            write_highlights(drama_dir, [highlight], {"01.mp4"}); require((drama_dir / "highlights.json").exists(), "高能点未写入")

            step("4/9 真实切 hook + body")
            clip = Clip(drama_id=drama.id, template_name="smoke", source_eps=["01.mp4"], source_start=1, source_end=16, current_step="cutting")
            session.add(clip); session.commit(); session.refresh(clip)
            work = workspace / "work"; work.mkdir(); raw = work / "cut.mp4"
            template = {"hook": {"offset": 0, "duration": 3}, "body": {"offset": 3, "duration": 12}, "output": {"width": 1080, "height": 1920, "fps": 25}}
            duration = cut_hook_and_body(ffmpeg, source, 1, template, raw, work / "parts"); require(raw.exists(), "切片文件不存在")

            step("5/9 音频处理")
            bgm_dir = media / "bgm" / "测试"; bgm_dir.mkdir(parents=True); bgm = bgm_dir / "bgm.wav"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=18", str(bgm)], check=True, capture_output=True)
            audio_out = work / "audio.mp4"
            if args.fast:
                shutil.copy2(raw, audio_out); vocals = None; replaced = False
                print("⚠️ --fast：明确跳过 Demucs，保留原音频", flush=True)
            else:
                _, vocals, replaced = replace_background_music(ffmpeg, raw, drama.genres, media, audio_out, work)
                require(replaced, "Demucs/BGM 替换没有成功；请看 doctor 的 Demucs 项")

            step("6/9 字幕、合规、竖屏和六帧预览")
            srt = work / "subtitles.srt"
            if args.fast:
                subtitle_text = "Everyone betrayed her. The truth changes everything."
                srt.write_text("1\n00:00:00,000 --> 00:00:06,000\nEveryone betrayed her.\n\n2\n00:00:06,000 --> 00:00:12,000\nThe truth changes everything.\n", encoding="utf-8")
                print("⚠️ --fast：使用明确标注的本地固定字幕，未冒充 Whisper 结果", flush=True)
            else:
                subtitle_text = transcribe(vocals or audio_out, "small", "cpu", "int8", srt); require(subtitle_text.strip(), "Whisper 未识别出测试语音")
            captioned, clean, preview = work / "captioned.mp4", media / "clips" / "smoke_clean.mp4", media / "clips" / "smoke_preview.jpg"
            clean.parent.mkdir(parents=True); burn_subtitles(ffmpeg, audio_out, srt, captioned); normalize_vertical(ffmpeg, captioned, clean, template); make_preview(ffmpeg, clean, preview, duration)
            hits, _ = check_text(subtitle_text, ROOT / "backend" / "data" / "banned_words.txt")
            clip.duration, clip.file_path, clip.preview_image, clip.subtitle_text, clip.hit_words, clip.audio_replaced, clip.current_step, clip.progress = duration, str(clean), str(preview), subtitle_text, hits, replaced, "completed", 100
            session.add(clip); session.commit(); require(clean.exists() and preview.exists(), "干净版或预览图缺失")

            step("7/9 创建隔离测试成品元数据")
            print("冒烟测试不调用外部生成服务，也不会把测试数据写入正式数据库", flush=True)
            title = "Everyone Betrayed Her—Then She Returned"
            caption = "Smoke-test content.\nFull episodes 👉 link in comments\nAI-generated content #AIGC"
            post = Post(clip_id=clip.id, title=title, caption=caption, hashtags=["#SmokeTest", "#AIGC"], title_formula=3, status="ready", cover_fallback=True)
            session.add(post); session.commit(); session.refresh(post)

            step("8/9 降级封面双规格压字")
            cover_dir = media / "posts" / f"post_{post.id}"; cover169, cover916 = cover_dir / "cover_16x9.jpg", cover_dir / "cover_9x16.jpg"
            style = ROOT / "backend" / "data" / "cover_style.json"
            render_cover(preview, cover169, title, "creator", (1920, 1080), style, ROOT); render_cover(preview, cover916, title, "creator", (1080, 1920), style, ROOT)
            post.cover_path_169, post.cover_path_916 = str(cover169), str(cover916); session.add(post); session.commit()

            step("9/9 验证未连接账号会被真实发布保护拦截")
            account = Account(platform="tiktok", name="冒烟测试达人号", account_type="creator")
            session.add(account); session.commit(); session.refresh(account)
            job = PublishJob(post_id=post.id, account_id=account.id, scheduled_at=datetime.now(), ai_disclosure=True)
            session.add(job); session.commit(); session.refresh(job)
            result = execute_publish_job(session, job)
            require(result.status == "blocked", f"未连接账号未被拦截：{result.status}")
            require(not (media / "packages").exists(), "不应生成本地假发布包")
        print("\n✅ 流水线完整可用", flush=True)
        return 0
    except Exception as exc:
        print(f"\n❌ 冒烟测试失败：{exc}", file=sys.stderr)
        print("上下文：", file=sys.stderr); traceback.print_exc()
        return 1


if __name__ == "__main__": raise SystemExit(main())
