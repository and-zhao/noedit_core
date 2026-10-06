"""矢量图标目录的共享读取器。

数据源是 web/ 下的三份目录（随核心一起分发，运行期只读）：

- web/icon-catalog.json     —— 几何 / 流程 / 器件（源自 draw.io 核心模具）
- web/icon-catalog-bio.json —— 分子 / 细胞 / 器材 / 动植物（源自 Bioicons）
- web/icon-catalog-uml.json —— UML 与流程图（源自 Apollon）

载入时把三份合并成一个列表、不分彼此。后两份可以缺失，缺了就少几组图标，
不影响第一份。本模块把「读文件 + 合并 + 解析分组/图标 + 按目标尺寸缩放路径」
收在一处，供 icon_groups / icon_search / icon_insert 等 API 复用。

几何约定：目录里每个图标的 d 都在 [0,0,box] 局部坐标里，只有 M/L/C/Z 绝对命令；
插入时元素框按 box 等比定尺寸（长边对齐 size），再把 d 按 (w/bw, h/bh) 线性缩放。
线稿型图标（line=true）走描边，实心型走填充。

文件缺失或损坏时统一返回空值，由调用方自行兜底。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .paths import WEB_DIR

CATALOG_FILES: tuple[Path, ...] = (
    WEB_DIR / "icon-catalog.json",
    WEB_DIR / "icon-catalog-bio.json",
    WEB_DIR / "icon-catalog-uml.json",
)

#: 插入时元素框长边默认像素
ICON_SIZE = 150

#: 默认主色
DEFAULT_COLOR = "#2f6fed"

#: 转换器只输出这四种绝对命令，每条命令后固定携带的坐标分量数
_CMD_ARITY = {"M": 2, "L": 2, "C": 6, "Z": 0}

# 按 mtime 缓存一次，避免每次查找都读盘
_cache: dict[str, Any] = {"stamp": None, "data": None}
_index: dict[str, Any] = {"by_id": {}, "by_group": {}, "by_parent": {}, "groups": []}


def load() -> dict | None:
    """读取并合并图标目录；全都缺失、损坏或缺 icons 时返回 None。"""
    stamp = []
    for path in CATALOG_FILES:
        try:
            stamp.append(path.stat().st_mtime)
        except OSError:
            stamp.append(None)
    stamp = tuple(stamp)
    if _cache["data"] is not None and _cache["stamp"] == stamp:
        return _cache["data"]

    parts = []
    for path in CATALOG_FILES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  某一份目录损坏不该拖垮另一份
            continue
        if isinstance(data, dict) and isinstance(data.get("icons"), list) and data["icons"]:
            parts.append(data)
    if not parts:
        return None

    merged = {
        "version": 1,
        "sources": [p.get("source") for p in parts if p.get("source")],
        "groups": [],
        "icons": [],
    }
    seen_groups = set()
    for part in parts:
        for group in part.get("groups") or []:
            gid = group.get("id")
            if gid and gid not in seen_groups:
                seen_groups.add(gid)
                merged["groups"].append(group)
        merged["icons"].extend(part["icons"])
    _cache["stamp"] = stamp
    _cache["data"] = merged
    _build_index(merged)
    return merged


def _build_index(data: dict) -> None:
    """随目录重新加载一起重建 id / 分组索引。"""
    by_id: dict[str, dict] = {}
    by_group: dict[str, list] = {}
    by_parent: dict[str, list] = {}
    groups: list[dict] = []
    declared = {g.get("id"): g for g in (data.get("groups") or [])}
    for icon in data.get("icons") or []:
        iid = icon.get("id")
        if not iid:
            continue
        by_id[iid] = icon
        gid = icon.get("group") or ""
        by_group.setdefault(gid, []).append(icon)
    for gid, icons in by_group.items():
        spec = declared.get(gid) or {}
        parent = spec.get("parent") or ""
        if parent:                                   # 二级分组：登记到父大类，便于整类检索
            by_parent.setdefault(parent, []).extend(icons)
        groups.append({
            "id": gid,
            "label": spec.get("label") or gid,
            "parent": parent,
            "parentLabel": (declared.get(parent) or {}).get("label") or "",
            "source": spec.get("source") or "",
            "count": len(icons),
        })
    groups.sort(key=lambda g: g["id"])
    _index["by_id"] = by_id
    _index["by_group"] = by_group
    _index["by_parent"] = by_parent
    _index["groups"] = groups


def groups() -> list[dict]:
    """分组概览：[{id, label, source, count}]；读不到时返回空列表。"""
    load()
    return copy.deepcopy(_index["groups"])


def icons(group: str = "") -> list[dict]:
    """某分组（或某个大类）的全部图标；group 为空时返回全部。读不到时返回空列表。"""
    load()
    if group:
        return list(_index["by_group"].get(group) or _index["by_parent"].get(group) or [])
    return list(_index["by_id"].values())


def count() -> int:
    """图标总数。"""
    load()
    return len(_index["by_id"])


def by_id(icon_id: str) -> dict | None:
    """按 id 取图标定义（含 d/box/line）；找不到返回 None。"""
    load()
    return _index["by_id"].get(icon_id)


def brief(icon: dict) -> dict:
    """列表/搜索用的精简条目：不带 d（太长），只留定位需要的字段。"""
    return {
        "id": icon.get("id"),
        "label": icon.get("label"),
        "group": icon.get("group"),
        "box": icon.get("box"),
        "line": bool(icon.get("line")),
        "multi": bool(icon.get("multi")),
    }


def search(keyword: str = "", group: str = "", limit: int = 40) -> list[dict]:
    """按关键词搜图标：匹配英文名、id、以及中文分组名。"""
    items = icons(group)
    kw = str(keyword or "").strip().lower()
    if kw:
        labels = {g["id"]: f"{g['label']} {g.get('parentLabel', '')}".strip() for g in groups()}
        hit = []
        for icon in items:
            hay = f"{icon.get('label')} {icon.get('id')} {labels.get(icon.get('group'), '')}".lower()
            if kw in hay:
                hit.append(icon)
        items = hit
    try:
        top = max(1, int(limit or 40))
    except (TypeError, ValueError):
        top = 40
    return items[:top]


def fit_size(icon_id: str, size: int = ICON_SIZE) -> tuple[int, int]:
    """按图标原始比例算出元素框尺寸（长边对齐 size）。"""
    icon = by_id(icon_id)
    if not icon:
        return (0, 0)
    box = icon.get("box") or [100, 100]
    bw, bh = float(box[0] or 1), float(box[1] or 1)
    try:
        target = float(size) if float(size) > 0 else float(ICON_SIZE)
    except (TypeError, ValueError):
        target = float(ICON_SIZE)
    fit = target / max(bw, bh)
    return (max(1, round(bw * fit)), max(1, round(bh * fit)))


def _fmt(value: float) -> str:
    """路径坐标取两位小数、去掉多余的 0。"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def scale_d(d: str, sx: float, sy: float) -> str:
    """把目录里的 d 线性缩放到目标尺寸。只需处理 M/L/C/Z 绝对命令。"""
    if not d or (sx == 1 and sy == 1):
        return d
    out: list[str] = []
    i, n = 0, len(d)
    while i < n:
        cmd = d[i]
        arity = _CMD_ARITY.get(cmd)
        if arity is None:      # 目录只应有 M/L/C/Z；别的字符跳过，不让它污染输出
            i += 1
            continue
        i += 1
        nums: list[str] = []
        for k in range(arity):
            while i < n and d[i] == " ":
                i += 1
            start = i
            while i < n and (d[i].isdigit() or d[i] in ".-+eE"):
                i += 1
            try:
                value = float(d[start:i])
            except ValueError:
                value = 0.0
            nums.append(_fmt(value * (sx if k % 2 == 0 else sy)))
        out.append(cmd + " ".join(nums))
    return "".join(out)


def build_element(icon_id: str, x: int, y: int, size: int = ICON_SIZE,
                  color: str = DEFAULT_COLOR, name: str = "") -> dict | None:
    """把单色图标组装成一个可编辑的 path 元素。

    线稿型：fillType='none' + 3px 描边；实心型：fillType='solid' + 纯填充。
    """
    icon = by_id(icon_id)
    if not icon:
        return None
    box = icon.get("box") or [100, 100]
    bw, bh = float(box[0] or 1), float(box[1] or 1)
    w, h = fit_size(icon_id, size)
    line = bool(icon.get("line"))
    return {
        "type": "path",
        "name": name or icon.get("label") or icon_id,
        "x": int(x),
        "y": int(y),
        "w": w,
        "h": h,
        "props": {
            "d": scale_d(icon.get("d") or "", w / bw, h / bh),
            "fillRule": "nonzero",
            "fillType": "none" if line else "solid",
            "strokeDash": "solid",
            "strokeCap": "round",
            "strokeJoin": "round",
            "vector": True,
        },
        "style": {
            "background": "transparent" if line else color,
            "borderWidth": 3 if line else 0,
            "borderColor": color,
            "borderStyle": "solid",
            "borderRadius": 0,
        },
    }


def build_elements(icon_id: str, x: int, y: int, size: int = ICON_SIZE,
                   color: str = DEFAULT_COLOR, name: str = "", make_id=None) -> list[dict]:
    """把图标组装成「按顺序插入」的元素列表。

    - 单色图标：``[一个 path 元素]``，颜色取 color，用户插完还能整体换色。
    - 多色图标：``[分组容器, 第 1 层, 第 2 层, …]``。容器排在最前，落盘后 z 最小、压在成员
      下面；成员用 parentId 指向容器，各自带原图的填充 / 描边，此时 color 不参与。

    ``make_id(prefix)`` 用于给容器与成员预生成 id（成员要提前知道父 id），由调用方传入。
    """
    icon = by_id(icon_id)
    if not icon:
        return []
    layers = icon.get("layers")
    if not isinstance(layers, list) or not layers:
        single = build_element(icon_id, x, y, size=size, color=color, name=name)
        return [single] if single else []

    box = icon.get("box") or [100, 100]
    bw, bh = float(box[0] or 1), float(box[1] or 1)
    w, h = fit_size(icon_id, size)
    sx, sy = w / bw, h / bh
    avg = (sx + sy) / 2
    label = name or icon.get("label") or icon_id
    gid = make_id("el") if make_id else "el-icon-group"

    out: list[dict] = [{
        "id": gid,
        "type": "group",
        "name": label,
        "x": int(x),
        "y": int(y),
        "w": w,
        "h": h,
    }]
    for layer in layers:
        fill = layer.get("fill") or "none"
        stroke = layer.get("stroke") or "none"
        sw = float(layer.get("sw") or 0) if stroke != "none" else 0.0
        out.append({
            "id": make_id("el") if make_id else f"el-icon-{len(out)}",
            "type": "path",
            "name": label,
            "x": int(x),
            "y": int(y),
            "w": w,
            "h": h,
            "parentId": gid,
            "props": {
                "d": scale_d(layer.get("d") or "", sx, sy),
                "fillRule": "nonzero",
                "fillType": "none" if fill == "none" else "solid",
                "strokeDash": "solid",
                "strokeCap": "round",
                "strokeJoin": "round",
                "vector": True,
            },
            "style": {
                "background": "transparent" if fill == "none" else fill,
                "borderWidth": round(max(0.5, sw * avg), 2) if sw > 0 else 0,
                "borderColor": stroke if stroke != "none" else (color if fill == "none" else fill),
                "borderStyle": "solid",
                "borderRadius": 0,
            },
        })
    return out
