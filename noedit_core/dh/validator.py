# -*- coding: utf-8 -*-
"""数字人环境探测：不装重依赖也能先跑轻量档。

用法：
    python -m noedit_core.dh.validator              # 全量探测并打印
    python -m noedit_core.dh.validator --download liveportrait   # 打印该引擎的手动接入步骤
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_lightweight() -> str:
    if not _has_module("PIL"):
        return "missing Pillow"
    if not (_has_ffmpeg() or _has_module("imageio_ffmpeg")):
        return "missing ffmpeg (install ffmpeg / pip install imageio-ffmpeg)"
    return "ok"


def check_liveportrait() -> str:
    from .engines import liveportrait_engine
    return liveportrait_engine.LivePortraitEngine().check()


def check_sadtalker() -> str:
    from .engines import sadtalker_engine
    return sadtalker_engine.SadTalkerEngine().check()


def check_cloud() -> str:
    if not _has_module("requests"):
        return "missing requests"
    from .engines import cloud_engine
    if not cloud_engine.load_config():
        return "no config set (copy cloud_config.example.json -> cloud_config.json)"
    return "ok"


def check_all() -> dict:
    """返回 {engine: 'ok' | 'missing ...'}。至少 lightweight ok 即可开始。"""
    return {
        "lightweight": check_lightweight(),
        "liveportrait": check_liveportrait(),
        "sadtalker": check_sadtalker(),
        "cloud": check_cloud(),
    }


def _print_status():
    status = check_all()
    width = max(len(k) for k in status)
    for k, v in status.items():
        print("%-*s: %s" % (width, k, v))
    return status


def _download_hint(engine: str):
    """本地 GPU 引擎的权重没法替用户下载（各家托管地址会变），给可复制的步骤。"""
    if engine == "liveportrait":
        print("LivePortrait 接入步骤：")
        print("  git clone https://github.com/KlingAIResearch/LivePortrait")
        print("  cd LivePortrait && pip install -r requirements.txt")
        print("  按仓库 README『Pretrained models』一节把权重下到 <仓库>/pretrained_weights/")
        print("  指认仓库：Windows `set NOEDIT_DH_LIVEPORTRAIT=<仓库绝对路径>`，")
        print("            类 Unix `export NOEDIT_DH_LIVEPORTRAIT=<仓库绝对路径>`")
    elif engine == "sadtalker":
        print("SadTalker 接入步骤：")
        print("  git clone https://github.com/OpenTalker/SadTalker")
        print("  cd SadTalker && bash scripts/download_models.sh   # 权重落到 checkpoints/")
        print("  pip install torch torchvision opencv-python（按本机 CUDA 版本选 torch 构建）")
        print("  指认仓库：Windows `set NOEDIT_DH_SADTALKER=<仓库绝对路径>`，")
        print("            类 Unix `export NOEDIT_DH_SADTALKER=<仓库绝对路径>`")
    elif engine in ("lightweight", "cloud"):
        print("%s 不需要下载模型权重：" % engine)
        print("  lightweight: pip install pillow imageio-ffmpeg（或系统装 ffmpeg）")
        print("  cloud: 复制 dh/cloud_config.example.json -> cloud_config.json 填 key；"
              "注意桥接分支尚未接入，dh_status 会如实回报")
    else:
        print("未知引擎:", engine, "（可选: lightweight / liveportrait / sadtalker / cloud）")
    if engine in ("liveportrait", "sadtalker"):
        print("装好后重跑 `python -m noedit_core.dh.validator` 确认状态变成 ok。")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--download":
        _download_hint(argv[1] if len(argv) > 1 else "")
        return 0
    _print_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
