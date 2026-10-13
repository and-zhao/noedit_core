# -*- coding: utf-8 -*-
"""引擎注册表：generator 按名字或 auto 顺序取引擎。"""
from __future__ import annotations

from typing import Callable, Dict

from .base import Engine

_ENGINES: Dict[str, Callable[[], Engine]] = {}


def register(name: str, factory: Callable[[], Engine]):
    _ENGINES[name] = factory


def get(name: str) -> Engine:
    _ensure_loaded()
    if name not in _ENGINES:
        raise KeyError("未知数字人引擎: %s（可选: %s）" % (name, ", ".join(sorted(_ENGINES))))
    return _ENGINES[name]()


def names() -> list:
    _ensure_loaded()
    return sorted(_ENGINES)


_EXPECTED = {"lightweight", "liveportrait", "sadtalker", "cloud"}


def import_all():
    """导入各引擎模块并触发注册（各模块在文件尾自动注册）。"""
    from . import lightweight_engine  # noqa: F401
    from . import liveportrait_engine  # noqa: F401
    from . import sadtalker_engine  # noqa: F401
    from . import cloud_engine  # noqa: F401


def _ensure_loaded():
    # 不能用 `if not _ENGINES`：validator.check_all() 可能已单独触发部分引擎注册
    if _EXPECTED - set(_ENGINES):
        import_all()


def auto_pick(available_fn) -> str:
    """按效果优先级返回第一个可用的引擎名：liveportrait → sadtalker → lightweight。"""
    order = fallback_order(available_fn)
    return order[0] if order else ""


def fallback_order(available_fn) -> list:
    """按效果优先级列出所有可用引擎，供 generator 在运行期失败时逐个降级。"""
    _ensure_loaded()
    return [name for name in ("liveportrait", "sadtalker", "lightweight")
            if name in _ENGINES and available_fn(name) == "ok"]
