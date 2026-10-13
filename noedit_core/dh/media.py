# -*- coding: utf-8 -*-
"""音视频小工具：时长探测 + 封面帧抽取。

数字人在 PPTX / PDF / PNG 里只能以静态封面帧呈现，而 Agent 直接调 API 建工程时
没有人替它抓帧——过去只能落深色兜底图，或者把 mp4 路径误写进 props.poster
（结果封面根本打不开）。这一段补在这里，生成与导出两侧都能用。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from .engines.base import EngineError


def ffmpeg_exe() -> str:
    """优先系统 ffmpeg；没有则用 imageio-ffmpeg 捆绑二进制；都没有返回空串。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def probe_seconds(path: str, ffmpeg: Optional[str] = None) -> float:
    """探音视频时长（秒）：先 ffprobe，再退回解析 ffmpeg 的 Duration 行；拿不到返回 0。"""
    ffmpeg = ffmpeg if ffmpeg is not None else ffmpeg_exe()
    probe = shutil.which("ffprobe")
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=30)
            return float(out.stdout.strip())
        except Exception:
            pass
    if not ffmpeg:
        return 0.0
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out.stderr or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def extract_poster(video: str, out_path: str = "", at_sec: float = 0.5) -> str:
    """从视频取一帧存成 JPG 封面，返回输出绝对路径。失败抛 EngineError。

    at_sec 处的帧取不到（首段损坏 / 关键帧稀疏）会退回 0 秒再试一次。
    """
    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        raise EngineError("缺少 ffmpeg（装 ffmpeg 或 pip install imageio-ffmpeg）")
    video = str(video)
    out = os.path.abspath(out_path or (os.path.splitext(video)[0] + "_poster.jpg"))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    duration = probe_seconds(video, ffmpeg)
    start = min(max(0.0, float(at_sec or 0)), max(0.0, duration - 0.1)) if duration else max(0.0, float(at_sec or 0))
    err = ""
    for ss in ([start, 0.0] if start > 0 else [0.0]):
        try:
            r = subprocess.run(
                [ffmpeg, "-y", "-ss", "%.3f" % ss, "-i", video,
                 "-frames:v", "1", "-q:v", "3", out],
                capture_output=True, text=True, timeout=120)
            err = (r.stderr or r.stdout or "")[-300:]
            if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                return out
        except Exception as exc:
            err = str(exc)
    raise EngineError("封面帧抽取失败: %s" % err)
