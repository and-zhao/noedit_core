"""NoEdit Core —— 可独立编程调用的 PPT/画布创作核心。

围绕「建工程 → 加页 → 改元素 → 导素材 → 导出」这条闭环，纯 Python、无外部服务依赖。

用法：
    import sys; sys.path.insert(0, r"...\\noedit_core")
    from noedit_core import api
    p = api.create_project("我的演示", parent_dir=r"D:\\demo")
    api.insert(p["path"], {"type": "text", "props": {"text": "标题"}}, page_index=0)
    api.export(p["path"], "pptx")
"""

from __future__ import annotations

__all__ = ["api", "__version__"]

__version__ = "0.1.0"
