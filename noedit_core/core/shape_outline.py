"""形状轮廓采样（web/js/render-kit.js 的 SHAPE_GEOMS + web/js/path-geom.js 的路径扁平化的 Python 复刻）。

用途：给连线求「贴合形状真实轮廓」的落点（见 connector_geom.py），以及 SVG 导出时把形状写成真矢量。纯计算，不碰 DOM。

复刻范围：
  render-kit.js  几何辅助 + SHAPE_GEOMS 的**轮廓 d 与 detail** + shapePath() / shapeSvg()
  path-geom.js   tokenize / arcToCubics / parsePath / segPoints（采样用 cubicPoints）
  detail（can / cube 的内壁、flowChart 的分隔线等附加描边）也一并复刻，导出 SVG 时要写回去。

JS 侧是唯一源；改 render-kit.js 的形状几何时这里要同步改，两者必须给出同一份几何。
"""

from __future__ import annotations

import math
import re

# ================================================================ 形状几何

_CMD_RE = re.compile(r"[-+]?(?:[0-9]*\.[0-9]+|[0-9]+\.?)(?:[eE][-+]?[0-9]+)?")


def _num(value, default=0.0) -> float:
    """与 JS 的 num(v, d) 对齐：能转成有限数就用它，否则用默认值。"""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(default)
    return n if math.isfinite(n) else float(default)


def _js_num(value) -> str:
    """数字 → JS 的 String(n) 形态（整数不带小数点，其余保留 1 位）。只用于 gnum 的产物。"""
    n = float(value)
    if n == 0:
        return "0"
    if n.is_integer():
        return str(int(n))
    return f"{n:.1f}"


def _gnum(value) -> str:
    """与 JS 的 gnum 对齐：四舍五入到 1 位小数（半数朝 +∞），再转字符串。"""
    return _js_num(math.floor(float(value) * 10 + 0.5) / 10)


def _gpts(points, close=True) -> str:
    s = ""
    for i, pt in enumerate(points):
        s += ("L" if i else "M") + _gnum(pt[0]) + " " + _gnum(pt[1])
    return s if close is False else s + "Z"


def _gpt(cx, cy, rx, ry, deg):
    """椭圆上按角度取点：0° 在右，顺时针为正（屏幕坐标 y 向下）。"""
    a = deg * math.pi / 180
    return [cx + rx * math.cos(a), cy + ry * math.sin(a)]


def _gell(cx, cy, rx, ry) -> str:
    return ("M" + _gnum(cx - rx) + " " + _gnum(cy)
            + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 1 0 " + _gnum(cx + rx) + " " + _gnum(cy)
            + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 1 0 " + _gnum(cx - rx) + " " + _gnum(cy) + "Z")


def _garc(cx, cy, rx, ry, a0, a1) -> str:
    """开放弧线（只描边用）：与 render-kit.js 的 garc 对齐。"""
    p0 = _gpt(cx, cy, rx, ry, a0)
    p1 = _gpt(cx, cy, rx, ry, a1)
    large = 1 if abs(a1 - a0) > 180 else 0
    return ("M" + _gnum(p0[0]) + " " + _gnum(p0[1])
            + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 " + str(large) + " 1 "
            + _gnum(p1[0]) + " " + _gnum(p1[1]))


def _gsector(cx, cy, rx, ry, a0, a1) -> str:
    """扇形（圆心 → 起弧 → 扫到终点 → 闭合）。"""
    p0 = _gpt(cx, cy, rx, ry, a0)
    p1 = _gpt(cx, cy, rx, ry, a1)
    large = 1 if abs(a1 - a0) > 180 else 0
    return ("M" + _gnum(cx) + " " + _gnum(cy) + "L" + _gnum(p0[0]) + " " + _gnum(p0[1])
            + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 " + str(large) + " 1 "
            + _gnum(p1[0]) + " " + _gnum(p1[1]) + "Z")


def _gstar(cx, cy, rx, ry, n, rot, ratio) -> str:
    """n 角星：rot 起始角（弧度），rx/ry 外接椭圆半径，ratio 内外半径比。"""
    pts = []
    for i in range(n * 2):
        k = ratio if i % 2 else 1
        a = rot + i * math.pi / n
        pts.append([cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)])
    return _gpts(pts)


def _gpoly(W, H, n, rot) -> str:
    """占满 W×H 外接椭圆的内接正多边形（rot 起始角，弧度）。"""
    pts = []
    for i in range(n):
        a = rot + i * 2 * math.pi / n
        pts.append([W / 2 + W / 2 * math.cos(a), H / 2 + H / 2 * math.sin(a)])
    return _gpts(pts)


def _grrect(W, H, tl, tr, br, bl) -> str:
    """四角圆角矩形（角半径各自独立，0 表示直角）。"""
    m = min(W, H) / 2
    tl = max(0, min(tl, m)); tr = max(0, min(tr, m))
    br = max(0, min(br, m)); bl = max(0, min(bl, m))
    d = "M" + _gnum(tl) + " 0L" + _gnum(W - tr) + " 0"
    if tr:
        d += "A" + _gnum(tr) + " " + _gnum(tr) + " 0 0 1 " + _gnum(W) + " " + _gnum(tr)
    d += "L" + _gnum(W) + " " + _gnum(H - br)
    if br:
        d += "A" + _gnum(br) + " " + _gnum(br) + " 0 0 1 " + _gnum(W - br) + " " + _gnum(H)
    d += "L" + _gnum(bl) + " " + _gnum(H)
    if bl:
        d += "A" + _gnum(bl) + " " + _gnum(bl) + " 0 0 1 0 " + _gnum(H - bl)
    d += "L0 " + _gnum(tl)
    if tl:
        d += "A" + _gnum(tl) + " " + _gnum(tl) + " 0 0 1 " + _gnum(tl) + " 0"
    return d + "Z"


def _gsrect(W, H, tl, tr, br, bl) -> str:
    """四角切角矩形。"""
    return _gpts([[tl, 0], [W - tr, 0], [W, tr], [W, H - br], [W - br, H], [bl, H], [0, H - bl], [0, tl]])


def _gnum_or(value, default=0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(default)
    return n if math.isfinite(n) else float(default)


def _gcorners(p, st, dflt):
    """取四角圆角半径，顺序 左上/右上/右下/左下。

    优先级：逐角 props.radiusTL/TR/BR/BL > 统一 style.borderRadius(>0) > 形状自带比例 dflt。
    空串 / None 视为「未设」；统一圆角为 0 也视为「未设」，交给形状比例。
    """
    p = p or {}
    uni = _gnum_or((st or {}).get("borderRadius"), 0)

    def pick(key, d):
        v = p.get(key)
        if v is not None and v != "":
            try:
                n = float(v)
            except (TypeError, ValueError):
                n = float("nan")
            if math.isfinite(n):
                return max(0.0, n)
        return uni if uni > 0 else max(0.0, d)

    return [pick("radiusTL", dflt[0]), pick("radiusTR", dflt[1]),
            pick("radiusBR", dflt[2]), pick("radiusBL", dflt[3])]


#: 形状名 → {d, detail, rule}。与 render-kit.js 的 SHAPE_GEOMS 一一对应（缺省 rule 为 evenodd）。
SHAPE_GEOMS = {
    "rect": lambda W, H, p, st: {"d": _rect_d(W, H, p, st)},
    "roundRect": lambda W, H, p, st: {"d": _grrect(W, H, *_gcorners(p, st, [min(W, H) * 0.16667] * 4))},
    "round1Rect": lambda W, H, p, st: {"d": _grrect(W, H, *_gcorners(p, st, [min(W, H) * 0.16667, 0, 0, 0]))},
    "round2SameRect": lambda W, H, p, st: {"d": _grrect(W, H, *_gcorners(p, st, [min(W, H) * 0.16667] * 2 + [0, 0]))},
    "round2DiagRect": lambda W, H, p, st: {"d": _grrect(W, H, *_gcorners(p, st, [min(W, H) * 0.16667, 0, min(W, H) * 0.16667, 0]))},
    "snip1Rect": lambda W, H, p, st: {"d": _gsrect(W, H, min(W, H) * 0.25, 0, 0, 0)},
    "snip2SameRect": lambda W, H, p, st: {"d": _gsrect(W, H, min(W, H) * 0.25, min(W, H) * 0.25, 0, 0)},
    "snip2DiagRect": lambda W, H, p, st: {"d": _gsrect(W, H, min(W, H) * 0.25, 0, min(W, H) * 0.25, 0)},
    "snipRoundRect": lambda W, H, p, st: {
        "d": "M" + _gnum(min(W, H) * 0.16667) + " 0L" + _gnum(W - min(W, H) * 0.25) + " 0L" + _gnum(W)
        + " " + _gnum(min(W, H) * 0.25) + "L" + _gnum(W) + " " + _gnum(H - min(W, H) * 0.25)
        + "L" + _gnum(W - min(W, H) * 0.25) + " " + _gnum(H) + "L" + _gnum(min(W, H) * 0.25) + " " + _gnum(H)
        + "L0 " + _gnum(H - min(W, H) * 0.25) + "L0 " + _gnum(min(W, H) * 0.16667)
        + "A" + _gnum(min(W, H) * 0.16667) + " " + _gnum(min(W, H) * 0.16667) + " 0 0 1 "
        + _gnum(min(W, H) * 0.16667) + " 0Z"
    },
    "ellipse": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2)},
    "triangle": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H], [0, H]])},
    "rtTriangle": lambda W, H, p, st: {"d": _gpts([[0, 0], [0, H], [W, H]])},
    "diamond": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]])},
    "parallelogram": lambda W, H, p, st: {"d": _gpts([[W * 0.25, 0], [W, 0], [W - W * 0.25, H], [0, H]])},
    "trapezoid": lambda W, H, p, st: {"d": _gpts([[W * 0.25, 0], [W - W * 0.25, 0], [W, H], [0, H]])},
    "nonIsoscelesTrapezoid": lambda W, H, p, st: {"d": _gpts([[0, 0], [W - W * 0.25, 0], [W, H], [0, H]])},
    "pentagon": lambda W, H, p, st: {"d": _gpoly(W, H, 5, -math.pi / 2)},
    "hexagon": lambda W, H, p, st: {"d": _gpoly(W, H, 6, 0)},
    "heptagon": lambda W, H, p, st: {"d": _gpoly(W, H, 7, -math.pi / 2)},
    "octagon": lambda W, H, p, st: {"d": _gpoly(W, H, 8, -math.pi / 2)},
    "decagon": lambda W, H, p, st: {"d": _gpoly(W, H, 10, -math.pi / 2)},
    "dodecagon": lambda W, H, p, st: {"d": _gpoly(W, H, 12, -math.pi / 2)},
    "bevel": lambda W, H, p, st: {"d": _gsrect(W, H, min(W, H) * 0.25, min(W, H) * 0.25, min(W, H) * 0.25, min(W, H) * 0.25)},
    "plaque": lambda W, H, p, st: {"d": _grrect(W, H, min(W, H) * 0.25, min(W, H) * 0.25, min(W, H) * 0.25, min(W, H) * 0.25)},
    "cross": lambda W, H, p, st: {"d": _gpts(_plus_pts(W, H, 0.16, 0.16))},
    "mathPlus": lambda W, H, p, st: {"d": _gpts(_plus_pts(W, H, 0.09, 0.09))},
    "frame": lambda W, H, p, st: {
        "d": _gpts([[0, 0], [W, 0], [W, H], [0, H]])
        + _gpts([[min(W, H) * 0.25, min(W, H) * 0.25], [W - min(W, H) * 0.25, min(W, H) * 0.25],
                 [W - min(W, H) * 0.25, H - min(W, H) * 0.25], [min(W, H) * 0.25, H - min(W, H) * 0.25]])
    },
    "halfFrame": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, min(W, H) * 0.3],
                                                  [min(W, H) * 0.3, min(W, H) * 0.3], [min(W, H) * 0.3, H], [0, H]])},
    "corner": lambda W, H, p, st: {"d": _gpts([[W, 0], [W, min(W, H) * 0.35], [min(W, H) * 0.35, min(W, H) * 0.35],
                                               [min(W, H) * 0.35, H], [0, H], [0, 0]])},
    "diagStripe": lambda W, H, p, st: {"d": _gpts([[0, H], [0, H - min(W, H) * 0.3], [W - min(W, H) * 0.3, 0],
                                                   [W, 0], [W, min(W, H) * 0.3], [min(W, H) * 0.3, H]])},
    "donut": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2) + _gell(W / 2, H / 2, W * 0.3, H * 0.3)},
    "can": lambda W, H, p, st: {"d": _can_d(W, H), "detail": _can_detail(W, H)},
    "cube": lambda W, H, p, st: {"d": _gpts([[0, min(W, H) * 0.25], [W - min(W, H) * 0.25, min(W, H) * 0.25],
                                             [W - min(W, H) * 0.25, H], [0, H]]),
                                 "detail": _cube_detail(W, H)},
    "teardrop": lambda W, H, p, st: {"d": _teardrop_d(W, H)},
    "blockArc": lambda W, H, p, st: {"d": _block_arc_d(W, H)},
    "pie": lambda W, H, p, st: {"d": _gsector(W / 2, H / 2, W / 2, H / 2, -90, 180)},
    "pieWedge": lambda W, H, p, st: {"d": _gsector(W / 2, H / 2, W / 2, H / 2, 0, 90)},
    "chord": lambda W, H, p, st: {"d": _chord_d(W, H)},
    "moon": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2) + _gell(W / 2 + W * 0.28, H / 2, W / 2 * 0.9, H / 2 * 0.9)},
    "arc": lambda W, H, p, st: {"d": "", "detail": _garc(W / 2, H / 2, W / 2, H / 2, 180, 0)},
    "sun": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, min(W, H) / 2 * 0.58, min(W, H) / 2 * 0.58),
                                "detail": _sun_detail(W, H)},
    "cloud": lambda W, H, p, st: {"d": _cloud_d(W, H, H)},
    "heart": lambda W, H, p, st: {"d": _heart_d(W, H)},
    "lightningBolt": lambda W, H, p, st: {"d": _gpts([[W * 0.42, 0], [W * 0.78, 0], [W * 0.5, H * 0.44],
                                                      [W * 0.78, H * 0.44], [W * 0.3, H], [W * 0.44, H * 0.56],
                                                      [W * 0.18, H * 0.56]])},
    "smileyFace": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2)
                                       + _gell(W / 2 - W * 0.18, H / 2 - H * 0.16, W * 0.07, H * 0.1)
                                       + _gell(W / 2 + W * 0.18, H / 2 - H * 0.16, W * 0.07, H * 0.1),
                                       "detail": _garc(W / 2, H / 2, W / 2 * 0.62, H / 2 * 0.62, 25, 155)},
    "noSmoking": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2), "detail": _nosmoking_detail(W, H)},
    # 直线：与画布 shapeSvg / OOXML 预设 line 同源 —— 左上角连到右下角的对角线。
    # （旧版是水平中线，(2×210) 这类竖直细线会缩成一个点，与 PPTX 对不上。）
    "line": lambda W, H, p, st: {"d": "", "detail": "M0 0L" + _gnum(W) + " " + _gnum(H)},
    "star4": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 4, -math.pi / 2, 0.38)},
    "star5": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 5, -math.pi / 2, 0.382)},
    "star6": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 6, -math.pi / 2, 0.5)},
    "star7": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 7, -math.pi / 2, 0.55)},
    "star8": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 8, -math.pi / 2, 0.55)},
    "star10": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 10, -math.pi / 2, 0.62)},
    "star12": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 12, -math.pi / 2, 0.68)},
    "star16": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 16, -math.pi / 2, 0.75)},
    "star24": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 24, -math.pi / 2, 0.82)},
    "star32": lambda W, H, p, st: {"d": _gstar(W / 2, H / 2, W / 2, H / 2, 32, -math.pi / 2, 0.87)},
    "rightArrow": lambda W, H, p, st: {"d": _gpts([[0, H * 0.25], [W * 0.6, H * 0.25], [W * 0.6, 0], [W, H / 2],
                                                   [W * 0.6, H], [W * 0.6, H * 0.75], [0, H * 0.75]])},
    "leftArrow": lambda W, H, p, st: {"d": _gpts([[0, H / 2], [W * 0.4, 0], [W * 0.4, H * 0.25], [W, H * 0.25],
                                                  [W, H * 0.75], [W * 0.4, H * 0.75], [W * 0.4, H]])},
    "upArrow": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H * 0.4], [W * 0.75, H * 0.4], [W * 0.75, H],
                                                [W * 0.25, H], [W * 0.25, H * 0.4], [0, H * 0.4]])},
    "downArrow": lambda W, H, p, st: {"d": _gpts([[W / 2, H], [0, H * 0.6], [W * 0.25, H * 0.6], [W * 0.25, 0],
                                                  [W * 0.75, 0], [W * 0.75, H * 0.6], [W, H * 0.6]])},
    "leftRightArrow": lambda W, H, p, st: {"d": _gpts([[0, H / 2], [W * 0.3, 0], [W * 0.3, H * 0.25], [W * 0.7, H * 0.25],
                                                       [W * 0.7, 0], [W, H / 2], [W * 0.7, H], [W * 0.7, H * 0.75],
                                                       [W * 0.3, H * 0.75], [W * 0.3, H]])},
    "upDownArrow": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H * 0.3], [W * 0.75, H * 0.3], [W * 0.75, H * 0.7],
                                                    [W, H * 0.7], [W / 2, H], [W * 0.25, H * 0.7], [W * 0.25, H * 0.3],
                                                    [0, H * 0.3]])},
    "quadArrow": lambda W, H, p, st: {"d": _quad_arrow_d(W, H)},
    "leftRightUpArrow": lambda W, H, p, st: {"d": _left_right_up_arrow_d(W, H)},
    "bentArrow": lambda W, H, p, st: {"d": _bent_arrow_d(W, H)},
    "uturnArrow": lambda W, H, p, st: {"d": _uturn_arrow_d(W, H)},
    "leftUpArrow": lambda W, H, p, st: {"d": _left_right_up_arrow_d(W, H)},
    "notchedRightArrow": lambda W, H, p, st: {"d": _gpts([[0, H * 0.25], [W * 0.6, H * 0.25], [W * 0.6, 0], [W, H / 2],
                                                         [W * 0.6, H], [W * 0.6, H * 0.75], [0, H * 0.75],
                                                         [W * 0.18, H / 2]])},
    "chevron": lambda W, H, p, st: {"d": _gpts([[0, 0], [W - W * 0.25, 0], [W, H / 2], [W - W * 0.25, H],
                                                [0, H], [W * 0.25, H / 2]])},
    "homePlate": lambda W, H, p, st: {"d": _gpts([[0, 0], [W - W * 0.25, 0], [W, H / 2], [W - W * 0.25, H], [0, H]])},
    "flowChartProcess": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, H], [0, H]])},
    "flowChartDecision": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]])},
    "flowChartTerminator": lambda W, H, p, st: {"d": _grrect(W, H, min(W, H) / 2, min(W, H) / 2, min(W, H) / 2, min(W, H) / 2)},
    "flowChartDocument": lambda W, H, p, st: {"d": _flow_document_d(W, H)},
    "flowChartPredefinedProcess": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, H], [0, H]]),
                                                        "detail": _predefined_detail(W, H)},
    "flowChartInternalStorage": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, H], [0, H]]),
                                                      "detail": _internal_storage_detail(W, H)},
    "flowChartConnector": lambda W, H, p, st: {"d": _gell(W / 2, H / 2, W / 2, H / 2)},
    "flowChartSort": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]]),
                                          "detail": _hline_detail(W, H)},
    "flowChartExtract": lambda W, H, p, st: {"d": _gpts([[W / 2, 0], [W, H], [0, H]])},
    "flowChartMerge": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W / 2, H]])},
    "flowChartMagneticDisk": lambda W, H, p, st: {"d": _can_d(W, H), "detail": _can_detail(W, H)},
    "flowChartOffpageConnector": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, H * 0.7], [W / 2, H], [0, H * 0.7]])},
    "wedgeRectCallout": lambda W, H, p, st: {"d": _gpts([[0, 0], [W, 0], [W, H * 0.8], [W * 0.3, H * 0.8],
                                                         [W * 0.12, H], [W * 0.22, H * 0.8], [0, H * 0.8]])},
    "cloudCallout": lambda W, H, p, st: {"d": _cloud_d(W, H, H * 0.72) + _gell(W * 0.3, H * 0.88, W * 0.07, H * 0.08)
                                         + _gell(W * 0.18, H * 0.97, W * 0.045, H * 0.05), "rule": "nonzero"},
    "flag": lambda W, H, p, st: {"d": _flag_d(W, H), "rule": "nonzero"},
}


def _rect_d(W, H, p, st) -> str:
    """矩形：四角圆角都为 0 时是直角矩形，否则走圆角矩形（矩形族全靠 style.borderRadius 起效）。"""
    c = _gcorners(p, st, [0, 0, 0, 0])
    if not any(c):
        return _gpts([[0, 0], [W, 0], [W, H], [0, H]])
    return _grrect(W, H, c[0], c[1], c[2], c[3])


def _plus_pts(W, H, txr, tyr):
    """十字 / 加号的 12 个顶点（txr / tyr 是横竖臂的相对半宽）。"""
    tx = W * txr
    ty = H * tyr
    a = W / 2 - tx
    b = W / 2 + tx
    c = H / 2 - ty
    e = H / 2 + ty
    return [[a, 0], [b, 0], [b, c], [W, c], [W, e], [b, e], [b, H], [a, H], [a, e], [0, e], [0, c], [a, c]]


def _can_d(W, H) -> str:
    """圆柱 / 磁盘：上下两条弧 + 左右两条竖边。"""
    rx = W / 2
    ry = min(W, H) * 0.15
    return ("M0 " + _gnum(ry) + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 0 1 " + _gnum(W) + " " + _gnum(ry)
            + "L" + _gnum(W) + " " + _gnum(H - ry) + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 0 1 0 "
            + _gnum(H - ry) + "Z")


def _can_detail(W, H) -> str:
    """圆柱 / 磁盘的顶面椭圆（只描边）。"""
    rx = W / 2
    ry = min(W, H) * 0.15
    return _gell(rx, ry, rx, ry)


def _cube_detail(W, H) -> str:
    """立体的顶面与右侧面折线。"""
    k = min(W, H) * 0.25
    return ("M0 " + _gnum(k) + "L" + _gnum(k) + " 0L" + _gnum(W) + " 0L" + _gnum(W - k) + " " + _gnum(k)
            + "M" + _gnum(W) + " 0L" + _gnum(W) + " " + _gnum(H - k) + "L" + _gnum(W - k) + " " + _gnum(H))


def _sun_detail(W, H) -> str:
    """太阳的 12 道放射线。"""
    cx, cy = W / 2, H / 2
    R = min(W, H) / 2
    r = R * 0.58
    out = ""
    for i in range(12):
        p0 = _gpt(cx, cy, r, r, i * 30)
        p1 = _gpt(cx, cy, R, R, i * 30)
        out += "M" + _gnum(p0[0]) + " " + _gnum(p0[1]) + "L" + _gnum(p1[0]) + " " + _gnum(p1[1])
    return out


def _nosmoking_detail(W, H) -> str:
    """禁烟记号：一道斜杠。"""
    cx, cy = W / 2, H / 2
    k = min(W, H) * 0.36
    return ("M" + _gnum(cx - k) + " " + _gnum(cy + k) + "L" + _gnum(cx + k) + " " + _gnum(cy - k))


def _hline_detail(W, H) -> str:
    """水平中线（直线 / 流程-排序共用）。"""
    return "M0 " + _gnum(H / 2) + "L" + _gnum(W) + " " + _gnum(H / 2)


def _predefined_detail(W, H) -> str:
    """流程-预定义过程：左右两条竖线。"""
    a = W * 0.12
    b = W * 0.88
    return ("M" + _gnum(a) + " 0L" + _gnum(a) + " " + _gnum(H)
            + "M" + _gnum(b) + " 0L" + _gnum(b) + " " + _gnum(H))


def _internal_storage_detail(W, H) -> str:
    """流程-内存储：顶部横线 + 左侧竖线。"""
    return ("M0 " + _gnum(H * 0.2) + "L" + _gnum(W) + " " + _gnum(H * 0.2)
            + "M" + _gnum(W * 0.2) + " 0L" + _gnum(W * 0.2) + " " + _gnum(H))


def _teardrop_d(W, H) -> str:
    cx, cy, rx, ry = W / 2, H / 2, W / 2, H / 2
    return ("M" + _gnum(W) + " 0Q" + _gnum(cx + rx * 0.15) + " " + _gnum(cy - ry * 0.95) + " " + _gnum(cx)
            + " " + _gnum(cy - ry) + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 1 1 "
            + _gnum(cx + rx) + " " + _gnum(cy) + "Q" + _gnum(cx + rx * 0.95) + " " + _gnum(cy - ry * 0.15)
            + " " + _gnum(W) + " 0Z")


def _block_arc_d(W, H) -> str:
    cx, cy, rx, ry = W / 2, H / 2, W / 2, H / 2
    irx, iry = rx * 0.6, ry * 0.6
    p0 = _gpt(cx, cy, rx, ry, -90)
    p1 = _gpt(cx, cy, rx, ry, 180)
    q0 = _gpt(cx, cy, irx, iry, 180)
    q1 = _gpt(cx, cy, irx, iry, -90)
    return ("M" + _gnum(p0[0]) + " " + _gnum(p0[1]) + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 1 1 "
            + _gnum(p1[0]) + " " + _gnum(p1[1]) + "L" + _gnum(q0[0]) + " " + _gnum(q0[1])
            + "A" + _gnum(irx) + " " + _gnum(iry) + " 0 1 0 " + _gnum(q1[0]) + " " + _gnum(q1[1]) + "Z")


def _chord_d(W, H) -> str:
    cx, cy, rx, ry = W / 2, H / 2, W / 2, H / 2
    p0 = _gpt(cx, cy, rx, ry, -60)
    p1 = _gpt(cx, cy, rx, ry, 60)
    return ("M" + _gnum(p0[0]) + " " + _gnum(p0[1]) + "A" + _gnum(rx) + " " + _gnum(ry) + " 0 1 1 "
            + _gnum(p1[0]) + " " + _gnum(p1[1]) + "Z")


def _cloud_d(W, H, t) -> str:
    """云：t 是「云团纵向尺度」（云形标注会把它压到 0.72H）。"""
    return ("M" + _gnum(W * 0.18) + " " + _gnum(t * 0.85)
            + "C" + _gnum(W * 0.02) + " " + _gnum(t * 0.85) + " " + _gnum(W * 0.02) + " " + _gnum(t * 0.6)
            + " " + _gnum(W * 0.16) + " " + _gnum(t * 0.57)
            + "C" + _gnum(W * 0.11) + " " + _gnum(t * 0.3) + " " + _gnum(W * 0.34) + " " + _gnum(t * 0.24)
            + " " + _gnum(W * 0.44) + " " + _gnum(t * 0.36)
            + "C" + _gnum(W * 0.52) + " " + _gnum(t * 0.13) + " " + _gnum(W * 0.79) + " " + _gnum(t * 0.15)
            + " " + _gnum(W * 0.8) + " " + _gnum(t * 0.4)
            + "C" + _gnum(W * 1.0) + " " + _gnum(t * 0.4) + " " + _gnum(W * 1.02) + " " + _gnum(t * 0.85)
            + " " + _gnum(W * 0.86) + " " + _gnum(t * 0.85) + "Z")


def _heart_d(W, H) -> str:
    return ("M" + _gnum(W / 2) + " " + _gnum(H * 0.95)
            + "C" + _gnum(-W * 0.1) + " " + _gnum(H * 0.55) + " " + _gnum(W * 0.12) + " " + _gnum(H * 0.05)
            + " " + _gnum(W / 2) + " " + _gnum(H * 0.28)
            + "C" + _gnum(W * 0.88) + " " + _gnum(H * 0.05) + " " + _gnum(W * 1.1) + " " + _gnum(H * 0.55)
            + " " + _gnum(W / 2) + " " + _gnum(H * 0.95) + "Z")


def _flow_document_d(W, H) -> str:
    return ("M0 0L" + _gnum(W) + " 0L" + _gnum(W) + " " + _gnum(H * 0.85)
            + "C" + _gnum(W * 0.75) + " " + _gnum(H) + " " + _gnum(W * 0.25) + " " + _gnum(H * 1.1)
            + " 0 " + _gnum(H * 0.85) + "Z")


def _quad_arrow_d(W, H) -> str:
    m = min(W, H)
    hw, hl, sh = m * 0.18, m * 0.28, m * 0.09
    mx, my = W / 2, H / 2
    return _gpts([
        [mx, 0], [mx + hw, hl], [mx + sh, hl], [mx + sh, my - sh],
        [W - hl, my - sh], [W - hl, my - hw], [W, my], [W - hl, my + hw], [W - hl, my + sh],
        [mx + sh, my + sh], [mx + sh, H - hl], [mx + hw, H - hl], [mx, H], [mx - hw, H - hl],
        [mx - sh, H - hl], [mx - sh, my + sh], [hl, my + sh], [hl, my + hw], [0, my],
        [hl, my - hw], [hl, my - sh], [mx - sh, my - sh], [mx - sh, hl], [mx - hw, hl]])


def _left_right_up_arrow_d(W, H) -> str:
    """左右上箭头 / 左上箭头（render-kit.js 里这两个用的是同一份顶点）。"""
    m = min(W, H)
    hw, hl, sh = m * 0.18, m * 0.28, m * 0.09
    mx, my = W / 2, H / 2
    return _gpts([
        [mx, 0], [mx + hw, hl], [mx + sh, hl], [mx + sh, my - sh],
        [W, my - sh], [W, my + sh], [mx + sh, my + sh], [mx + sh, H], [mx - sh, H],
        [mx - sh, my + sh], [hl, my + sh], [hl, my + hw], [0, my], [hl, my - hw],
        [hl, my - sh], [mx - sh, my - sh], [mx - sh, hl], [mx - hw, hl]])


def _bent_arrow_d(W, H) -> str:
    m = min(W, H)
    sh, hw, hl = m * 0.14, m * 0.2, m * 0.24
    cx = W - hw
    return _gpts([[0, H], [0, H - 2 * sh], [cx + sh, H - 2 * sh], [cx + sh, hl], [W, hl],
                  [cx, 0], [cx - hw, hl], [cx - sh, hl], [cx - sh, H]])


def _uturn_arrow_d(W, H) -> str:
    m = min(W, H)
    sh, hl = m * 0.14, m * 0.24
    a = 2 * sh
    return _gpts([[0, H], [0, 0], [W, 0], [W, H - hl], [W - sh, H], [W - a, H - hl],
                  [W - a, a], [a, a], [a, H]])


def _flag_d(W, H) -> str:
    x0 = W * 0.09
    return (_gpts([[0, 0], [x0, 0], [x0, H], [0, H]])
            + "M" + _gnum(x0) + " 0L" + _gnum(W) + " 0"
            + "C" + _gnum(W * 0.75) + " " + _gnum(H * 0.2) + " " + _gnum(W * 0.6) + " " + _gnum(H * 0.1)
            + " " + _gnum(W * 0.45) + " " + _gnum(H * 0.28)
            + "C" + _gnum(W * 0.3) + " " + _gnum(H * 0.45) + " " + _gnum(W * 0.2) + " " + _gnum(H * 0.4)
            + " " + _gnum(x0) + " " + _gnum(H * 0.5) + "Z")


def shape_geometry(props, w, h, style=None) -> dict:
    """形状的完整几何 {d, detail, rule}；与 render-kit.js 的 shapeSvg 同源。

    d 是轮廓，detail 是只描边的附加线（可为空），rule 是填充规则（形状一律 evenodd，
    甜甜圈 / 边框 / 月亮靠它挖洞）。
    """
    p = props or {}
    st = style if isinstance(style, dict) else (p.get("$style") if isinstance(p.get("$style"), dict) else {})
    W = max(1.0, _num(w, _num(p.get("$w"), 220)))
    H = max(1.0, _num(h, _num(p.get("$h"), 140)))
    geom = SHAPE_GEOMS.get(str(p.get("shape") or "")) or SHAPE_GEOMS["rect"]
    g = geom(W, H, p, st) or {}
    return {"d": g.get("d") or "", "detail": g.get("detail") or "", "rule": g.get("rule") or "evenodd"}


def shape_path(props, w, h, style=None) -> str:
    """形状元素的轮廓 d；与 render-kit.js 的 ACRender.shapePath 同源。"""
    return shape_geometry(props, w, h, style)["d"]


# ================================================================ 路径扁平化（path-geom.js 的复刻）


def _tokenize(d):
    """切词：命令字母与数字分开，逗号 / 空白只作分隔。"""
    s = str(d or "")
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if ("a" <= c <= "z") or ("A" <= c <= "Z"):
            out.append(c)
            i += 1
            continue
        if c.isspace() or c == ",":
            i += 1
            continue
        m = _CMD_RE.match(s, i)
        if not m:
            i += 1
            continue
        out.append(float(m.group(0)))
        i = m.end()
    return out


def _arc_to_cubics(x1, y1, rx, ry, phi_deg, large_arc, sweep, x2, y2):
    """椭圆弧 → 若干三次贝塞尔（SVG 规范 F.6.5 的端点参数化），返回 [[c1x,c1y,c2x,c2y,x,y], ...]。"""
    if not rx or not ry:
        return [[x1, y1, x1, y1, x2, y2]]
    phi = (phi_deg or 0) * math.pi / 180
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)
    dx2 = (x1 - x2) / 2
    dy2 = (y1 - y2) / 2
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    rx = abs(rx)
    ry = abs(ry)
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    sign = 1 if large_arc != sweep else -1
    co = sign * math.sqrt(max(0.0, num / den)) if den else 0.0
    cxp = co * (rx * y1p) / ry
    cyp = co * -(ry * x1p) / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        length = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        if not length:
            return 0.0
        a = math.acos(max(-1.0, min(1.0, dot / length)))
        return -a if ux * vy - uy * vx < 0 else a

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry
    theta1 = angle(1, 0, ux, uy)
    dtheta = angle(ux, uy, vx, vy)
    if not sweep and dtheta > 0:
        dtheta -= math.pi * 2
    if sweep and dtheta < 0:
        dtheta += math.pi * 2
    count = max(1, math.ceil(abs(dtheta) / (math.pi / 2)))
    delta = dtheta / count
    k = (4 / 3) * math.tan(delta / 4)

    def at(a):
        ex = rx * math.cos(a)
        ey = ry * math.sin(a)
        return [cos_p * ex - sin_p * ey + cx, sin_p * ex + cos_p * ey + cy]

    def deriv(a):
        ex = -rx * math.sin(a)
        ey = ry * math.cos(a)
        return [cos_p * ex - sin_p * ey, sin_p * ex + cos_p * ey]

    segs = []
    th = theta1
    for _ in range(count):
        th2 = th + delta
        p1 = at(th)
        p2 = at(th2)
        d1 = deriv(th)
        d2 = deriv(th2)
        segs.append([p1[0] + k * d1[0], p1[1] + k * d1[1],
                     p2[0] - k * d2[0], p2[1] - k * d2[1], p2[0], p2[1]])
        th = th2
    return segs


def _push_node(sp, x, y, h_in=None, h_out=None):
    if not sp:
        return
    sp["nodes"].append({"x": x, "y": y, "hIn": h_in or None, "hOut": h_out or None})


def _last_node(sp):
    return sp["nodes"][-1] if (sp and sp["nodes"]) else None


def _dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def parse_path(d):
    """SVG path 数据 → 节点树 [{closed, nodes:[{x,y,hIn,hOut}]}]。

    支持 M/L/H/V/C/S/Q/T/A/Z 及其相对形式；Q/T 转成等价的 C，A 拆成若干 C。
    不认识 / 写坏的命令跳过（已解析的部分照常返回）。
    """
    toks = _tokenize(d)
    subpaths = []
    sp = None
    cx = cy = 0.0
    sx = sy = 0.0
    prev_ctrl = None
    prev_qctrl = None
    last_cmd = ""
    i = 0
    n = len(toks)

    def num():
        nonlocal i
        v = toks[i] if i < n else None
        i += 1
        return v if isinstance(v, float) else 0.0

    while i < n:
        cmd = toks[i]
        if isinstance(cmd, str):
            i += 1
        else:                                   # 隐式重复上一条命令
            cmd = "L" if last_cmd == "M" else ("l" if last_cmd == "m" else last_cmd)
        up = cmd.upper()
        rel = cmd != up
        bx = cx if rel else 0.0
        by = cy if rel else 0.0
        if up == "M":
            cx = num(); cy = num(); sx = cx; sy = cy
            sp = {"closed": False, "nodes": []}
            _push_node(sp, cx, cy)
            subpaths.append(sp)
            prev_ctrl = None; prev_qctrl = None
        elif up == "L":
            cx = bx + num(); cy = by + num()
            _push_node(sp, cx, cy)
            prev_ctrl = None; prev_qctrl = None
        elif up == "H":
            cx = bx + num()
            _push_node(sp, cx, cy)
            prev_ctrl = None; prev_qctrl = None
        elif up == "V":
            cy = by + num()
            _push_node(sp, cx, cy)
            prev_ctrl = None; prev_qctrl = None
        elif up == "C":
            x1 = bx + num(); y1 = by + num()
            x2 = bx + num(); y2 = by + num()
            cx = bx + num(); cy = by + num()
            last = _last_node(sp)
            if last:
                last["hOut"] = {"x": x1, "y": y1}
            _push_node(sp, cx, cy, {"x": x2, "y": y2})
            prev_ctrl = {"x": x2, "y": y2}; prev_qctrl = None
        elif up == "S":
            x2 = bx + num(); y2 = by + num()
            cx = bx + num(); cy = by + num()
            last = _last_node(sp)
            px = last["x"] if last else cx
            py = last["y"] if last else cy
            h = ({"x": 2 * px - prev_ctrl["x"], "y": 2 * py - prev_ctrl["y"]} if prev_ctrl
                 else {"x": px, "y": py})
            if last:
                last["hOut"] = h
            _push_node(sp, cx, cy, {"x": x2, "y": y2})
            prev_ctrl = {"x": x2, "y": y2}; prev_qctrl = None
        elif up == "Q":
            qx = bx + num(); qy = by + num()
            cx = bx + num(); cy = by + num()
            last = _last_node(sp)
            px = last["x"] if last else cx
            py = last["y"] if last else cy
            if last:
                last["hOut"] = {"x": px + (2 / 3) * (qx - px), "y": py + (2 / 3) * (qy - py)}
            _push_node(sp, cx, cy, {"x": cx + (2 / 3) * (qx - cx), "y": cy + (2 / 3) * (qy - cy)})
            prev_ctrl = None; prev_qctrl = {"x": qx, "y": qy}
        elif up == "T":
            last = _last_node(sp)
            px = last["x"] if last else cx
            py = last["y"] if last else cy
            qx = 2 * px - prev_qctrl["x"] if prev_qctrl else px
            qy = 2 * py - prev_qctrl["y"] if prev_qctrl else py
            cx = bx + num(); cy = by + num()
            if last:
                last["hOut"] = {"x": px + (2 / 3) * (qx - px), "y": py + (2 / 3) * (qy - py)}
            _push_node(sp, cx, cy, {"x": cx + (2 / 3) * (qx - cx), "y": cy + (2 / 3) * (qy - cy)})
            prev_ctrl = None; prev_qctrl = {"x": qx, "y": qy}
        elif up == "A":
            rx = num(); ry = num(); rot = num(); large = num(); sweep = num()
            x = bx + num(); y = by + num()
            for s in _arc_to_cubics(cx, cy, rx, ry, rot, bool(large), bool(sweep), x, y):
                last = _last_node(sp)
                if last:
                    last["hOut"] = {"x": s[0], "y": s[1]}
                _push_node(sp, s[4], s[5], {"x": s[2], "y": s[3]})
            cx = x; cy = y
            prev_ctrl = None; prev_qctrl = None
        elif up == "Z":
            if sp:
                sp["closed"] = True
                nodes = sp["nodes"]
                # 闭合命令隐式画回起点：末节点正好落在起点且没有出控制点时并掉，免得留一个重合节点
                if len(nodes) > 1:
                    last = nodes[-1]
                    head = nodes[0]
                    if not last["hOut"] and _dist(last, head) < 0.01:
                        if last["hIn"]:
                            head["hIn"] = last["hIn"]
                        nodes.pop()
            cx = sx; cy = sy
            prev_ctrl = None; prev_qctrl = None
        else:
            break                               # 不认识的命令：停在这里，已解析的部分照常返回
        last_cmd = cmd
        if up == "Z":
            last_cmd = "M"
    return [s for s in subpaths if s["nodes"]]


def _cubic_points(p0, c1, c2, p1, steps):
    out = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        a = mt * mt * mt
        b = 3 * mt * mt * t
        c = 3 * mt * t * t
        d = t * t * t
        out.append({
            "x": a * p0["x"] + b * c1["x"] + c * c2["x"] + d * p1["x"],
            "y": a * p0["y"] + b * c1["y"] + c * c2["y"] + d * p1["y"],
        })
    return out


def seg_points(sp, i, steps=16):
    """一段（i → i+1，闭合时末段回绕）的采样点，含两端。"""
    ns = sp["nodes"]
    a = ns[i]
    b = ns[(i + 1) % len(ns)]
    if a["hOut"] or b["hIn"]:
        return _cubic_points(a, a["hOut"] or a, b["hIn"] or b, b, steps)
    return [{"x": a["x"], "y": a["y"]}, {"x": b["x"], "y": b["y"]}]


def outline_polygon(el, box):
    """绑定元素的轮廓采样点（元素局部坐标 0..w / 0..h）；拿不到轮廓时返回 None。

    形状元素走 SHAPE_GEOMS，路径元素直接用 props.d；文本 / 图片 / 表格等本来就是矩形，
    返回 None 让调用方退回包围盒落点。
    """
    el = el or {}
    props = el.get("props") if isinstance(el.get("props"), dict) else {}
    kind = el.get("type")
    if kind == "shape":
        d = shape_path(props, box["w"], box["h"], el.get("style"))
    elif kind == "path":
        d = str(props.get("d") or "")
    else:
        return None
    if not d:
        return None
    subs = parse_path(d)
    sp = subs[0] if subs else None          # 第一个子路径 = 外轮廓（甜甜圈 / 边框这类取外层）
    if not sp or len(sp["nodes"]) < 3:
        return None
    pts = []
    count = len(sp["nodes"]) if sp["closed"] else len(sp["nodes"]) - 1
    for i in range(count):
        pts.extend(seg_points(sp, i, 16)[:-1])
    return pts if len(pts) >= 3 else None
