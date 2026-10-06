"""连线几何内核（web/js/connector-geom.js 的 Python 复刻）。

把「两端的绑定关系」解析成一份可存储、可渲染、可导出的静态几何。纯计算，不碰 DOM，
画布 / 缩略图 / HTML 导出 / PPTX 共用同一份结果。

落点贴合形状真实轮廓：形状 / 路径元素的轮廓由 shape_outline.py 采样（复刻 render-kit.js 的
SHAPE_GEOMS），把包围盒候选点沿该边推到轮廓上；其它元素本来就是矩形，退回包围盒落点。

数据约定（都存在元素的 props 里）：
  from / to  { id, anchor, x, y }
    id      绑定元素的 id；为空 = 自由端点
    anchor  'auto' | 'c' | 'l' | 'r' | 't' | 'b'（auto = 按另一端的相对位置自动选边）
    x / y   绝对画布坐标；端点绑定了元素时由解析结果不断刷新（目标被删后线也不会跳回原点）
  route        'straight' | 'elbow' | 'curve'
  corner       折线拐角的圆角半径
  arrowStartType / arrowEndType / arrowSize   两端箭头的类型与大小。类型取
               none 无 / triangle 实心三角 / hollowTriangle 空心三角 / open 开放箭头 /
               diamond 实心菱形 / hollowDiamond 空心菱形 / stealth 燕尾箭头。
               老数据只写了 arrowStart / arrowEnd 布尔开关时按兼容处理（true = 实心三角）

解析结果全部写回元素，导出侧因此不需要知道任何绑定关系：
  el.x / el.y / el.w / el.h            包围盒（元素框 = 几何包围盒）
  props.d                              元素局部坐标下的主路径
  props.arrowStartPath / arrowEndPath  两端箭头的路径（局部坐标；闭合的以 Z 收尾）
  props.arrowStartPaint / arrowEndPaint  箭头画法：fill 实心 / hollow 空心（白底描边）/ stroke 开放（只描边）
"""

from __future__ import annotations

import math

from . import shape_outline

CONNECTOR_ROUTES = [("straight", "直线"), ("elbow", "折线"), ("curve", "曲线")]


def _num(value, default=0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(default)
    return n if math.isfinite(n) else float(default)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _round2(value):
    """与 JS Math.round(v*100)/100 对齐（半数朝 +∞ 取整，负数也一样）。"""
    return math.floor(value * 100 + 0.5) / 100


def _f(value) -> str:
    """数字 → 紧凑字符串（最多 2 位小数）。"""
    r = _round2(value)
    if r == 0:
        return "0"
    return f"{r:.2f}".rstrip("0").rstrip(".")


def norm_route(value) -> str:
    """走线方式归一：认不出的一律当折线（折线最中性，也最像原理图）。"""
    route = str(value or "")
    return route if route in ("straight", "curve") else "elbow"


def box_of(el) -> dict:
    el = el or {}
    x = _num(el.get("x"), 0)
    y = _num(el.get("y"), 0)
    w = max(0.0, _num(el.get("w"), 0))
    h = max(0.0, _num(el.get("h"), 0))
    return {"x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2}


def _norm_dir(v) -> dict:
    length = math.hypot(v["x"], v["y"])
    if length > 1e-6:
        return {"x": v["x"] / length, "y": v["y"] / length}
    return {"x": 1.0, "y": 0.0}


def _side_of(dx, dy) -> str:
    """auto 锚点：按「另一端在本元素中心的哪个方位」挑边，横竖哪边差得多就走哪边。"""
    if abs(dx) >= abs(dy):
        return "r" if dx >= 0 else "l"
    return "b" if dy >= 0 else "t"


def _box_anchor(box, side, ref) -> dict:
    """某条边上的落点（包围盒版）：沿这条边朝 ref 投影，并夹在 0.1~0.9 之间（免得贴着角的尖上）。"""
    if side == "c":
        return {"x": box["cx"], "y": box["cy"]}
    if side in ("l", "r"):
        t = _clamp((ref["y"] - box["y"]) / box["h"], 0.1, 0.9) if box["h"] > 0 else 0.5
        x = box["x"] if side == "l" else box["x"] + box["w"]
        return {"x": x, "y": box["y"] + box["h"] * t}
    t = _clamp((ref["x"] - box["x"]) / box["w"], 0.1, 0.9) if box["w"] > 0 else 0.5
    y = box["y"] if side == "t" else box["y"] + box["h"]
    return {"x": box["x"] + box["w"] * t, "y": y}


def _push_to_outline(poly, box, side, p) -> dict:
    """把包围盒候选点朝元素内部推到形状轮廓上：左右边沿水平走、上下边沿垂直走，
    取这条线上遇到的第一个轮廓交点。该方向上没有交点时原样返回候选点。"""
    lx = p["x"] - box["x"]
    ly = p["y"] - box["y"]
    horizontal = side in ("l", "r")
    hits = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if horizontal:
            if (a["y"] <= ly < b["y"]) or (b["y"] <= ly < a["y"]):
                hits.append(a["x"] + (b["x"] - a["x"]) * (ly - a["y"]) / (b["y"] - a["y"]))
        elif (a["x"] <= lx < b["x"]) or (b["x"] <= lx < a["x"]):
            hits.append(a["y"] + (b["y"] - a["y"]) * (lx - a["x"]) / (b["x"] - a["x"]))
    if not hits:
        return p
    if side == "l":
        return {"x": box["x"] + min(hits), "y": p["y"]}
    if side == "r":
        return {"x": box["x"] + max(hits), "y": p["y"]}
    if side == "t":
        return {"x": p["x"], "y": box["y"] + min(hits)}
    return {"x": p["x"], "y": box["y"] + max(hits)}


def _anchor_point(box, side, ref, el) -> dict:
    """某条边上的落点：先按包围盒取候选点，再推到绑定元素的真实轮廓上。

    轮廓拿不到（文本 / 图片 / 表格等本来就是矩形，或形状几何缺失）时与改前完全一致。
    """
    p = _box_anchor(box, side, ref)
    if side == "c" or not el:
        return p
    poly = shape_outline.outline_polygon(el, box)
    return _push_to_outline(poly, box, side, p) if poly else p


def _exit_dir(box, side, ref) -> dict:
    """出线方向：左右边水平向外、上下边垂直向外；中心锚点直接朝另一端。"""
    if side == "l":
        return {"x": -1.0, "y": 0.0}
    if side == "r":
        return {"x": 1.0, "y": 0.0}
    if side == "t":
        return {"x": 0.0, "y": -1.0}
    if side == "b":
        return {"x": 0.0, "y": 1.0}
    return _norm_dir({"x": ref["x"] - box["cx"], "y": ref["y"] - box["cy"]})


def _ref_point(end, lookup) -> dict:
    """另一端的「参考点」：绑定了就取元素中心，自由端点就取自身的绝对坐标。"""
    bound = lookup(end.get("id")) if (end and end.get("id")) else None
    if bound:
        b = box_of(bound)
        return {"x": b["cx"], "y": b["cy"]}
    return {"x": _num((end or {}).get("x"), 0), "y": _num((end or {}).get("y"), 0)}


def _resolve_end(end, ref, lookup) -> dict:
    """解析一端 → 落点 / 出线方向 / 绑定状态。"""
    e = end or {}
    bound = lookup(e.get("id")) if e.get("id") else None
    if not bound:
        point = {"x": _num(e.get("x"), 0), "y": _num(e.get("y"), 0)}
        return {"point": point, "dir": _norm_dir({"x": ref["x"] - point["x"], "y": ref["y"] - point["y"]}), "box": None}
    box = box_of(bound)
    side = str(e.get("anchor") or "auto")
    if side in ("auto", ""):
        side = _side_of(ref["x"] - box["cx"], ref["y"] - box["cy"])
    return {"point": _anchor_point(box, side, ref, bound), "dir": _exit_dir(box, side, ref), "box": box}


def _dedupe(points) -> list[dict]:
    """去掉重复点与共线的中间点（正交走线经常产出三连共线）。"""
    out: list[dict] = []
    for p in points:
        last = out[-1] if out else None
        if last and abs(last["x"] - p["x"]) < 0.01 and abs(last["y"] - p["y"]) < 0.01:
            continue
        out.append({"x": p["x"], "y": p["y"]})
    if len(out) <= 2:
        return out
    keep = [out[0]]
    for i in range(1, len(out) - 1):
        a, b, c = keep[-1], out[i], out[i + 1]
        cross = (b["x"] - a["x"]) * (c["y"] - a["y"]) - (b["y"] - a["y"]) * (c["x"] - a["x"])
        if abs(cross) < 0.01:
            continue
        keep.append(b)
    keep.append(out[-1])
    return keep


def _elbow_points(a, b, a_dir, b_dir) -> list[dict]:
    """折线折点：两端出线方向一致就用「中线换向」，一横一竖就一个 90° 拐角。"""
    h1 = abs(a_dir["x"]) >= abs(a_dir["y"])
    h2 = abs(b_dir["x"]) >= abs(b_dir["y"])
    if h1 and h2:
        mx = (a["x"] + b["x"]) / 2
        return [a, {"x": mx, "y": a["y"]}, {"x": mx, "y": b["y"]}, b]
    if not h1 and not h2:
        my = (a["y"] + b["y"]) / 2
        return [a, {"x": a["x"], "y": my}, {"x": b["x"], "y": my}, b]
    if h1:
        return [a, {"x": b["x"], "y": a["y"]}, b]
    return [a, {"x": a["x"], "y": b["y"]}, b]


def _along(start, target, radius) -> dict:
    """沿 start→target 方向、在距离 radius 处取点。"""
    dx = target["x"] - start["x"]
    dy = target["y"] - start["y"]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return {"x": start["x"], "y": start["y"]}
    return {"x": start["x"] + (dx / length) * radius, "y": start["y"] + (dy / length) * radius}


def _build_route(route, A, B, props) -> dict:
    """走线 → { ops, pts, start_ref, end_ref }；ops 是绝对坐标的操作列表，pts 供包围盒用。"""
    a = A["point"]
    b = B["point"]
    if route == "straight":
        return {"ops": [("M", a["x"], a["y"]), ("L", b["x"], b["y"])], "pts": [a, b], "start_ref": b, "end_ref": a}
    if route == "curve":
        k = _clamp(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) * 0.42, 18, 180)
        c1 = {"x": a["x"] + A["dir"]["x"] * k, "y": a["y"] + A["dir"]["y"] * k}
        c2 = {"x": b["x"] + B["dir"]["x"] * k, "y": b["y"] + B["dir"]["y"] * k}
        return {
            "ops": [("M", a["x"], a["y"]), ("C", c1["x"], c1["y"], c2["x"], c2["y"], b["x"], b["y"])],
            "pts": [a, c1, c2, b],
            "start_ref": c1,
            "end_ref": c2,
        }
    pts = _dedupe(_elbow_points(a, b, A["dir"], B["dir"]))
    ops = [("M", pts[0]["x"], pts[0]["y"])]
    radius = max(0.0, _num(props.get("corner"), 8))
    for i in range(1, len(pts) - 1):
        prev, cur, nxt = pts[i - 1], pts[i], pts[i + 1]
        r = min(radius,
                math.hypot(cur["x"] - prev["x"], cur["y"] - prev["y"]) / 2,
                math.hypot(nxt["x"] - cur["x"], nxt["y"] - cur["y"]) / 2)
        if r > 0.5:
            in_p = _along(cur, prev, r)
            out_p = _along(cur, nxt, r)
            ops.append(("L", in_p["x"], in_p["y"]))
            ops.append(("Q", cur["x"], cur["y"], out_p["x"], out_p["y"]))
        else:
            ops.append(("L", cur["x"], cur["y"]))
    ops.append(("L", pts[-1]["x"], pts[-1]["y"]))
    return {
        "ops": ops,
        "pts": pts,
        "start_ref": pts[1] if len(pts) > 1 else b,
        "end_ref": pts[-2] if len(pts) > 1 else a,
    }


def _emit_ops(ops, ox, oy) -> str:
    """绝对坐标 ops → 元素局部坐标的 SVG path 数据。"""
    parts = []
    for op in ops:
        if op[0] in ("M", "L"):
            parts.append(op[0] + _f(op[1] - ox) + " " + _f(op[2] - oy))
        elif op[0] == "Q":
            parts.append("Q" + _f(op[1] - ox) + " " + _f(op[2] - oy) + " " + _f(op[3] - ox) + " " + _f(op[4] - oy))
        elif op[0] == "C":
            parts.append("C" + _f(op[1] - ox) + " " + _f(op[2] - oy) + " " + _f(op[3] - ox) + " " + _f(op[4] - oy)
                         + " " + _f(op[5] - ox) + " " + _f(op[6] - oy))
    return "".join(parts)


ARROW_TYPES = ("none", "triangle", "hollowTriangle", "open", "diamond", "hollowDiamond", "stealth")


def arrow_type_of(props, end: str) -> str:
    """读一端的箭头类型；没写新字段的老数据按布尔开关兼容（true = 实心三角）。

    与 web/js/connector-geom.js 的 arrowTypeOf 同一套规则。
    """
    props = props or {}
    raw = props.get("arrowStartType") if end == "start" else props.get("arrowEndType")
    raw = "" if raw is None else str(raw)
    if raw in ARROW_TYPES:
        return raw
    if raw:
        return "none"
    on = props.get("arrowStart") if end == "start" else props.get("arrowEnd")
    return "triangle" if on else "none"


def _arrow_head(kind: str, tip, ref, size: float):
    """一端箭头的几何：尖在 tip，沿 (ref - tip) 方向退开。返回 { points, closed, paint }；
    paint 为 fill 实心 / hollow 空心（白底描边）/ stroke 开放（只描边两条线）。类型 none 返回 None。"""
    if not kind or kind == "none":
        return None
    u = _norm_dir({"x": ref["x"] - tip["x"], "y": ref["y"] - tip["y"]})
    n = {"x": -u["y"], "y": u["x"]}
    apex = {"x": tip["x"], "y": tip["y"]}

    def at(a, b):
        return {"x": tip["x"] + u["x"] * a + n["x"] * b, "y": tip["y"] + u["y"] * a + n["y"] * b}

    if kind == "open":
        return {"points": [at(size, size * 0.55), apex, at(size, -size * 0.55)],
                "closed": False, "paint": "stroke"}
    if kind in ("diamond", "hollowDiamond"):
        length = size * 1.3
        hw = size * 0.42
        return {"points": [apex, at(length / 2, hw), at(length, 0), at(length / 2, -hw)],
                "closed": True, "paint": "fill" if kind == "diamond" else "hollow"}
    if kind == "stealth":
        hw = size * 0.42
        return {"points": [apex, at(size, hw), at(size * 0.65, 0), at(size, -hw)],
                "closed": True, "paint": "fill"}
    hw = size * 0.4
    return {"points": [apex, at(size, hw), at(size, -hw)],
            "closed": True, "paint": "hollow" if kind == "hollowTriangle" else "fill"}


def _poly_d(points, ox, oy, closed: bool = True) -> str:
    return "".join(("L" if i else "M") + _f(p["x"] - ox) + " " + _f(p["y"] - oy)
                   for i, p in enumerate(points)) + ("" if closed is False else "Z")


def resolve_connector(el, lookup=None) -> bool:
    """主入口：把一条连线的几何重算一遍并写回元素（x/y/w/h、props.d、两个箭头路径）。

    lookup(id) → 元素或 None（由调用方提供，且必须排除连线自身，避免依赖成环）。
    返回是否发生了变化（供调用方决定要不要重绘 / 记入 changed）。
    """
    if not el or el.get("type") != "connector":
        return False
    props = el.get("props")
    if not isinstance(props, dict):
        props = el["props"] = {}
    from_end = props.get("from")
    if not isinstance(from_end, dict):
        from_end = props["from"] = {"id": None, "anchor": "auto", "x": 0, "y": 0}
    to_end = props.get("to")
    if not isinstance(to_end, dict):
        to_end = props["to"] = {"id": None, "anchor": "auto", "x": 0, "y": 0}
    find = lookup if callable(lookup) else (lambda _id: None)

    A = _resolve_end(from_end, _ref_point(to_end, find), find)
    B = _resolve_end(to_end, _ref_point(from_end, find), find)
    # 记住最后已知的绝对坐标：目标被删掉之后线停在原地，而不是跳回 (0,0)
    from_end["x"] = _round2(A["point"]["x"])
    from_end["y"] = _round2(A["point"]["y"])
    to_end["x"] = _round2(B["point"]["x"])
    to_end["y"] = _round2(B["point"]["y"])

    built = _build_route(norm_route(props.get("route")), A, B, props)
    style = el.get("style") if isinstance(el.get("style"), dict) else {}
    sw = max(0.0, _num(style.get("borderWidth"), 2))
    size = _clamp(_num(props.get("arrowSize"), 10), 3, 60)
    start_head = _arrow_head(arrow_type_of(props, "start"), A["point"], built["start_ref"], size)
    end_head = _arrow_head(arrow_type_of(props, "end"), B["point"], built["end_ref"], size)

    xs, ys = [], []
    for p in built["pts"]:
        xs.append(p["x"])
        ys.append(p["y"])
    for head in (start_head, end_head):
        for p in ((head or {}).get("points") or []):
            xs.append(p["x"])
            ys.append(p["y"])
    pad = sw / 2 + 1
    minx = min(xs) - pad
    miny = min(ys) - pad
    nx = _round2(minx)
    ny = _round2(miny)
    nw = _round2(max(1.0, max(xs) + pad - minx))
    nh = _round2(max(1.0, max(ys) + pad - miny))

    d = _emit_ops(built["ops"], nx, ny)
    sp = _poly_d(start_head["points"], nx, ny, start_head["closed"]) if start_head else ""
    ep = _poly_d(end_head["points"], nx, ny, end_head["closed"]) if end_head else ""
    sp_paint = start_head["paint"] if start_head else ""
    ep_paint = end_head["paint"] if end_head else ""

    changed = (
        abs(_num(el.get("x"), 0) - nx) > 0.01
        or abs(_num(el.get("y"), 0) - ny) > 0.01
        or abs(_num(el.get("w"), 0) - nw) > 0.01
        or abs(_num(el.get("h"), 0) - nh) > 0.01
        or str(props.get("d") or "") != d
        or str(props.get("arrowStartPath") or "") != sp
        or str(props.get("arrowEndPath") or "") != ep
        or str(props.get("arrowStartPaint") or "") != sp_paint
        or str(props.get("arrowEndPaint") or "") != ep_paint
    )

    el["x"] = nx
    el["y"] = ny
    el["w"] = nw
    el["h"] = nh
    props["d"] = d
    props["arrowStartPath"] = sp
    props["arrowEndPath"] = ep
    props["arrowStartPaint"] = sp_paint
    props["arrowEndPaint"] = ep_paint
    return changed
