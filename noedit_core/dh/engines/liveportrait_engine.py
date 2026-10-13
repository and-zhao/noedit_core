# -*- coding: utf-8 -*-
"""LivePortrait 引擎封装（MIT，默认推荐）。

要求：本地克隆 LivePortrait 仓库 + 下载预训练权重，然后设置环境变量
NOEDIT_DH_LIVEPORTRAIT 指向仓库根目录（含 inference.py 与 pretrained_weights）。

生成逻辑：用音频驱动的 neutral 驱动视频不可得时，LivePortrait 本身是「驱动视频 → 动照片」。
与讲稿音频合成的组合：先取驱动视频帧驱动照片 → 输出无声人像视频 → ffmpeg 拼上讲稿音频。
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

from ..media import ffmpeg_exe
from .base import Engine, EngineError


def _has(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _repo_root() -> str:
    return os.environ.get("NOEDIT_DH_LIVEPORTRAIT", "").strip()


class LivePortraitEngine(Engine):
    name = "liveportrait"

    def check(self) -> str:
        if not _has("torch"):
            return "missing torch"
        if not _has("cv2"):
            return "missing opencv-python"
        root = _repo_root()
        if not root or not os.path.isfile(os.path.join(root, "inference.py")):
            return "missing repo (set NOEDIT_DH_LIVEPORTRAIT to LivePortrait checkout)"
        if not os.path.isdir(os.path.join(root, "pretrained_weights")):
            return "missing pretrained_weights (见 dh/README.md 下载说明)"
        return "ok"

    def generate(self, image: str, audio: str, out_path: str, **kw) -> str:
        status = self.check()
        if status != "ok":
            raise EngineError("liveportrait 引擎不可用: %s" % status)
        root = _repo_root()
        # 1) 静态照片 → 人像动画视频（drive_mode=video 时用驱动视频；这里生成一张
        #    由音频时长决定的「微动驱动视频」由 LivePortrait 自带 demo 生成脚本处理，
        #    简化起见调用其 image-to-image 的 still 模式产出轻微微动的视频）。
        tmp_video = out_path + ".silent.mp4"
        started = time.time()
        env = dict(os.environ, PYTHONPATH=root)
        last_err = ""
        # 不同版本 inference.py 的静照模式开关名不一样（新版 --flag_still_mode），
        # 认不出参数就换个名字再试一次，别把用户挡在一条 argparse 报错外面。
        for still_flag in ("--flag_still_mode", "--flag_still"):
            cmd = [os.environ.get("PYTHON", "python"), os.path.join(root, "inference.py"),
                   "-s", image,
                   still_flag, "--flag_relative_motion",
                   "-o", os.path.dirname(out_path)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800, cwd=root, env=env)
            if r.returncode == 0:
                break
            last_err = (r.stderr or r.stdout or "")[-400:]
        else:
            raise EngineError("LivePortrait 推理失败: %s" % last_err)
        # 输出落在 <out>/animations/<源图名>/*.mp4，递归找本次运行新生成的那一个：
        # 只看 mtime 最新会把上一次运行留下的旧视频当成果，宁可报「未产出」。
        cand = [f for f in glob.glob(os.path.join(os.path.dirname(out_path), "**", "*.mp4"),
                                     recursive=True)
                if os.path.abspath(f) not in (os.path.abspath(out_path), os.path.abspath(tmp_video))
                and os.path.getmtime(f) >= started - 2]
        if not cand:
            raise EngineError("LivePortrait 未产出视频（在输出目录里没找到本次新生成的 mp4）")
        silent = max(cand, key=os.path.getmtime)
        shutil.move(silent, tmp_video)

        # 2) 与讲稿音频合并（-shortest 以音频时长为准）
        mrg = [ffmpeg_exe(), "-y", "-i", tmp_video, "-i", audio,
               "-c:v", "copy", "-c:a", "aac", "-shortest",
               "-movflags", "+faststart", out_path]
        try:
            r2 = subprocess.run(mrg, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=600)
        finally:
            try:
                os.remove(tmp_video)
            except OSError:
                pass
        if r2.returncode != 0:
            raise EngineError("ffmpeg 合成失败: %s" % r2.stderr[-400:])
        return out_path


def register(registry):
    registry.register("liveportrait", LivePortraitEngine)


def register_self():
    from . import register as _reg
    _reg("liveportrait", LivePortraitEngine)


register_self()
