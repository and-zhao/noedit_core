"""NoEdit Core 命令行入口（任意工作目录都能跑）。

    python main.py <子命令> ...

等价于 `python -m noedit_core.cli`，只是省去了设置 PYTHONPATH 的麻烦。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from noedit_core.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
