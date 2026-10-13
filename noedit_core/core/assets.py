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


_MIN_IMAGE_SIDE = 48          # 短边小于这个数，基本是缩略图 / 图标，放大到版面上必糊
_DOWNLOAD_TIMEOUT = 20
_DOWNLOAD_RETRIES = 3
# 浏览器 UA：图床对裸 UA 的请求常返回 403，带 UA 命中率明显更高
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 noedit-core")
_MAGIC_EXT = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"),
              (b"GIF8", ".gif"), (b"BM", ".bmp"))
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


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
    """把外部素材复制进工程 assets 目录，返回工程内素材记录列表。

    需要知道「哪些文件没进来」时请用 import_assets_report；本函数只给记录，
    保持老调用方的形状不变。
    """
    return import_assets_report(project_dir, source_paths)[0]


def import_assets_report(project_dir: str | Path,
                         source_paths: list[str]) -> tuple[list[dict], list[dict]]:
    """把外部素材复制进工程 assets 目录，返回 (记录列表, 问题列表)。

    问题列表逐项写明哪个源文件没进来（路径不存在 / 不是文件 / 图片解不开 / 复制失败），
    以及进来的图有什么毛病（缩略图尺寸告警）。搜图与生图拿到的路径经常对不上，
    静默跳过只会让页面上凭空少一张图，所以这里一律把原因吐回去。
    """
    directory = assets_dir(project_dir)
    out: list[dict] = []
    problems: list[dict] = []
    for raw in source_paths or []:
        src = Path(str(raw))
        if not src.is_file():
            problems.append({"source": str(raw), "reason": "文件不存在或不是文件", "imported": False})
            continue
        fatal, warn = inspect_image(src)
        if fatal:
            problems.append({"source": str(raw), "reason": fatal, "imported": False})
            continue
        if warn:
            problems.append({"source": str(raw), "reason": warn, "imported": True})
        try:
            target = _unique_target(directory, src.name)
            shutil.copy2(src, target)
        except OSError as exc:
            problems.append({"source": str(raw), "reason": "复制失败: %s" % exc, "imported": False})
            continue
        stretch_svg(target)
        out.append(_record(target, str(src)))
    return out, problems


def inspect_image(path: Path) -> tuple[str, str]:
    """检查图片文件：返回 (致命问题, 告警)，都没有则空串。

    SVG / 没装 Pillow / 非图片扩展名一律放过——宁可少判也不能误杀正常素材。
    """
    if path.suffix.lower() == ".svg" or kind_of(path) != "image":
        return "", ""
    try:
        from PIL import Image
    except Exception:                                     # 没装 Pillow：不做深检
        return "", ""
    try:
        with Image.open(path) as im:
            im.load()                       # 真解一次像素：比 verify() 宽容，块校验和小瑕疵不误杀
            w, h = im.size
    except Exception as exc:
        return "图片无法解码（%s）" % exc, ""
    if w < _MIN_IMAGE_SIDE or h < _MIN_IMAGE_SIDE:
        return "", "尺寸只有 %d×%d，像缩略图，放大到版面上会糊" % (w, h)
    return "", ""


def image_size(path: str | Path) -> tuple[int, int]:
    """图片像素尺寸；读不出来返回 (0, 0)。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return (int(im.width), int(im.height))
    except Exception:
        return (0, 0)


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


def sniff_image_ext(data: bytes) -> str:
    """按文件头判断图片真实格式；认不出来返回空串。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    for magic, ext in _MAGIC_EXT:
        if data.startswith(magic):
            return ext
    return ""


def fetch_image(url: str, timeout: int = _DOWNLOAD_TIMEOUT,
                retries: int = _DOWNLOAD_RETRIES) -> tuple[bytes, str]:
    """下载一张网络图片，返回 (字节, 建议扩展名)。失败抛 ValueError（带原因）。

    只走 http(s)；带浏览器 UA、限大小、指数退避重试，并按文件头复核内容确实是图片——
    搜图拿到的直链常常是 HTML 跳转页或防盗链 403，早报错比页面上空一块好排查。
    """
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    scheme = urlparse(str(url)).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError("只支持 http(s) 图片地址，收到: %s" % (scheme or url))
    last = ""
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(str(url), headers={
                "User-Agent": _UA, "Accept": "image/*,*/*;q=0.8",
                "Referer": "%s://%s" % (urlparse(url).scheme, urlparse(url).netloc),
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                data = resp.read(_MAX_DOWNLOAD_BYTES + 1)
            if not data:
                raise ValueError("返回内容为空")
            if len(data) > _MAX_DOWNLOAD_BYTES:
                raise ValueError("图片超过 %d MB，不接收" % (_MAX_DOWNLOAD_BYTES // (1024 * 1024)))
            ext = sniff_image_ext(data)
            if not ext:
                if "image" in ctype or ctype.startswith("application/octet-stream"):
                    tail = Path(urlparse(str(url)).path).suffix.lower()
                    ext = tail if tail in IMAGE_EXT else ".png"
                else:
                    raise ValueError("返回的不是图片（Content-Type=%s），可能是防盗链或跳转页" % (ctype or "未知"))
            return data, ext
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = str(exc) or exc.__class__.__name__
            if attempt < retries - 1:
                time.sleep(0.6 * (2 ** attempt))      # 0.6s → 1.2s → 2.4s
    raise ValueError("下载失败（已重试 %d 次）: %s" % (retries, last))


def import_asset_from_url(project_dir: str | Path, url: str, filename: str = "",
                          timeout: int = _DOWNLOAD_TIMEOUT,
                          retries: int = _DOWNLOAD_RETRIES) -> tuple[dict, str]:
    """下载网络图片并落进工程 assets，返回 (素材记录, 告警)。失败抛 ValueError。"""
    from urllib.parse import urlparse

    data, ext = fetch_image(url, timeout=timeout, retries=retries)
    name = sanitize_filename(filename or Path(urlparse(str(url)).path).name or "web_image") or "web_image"
    if Path(name).suffix.lower() not in IMAGE_EXT:
        name += ext
    directory = assets_dir(project_dir)
    target = _unique_target(directory, name)
    target.write_bytes(data)
    fatal, warn = inspect_image(target)
    if fatal:
        try:
            target.unlink()
        except OSError:
            pass
        raise ValueError("下载内容不是可用图片: %s" % fatal)
    return _record(target, str(url)), warn


def _record(target: Path, origin: str) -> dict:
    rec = {
        "id": uuid.uuid4().hex[:10],
        "name": target.name,
        "relPath": f"{ASSETS_DIR_NAME}/{target.name}",
        "kind": kind_of(target),
        "size": target.stat().st_size,
        "addedAt": _now(),
        "origin": origin,
    }
    if rec["kind"] == "image" and target.suffix.lower() != ".svg":
        w, h = image_size(target)
        if w and h:
            rec["width"], rec["height"] = w, h
    return rec


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
