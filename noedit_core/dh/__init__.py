# -*- coding: utf-8 -*-
"""数字人播报模块（可选，可拆分）。不安装重依赖时核心照常运行，本模块探测式降级。

快速上手见 dh/README.md；引擎探测见 dh/validator.py；生成入口见 dh/generator.py。
注意：validator / generator 惰性导入（支持 python -m noedit_core.dh.validator 直跑）。
"""
from __future__ import annotations

import importlib

__all__ = ["validator", "generator", "is_available"]


def _lazy(name):
    mod = importlib.import_module("noedit_core.dh." + name)
    globals()[name] = mod          # 缓存，后续不再走 __getattr__
    return mod


def __getattr__(name):
    if name in ("validator", "generator"):
        return _lazy(name)
    raise AttributeError(name)


def is_available() -> bool:
    """模块永远可 import；返回 True 表示至少有一个引擎可用（含 lightweight）。"""
    try:
        status = _lazy("validator").check_all()
        return any(v == "ok" for v in status.values())
    except Exception:
        return False
