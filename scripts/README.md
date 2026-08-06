# 运维与验收脚本

- `doctor.py`：中文环境体检，失败项附修复命令。
- `download_models.py`：主动下载 Whisper small 与 Demucs 模型并显示进度。
- `smoke_test.py`：使用真实 ffmpeg 媒体跑完整 P0 回归；`--fast` 仅跳过 Demucs。

