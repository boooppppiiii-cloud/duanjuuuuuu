import json
import math
import re
import subprocess
from pathlib import Path


def media_duration(ffprobe: str, source: Path) -> float:
    result=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration","-of","json",str(source)],capture_output=True,text=True,encoding="utf-8",errors="replace")
    if result.returncode: raise RuntimeError(result.stderr[-1000:])
    return float(json.loads(result.stdout)["format"]["duration"])


def loudness_peaks(ffmpeg: str, source: Path) -> list[tuple[float,float]]:
    result=subprocess.run([ffmpeg,"-hide_banner","-nostats","-loglevel","verbose","-i",str(source),"-af","ebur128=framelog=verbose","-f","null","NUL"],capture_output=True,text=True,encoding="utf-8",errors="replace")
    pattern=re.compile(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+)")
    frames=[(float(t),float(level)) for t,level in pattern.findall(result.stderr) if float(level)>-70]
    ranked=[]
    for i in range(1,len(frames)):
        jump=frames[i][1]-frames[i-1][1]
        if jump>2 and math.isfinite(jump): ranked.append((frames[i][0],jump))
    return sorted(ranked,key=lambda x:x[1],reverse=True)


def subtitle_emotions(source: Path, words: list[str], model_name: str, device: str, compute_type: str) -> list[tuple[float,int,list[str]]]:
    from faster_whisper import WhisperModel
    model=WhisperModel(model_name,device=device,compute_type=compute_type)
    segments,_=model.transcribe(str(source),vad_filter=True)
    found=[]
    for seg in segments:
        hits=[word for word in words if word and word in seg.text]
        if hits: found.append((float(seg.start),len(hits),hits))
    return found
