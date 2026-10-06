"""「最近工程 / 设置」接口的空实现。

projects.py 落盘时会调用这几个函数；本核心不维护最近工程、也不持久化设置，
故留三个空实现保持接口形状，避免引入额外依赖。

- push_recent：空实现，不写最近工程列表。
- get_settings：恒返回空字典。
- save_settings：原样返回，不落盘。
"""

from __future__ import annotations


def push_recent(*_args, **_kwargs) -> None:
    """空实现：本核心不维护最近工程列表。"""
    return None


def get_settings() -> dict:
    """空实现：本核心不持久化设置，恒返回空字典。"""
    return {}


def save_settings(data: dict) -> dict:
    """空实现：原样返回，不落盘。"""
    return data or {}
