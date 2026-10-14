# -*- coding: utf-8 -*-
"""生成入口：generate(image, audio, engine="auto") → 输出视频路径 + 封面帧。

engine="auto" 按效果优先级探测：liveportrait → sadtalker → lightweight；
选中的引擎跑一半失败（GPU 缺失、依赖版本不兼容等探测不出来的问题）会**自动降级
到下一档重试**，而不是直接抛错。全部不可用则抛错并列出各引擎缺失项。
"""
from __future__ import annotations

import os
from typing import Optional

from .engines import fallback_order, get
from .engines.base import EngineError
from . import media, validator


def _looks_like_video(path: str) -> str:
    """产物体检：像一段能放的返回 ''，否则返回问题描述。"""
    if not os.path.isfile(path):
        return "引擎没产出文件"
    size = os.path.getsize(path)
    if size < 2048:
        return "产出文件只有 %d 字节，不像是视频" % size
    seconds = media.probe_seconds(path)
    if seconds and seconds < 0.2:
        return "产出视频时长只有 %.2f 秒" % seconds
    return ""


def _poster_for(video: str) -> str:
    """尽力抽一张封面帧；抽不到不影响主流程（导出侧还有深色兜底图）。"""
    try:
        return media.extract_poster(video, at_sec=0.5)
    except Exception:
        return ""


def generate(image: str, audio: str, engine: str = "auto", out_dir: Optional[str] = None,
             out_name: Optional[str] = None, poster: bool = True, **kw) -> dict:
    """输入真人照片 + 讲稿音频，生成数字人播报视频。

    参数：
        image    : 真人正脸照片路径（png/jpg）
        audio    : 讲稿音频路径（wav/mp3）
        engine   : "auto"（可用引擎按优先级逐个尝试）| "liveportrait" | "sadtalker" | "lightweight" | "cloud"
        out_dir  : 输出目录（默认与音频同目录）
        out_name : 输出文件名（默认 <照片名>_<音频名>.mp4）
        poster   : 是否顺带抽一张封面帧 JPG（默认 True）
        **kw     : 透传给引擎（lightweight 支持 fps/width/duration 等）

    返回：
        {"video": 输出绝对路径, "engine": 实际使用的引擎,
         "poster": 封面帧路径或空串, "tried": [尝试过的引擎]}
    """
    if not os.path.isfile(image):
        raise EngineError("照片不存在: %s" % image)
    if not os.path.isfile(audio):
        raise EngineError("音频不存在: %s" % audio)

    out_dir = out_dir or os.path.dirname(os.path.abspath(audio)) or "."
    os.makedirs(out_dir, exist_ok=True)
    if not out_name:
        stem_img = os.path.splitext(os.path.basename(image))[0]
        stem_aud = os.path.splitext(os.path.basename(audio))[0]
        out_name = ("%s_%s.mp4" % (stem_img[:24], stem_aud[:24])).replace(" ", "_")
    elif not out_name.lower().endswith((".mp4", ".mov", ".webm", ".gif")):
        out_name += ".mp4"        # ffmpeg 靠扩展名选 muxer，缺了会直接报 Invalid argument
    out_path = os.path.join(out_dir, out_name)

    status = validator.check_all()
    tried = []
    if engine == "auto":
        order = fallback_order(lambda n: status.get(n, ""))
        if not order:
            missing = "\n".join("  %-12s %s" % (k, v) for k, v in status.items())
            raise EngineError("没有可用的数字人引擎。各引擎状态：\n%s\n"
                              "最简单：pip install pillow imageio-ffmpeg 后用 lightweight 引擎。" % missing)
    else:
        if status.get(engine) and status[engine] != "ok":
            raise EngineError("引擎 %s 不可用: %s" % (engine, status[engine]))
        order = [engine]

    failures = []
    for name in order:
        tried.append(name)
        try:
            result = get(name).generate(image, audio, out_path, **kw)
            problem = _looks_like_video(result)
            if problem:
                raise EngineError(problem)
        except Exception as exc:                      # 运行期炸了就降级下一档
            failures.append("%s: %s" % (name, exc))
            continue
        return {"video": os.path.abspath(result), "engine": name,
                "poster": _poster_for(result) if poster else "",
                "tried": tried,
                "note": "已降级: " + " | ".join(failures) if failures else ""}

    raise EngineError("数字人视频生成失败（尝试过 %s）：\n%s\n"
                      "换 engine=\"auto\" 让它自动降级，或按 README 装依赖后用 lightweight 档。"
                      % (", ".join(tried), "\n".join(failures)))
