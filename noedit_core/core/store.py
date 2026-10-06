"""工程读写：读 → 改 → 写 的标准通路。

把「找工程根目录 / 读 manifest / 持锁改 / 原子写回 + 刷新 index.html」收在一处，
是 core 内部唯一的落盘入口。不维护最近工程，也不持久化设置。
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from . import projects as projects_mod
from .errors import CoreError
from .paths import CANVAS_HTML_NAME, MANIFEST_NAME, ensure_dir


def project_root(path: str | Path) -> Path:
    """把入参规整成工程文件夹；指向 manifest 文件时取其父目录。"""
    raw = str(path or "").strip()
    if not raw:
        raise CoreError("缺少工程路径 path")
    target = Path(raw).expanduser().resolve()
    if target.is_file():
        target = target.parent
    if not (target / MANIFEST_NAME).exists():
        raise CoreError(f"不是有效的工程文件夹（缺少 {MANIFEST_NAME}）：{target}")
    return target


def read_manifest(root: Path) -> dict:
    file = root / MANIFEST_NAME
    if not file.exists():
        raise CoreError(f"工程缺少 {MANIFEST_NAME}：{root}")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoreError(f"工程文件不是合法 JSON：{exc}") from exc
    return projects_mod.normalize_manifest(data)


@contextmanager
def project_lock(root: str | Path, timeout: float = 30.0):
    """工程级互斥：实现归 core/projects.py，这里把超时翻译成可展示的错误。"""
    try:
        with projects_mod.project_lock(root, timeout=timeout):
            yield
    except TimeoutError as exc:
        raise CoreError(str(exc)) from exc


@contextmanager
def edit_project(path: str | Path):
    """读 → 改 的通路（全程持锁）；yield (root, manifest)，调用方改完必须走 write_manifest。"""
    root = project_root(path)
    with project_lock(root):
        manifest = read_manifest(root)
        yield root, manifest


def write_manifest(root: Path, manifest: dict, refresh_html: bool = True) -> dict:
    """规范化 → 刷新 updatedAt → 剔除已丢失的素材记录 → 原子写 manifest → 按需重写 index.html。

    调用方应已在 project_lock(root) 内（用 mutate() 即自动满足）。
    """
    manifest = projects_mod.normalize_manifest(manifest)
    manifest["updatedAt"] = int(time.time() * 1000)

    valid = []
    for item in manifest.get("assets", []):
        rel = item.get("relPath", "")
        if rel and (root / rel).exists():
            item["size"] = (root / rel).stat().st_size
            valid.append(item)
    manifest["assets"] = valid

    ensure_dir(root)
    projects_mod.atomic_write_text(
        root / MANIFEST_NAME,
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    if refresh_html:
        projects_mod.atomic_write_text(
            root / CANVAS_HTML_NAME, projects_mod.render_static_html(manifest)
        )
    return manifest


def mutate(path: str | Path, fn, *, refresh_html: bool = True):
    """读 → 改 → 写（全程持锁）。fn(manifest) 就地修改，可返回要并入结果的 extra 字段。"""
    root = project_root(path)
    with project_lock(root):
        manifest = read_manifest(root)
        extra = fn(manifest) or {}
        write_manifest(root, manifest, refresh_html=refresh_html)
        return root, manifest, extra
