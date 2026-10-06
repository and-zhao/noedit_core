"""把 NoEdit Core 打成一个自包含的 Agent Skill（别人可直接添加）。

用法：
    python packaging/build_skill.py

产物：
    dist/noedit-core/            # 装进 <skills 根>/noedit-core/ 即可用
    dist/noedit-core-skill.zip   # 整包分发（解压后把 noedit-core/ 放到 skills 根下）

skill 目录内容：
    SKILL.md            frontmatter 的 name 必须等于目录名（= noedit-core）
    references/*.md     按需加载的长文档
    main.py             入口：python main.py <子命令>
    noedit_core/        Python 包（排除 data/ 与各类缓存）
    img/logo.svg

运行数据默认落用户目录（~/.noedit_core）：
    打包时在 noedit_core/__init__.py 里注入一段前奏，把
    NOEDIT_CORE_ROOT 默认指向用户目录。于是 data/（settings.json、ui.json、
    locks）不会写进 skill 安装目录——安装目录可能只读，且不该被运行数据污染。
    默认工程目录不在这里定：由 noedit_core/core/paths.py 的 projects_root() 自动获取，
    = 与 skill 文件夹**同级**的 noedit_core/（跟着 skill 装到哪就跟到哪）。
    想改落点，运行前设 NOEDIT_CORE_ROOT / NOEDIT_CORE_PROJECTS 覆盖即可
    （用 setdefault，显式设置优先）；界面上用户设过「默认目录」也以用户设置为准。
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

SKILL_NAME = "noedit-core"
# 开发仓库里 skill 放在 skill/ 下；打包后目录名要等于 frontmatter 的 name。
SRC_SKILL_DIR = "skill"
PACKAGE_DIR = "noedit_core"

# 复制包时要排除的内容：运行数据与各种缓存都不进包。
#   data/          运行数据（settings.json / ui.json / locks / cache）→ 落用户目录
#   __pycache__    字节码缓存
#   *.pyc / *.pyo  同上
COPY_IGNORE = shutil.ignore_patterns(
    "data", "__pycache__", ".pytest_cache", "*.pyc", "*.pyo"
)

# 注入到 noedit_core/__init__.py 的前奏：放在 `from __future__` 之后、
# 其余 import 之前，保证在 core.paths 读环境变量之前生效。
PRELUDE = '''\
# --- 自包含 skill 打包注入：可写数据默认落用户目录（源码仓库版不含本段）---
import os as _os
from pathlib import Path as _Path

# 运行数据（settings.json / ui.json / locks）统一落用户主目录：
# skill 安装目录可能只读，也不该被运行数据污染。显式设了环境变量则以显式为准。
_os.environ.setdefault("NOEDIT_CORE_ROOT", str(_Path.home() / ".noedit_core"))
del _os, _Path
'''


def _repo_root() -> Path:
    """本脚本在 <repo>/packaging/ 下，仓库根 = 上一级。"""
    return Path(__file__).resolve().parent.parent


def _inject_prelude(init_file: Path) -> None:
    """把环境前奏插到 `from __future__ import annotations` 之后（它必须是首句）。"""
    text = init_file.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if anchor not in text:
        raise RuntimeError(f"{init_file} 里找不到 {anchor!r}，无法注入环境前奏")
    init_file.write_text(text.replace(anchor, anchor + "\n" + PRELUDE, 1), encoding="utf-8")


def _read_skill_name(skill_md: Path) -> str:
    """从 frontmatter 里取 name（用于校验目录名是否与之一致）。"""
    for line in skill_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"{skill_md} 的 frontmatter 缺少 name")


def _zip_dir(src: Path, zip_path: Path) -> None:
    """把 dist/<name>/ 压成 zip，包内顶层就是 <name>/。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src.parent).as_posix())


def build() -> Path:
    root = _repo_root()
    dist = root / "dist"
    out = dist / SKILL_NAME

    # 1) 清空旧产物
    if dist.exists():
        shutil.rmtree(dist)
    out.mkdir(parents=True)

    # 2) skill 规则手册 + 按需加载的长文档
    shutil.copy2(root / SRC_SKILL_DIR / "SKILL.md", out / "SKILL.md")
    shutil.copytree(root / SRC_SKILL_DIR / "references", out / "references")

    # 3) 入口脚本
    shutil.copy2(root / "main.py", out / "main.py")

    # 4) Python 包（排除运行数据与缓存），再注入环境前奏
    shutil.copytree(root / PACKAGE_DIR, out / PACKAGE_DIR, ignore=COPY_IGNORE)
    _inject_prelude(out / PACKAGE_DIR / "__init__.py")

    # 5) 图标资源。
    #    注意：不带 README——它们是开发仓库文档，里面的 `skill/references/...`
    #    相对链接在打包后的目录里不存在，带上反而误导；skill 的权威说明是 SKILL.md。
    shutil.copytree(root / "img", out / "img")

    # 6) 校验：frontmatter 的 name 必须等于目录名（skill 规范的硬要求）
    declared = _read_skill_name(out / "SKILL.md")
    if declared != out.name:
        raise RuntimeError(f"frontmatter name={declared!r} 与目录名 {out.name!r} 不一致")

    # 7) 打 zip
    _zip_dir(out, dist / f"{SKILL_NAME}-skill.zip")
    return out


def main() -> int:
    out = build()
    rel = out.relative_to(_repo_root()).as_posix()
    n = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"[ok] {rel}/  ({n} files)")
    print(f"[ok] dist/{SKILL_NAME}-skill.zip")
    print(f"     装法：把 {SKILL_NAME}/ 整个放到 skills 根下，例如")
    print(f"       ~/.trae-cn/skills/{SKILL_NAME}/   (全局)")
    print(f"       <项目>/.trae/skills/{SKILL_NAME}/ (项目级)")
    print("     运行数据默认落 ~/.noedit_core/；默认工程目录 = 与 skill 同级的 noedit_core/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
