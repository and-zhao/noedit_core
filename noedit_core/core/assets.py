"""素材处理：工程内 assets 复制、相对路径转换、素材类型识别。

规则（5.x）：
- 导入项目的素材一律复制到 <project>/assets 下，形成工程内副本
- 传给大模型的素材地址统一为工程内相对路径，绝不传本地绝对路径
- 全局素材库只保存引用地址，不复制本体
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

from .paths import (
    ASSETS_DIR_NAME,
    AUDIO_EXT,
    CODE_EXT,
    IMAGE_EXT,
    TABLE_EXT,
    VIDEO_EXT,
    ensure_dir,
)


def _now() -> int:
    return int(time.time() * 1000)


def kind_of(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in TABLE_EXT:
        return "table"
    if ext in CODE_EXT:
        return "code"
    return "file"


def assets_dir(project_dir: str | Path) -> Path:
    return ensure_dir(Path(project_dir) / ASSETS_DIR_NAME)


def _unique_target(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = directory / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


_SVG_OPEN = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_SVG_MAX_BYTES = 4 * 1024 * 1024


def stretch_svg(path: Path) -> None:
    """给工程内的 SVG 素材补上 `preserveAspectRatio="none"`，让它能像 PNG 一样被拉伸变形。

    SVG 只要带 viewBox，默认就是 `xMidYMid meet`：放进 `<img>` 里拉边框只会居中留边，
    而画布上的其它图片（object-fit:fill）是真的拉伸压缩，两者手感不一致。改成 none 后
    行为才统一 —— 它只在非等比拉伸时有区别，天然尺寸下比例相同，渲染结果不变。
    原作者自己写了 preserveAspectRatio 的就不动，尊重他的意图；非 UTF-8 / 过大 / 解析不出
    根节点的也一律跳过，宁可保持原样也不写坏素材。
    """
    if path.suffix.lower() != ".svg":
        return
    try:
        if path.stat().st_size > _SVG_MAX_BYTES:
            return
        raw = path.read_bytes()
    except OSError:
        return
    encoding = "utf-8-sig" if raw[:3] == b"\xef\xbb\xbf" else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        return
    m = _SVG_OPEN.search(text)
    if not m or "preserveAspectRatio" in m.group(0):
        return
    tag = m.group(0)
    fixed = text[: m.start()] + tag[:4] + ' preserveAspectRatio="none"' + tag[4:] + text[m.end():]
    try:
        path.write_bytes(fixed.encode(encoding))
    except OSError:
        pass


def import_assets(project_dir: str | Path, source_paths: list[str]) -> list[dict]:
    """把外部素材复制进工程 assets 目录，返回工程内素材记录列表。"""
    directory = assets_dir(project_dir)
    out: list[dict] = []
    for raw in source_paths or []:
        src = Path(raw)
        if not src.exists() or not src.is_file():
            continue
        target = _unique_target(directory, src.name)
        shutil.copy2(src, target)
        stretch_svg(target)
        out.append(_record(target, str(src)))
    return out


def import_asset_bytes(project_dir: str | Path, filename: str, data: bytes) -> dict:
    """把内存里的一段字节（从剪贴板粘贴进来的图片）写进工程 assets 目录。

    粘贴来源只有字节、没有磁盘路径，所以走不了 import_assets 的复制路径。
    """
    directory = assets_dir(project_dir)
    name = Path(str(filename or "")).name or "pasted.png"
    target = _unique_target(directory, name)
    target.write_bytes(data)
    stretch_svg(target)
    return _record(target, "paste")


def _record(target: Path, origin: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": target.name,
        "relPath": f"{ASSETS_DIR_NAME}/{target.name}",
        "kind": kind_of(target),
        "size": target.stat().st_size,
        "addedAt": _now(),
        "origin": origin,
    }


_ILLEGAL_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """清掉文件名里的非法字符与首尾空白，空名或只剩点时返回空串。"""
    cleaned = _ILLEGAL_NAME.sub("_", str(name or "")).strip()
    return "" if cleaned.strip(".") == "" else cleaned


def rename_asset(project_dir: str | Path, rel_path: str, new_name: str) -> dict:
    """重命名工程内素材文件，返回更新后的记录（含新的 name / relPath）。

    调用方拿到新 relPath 后要同步替换引用它的元素 src。
    """
    directory = assets_dir(project_dir)
    src = (Path(project_dir) / rel_path).resolve()
    if not src.is_file():
        raise FileNotFoundError("素材不存在")
    clean = sanitize_filename(new_name)
    if not clean:
        raise ValueError("名称不能为空")
    if not Path(clean).suffix:            # 用户没带后缀：沿用原后缀，避免类型丢失
        clean += src.suffix
    if clean == src.name:
        record = _record(src, "rename")
        record["oldRelPath"] = rel_path
        return record
    target = _unique_target(directory, clean)
    src.rename(target)
    record = _record(target, "rename")
    record["oldRelPath"] = rel_path
    return record


def remove_assets(project_dir: str | Path, rel_paths: list[str]) -> list[str]:
    """删除工程内素材文件，返回实际删掉的 relPath 列表（文件不在也算删过引用）。"""
    root = Path(project_dir)
    removed: list[str] = []
    for rel in rel_paths or []:
        p = (root / rel).resolve()
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            continue
        removed.append(rel)
    return removed


def to_relative(project_dir: str | Path, abs_path: str) -> str | None:
    """把工程内文件的绝对路径转换为相对路径；工程外则返回 None。"""
    try:
        return Path(abs_path).resolve().relative_to(Path(project_dir).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def resolve_relative(project_dir: str | Path, rel_path: str) -> Path:
    return (Path(project_dir) / rel_path).resolve()


def sanitize_for_model(assets: list[dict]) -> list[dict]:
    """只向模型暴露工程内相对路径。"""
    safe = []
    for a in assets or []:
        rel = a.get("relPath") or ""
        if not rel or Path(rel).is_absolute():
            continue
        safe.append(
            {
                "name": a.get("name", ""),
                "relPath": rel,
                "kind": a.get("kind", "file"),
                "size": a.get("size", 0),
            }
        )
    return safe
