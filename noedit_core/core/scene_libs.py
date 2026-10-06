"""微场景可用的前端库：按需下载并缓存在本地，之后完全离线可用。

纯本地约束下的唯一例外：只有用户在「设置 → 场景库」里主动点击下载时才会联网，
源码落到 data/scene_libs/<id>.js 之后，编辑态运行、放映、导出 HTML 都直接内联这份本地副本，
不再有任何网络请求。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import DATA_DIR, ensure_dir

LIBS_DIR_NAME = "scene_libs"

# 清单：每个库给出主地址与镜像地址，下载时按顺序尝试，第一个成功即止。
# 一律选 UMD 版本（挂全局变量），因为场景代码是普通 <script>，不是 ES module。
_LIB_SPECS: list[dict] = [
    {
        "id": "p5",
        "name": "p5.js",
        "version": "1.9.4",
        "global": "p5",
        "desc": "创意编程：setup/draw 画布绘图、粒子、图形动效",
        "urls": [
            "https://cdn.jsdelivr.net/npm/p5@1.9.4/lib/p5.min.js",
            "https://unpkg.com/p5@1.9.4/lib/p5.min.js",
        ],
    },
    {
        "id": "anime",
        "name": "anime.js",
        "version": "3.2.2",
        "global": "anime",
        "desc": "轻量补间动画：DOM / SVG / 对象属性都能做时间轴",
        "urls": [
            "https://cdn.jsdelivr.net/npm/animejs@3.2.2/lib/anime.min.js",
            "https://unpkg.com/animejs@3.2.2/lib/anime.min.js",
        ],
    },
    {
        "id": "gsap",
        "name": "GSAP",
        "version": "3.12.5",
        "global": "gsap",
        "desc": "专业补间动画库：时间轴、缓动、逐帧控制（seek 友好）",
        "urls": [
            "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js",
            "https://unpkg.com/gsap@3.12.5/dist/gsap.min.js",
        ],
    },
    {
        "id": "three",
        "name": "Three.js",
        "version": "0.147.0",
        "global": "THREE",
        "desc": "3D 场景：WebGL 渲染、相机、光照、模型动画",
        "urls": [
            "https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js",
            "https://unpkg.com/three@0.147.0/build/three.min.js",
        ],
    },
    {
        "id": "chart",
        "name": "Chart.js",
        "version": "4.4.1",
        "global": "Chart",
        "desc": "统计图：柱状 / 折线 / 饼图，可动画过渡",
        "urls": [
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
            "https://unpkg.com/chart.js@4.4.1/dist/chart.umd.min.js",
        ],
    },
    {
        "id": "d3",
        "name": "D3.js",
        "version": "7.8.5",
        "global": "d3",
        "desc": "数据可视化：SVG 绑数据、比例尺、力导向布局",
        "urls": [
            "https://cdn.jsdelivr.net/npm/d3@7.8.5/dist/d3.min.js",
            "https://unpkg.com/d3@7.8.5/dist/d3.min.js",
        ],
    },
    {
        "id": "matter",
        "name": "Matter.js",
        "version": "0.19.0",
        "global": "Matter",
        "desc": "2D 物理引擎：重力、碰撞、刚体（适合机械 / 原理演示）",
        "urls": [
            "https://cdn.jsdelivr.net/npm/matter-js@0.19.0/build/matter.min.js",
            "https://unpkg.com/matter-js@0.19.0/build/matter.min.js",
        ],
    },
    {
        "id": "confetti",
        "name": "canvas-confetti",
        "version": "1.9.2",
        "global": "confetti",
        "desc": "彩带 / 礼花粒子效果，一行调用",
        "urls": [
            "https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.2/dist/confetti.browser.min.js",
            "https://unpkg.com/canvas-confetti@1.9.2/dist/confetti.browser.min.js",
        ],
    },
]


def libs_dir() -> Path:
    return ensure_dir(DATA_DIR / LIBS_DIR_NAME)


def _spec(lib_id: str) -> dict | None:
    for spec in _LIB_SPECS:
        if spec["id"] == lib_id:
            return spec
    return None


def lib_file(lib_id: str) -> Path:
    return libs_dir() / f"{lib_id}.js"


def list_libs() -> list[dict]:
    """全部可用的库及其本地缓存状态（给设置面板与场景生成用）。"""
    out = []
    for spec in _LIB_SPECS:
        path = lib_file(spec["id"])
        cached = path.exists() and path.stat().st_size > 0
        out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "version": spec["version"],
                "global": spec["global"],
                "desc": spec["desc"],
                "cached": cached,
                "bytes": path.stat().st_size if cached else 0,
                "cachedAt": int(path.stat().st_mtime * 1000) if cached else 0,
            }
        )
    return out


def _download(urls: list[str], timeout: float = 90) -> tuple[bytes, str]:
    """按顺序尝试各地址；返回 (内容, 实际地址)。全部失败时抛最后一个错误。"""
    last: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "noedit_core-editor/0.1", "Accept": "*/*"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            text = data[:400].decode("utf-8", "ignore").lower()
            if len(data) < 512 or "<html" in text:
                raise ValueError(f"返回内容不像 JS（{len(data)} 字节）")
            return data, url
        except Exception as exc:  # noqa: BLE001  换镜像继续尝试
            last = exc
    raise RuntimeError(str(last) if last else "没有可用的下载地址")


def ensure_lib(lib_id: str) -> dict:
    """下载并缓存一个库；已缓存时直接返回（幂等）。"""
    spec = _spec(lib_id)
    if spec is None:
        raise ValueError(f"未知的库：{lib_id}")
    path = lib_file(lib_id)
    if path.exists() and path.stat().st_size > 0:
        return {"id": lib_id, "name": spec["name"], "bytes": path.stat().st_size, "cached": True, "downloaded": False}
    data, url = _download(spec["urls"])
    tmp = path.with_suffix(".js.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return {
        "id": lib_id,
        "name": spec["name"],
        "bytes": len(data),
        "cached": True,
        "downloaded": True,
        "url": url,
        "at": int(time.time() * 1000),
    }


def remove_lib(lib_id: str) -> dict:
    path = lib_file(lib_id)
    if path.exists():
        path.unlink()
    return {"id": lib_id, "cached": False}


def lib_source(lib_id: str) -> str:
    """本地缓存的库源码；未缓存时返回空串（调用方负责提示）。"""
    path = lib_file(lib_id)
    if not (path.exists() and path.stat().st_size > 0):
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def sources_for(lib_ids: list[str]) -> dict:
    """批量取源码：{id: source}，并给出缺失清单，供前端 / 导出统一处理。"""
    sources: dict[str, str] = {}
    missing: list[str] = []
    for lib_id in lib_ids or []:
        source = lib_source(lib_id)
        if source:
            sources[lib_id] = source
        else:
            missing.append(lib_id)
    return {"sources": sources, "missing": missing}


def libs_meta_text() -> str:
    """给模型看的库清单（含本地是否有缓存）。"""
    lines = []
    for item in list_libs():
        mark = "已缓存，可直接用" if item["cached"] else "未缓存（需用户先在设置里下载）"
        lines.append(
            f"   - {item['id']}（{item['name']} {item['version']}，全局变量 {item['global']}）：{item['desc']}。{mark}"
        )
    return "\n".join(lines)
