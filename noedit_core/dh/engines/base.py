# -*- coding: utf-8 -*-
"""引擎抽象基类：generate(image, audio, out_path, **kw) -> out_path。"""
from __future__ import annotations

import abc


class EngineError(RuntimeError):
    """引擎不可用 / 生成失败。"""


class Engine(abc.ABC):
    """所有数字人引擎实现同一契约：

    - check()      -> str    环境是否可用："ok" 或缺失说明
    - generate(...) -> str   生成成功返回输出视频绝对路径
    """

    name: str = "base"

    @abc.abstractmethod
    def check(self) -> str:
        """返回 'ok' 或缺失依赖说明。"""

    @abc.abstractmethod
    def generate(self, image: str, audio: str, out_path: str, **kw) -> str:
        """输入照片 + 讲稿音频，生成口型/动画视频，返回 out_path。"""
