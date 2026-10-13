# -*- coding: utf-8 -*-
"""轻量占位引擎：无深度学习依赖（ffmpeg + Pillow）。

对静态照片做缓慢呼吸缩放 + 亮度脉动，并与讲稿音频合并成 MP4。
效果不逼真，但能立即验证「照片 → 视频 → 页面元素 → 导出」全链路。
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile

from ..media import ffmpeg_exe as _ffmpeg_exe, probe_seconds as _probe_seconds
from .base import Engine, EngineError


def _has(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _probe_audio_seconds(audio: str) -> float:
    return _probe_seconds(audio, _ffmpeg_exe())


class LightweightEngine(Engine):
    name = "lightweight"

    def check(self) -> str:
        if not _has("PIL"):
            return "missing Pillow"
        if not _ffmpeg_exe():
            return "missing ffmpeg (install ffmpeg / pip install imageio-ffmpeg)"
        return "ok"

    def generate(self, image: str, audio: str, out_path: str, **kw) -> str:
        status = self.check()
        if status != "ok":
            raise EngineError("lightweight 引擎不可用: %s" % status)
        from PIL import Image, ImageEnhance

        ffmpeg = _ffmpeg_exe()
        fps = int(kw.get("fps", 15))
        duration = float(kw.get("duration", 0)) or _probe_audio_seconds(audio) or 4.0
        w = int(kw.get("width", 480))
        # 高按原图比例算，限制在 480~720
        base = Image.open(image).convert("RGB")
        h = max(480, min(720, int(base.height * w / max(1, base.width))))
        # libx264 + yuv420p 只接受偶数边长，奇数会让 ffmpeg 直接失败
        w -= w % 2
        h -= h % 2
        # 长讲稿按帧数上限降 fps，避免几上千张 PNG 把磁盘和时间吃掉
        max_frames = int(kw.get("max_frames", 1800))
        if duration * fps > max_frames:
            fps = max(5, int(max_frames / max(duration, 0.1)))
        nframes = max(1, int(duration * fps))

        tmp = tempfile.mkdtemp(prefix="dh_light_")
        try:
            for i in range(nframes):
                t = i / fps
                # 呼吸缩放：1.00 ~ 1.03
                scale = 1.0 + 0.015 * (1.0 - math.cos(t * 2 * math.pi / max(duration, 0.1)))
                sw, sh = int(w * scale), int(h * scale)
                frame = base.resize((sw, sh), Image.LANCZOS)
                # 居中裁回目标尺寸
                frame = frame.crop(((sw - w) // 2, (sh - h) // 2,
                                    (sw - w) // 2 + w, (sh - h) // 2 + h))
                # 亮度脉动：0.97 ~ 1.03
                frame = ImageEnhance.Brightness(frame).enhance(
                    1.0 + 0.03 * math.sin(t * 2 * math.pi / max(duration, 0.1)))
                frame.save(os.path.join(tmp, "f%05d.png" % i))

            # 合成：视频流（帧序列）+ 原音频；时长以音频为准（-shortest）
            cmd = [ffmpeg, "-y",
                   "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.png"),
                   "-i", audio,
                   "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-shortest",
                   "-movflags", "+faststart", out_path]
            r = subprocess.run(cmd, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=600)
            if r.returncode != 0 or not os.path.exists(out_path):
                raise EngineError("ffmpeg 合成失败: %s" % r.stderr[-400:])
            return out_path
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def register_self():
    from . import register as _reg
    _reg("lightweight", LightweightEngine)


register_self()
