"""Action JSON → manifest 的执行器（后端版）。

这是本扩展唯一「重写」的逻辑，语义必须与前端 web/js/store.js 的 applyActions 保持一致：
  store.js  applyActions              L374-L486
  store.js  resolveTargets/matchElements L323-L367
  store.js  targetPages              L292-L311
  store.js  setPath/NUMERIC_KEYS      L32-L36, L182-L197
  store.js  normalizeElement          L259-L280
  anim.js   ANIM_PRESETS/normalizeAnim/animFromPreset L26-L108
  store.js  连线端点解析与几何补算        L536-L615（settleConnectors）
  几何内核  web/js/connector-geom.js     → app/connector_geom.py（逐行复刻）

支持 op：update / insert / delete / reorder / animate /
         page.update / page.insert / page.delete / select

差异说明（有意为之）：
- 后端没有「当前页」概念，用 page_index（默认 0）作为 homePage 的等价物；
- 后端没有选区，select 只记录到返回值，不产生副作用；
- 撤销栈在前端，这里不维护（每次操作都是「先重读 manifest 再改再落盘」）。
"""

from __future__ import annotations

import json
import math

from .errors import McpError
from . import connector_geom, element_schema
from . import projects as projects_mod
from .projects import new_id

#: 引擎不认、模型却爱写的别名键（真身见 web/element-schema.json 的 aliases，前后端共用同一份）。
#: 落盘时 normalize_manifest 会把它们并回规范字段，这里只负责把这件事回给模型看，
#: 免得「改了没反应」又要靠肉眼去发现。


def _style_alias_hits(paths) -> list[str]:
    """入参里出现了哪些别名键（如 style.fill、props.fillColor）。"""
    table = element_schema.aliases() or {}
    return sorted(str(k).strip() for k in (paths or []) if str(k).strip() in table)


def _style_alias_warning(hits: list[str]) -> str:
    table = element_schema.aliases() or {}
    detail = []
    for hit in hits:
        target = table.get(hit)
        to = target if isinstance(target, str) else (target or {}).get("to")
        detail.append(f"{hit} → {to or '?'}")
    return f"⚠ {'、'.join(hits)} 不是有效字段，已按原意改写：" + "；".join(detail)


# ---------------------------------------------------------------- 动画（复刻 web/js/anim.js）

ANIM_TRIGGERS = ["page", "click", "loop"]
ANIM_EASINGS = ["linear", "ease", "ease-in", "ease-out", "ease-in-out"]

ANIM_PRESETS: dict[str, dict] = {
    "none": {"label": "无动画（自定义）", "keyframes": []},
    "fadeIn": {"label": "淡入", "keyframes": [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]},
    "fadeOut": {"label": "淡出", "keyframes": [{"t": 0, "opacity": 1}, {"t": 1, "opacity": 0}]},
    "slideInLeft": {"label": "左侧滑入", "keyframes": [{"t": 0, "opacity": 0, "dx": -140}, {"t": 1, "opacity": 1, "dx": 0}]},
    "slideInRight": {"label": "右侧滑入", "keyframes": [{"t": 0, "opacity": 0, "dx": 140}, {"t": 1, "opacity": 1, "dx": 0}]},
    "slideInUp": {"label": "下方滑入（向上）", "keyframes": [{"t": 0, "opacity": 0, "dy": 140}, {"t": 1, "opacity": 1, "dy": 0}]},
    "slideInDown": {"label": "上方滑入（向下）", "keyframes": [{"t": 0, "opacity": 0, "dy": -140}, {"t": 1, "opacity": 1, "dy": 0}]},
    "zoomIn": {"label": "放大进入", "keyframes": [{"t": 0, "opacity": 0, "scale": 0.4}, {"t": 1, "opacity": 1, "scale": 1}]},
    "zoomOut": {"label": "缩小进入", "keyframes": [{"t": 0, "opacity": 0, "scale": 1.8}, {"t": 1, "opacity": 1, "scale": 1}]},
    "spinIn": {"label": "旋转进入", "keyframes": [{"t": 0, "opacity": 0, "rotate": -180, "scale": 0.6}, {"t": 1, "opacity": 1, "rotate": 0, "scale": 1}]},
    "bounceIn": {
        "label": "弹跳进入",
        "keyframes": [{"t": 0, "opacity": 0, "dy": -180}, {"t": 0.6, "opacity": 1, "dy": 0}, {"t": 0.78, "dy": -28}, {"t": 1, "dy": 0}],
    },
    "pulse": {"label": "脉冲强调", "keyframes": [{"t": 0, "scale": 1}, {"t": 0.5, "scale": 1.12}, {"t": 1, "scale": 1}]},
    "float": {"label": "漂浮循环", "keyframes": [{"t": 0, "dy": 0}, {"t": 0.5, "dy": -16}, {"t": 1, "dy": 0}]},
}

KEYFRAME_KEYS = ["opacity", "dx", "dy", "scale", "rotate"]


def _clamp01(value) -> float:
    num = _number(value, 0.0) or 0.0
    return max(0.0, min(1.0, float(num)))


def _number(value, fallback: float = 0.0):
    """JS Number() 的容错版：取不到有限数就回落。"""
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return fallback
    try:
        num = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(num) or math.isinf(num):
        return fallback
    return int(num) if num.is_integer() else num


def _opt_num(value):
    """可选数值字段：空值返回 None（表示「用元素静态值」）。"""
    if value is None or value == "":
        return None
    return _number(value, None)


def normalize_anim(raw):
    """校验并补齐一条动画；返回 None 表示该元素没有动画（对应 anim.js normalizeAnim）。"""
    if not raw or raw is True or not isinstance(raw, dict):
        return None
    if raw.get("enabled") is False:
        return None
    preset = raw.get("preset") if raw.get("preset") in ANIM_PRESETS else None
    kfs = raw.get("keyframes") if isinstance(raw.get("keyframes"), list) else None
    preset = preset or "none"
    source = kfs if kfs else (ANIM_PRESETS.get(preset) or ANIM_PRESETS["none"])["keyframes"]
    if not source:
        return None
    keyframes = []
    for item in source:
        if not isinstance(item, dict):
            continue
        keyframes.append({
            "t": _clamp01(item.get("t", 0)),
            "opacity": _opt_num(item.get("opacity")),
            "dx": _number(item.get("dx"), 0),
            "dy": _number(item.get("dy"), 0),
            "scale": _number(item.get("scale"), 1),
            "rotate": _number(item.get("rotate"), 0),
        })
    keyframes.sort(key=lambda k: k["t"])
    if not keyframes:
        return None
    return {
        "enabled": True,
        "trigger": raw.get("trigger") if raw.get("trigger") in ANIM_TRIGGERS else "page",
        "delay": max(0, _number(raw.get("delay"), 0)),
        "duration": max(60, _number(raw.get("duration"), 700)),
        "easing": raw.get("easing") if raw.get("easing") in ANIM_EASINGS else "ease-out",
        "preset": preset,
        "keyframes": keyframes,
    }


def anim_from_preset(preset: str, base: dict | None = None) -> dict:
    base = base or {}
    spec = ANIM_PRESETS.get(preset) or ANIM_PRESETS["none"]
    return {
        "enabled": len(spec["keyframes"]) > 0,
        "trigger": base.get("trigger") or "page",
        "delay": _number(base.get("delay"), 0),
        "duration": _number(base.get("duration"), 700),
        "easing": base.get("easing") or "ease-out",
        "preset": preset,
        "keyframes": json.loads(json.dumps(spec["keyframes"])),
    }


# ---------------------------------------------------------------- 路径读写（复刻 setPath）

NUMERIC_KEYS = {
    "x", "y", "w", "h", "z", "rotate", "opacity", "fontSize", "letterSpacing",
    "lineHeight", "paragraphSpacing", "textIndent", "padding", "borderRadius",
    "borderWidth", "size", "index",
}


def set_path(obj: dict, path: str, value):
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return obj
    cursor = obj
    for key in parts[:-1]:
        if not isinstance(cursor.get(key), dict):
            cursor[key] = {}
        cursor = cursor[key]
    last = parts[-1]
    if isinstance(value, str) and last in NUMERIC_KEYS and value.strip() != "":
        try:
            num = float(value)
            value = int(num) if num.is_integer() else num
        except ValueError:
            pass
    cursor[last] = value
    return obj


# ---------------------------------------------------------------- 定位与目标解析

def sorted_elements(page: dict) -> list[dict]:
    return sorted(page.get("elements", []), key=lambda e: e.get("z") or 0)


def locate_element(manifest: dict, element_id):
    if not element_id:
        return None
    for page in manifest.get("pages", []):
        for el in page.get("elements", []):
            if el.get("id") == element_id:
                return {"el": el, "page": page}
    return None


def new_page(manifest: dict, name: str | None = None) -> dict:
    return {
        "id": new_id("page"),
        "name": name or f"第 {len(manifest.get('pages', [])) + 1} 页",
        "background": {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"},
        "elements": [],
    }


def _next_z(page: dict) -> int:
    elements = page.get("elements") or []
    if not elements:
        return 1
    return int(max((e.get("z") or 0) for e in elements)) + 1


def target_pages(manifest: dict, action: dict, home_page: dict | None = None) -> list[dict]:
    """动作的目标页。作用域**只认显式声明**：allPages / pageIds / pageIndexes / pageId；
    都不给则落在 home_page（调用方指定的归属页）。

    这里刻意不做「指令里出现『每页 / 全篇』就铺满全篇」的文本推断。调用方传进来的长指令
    绝大部分是内容与风格描述，从自由文本里猜作用域会把「只为这一页写的正文」复制到每一页；
    要全篇就由调用方用 allPages 显式表达。
    """
    pages = manifest.get("pages") or []
    explicit = action.get("pageId") or action.get("pageIds") or action.get("pageIndexes")
    if not action.get("allPages") and explicit:
        if isinstance(action.get("pageIndexes"), list):
            out = []
            for raw in action["pageIndexes"]:
                idx = _number(raw, None)
                if isinstance(idx, int) and 0 <= idx < len(pages):
                    out.append(pages[idx])
            return out
        if isinstance(action.get("pageIds"), list):
            wanted = set(action["pageIds"])
            return [p for p in pages if p.get("id") in wanted]
        found = next((p for p in pages if p.get("id") == action.get("pageId")), None)
        return [found] if found else []
    if action.get("allPages"):
        return list(pages)
    return [home_page] if home_page else []


# ---------------------------------------------------------------- 落盘范围（硬上界）

def normalize_scope(scope) -> dict:
    """规整调用方声明的落盘范围 → {"allPages": bool, "pageIndexes": [int]}。

    这是**落盘的授权范围**：一次落盘允许改到哪些页，由提交任务的一方声明，不由模型输出的
    动作自行决定。返回空范围 = 不设上界（只有走逐元素直改的内部通路会这样）。
    """
    if not scope:
        return {"allPages": False, "pageIndexes": []}
    if scope.get("allPages"):
        return {"allPages": True, "pageIndexes": []}
    out: list[int] = []
    for raw in (scope.get("pageIndexes") or []):
        idx = _number(raw, None)
        if isinstance(idx, int) and idx not in out:
            out.append(idx)
    return {"allPages": False, "pageIndexes": out}


def _page_text(indexes: list[int]) -> str:
    return "、".join(str(i) for i in indexes)


def scope_clamp(action: dict, scope: dict, manifest: dict) -> str | None:
    """把一条动作收窄进 scope；就地改写并返回越界说明（None = 没越界）。

    为什么必须有这一层：模型在长指令里读到「全篇 / 每页」这类字眼，就会在动作里自己写
    `allPages: true`，把只为某一页写的正文复制到整篇。此前落盘层完全信任动作的声明，只在
    提示词里警告模型别这么写——软约束拦不住模型，于是「一页叠着别人页的内容」反复发生。
    现在范围以提交方声明的为准：越界的声明一律改写成 scope，并把越界事实报回去。
    """
    if not isinstance(action, dict):
        return None
    if (scope or {}).get("allPages"):
        return None
    allowed = list((scope or {}).get("pageIndexes") or [])
    if not allowed:
        return None
    pages = manifest.get("pages") or []
    if action.get("allPages"):
        action.pop("allPages", None)
        action["pageIndexes"] = list(allowed)
        return (f"动作自己声明了 allPages（整篇 {len(pages)} 页），越出本次落盘范围，"
                f"已收窄到第 {_page_text(allowed)} 页")
    if isinstance(action.get("pageIndexes"), list):
        wanted = [i for i in (_number(x, None) for x in action["pageIndexes"]) if isinstance(i, int)]
        kept = [i for i in wanted if i in allowed]
        action["pageIndexes"] = kept
        if len(kept) == len(wanted):
            return None
        if not kept:
            action.pop("pageIndexes", None)
            return (f"动作声明的 pageIndexes {wanted} 全在本次落盘范围"
                    f"（第 {_page_text(allowed)} 页）之外，已去掉跨页目标")
        return f"动作声明的 pageIndexes {wanted} 越出本次落盘范围，已收窄为 {kept}"
    want_ids = [x for x in (action.get("pageIds") or []) if x] if isinstance(action.get("pageIds"), list) else []
    if action.get("pageId"):
        want_ids.append(action.get("pageId"))
    if want_ids:
        allowed_ids = {pages[i].get("id") for i in allowed if 0 <= i < len(pages)}
        kept_ids = [x for x in want_ids if x in allowed_ids]
        if len(kept_ids) == len(want_ids):
            return None
        action.pop("pageId", None)
        action.pop("pageIds", None)
        if kept_ids:
            action["pageIds"] = kept_ids
        else:
            action["pageIndexes"] = list(allowed)
        return f"动作声明的目标页越出本次落盘范围，已收窄到第 {_page_text(allowed)} 页"
    if action.get("match"):
        # match 不给页范围时会跨整篇匹配，必须钉进本次落盘范围
        action["pageIndexes"] = list(allowed)
        return f"动作没声明目标页（match 会跨整篇匹配），已钉进本次落盘范围（第 {_page_text(allowed)} 页）"
    return None


def _match_one(el: dict, key: str, value) -> bool:
    want = str(value)
    if key == "name":
        return str(el.get("name") or "") == want
    if key == "type":
        return str(el.get("type") or "") == want
    if key == "nameContains":
        return want.lower() in str(el.get("name") or "").lower()
    if key == "srcContains":
        src = str((el.get("props") or {}).get("src") or "") + " " + str(el.get("name") or "")
        return want.lower() in src.lower()
    return False


def match_elements(manifest: dict, action: dict, home_page: dict | None = None) -> list[dict]:
    spec = action.get("match") or {}
    keys = [
        k for k in ("name", "nameContains", "type", "srcContains")
        if spec.get(k) is not None and str(spec.get(k)) != ""
    ]
    if not keys:
        return []
    scoped = bool(
        action.get("allPages") or action.get("pageId")
        or action.get("pageIds") or action.get("pageIndexes")
    )
    pages = target_pages(manifest, action, home_page) if scoped else (manifest.get("pages") or [])
    out = []
    for page in pages:
        for el in sorted_elements(page):
            if all(_match_one(el, key, spec[key]) for key in keys):
                out.append({"el": el, "page": page})
    return out


def resolve_targets(manifest: dict, action: dict, home_page: dict | None = None) -> list[dict]:
    if action.get("match"):
        hits = match_elements(manifest, action, home_page)
        if not hits:
            raise McpError(f"没有任何元素匹配 {json.dumps(action['match'], ensure_ascii=False)}")
        return hits
    hit = locate_element(manifest, action.get("id"))
    if not hit:
        raise McpError(f"找不到元素 {action.get('id')}")
    return [hit]


# ---------------------------------------------------------------- 元素构造

def normalize_element(raw: dict, page: dict) -> dict:
    """按页生成一个完整元素（对应 store.js 的 normalizeElement + createElement）。"""
    raw = raw if isinstance(raw, dict) else {}
    etype = raw.get("type") or "text"
    base = projects_mod.default_element(etype)          # 默认值来自 web/element-schema.json，与前端同源

    props = json.loads(json.dumps(base.get("props") or {}))
    if isinstance(raw.get("props"), dict):
        props.update(raw["props"])
    style = json.loads(json.dumps(base.get("style") or {}))
    if isinstance(raw.get("style"), dict):
        style.update(raw["style"])

    el = {
        "id": raw.get("id") or new_id("el"),
        "type": etype,
        "name": raw.get("name") or base.get("name") or etype,
        "x": _number(raw.get("x"), 80),
        "y": _number(raw.get("y"), 80),
        "w": _number(raw.get("w"), base.get("w") or 400),
        "h": _number(raw.get("h"), base.get("h") or 200),
        # z 必须按「真正落进去的那一页」算，多页插入时每页各自独立
        "z": _number(raw.get("z"), _next_z(page)),
        "rotate": _number(raw.get("rotate"), 0),
        "opacity": _number(raw.get("opacity"), 1),
        "visible": raw.get("visible") is not False,
        "locked": False,
        "parentId": raw.get("parentId") or None,
        "anim": raw.get("anim") or None,
        "props": props,
        "style": style,
    }
    return el


# ---------------------------------------------------------------- 连线端点（复刻 store.js 的同名逻辑）

def _num_or_none(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def element_by_name(page: dict, name) -> dict | None:
    """元素名 → 元素：先全等名字，再全等正文（文本元素），最后「唯一包含」；重名或找不到都返回 None。

    模型画流程图时爱写节点的文字（"开始"），而元素的 name 可能是「开始框」，所以逐级放宽。
    """
    want = str(name or "").strip()
    if not want:
        return None
    others = [el for el in (page.get("elements") or []) if el.get("type") != "connector"]

    def label(el):
        return str(el.get("name") or "").strip()

    exact = [el for el in others if label(el) == want]
    if exact:
        return exact[0]
    body = [el for el in others
            if el.get("type") == "text" and str((el.get("props") or {}).get("text") or "").strip() == want]
    if body:
        return body[0]
    # 兜底只认「唯一包含」：先比图形元素，免得和「文字-开始」这类标签撞车；一个都没命中才放宽到全部
    shapes = [el for el in others if el.get("type") != "text" and want in label(el)]
    if shapes:
        return shapes[0] if len(shapes) == 1 else None
    loose = [el for el in others if want in label(el)]
    return loose[0] if len(loose) == 1 else None


def connector_end(page: dict, raw) -> tuple[dict, str | None]:
    """解析连线一端的写法，模型可以给：
      "开始框"            → 按元素名绑定
      { name: "开始框" }  → 按元素名绑定
      { id: "el_xxx" }    → 按元素 id 绑定（id 位写了名字，会按名字再试一次）
      { x: 120, y: 340 }  → 自由端点（绝对画布坐标）
    返回 (end, miss)：miss 是字符串 = 这个端点没绑定上；是 "" = 什么都没给（会退化成一个点）；
    是 None = 正常（绑上了元素，或是有坐标的自由端点）。
    """
    end = {"id": None, "anchor": "auto", "x": 0, "y": 0}
    want = ""
    free = False
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        want = str(raw).strip()
    elif isinstance(raw, dict):
        end["anchor"] = str(raw.get("anchor") or "auto") or "auto"
        key = "" if raw.get("id") in (None, "") else str(raw.get("id")).strip()
        if key:
            if any(el.get("id") == key and el.get("type") != "connector" for el in (page.get("elements") or [])):
                end["id"] = key
            else:
                want = key
        if not end["id"] and not want and raw.get("name") is not None:
            want = str(raw.get("name")).strip()
        x = _num_or_none(raw.get("x"))
        y = _num_or_none(raw.get("y"))
        if x is not None:
            end["x"] = x
        if y is not None:
            end["y"] = y
        free = (x is not None or y is not None) and (end["x"] != 0 or end["y"] != 0)
    if not end["id"] and want:
        hit = element_by_name(page, want)
        if hit:
            end["id"] = hit.get("id")
        else:
            return end, want   # 名字没对上：保留原坐标，线停在原地而不是跳回原点
    if not end["id"] and not free:
        return end, ""
    return end, None


def settle_connectors(page: dict, logs: list, mark) -> None:
    """一页里的连线统一收敛：端点按名字 / 坐标补全成元素 id，几何重算回 x/y/w/h 与 props.d。

    绑不上的端点写进 logs 告警，让模型在下一轮能看见并改正。
    """
    elements = page.get("elements") or []

    def lookup(element_id):
        return next((el for el in elements
                     if el.get("id") == element_id and el.get("type") != "connector"), None)

    for el in elements:
        if el.get("type") != "connector":
            continue
        props = el.setdefault("props", {})
        a, a_miss = connector_end(page, props.get("from"))
        b, b_miss = connector_end(page, props.get("to"))
        props["from"] = a
        props["to"] = b
        bad = []
        if a_miss is not None:
            bad.append(f"from「{a_miss}」" if a_miss else "from")
        if b_miss is not None:
            bad.append(f"to「{b_miss}」" if b_miss else "to")
        if bad:
            name = f"「{el.get('name')}」" if el.get("name") else ""
            logs.append(f"⚠ 连线{name}的 {'、'.join(bad)} 没绑定到元素，只画出一个点；"
                        "请在 props.from / props.to 里写目标元素的名字（或 {x,y} 绝对坐标）")
        if connector_geom.resolve_connector(el, lookup):
            mark(el.get("id"))


# ---------------------------------------------------------------- 主入口

def apply_actions(manifest: dict, actions: list, *, page_index: int = -1,
                  page_id: str = "", scope: dict | None = None) -> dict:
    """执行一批 Action；返回 {changed, errors, logs, pageStructureChanged, selected, scopeWarnings}。

    容错策略与前端一致：单条动作失败只记录 errors，不中断其余动作。
    作用域只认动作里的显式声明（见 target_pages），不读指令正文；由动作声明出来的目标还必须
    落在调用方提交任务时声明的落盘范围（scope）之内，越界会被 scope_clamp 收窄并记入
    scopeWarnings。
    """
    pages = manifest.get("pages") or []
    scope = normalize_scope(scope)
    home_page = None
    if page_id:
        home_page = next((p for p in pages if p.get("id") == page_id), None)
    if home_page is None and 0 <= int(page_index or 0) < len(pages):
        home_page = pages[int(page_index or 0)]
    # 归属页也要落在范围内：动作没声明目标页时会落到 home_page
    if scope["pageIndexes"]:
        allowed_pages = [pages[i] for i in scope["pageIndexes"] if 0 <= i < len(pages)]
        if allowed_pages and home_page not in allowed_pages:
            home_page = allowed_pages[0]

    changed: list[str] = []
    errors: list[str] = []
    logs: list[str] = []
    selected: list[str] = []
    scope_warnings: list[str] = []
    touched: list[str] = []          # 本次改动落在哪些页（id）：连线几何要在整批动作跑完之后统一补算
    page_structure_changed = False

    def mark(element_id):
        if element_id and element_id not in changed:
            changed.append(element_id)

    def touch(page):
        pid = (page or {}).get("id")
        if pid and pid not in touched:
            touched.append(pid)

    for i, action in enumerate(actions or []):
        try:
            if not isinstance(action, dict):
                raise McpError("动作必须是对象")
            op = action.get("op")

            # 落盘前先把动作收进本次提交声明的范围：模型的 allPages / 跨页 pageIds 一律不得越界
            warning = scope_clamp(action, scope, manifest)
            if warning:
                scope_warnings.append(f"第 {i + 1} 个动作（{op}）：{warning}")
                logs.append(f"⚠ 落盘范围收窄：{warning}")

            if op == "update":
                alias_hits = _style_alias_hits(action.get("props") or {})
                if alias_hits:
                    logs.append(_style_alias_warning(alias_hits))
                hits = resolve_targets(manifest, action, home_page)
                for hit in hits:
                    for path, value in (action.get("props") or {}).items():
                        set_path(hit["el"], path, value)
                    mark(hit["el"].get("id"))
                    touch(hit["page"])
                logs.append(f"更新 {len(hits)} 个元素" if len(hits) > 1 else f"更新 {hits[0]['el'].get('id')}")

            elif op == "insert":
                pages_hit = target_pages(manifest, action, home_page)
                if not pages_hit:
                    raise McpError("目标页面不存在")
                raw = json.loads(json.dumps(action.get("element") or {}))
                alias_hits = sorted(
                    _style_alias_hits([f"style.{k}" for k in (raw.get("style") or {})])
                    + _style_alias_hits([f"props.{k}" for k in (raw.get("props") or {})])
                )
                if alias_hits:
                    logs.append(_style_alias_warning(alias_hits))
                for page in pages_hit:
                    # 每页一份独立副本，否则多页共用同一个 props/style 对象
                    el = normalize_element(json.loads(json.dumps(raw)), page)
                    page.setdefault("elements", []).append(el)
                    mark(el.get("id"))
                    touch(page)
                etype = raw.get("type") or "text"
                logs.append(f"在 {len(pages_hit)} 页新增 {etype}" if len(pages_hit) > 1 else f"新增 {etype}")

            elif op == "delete":
                hits = resolve_targets(manifest, action, home_page)
                for hit in hits:
                    page, el = hit["page"], hit["el"]
                    page["elements"] = [e for e in page.get("elements", []) if e.get("id") != el.get("id")]
                    mark(el.get("id"))
                    touch(page)
                logs.append(f"删除 {len(hits)} 个元素" if len(hits) > 1 else f"删除 {hits[0]['el'].get('id')}")

            elif op == "reorder":
                hits = resolve_targets(manifest, action, home_page)
                for hit in hits:
                    page, el = hit["page"], hit["el"]
                    rest = [e for e in sorted_elements(page) if e.get("id") != el.get("id")]
                    raw_index = action.get("index")
                    index = len(rest) if raw_index is None else int(_number(raw_index, len(rest)))
                    index = max(0, min(len(rest), index))
                    rest.insert(index, el)
                    for z, item in enumerate(rest):
                        item["z"] = z + 1
                        mark(item.get("id"))
                    touch(page)
                logs.append(f"调整层级 {len(hits)} 个元素")

            elif op == "animate":
                hits = resolve_targets(manifest, action, home_page)
                spec = action.get("anim")
                if spec is None or spec is False or (isinstance(spec, dict) and spec.get("enabled") is False):
                    for hit in hits:
                        hit["el"]["anim"] = None
                        mark(hit["el"].get("id"))
                        touch(hit["page"])
                    logs.append(f"清除动画 {len(hits)} 个元素")
                else:
                    if not isinstance(spec, dict):
                        raise McpError("animate 需要 anim 字段")
                    for hit in hits:
                        el = hit["el"]
                        # 允许只给 preset，也允许只给 keyframes；两者都给时 keyframes 优先
                        if spec.get("preset") in ANIM_PRESETS:
                            base = anim_from_preset(spec["preset"], spec)
                        else:
                            base = {**(el.get("anim") or {}), **spec}
                        merged = {
                            **base, **spec,
                            "preset": spec.get("preset") or ("none" if spec.get("keyframes") else base.get("preset")),
                        }
                        anim = normalize_anim(merged)
                        if not anim:
                            raise McpError(f"动画参数无效：{json.dumps(spec, ensure_ascii=False)}")
                        el["anim"] = anim
                        mark(el.get("id"))
                        touch(hit["page"])
                    logs.append(f"设置动画 {len(hits)} 个元素")

            elif op == "page.update":
                pages_hit = target_pages(manifest, action, home_page)
                if not pages_hit:
                    raise McpError("目标页面不存在")
                for page in pages_hit:
                    for path, value in (action.get("props") or {}).items():
                        if path == "background" and isinstance(value, dict):
                            page["background"] = {**(page.get("background") or {}), **value}
                        else:
                            set_path(page, path, value)
                    touch(page)
                logs.append(f"更新 {len(pages_hit)} 个页面属性" if len(pages_hit) > 1 else "更新页面属性")

            elif op == "page.insert":
                page = new_page(manifest, (action.get("page") or {}).get("name"))
                bg = (action.get("page") or {}).get("background")
                if isinstance(bg, dict):
                    page["background"] = {**page["background"], **bg}
                manifest.setdefault("pages", []).append(page)
                touch(page)
                logs.append(f"新增页面 {page['name']}")
                page_structure_changed = True

            elif op == "page.delete":
                total = len(manifest.get("pages") or [])
                raw_index = action.get("index")
                if raw_index is None:
                    index = (manifest["pages"].index(home_page) if home_page in (manifest.get("pages") or []) else int(page_index or 0))
                else:
                    index = int(_number(raw_index, -1))
                if total <= 1:
                    raise McpError("至少保留一页")
                if not (0 <= index < total):
                    raise McpError("目标页面不存在")
                manifest["pages"].pop(index)
                logs.append("删除页面")
                page_structure_changed = True

            elif op == "select":
                ids = action.get("ids") or [action.get("id")]
                selected = [x for x in ids if x]
                logs.append(f"选中 {len(selected)} 个元素")

            else:
                raise McpError(f"不支持的动作：{op}")

        except McpError as exc:
            errors.append(f"第 {i + 1} 个动作({(action or {}).get('op') if isinstance(action, dict) else '?'}) 失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第 {i + 1} 个动作失败：{exc}")

    # 连线落盘：模型只写「从谁连到谁」，绑定关系与几何（包围盒 / 主路径 / 箭头）在这里补算，
    # 导出侧（index.html / PPTX）因此完全不需要知道绑定关系。整批动作跑完再算，
    # 端点才能引用同一批里刚插入的元素。
    for pid in touched:
        page = next((p for p in (manifest.get("pages") or []) if p.get("id") == pid), None)
        if page:
            settle_connectors(page, logs, mark)

    return {
        "changed": changed,
        "errors": errors,
        "logs": logs,
        "pageStructureChanged": page_structure_changed,
        "selected": selected,
        "scopeWarnings": scope_warnings,
    }


def record_history(manifest: dict, instruction: str, summary: str, status: str = "done") -> None:
    """写入工程内的指令历史（与前端 recordHistory 同结构，供上下文里的 recentInstructions 使用）。"""
    history = manifest.setdefault("history", [])
    history.insert(0, {
        "id": new_id("h"),
        "ts": _now_ms(),
        "instruction": instruction or "",
        "summary": summary or "",
        "status": status,
    })
    del history[400:]


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
