"""核心错误类型。

所有 API 抛出的都是普通异常；调用方直接读 str(exc) 即可展示给用户。
"""

from __future__ import annotations


class CoreError(Exception):
    """可以原样展示给用户/模型的错误（路径不存在、定位不到元素、动作不支持等）。"""


#: actions.py 内部沿用的旧名字，等价于 CoreError。
McpError = CoreError
