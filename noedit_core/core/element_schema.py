"""元素参数元数据的共享读取器。

唯一数据源是 web/element-schema.json（前端 web/js/element-schema.js 读同一份文件）。
本模块把「读文件 + 解析出类型清单 / 默认值 / 字段合法性」收在一处，供两边复用：
- app/llm.py      用 types() / modelNote 生成第 6 条提示词里的元素类型、参数清单与专用用法
- app/projects.py 用 defaults() 生成新元素的初始参数、用 aliases()/declared() 归一字段

文件缺失或损坏时统一返回空值，由调用方自行兜底（行为与改造前一致）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .paths import WEB_DIR

SCHEMA_FILE: Path = WEB_DIR / "element-schema.json"

# 按 mtime 缓存一次，避免每次生成提示词都读盘
_cache: dict[str, Any] = {"mtime": None, "data": None}

# 按类型缓存的「已声明字段」：随 schema 重新加载一起清空（见 load_schema）
_declared_cache: dict[str, dict[str, set]] = {}


def load_schema() -> dict | None:
    """读取参数元数据；文件缺失、损坏或缺 types 时返回 None。"""
    try:
        mtime = SCHEMA_FILE.stat().st_mtime
    except OSError:
        return None
    if _cache["data"] is not None and _cache["mtime"] == mtime:
        return _cache["data"]
    try:
        data = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  配置损坏等同于缺失
        return None
    if not isinstance(data, dict) or not isinstance(data.get("types"), dict) or not data["types"]:
        return None
    _cache["mtime"] = mtime
    _cache["data"] = data
    _declared_cache.clear()
    return data


def types() -> dict:
    """类型名 -> 该类型的元数据；读不到时返回空字典。"""
    return (load_schema() or {}).get("types") or {}


def label(etype: str) -> str:
    """类型的显示名（中文），读不到时回落类型名本身。"""
    spec = types().get(etype) or {}
    return spec.get("label") or etype


def aliases() -> dict:
    """别名表：模型爱写、引擎不认的键 → 规范字段（同 web/js/store.js 用的那一份）。

    schema 读不到时返回空表——调用方按「不做任何改写」处理，行为回到改造前。
    """
    return (load_schema() or {}).get("aliases") or {}


def _iter_rows(spec: dict):
    """遍历一份 spec 的所有 row：既支持 sections:[{rows:[…]}]，也支持顶层 rows（commonStyle）。"""
    for section in spec.get("sections") or []:
        yield from section.get("rows") or []
    yield from spec.get("rows") or []


def _collect(spec: dict) -> dict:
    """把一份 spec（类型或 commonStyle）里的点路径汇总成 {props: [...], style: [...]}。"""
    out: dict[str, list] = {"props": [], "style": []}
    for row in _iter_rows(spec):
        for field in row.get("fields") or []:
            path = str(field.get("path") or "")
            for bucket in ("props", "style"):
                if path.startswith(bucket + ".") and path not in out[bucket]:
                    out[bucket].append(path)
    return out


def declared(etype: str) -> dict:
    """该类型已声明的字段：{props: {一级键…}, style: {一级键…}}。

    只看一级键（props.filter.brightness 只登记 filter）。别名改写与未知键体检都按它判断：
    源键不在集合里才说明是「放错地方 / 名字写错」，可以按原意并回规范字段；在集合里就是
    该类型自己的合法参数，一律不动。
    """
    if etype in _declared_cache:
        return _declared_cache[etype]
    schema = load_schema() or {}
    type_spec = (schema.get("types") or {}).get(etype) or {}
    out: dict[str, set] = {"props": set(), "style": set()}
    for spec in (schema.get("commonStyle") or {}, type_spec):
        paths = _collect(spec)
        for bucket in ("props", "style"):
            out[bucket].update(path.split(".", 1)[1].split(".")[0] for path in paths[bucket])
    out["style"].update((type_spec.get("style") or {}).keys())   # 类型自带的 style 默认值也算已声明
    out["style"].update(schema.get("runtimeStyle") or [])        # 渲染读得到但没面板控件的全局键
    out["props"].update((schema.get("runtimeProps") or {}).get(etype) or [])
    _declared_cache[etype] = out
    return out


def _set_on_path(target: dict, path: str, value: Any) -> None:
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return
    cursor = target
    for key in parts[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def defaults(etype: str) -> dict | None:
    """某类型的初始参数：{name, w, h, props, style}；类型未登记时返回 None。

    规则与前端 element-schema.js 的 typeDefaultsFromSchema 一致：
    style 以类型自带的 style 为底，再把带 default 的字段按点路径汇总进 props / style。
    """
    spec = types().get(etype)
    if not spec:
        return None
    props: dict = {}
    style = json.loads(json.dumps(spec.get("style") or {}))
    for section in spec.get("sections") or []:
        for row in section.get("rows") or []:
            for field in row.get("fields") or []:
                path = str(field.get("path") or "")
                if not path or "default" not in field:
                    continue
                value = copy.deepcopy(field["default"])
                if path.startswith("style."):
                    _set_on_path(style, path[6:], value)
                elif path.startswith("props."):
                    _set_on_path(props, path[6:], value)
    return {
        "name": spec.get("name") or spec.get("label") or etype,
        "w": spec.get("w"),
        "h": spec.get("h"),
        "props": props,
        "style": style,
    }
