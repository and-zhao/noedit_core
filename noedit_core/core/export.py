"""导出能力：静态 HTML / PNG（透明底、96~600 DPI） / PDF / SVG（矢量优先） / PPTX（矢量 + 截图混合）。

Vector / raster 是每个元素自己的选择（props.rasterMode）：默认「矢量优先」，能原生表达的
走矢量、保不了的效果按画布截图贴回；标成「稳截图」的元素一律贴图。

表格 / 统计图 / 代码块 / 公式在 PPTX 与 SVG 里也尽力走矢量：导出前用无头浏览器把这一页
渲染一次，量回表格列宽行高、代码与公式的逐行逐色排版、统计图的原生 SVG（见 _attach_measure），
再照着摆成原生表格 / 原生图表 / 真文本图元；量不到或保不住时才回退截图。
"""

from __future__ import annotations

import base64
import html
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR, EXPORT_DIR_NAME, atomic_write_text, ensure_dir
from .projects import (
    CHART_PALETTE,
    _clean_runs,
    _line_offsets,
    _line_segments,
    has_math,
    normalize_manifest,
    render_kit_signature,
    render_page_html,
    render_probe_html,
    render_raster_sheet_html,
    render_static_html,
    tokens,
)
from .shape_outline import shape_geometry
from .connector_geom import arrow_type_of

PX_TO_EMU = 9525  # 96 DPI 下 1px = 9525 EMU
PT_PER_PX = 0.75  # 96 DPI 下 1px = 0.75pt


def _prefix_for(project_root: Path, out_dir: Path) -> str:
    rel = os.path.relpath(project_root, out_dir)
    rel = rel.replace("\\", "/")
    return "" if rel == "." else rel.rstrip("/") + "/"


def _file_prefix(project_root: Path) -> str:
    """绝对 file:// 前缀：导出成单个文件（PDF）时素材仍需能加载。"""
    return project_root.resolve().as_uri().rstrip("/") + "/"


def _safe_name(manifest: dict) -> str:
    raw = str(manifest.get("name") or "export")
    return re.sub(r'[\\/:*?"<>|]+', "_", raw).strip() or "export"


def _unique_path(target: Path) -> Path:
    """同名文件已存在时，在扩展名前插「 (2)」「 (3)」…，避免每次导出都覆盖上一份。

    导出的文件名默认取自工程名，固定不变；不去重的话连导两次第二次就悄悄盖掉第一次。
    序号规则与 Windows 资源管理器的「副本」一致：`名字.svg` → `名字 (2).svg`。
    """
    if not target.exists():
        return target
    for i in range(2, 10000):
        candidate = target.with_name(f"{target.stem} ({i}){target.suffix}")
        if not candidate.exists():
            return candidate
    return target


def _resolve_out_dir(project_root: Path, out_dir: str) -> Path:
    return ensure_dir(Path(out_dir)) if out_dir else ensure_dir(project_root / EXPORT_DIR_NAME)


# ---------------------------------------------------------------- 静态 HTML
def export_static_html(project_path: str, manifest: dict, out_path: str = "", out_dir: str = "") -> dict:
    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    if out_path:
        target = Path(out_path)
    else:
        target = _unique_path(_resolve_out_dir(root, out_dir) / f"{_safe_name(manifest)}.html")
    ensure_dir(target.parent)
    if not str(target).lower().endswith((".html", ".htm")):
        target = _unique_path(target.with_suffix(".html"))
    prefix = _prefix_for(root, target.parent)
    target.write_text(render_static_html(manifest, prefix), encoding="utf-8")
    return {"ok": True, "path": str(target), "message": f"已导出静态 HTML：{target}", "format": "html"}


# ---------------------------------------------------------------- PDF
def _find_browser() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def export_pdf(project_path: str, manifest: dict, out_dir: str = "") -> dict:
    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    target_dir = _resolve_out_dir(root, out_dir)
    target = _unique_path(target_dir / f"{_safe_name(manifest)}.pdf")

    browser = _find_browser()
    if not browser:
        return {
            "ok": False,
            "path": "",
            "message": "未找到 Microsoft Edge 或 Chrome，无法打印 PDF。请安装 Edge 后重试（也可直接使用「静态 HTML」并在浏览器中打印）。",
        }

    print_html = target_dir / f".{target.stem}.print.html"
    print_html.write_text(render_static_html(manifest, _file_prefix(root)), encoding="utf-8")

    profile_dir = Path(tempfile.mkdtemp(prefix="noedit_core-pdf-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--user-data-dir={profile_dir}",
        f"--print-to-pdf={target}",
        print_html.resolve().as_uri(),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "path": "", "message": "打印 PDF 超时（超过 180 秒），请重试。"}
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    if not target.exists():
        detail = (proc.stderr or b"").decode("utf-8", "ignore").strip()[:400]
        return {"ok": False, "path": "", "message": f"PDF 生成失败（浏览器返回码 {proc.returncode}）。{detail}"}
    try:
        print_html.unlink()
    except OSError:
        pass
    return {
        "ok": True,
        "path": str(target),
        "message": f"已导出 PDF（{len(manifest.get('pages', []))} 页）：{target}",
        "format": "pdf",
    }


# ---------------------------------------------------------------- PPTX
# 混合导出：能编辑的内容（文本 / 链接 / 图片 / 视频 / 微场景）走 OOXML 矢量映射；
# 纯视觉效果（形状、分组容器、带特殊滤镜的图片）与「属性多到 OOXML 表达不了」的内容
# （代码块的语言着色、表格的列宽/合并/高亮、统计图的十几种图形、含 LaTeX 公式的文本）
# 交给无头浏览器逐页截图、再按元素裁切贴图。
# 之所以要截图：透明度 / 圆角 / 投影 / 模糊 / 旋转 / 语法着色 / 公式排版在 OOXML 里没有等价表达，
# 硬做矢量映射只会"全变样"。找不到 Edge / Chrome 时整体退回矢量映射：效果打折，但一定可用。
RASTER_SCALE = 2  # 截图倍率（2x 保证在幻灯片里缩放后依然锐利）
RASTER_PAD = 48  # 元素四周最少多截一圈，容纳投影 / 模糊 / 旋转向外溢出的像素
RASTER_GUTTER = 16  # 格子表里格与格之间的间隔，防止相邻元素像素互相渗进对方的格
RASTER_SHEET_MAX = 2048  # 单张格子表的长边上限（CSS px）；超了就拆成多张，免得截出超大图

#: python-pptx 能直接嵌进幻灯片的图片格式（见 pptx.opc.spec.image_content_types）。
#: 别的（svg / webp / ico / avif…）add_picture 直接抛错，导出前必须先转成 PNG（见 _pptx_ready_image）。
PPTX_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".tif", ".tiff", ".wmf", ".emf", ".wdp"}

_CSS_SHADOW = re.compile(
    r"(?P<x>-?\d+(?:\.\d+)?)(?:px)?\s+(?P<y>-?\d+(?:\.\d+)?)(?:px)?\s+(?P<blur>\d+(?:\.\d+)?)px"
    r"(?:\s+(?P<spread>-?\d+(?:\.\d+)?)(?:px)?)?\s+(?P<color>rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})"
)


def _num(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _emu(el: dict, key: str, default: float = 0):
    from pptx.util import Emu

    return Emu(int(_num(el.get(key), default) * PX_TO_EMU))


def _pt(px, default: float = 12):
    from pptx.util import Pt

    return Pt(round(_num(px, default) * PT_PER_PX, 1))


def _rgb(value: str, default: str = "000000"):
    from pptx.dml.color import RGBColor

    raw = str(value or "").strip().lower()
    if raw.startswith(("rgb(", "rgba(")):
        # CSS 函数色：画布上大量 rgba()/rgb() 写法，必须先解析，否则会落成 default 的白色。
        text = _css_color(raw)[0]
    else:
        text = raw.lstrip("#")
        if len(text) == 4:                       # #rgba → #rrggbbaa
            text = "".join(c * 2 for c in text)
        if len(text) == 8:                       # #rrggbbaa → #rrggbb
            text = text[:6]
        if len(text) == 3:
            text = "".join(c * 2 for c in text)
    if not re.fullmatch(r"[0-9a-f]{6}", (text or "").lower()):
        text = default
    try:
        return RGBColor.from_string(text.upper())
    except ValueError:
        return RGBColor.from_string(default.upper())


def _color_alpha(value) -> float:
    """颜色字符串自带的不透明度：rgba() 第 4 位 / #rrggbbaa / #rgba。

    CSS 里 `rgba(0,0,0,0)` 表示全透明、`rgba(56,189,248,0.16)` 表示 16% 蓝，这个 alpha 必须
    跟着颜色一起带到 OOXML，否则画布上的淡环 / 浅底导出后会变成实心白或深灰。
    """
    raw = str(value or "").strip().lower()
    if raw in ("transparent", "none"):
        return 0.0
    if raw.startswith(("rgb(", "rgba(")):
        return _css_color(raw)[1]
    text = raw.lstrip("#")
    if len(text) == 8:
        try:
            return int(text[6:], 16) / 255
        except ValueError:
            return 1.0
    if len(text) == 4:
        try:
            return int(text[3] * 2, 16) / 255
        except ValueError:
            return 1.0
    return 1.0


def _alpha(opacity) -> str:
    """0..1 的不透明度 → OOXML 的 1/1000 百分比（100000 = 不透明）。"""
    return str(max(0, min(100000, int(round(_num(opacity, 1) * 100000)))))


def _align(value: str):
    from pptx.enum.text import PP_ALIGN

    return {
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
        "justify": PP_ALIGN.JUSTIFY,
    }.get(str(value or "").lower(), PP_ALIGN.LEFT)


def _anchor(value: str):
    from pptx.enum.text import MSO_ANCHOR

    return {
        "middle": MSO_ANCHOR.MIDDLE,
        "bottom": MSO_ANCHOR.BOTTOM,
    }.get(str(value or "").lower(), MSO_ANCHOR.TOP)


_GENERIC_FONTS = {
    "serif": "Times New Roman",
    "sans-serif": "Arial",
    "monospace": "Consolas",
    "cursive": "Segoe Script",
    "fantasy": "Impact",
    "system-ui": "Microsoft YaHei",
    "-apple-system": "Microsoft YaHei",
    "ui-sans-serif": "Microsoft YaHei",
    "ui-monospace": "Consolas",
}
_CJK_HINTS = ("yahei", "pingfang", "heiti", "simhei", "simsun", "songti", "msyh", "noto sans sc",
              "noto serif sc", "source han", "hiragino", "微软雅黑", "微软", "苹方", "思源", "黑体",
              "宋体", "楷体", "兰亭")
DEFAULT_EA_FONT = "Microsoft YaHei"


def _norm_font(name: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(name or "").lower())


@lru_cache(maxsize=1)
def _installed_fonts() -> frozenset[str]:
    """本机已装字体的规范化名集合（拿不到就返回空集，不影响导出）。"""
    if os.name != "nt":
        return frozenset()
    import winreg

    found: set[str] = set()
    path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, path) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    found.add(_norm_font(winreg.EnumValue(key, i)[0]))
        except OSError:
            continue
    return frozenset(n for n in found if n)


def _font_stack(value: str) -> tuple[str, str]:
    """CSS font-family → (latin, ea)。

    CSS 的字体栈（"Georgia, serif"）不能整串写进 OOXML：PowerPoint 找不到这个名字会直接回落
    默认字体。这里逐个试字体栈，挑本机真装了的第一款给 latin；中文字体单独给 ea。
    """
    names = [raw.strip().strip("\"'").strip() for raw in str(value or "").split(",")]
    candidates = [_GENERIC_FONTS.get(n.lower(), n) for n in names if n]
    if not candidates:
        return DEFAULT_EA_FONT, DEFAULT_EA_FONT
    installed = _installed_fonts()
    # 浏览器预览时用的是"本机装了的第一款"，PPTX 里挑同一款，字体才不会变
    usable = [c for c in candidates if not installed or any(_norm_font(c) in key for key in installed)]
    latin = usable[0] if usable else candidates[0]
    ea = next((c for c in usable if _is_ea_font(c)), DEFAULT_EA_FONT)
    return latin, ea


def _is_ea_font(name: str) -> bool:
    return name == DEFAULT_EA_FONT or any(h in name.lower() for h in _CJK_HINTS)


def _fill_typeface(rPr, latin: str, ea: str = "") -> None:
    """同时写 latin / ea / cs。

    只写 a:latin 的话中文会回落到主题字体（等线/宋体）——这就是导出后"字体变了"的根因。
    """
    from pptx.oxml.ns import qn

    node = rPr.find(qn("a:latin"))
    if node is None:
        node = rPr.makeelement(qn("a:latin"), {})
        rPr.append(node)
    node.set("typeface", latin)
    prev = node
    ea = ea or latin
    for tag in ("a:ea", "a:cs"):  # 架构顺序固定为 latin → ea → cs
        node = rPr.find(qn(tag))
        if node is None:
            node = rPr.makeelement(qn(tag), {})
            prev.addnext(node)
        node.set("typeface", ea)
        prev = node


def _style_run(run, *, name: str, size, bold: bool, italic: bool, color: str,
               opacity: float = 1.0, spacing: float = 0.0,
               underline: bool = False, highlight: str = "") -> None:
    from pptx.oxml.ns import qn

    latin, ea = _font_stack(name)
    font = run.font
    font.size = size
    font.bold = bold
    font.italic = italic
    font.name = latin
    font.color.rgb = _rgb(color)
    if underline:
        font.underline = True
    rPr = run._r.get_or_add_rPr()
    _fill_typeface(rPr, latin, ea)
    if highlight:
        # 文字高亮（CSS 的 background-color）→ a:highlight；OOXML 有元素顺序要求，必须排在 a:latin 之前
        hl = rPr.makeelement(qn("a:highlight"), {})
        hl.append(rPr.makeelement(qn("a:srgbClr"), {"val": str(_rgb(highlight))}))
        anchor = rPr.find(qn("a:latin"))
        if anchor is not None:
            anchor.addprevious(hl)
        else:
            rPr.append(hl)
    if spacing:
        rPr.set("spc", str(int(round(spacing * PT_PER_PX * 100))))
    if _num(opacity, 1) < 1:
        solid = rPr.find(qn("a:solidFill"))
        clr = solid.find(qn("a:srgbClr")) if solid is not None else None
        if clr is not None:
            clr.append(clr.makeelement(qn("a:alpha"), {"val": _alpha(opacity)}))


def _set_fill(shape_or_cell, color: str, opacity: float = 1.0) -> None:
    """形状 / 单元格填充（含透明度）。

    透明度取「颜色自带的 alpha × 元素 opacity」：全透明（如 rgba(0,0,0,0)）写成无填充，
    半透明写成 solidFill + a:alpha，与画布上的 rgba() 表现一致。
    """
    from pptx.oxml.ns import qn

    alpha = _color_alpha(color) * _num(opacity, 1)
    if alpha <= 0:
        shape_or_cell.fill.background()
        return
    shape_or_cell.fill.solid()
    shape_or_cell.fill.fore_color.rgb = _rgb(color, "FFFFFF")
    if alpha >= 1:
        return
    spPr = getattr(shape_or_cell._element, "spPr", None)
    if spPr is None:
        return
    solid = spPr.find(qn("a:solidFill"))
    clr = solid.find(qn("a:srgbClr")) if solid is not None else None
    if clr is not None:
        clr.append(clr.makeelement(qn("a:alpha"), {"val": _alpha(alpha)}))


_DASH_MAP = {
    "solid": None,
    "dash": "DASH",
    "longDash": "LONG_DASH",
    "dot": "SQUARE_DOT",
    "roundDot": "ROUND_DOT",
    "dashDot": "DASH_DOT",
}
_CAP_MAP = {"butt": "flat", "round": "rnd", "square": "sq"}
_JOIN_MAP = {"miter": "a:miter", "round": "a:round", "bevel": "a:bevel"}


def _set_line(shape, style: dict, props: dict | None = None) -> None:
    """描边 → a:ln：颜色 / 宽度 / 虚线 / 线端（cap） / 拐角（join）。

    线型优先取 props.strokeDash（形状面板的新字段），兼容老的 style.borderStyle == "dashed"。
    """
    width = _num(style.get("borderWidth"))
    if width <= 0:
        return
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.oxml.ns import qn

    props = props or {}
    line = shape.line
    alpha = _color_alpha(style.get("borderColor"))
    if alpha <= 0:
        line.fill.background()   # rgba(...,0) 的描边 = 不画线
        return
    line.color.rgb = _rgb(style.get("borderColor"), "333333")
    line.width = _pt(width, 1)
    dash = str(props.get("strokeDash") or "").strip()
    if not dash:
        dash = "dash" if str(style.get("borderStyle") or "solid") == "dashed" else "solid"
    member = _DASH_MAP.get(dash)
    if dash != "solid":
        style_enum = getattr(MSO_LINE_DASH_STYLE, member or "DASH", None)
        if style_enum is not None:
            line.dash_style = style_enum
    ln = shape._element.spPr.find(qn("a:ln"))
    if ln is None:
        return
    if alpha < 1:
        solid = ln.find(qn("a:solidFill"))
        clr = solid.find(qn("a:srgbClr")) if solid is not None else None
        if clr is not None:
            clr.append(clr.makeelement(qn("a:alpha"), {"val": _alpha(alpha)}))
    cap = _CAP_MAP.get(str(props.get("strokeCap") or "butt"))
    if cap:
        ln.set("cap", cap)
    join = _JOIN_MAP.get(str(props.get("strokeJoin") or "miter"))
    if join:
        for tag in ("a:round", "a:bevel", "a:miter"):
            node = ln.find(qn(tag))
            if node is not None:
                ln.remove(node)
        if not any(ln.find(qn(t)) is not None for t in ("a:round", "a:bevel", "a:miter")):
            ln.append(ln.makeelement(qn(join), {}))


def _css_color(text: str) -> tuple[str, float]:
    """CSS 颜色 → (RRGGBB, alpha)。支持 rgb()/rgba()/#rgb/#rrggbb/#rrggbbaa。"""
    raw = str(text or "").strip().lower()
    if raw.startswith(("rgb(", "rgba(")):
        inside = raw[raw.index("(") + 1: raw.rindex(")")]
        parts = [p for p in re.split(r"[,\s/]+", inside) if p]
        if len(parts) >= 3:
            comps = []
            for item in parts[:3]:
                value = float(item.rstrip("%"))
                comps.append(round(value * 2.55) if item.endswith("%") else round(value))
            color = "".join(f"{max(0, min(255, c)):02X}" for c in comps)
            alpha = 1.0
            if len(parts) >= 4:
                last = parts[3]
                alpha = float(last.rstrip("%")) / 100 if last.endswith("%") else float(last)
            return color, max(0.0, min(1.0, alpha))
    text = raw.lstrip("#")
    if len(text) == 8:
        try:
            return text[:6].upper(), int(text[6:], 16) / 255
        except ValueError:
            return "000000", 1.0
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if re.fullmatch(r"[0-9a-f]{6}", text):
        return text.upper(), 1.0
    return "000000", 1.0


def _apply_outer_shadow(shape, dx: float, dy: float, blur: float, spread: float,
                        color: str, alpha: float) -> None:
    """给形状写 a:outerShdw：偏移 (dx,dy) 定方向与距离，blur / spread 合成模糊半径。"""
    from pptx.oxml.ns import qn

    shape.shadow.inherit = False  # 先清掉主题自带阴影，再写入指定的
    spPr = shape._element.spPr
    effect = spPr.find(qn("a:effectLst"))
    if effect is None:
        effect = spPr.makeelement(qn("a:effectLst"), {})
        spPr.append(effect)
    shadow = effect.makeelement(qn("a:outerShdw"), {
        "blurRad": str(int(max(blur, spread) * PX_TO_EMU)),
        "dist": str(int(math.hypot(dx, dy) * PX_TO_EMU)),
        "dir": str(int(round(math.degrees(math.atan2(dy, dx)) * 60000)) % 21600000),
        "rotWithShape": "0",
    })
    clr = shadow.makeelement(qn("a:srgbClr"), {"val": color})
    clr.append(clr.makeelement(qn("a:alpha"), {"val": _alpha(alpha)}))
    shadow.append(clr)
    effect.append(shadow)


def _shadow_struct(style: dict) -> dict | None:
    """取元素投影：优先结构化 style.shadow，退回 legacy boxShadow 字符串（多层只取第一层）。"""
    shadow = style.get("shadow")
    if isinstance(shadow, dict):
        return shadow
    raw = str(style.get("boxShadow") or "").strip()
    if not raw or raw.lower() == "none":
        return None
    match = _CSS_SHADOW.search(raw)
    if not match:
        return None
    color, alpha = _css_color(match.group("color"))
    return {
        "dx": _num(match.group("x")), "dy": _num(match.group("y")),
        "blur": _num(match.group("blur")), "spread": _num(match.group("spread")),
        "color": "#" + color, "alpha": alpha,
    }


def _has_shadow(style: dict) -> bool:
    return _shadow_struct(style) is not None


def _set_shadow(shape, style: dict) -> None:
    """元素投影 → a:outerShdw（偏移 / 模糊 / 方向 / 颜色透明度都带上）。"""
    shadow = _shadow_struct(style)
    if not shadow:
        return
    color, _ = _css_color(shadow.get("color"))
    _apply_outer_shadow(shape,
                        _num(shadow.get("dx")), _num(shadow.get("dy")),
                        _num(shadow.get("blur")), _num(shadow.get("spread")),
                        color, _num(shadow.get("alpha"), 1))


def _set_radius(shape, style: dict, el: dict) -> None:
    """border-radius → roundRect 的 adj（半径占短边的比例）；图片则改 prstGeom。

    只在矩形几何体上生效。椭圆 / 三角形的形状不是靠 adj 描述的：椭圆的 avLst 是空的，
    给 adjustments[0] 赋值会抛 IndexError，兜底分支再把 prst 改成 roundRect，圆就直接
    变成方；三角形的 adj 是顶点位置，改它会把顶点挪歪。圆角对它们都没有意义，一律不动。
    """
    from pptx.oxml.ns import qn

    radius = _num(style.get("borderRadius"))
    if radius <= 0:
        return
    geom = shape._element.spPr.find(qn("a:prstGeom"))
    if geom is None:
        return
    if str(geom.get("prst") or "rect") not in ("rect", "roundRect"):
        return
    short = max(1.0, min(_num(el.get("w"), 1), _num(el.get("h"), 1)))
    ratio = min(0.5, radius / short)

    adjustments = getattr(shape, "adjustments", None)
    if adjustments is not None:
        try:
            adjustments[0] = ratio
            return
        except (IndexError, ValueError, TypeError):
            pass
    geom.set("prst", "roundRect")
    av = geom.find(qn("a:avLst"))
    if av is None:
        av = geom.makeelement(qn("a:avLst"), {})
        geom.append(av)
    av.append(av.makeelement(qn("a:gd"), {"name": "adj", "fmla": f"val {int(ratio * 100000)}"}))


def _set_rotation(shape, el: dict) -> None:
    deg = _num(el.get("rotate"))
    if not deg:
        return
    try:
        shape.rotation = deg % 360
    except (AttributeError, ValueError):
        pass


def _strip_theme_style(shape) -> None:
    """去掉 add_shape 自带的 <p:style>：否则 PowerPoint 会套主题填充 / 描边 / 阴影。"""
    from pptx.oxml.ns import qn

    node = shape._element.find(qn("p:style"))
    if node is not None:
        shape._element.remove(node)


def _apply_box(shape, style: dict, el: dict, props: dict | None = None) -> None:
    """把一个「有底色的盒子」的样式落到形状上：填充 / 描边 / 圆角 / 投影 / 旋转。"""
    _strip_theme_style(shape)
    props = props or {}
    # style.fill 是引擎不认的别名键（见 element-schema.json 的 aliases）：落盘时会被改写过来，
    # 这里再兜一层，免得导出旧工程时漏掉填充色。
    background = str(style.get("background") or style.get("fill") or "").strip()
    if str(props.get("fillType") or "") == "none":
        shape.fill.background()
    elif background and background not in ("transparent", "none"):
        _set_fill(shape, background, _num(el.get("opacity"), 1))
    else:
        shape.fill.background()
    _set_line(shape, style, props)
    _set_radius(shape, style, el)
    _set_shadow(shape, style)
    _set_rotation(shape, el)


def _has_box(style: dict) -> bool:
    """文本要不要用"卡片"（圆角矩形）承载：有底色 / 描边 / 投影才算。"""
    background = str(style.get("background") or "").strip()
    return bool(
        (background and background not in ("transparent", "none"))
        or _num(style.get("borderWidth")) > 0
        or _has_shadow(style)
    )


def _add_text(slide, el: dict, text: str, mono: bool = False, link: str = "") -> object:
    """文本 / 代码 → 文本框；带底色、描边或投影时改用圆角矩形卡片，保证这些效果不丢。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Emu

    style = el.get("style") or {}
    if _has_box(style):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if _num(style.get("borderRadius")) > 0 else MSO_SHAPE.RECTANGLE,
            _emu(el, "x"), _emu(el, "y"), _emu(el, "w", 200), _emu(el, "h", 60),
        )
        _apply_box(shape, style, el)
    else:
        shape = slide.shapes.add_textbox(_emu(el, "x"), _emu(el, "y"), _emu(el, "w", 200), _emu(el, "h", 60))
        _set_rotation(shape, el)

    frame = shape.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = _anchor(style.get("verticalAlign"))
    padding = style.get("padding")
    pad = int(_num(padding, 0) * PX_TO_EMU)  # HTML 里文字贴在元素边缘，PPTX 默认内边距必须清掉
    margin = 0 if pad == 0 else Emu(pad)
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = margin

    size = _pt(style.get("fontSize") or 24, 24)
    weight = str(style.get("fontWeight") or "")
    bold = weight.isdigit() and int(weight) >= 600
    italic = str(style.get("fontStyle") or "") == "italic"
    name = "Consolas" if mono else str(style.get("fontFamily") or "Microsoft YaHei")
    color = str(style.get("color") or ("E6EDF3" if mono else "1F2328"))
    opacity = _num(el.get("opacity"), 1)
    line_spacing = _num(style.get("lineHeight"))
    spacing = _num(style.get("letterSpacing"))
    paragraph_spacing = _num(style.get("paragraphSpacing"))
    indent = _num(style.get("textIndent"))
    align = _align(style.get("textAlign") or style.get("align"))

    # CSS 的 line-height 是「倍数 × 字号」；OOXML 百分比行距的基准却是「字体自然行高」（约 1.3em），
    # 照抄 1.8 会比画布大出约 30%，整块文字越往下越偏。换算成绝对磅值（1 逻辑像素 = 0.75pt）才逐行对齐。
    line_pitch = _pt(_num(style.get("fontSize"), 24) * line_spacing) if line_spacing else None
    # 导出前前端已按浏览器的真实断行结果切好行（props._wrapLines）：PPT 的换行点就与画布一致，不再各断各的。
    raw_text = str(text or "")
    wrapped = (el.get("props") or {}).get("_wrapLines")
    if isinstance(wrapped, list) and wrapped and "".join(str(x) for x in wrapped) == raw_text.replace("\n", ""):
        lines = [str(x) for x in wrapped]
    else:
        lines = raw_text.split("\n") or [""]
    # 行内富文本：把每行再按 props.runs 切成若干段，逐段套样式（仍落在同一个文本框里）
    runs = _clean_runs((el.get("props") or {}).get("runs"), len(raw_text))
    offs = _line_offsets(raw_text, lines)
    for i, line in enumerate(lines):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = align
        if line_pitch is not None:
            para.line_spacing = line_pitch
        if paragraph_spacing and i:
            para.space_before = _pt(paragraph_spacing)
        if indent and i == 0:  # CSS 的 text-indent 只缩进整块首行，PPTX 的 indent 是逐段生效
            para._p.get_or_add_pPr().set("indent", str(int(indent * PX_TO_EMU)))
        for seg_text, st in _line_segments(line, offs[i], runs):
            run = para.add_run()
            run.text = seg_text
            _style_run(run, name=name, size=size,
                       bold=bold or bool(st.get("b")),
                       italic=italic or bool(st.get("i")),
                       color=str(st.get("c") or color),
                       opacity=opacity, spacing=spacing,
                       underline=bool(st.get("u")),
                       highlight=str(st.get("bg") or ""))
            if link:
                run.hyperlink.address = link
    return shape


_SAFE_COLOR_RES = (
    re.compile(r"^#[0-9a-fA-F]{3,8}$"),
    re.compile(r"^rgba?\([0-9.,%\s]+\)$"),
    re.compile(r"^hsla?\([0-9.,%\s]+\)$"),
    re.compile(r"^[a-zA-Z]{3,20}$"),
)


def _safe_color(value, fallback: str = "") -> str:
    """只保留看上去像颜色的字符串（与 render-kit.js 的 safeColor 同一套规则）。"""
    text = str(value or "").strip()
    if not text:
        return fallback
    for rx in _SAFE_COLOR_RES:
        if rx.match(text):
            return text
    return fallback


def _code_vars(props: dict) -> dict:
    """代码块的结构化样式（IR 形态）：与 render-kit.js 的 codeVars 同一套默认值与 token。

    颜色默认值只写在 tokens.js（tokens()['code'][theme]），字号 / 内边距 / 圆角的默认值
    也只写这一处，HTML 渲染与 PPTX 写出读同一份，不再各写一套猜测值。
    """
    p = props or {}
    theme = "light" if str(p.get("theme") or "dark") == "light" else "dark"
    code_tok = (tokens().get("code") or {}).get(theme) or {}
    bg = _safe_color(p.get("bgColor"))
    fg = _safe_color(p.get("fgColor"))
    accent = _safe_color(p.get("accent"))
    return {
        "theme": theme,
        "hasBg": bool(bg),
        "hasFg": bool(fg),
        "hasAccent": bool(accent),
        "bg": bg or code_tok.get("bg", ""),
        "bar": bg or code_tok.get("bar", ""),
        "fg": fg or code_tok.get("fg", ""),
        "accent": accent or code_tok.get("accent", ""),
        "fontSize": _clamp(_num(p.get("fontSize"), 13), 6, 96),
        "lineHeight": _clamp(_num(p.get("lineHeight"), 1.55), 1, 4),
        "padding": _clamp(_num(p.get("padding"), 10), 0, 80),
        "radius": _clamp(_num(p.get("radius"), 8), 0, 40),
        "shadow": bool(p.get("shadow")),
    }


def _add_code(slide, el: dict) -> None:
    """代码块 → 深/浅色圆角卡片 + 等宽字体；行号用等宽字体预先对齐（与 HTML 的 gutter 等宽）。

    配色 / 字号 / 圆角走 _code_vars（IR 形态，与 render-kit.js 的 codeVars 同一份 token）。
    """
    props = el.get("props") or {}
    v = _code_vars(props)
    style = dict(el.get("style") or {})
    style["background"] = style.get("background") or v["bg"]
    style["color"] = style.get("color") or v["fg"]
    style["borderRadius"] = style.get("borderRadius", v["radius"])
    style["fontSize"] = style.get("fontSize") or v["fontSize"]
    style["lineHeight"] = style.get("lineHeight") or v["lineHeight"]
    if style.get("padding") is None:
        style["padding"] = v["padding"]

    code = str(props.get("code") or "")
    if props.get("lineNumbers"):
        lines = code.split("\n")
        width = len(str(len(lines)))
        code = "\n".join(f"{i + 1:>{width}}  {line}" for i, line in enumerate(lines))
    _add_text(slide, {**el, "style": style}, code, mono=True)


def _add_display_list(slide, el: dict, dp: list, href: str = "") -> int:
    """「图元清单」→ 幻灯片形状：矩形照尺寸画，文本落成文本框（文字仍可选中 / 可编辑）。

    dp 由浏览器探针量出（见 projects._PROBE_JS），坐标是元素本地坐标，这里加上元素原点。
    代码块与含公式的文本都走这条路：卡片、标题栏、圆点、语言徽标、行号、高亮行、逐行彩色
    代码 —— 一个不落地照画布摆回来，同时每一段文字都是真文本而不是像素。
    """
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Emu

    ox, oy = _num(el.get("x")), _num(el.get("y"))
    count = 0
    for prim in dp or []:
        if not isinstance(prim, dict):
            continue
        x = ox + _num(prim.get("x"))
        y = oy + _num(prim.get("y"))
        w = _num(prim.get("w"))
        h = _num(prim.get("h"))
        if w <= 0.4 or h <= 0.4:
            continue
        box = (Emu(int(x * PX_TO_EMU)), Emu(int(y * PX_TO_EMU)),
               Emu(int(w * PX_TO_EMU)), Emu(int(h * PX_TO_EMU)))
        if prim.get("k") == "s":
            # 外投影：一块看不见的矩形，只留 a:outerShdw（代码块卡片那道投影就是它）
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *box)
            _strip_theme_style(shape)
            shape.fill.background()
            shape.line.fill.background()
            _apply_outer_shadow(shape, _num(prim.get("dx")), _num(prim.get("dy")),
                                _num(prim.get("b")), 0.0,
                                str(prim.get("f") or "#000000").lstrip("#").upper(),
                                _num(prim.get("o"), 1))
            count += 1
        elif prim.get("k") == "r":
            radius = _num(prim.get("r"))
            shape = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE if radius > 0 else MSO_SHAPE.RECTANGLE, *box)
            _strip_theme_style(shape)
            shape.shadow.inherit = False
            shape.line.fill.background()
            _set_fill(shape, str(prim.get("f") or "#ffffff"), _num(prim.get("o"), 1))
            if radius > 0:
                _set_radius(shape, {"borderRadius": radius}, {"w": w, "h": h})
            count += 1
        elif prim.get("k") == "t":
            text = str(prim.get("t") or "")
            if not text.strip():
                continue
            shape = slide.shapes.add_textbox(*box)
            frame = shape.text_frame
            frame.word_wrap = False
            frame.auto_size = None
            frame.vertical_anchor = _anchor("middle")
            frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
            para = frame.paragraphs[0]
            para.alignment = _align("left")
            run = para.add_run()
            run.text = text
            _style_run(run, name=str(prim.get("f") or "Microsoft YaHei"),
                       size=_pt(_num(prim.get("s"), 14), 14),
                       bold=bool(prim.get("b")), italic=bool(prim.get("i")),
                       color=str(prim.get("c") or "#1f2328"), opacity=_num(prim.get("o"), 1),
                       spacing=_num(prim.get("sp")),
                       underline=bool(prim.get("u")), highlight=str(prim.get("hl") or ""))
            if href:
                run.hyperlink.address = href
            count += 1
    return count


def _fit_box(el: dict, props: dict, iw: int, ih: int):
    """object-fit → 图片在元素框里的实际位置 / 尺寸 / 裁切量。

    PPTX 的 add_picture 会把图拉伸到给定框，cover / contain 必须自己算：cover 裁掉溢出部分，
    contain / scale-down 缩到框内居中，否则图片会被压扁。
    """
    x, y = _num(el.get("x")), _num(el.get("y"))
    w, h = max(1.0, _num(el.get("w"), 100)), max(1.0, _num(el.get("h"), 100))
    fit = str(props.get("fit") or "cover")
    if fit == "fill" or not iw or not ih:
        return x, y, w, h, (0.0, 0.0, 0.0, 0.0)
    img_ratio, box_ratio = iw / ih, w / h
    if fit == "cover":
        if img_ratio > box_ratio:
            crop = (1 - box_ratio / img_ratio) / 2
            return x, y, w, h, (crop, crop, 0.0, 0.0)
        if img_ratio < box_ratio:
            crop = (1 - img_ratio / box_ratio) / 2
            return x, y, w, h, (0.0, 0.0, crop, crop)
        return x, y, w, h, (0.0, 0.0, 0.0, 0.0)
    dw, dh = (h * img_ratio, h) if h * img_ratio <= w else (w, w / img_ratio)
    if fit == "scale-down":
        dw, dh = min(dw, iw), min(dh, ih)
    return x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, (0.0, 0.0, 0.0, 0.0)


def _apply_picture_effects(pic, el: dict) -> None:
    """图片能直接映射的部分：翻转 / 亮度对比度 / 透明度 / 圆角 / 投影 / 旋转。"""
    from pptx.oxml.ns import qn

    props = el.get("props") or {}
    f = props.get("filter") or {}
    try:
        xfrm = pic._element.spPr.find(qn("a:xfrm"))
        if xfrm is not None:
            if props.get("flipH"):
                xfrm.set("flipH", "1")
            if props.get("flipV"):
                xfrm.set("flipV", "1")
        blip = pic._element.blipFill.blip
        opacity = _num(el.get("opacity"), 1)
        if opacity < 1:  # alphaModFix 必须排在 a:lum 之前
            blip.append(blip.makeelement(qn("a:alphaModFix"), {"amt": _alpha(opacity)}))
        bright = round((_num(f.get("brightness"), 1) - 1) * 100000)
        contrast = round((_num(f.get("contrast"), 1) - 1) * 100000)
        if bright or contrast:
            blip.append(blip.makeelement(qn("a:lum"), {"bright": str(bright), "contrast": str(contrast)}))
    except Exception:  # noqa: BLE001
        pass
    _set_radius(pic, el.get("style") or {}, el)
    _set_shadow(pic, el.get("style") or {})
    _set_rotation(pic, el)


def _svg_size(path: Path) -> tuple[int, int]:
    """读 SVG 的固有尺寸（先看 width/height，再看 viewBox），读不出来返回 (0, 0)。"""
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return 0, 0
    tag = re.search(r"<svg\b[^>]*>", head, re.IGNORECASE)
    if not tag:
        return 0, 0
    attrs = tag.group(0)
    sizes = []
    for name in ("width", "height"):
        found = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs)
        number = re.match(r"\s*([0-9]*\.?[0-9]+)", found.group(1)) if found else None
        sizes.append(float(number.group(1)) if number else 0.0)
    if sizes[0] > 0 and sizes[1] > 0:
        return int(round(sizes[0])), int(round(sizes[1]))
    view_box = re.search(r'\bviewBox\s*=\s*"([^"]*)"', attrs)
    if view_box:
        parts = re.split(r"[\s,]+", view_box.group(1).strip())
        if len(parts) == 4:
            try:
                vw, vh = float(parts[2]), float(parts[3])
            except ValueError:
                return 0, 0
            if vw > 0 and vh > 0:
                return int(round(vw)), int(round(vh))
    return 0, 0


def _rasterize_svg(path: Path, work_dir: Path, browser: str, token: str, box: tuple) -> Path | None:
    """把 SVG 交给无头浏览器栅格化成透明底 PNG（按固有尺寸，比例不变）。

    为什么不用库：SVG 是矢量，python-pptx 嵌不了；而画布上的 SVG 本来就是浏览器画的，
    导出也交回同一个浏览器画，所见即所得（cairosvg / svglib 那类渲染器对 CSS、滤镜、
    渐变支持都不到位，导出来是另一个样子）。尺寸照固有值取，_fit_box 才能算准 cover/contain。
    """
    if not browser:
        return None
    iw, ih = _svg_size(path)
    if not iw or not ih:
        # 读不出尺寸（没写 width/height 也没 viewBox）就用元素框：至少不裁切
        iw, ih = max(1, int(box[0])), max(1, int(box[1]))
    shot = work_dir / f"svg-{token}.png"
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-svg-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        f"--force-device-scale-factor={RASTER_SCALE}",
        "--default-background-color=00000000",  # 透明底：SVG 没画到的地方不能被刷白
        f"--window-size={iw},{ih}",
        f"--user-data-dir={profile}",
        f"--screenshot={shot}",
        path.resolve().as_uri(),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
        return shot if shot.exists() else None
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _pptx_ready_image(path: Path, work_dir: Path, browser: str, token: str, box: tuple) -> Path | None:
    """把 python-pptx 嵌不了的图片转成 PNG：SVG 交给浏览器，webp / ico / avif 交给 Pillow。

    返回可以直接 add_picture 的路径（本来就嵌得进去的原样返回）；转不出来返回 None，调用方降级。
    """
    if path.suffix.lower() in PPTX_IMAGE_EXT:
        return path
    if path.suffix.lower() == ".svg":
        return _rasterize_svg(path, work_dir, browser, token, box)
    target = work_dir / f"conv-{token}.png"
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.convert("RGBA").save(target)
    except (OSError, ValueError):
        return None
    return target


def _converted_image(el: dict, root: Path, work_dir: Path, browser: str) -> str:
    """图片元素用了嵌不了的格式时，先转成 PNG，把路径挂在元素的 `_pptx_src` 上。

    和 `_pptx_gif` 同一个套路：写入函数只拿到 (slide, el, root, warnings)，没有导出上下文，
    路径得在跑写入函数之前备好。返回空串表示不用转（能直接嵌 / 不是本地素材 / 转不出来）。
    """
    if str(el.get("type") or "") != "image":
        return ""
    src = str((el.get("props") or {}).get("src") or "")
    if not src or src.startswith(("http://", "https://", "data:")):
        return ""
    path = (root / src).resolve()
    if not path.exists() or path.suffix.lower() in PPTX_IMAGE_EXT:
        return ""
    token = re.sub(r"[^0-9A-Za-z_-]", "", str(el.get("id") or "")) or "el"
    ready = _pptx_ready_image(path, work_dir, browser, token,
                              (_num(el.get("w"), 100), _num(el.get("h"), 100)))
    return str(ready) if ready else ""


def _add_image(slide, el: dict, root: Path) -> bool:
    from PIL import Image

    props = el.get("props") or {}
    # _pptx_src 是导出前转好的 PNG（svg / webp 这类），没有就用素材原路径
    src = str(el.get("_pptx_src") or props.get("src") or "")
    if not src or src.startswith(("http://", "https://", "data:")):
        return False
    path = (root / src).resolve()
    if not path.exists():
        return False
    try:
        with Image.open(path) as im:
            iw, ih = im.size
    except OSError:
        iw = ih = 0

    x, y, w, h, crop = _fit_box(el, props, iw, ih)
    from pptx.util import Emu

    pic = slide.shapes.add_picture(
        str(path),
        Emu(int(x * PX_TO_EMU)), Emu(int(y * PX_TO_EMU)),
        Emu(int(w * PX_TO_EMU)), Emu(int(h * PX_TO_EMU)),
    )
    if crop[0]:
        pic.crop_left = pic.crop_right = crop[0]
    if crop[2]:
        pic.crop_top = pic.crop_bottom = crop[2]
    _apply_picture_effects(pic, el)
    return True


def _cell_borders(cell, color: str, width_px: float, dashed: bool = False) -> None:
    """python-pptx 没有单元格边框 API，直接写 a:lnL/R/T/B。"""
    from pptx.oxml.ns import qn

    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        node = tcPr.find(qn(tag))
        if node is not None:
            tcPr.remove(node)
        node = tcPr.makeelement(qn(tag), {"w": str(int(width_px * PX_TO_EMU)), "cap": "flat",
                                          "cmpd": "sng", "algn": "ctr"})
        fill = node.makeelement(qn("a:solidFill"), {})
        fill.append(fill.makeelement(qn("a:srgbClr"), {"val": color}))
        node.append(fill)
        if dashed:
            node.append(node.makeelement(qn("a:prstDash"), {"val": "dash"}))
        tcPr.append(node)
    # 边框节点必须排在填充之前，顺序错了 PowerPoint 会报文件损坏
    order = {"a:lnL": 0, "a:lnR": 1, "a:lnT": 2, "a:lnB": 3, "a:lnTlToBr": 4, "a:lnBlToTr": 5,
             "a:cell3D": 6, "a:noFill": 7, "a:solidFill": 8, "a:gradFill": 9, "a:blipFill": 10,
             "a:pattFill": 11, "a:grpFill": 12, "a:headers": 13, "a:extLst": 14}
    children = sorted(tcPr, key=lambda c: order.get("a:" + c.tag.split("}")[-1], 99))
    for child in children:
        tcPr.append(child)


def _table_highlights(props: dict) -> tuple:
    """props.highlights → (整行底色, 单格底色)；列的写法与 render-kit.js 一致：-1 / "*" 表示整行。"""
    default = str(props.get("highlightColor") or "#fff3cd")
    rows_map: dict = {}
    cells_map: dict = {}
    for item in props.get("highlights") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        row = int(_num(item[0], -1))
        if row < 0:
            continue
        col = item[1]
        color = str(item[2]).strip() if len(item) > 2 and item[2] else default
        if col is None or col == "" or col == "*" or _num(col, -1) == -1:
            rows_map[row] = color
        else:
            cells_map[(row, int(_num(col)))] = color
    return rows_map, cells_map


#: 全角（CJK / 全角标点）字符：估宽度时算 1em，其余按 latinEm。与 render-kit.js 的
#: CJK_RE / textEm 同一套，保证两端算出的列宽权重与折行行数一致。
_CJK_RE = re.compile(
    r"[\u1100-\u115F\u2E80-\u303E\u3041-\u33FF\u3400-\u4DBF\u4E00-\u9FFF"
    r"\uA000-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFF60\uFFE0-\uFFE6]"
)


def _geom_tok(key: str, default: float) -> float:
    """取 tokens.js 的 geometry.table.* 常数（唯一来源），读不到就用 default。"""
    value = ((tokens().get("geometry") or {}).get("table") or {})
    try:
        return float(value.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _text_em(text) -> float:
    """文本宽度（em）：全角 1、半角 latinEm。"""
    wide = _geom_tok("cjkEm", 1)
    latin = _geom_tok("latinEm", 0.55)
    return sum(wide if _CJK_RE.match(ch) else latin for ch in str("" if text is None else text))


def _table_geom(props: dict, rows: list, width: float) -> dict:
    """表格几何：与 render-kit.js 的 tableGeom 同一条公式。

    列宽按权重分摊（props.columnWidths 优先，否则按内容宽度估）；行高 = 折行数 × 字号 ×
    行高 + 上下内边距 + 上下边框；标题另占一行高。宽度用 em 估，两端一致。
    """
    p = props or {}
    cols = max(1, max((len(r) for r in rows), default=0))
    density = str(p.get("density") or "normal")
    # 密度是内边距的倍率（紧凑 0.5× / 正常 1× / 宽松 2×），与 render-kit.tableGeom 同一套。
    # 早先「有 cellPadding 就无视 density」会被 schema 的默认值顶掉，导致行高密度点了没反应。
    cell_pad = _clamp(_num(p.get("cellPadding"), 7), 0, 60)
    pad_scale = 0.5 if density == "compact" else (2.0 if density == "loose" else 1.0)
    pad = _clamp(cell_pad * pad_scale, 0, 60)
    fs = _clamp(_num(p.get("fontSize"), 14), 6, 96)
    header_fs = _clamp(_num(p.get("headerFontSize"), fs), 6, 96)
    header = p.get("header", True) is not False
    bw = 0.0 if p.get("borders", True) is False else _clamp(_num(p.get("borderWidth"), 1), 0, 12)
    pad_v = round(pad * 1.05)
    pad_h = round(pad * 1.4)
    line_h = _geom_tok("lineHeight", 1.35)
    width = max(0.0, _num(width))

    given = p.get("columnWidths") if isinstance(p.get("columnWidths"), list) else None
    weights, seen = [], []
    for c in range(cols):
        v = _num(given[c], 0) if given and c < len(given) else 0.0
        weights.append(v if v > 0 else 0.0)
        if v > 0:
            seen.append(v)
    if seen:
        avg = sum(seen) / len(seen)
        weights = [w if w > 0 else avg for w in weights]
    else:
        min_em = _geom_tok("minColEm", 4)
        weights = []
        for c in range(cols):
            widest = 0.0
            for row in rows:
                widest = max(widest, _text_em(row[c] if c < len(row) else ""))
            weights.append(max(min_em, widest))
    total = sum(weights) or 1.0
    col_w = [w / total * width for w in weights]

    row_h = []
    for r, row in enumerate(rows):
        size = header_fs if (header and r == 0) else fs
        lines = 1
        if width > 0:
            for c in range(cols):
                avail = max(1.0, col_w[c] - 2 * pad_h - 2 * bw)
                need = math.ceil(_text_em(row[c] if c < len(row) else "") / max(0.01, avail / size))
                lines = max(lines, need)
        row_h.append(2 * pad_v + lines * size * line_h + 2 * bw)

    return {
        "cols": cols, "col_w": col_w, "row_h": row_h,
        "pad_v": pad_v, "pad_h": pad_h, "fs": fs, "header_fs": header_fs, "bw": bw,
    }


def _add_table(slide, el: dict) -> bool:
    """表格 → 原生 PPTX 表格（PowerPoint 里可继续编辑）。

    列宽 / 行高走 IR 公式（见 _table_geom，与浏览器侧 render-kit.tableGeom 同一套），
    不再依赖探针实测：两端从同一份 props 算，天然对齐，也不怕没有浏览器。
    """
    from pptx.oxml.ns import qn
    from pptx.util import Emu

    props = el.get("props") or {}
    style = el.get("style") or {}
    rows = [list(r) if isinstance(r, (list, tuple)) else [r] for r in (props.get("rows") or [])]
    if not rows:
        return False

    geom = _table_geom(props, rows, max(1.0, _num(el.get("w"), 400)))
    cols = geom["cols"]
    tx, ty = _num(el.get("x")), _num(el.get("y"))
    tw = max(1.0, _num(el.get("w"), 400))
    th = max(1.0, _num(el.get("h"), 200))
    # 几何优先用浏览器实测值：列宽是浏览器按内容自动分配的、行高按字体实际撑开，只有它算得准；
    # 拿不到实测（没装浏览器 / 探针失败）才退回 IR 公式（_table_geom，与 render-kit.tableGeom 同一套）。
    mm = _ac_measure(el)
    mm = mm if mm.get("kind") == "table" else {}
    col_w = [max(1.0, _num(v)) for v in (mm.get("cols") or geom["col_w"])]
    row_h = [max(1.0, _num(v)) for v in (mm.get("rws") or geom["row_h"])]
    tw = sum(col_w) or tw
    # 表格撑满元素框（与画布 render-kit 的 height:100% 一致）：行高按比例摊掉元素框多出来的高度，
    # 单元格垂直对齐（vertical anchor）才有可见效果，WPS / Office 打开也一样。
    extra_h = th - sum(row_h)
    if extra_h > 1 and row_h:
        base = sum(row_h) or float(len(row_h))
        row_h = [h + extra_h * (h / base) for h in row_h]

    head = props.get("header", True) is not False
    zebra = bool(props.get("zebra"))
    borders = props.get("borders", True) is not False
    border_w = max(0.0, _num(props.get("borderWidth"), 1)) if borders else 0.0
    border_col = str(props.get("borderColor") or "#d0d5dd")
    font_size = _num(props.get("fontSize"), 14)
    header_size = _num(props.get("headerFontSize"), font_size)
    density = str(props.get("density") or "normal")
    cell_pad = max(0.0, _num(props.get("cellPadding"), 7))
    pad_scale = 0.5 if density == "compact" else (2.0 if density == "loose" else 1.0)
    pad = cell_pad * pad_scale
    aligns = props.get("aligns") if isinstance(props.get("aligns"), list) else None
    default_align = str(props.get("align") or "left")
    header_align = str(props.get("headerAlign") or (aligns[0] if aligns else "") or default_align)
    header_bold = props.get("headerBold", True) is not False
    first_col_bold = bool(props.get("firstColBold"))
    valign = str(props.get("verticalAlign") or "middle")
    font_name = str(props.get("fontFamily") or style.get("fontFamily") or "Microsoft YaHei")
    body_color = str(style.get("color") or "#1f2328")
    hl_rows, hl_cells = _table_highlights(props)

    body_h = max(1.0, sum(row_h) if row_h else th)

    shape = slide.shapes.add_table(
        len(rows), cols, Emu(int(tx * PX_TO_EMU)), Emu(int(ty * PX_TO_EMU)),
        Emu(int(tw * PX_TO_EMU)), Emu(int(body_h * PX_TO_EMU)),
    )
    table = shape.table
    table.first_row = False  # 关掉 PPTX 主题的"首行强调/斑马纹"，颜色全部按工程样式显式写
    table.horz_banding = False
    # 默认表样式（Medium Style 2 - Accent 1）会给单元格加主题色内边框，工程没配边框时反而多出线
    tblPr = table._tbl.tblPr
    style_id = tblPr.find(qn("a:tableStyleId"))
    if style_id is None:
        style_id = tblPr.makeelement(qn("a:tableStyleId"), {})
        tblPr.append(style_id)
    style_id.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # No Style, No Grid
    for c in range(cols):
        table.columns[c].width = Emu(int(col_w[c] * PX_TO_EMU))
    for r in range(len(rows)):
        table.rows[r].height = Emu(int(row_h[r] * PX_TO_EMU))

    for r, row in enumerate(rows):
        for c in range(cols):
            cell = table.cell(r, c)
            value = row[c] if c < len(row) else ""
            cell.text = "" if value is None else str(value)
            cell.vertical_anchor = _anchor(valign)
            cell.margin_left = cell.margin_right = Emu(int(pad * 1.4 * PX_TO_EMU))
            cell.margin_top = cell.margin_bottom = Emu(int(pad * 1.05 * PX_TO_EMU))
            is_head = head and r == 0
            if is_head:
                fill = str(props.get("headerBg") or "#f2f4f7")
                text_color = str(props.get("headerColor") or "#344054")
                bold = header_bold
            else:
                body_index = r - 1 if head else r
                # 斑马纹优先于行底色（同 render-kit.tableHtml）：rowBg 有 schema 默认值，
                # 若让它先行，整块铺色会把斑马纹彻底盖住。
                fill = hl_cells.get((r, c)) or hl_rows.get(r) or ""
                if not fill:
                    if zebra:
                        fill = str(props.get("altBg") or "#f7f9fc") if body_index % 2 == 1 else str(props.get("rowBg") or "")
                    else:
                        fill = str(props.get("rowBg") or "")
                text_color = body_color
                bold = bool(first_col_bold and c == 0)
            if fill and fill.strip().lower() not in ("transparent", "none"):
                _set_fill(cell, fill)
            else:
                cell.fill.background()
            if border_w > 0:
                _cell_borders(cell, border_col, border_w)
            align = header_align if is_head else (
                str(aligns[c]) if aligns and c < len(aligns) and aligns[c] else default_align)
            for para in cell.text_frame.paragraphs:
                para.alignment = _align(align)
                for run in para.runs:
                    _style_run(run, name=font_name, size=_pt(header_size if is_head else font_size, 14),
                               bold=bold, italic=False, color=text_color)
    return True


_XL_LEGEND_POS = {"top": "TOP", "bottom": "BOTTOM", "left": "LEFT", "right": "RIGHT"}

# valueFormat（与 render-kit.js 的 fmtValue 同一套）→ OOXML 数值格式码
_VALUE_FORMAT = {
    "percent": "0%",
    "fixed1": "0.0",
    "fixed2": "0.00",
    "thousand": "#,##0",
    "compact": "#,##0.###",
    "auto": "#,##0.###",
}


def _fill_alpha(fill, opacity: float) -> None:
    """给已经 solid 的填充叠一层 alpha（python-pptx 没有透明度 API）。失败就保持不透明。"""
    from pptx.oxml.ns import qn

    if _num(opacity, 1) >= 1:
        return
    parent = getattr(fill, "_xPr", None)
    solid = parent.find(qn("a:solidFill")) if parent is not None else None
    clr = solid.find(qn("a:srgbClr")) if solid is not None else None
    if clr is not None:
        clr.append(clr.makeelement(qn("a:alpha"), {"val": _alpha(opacity)}))


def _add_chart(slide, el: dict) -> bool:
    """统计图 → python-pptx 原生图表（兜底路径：拿不到探针 SVG 时才走这里）。

    首选是 _add_chart_svg（探针实测的 SVG 矢量贴图，与画布一一对应，见 _pptx_chart）；
    这条原生路径只在没装浏览器 / 探针失败时兜底，多系列、配色预设、标题 / 图例 / 值标签 /
    轴都按工程设置显式写死，否则 PowerPoint 会套主题色。
    画不像的图（雷达 / 散点 / 热力图 / 箱线…）不走这里，由 _chart_vector_ok 交回截图。
    """
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE

    props = el.get("props") or {}
    style = el.get("style") or {}
    labels, names, values = _chart_series(props)
    if not labels or not values:
        return False
    kind = _chart_native_kind(props)
    if not kind:
        return False
    pie_like = kind in ("PIE", "DOUGHNUT")
    horizontal = kind in ("BAR_CLUSTERED", "BAR_STACKED")
    stacked = kind in ("COLUMN_STACKED", "BAR_STACKED", "AREA_STACKED")
    palette = _chart_palette(props)
    font_name = str(style.get("fontFamily") or "Microsoft YaHei")
    tick_size = _num(props.get("fontSize"), 12)

    data = CategoryChartData()
    data.categories = labels
    for name, vals in zip(names, values):
        data.add_series(str(name), vals)
    frame = slide.shapes.add_chart(
        getattr(XL_CHART_TYPE, kind),
        _emu(el, "x"), _emu(el, "y"), _emu(el, "w", 480), _emu(el, "h", 300),
        data,
    )
    chart = frame.chart
    try:  # 图表里的中文同样要 ea，否则会换字体
        chart.font.size = _pt(tick_size, 12)
        latin, ea = _font_stack(font_name)
        chart.font.name = latin
        _fill_typeface(chart.font._rPr, latin, ea)
    except Exception:  # noqa: BLE001
        pass

    title = str(props.get("title") or "").strip()
    chart.has_title = bool(title)
    if title:
        frame_tf = chart.chart_title.text_frame
        frame_tf.text = title
        para = frame_tf.paragraphs[0]
        para.alignment = _align(str(props.get("titleAlign") or "center"))
        for run in para.runs:
            _style_run(run, name=font_name, size=_pt(_num(props.get("titleSize"), 17), 17),
                       bold=True, italic=False, color=str(props.get("titleColor") or "#1f2328"))

    plot = chart.plots[0]
    pie_fmt = str(props.get("valueFormat") or "auto")
    show_values = props.get("showValues", True) is not False and pie_fmt != "none"
    plot.has_data_labels = show_values
    if show_values:
        dlabels = plot.data_labels
        dlabels.show_category_name = False
        dlabels.show_series_name = False
        if pie_like:                      # 饼图 / 环形图在画布上显示的是百分比
            dlabels.show_percentage = True
            dlabels.show_value = False
            dlabels.number_format = "0.0%" if pie_fmt == "fixed1" else "0%"
        else:
            dlabels.show_value = True
            dlabels.show_percentage = False
            dlabels.number_format = _VALUE_FORMAT.get(pie_fmt, "#,##0.###")
        dlabels.number_format_is_linked = False
        dlabels.font.size = _pt(max(8, tick_size - 2), 10)
        dlabels.font.color.rgb = _rgb(str(props.get("valueColor") or "#475467"))
        try:
            _fill_typeface(dlabels.font._rPr, *_font_stack(font_name))
        except Exception:  # noqa: BLE001
            pass

    by_category = props.get("colorByCategory") is True
    for si, series in enumerate(plot.series):
        color = palette[si % len(palette)]
        if kind in ("LINE_MARKERS", "LINE"):
            series.format.line.color.rgb = _rgb(color)
            series.format.line.width = _pt(_num(props.get("lineWidth"), 2.5), 2.5)
            if props.get("showPoints", True) is not False:
                series.marker.style = XL_MARKER_STYLE.CIRCLE
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = _rgb("FFFFFF")
                series.marker.format.line.color.rgb = _rgb(color)
            else:
                series.marker.style = XL_MARKER_STYLE.NONE
            continue
        if pie_like or by_category:       # 逐扇区 / 逐类目上色
            for i, point in enumerate(series.points):
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = _rgb(palette[i % len(palette)])
            continue
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _rgb(color)
        if kind in ("AREA", "AREA_STACKED"):
            try:
                _fill_alpha(series.format.fill, _num(props.get("areaOpacity"), 0.22))
            except Exception:  # noqa: BLE001
                pass

    if kind in ("COLUMN_CLUSTERED", "COLUMN_STACKED", "BAR_CLUSTERED", "BAR_STACKED"):
        gap = min(0.9, max(0.0, _num(props.get("barGap"), 0.34)))
        try:
            plot.gap_width = int(round(gap / max(0.01, 1 - gap) * 100))
        except Exception:  # noqa: BLE001
            pass
    if stacked:
        try:
            plot.overlap = 100             # 堆叠系列要贴在一起才会形成一整条
        except Exception:  # noqa: BLE001
            pass

    legend_pos = str(props.get("legendPos") or ("right" if pie_like else "top"))
    if props.get("showLegend") is False or (len(names) <= 1 and not pie_like):
        chart.has_legend = False
        legend_pos = "none"
    if legend_pos != "none":
        chart.has_legend = True
        chart.legend.position = getattr(XL_LEGEND_POSITION, _XL_LEGEND_POS.get(legend_pos, "TOP"))
        chart.legend.include_in_layout = False
        chart.legend.font.size = _pt(tick_size, 12)
        try:
            _fill_typeface(chart.legend.font._rPr, *_font_stack(font_name))
        except Exception:  # noqa: BLE001
            pass

    if not pie_like:
        label_color = str(props.get("labelColor") or "#667085")
        value_axis = chart.value_axis
        cat_axis = chart.category_axis
        show_grid = props.get("showGrid", True) is not False
        value_axis.has_major_gridlines = show_grid
        if show_grid:
            try:
                value_axis.major_gridlines.format.line.color.rgb = _rgb(str(props.get("gridColor") or "#e6e9ee"))
                value_axis.major_gridlines.format.line.width = _pt(1, 1)
            except Exception:  # noqa: BLE001
                pass
        cat_axis.has_major_gridlines = False
        for axis in (value_axis, cat_axis):
            axis.tick_labels.font.size = _pt(tick_size, 12)
            axis.tick_labels.font.color.rgb = _rgb(label_color)
            try:
                _fill_typeface(axis.tick_labels.font._rPr, *_font_stack(font_name))
            except Exception:  # noqa: BLE001
                pass
        if props.get("showAxis", True) is False:
            for axis in (value_axis, cat_axis):
                try:
                    axis.format.line.fill.background()   # 画布上可以关掉轴线，PPTX 里就得抹掉描边
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                cat_axis.format.line.color.rgb = _rgb(str(props.get("axisColor") or "#d0d5dd"))
            except Exception:  # noqa: BLE001
                pass
        if _num(props.get("minValue")):
            value_axis.minimum_scale = _num(props.get("minValue"))
        if _num(props.get("maxValue")):
            value_axis.maximum_scale = _num(props.get("maxValue"))
        # 横向柱状图的两条轴对调：类目轴在竖直方向
        cat_title = props.get("yTitle") if horizontal else props.get("xTitle")
        val_title = props.get("xTitle") if horizontal else props.get("yTitle")
        for axis, text in ((cat_axis, cat_title), (value_axis, val_title)):
            if not str(text or "").strip():
                continue
            axis.has_title = True
            axis.axis_title.text_frame.text = str(text)
            for run in axis.axis_title.text_frame.paragraphs[0].runs:
                _style_run(run, name=font_name, size=_pt(tick_size, 12), bold=False,
                           italic=False, color=label_color)
    return True


def _svg_with_font(svg: str, el: dict) -> str:
    """把元素字体族补到 SVG 根上：图表 SVG 里的文字靠继承取字体，不补就会落到 PowerPoint 默认字体。

    兜底字体与画布一致（见 canvas.js 里元素的 `style.fontFamily || 'Microsoft YaHei'`）。
    """
    family = str((el.get("style") or {}).get("fontFamily") or "").strip() or "Microsoft YaHei"
    if "<svg" not in svg:
        return svg
    head = svg.split(">", 1)[0]
    if "font-family" in head:
        return svg
    return svg.replace("<svg", '<svg font-family="%s"' % html.escape(family, quote=True), 1)


_SVG_VIEWBOX_RE = re.compile(r"viewBox\s*=\s*[\"']([^\"']+)[\"']")


def _svg_ratio(svg: str) -> float:
    """SVG 的宽高比（取自 viewBox）；读不到返回 0，表示「就按元素框来」。"""
    m = _SVG_VIEWBOX_RE.search(svg)
    if not m:
        return 0.0
    nums = re.findall(r"-?\d+(?:\.\d+)?", m.group(1))
    if len(nums) < 4:
        return 0.0
    w, h = _num(nums[2]), _num(nums[3])
    return w / h if w > 0 and h > 0 else 0.0


def _contain_box(x: float, y: float, w: float, h: float, ratio: float) -> tuple:
    """在 (x, y, w, h) 里按 ratio 取最大内接矩形并居中 —— SVG 的 `meet` 就是这么摆的。"""
    if ratio <= 0 or w <= 0 or h <= 0:
        return x, y, w, h
    if w / h > ratio:
        iw = h * ratio
        return x + (w - iw) / 2, y, iw, h
    ih = w / ratio
    return x, y + (h - ih) / 2, w, ih


_SVG_BLIP_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"


def _add_svg_picture(slide, svg_text: str, png_path: Path, box) -> bool:
    """贴一张「矢量主体 + PNG 兜底帧」的图片 —— PPTX 的 svgBlip 机制。

    python-pptx 不认识 SVG，这里手工补一个 svg 部件、把它的 rId 写进 a:blip 的 extLst；
    a:blip 自己的 r:embed 仍指向 PNG —— PowerPoint 2016+ 按 SVG 走矢量渲染，老版本认不出
    svgBlip 就退回兜底帧。两帧出自同一次渲染，走哪条路都不变形。
    """
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.oxml import parse_xml

    pic = slide.shapes.add_picture(str(png_path), *box)
    try:
        package = slide.part.package
        partname = package.next_partname("/ppt/media/image%d.svg")
        svg_part = Part(partname, "image/svg+xml", package, svg_text.encode("utf-8"))
        rel_id = slide.part.relate_to(svg_part, RT.IMAGE)
        pic._element.blipFill.blip.append(parse_xml(
            "<a:extLst %s><a:ext uri=\"%s\"><asvg:svgBlip r:embed=\"%s\"/></a:ext></a:extLst>" % (
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
                ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
                ' xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main"',
                _SVG_BLIP_URI, rel_id,
            )
        ))
    except Exception:  # noqa: BLE001 —— 挂不上 SVG 就只留 PNG 兜底帧，图片本身还是对的
        pass
    return True


def _svg_num(value) -> str:
    """SVG 数字：两位小数、去掉尾随 0，省得属性值拖一长串。"""
    return ("%.2f" % float(_num(value))).rstrip("0").rstrip(".")


def _svg_opacity(value) -> str:
    """fill-opacity 属性；全不透明就不写。"""
    value = _num(value, 1)
    return "" if value >= 0.999 else ' fill-opacity="%s"' % _svg_num(max(0.0, value))


def _place_measure_svg(slide, el: dict, root: Path, tag: str, make_svg) -> bool:
    """贴一张「实测渲染出来的 SVG」：现场截一张同源的 PNG 当兜底帧，走 PPTX 的 svgBlip。

    make_svg 拿到截图框（canvas）之后返回 (SVG 源码, 落地区域) —— 代码块的 viewBox 要靠截图框才
    知道该留多少投影余量。图片框由「落地区域按 SVG 的 viewBox 比例取内接矩形」定：PowerPoint /
    WPS 不认 preserveAspectRatio，会把图拉伸填满框，比例不一致就直接变形；两帧同比例、同位置，
    走哪条路都与画布一致。
    """
    from pptx.util import Emu

    browser = str(el.get("_pptx_browser") or "")
    work_dir = el.get("_pptx_work")
    if not browser or work_dir is None:
        return False
    work_dir = Path(work_dir)
    index = int(el.get("_pptx_index") or 0)
    piece, image = _screenshot_element(browser, el, root, work_dir, index)
    if piece is None:
        return False
    try:
        bx, by, bw, bh = piece["canvas"]
        sx, sy, sw, sh = piece["spot"]
        scale = piece["scale"]
        if bw < 1 or bh < 1 or sw < 1 or sh < 1:
            return False
        svg, region = make_svg(piece)
        svg = str(svg or "")
        if not svg.strip():
            return False
        rx, ry, rw, rh = (_num(v) for v in region)
        ix, iy, iw, ih = _contain_box(rx, ry, rw, rh, _svg_ratio(svg))
        kx, ky = sw / bw, sh / bh          # 截图里那一格与元素框的比例（正常都是 1）
        crop = piece["image"].crop((
            int(round((sx + (ix - bx) * kx) * scale)), int(round((sy + (iy - by) * ky) * scale)),
            int(round((sx + (ix - bx + iw) * kx) * scale)),
            int(round((sy + (iy - by + ih) * ky) * scale)),
        ))
        if crop.getchannel("A").getbbox() is None:
            return False
        token = re.sub(r"[^0-9A-Za-z_-]", "", str(el.get("id") or "")) or "el"
        frame = work_dir / f"{tag}-{index}-{token}.png"
        crop.save(frame)
        return _add_svg_picture(
            slide, _svg_with_font(svg, el), frame,
            (Emu(int(ix * PX_TO_EMU)), Emu(int(iy * PX_TO_EMU)),
             Emu(int(iw * PX_TO_EMU)), Emu(int(ih * PX_TO_EMU))),
        )
    finally:
        if image is not None:
            image.close()


def _dl_to_svg(el: dict, dp: list, ox: float, oy: float, w: float, h: float) -> str:
    """图元清单 → SVG。

    代码块在画布上是 HTML 卡片，PPTX 里没有对应的原生对象；把浏览器量到的每个矩形、每段文字
    按原坐标写成 SVG 再作为矢量图贴进去，位置与画布逐点对应，放大也不会糊。

    (ox, oy) 是元素原点在画布框里的位置，(w, h) 是画布框尺寸 —— 画布框比元素框大一圈（给投影
    留的余量），viewBox 按它来定，卡片那道外投影才不会被裁掉。
    """
    w = max(1.0, _num(w, 100))
    h = max(1.0, _num(h, 100))
    style = el.get("style") or {}
    fallback = _font_stack(str(style.get("fontFamily") or ""))[0] or DEFAULT_EA_FONT
    radius = max(0.0, _num(style.get("borderRadius")))
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" viewBox="0 0 %s %s" '
        'width="%s" height="%s">' % (_svg_num(w), _svg_num(h), _svg_num(w), _svg_num(h)),
    ]
    shadow_id = 0
    for prim in dp or []:
        if not isinstance(prim, dict):
            continue
        kind = str(prim.get("k") or "")
        pw, ph = _num(prim.get("w")), _num(prim.get("h"))
        if pw <= 0.4 or ph <= 0.4:
            continue
        px_ = _num(prim.get("x")) + ox
        py_ = _num(prim.get("y")) + oy
        if kind == "r":
            parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s"%s/>' % (
                _svg_num(px_), _svg_num(py_), _svg_num(pw), _svg_num(ph),
                _svg_num(max(0.0, _num(prim.get("r")))),
                html.escape(str(prim.get("f") or "#ffffff")), _svg_opacity(prim.get("o"))))
        elif kind == "s":
            # 外投影：CSS 的模糊半径对应高斯 stdDeviation 的一半，画成一块同形的模糊矩形
            fid = "sh%d" % shadow_id
            shadow_id += 1
            parts.append(
                '<defs><filter id="%s" x="-50%%" y="-50%%" width="200%%" height="200%%">'
                '<feGaussianBlur stdDeviation="%s"/></filter></defs>' % (
                    fid, _svg_num(max(0.0, _num(prim.get("b")) / 2.0))))
            parts.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s"%s '
                         'filter="url(#%s)"/>' % (
                             _svg_num(px_ + _num(prim.get("dx"))),
                             _svg_num(py_ + _num(prim.get("dy"))),
                             _svg_num(pw), _svg_num(ph), _svg_num(radius),
                             html.escape(str(prim.get("f") or "#000000")),
                             _svg_opacity(prim.get("o")), fid))
        elif kind == "t":
            text = str(prim.get("t") or "")
            if not text.strip():
                continue
            ascent = _num(prim.get("a"))
            base = py_ + (ascent if ascent > 0 else ph * 0.8)   # 探针给了基线偏移就用它
            latin = _font_stack(str(prim.get("f") or ""))[0] or fallback
            extra = ' font-weight="bold"' if prim.get("b") else ''
            extra += ' font-style="italic"' if prim.get("i") else ''
            parts.append('<text x="%s" y="%s" font-family="%s" font-size="%s" fill="%s"%s%s>%s</text>' % (
                _svg_num(px_), _svg_num(base), html.escape(latin, quote=True),
                _svg_num(_num(prim.get("s"), 14)), html.escape(str(prim.get("c") or "#1f2328")),
                _svg_opacity(prim.get("o")), extra, html.escape(text)))
    parts.append("</svg>")
    return "".join(parts)


def _add_chart_svg(slide, el: dict, root: Path) -> bool:
    """统计图 → 探针实测的图表 SVG（矢量贴图）。

    与画布用的是同一份渲染结果，标题对齐 / 圆角柱 / 刻度 / 图例位置天然一一对应；拿不到 SVG
    （没浏览器 / 探针没量到）就返回 False，由调用方退回原生图表。
    """
    m = _ac_measure(el)
    svg = str(m.get("svg") or "")
    if m.get("kind") != "chart" or not svg.strip():
        return False
    # 图表 SVG 直接铺满元素框（画布上就是这样摆的），所以落地区域就是元素框本身
    box = (_num(el.get("x")), _num(el.get("y")), _num(el.get("w")), _num(el.get("h")))
    return _place_measure_svg(slide, el, root, "chart", lambda _piece: (svg, box))


def _add_code_svg(slide, el: dict, root: Path) -> bool:
    """代码块 → 探针实测渲染的 SVG（矢量贴图），卡片 / 标题栏 / 行号 / 高亮与画布逐点对应。"""
    m = _ac_measure(el)
    dp = m.get("dp") or []
    if m.get("kind") != "dl" or not dp:
        return False

    def make(piece):
        # 图元清单是相对元素框量的；viewBox 按截图框（元素框 + 投影余量）定，坐标整体挪过去
        bx, by, bw, bh = piece["canvas"]
        return _dl_to_svg(el, dp, _num(el.get("x")) - bx, _num(el.get("y")) - by, bw, bh), (bx, by, bw, bh)

    return _place_measure_svg(slide, el, root, "code", make)


def _apply_image_fill(shape, el: dict, root: Path) -> bool:
    """图片填充 → spPr/a:blipFill（拉伸）：PowerPoint 里的原生「图片填充」，可继续编辑。

    与画布同一套映射：图片拉伸铺满元素外框，再由轮廓裁剪（a:stretch + a:fillRect），
    和 PowerPoint 图片填充的「拉伸」完全一致，而不是截图贴一张位图。
    素材拿不到（路径空 / 文件不在 / 转不成 PNG）返回 False，调用方保留原填充。
    """
    from lxml import etree
    from pptx.oxml.ns import qn

    rel = _fill_image_rel(el)
    if not rel or rel.startswith(("http://", "https://", "data:")):
        return False   # 远程 / 内联图先不处理，保留原填充（避免联网与体积问题）
    path = (root / rel.lstrip("/\\")).resolve()
    if not path.exists():
        return False
    # 嵌不进去的格式（svg / webp…）先转 PNG：_pptx_work / _pptx_browser 由导出主循环挂在元素上
    work = str(el.get("_pptx_work") or "")
    token = "fill-" + (re.sub(r"[^0-9A-Za-z_-]", "", str(el.get("id") or "")) or "el")
    ready = _pptx_ready_image(path, Path(work), str(el.get("_pptx_browser") or ""), token,
                              (_num(el.get("w"), 100), _num(el.get("h"), 100))) if work else path
    if ready is None or not Path(ready).exists():
        return False
    _image_part, rId = shape.part.get_or_add_image_part(str(ready))

    sp_pr = shape._element.spPr
    for tag in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"):
        node = sp_pr.find(qn(tag))
        if node is not None:
            sp_pr.remove(node)
    blip_fill = sp_pr.makeelement(qn("a:blipFill"), {})
    blip = etree.SubElement(blip_fill, qn("a:blip"))
    blip.set(qn("r:embed"), rId)
    stretch = etree.SubElement(blip_fill, qn("a:stretch"))
    etree.SubElement(stretch, qn("a:fillRect"))
    # 填充节点必须排在几何之后、描边之前（spPr 子元素顺序固定，位置错了 PowerPoint 会判损坏）
    geom = sp_pr.find(qn("a:custGeom"))
    if geom is None:
        geom = sp_pr.find(qn("a:prstGeom"))
    if geom is not None:
        geom.addnext(blip_fill)
    else:
        sp_pr.append(blip_fill)
    return True


def _add_shape(slide, el: dict, root: Path | None = None):
    """形状的矢量映射（只在拿不到浏览器截图时兜底）：直接用 OOXML 预设几何体 + 描边 / 翻转。

    props.shape 与 PowerPoint 预设几何名（prst）一一对应，这里覆写 spPr/a:prstGeom@prst，
    比 MSO_SHAPE 枚举覆盖面宽得多（本工程 86 个图形全部命中）。
    """
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    props = el.get("props") or {}
    style = el.get("style") or {}
    kind = MSO_SHAPE.RECTANGLE
    if _num(style.get("borderRadius")) > 0:
        kind = MSO_SHAPE.ROUNDED_RECTANGLE
    shape = slide.shapes.add_shape(kind, _emu(el, "x"), _emu(el, "y"), _emu(el, "w", 100), _emu(el, "h", 100))
    name = str(props.get("shape") or "rect")
    if name and name != "rect":
        geom = shape._element.spPr.find(qn("a:prstGeom"))
        if geom is not None:
            geom.set("prst", name)
    _apply_box(shape, style, el, props)
    if root is not None:
        _apply_image_fill(shape, el, root)   # 图片填充顶掉纯色底，写成原生 a:blipFill
    xfrm = shape._element.spPr.find(qn("a:xfrm"))
    if xfrm is not None:
        if _num(props.get("flipH")) or props.get("flipH") is True:
            xfrm.set("flipH", "1")
        if _num(props.get("flipV")) or props.get("flipV") is True:
            xfrm.set("flipV", "1")
    shape.text_frame.text = ""
    return shape


# ------------------------------------------------------------------ 可编辑矢量路径（custGeom）
_SVG_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _svg_tokens(d: str) -> list:
    """SVG path 数据 → 命令字母与数字交错的记号流。"""
    s = str(d or "")
    out: list = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isalpha():
            out.append(c)
            i += 1
            continue
        if c in " \t\r\n,":
            i += 1
            continue
        m = _SVG_NUM.match(s, i)
        if not m:
            i += 1
            continue
        out.append(float(m.group(0)))
        i = m.end()
    return out


def _arc_polyline(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2) -> list:
    """椭圆弧 → 折线点（SVG 规范 F.6.5 端点参数化，每 1/4 弧切一段）。"""
    if not rx or not ry:
        return [(x2, y2)]
    phi = math.radians(phi_deg or 0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    rx, ry = abs(rx), abs(ry)
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    numv = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    sign = 1 if (bool(large) != bool(sweep)) else -1
    co = sign * math.sqrt(max(0.0, numv / den)) if den else 0.0
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        ln = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        if not ln:
            return 0.0
        a = math.acos(max(-1.0, min(1.0, dot / ln)))
        return -a if (ux * vy - uy * vx) < 0 else a

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    th1 = ang(1, 0, ux, uy)
    dth = ang(ux, uy, vx, vy)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    if sweep and dth < 0:
        dth += 2 * math.pi
    n = max(1, int(math.ceil(abs(dth) / (math.pi / 2))))
    pts = []
    for k in range(1, n + 1):
        th = th1 + dth * k / n
        ex, ey = rx * math.cos(th), ry * math.sin(th)
        pts.append((cos_p * ex - sin_p * ey + cx, sin_p * ex + cos_p * ey + cy))
    return pts


def _parse_svg_path(d: str) -> list:
    """SVG path 数据 → 只含 M / L / C / Z 的段列表（Q/T 转三次贝塞尔，A 折线近似）。"""
    toks = _svg_tokens(d)
    ops: list = []
    idx = 0
    total = len(toks)
    cx = cy = sx = sy = 0.0
    prev_c2 = None
    prev_q = None
    last = ""

    def num() -> float:
        nonlocal idx
        v = toks[idx] if idx < total else 0.0
        idx += 1
        return v if isinstance(v, float) else 0.0

    while idx < total:
        t = toks[idx]
        if isinstance(t, str):
            cmd = t
            idx += 1
        else:
            cmd = "L" if last in ("M", "m") else last   # 隐式重复
        up = cmd.upper()
        rel = cmd.islower()
        px, py = cx, cy
        bx = px if rel else 0.0
        by = py if rel else 0.0
        if up == "M":
            cx, cy = bx + num(), by + num()
            sx, sy = cx, cy
            ops.append(("M", cx, cy))
            prev_c2 = prev_q = None
        elif up == "L":
            cx, cy = bx + num(), by + num()
            ops.append(("L", cx, cy))
            prev_c2 = prev_q = None
        elif up == "H":
            cx = bx + num()
            ops.append(("L", cx, cy))
            prev_c2 = prev_q = None
        elif up == "V":
            cy = by + num()
            ops.append(("L", cx, cy))
            prev_c2 = prev_q = None
        elif up == "C":
            x1, y1 = bx + num(), by + num()
            x2, y2 = bx + num(), by + num()
            cx, cy = bx + num(), by + num()
            ops.append(("C", x1, y1, x2, y2, cx, cy))
            prev_c2, prev_q = (x2, y2), None
        elif up == "S":
            x2, y2 = bx + num(), by + num()
            cx, cy = bx + num(), by + num()
            x1 = 2 * px - prev_c2[0] if prev_c2 else px
            y1 = 2 * py - prev_c2[1] if prev_c2 else py
            ops.append(("C", x1, y1, x2, y2, cx, cy))
            prev_c2, prev_q = (x2, y2), None
        elif up == "Q":
            qx, qy = bx + num(), by + num()
            cx, cy = bx + num(), by + num()
            ops.append(("C",
                        px + 2.0 / 3.0 * (qx - px), py + 2.0 / 3.0 * (qy - py),
                        cx + 2.0 / 3.0 * (qx - cx), cy + 2.0 / 3.0 * (qy - cy),
                        cx, cy))
            prev_c2, prev_q = None, (qx, qy)
        elif up == "T":
            qx = 2 * px - prev_q[0] if prev_q else px
            qy = 2 * py - prev_q[1] if prev_q else py
            cx, cy = bx + num(), by + num()
            ops.append(("C",
                        px + 2.0 / 3.0 * (qx - px), py + 2.0 / 3.0 * (qy - py),
                        cx + 2.0 / 3.0 * (qx - cx), cy + 2.0 / 3.0 * (qy - cy),
                        cx, cy))
            prev_c2, prev_q = None, (qx, qy)
        elif up == "A":
            rx, ry = num(), num()
            rot, large, sweep = num(), num(), num()
            ex, ey = bx + num(), by + num()
            for ax, ay in _arc_polyline(cx, cy, rx, ry, rot, large, sweep, ex, ey):
                ops.append(("L", ax, ay))
            cx, cy = ex, ey
            prev_c2 = prev_q = None
        elif up == "Z":
            ops.append(("Z",))
            cx, cy = sx, sy
            prev_c2 = prev_q = None
        else:
            break    # 不认识的命令：停在已解析的部分
        last = cmd
        if up == "Z":
            last = "M"
    return ops


def _add_path_shape(slide, el: dict, root: Path | None = None):
    """props.d → 带 a:custGeom 的自选图形：PPTX 里是能继续拖节点编辑的矢量轮廓。"""
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    props = el.get("props") or {}
    style = el.get("style") or {}
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, _emu(el, "x"), _emu(el, "y"),
                                   _emu(el, "w", 100), _emu(el, "h", 100))
    sp_pr = shape._element.spPr
    geom = sp_pr.find(qn("a:prstGeom"))
    if geom is None:
        return None
    cust = etree.Element(qn("a:custGeom"))
    etree.SubElement(cust, qn("a:avLst"))
    etree.SubElement(cust, qn("a:gdLst"))
    etree.SubElement(cust, qn("a:ahLst"))
    etree.SubElement(cust, qn("a:cxnLst"))
    rect = etree.SubElement(cust, qn("a:rect"))
    rect.set("l", "0"), rect.set("t", "0")
    rect.set("r", str(int(w))), rect.set("b", str(int(h)))
    path_lst = etree.SubElement(cust, qn("a:pathLst"))
    path = etree.SubElement(path_lst, qn("a:path"))
    path.set("w", str(int(w)))
    path.set("h", str(int(h)))

    def pt(parent, x, y):
        node = etree.SubElement(parent, qn("a:pt"))
        node.set("x", str(int(round(x))))
        node.set("y", str(int(round(y))))

    for op in _parse_svg_path(str(props.get("d") or "")):
        if op[0] == "M":
            pt(etree.SubElement(path, qn("a:moveTo")), op[1], op[2])
        elif op[0] == "L":
            pt(etree.SubElement(path, qn("a:lnTo")), op[1], op[2])
        elif op[0] == "C":
            node = etree.SubElement(path, qn("a:cubicBezTo"))
            pt(node, op[1], op[2])
            pt(node, op[3], op[4])
            pt(node, op[5], op[6])
        else:
            etree.SubElement(path, qn("a:close"))
    # custGeom 必须顶掉 prstGeom 的位置（spPr 子元素顺序是固定的，直接 append 会被 PowerPoint 判为损坏）
    geom.addprevious(cust)
    sp_pr.remove(geom)
    _apply_box(shape, style, el, props)
    if root is not None:
        _apply_image_fill(shape, el, root)   # 图片填充顶掉纯色底，写成原生 a:blipFill
    shape.text_frame.text = ""
    return shape


# UML 箭头类型 → OOXML a:headEnd / a:tailEnd 的原生 type；空心头没有原生表达，另叠图形补画
_NATIVE_HEAD = {"triangle": "triangle", "open": "arrow", "diamond": "diamond", "stealth": "stealth"}


def _add_head_overlay(slide, el: dict, props: dict, style: dict, end: str) -> None:
    """空心头（继承的空心三角 / 聚合的空心菱形）：OOXML 没有原生表达，另叠一个小矢量图形。

    白底 + 描边，盖在连线之上 —— 线伸进三角 / 菱形里的那截被白底遮掉，看起来就是空心。
    轮廓取自 props.arrowStartPath / arrowEndPath（元素局部坐标，与主路径同一坐标系），
    所以直接放在与连线同一个矩形里、按元素 w / h 建 path 坐标系即可。
    """
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    key = "arrowStartPath" if end == "start" else "arrowEndPath"
    ops = _parse_svg_path(str(props.get(key) or ""))
    if not ops:
        return
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, _emu(el, "x"), _emu(el, "y"),
                                   _emu(el, "w", 100), _emu(el, "h", 100))
    sp_pr = shape._element.spPr
    geom = sp_pr.find(qn("a:prstGeom"))
    if geom is None:
        return
    cust = etree.Element(qn("a:custGeom"))
    etree.SubElement(cust, qn("a:avLst"))
    etree.SubElement(cust, qn("a:gdLst"))
    etree.SubElement(cust, qn("a:ahLst"))
    etree.SubElement(cust, qn("a:cxnLst"))
    rect = etree.SubElement(cust, qn("a:rect"))
    rect.set("l", "0"), rect.set("t", "0")
    rect.set("r", str(int(w))), rect.set("b", str(int(h)))
    path_lst = etree.SubElement(cust, qn("a:pathLst"))
    path = etree.SubElement(path_lst, qn("a:path"))
    path.set("w", str(int(w)))
    path.set("h", str(int(h)))

    def pt(parent, x, y):
        node = etree.SubElement(parent, qn("a:pt"))
        node.set("x", str(int(round(x))))
        node.set("y", str(int(round(y))))

    for op in ops:
        if op[0] == "M":
            pt(etree.SubElement(path, qn("a:moveTo")), op[1], op[2])
        elif op[0] == "L":
            pt(etree.SubElement(path, qn("a:lnTo")), op[1], op[2])
        elif op[0] == "C":
            node = etree.SubElement(path, qn("a:cubicBezTo"))
            pt(node, op[1], op[2])
            pt(node, op[3], op[4])
            pt(node, op[5], op[6])
    etree.SubElement(path, qn("a:close"))
    geom.addprevious(cust)
    sp_pr.remove(geom)
    _strip_theme_style(shape)
    _set_fill(shape, "FFFFFF")
    line = shape.line
    line.color.rgb = _rgb(style.get("borderColor"), "2f6fed")
    width = _num(style.get("borderWidth"), 2)
    if width > 0:
        line.width = _pt(width, 1)
    _set_rotation(shape, el)
    shape.text_frame.text = ""


def _add_connector_shape(slide, el: dict):
    """连线的 props.d → 带 a:custGeom 的开放路径：不填充、只描边，两端按需加箭头。

    与 _add_path_shape 的区别：连线是一条断开的线段（没有围合区域），所以不填充；
    实心箭头不做成独立三角形，而是挂在 a:ln 的 headEnd / tailEnd 上 —— 在 PowerPoint 里
    拖端点改走向时箭头会自己跟着走；空心头（OOXML 表达不了）另叠一个矢量图形补画。
    """
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    props = el.get("props") or {}
    style = el.get("style") or {}
    ops = _parse_svg_path(str(props.get("d") or ""))
    if not ops:
        return None
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, _emu(el, "x"), _emu(el, "y"),
                                   _emu(el, "w", 100), _emu(el, "h", 100))
    sp_pr = shape._element.spPr
    geom = sp_pr.find(qn("a:prstGeom"))
    if geom is None:
        return None
    cust = etree.Element(qn("a:custGeom"))
    etree.SubElement(cust, qn("a:avLst"))
    etree.SubElement(cust, qn("a:gdLst"))
    etree.SubElement(cust, qn("a:ahLst"))
    etree.SubElement(cust, qn("a:cxnLst"))
    rect = etree.SubElement(cust, qn("a:rect"))
    rect.set("l", "0"), rect.set("t", "0")
    rect.set("r", str(int(w))), rect.set("b", str(int(h)))
    path_lst = etree.SubElement(cust, qn("a:pathLst"))
    path = etree.SubElement(path_lst, qn("a:path"))
    path.set("w", str(int(w)))
    path.set("h", str(int(h)))
    path.set("fill", "none")          # 开放路径：只描边，不填充

    def pt(parent, x, y):
        node = etree.SubElement(parent, qn("a:pt"))
        node.set("x", str(int(round(x))))
        node.set("y", str(int(round(y))))

    for op in ops:
        if op[0] == "M":
            pt(etree.SubElement(path, qn("a:moveTo")), op[1], op[2])
        elif op[0] == "L":
            pt(etree.SubElement(path, qn("a:lnTo")), op[1], op[2])
        elif op[0] == "C":
            node = etree.SubElement(path, qn("a:cubicBezTo"))
            pt(node, op[1], op[2])
            pt(node, op[3], op[4])
            pt(node, op[5], op[6])
    # custGeom 必须顶掉 prstGeom 的位置（spPr 子元素顺序固定）
    geom.addprevious(cust)
    sp_pr.remove(geom)
    _strip_theme_style(shape)
    shape.fill.background()
    _set_line(shape, style, props)
    _set_rotation(shape, el)
    shape.text_frame.text = ""

    # 箭头：实心三角 / 实心菱形 / 开放箭头 / 燕尾挂在 a:ln 的 headEnd / tailEnd 上（箭头大小
    # 只有三档 sm / med / lg，按 px 值就近映射）；空心头（继承 / 聚合）OOXML 没有原生表达，
    # 另叠一个小矢量图形补画（见 _add_head_overlay）。
    ln = sp_pr.find(qn("a:ln"))
    if ln is not None:
        arrow = _num(props.get("arrowSize"), 10)
        level = "sm" if arrow <= 6 else ("lg" if arrow >= 16 else "med")
        overlays: list = []
        for tag, end in (("a:headEnd", "start"), ("a:tailEnd", "end")):
            for old in ln.findall(qn(tag)):
                ln.remove(old)
            kind = arrow_type_of(props, end)
            native = _NATIVE_HEAD.get(kind)
            if not native:
                if kind in ("hollowTriangle", "hollowDiamond"):
                    overlays.append(end)
                continue
            node = etree.SubElement(ln, qn(tag))
            node.set("type", native)
            node.set("w", level)
            node.set("len", level)
        for end in overlays:
            _add_head_overlay(slide, el, props, style, end)
    return shape


def _add_placeholder(slide, el: dict, label: str):
    style = dict(el.get("style") or {})
    style.setdefault("color", "667085")
    style.setdefault("fontSize", 14)
    style.setdefault("textAlign", "center")
    style.setdefault("verticalAlign", "middle")
    box = slide.shapes.add_textbox(_emu(el, "x"), _emu(el, "y"), _emu(el, "w", 200), _emu(el, "h", 60))
    _set_fill(box, str(style.get("background") or "F2F4F7"))
    frame = box.text_frame
    frame.vertical_anchor = _anchor("middle")
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = _emu({}, "x", 0)
    para = frame.paragraphs[0]
    para.alignment = _align("center")
    run = para.add_run()
    run.text = label
    _style_run(run, name="Microsoft YaHei", size=_pt(14, 14), bold=False, italic=False,
               color=str(style.get("color") or "667085"))
    return box


def _apply_page_background(slide, page: dict, root: Path, prs,
                           work_dir: Path, browser: str, warnings: list) -> None:
    from pptx.util import Emu

    bg = page.get("background") or {}
    kind = bg.get("type", "solid")
    if kind == "image" and bg.get("image"):
        path = (root / str(bg["image"])).resolve()
        if path.exists():
            # svg / webp 这类嵌不进去的背景图先转成 PNG（否则 add_picture 抛错，整页导出都会挂）
            ready = _pptx_ready_image(path, work_dir, browser, "bg",
                                      (prs.slide_width / PX_TO_EMU, prs.slide_height / PX_TO_EMU))
            if ready is not None:
                slide.shapes.add_picture(str(ready), Emu(0), Emu(0), prs.slide_width, prs.slide_height)
                return
            warnings.append(f"页面背景图 {path.name} 转换失败，本页改用底色")
    if kind == "none":
        return
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(bg.get("color"), "FFFFFF")


# ------------------------------------------------------------------ 浏览器 DOM 探针
# 表格列宽 / 行高、代码块与公式的逐行排版、统计图的原生 SVG，只有浏览器算得出来
# （列宽按内容自动分配、公式靠 CSS 排版）。导出前把这一页交给无头浏览器量一次，
# 结果挂到元素上（沿用 _pptx_gif / _pptx_src 那套写法），PPTX 与 SVG 两路共用。
#
# 开浏览器很慢，而同一份内容的实测几何是确定的，所以量到的结果按内容哈希缓存 ——
# 缓存放「软件安装目录」的 data/cache 下，工程目录一个字都不写（导出对工程保持只读）。
def _wants_measure(el: dict) -> bool:
    """这份元素要不要拿去浏览器里量几何。"""
    etype = str(el.get("type") or "")
    if etype in ("table", "chart", "code"):
        return True
    if etype in ("text", "link"):
        props = el.get("props") or {}
        # 带行内富文本（props.runs）的文本也要逐段量：加粗/变色/高亮各自独立才摆得回去
        return bool(props.get("runs")) or has_math(props.get("text"))
    return False


def _ac_measure(el: dict) -> dict:
    data = el.get("_ac_measure")
    return data if isinstance(data, dict) else {}


_MEASURE_CACHE_DIR = DATA_DIR / "cache" / "measured"
# 探针（projects._PROBE_JS）改了就得 +1：实测数据只存在这份缓存里，探针一变旧数据就不能再用
_MEASURE_PROBE_VERSION = 3
_MEASURE_CACHE_MAX = 800  # 缓存文件上限，超了按修改时间删最旧的


def _measure_key(page: dict, el: dict) -> str:
    """实测结果的缓存键：渲染器指纹 + 画布尺寸 + 元素本身（去掉运行时挂上的下划线字段）。

    指纹一变（改了 tokens / render-kit）整批缓存自然失效；元素内容一变则只失效它自己。
    """
    blob = json.dumps(
        {
            "probe": _MEASURE_PROBE_VERSION,
            "kit": render_kit_signature(),
            "canvas": [page.get("width"), page.get("height")],
            "el": {k: v for k, v in el.items() if not k.startswith("_")},
        },
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _measure_cache_load(page: dict, el: dict) -> dict | None:
    try:
        text = (_MEASURE_CACHE_DIR / f"{_measure_key(page, el)}.json").read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


def _measure_cache_store(page: dict, el: dict, data: dict) -> None:
    if not isinstance(data, dict) or not data:
        return
    try:
        ensure_dir(_MEASURE_CACHE_DIR)
        atomic_write_text(_MEASURE_CACHE_DIR / f"{_measure_key(page, el)}.json",
                          json.dumps(data, ensure_ascii=False))
        files = sorted(_MEASURE_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for stale in files[:-_MEASURE_CACHE_MAX]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def _probe_page(browser: str, root: Path, manifest: dict, page_index: int, work_dir: Path) -> dict:
    """跑一次无头浏览器取回该页的实测几何；拿不到就返回 {}（相关元素自然回退截图）。"""
    if not browser:
        return {}
    pages = manifest.get("pages") or []
    page = pages[page_index] if 0 <= page_index < len(pages) else {}
    if not any(_wants_measure(el) for el in page.get("elements", []) if el.get("visible", True)):
        return {}
    html_path = work_dir / f"probe-{page_index}.html"
    try:
        html_path.write_text(render_probe_html(manifest, page_index, _file_prefix(root)), encoding="utf-8")
    except OSError:
        return {}
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-probe-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "--virtual-time-budget=4000",
        f"--user-data-dir={profile}",
        "--dump-dom",
        html_path.resolve().as_uri(),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        raw = proc.stdout or b""
    except (subprocess.TimeoutExpired, OSError):
        return {}
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
    match = re.search(r'data-ac-probe="([^"]*)"', text)
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1)))
    except (TypeError, ValueError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def _page_measure(browser: str, root: Path, manifest: dict, page: dict, page_index: int,
                  work_dir: Path) -> dict:
    """取该页所有待测元素的实测几何：先查缓存，缺的才开浏览器量一次并回填缓存。"""
    targets = [el for el in page.get("elements", [])
               if el.get("visible", True) and _wants_measure(el)]
    if not targets:
        return {}
    items: dict = {}
    missing = []
    for el in targets:
        cached = _measure_cache_load(page, el)
        if cached is not None:
            items[str(el.get("id"))] = cached
        else:
            missing.append(el)
    if missing and browser:
        fresh = _probe_page(browser, root, manifest, page_index, work_dir)
        for el in missing:
            found = fresh.get(str(el.get("id")))
            if isinstance(found, dict):
                items[str(el.get("id"))] = found
                _measure_cache_store(page, el, found)
    return items


def _attach_measure(browser: str, root: Path, manifest: dict, page: dict, page_index: int,
                    work_dir: Path) -> None:
    """把实测几何挂到元素上；元素没有实测数据时，对应的矢量写入会因缺料而回退截图。"""
    for el in page.get("elements", []):
        el.pop("_ac_measure", None)
    items = _page_measure(browser, root, manifest, page, page_index, work_dir)
    if not items:
        return
    for el in page.get("elements", []):
        found = items.get(str(el.get("id")))
        if isinstance(found, dict):
            el["_ac_measure"] = found


# ------------------------------------------------------------------ IR 对拍
# IR 公式（_table_geom 等）本应和浏览器实测基本一致。打开对拍后两边都算一遍，偏差超阈值
# 的写进导出警告 —— 只做诊断，不改变导出结果。默认关，ATOMIC_CANVAS_IR_DIFF=1 打开。
IR_DIFF = os.environ.get("ATOMIC_CANVAS_IR_DIFF", "").strip().lower() not in ("", "0", "false", "off")
IR_DIFF_TOL = 0.08  # 相对偏差阈值（8%）


def _ir_worst_diff(pred: list, real: list) -> float:
    """两组数字的最大相对偏差；项数对不上直接返回无穷（也是偏差）。"""
    if len(pred) != len(real):
        return float("inf")
    worst = 0.0
    for a, b in zip(pred, real):
        b = _num(b)
        if b <= 0.01:
            continue
        worst = max(worst, abs(_num(a) - b) / b)
    return worst


def _ir_diff_check(page: dict) -> list[str]:
    """对拍 IR 预测 vs 探针实测（当前只覆盖表格几何），返回偏差告警。"""
    if not IR_DIFF:
        return []
    notes = []
    for el in page.get("elements", []):
        if str(el.get("type") or "") != "table":
            continue
        measured = _ac_measure(el)
        cols, rws = measured.get("cols"), measured.get("rws")
        if not isinstance(cols, list) or not isinstance(rws, list):
            continue
        props = el.get("props") or {}
        rows = [list(r) if isinstance(r, (list, tuple)) else [r] for r in (props.get("rows") or [])]
        if not rows:
            continue
        geom = _table_geom(props, rows, max(1.0, _num(el.get("w"), 400)))
        worst = max(_ir_worst_diff(geom["col_w"], cols), _ir_worst_diff(geom["row_h"], rws))
        if worst > IR_DIFF_TOL:
            shown = "∞（项数不一致）" if math.isinf(worst) else f"{worst * 100:.1f}%"
            notes.append(f"[IR 对拍] {el.get('name') or el.get('id')}：表格几何偏差 {shown}"
                         f" 超过阈值 {IR_DIFF_TOL * 100:.0f}%")
    return notes


def _no_rotation(el: dict) -> bool:
    return abs(_num(el.get("rotate"))) <= 0.01


def _table_native_ok(el: dict) -> bool:
    """表格写原生 PPTX 表格：必须拿到浏览器实测列宽 / 行高，否则等分列宽就是变形。"""
    props = el.get("props") or {}
    if props.get("merges") or _num(props.get("radius")) > 0 or props.get("shadow"):
        return False          # 合并 / 圆角 / 投影在原生表格里表达不了，交回截图
    if not _no_rotation(el):
        return False
    m = _ac_measure(el)
    return m.get("kind") == "table" and bool(m.get("cols"))


def _dl_ok(el: dict) -> bool:
    """代码块 / 含公式的文本：有浏览器量好的「图元清单」就能一比一摆回来。"""
    if not _no_rotation(el) or _num(el.get("opacity"), 1) < 1:
        return False
    style = el.get("style") or {}
    if _CSS_GRADIENT.search(str(style.get("background") or style.get("fill") or "")):
        return False          # 渐变底在浏览器里量不出颜色，交回截图
    m = _ac_measure(el)
    return m.get("kind") == "dl" and bool(m.get("dp"))


_NATIVE_CHART_KINDS = {
    "bar": "COLUMN_CLUSTERED",
    "hbar": "BAR_CLUSTERED",
    "line": "LINE_MARKERS",
    "area": "AREA",
    "stackedArea": "AREA_STACKED",
    "pie": "PIE",
    "donut": "DOUGHNUT",
}

_CHART_KIND_ALIAS = {
    "column": "bar", "columns": "bar", "vbar": "bar", "barchart": "bar",
    "groupedbar": "bar", "stackedbar": "bar",
    "horizontalbar": "hbar", "barh": "hbar", "rowbar": "hbar",
    "hgroupedbar": "hbar", "hstackedbar": "hbar",
    "linechart": "line", "spline": "line", "curve": "line", "areachart": "area",
    "stackedarea": "stackedArea",
    "circle": "pie", "piechart": "pie", "ring": "donut", "doughnut": "donut", "donutchart": "donut",
}

_CHART_PRESETS = {
    "okabe": ["#0072b2", "#e69f00", "#009e73", "#d55e00", "#cc79a7", "#56b4e9", "#f0e442", "#999999"],
    "nature": ["#3c5488", "#e64b35", "#00a087", "#4dbbd5", "#f39b7f", "#8491b4", "#91d1c2", "#b09c85"],
    "grey": ["#404040", "#7d7d7d", "#a8a8a8", "#c9c9c9", "#5c5c5c", "#919191", "#bdbdbd", "#e0e0e0"],
}


def _chart_native_kind(props: dict) -> str:
    """画布图表类型 → PowerPoint 原生图表类型；映射不到的（雷达 / 散点 / 热力图…）返回空串。"""
    raw = str(props.get("kind") or "bar").strip()
    key = raw.lower().replace(" ", "").replace("_", "").replace("-", "")
    kind = _CHART_KIND_ALIAS.get(key, raw)
    if kind == "bar":
        return "COLUMN_STACKED" if props.get("stacked") else "COLUMN_CLUSTERED"
    if kind == "hbar":
        return "BAR_STACKED" if props.get("stacked") else "BAR_CLUSTERED"
    return _NATIVE_CHART_KINDS.get(kind, "")


def _chart_palette(props: dict) -> list:
    preset = _CHART_PRESETS.get(str(props.get("palettePreset") or ""))
    if preset:
        return preset
    raw = props.get("palette")
    if isinstance(raw, str):
        raw = re.split(r"[,，\n]", raw)
    if isinstance(raw, (list, tuple)):
        colors = [str(c).strip() for c in raw if str(c or "").strip()]
        if colors:
            return colors
    return CHART_PALETTE


def _chart_series(props: dict) -> tuple:
    """与 render-kit.js 的 chartData 同一套读法：首列类目，其余列各自成为一个系列。"""
    rows = [r for r in (props.get("rows") or []) if isinstance(r, (list, tuple)) and len(r)]
    labels = ["" if r[0] is None else str(r[0]) for r in rows]
    max_cols = max((len(r) for r in rows), default=0)
    headers = props.get("headers") if isinstance(props.get("headers"), list) else None
    names: list[str] = []
    values: list[list[float]] = []
    if max_cols >= 3:
        for c in range(1, max_cols):
            head = headers[c] if headers and len(headers) > c and headers[c] else ""
            names.append(str(head) or f"系列{c}")
            values.append([_num(r[c], 0) if len(r) > c else 0.0 for r in rows])
    else:
        head = headers[1] if headers and len(headers) > 1 and headers[1] else ""
        names.append(str(head) or str(props.get("seriesName") or "数值"))
        values.append([_num(r[1], 0) if len(r) > 1 else 0.0 for r in rows])
    custom = str(props.get("seriesNames") or "")
    if custom.strip():
        parts = [s.strip() for s in re.split(r"[,，]", custom)]
        for i in range(min(len(names), len(parts))):
            if parts[i]:
                names[i] = parts[i]
    return labels, names, values


def _chart_vector_ok(el: dict) -> bool:
    """统计图走矢量：拿到浏览器量出的图表 SVG 就按矢量贴（与画布同一份渲染结果）。

    探针拿不到 SVG（没装浏览器 / 探针失败）才退回原生 PPTX 图表 —— 那时本来也截不了图，
    有原生图表总比占位框强。
    """
    if not _no_rotation(el):
        return False
    m = _ac_measure(el)
    if m.get("kind") == "chart" and str(m.get("svg") or "").strip():
        return True
    props = el.get("props") or {}
    if not _chart_native_kind(props):
        return False
    return any(isinstance(r, (list, tuple)) and len(r) for r in (props.get("rows") or []))


# ------------------------------------------------------------------ 视觉元素栅格化
def _raster_mode(el: dict) -> str:
    """元素的导出方式：vector = 矢量优先（默认）/ raster = 稳截图。"""
    mode = str((el.get("props") or {}).get("rasterMode") or "").strip().lower()
    return "raster" if mode == "raster" else "vector"


_CSS_GRADIENT = re.compile(r"gradient\(|\burl\(", re.IGNORECASE)


def _plain_bg(style: dict, props: dict) -> bool:
    """底色是不是「纯色」。

    渐变 / 图片底有两种写法：props.fillType=gradient 是引擎认可的写法，但模型与旧工程更常
    直接把 CSS 的 `linear-gradient(...)` 塞进 style.background。这两种在 OOXML 与 SVG 里都
    没有属性级的等价表达，硬按矢量写就是「填充变白 / 填充属性非法」，只能回退截图。
    """
    if str(props.get("fillType") or "solid") not in ("solid", "none"):
        return False
    return not _CSS_GRADIENT.search(str(style.get("background") or style.get("fill") or ""))


def _plain_paint(el: dict) -> bool:
    """这份元素能不能用 OOXML 老老实实画出来：纯色、不透明、无投影 / 发光 / 倒影、无渐变。

    透明度、渐变、发光、倒影 OOXML 里都没有等价表达（硬做就是「变样」），带这些效果的
    只能回退截图；纯色不透明的才放心交给矢量。
    """
    props = el.get("props") or {}
    style = el.get("style") or {}
    return _plain_paint_no_bg(el) and _plain_bg(style, props)


def _plain_paint_no_bg(el: dict) -> bool:
    """除「填充本身」之外的效果能不能矢量表达（不透明度 / 投影 / 发光 / 倒影 / 半透明填充）。

    图片填充走 a:blipFill，不需要纯色底，所以它单独用这条判据，跳过 _plain_bg 的纯色检查。
    """
    props = el.get("props") or {}
    style = el.get("style") or {}
    if _num(el.get("opacity"), 1) < 1:
        return False
    if _has_shadow(style):
        return False
    if _num(props.get("fillOpacity"), 1) < 1:
        return False
    if props.get("shadowOn") or props.get("glowOn") or props.get("reflectOn"):
        return False
    return True


def _fill_image_rel(el: dict) -> str:
    """图形图片填充的素材相对路径；没开图片填充返回空串。"""
    props = el.get("props") or {}
    if str(props.get("fillType") or "") != "image":
        return ""
    return str(props.get("fillImage") or "").strip()


def _shape_paint_ok(el: dict) -> bool:
    """形状 / 路径的填充能不能原生表达：纯色走 solidFill，图片填充走 blipFill。"""
    if _fill_image_rel(el):
        return _plain_paint_no_bg(el)
    return _plain_paint(el)


_ARC_CMD = re.compile(r"[Aa]")


def _vector_ok(el: dict) -> bool:
    """「矢量优先」下这份元素有没有可靠的原生矢量映射；没有就自动回退截图。"""
    etype = str(el.get("type") or "")
    props = el.get("props") or {}
    if etype in ("text", "link"):
        if has_math(props.get("text")):
            # 含公式的文本一律截图：KaTeX 的根号靠内联 SVG 画，而图元清单只收矩形与文字
            # （探针 walk 不收内联 SVG），硬摆回去根号会整块消失；公式字形又取自自带字体
            # （KaTeX_Main 等），PowerPoint 里没有对应字体，摆出来的字也是错的。
            return False
        return _plain_bg(el.get("style") or {}, props)
    if etype == "image":
        # 翻转 / 亮度 / 对比度 PPTX 还能映射，模糊、灰度、饱和度不行
        f = props.get("filter") or {}
        return not (
            _num(f.get("blur")) > 0
            or _num(f.get("grayscale")) > 0
            or abs(_num(f.get("saturate"), 1) - 1) > 1e-6
        )
    if etype == "video":
        return True   # 幻灯片里嵌真视频（封面帧当海报）
    if etype == "scene":
        return True   # PPTX 里换成 GIF 动图 / 封面帧静图
    if etype == "connector":
        return bool(str(props.get("d") or "")) and _plain_paint(el)
    if etype == "path":
        if not str(props.get("d") or ""):
            return False
        if _ARC_CMD.search(str(props.get("d"))):
            return False  # 弧线在 OOXML 里只能折线近似，保真度不够，交回截图
        return _shape_paint_ok(el)
    if etype == "shape":
        return _shape_paint_ok(el)
    if etype == "table":
        return _table_native_ok(el)     # 原生 PPTX 表格（列宽 / 行高按浏览器实测值）
    if etype == "chart":
        return _chart_vector_ok(el)     # 探针实测的图表 SVG（矢量贴图，与画布一致）
    if etype == "code":
        return _dl_ok(el)               # 探针实测渲染的代码块 SVG（矢量贴图，与画布一致）
    # 分组容器 / 未知类型：OOXML 里没有等价表达，只能截图
    return False


def _needs_raster(el: dict) -> bool:
    """这份元素要不要靠截图。

    默认「矢量优先」：有可靠矢量映射（文字、图片、纯色形状与路径、连线）就直接写矢量；
    标了「稳截图」的、或矢量保不了的效果（渐变 / 投影 / 发光 / 半透明 / 公式 / 弧线）一律截图 ——
    这就是「失败自动回退截图」的第一道门，写入时再抛异常还有第二道门（见 _raster_fallback）。
    """
    if _raster_mode(el) == "raster":
        return True
    return not _vector_ok(el)


def _raster_ids(page: dict) -> list[str]:
    return [
        str(el.get("id"))
        for el in page.get("elements", [])
        if el.get("visible", True) and _needs_raster(el)
    ]


_ALPHA_PROBE_HTML = (
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>"
    "<style>html, body { margin:0; background:transparent !important; }</style>"
    "</head><body></body></html>"
)


def _alpha_supported(browser: str) -> bool:
    """探一次「截图能不能带透明通道」。

    `--default-background-color=00000000` 在个别浏览器版本上会被忽略，那时截出来是白底，
    贴回幻灯片就是一个白方块。判据只能是「本来就没画东西的地方是不是透明」，所以必须拿
    一张空页面去探：页面本身若有铺满画布的形状（本工程的「底板-底色」就是），那个地方
    本来就该不透明，拿它当判据必然误判成「透明失效」。
    """
    from PIL import Image

    work_dir = Path(tempfile.mkdtemp(prefix="noedit_core-alpha-"))
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-alpha-profile-"))
    page_path = work_dir / "probe.html"
    shot = work_dir / "probe.png"
    try:
        page_path.write_text(_ALPHA_PROBE_HTML, encoding="utf-8")
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--hide-scrollbars",
            "--default-background-color=00000000",
            "--window-size=200,120",
            f"--user-data-dir={profile}",
            f"--screenshot={shot}",
            page_path.resolve().as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)
        if not shot.exists():
            return False
        with Image.open(shot) as img:
            img.load()
            return img.convert("RGBA").getchannel("A").getextrema()[0] == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def _raster_pad(el: dict) -> float:
    """元素四周要留出的余量（CSS px）：容纳投影 / 模糊 / 旋转向外溢出的像素。

    宁可放宽：余量多了只是截图大一点，少了就会把投影或模糊的边切掉。按 box-shadow 的
    偏移 + 模糊 + 扩展、filter:blur 的 3σ 估一个下界，再和 RASTER_PAD 取大，最后封顶。
    """
    pad = float(RASTER_PAD)
    style = el.get("style") or {}
    shadow = _shadow_struct(style)
    if shadow:
        dx = abs(_num(shadow.get("dx")))
        dy = abs(_num(shadow.get("dy")))
        blur = max(0.0, _num(shadow.get("blur")))
        spread = max(0.0, _num(shadow.get("spread")))
        pad = max(pad, max(dx, dy) + blur + spread + 8)
    blur = _num((el.get("props") or {}).get("filter", {}).get("blur"))
    if blur > 0:
        pad = max(pad, blur * 3 + 8)
    return min(pad, 400.0)


def _raster_cell(el: dict) -> tuple[float, float, float, float]:
    """元素在画布上的外接矩形（含旋转外扩与视觉余量），返回左/上/宽/高。

    故意不「夹到画布内」：出血（部分在画布外）的元素也要完整截下来，否则会被切掉一半。
    旋转同理：CSS 绕中心旋转，取旋转后的外接矩形，四角才不会被切。
    """
    x, y = _num(el.get("x")), _num(el.get("y"))
    w, h = max(1.0, _num(el.get("w"), 100)), max(1.0, _num(el.get("h"), 100))
    pad = _raster_pad(el)
    rotate = _num(el.get("rotate"))
    if rotate:
        rad = math.radians(rotate)
        bw = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
        bh = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
        bx, by = x + (w - bw) / 2, y + (h - bh) / 2
        return (bx - pad, by - pad, bw + 2 * pad, bh + 2 * pad)
    return (x - pad, y - pad, w + 2 * pad, h + 2 * pad)


def _raster_sheets(page: dict, force: bool = False) -> list[dict]:
    """把该页要栅格化的元素排进若干张「格子表」。

    逐个按外接矩形铺进大图：从左到右、满了换行、再满了换下一张表；单张表长边不超过
    RASTER_SHEET_MAX（放不下就拆多张），免得一次截出几万像素的图（浏览器与 Pillow 都吃不消）。
    每张表带 {w, h, cells:[{el, canvas, sheet}]}，sheet 是该格在这张表上的落地矩形。
    force=True 时忽略导出方式，指定元素一律截（矢量写入失败后的回退用）。
    """
    els = [
        el for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0))
        if el.get("visible", True) and (force or _needs_raster(el))
    ]
    if not els:
        return []
    boxes = [(_raster_cell(el), el) for el in els]
    limit_w = max(float(RASTER_SHEET_MAX), max(b[2] for b, _ in boxes) + 2 * RASTER_GUTTER)
    limit_h = max(float(RASTER_SHEET_MAX), max(b[3] for b, _ in boxes) + 2 * RASTER_GUTTER)

    sheets: list[dict] = []
    cur: dict = {"w": 0.0, "h": 0.0, "cells": []}
    cx = cy = float(RASTER_GUTTER)
    row_h = 0.0
    for (bx, by, bw, bh), el in boxes:
        if cur["cells"] and cx + bw + RASTER_GUTTER > limit_w:  # 换行
            cx = float(RASTER_GUTTER)
            cy += row_h + RASTER_GUTTER
            row_h = 0.0
        if cur["cells"] and cy + bh + RASTER_GUTTER > limit_h:  # 换下一张表
            sheets.append(cur)
            cur = {"w": 0.0, "h": 0.0, "cells": []}
            cx = cy = float(RASTER_GUTTER)
            row_h = 0.0
        cur["cells"].append({"el": el, "canvas": (bx, by, bw, bh), "sheet": (cx, cy, bw, bh)})
        cur["w"] = max(cur["w"], cx + bw + RASTER_GUTTER)
        cur["h"] = max(cur["h"], cy + bh + RASTER_GUTTER)
        cx += bw + RASTER_GUTTER
        row_h = max(row_h, bh)
    if cur["cells"]:
        sheets.append(cur)
    for sheet in sheets:
        sheet["w"] = max(1, int(math.ceil(sheet["w"])))
        sheet["h"] = max(1, int(math.ceil(sheet["h"])))
    return sheets


def _screenshot_sheet(browser: str, sheet: dict, root: Path, work_dir: Path, index: int, part: int,
                      scale: float = RASTER_SCALE):
    """把一张格子表截成透明底 PNG，返回 PIL 图像（失败返回 None）。"""
    from PIL import Image

    html_path = work_dir / f"sheet-{index}-{part}.html"
    html_path.write_text(
        render_raster_sheet_html(sheet["w"], sheet["h"], _file_prefix(root), sheet["cells"]),
        encoding="utf-8",
    )
    shot = (work_dir / f"sheet-{index}-{part}.png").resolve()
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-shot-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        f"--force-device-scale-factor={scale}",
        "--default-background-color=00000000",  # 关键：否则透明处会被刷成白底
        f"--window-size={int(sheet['w'])},{int(sheet['h'])}",
        f"--user-data-dir={profile}",
        f"--screenshot={shot}",
        html_path.resolve().as_uri(),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
        if not shot.exists():
            return None
        with Image.open(shot) as img:
            img.load()
            return img.convert("RGBA")
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _raster_pieces(browser: str, page: dict, root: Path, work_dir: Path, index: int):
    """把该页所有要栅格化的元素截出来。

    返回 (pieces, images)：pieces 是 [{el, image, canvas, spot, scale}]——canvas 是元素在画布
    上的外接矩形、spot 是它在该张截图里的落地矩形、scale 是「截图像素 ÷ CSS 像素」（不写死 2，
    浏览器实际倍率有偏差也能对上）；images 是本次打开的截图，用完由调用方统一关闭。
    """
    pieces: list[dict] = []
    images: list = []
    for part, sheet in enumerate(_raster_sheets(page)):
        image = _screenshot_sheet(browser, sheet, root, work_dir, index, part)
        if image is None or not sheet["w"]:
            continue
        images.append(image)
        scale = image.width / float(sheet["w"])
        for cell in sheet["cells"]:
            pieces.append({
                "el": cell["el"],
                "image": image,
                "canvas": cell["canvas"],
                "spot": cell["sheet"],
                "scale": scale,
            })
    return pieces, images


def _place_raster(slide, piece: dict, work_dir: Path, index: int) -> bool:
    """从格子表截图里裁出该元素那一格，按它在画布上的位置/大小贴回幻灯片。"""
    from pptx.util import Emu

    bx, by, bw, bh = piece["canvas"]
    sx, sy, sw, sh = piece["spot"]
    scale = piece["scale"]
    if bw < 1 or bh < 1 or sw < 1 or sh < 1:
        return False
    crop = piece["image"].crop((
        int(round(sx * scale)), int(round(sy * scale)),
        int(round((sx + sw) * scale)), int(round((sy + sh) * scale)),
    ))
    if crop.getchannel("A").getbbox() is None:
        return False  # 全透明：这个元素没画出任何像素（比如空的分组容器），不用占一张图
    token = re.sub(r"[^0-9A-Za-z_-]", "", str(piece["el"].get("id") or "")) or "el"
    path = work_dir / f"crop-{index}-{token}.png"
    crop.save(path)
    slide.shapes.add_picture(
        str(path),
        Emu(int(bx * PX_TO_EMU)), Emu(int(by * PX_TO_EMU)),
        Emu(int(bw * PX_TO_EMU)), Emu(int(bh * PX_TO_EMU)),
    )
    return True


def _screenshot_element(browser: str, el: dict, root: Path, work_dir: Path, index: int,
                        scale: float = RASTER_SCALE):
    """单独把一个元素截成透明底 PNG（无视它的导出方式）。返回 (piece, image)，失败返回 (None, None)。

    矢量写入失败后的第二道门：既然原生映射写不出来，就按画布所见截一张贴回去，总比占位框强。
    """
    sheets = _raster_sheets({"elements": [el]}, force=True)
    if not sheets:
        return None, None
    sheet = sheets[0]
    image = _screenshot_sheet(browser, sheet, root, work_dir, index, 99, scale)
    if image is None:
        return None, None
    cell = sheet["cells"][0]
    piece = {
        "el": el,
        "image": image,
        "canvas": cell["canvas"],
        "spot": cell["sheet"],
        "scale": image.width / float(sheet["w"]),
    }
    return piece, image


def _raster_fallback(slide, el: dict, browser: str, root: Path, work_dir: Path, index: int) -> bool:
    """矢量写入失败时的回退：把元素截一张贴回幻灯片。成功返回 True。"""
    piece, image = _screenshot_element(browser, el, root, work_dir, index)
    try:
        return piece is not None and _place_raster(slide, piece, work_dir, index)
    finally:
        if image is not None:
            image.close()


# ------------------------------------------------------------------ 元素 → PPTX 写入注册表
# 按 type 分发（取代原先的 if / elif 链）。新增一种元素：写好上面的写入函数，再在这里登记一条。
def _pptx_text(slide, el: dict, root: Path, warnings: list) -> None:
    # 带公式的文本：按浏览器量好的图元清单摆回去，公式区域是真文本而不是 $..$ 源码；
    # 纯行内富文本走 _add_text 的多 run 文本框——保持单个可编辑文本框，字号回退时还能自动回流
    text = (el.get("props") or {}).get("text", "")
    if has_math(text) and _dl_ok(el) and _add_display_list(slide, el, _ac_measure(el).get("dp") or []):
        return
    _add_text(slide, el, text)


def _pptx_link(slide, el: dict, root: Path, warnings: list) -> None:
    props = el.get("props") or {}
    href = str(props.get("href") or "")
    text = props.get("text", "")
    # 同 _pptx_text：只有含公式才用图元清单，纯富文本保持单个多 run 文本框
    if has_math(text) and _dl_ok(el) and _add_display_list(slide, el, _ac_measure(el).get("dp") or [], href=href):
        return
    _add_text(slide, el, text, link=href)


def _pptx_code(slide, el: dict, root: Path, warnings: list) -> None:
    # 代码块优先贴探针实测渲染的 SVG（与画布一一对应，不变形）；拿不到才退回图元清单 / 整块文本
    if _add_code_svg(slide, el, root):
        return
    if _dl_ok(el) and _add_display_list(slide, el, _ac_measure(el).get("dp") or []):
        return
    _add_code(slide, el)


def _pptx_image(slide, el: dict, root: Path, warnings: list) -> None:
    if not _add_image(slide, el, root):
        _add_placeholder(slide, el, f"[图片缺失] {el.get('name', '')}")
        warnings.append(f"{el.get('name')}：素材文件不存在，已用占位框替代")


_VIDEO_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv", ".avi": "video/avi", ".mpg": "video/mpg",
    ".mpeg": "video/mpg", ".webm": "video/webm", ".ogv": "video/ogg",
}
# 音频也挂在 video 类型上（画布上就是这么存的），PPTX 里退回占位框，硬塞进 p:video 会变形
_AUDIO_ONLY_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wea", ".oga"}


def _video_placeholder(slide, el: dict, label: str) -> None:
    """视频没法嵌入时的落点：深色框 + 文件名。

    原来这里走的是通用占位框（浅灰），投影到幻灯片上就是「一片白」，等于什么都没看见。
    """
    clone = dict(el)
    style = dict(el.get("style") or {})
    style["background"] = str(style.get("background") or "1F2937")
    style["color"] = str(style.get("color") or "D7DEE8")
    clone["style"] = style
    _add_placeholder(slide, clone, label)


def _dark_poster(name: str):
    """抓不到封面帧时的兜底图：深色底 + 播放三角 + 文件名（Pillow 不在就返回 None）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    img = Image.new("RGB", (1280, 720), (31, 41, 55))
    draw = ImageDraw.Draw(img)
    draw.polygon([(596, 322), (596, 398), (664, 360)], fill=(120, 132, 148))
    text = str(name or "视频")
    font = None
    for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        try:
            font = ImageFont.truetype(cand, 28)
            break
        except OSError:
            continue
    if font is not None:
        try:
            box = draw.textbbox((0, 0), text, font=font)
            draw.text(((1280 - (box[2] - box[0])) / 2, 430), text, fill=(205, 213, 224), font=font)
        except (OSError, ValueError):
            pass
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    stream.seek(0)
    return stream


def _video_poster(props: dict, root: Path, name: str):
    """封面帧：dataURL 解成字节流 / 工程内路径直接用 / 都没有就现画一张深色图。"""
    poster = str(props.get("poster") or "")
    if poster.startswith("data:image") and "," in poster:
        try:
            return io.BytesIO(base64.b64decode(poster.split(",", 1)[1]))
        except Exception:  # noqa: BLE001 —— 数据坏了就退到兜底图
            return _dark_poster(name)
    if poster:
        path = (root / poster).resolve()
        if path.is_file():
            return str(path)
    return _dark_poster(name)


_P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
_P14_MEDIA = "{%s}media" % _P14_NS


def _apply_video_playback(frame, props: dict) -> None:
    """把音量 / 静音 / 自动播放 / 循环 / 全屏 / 未播放时隐藏写进 p:video 节点。

    只写 ISO/IEC 29500 里确实存在的属性，免得 PowerPoint 提示「需要修复」：
    p:video@fullScrn、p:cMediaNode@vol/@mute/@showWhenStopped、p:cTn@repeatCount、p:cond@delay。
    """
    from pptx.oxml.ns import qn

    pic = frame._element
    # p:video 挂在 p:sld/p:timing 下，形状本身在 p:sld/p:cSld/p:spTree 里，
    # 所以得顺着祖先往上找到 p:sld（直接 getparent().getparent() 只到 p:cSld）。
    sld = pic
    while sld is not None and sld.tag != qn("p:sld"):
        sld = sld.getparent()
    if sld is None:
        return
    for node in sld.iter(qn("p:video")):
        media = node.find(qn("p:cMediaNode"))
        if media is None:
            continue
        tgt = media.find(qn("p:tgtEl"))
        sp = None if tgt is None else tgt.find(qn("p:spTgt"))
        if sp is None or str(sp.get("spid")) != str(frame.shape_id):
            continue
        vol = max(0.0, min(1.0, _num(props.get("volume"), 1)))
        media.set("vol", str(int(round(vol * 100000))))
        if props.get("muted", True) is not False:
            media.set("mute", "1")
        # showWhenStopped=0 就是 PowerPoint 的「未播放时隐藏」：停下后只留封面帧那张图
        if props.get("hideWhenNotPlaying"):
            media.set("showWhenStopped", "0")
        if props.get("fullscreen"):
            node.set("fullScrn", "1")
        ctn = media.find(qn("p:cTn"))
        if ctn is None:
            return
        if props.get("loop"):
            ctn.set("repeatCount", "indefinite")   # 对应「循环播放，直到停止」
        st_cond = ctn.find(qn("p:stCondLst"))
        cond = None if st_cond is None else st_cond.find(qn("p:cond"))
        if cond is not None and props.get("autoplay"):
            cond.set("delay", "0")                 # delay=indefinite 是「单击时播放」
        return


def _apply_video_trim(frame, props: dict, warnings: list, name: str) -> None:
    """把剪辑起止写进 p14:media/p14:trim（st = 从片头裁掉、end = 从片尾裁掉，单位毫秒）。

    p14:media 是 add_movie 已经建好的骨架（p:nvPr/p:extLst/p:ext 里），这里只补一个 trim 子节点，
    并按 CT_Media 的元素顺序（trim, fade, bmkLst, extLst）插在最前面。
    从片尾裁多少得知道视频总时长，所以依赖导出前抓封面帧时一并写回的 props.duration。
    """
    from pptx.oxml import parse_xml

    start = max(0.0, _num(props.get("startTime")))
    end = max(0.0, _num(props.get("endTime")))
    duration = _num(props.get("duration"))
    if not start and not end:
        return
    st_ms = int(round(start * 1000))
    end_ms = 0
    if end:
        if duration > end:
            end_ms = int(round((duration - end) * 1000))
        else:
            warnings.append(
                f"{name}：设了剪辑结束时间但拿不到视频总时长，请先在属性面板点一次「生成封面帧」再导出，"
                "否则 PPTX 里只裁掉了片头"
            )
    media14 = None
    for node in frame._element.iter(_P14_MEDIA):
        media14 = node
        break
    if media14 is None:
        return
    trim = parse_xml('<p14:trim xmlns:p14="%s" st="%d" end="%d"/>' % (_P14_NS, st_ms, end_ms))
    media14.insert(0, trim)


def _pptx_video(slide, el: dict, root: Path, warnings: list) -> None:
    """视频：用 python-pptx 的 add_movie 把真视频嵌进 PPTX，PowerPoint 里能直接播。

    放映前显示的是封面帧这张图（导出前前端已经抓好写进 props.poster），
    所以幻灯片上看到的是画面而不是空白；抓不到封面帧也还有深色兜底图。
    """
    from pptx.util import Emu

    props = el.get("props") or {}
    name = str(el.get("name") or "视频")
    src = str(props.get("src") or "")
    box = (
        Emu(int(_num(el.get("x")) * PX_TO_EMU)),
        Emu(int(_num(el.get("y")) * PX_TO_EMU)),
        Emu(int(_num(el.get("w"), 420) * PX_TO_EMU)),
        Emu(int(_num(el.get("h"), 240) * PX_TO_EMU)),
    )
    path = (root / src).resolve() if src else None
    if path is None or not path.is_file():
        _video_placeholder(slide, el, f"[视频缺失] {name}")
        warnings.append(f"{name}：素材文件不在，幻灯片上用深色占位框替代")
        return
    if path.suffix.lower() in _AUDIO_ONLY_EXT:
        _video_placeholder(slide, el, f"[音频] {name}")
        warnings.append(f"{name}：音频在 PPTX 里以占位框呈现，请用 PowerPoint 的「插入 → 音频」补充")
        return
    try:
        frame = slide.shapes.add_movie(
            str(path), *box,
            poster_frame_image=_video_poster(props, root, name),
            mime_type=_VIDEO_MIME.get(path.suffix.lower(), "video/unknown"),
        )
    except Exception as exc:  # noqa: BLE001 —— 编解码/文件读坏都不该让整页导出挂掉
        _video_placeholder(slide, el, f"[视频嵌入失败] {name}")
        warnings.append(f"{name}：视频嵌入失败（{exc}），幻灯片上用深色占位框替代")
        return
    _apply_video_playback(frame, props)
    _apply_video_trim(frame, props, warnings, name)


def _pptx_table(slide, el: dict, root: Path, warnings: list) -> None:
    if not _add_table(slide, el):
        _add_placeholder(slide, el, "[空表格]")


def _pptx_chart(slide, el: dict, root: Path, warnings: list) -> None:
    # 统计图优先贴探针实测渲染的 SVG（与画布一一对应，不变形）；拿不到 SVG 才退回原生图表
    if _add_chart_svg(slide, el, root):
        return
    if not _add_chart(slide, el):
        _add_placeholder(slide, el, "[无数据图表]")


def _pptx_shape(slide, el: dict, root: Path, warnings: list) -> None:
    _add_shape(slide, el, root)


def _pptx_path(slide, el: dict, root: Path, warnings: list) -> None:
    """可编辑路径：勾了「PPTX 里保留为可编辑矢量」或拿不到浏览器截图时走这里。"""
    if _add_path_shape(slide, el, root) is None:
        _add_placeholder(slide, el, "[空路径]")


def _pptx_connector(slide, el: dict, root: Path, warnings: list) -> None:
    """元素间连线：勾了「PPTX 里保留为可编辑矢量」或拿不到浏览器截图时走这里。"""
    if _add_connector_shape(slide, el) is None:
        _add_placeholder(slide, el, "[空连线]")


def _pptx_group(slide, el: dict, root: Path, warnings: list) -> None:
    """分组容器不产出独立形状，子元素按各自类型分别导出。"""


def _pptx_scene(slide, el: dict, root: Path, warnings: list) -> None:
    """微场景在 PPTX 里放 GIF 动图（导出前由前端逐帧抓帧、Pillow 合成，路径经 scene_gifs 传进来）。

    PPTX 不是可执行环境，放不下活的 HTML；GIF 是它能"动"的唯一图片格式
    （python-pptx 按原字节嵌入，PowerPoint 放映时照常播放动画）。
    没有动图（场景没实现 seek(t) / 用户没勾选 / 抓帧失败）就退回封面帧静图，连封面帧都没有才是占位框。
    """
    from pptx.util import Emu

    props = el.get("props") or {}
    gif = str(el.get("_pptx_gif") or "")
    box = (
        Emu(int(_num(el.get("x")) * PX_TO_EMU)),
        Emu(int(_num(el.get("y")) * PX_TO_EMU)),
        Emu(int(_num(el.get("w"), 480) * PX_TO_EMU)),
        Emu(int(_num(el.get("h"), 270) * PX_TO_EMU)),
    )
    if gif:
        path = Path(gif)
        if path.exists():
            _apply_picture_effects(slide.shapes.add_picture(str(path), *box), el)
            return
        warnings.append(f"{el.get('name')}：微场景动图文件不在了，改放封面帧静图")

    poster = str(props.get("poster") or "")
    pic = None
    if poster.startswith("data:image") and "," in poster:
        try:
            stream = io.BytesIO(base64.b64decode(poster.split(",", 1)[1]))
            pic = slide.shapes.add_picture(stream, *box)
        except Exception:  # noqa: BLE001 —— 封面帧数据损坏时退化为占位框
            pic = None
    elif poster:
        path = (root / poster).resolve()
        if path.exists():
            pic = slide.shapes.add_picture(str(path), *box)
    if pic is None:
        _add_placeholder(slide, el, f"[微场景] {el.get('name', '')}")
        warnings.append(f"{el.get('name')}：微场景在 PPTX 中以封面帧呈现，当前没有可用封面帧，已用占位框替代")
        return
    _apply_picture_effects(pic, el)


_PPTX_WRITERS = {
    "text": _pptx_text,
    "link": _pptx_link,
    "code": _pptx_code,
    "image": _pptx_image,
    "video": _pptx_video,
    "table": _pptx_table,
    "chart": _pptx_chart,
    "shape": _pptx_shape,
    "path": _pptx_path,
    "connector": _pptx_connector,
    "group": _pptx_group,
    "scene": _pptx_scene,
}


def register_pptx_writer(etype: str, fn) -> None:
    """注册（或覆盖）一种元素的 PPTX 写入函数，供扩展新元素使用。"""
    if etype and fn:
        _PPTX_WRITERS[etype] = fn


def export_pptx(project_path: str, manifest: dict, out_dir: str = "", scene_gifs: dict | None = None) -> dict:
    """导出 PPTX（混合模式：矢量映射 + 视觉元素截图贴图）。

    scene_gifs：可选，{ 元素id: GIF 绝对路径 }。微场景动图必须在导出前由前端抓帧生成
    （后端不执行前端代码），这里只负责把它标到对应元素上，由 `_pptx_scene` 插进幻灯片。
    """
    try:
        from pptx import Presentation
    except ImportError:
        return {
            "ok": False,
            "path": "",
            "message": "缺少 python-pptx 依赖，无法导出 PPTX。请执行：pip install python-pptx",
        }

    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    canvas = manifest.get("canvas", {})
    cw, ch = int(canvas.get("width", 1280)), int(canvas.get("height", 720))
    gifs = {str(k): str(v) for k, v in (scene_gifs or {}).items() if k and v}

    prs = Presentation()
    prs.slide_width = int(cw * PX_TO_EMU)
    prs.slide_height = int(ch * PX_TO_EMU)
    blank = prs.slide_layouts[6]
    warnings: list[str] = []

    browser = _find_browser()
    # 截图必须能出透明底，否则元素贴回幻灯片会带一层白方块；先探一次再决定要不要走截图
    raster_ok = bool(browser) and _alpha_supported(browser)
    work_dir = Path(tempfile.mkdtemp(prefix="noedit_core-pptx-"))
    raster_pages = 0
    raster_missed = 0
    fallback_count = 0
    try:
        for index, page in enumerate(manifest.get("pages", [])):
            slide = prs.slides.add_slide(blank)
            _apply_page_background(slide, page, root, prs, work_dir, browser, warnings)
            # 先量一次浏览器实测几何：表格列宽、代码块 / 公式逐行排版、图表原生 SVG 都靠它
            _attach_measure(browser, root, manifest, page, index, work_dir)
            warnings.extend(_ir_diff_check(page))

            raster_ids = _raster_ids(page) if raster_ok else []
            pieces: dict[str, dict] = {}
            images: list = []
            if raster_ids:
                got, images = _raster_pieces(browser, page, root, work_dir, index)
                for piece in got:
                    pieces[str(piece["el"].get("id"))] = piece
                if pieces:
                    raster_pages += 1
                else:
                    raster_missed += 1

            for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0)):
                if not el.get("visible", True):
                    continue
                gif = gifs.get(str(el.get("id") or ""))
                if gif:
                    el["_pptx_gif"] = gif
                # 图表贴 SVG 时要现场截一张兜底帧，把浏览器 / 临时目录也挂到元素上（同 _pptx_gif 那套写法）
                el["_pptx_browser"] = browser
                el["_pptx_work"] = work_dir
                el["_pptx_index"] = index
                converted = _converted_image(el, root, work_dir, browser)
                if converted:
                    el["_pptx_src"] = converted
                # 按 z 序逐个落位：截图贴图与矢量元素混排，叠放次序和画布上一致
                piece = pieces.get(str(el.get("id")))
                if piece is not None:
                    if _place_raster(slide, piece, work_dir, index):
                        continue
                etype = el.get("type", "text")
                writer = _PPTX_WRITERS.get(etype)
                try:
                    if writer is None:
                        raise LookupError(f"未登记的元素类型：{etype}")
                    writer(slide, el, root, warnings)
                except Exception as exc:  # noqa: BLE001
                    name = el.get("name") or el.get("id")
                    # 矢量写不出来就自动回退截图（「矢量优先 / 稳截图」的后半句），总比占位框强
                    if raster_ok and _raster_fallback(slide, el, browser, root, work_dir, index):
                        fallback_count += 1
                        warnings.append(f"{name}：矢量写入失败（{exc}），已自动回退为截图")
                        continue
                    warnings.append(f"{name}：{exc}")
                    _add_placeholder(slide, el, f"[无法导出] {el.get('name', '')}")
            for image in images:
                image.close()

        target = _unique_path(_resolve_out_dir(root, out_dir) / f"{_safe_name(manifest)}.pptx")
        prs.save(str(target))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    message = f"已导出 PPTX（{len(manifest.get('pages', []))} 页）：{target}"
    if raster_pages:
        message += f"；{raster_pages} 页里矢量保不了的元素按截图贴图，文字 / 图表数据 / 表格单元格保持可编辑"
    if not browser:
        message += "；未找到 Edge/Chrome，视觉元素退回矢量映射，透明度/阴影/模糊可能不一致"
    elif not raster_ok:
        message += "；浏览器截图拿不到透明通道，视觉元素退回矢量映射，透明度/阴影/模糊可能不一致"
    if raster_missed:
        message += f"；{raster_missed} 页截图失败，已退回矢量映射"
    if fallback_count:
        message += f"；{fallback_count} 处矢量写入失败，已自动回退截图"
    if warnings:
        message += f"；{len(warnings)} 处降级处理"
    return {
        "ok": True,
        "path": str(target),
        "message": message,
        "format": "pptx",
        "warnings": warnings,
    }


# ---------------------------------------------------------------- WPS / Office 可视化导出
# 本机装了 WPS 演示或 PowerPoint 时，可以在当地把画布「画」进去：不再先生成一份 PPTX 草稿
# 再打开它，而是把每个元素逐个翻译成 COM 能接收的绘制原语（自选图形 / 文本框 / 图片），
# 通过 COM 一个一个推给演示文稿应用，让它当着人的面把这一页搭出来，最后另存为目标文件。
#
# 元素分两路走：COM 有等价表达的直接推原生对象（文字仍是可选中的真文本、形状仍是可拖拽的
# 自选图形）；COM 表达不了的（渐变 / 投影 / 发光 / 半透明 / 公式 / 弧线 / 表格 / 图表 / 代码块…）
# 先用无头浏览器按画布截成透明底 PNG，再当图片推过去 —— 一样是「推」，只是推的是像素。
#
# 不用 pywin32：走 PowerShell 的 New-Object -ComObject。Windows 自带 PowerShell，打包不必
# 再多带一份 win32com。演示文稿的 ProgID：WPS 演示 = KWPP.Application，微软 = PowerPoint.Application。
_OFFICE_APPS = (
    ("wps", "KWPP.Application", "WPS 演示"),
    ("powerpoint", "PowerPoint.Application", "PowerPoint"),
)
# Presentation.SaveAs 的格式常量：24 = ppSaveAsOpenXMLPresentation（.pptx）
_PP_SAVE_AS_PPTX = 24
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _ps_literal(value) -> str:
    """PowerShell 单引号字符串字面量：内部单引号翻倍。"""
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script: str, timeout: int = 300) -> tuple:
    """跑一段 PowerShell，返回 (returncode, stdout, stderr)。找不到 PowerShell 就返回失败。"""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return 127, "", "未找到 PowerShell"
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _registered_office_progids() -> set:
    """注册表里登记了哪些演示文稿 COM 组件（只查注册，不启动进程）。"""
    if os.name != "nt":
        return set()
    ids = ", ".join(_ps_literal(progid) for _, progid, _ in _OFFICE_APPS)
    script = (
        "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        f"foreach ($id in @({ids})) {{ try {{ if ([Type]::GetTypeFromProgID($id)) {{ $id }} }} catch {{}} }}"
    )
    code, out, _ = _run_powershell(script, timeout=30)
    if code != 0:
        return set()
    known = {progid for _, progid, _ in _OFFICE_APPS}
    return {line.strip() for line in out.splitlines() if line.strip() in known}


def probe_office() -> dict:
    """探测本机可用的演示文稿应用，按「WPS 优先，PowerPoint 次之」排好序。"""
    registered = _registered_office_progids()
    apps = [
        {"id": key, "label": label, "progid": progid}
        for key, progid, label in _OFFICE_APPS if progid in registered
    ]
    return {"apps": apps, "available": bool(apps), "preferred": apps[0]["id"] if apps else ""}


# 现场进度：PowerShell 那边每推进一个阶段 / 一页 / 一个元素就往 stdout 写一行
# 「##STAGE …」「##PAGE i/n」「##ELEM k/n」，这里边读边存；界面轮询 office_progress 取细节。
_OFFICE_PROGRESS: dict = {
    "active": False, "stage": "", "message": "", "page": 0, "pages": 0, "elem": 0, "elems": 0,
}
_OFFICE_TIMEOUT = 900
_OFFICE_READY_TIMEOUT = 90      # 等演示文稿应用把窗口亮出来的上限（秒）
_OFFICE_PLAN_WAIT_MS = 600000   # 窗口亮出来之后，守着等绘制计划落盘的上限（毫秒）


def office_progress() -> dict:
    """可视化导出的进度快照（给界面轮询）。"""
    return dict(_OFFICE_PROGRESS)


def _office_progress_begin() -> None:
    _OFFICE_PROGRESS.update({"active": True, "stage": "准备中", "message": "准备中…",
                             "page": 0, "pages": 0, "elem": 0, "elems": 0})


def _office_progress_stage(text: str) -> None:
    _OFFICE_PROGRESS.update({"stage": text, "message": text})


def _int_or(text, fallback: int) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return fallback


def _office_progress_note(line: str) -> None:
    """解析 PowerShell 写回来的一行 ## 进度标记。"""
    if line.startswith("##STAGE "):
        _office_progress_stage(line[8:].strip())
        return
    if line.startswith("##PAGE "):
        current, _, total = line[7:].strip().partition("/")
        _OFFICE_PROGRESS.update({"page": _int_or(current, 0), "pages": _int_or(total, 0),
                                 "elem": 0, "elems": 0})
    elif line.startswith("##ELEM "):
        current, _, total = line[7:].strip().partition("/")
        _OFFICE_PROGRESS.update({"elem": _int_or(current, 0), "elems": _int_or(total, 0)})
    else:
        return
    page, pages = _OFFICE_PROGRESS["page"], _OFFICE_PROGRESS["pages"]
    elem, elems = _OFFICE_PROGRESS["elem"], _OFFICE_PROGRESS["elems"]
    text = f"正在推送第 {page} / {pages} 页"
    if elems:
        text += f" · 元素逐个落笔 {elem} / {elems}"
    _OFFICE_PROGRESS.update({"stage": "推送中", "message": text})


# ------------------------------------------------------------------ 元素 → COM 绘制原语
# MsoAutoShapeType：element-schema.json 里的 86 个预设名，凡在 OOXML 里有稳定对应值的都登记在
# 这里；查不到可靠数值的一律走截图（round2DiagRect / snip2DiagRect 在微软文档里同为 157，
# flag / line 没有能确认的枚举值，都不冒险）。
_MSO_SHAPES = {
    "rect": 1, "roundRect": 5, "round1Rect": 151, "round2SameRect": 152,
    "snip1Rect": 155, "snip2SameRect": 156, "snipRoundRect": 154,
    "ellipse": 9, "triangle": 7, "rtTriangle": 8, "diamond": 4,
    "parallelogram": 2, "trapezoid": 3, "nonIsoscelesTrapezoid": 143,
    "pentagon": 12, "hexagon": 10, "heptagon": 145, "octagon": 6,
    "decagon": 144, "dodecagon": 146, "plaque": 28, "can": 13, "cube": 14,
    "bevel": 15, "donut": 18, "blockArc": 20, "pie": 142, "pieWedge": 175,
    "chord": 161, "teardrop": 160, "frame": 158, "halfFrame": 159, "corner": 162,
    "diagStripe": 141, "moon": 24, "sun": 23, "cloud": 179, "heart": 21,
    "lightningBolt": 22, "smileyFace": 17, "noSmoking": 19, "arc": 25,
    "star4": 91, "star5": 92, "star6": 147, "star7": 148, "star8": 93,
    "star10": 149, "star12": 150, "star16": 94, "star24": 95, "star32": 96,
    "rightArrow": 33, "leftArrow": 34, "upArrow": 35, "downArrow": 36,
    "leftRightArrow": 37, "upDownArrow": 38, "quadArrow": 39,
    "leftRightUpArrow": 40, "bentArrow": 41, "uturnArrow": 42, "leftUpArrow": 43,
    "notchedRightArrow": 50, "chevron": 52, "homePlate": 51,
    "flowChartProcess": 61, "flowChartDecision": 63, "flowChartTerminator": 69,
    "flowChartDocument": 67, "flowChartPredefinedProcess": 65,
    "flowChartInternalStorage": 66, "flowChartConnector": 73, "flowChartSort": 80,
    "flowChartExtract": 81, "flowChartMerge": 82, "flowChartMagneticDisk": 86,
    "flowChartOffpageConnector": 74,
    "wedgeRectCallout": 105, "cloudCallout": 108, "cross": 11, "mathPlus": 163,
}
_MSO_SHAPE_RECT = 1
_MSO_SHAPE_ROUNDED = 5
# ParagraphFormat.Alignment / TextFrame.VerticalAnchor / Line.DashStyle 的取值
_MSO_ALIGN = {"left": 1, "center": 2, "right": 3, "justify": 4}
_MSO_ANCHOR = {"top": 1, "middle": 3, "bottom": 4}
_MSO_LINE_DASH = {"solid": 1, "dot": 2, "roundDot": 3, "dash": 4, "dashDot": 5, "longDash": 7}


def _com_pt(px, default: float = 0.0) -> float:
    """CSS px → 磅。COM 的 Left / Top / Width / Height / 字号 / 行距都以磅为单位。"""
    return round(_num(px, default) * PT_PER_PX, 2)


def _com_rgb(value, default: str = "000000") -> int:
    """CSS 颜色 → COM 的 BGR 整数（VBA 的 RGB(r,g,b) = r + g*256 + b*65536）。"""
    raw = str(value or "").strip()
    if not raw or raw.lower() in ("transparent", "none"):
        raw = default
    color, alpha = _css_color(raw)
    if alpha <= 0:
        color, _ = _css_color(default)
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    return r + g * 256 + b * 65536


def _com_id(el: dict) -> str:
    """元素 id → 只留安全字符的文件名片段。"""
    return re.sub(r"[^0-9A-Za-z_-]", "", str(el.get("id") or "")) or "el"


def _com_box(el: dict) -> dict:
    """元素的位置 / 尺寸 / 旋转 → COM 原语的公共字段（磅）。"""
    return {
        "x": _com_pt(el.get("x")),
        "y": _com_pt(el.get("y")),
        "w": max(0.1, _com_pt(el.get("w"), 100)),
        "h": max(0.1, _com_pt(el.get("h"), 100)),
        "rot": round(_num(el.get("rotate")) % 360, 2),
    }


def _com_fill(style: dict, props: dict | None = None):
    """填充 → BGR 整数；没有填充时返回空串（PowerShell 侧据此关掉 Fill）。"""
    props = props or {}
    if str(props.get("fillType") or "solid") == "none":
        return ""
    background = str(style.get("background") or style.get("fill") or "").strip()
    if not background or background in ("transparent", "none"):
        return ""
    return _com_rgb(background, "FFFFFF")


def _com_line(style: dict, props: dict | None = None):
    """描边 → {color, width, dash}；没有描边返回 None。"""
    width = _num(style.get("borderWidth"))
    if width <= 0:
        return None
    props = props or {}
    dash = str(props.get("strokeDash") or "").strip()
    if not dash:
        dash = "dash" if str(style.get("borderStyle") or "solid") == "dashed" else "solid"
    return {
        "color": _com_rgb(style.get("borderColor"), "333333"),
        "width": max(0.25, _com_pt(width, 1)),
        "dash": _MSO_LINE_DASH.get(dash, 1),
    }


def _com_adj(radius, el: dict) -> float:
    """border-radius → 圆角矩形的 adj（半径占短边的比例，0.5 封顶）。"""
    radius = _num(radius)
    if radius <= 0:
        return 0.0
    short = max(1.0, min(_num(el.get("w"), 1), _num(el.get("h"), 1)))
    return round(min(0.5, radius / short), 4)


#: COM 的 Fill.UserPicture 能直接吃的位图格式。别的（svg / webp / ico…）它认不了，
#: 与其赌一把，不如让这个元素照旧走截图。
_COM_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".tif", ".tiff", ".wmf", ".emf"}


def _com_fill_image(el: dict, root: Path | None) -> str:
    """形状图片填充的素材绝对路径；COM 用不了（没开图片填充 / 找不到 / 格式不支持）返回空串。"""
    rel = _fill_image_rel(el)
    if not rel or root is None:
        return ""
    if "://" in rel or rel.lower().startswith("data:"):
        return ""  # 网络图 / 内联图：COM 这边引不了，交回截图
    path = (root / rel.lstrip("/\\")).resolve()
    if not path.is_file() or path.suffix.lower() not in _COM_IMAGE_EXT:
        return ""
    return str(path)


def _com_opaque(el: dict) -> bool:
    """这份元素用到的颜色是不是全不透明。

    COM 原语只会收到一个 BGR 整数，颜色里的 alpha 会被整个丢掉：深色页上那层
    `rgba(255,255,255,0.06)` 的卡片底色推过去就变成一整块纯白，卡片上的白字跟着消失。
    所以底色 / 描边 / 文字色里只要带透明度，就别硬推原语，交给截图去保真。
    """
    style = el.get("style") or {}
    for key in ("background", "fill", "borderColor", "color"):
        raw = str(style.get(key) or "").strip()
        if raw and raw.lower() not in ("transparent", "none") and _css_color(raw)[1] < 1:
            return False
    return True


def _com_native(el: dict, root: Path | None = None) -> bool:
    """这份元素能不能直接翻译成 COM 原语（自选图形 / 文本框），不用先截图。

    只有「文字」和「形状」两种：文字推过去是真文本、还能改字，形状推过去是原生自选图形。
    形状的填充既可以是纯色（Solid），也可以是图片（Fill.UserPicture，等价于 PowerPoint 的
    「图片填充 - 拉伸」）—— 只要素材是 COM 认得的位图、且没有别的花哨效果。
    其余（图片 / 表格 / 图表 / 代码块 / 公式 / 路径 / 连线 / 微场景 / 分组）一律走截图 ——
    与其猜一套 COM 写法，不如把浏览器画好的像素原样推过去，所见即所得。
    """
    etype = str(el.get("type") or "")
    props = el.get("props") or {}
    if _raster_mode(el) == "raster":
        return False
    if etype in ("text", "link"):
        if not _com_opaque(el):
            return False
        if has_math(props.get("text")) or _dl_ok(el):
            return False
        style = el.get("style") or {}
        if _num(el.get("opacity"), 1) < 1 or _has_shadow(style):
            return False
        if props.get("glowOn") or props.get("reflectOn"):
            return False
        return _plain_bg(style, props) and _num(props.get("fillOpacity"), 1) >= 1
    if etype == "shape":
        if props.get("flipH") or props.get("flipV"):
            return False
        if str(props.get("shape") or "rect") not in _MSO_SHAPES:
            return False
        if _fill_image_rel(el):
            # 图片填充：底色无关紧要，但别的效果（透明度 / 投影 / 发光 / 倒影）仍得能原生表达，
            # 素材也得是 COM 认得、找得到的位图；任一条不满足就交回截图。
            return _plain_paint_no_bg(el) and bool(_com_fill_image(el, root))
        return _com_opaque(el) and _plain_paint(el)
    return False


def _com_text_item(el: dict) -> dict:
    """文字 / 链接 → 文本框（带底色 / 描边时改用自选图形当卡片承载，这些效果才不丢）。"""
    props = el.get("props") or {}
    style = el.get("style") or {}
    text = props.get("text", "")
    item = _com_box(el)
    item["op"] = "text"

    card = None
    if _has_box(style):
        radius = _num(style.get("borderRadius"))
        card = {
            "type": _MSO_SHAPE_ROUNDED if radius > 0 else _MSO_SHAPE_RECT,
            "fill": _com_fill(style, props),
            "line": _com_line(style, props),
            "adj": _com_adj(radius, el),
        }
    item["card"] = card

    weight = str(style.get("fontWeight") or "")
    latin, ea = _font_stack(str(style.get("fontFamily") or "Microsoft YaHei"))
    # 导出前前端已按浏览器的真实断行结果切好行（props._wrapLines），照它摆换行点才与画布一致
    wrapped = props.get("_wrapLines")
    if isinstance(wrapped, list) and wrapped and "".join(str(x) for x in wrapped) == str(text or "").replace("\n", ""):
        lines = [str(x) for x in wrapped]
    else:
        lines = str(text or "").split("\n") or [""]

    size_px = _num(style.get("fontSize"), 24) or 24
    line_spacing = _num(style.get("lineHeight"))
    item.update({
        "lines": lines,
        "font": latin,
        "fontEa": ea,
        "size": _com_pt(size_px, 24),
        "bold": weight.isdigit() and int(weight) >= 600,
        "italic": str(style.get("fontStyle") or "") == "italic",
        "color": _com_rgb(style.get("color"), "1F2328"),
        "align": _MSO_ALIGN.get(str(style.get("textAlign") or style.get("align") or "").lower(), 1),
        "anchor": _MSO_ANCHOR.get(str(style.get("verticalAlign") or "").lower(), 1),
        # CSS 的 line-height 是「倍数 × 字号」，换成绝对磅值才逐行对齐（同 _add_text 的算法）
        "pitch": _com_pt(size_px * line_spacing) if line_spacing else 0,
        "space": _com_pt(style.get("paragraphSpacing")),
        "pad": _com_pt(style.get("padding")),
        "href": str(props.get("href") or "") if str(el.get("type")) == "link" else "",
    })

    # 行内富文本：把每行再按 props.runs 切成若干段，逐段在 COM 里改字体（整段仍是同一个文本框）。
    # start 是「整个文本（各行用 \r 连接）」里的 0 基偏移，PowerShell 侧 Characters(start + 1, len)。
    runs = _clean_runs(props.get("runs"), len(str(text or "")))
    segs = []
    if runs:
        offs = _line_offsets(str(text or ""), lines)
        base_bold = weight.isdigit() and int(weight) >= 600
        base_italic = str(style.get("fontStyle") or "") == "italic"
        base_color = item["color"]
        pos = 0
        for i, line in enumerate(lines):
            for seg_text, st in _line_segments(line, offs[i], runs):
                segs.append({
                    "start": pos, "len": len(seg_text),
                    "b": base_bold or bool(st.get("b")),
                    "i": base_italic or bool(st.get("i")),
                    "u": bool(st.get("u")),
                    "c": _com_rgb(st["c"]) if st.get("c") else base_color,
                    "hl": _com_rgb(st["bg"]) if st.get("bg") else None,
                })
                pos += len(seg_text)
            if i < len(lines) - 1:
                pos += 1   # 行间的 \r 也算一个字符
    item["segs"] = segs
    return item


def _com_shape_item(el: dict, root: Path | None = None) -> dict:
    """形状 → 原生自选图形（圆角矩形在 COM 里靠 adj 调圆角比例；图片填充额外带素材路径）。"""
    props = el.get("props") or {}
    style = el.get("style") or {}
    kind = str(props.get("shape") or "rect")
    radius = _num(style.get("borderRadius"))
    if radius > 0 and kind == "rect":
        kind = "roundRect"
    item = _com_box(el)
    item.update({
        "op": "shape",
        "type": _MSO_SHAPES.get(kind, _MSO_SHAPE_RECT),
        "fill": _com_fill(style, props),
        "line": _com_line(style, props),
        "adj": _com_adj(radius, el) if kind == "roundRect" else 0.0,
    })
    img = _com_fill_image(el, root)
    if img:
        item["img"] = img
    return item


def _com_picture_items(els: list, page_index: int, work_dir: Path, root: Path, browser: str,
                       gifs: dict, warnings: list) -> dict:
    """把 COM 表达不了的元素截成透明底 PNG，返回 {元素id: picture 原语}。

    复用内置导出那套格子表管线：一页的元素排进若干张大图，一次截完再逐格裁开 ——
    贴回幻灯片的就是画布上那一格像素，旋转 / 阴影 / 半透明 / 渐变全都原样带上。
    微场景若有前端抓好的 GIF 动图就直接推 GIF（PowerPoint 放映时会自己播），更接近原样。
    """
    out: dict = {}
    if browser:
        for part, sheet in enumerate(_raster_sheets({"elements": els}, force=True)):
            image = _screenshot_sheet(browser, sheet, root, work_dir, page_index, part)
            if image is None:
                continue
            try:
                scale = image.width / float(sheet["w"] or 1)
                for cell in sheet["cells"]:
                    bx, by, bw, bh = cell["canvas"]
                    sx, sy, sw, sh = cell["sheet"]
                    if bw < 1 or bh < 1 or sw < 1 or sh < 1:
                        continue
                    crop = image.crop((
                        int(round(sx * scale)), int(round(sy * scale)),
                        int(round((sx + sw) * scale)), int(round((sy + sh) * scale)),
                    ))
                    if crop.getchannel("A").getbbox() is None:
                        continue  # 全透明：这个元素没画出任何像素（比如空的分组容器），不用占一张图
                    path = work_dir / f"com-{page_index}-{part}-{_com_id(cell['el'])}.png"
                    crop.save(path)
                    out[str(cell["el"].get("id"))] = {
                        "op": "picture", "path": str(path),
                        "x": _com_pt(bx), "y": _com_pt(by),
                        "w": _com_pt(bw), "h": _com_pt(bh), "rot": 0.0,
                    }
            finally:
                image.close()
    for el in els:
        gif = gifs.get(str(el.get("id") or ""))
        if not gif or not Path(gif).exists():
            continue
        out[str(el.get("id"))] = {"op": "picture", "path": str(gif), **_com_box(el)}
    return out


def _com_background(page: dict, index: int, work_dir: Path, root: Path, browser: str,
                    canvas: tuple, warnings: list) -> dict:
    """页面背景 → COM 原语：纯色走幻灯片的 Background.Fill，背景图按 cover / contain 摆一张图。"""
    from PIL import Image

    bg = page.get("background") or {}
    kind = str(bg.get("type") or "solid")
    if kind == "none":
        return {}
    if kind == "image" and bg.get("image"):
        path = (root / str(bg["image"])).resolve()
        if path.exists():
            # svg / webp 这类嵌不进去的背景图先转成 PNG（否则 AddPicture 会直接失败）
            ready = _pptx_ready_image(path, work_dir, browser, "com-bg", canvas)
            if ready is not None:
                try:
                    with Image.open(ready) as img:
                        iw, ih = img.size
                except (OSError, ValueError):
                    iw = ih = 0
                cw, ch = canvas
                fit = str(bg.get("fit") or "cover")
                if not iw or not ih or fit == "fill":
                    box = (0.0, 0.0, cw, ch)
                else:
                    ratio = iw / ih
                    if fit == "contain":   # 整图缩进画布，居中留白
                        w = min(cw, ch * ratio)
                    else:                  # cover：铺满画布，多出来的溢到画布外（不会被显示）
                        w = max(cw, ch * ratio)
                    h = w / ratio
                    box = ((cw - w) / 2, (ch - h) / 2, w, h)
                return {"picture": str(ready), "x": _com_pt(box[0]), "y": _com_pt(box[1]),
                        "w": _com_pt(box[2]), "h": _com_pt(box[3])}
            warnings.append(f"第 {index + 1} 页的背景图 {path.name} 转换失败，本页改用底色")
    return {"color": _com_rgb(bg.get("color"), "FFFFFF")}


def _com_page(page: dict, index: int, work_dir: Path, root: Path, browser: str,
              canvas: tuple, gifs: dict, warnings: list) -> dict:
    """一页 → 绘制计划的 page 节点：背景 + 按 z 序排好的元素原语。"""
    els = [
        el for el in sorted(page.get("elements", []), key=lambda e: _num(e.get("z")))
        if el.get("visible", True)
    ]
    pictures = _com_picture_items([el for el in els if not _com_native(el, root)],
                                  index, work_dir, root, browser, gifs, warnings)

    items: list = []
    for el in els:
        if _com_native(el, root):
            items.append(_com_shape_item(el, root) if str(el.get("type")) == "shape" else _com_text_item(el))
            continue
        picture = pictures.get(str(el.get("id")))
        if picture is None:
            if browser:
                warnings.append(f"第 {index + 1} 页「{el.get('name') or el.get('id')}」没能截成图，已跳过")
            continue
        items.append(picture)

    return {
        "background": _com_background(page, index, work_dir, root, browser, canvas, warnings),
        "items": items,
    }


def _com_plan(project_path: str, manifest: dict, scene_gifs: dict | None, work_dir: Path,
              browser: str, warnings: list) -> dict:
    """把整份画布翻译成 COM 绘制计划（纯 JSON，PowerShell 那边读它照着画）。

    这里就是「本地逐元素翻译」的落点：COM 有等价表达的（文字、纯色形状）翻成原语直接推；
    表达不了的先用无头浏览器按画布截成透明底 PNG，再当图片推过去 —— 一样是「推」，只是推的是像素。
    """
    canvas = manifest.get("canvas") or {}
    cw = max(1.0, _num(canvas.get("width"), 1280))
    ch = max(1.0, _num(canvas.get("height"), 720))
    pages = manifest.get("pages") or []
    gifs = {str(k): str(v) for k, v in (scene_gifs or {}).items() if k and v}
    root = Path(project_path)
    if not browser:
        need = [el for page in pages for el in (page.get("elements") or [])
                if el.get("visible", True) and not _com_native(el, root)]
        if need:
            warnings.append(f"未找到 Edge/Chrome：{len(need)} 个 COM 表达不了的元素"
                            "（图片 / 表格 / 图表 / 代码块等）截不了图，本次已跳过")
    return {
        "width": _com_pt(cw),
        "height": _com_pt(ch),
        "pages": [
            _com_page(page, index, work_dir, root, browser, (cw, ch), gifs, warnings)
            for index, page in enumerate(pages)
        ],
    }


def _office_build_script(progid: str, plan_path: Path, abort_mark: Path, target: Path,
                         keep_open: bool) -> str:
    """拼出「可视化导出」长驻会话的 PowerShell 脚本。

    这个脚本一口气串起三件事：
      ① 立刻把演示文稿应用拉起来 —— 可见、铺满屏幕，并顶一页空白，让窗口先亮出来；
      ② 守着等 Python 把绘制计划写到 plan.json（本地逐元素翻译要花点时间，慢的正是这一步）；
      ③ 计划一到就新建一份空白演示文稿，照着计划一页一页、一个元素一个元素地画出来，
         最后另存为目标文件。
    中途用 ##STAGE / ##PAGE / ##ELEM 往 stdout 回话，Python 边读边更新进度；单个元素没画上
    只发一条 ##WARN，不打断整场。
    """
    helpers = (
        "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        # Write-Output 走管道时会攒在缓冲区里，显式 flush 进度才能实时冒到界面上；
        # 个别宿主下 [Console]::Out 可能是 null，这一下不能把整段脚本带崩
        "function F($t) { Write-Output $t; try { if ([Console]::Out) { [Console]::Out.Flush() } } catch {} }; "
        # 填充 / 描边：计划里用空串表示「不填」，用 null 表示「不描边」
        "function SetPaint($sh, $fill, $line) { "
        "  if ($null -ne $fill -and $fill -ne '') { "
        "    $sh.Fill.Solid(); $sh.Fill.ForeColor.RGB = [int]$fill "
        "  } else { "
        "    try { $sh.Fill.Visible = 0 } catch {} "
        "  }; "
        "  if ($null -ne $line) { "
        "    $sh.Line.Visible = -1; $sh.Line.ForeColor.RGB = [int]$line.color; "
        "    $sh.Line.Weight = [double]$line.width; "
        "    if ($line.dash) { $sh.Line.DashStyle = [int]$line.dash } "
        "  } else { "
        "    try { $sh.Line.Visible = 0 } catch {} "
        "  } "
        "}; "
        # 文字：整段先设一套字体 / 字号 / 颜色（没有行内样式时就是最终效果），带行内富文本
        # 的元素随后按 segs 逐段覆盖。
        # 行距一律按「绝对磅值」给（换行点才与画布一致），但 LineRuleWithin 这个开关
        # 两家恰好反着用：微软 PowerPoint 是 0=磅值 / -1=行数，WPS 演示是 0=行数 / -1=磅值。
        # 给成 0 的话 WPS 会把磅值当「行数」，行高被放大几十倍，文字直接被顶出框外。
        "function SetText($sh, $it) { "
        "  $tf = $sh.TextFrame; "
        "  $tf.WordWrap = -1; $tf.AutoSize = 0; "
        "  try { $tf.VerticalAnchor = [int]$it.anchor } catch {}; "
        "  $pad = [double]$it.pad; "
        "  $tf.MarginLeft = $pad; $tf.MarginRight = $pad; "
        "  $tf.MarginTop = $pad; $tf.MarginBottom = $pad; "
        "  $tr = $tf.TextRange; "
        "  $tr.Text = ($it.lines -join \"`r\"); "
        "  $tr.Font.Name = [string]$it.font; "
        "  if ($it.fontEa) { $tr.Font.NameFarEast = [string]$it.fontEa }; "
        "  $tr.Font.Size = [double]$it.size; "
        "  $tr.Font.Bold = $(if ($it.bold) { -1 } else { 0 }); "
        "  $tr.Font.Italic = $(if ($it.italic) { -1 } else { 0 }); "
        "  $tr.Font.Color.RGB = [int]$it.color; "
        # 行内富文本：整段字体设完后，再按 segs 逐段覆盖（加粗 / 斜体 / 下划线 / 变色 / 高亮）。
        # Characters 的第一个参数是 1 基下标，所以 start + 1；空段（空行）跳过。
        "  if ($it.segs) { "
        "    foreach ($sg in $it.segs) { "
        "      if ([int]$sg.len -le 0) { continue }; "
        "      try { "
        "        $seg = $tr.Characters([int]$sg.start + 1, [int]$sg.len); "
        "        $seg.Font.Bold = $(if ($sg.b) { -1 } else { 0 }); "
        "        $seg.Font.Italic = $(if ($sg.i) { -1 } else { 0 }); "
        "        $seg.Font.Underline = $(if ($sg.u) { -1 } else { 0 }); "
        "        $seg.Font.Color.RGB = [int]$sg.c; "
        "        if ($null -ne $sg.hl) { $seg.HighlightColor.RGB = [int]$sg.hl } "
        "      } catch {} "
        "    } "
        "  }; "
        "  $pf = $tr.ParagraphFormat; "
        "  $pf.Alignment = [int]$it.align; "
        "  $rule = $(if ($isWps) { -1 } else { 0 }); "
        "  if ([double]$it.pitch -gt 0) { $pf.LineRuleWithin = $rule; $pf.SpaceWithin = [double]$it.pitch }; "
        "  if ([double]$it.space -gt 0) { $pf.LineRuleBefore = $rule; $pf.SpaceBefore = [double]$it.space }; "
        "  if ($it.href) { $sh.ActionSettings(1).Hyperlink.Address = [string]$it.href }; "
        # WPS 的 AddTextbox 不认 Height 参数，建出来的框一律 29 磅高；填完字再把高度设回去，
        # 否则垂直居中的文字是按 29 磅的框对中的，整段会明显偏上/偏下
        "  try { $sh.Height = [double]$it.h } catch {} "
        "}; "
        # 一个元素：图片直接贴；形状先建自选图形；文字要卡片就先建图形再往里塞字
        "function Draw($sl, $it) { "
        "  if ($it.op -eq 'picture') { "
        "    $sh = $sl.Shapes.AddPicture([string]$it.path, 0, -1, "
        "      [double]$it.x, [double]$it.y, [double]$it.w, [double]$it.h); "
        "    if ($it.rot) { $sh.Rotation = [double]$it.rot }; "
        "    return "
        "  }; "
        "  if ($it.op -eq 'shape') { "
        "    $sh = $sl.Shapes.AddShape([int]$it.type, "
        "      [double]$it.x, [double]$it.y, [double]$it.w, [double]$it.h); "
        "    SetPaint $sh $it.fill $it.line; "
        # 图片填充：Fill.UserPicture 只给一个文件参数时就是把图拉满整个形状（= PowerPoint 的
        # 「图片填充 - 拉伸」），与内置导出写 a:blipFill 的观感一致；WPS 不认也只是退回底色，不打断
        "    if ($it.img) { try { $sh.Fill.UserPicture([string]$it.img) } catch {} }; "
        "    if ([double]$it.adj -gt 0) { try { $sh.Adjustments.Item(1) = [double]$it.adj } catch {} }; "
        "    if ($it.rot) { $sh.Rotation = [double]$it.rot }; "
        "    return "
        "  }; "
        "  if ($null -ne $it.card) { "
        "    $sh = $sl.Shapes.AddShape([int]$it.card.type, "
        "      [double]$it.x, [double]$it.y, [double]$it.w, [double]$it.h); "
        "    SetPaint $sh $it.card.fill $it.card.line; "
        "    if ([double]$it.card.adj -gt 0) { "
        "      try { $sh.Adjustments.Item(1) = [double]$it.card.adj } catch {} "
        "    } "
        "  } else { "
        "    $sh = $sl.Shapes.AddTextbox(1, "
        "      [double]$it.x, [double]$it.y, [double]$it.w, [double]$it.h) "
        "  }; "
        "  if ($it.rot) { $sh.Rotation = [double]$it.rot }; "
        "  SetText $sh $it "
        "}; "
    )
    body = (
        "$ErrorActionPreference = 'Stop'; "
        # $stage 一路记着「现在卡在哪一步」，出错时连同阶段名一起报出去，省得只看到一句没头没尾的异常
        "$app = $null; $pres = $null; $blank = $null; $books = $null; $done = $false; $stage = '启动'; "
        "try { "
        "  $stage = '创建 COM 实例'; "
        f"  $app = New-Object -ComObject {_ps_literal(progid)}; "
        # 认清对面到底是 WPS 演示还是微软 PowerPoint —— 两家对行距开关的取值恰好相反。
        # 注意 WPS 会把 Name 报成 "Microsoft PowerPoint"，只有安装路径骗不了人。
        "  $isWps = $false; "
        "  try { if (([string]$app.Path) -match 'wps|kingsoft') { $isWps = $true } } catch {}; "
        "  $stage = '显示窗口'; "
        "  try { $app.Visible = $true } catch {}; "
        # 关掉自带的提示框：一次保存失败要是弹出「保存失败」对话框，就会挡在重试前面，整场卡死
        "  try { $app.DisplayAlerts = 1 } catch {}; "
        # COM 服务刚被拉起来时 Presentations 未必就绪，反复取一会儿，别一次取空就往下走
        "  $stage = '等待应用就绪'; "
        "  for ($i = 0; $i -lt 60; $i++) { "
        "    try { $books = $app.Presentations } catch {}; "
        "    if ($books) { break }; "
        "    Start-Sleep -Milliseconds 250 "
        "  }; "
        "  if (-not $books) { throw '演示文稿应用没有就绪（拿不到 Presentations 集合）' }; "
        "  $stage = '新建空白稿'; "
        "  $blank = $books.Add(); "
        # 铺满屏幕：编辑态能做到的就是把窗口最大化（3 = 最大化）；真·全屏只有放映态才有，
        # 但放映态是整屏快照，元素落笔不会实时刷新，会毁掉「逐个摆放」的效果，所以不用。
        "  $stage = '最大化窗口'; "
        "  try { $app.WindowState = 3 } catch {}; "
        "  $stage = ''; "
        "  F '##READY'; "
        # 绘制计划由 Python 在本地逐元素翻译出来，这里守着等它落盘；收到中止标记就别等了
        f"  $deadline = (Get-Date).AddMilliseconds({_OFFICE_PLAN_WAIT_MS}); "
        f"  while (-not (Test-Path -LiteralPath {_ps_literal(plan_path)})) {{ "
        f"    if (Test-Path -LiteralPath {_ps_literal(abort_mark)}) {{ F '##ABORT'; break }}; "
        "    if ((Get-Date) -gt $deadline) { F '##TIMEOUT'; break }; "
        "    Start-Sleep -Milliseconds 200 "
        "  }; "
        f"  if (Test-Path -LiteralPath {_ps_literal(plan_path)}) {{ "
        "    if ($blank) { try { $blank.Close() } catch {}; $blank = $null }; "
        "    $stage = '读取绘制计划'; "
        f"    $plan = Get-Content -LiteralPath {_ps_literal(plan_path)} -Raw -Encoding UTF8 | ConvertFrom-Json; "
        "    $stage = '新建演示文稿'; "
        # 另起一份干净文稿：页面尺寸按画布换算成磅；先建够页数，再删掉 Add 自带的那一页
        "    $pres = $books.Add(); "
        "    try { $app.WindowState = 3 } catch {}; "
        "    $pres.PageSetup.SlideWidth = [double]$plan.width; "
        "    $pres.PageSetup.SlideHeight = [double]$plan.height; "
        "    $pages = @($plan.pages); "
        "    $total = $pages.Count; "
        "    for ($i = 1; $i -le $total; $i++) { "
        "      try { [void]$pres.Slides.Add($pres.Slides.Count + 1, 12) } catch {} "
        "    }; "
        "    try { if ($pres.Slides.Count -gt $total) { $pres.Slides.Item(1).Delete() } } catch {}; "
        "    $win = $null; try { $win = $pres.Windows.Item(1) } catch {}; "
        "    F '##STAGE 开始逐页推送'; "
        "    for ($n = 1; $n -le $total; $n++) { "
        "      $pg = $pages[$n - 1]; "
        "      $stage = \"第 $n 页\"; "
        "      F \"##PAGE $n/$total\"; "
        "      $sl = $pres.Slides.Item($n); "
        "      if ($win) { try { $win.View.GotoSlide($n) } catch {} }; "
        "      $bg = $pg.background; "
        "      if ($null -ne $bg) { "
        "        if ($null -ne $bg.color) { "
        "          try { $sl.FollowMasterBackground = 0 } catch {}; "
        "          try { "
        "            $sl.Background.Fill.Solid(); "
        "            $sl.Background.Fill.ForeColor.RGB = [int]$bg.color "
        "          } catch {} "
        "        } elseif ($null -ne $bg.picture) { "
        "          try { "
        "            [void]$sl.Shapes.AddPicture([string]$bg.picture, 0, -1, "
        "              [double]$bg.x, [double]$bg.y, [double]$bg.w, [double]$bg.h) "
        "          } catch {} "
        "        } "
        "      }; "
        "      $m = @($pg.items).Count; "
        "      for ($k = 1; $k -le $m; $k++) { "
        "        $it = $pg.items[$k - 1]; "
        "        try { Draw $sl $it } catch { "
        "          F ('##WARN ' + $stage + ' 第 ' + $k + ' 个元素没画上：' + $_.Exception.Message) "
        "        }; "
        "        F \"##ELEM $k/$m\"; "
        "      }; "
        "    }; "
        "    $stage = '另存为目标文件'; "
        # WPS 的另存为偶尔会抽风（报 0x8007007A / E_FAIL，隔一会儿再存又好了），
        # 所以这里连着重试几次：每次先把窗口拉到前台、停一下再存，失败也不弹框打断。
        "    $saved = $false; "
        "    for ($t = 1; $t -le 3; $t++) { "
        "      try { "
        "        if ($win) { try { $win.Activate() } catch {} }; "
        "        Start-Sleep -Milliseconds 400; "
        f"        $pres.SaveAs({_ps_literal(target)}, {_PP_SAVE_AS_PPTX}); "
        "        $saved = $true; break "
        "      } catch { "
        "        F ('另存重试 ' + $t + '：' + $_.Exception.Message); "
        "        Start-Sleep -Milliseconds 1200 "
        "      } "
        "    }; "
        "    if (-not $saved) { throw '连续三次另存都失败了' }; "
        "    F '##STAGE 已另存为目标文件'; F '##DONE'; $done = $true "
        "  } "
        "} catch { F ('##ERR [' + $stage + '] ' + $_.Exception.Message) }; "
        # 没成功就一律收尾退出；成功时看用户选的是「手动关闭」还是「自动关闭」
        "if (-not $done) { "
        "  if ($pres) { try { $pres.Close() } catch {} }; "
        "  if ($blank) { try { $blank.Close() } catch {} }; "
        "  try { $app.Quit() } catch {} "
        "} elseif (" + ("$false" if keep_open else "$true") + ") { "
        "  if ($pres) { try { $pres.Close() } catch {} }; "
        "  try { $app.Quit() } catch {} "
        "}; "
        "F 'OK'"
    )
    return helpers + body


_OFFICE_ERR = "##ERR"
_OFFICE_WARN = "##WARN"


class _OfficeSession:
    """一次可视化导出的本机会话：起 PowerShell、等窗口亮出来、最后收回结果。

    脚本一跑窗口就出现了，所以「在本地把画布逐个元素翻译成绘制计划」那段
    「慢功夫」可以挪到窗口亮出来之后再做 —— 用户不会对着一个没反应的面板干等。
    """

    def __init__(self, progid: str, plan_path: Path, abort_mark: Path, target: Path,
                 keep_open: bool):
        self.progid = progid
        self.plan_path = plan_path
        self.abort_mark = abort_mark
        self.target = target
        self.keep_open = keep_open
        self.proc = None
        self.settled = threading.Event()  # 窗口亮出来（##READY）或起不来（##ERR），二选一
        self.outcome = ""    # DONE / ABORT / TIMEOUT
        self.reason = ""     # ##ERR 带回来的失败原因
        self.warnings: list = []  # ##WARN 带回来的「某个元素没画上」
        self.plain: list = []  # 其它输出，兜底当失败原因
        self._readers: list = []

    def start(self) -> tuple:
        """拉起演示文稿应用并等它就绪。返回 (是否成功, 失败原因)。"""
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return False, "未找到 PowerShell"
        script = _office_build_script(self.progid, self.plan_path, self.abort_mark,
                                      self.target, self.keep_open)
        try:
            self.proc = subprocess.Popen(
                [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            return False, str(exc)
        for stream, is_progress in ((self.proc.stdout, True), (self.proc.stderr, False)):
            reader = threading.Thread(target=self._pump, args=(stream, is_progress), daemon=True)
            reader.start()
            self._readers.append(reader)
        if not self.settled.wait(_OFFICE_READY_TIMEOUT):
            self.stop()
            return False, "演示文稿应用没有在预期时间内就绪"
        if self.reason:
            self.stop()
            return False, self.reason
        return True, ""

    def _pump(self, stream, is_progress: bool) -> None:
        """边跑边读：进度要实时冒到界面上，所以不能等进程结束再一次性收 stdout。"""
        try:
            for raw in stream:
                text = raw.strip()
                if not text:
                    continue
                if not (is_progress and text.startswith("#")):
                    self.plain.append(text)
                elif text == "##READY":
                    self.settled.set()
                elif text.startswith(_OFFICE_ERR):
                    self.reason = text[len(_OFFICE_ERR):].strip()
                    self.settled.set()
                elif text.startswith(_OFFICE_WARN):
                    # 单个元素画不上不算致命：记下来，最后连同结果一起报出去
                    self.warnings.append(text[len(_OFFICE_WARN):].strip())
                elif text in ("##DONE", "##ABORT", "##TIMEOUT"):
                    self.outcome = text[2:]
                else:
                    _office_progress_note(text)
        finally:
            stream.close()

    def finish(self) -> tuple:
        """等这次会话收尾。返回 (是否成功, 失败原因)。"""
        try:
            code = self.proc.wait(timeout=_OFFICE_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return False, "演示文稿应用长时间没有响应，已中断"
        for reader in self._readers:
            reader.join(timeout=3)
        if code == 0 and self.outcome == "DONE":
            return True, ""
        if self.reason:
            return False, self.reason
        if self.outcome == "TIMEOUT":
            return False, "等绘制计划落盘超时"
        if self.outcome == "ABORT":
            return False, "绘制计划没能生成，已中止"
        return False, (self.plain[-1] if self.plain else f"调用失败（退出码 {code}）")

    def abort(self) -> None:
        """绘制计划没能生成时叫停：留个标记让 PowerShell 别再干等，然后把进程收掉。"""
        try:
            self.abort_mark.write_text("abort", encoding="utf-8")
        except OSError:
            pass
        self.stop()

    def stop(self, timeout: float = 15) -> None:
        if not self.proc:
            return
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for reader in self._readers:
            reader.join(timeout=2)


def export_pptx_via_office(project_path: str, manifest: dict, out_dir: str = "",
                           scene_gifs: dict | None = None, keep_open: bool = True) -> dict:
    """用 WPS 演示 / PowerPoint 生成 PPTX：**先把本机的演示文稿应用拉起来**（可见、铺满屏幕），
    再在本地把画布上的每个元素逐个翻译成 COM 调用，通过 COM 直接推给它，让它现场把演示文稿搭出来。

    顺序是刻意颠倒的：逐元素翻译要跑一遍无头浏览器截图，动辄几十秒，先起窗口能让人立刻看到
    反应，而不是干等。这两个动作分别在两个进程里跑，互不阻塞。

    优先级：WPS 演示 → PowerPoint；两者都不可用（或都调不通）时返回 ok=False，
    由界面弹窗告知「不能使用」。

    过程中**每页把元素一个个摆出来**再另存——这一步纯是给人看的（看着有排面），
    中间不留任何停顿，推完就翻下一页；期间通过 office_progress() 对外吐进度。

    keep_open：默认 True —— 导完把窗口留着，让用户自己看一眼再关（需求就是「不要自动关闭」）；
    传 False 则导出后自动关掉窗口。
    """
    _office_progress_begin()
    try:
        probe = probe_office()
        if not probe["available"]:
            return {
                "ok": False,
                "path": "",
                "format": "pptx",
                "message": "未检测到可用的 WPS 演示或 PowerPoint，无法使用「WPS / Office 可视化导出」。"
                           "请安装 WPS Office 或 Microsoft Office，或改用内置导出。",
            }

        root = Path(project_path)
        manifest = normalize_manifest(manifest)
        page_count = len(manifest.get("pages", []))
        # 目标路径必须给绝对路径：另存是由 WPS / PowerPoint 自己执行的，相对路径会被它
        # 按「自己进程的工作目录」去解析，然后报一句没头没尾的「保存失败」。
        target = _unique_path(_resolve_out_dir(root, out_dir) / f"{_safe_name(manifest)}.pptx").resolve()

        work = Path(tempfile.mkdtemp(prefix="noedit_core-office-"))
        # 绘制计划固定叫 plan.json（纯 ASCII），PowerShell 那边守着这个路径等它出现
        plan_path = work / "plan.json"
        abort_mark = work / "abort.marker"
        plan_warnings: list = []
        plan_written = False
        errors: list = []
        try:
            for app in probe["apps"]:
                _office_progress_stage(f"正在拉起 {app['label']}…")
                session = _OfficeSession(app["progid"], plan_path, abort_mark, target, keep_open)
                ok, detail = session.start()
                if not ok:
                    errors.append(f"{app['label']}：{detail}")
                    continue

                # 窗口这会儿已经铺满屏幕了，才轮到慢功夫：把画布逐个元素翻译成绘制计划
                if not plan_written:
                    _office_progress_stage("正在把画布逐个元素翻译成绘制计划…")
                    try:
                        plan = _com_plan(project_path, manifest, scene_gifs, work,
                                         _find_browser(), plan_warnings)
                    except Exception as exc:  # 翻译本身就出错时，别把窗口晾在那
                        session.abort()
                        return {
                            "ok": False,
                            "path": "",
                            "format": "pptx",
                            "message": f"把画布翻译成绘制计划时出错：{exc}",
                            "warnings": plan_warnings,
                        }
                    atomic_write_text(plan_path, json.dumps(plan))
                    plan_written = True

                ok, detail = session.finish()
                if ok:
                    tail = "（窗口已保留，看完自己关掉即可）" if keep_open else "（窗口已自动关闭）"
                    return {
                        "ok": True,
                        "path": str(target),
                        "message": f"已由 {app['label']} 逐元素推送生成 PPTX（{page_count} 页）{tail}：{target}",
                        "format": "pptx",
                        "warnings": plan_warnings + session.warnings,
                        "office": app["id"],
                    }
                errors.append(f"{app['label']}：{detail}")
            return {
                "ok": False,
                "path": "",
                "format": "pptx",
                "message": "本机的演示文稿应用都调不通 —— " + "；".join(errors) + "。可改用内置导出。",
                "warnings": plan_warnings,
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)
    finally:
        # 演示结束（无论成败）都把进度收起来，界面不再轮询
        _OFFICE_PROGRESS["active"] = False


# ------------------------------------------------------------------ 页码 / DPI 参数
_RASTER_DPI = (96, 150, 300, 600)
_PX_PER_INCH = 96  # CSS px 的基准分辨率（96 DPI 下 1px = 1/96 英寸）


def _dpi_scale(dpi) -> tuple:
    """DPI → (dpi, 截图倍率)。只认 96 / 150 / 300 / 600，其余取 300（投稿最常用的档）。"""
    try:
        value = int(float(dpi))
    except (TypeError, ValueError):
        value = 300
    if value not in _RASTER_DPI:
        value = 300
    return value, value / float(_PX_PER_INCH)


def _parse_pages(spec, total: int) -> list:
    """页码表达式 → 0 基页码列表：支持 1 / 1,3 / 2-5 / 混合；空 = 全部；认不出的项忽略。"""
    if total <= 0:
        return []
    text = str(spec or "").strip()
    if not text:
        return list(range(total))
    picks: list = []
    for chunk in re.split(r"[,\s;，、]+", text):
        if not chunk:
            continue
        span = re.fullmatch(r"(\d+)\s*[-~至]\s*(\d+)", chunk)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            numbers = range(min(low, high), max(low, high) + 1)
        elif chunk.isdigit():
            numbers = [int(chunk)]
        else:
            continue
        for number in numbers:
            if 1 <= number <= total and (number - 1) not in picks:
                picks.append(number - 1)
    return picks or list(range(total))


def _screenshot_page(browser: str, page_html: str, cw: int, ch: int, scale: float,
                     work_dir: Path, index: int, alpha: bool):
    """把一整页 HTML 截成图（按 dpi/96 倍率），返回 PIL 图像；失败返回 None。"""
    from PIL import Image

    html_path = work_dir / f"page-{index}.html"
    shot = work_dir / f"page-{index}.png"
    html_path.write_text(page_html, encoding="utf-8")
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-page-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        f"--force-device-scale-factor={scale}",
        f"--window-size={int(cw)},{int(ch)}",
    ]
    if alpha:
        cmd.append("--default-background-color=00000000")  # 透明底：没画到的地方不能被刷白
    cmd += [f"--user-data-dir={profile}", f"--screenshot={shot}", html_path.resolve().as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
        if not shot.exists():
            return None
        with Image.open(shot) as img:
            img.load()
            return img.convert("RGBA")
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# ------------------------------------------------------------------ PNG（透明底 / 高 DPI）
def export_png(project_path: str, manifest: dict, out_dir: str = "", options: dict | None = None) -> dict:
    """导出 PNG：逐页截图。支持透明背景与 300 / 600 DPI（投稿交图的常用规格）。"""
    from PIL import Image

    opts = options or {}
    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    target_dir = _resolve_out_dir(root, out_dir)
    pages = manifest.get("pages", [])
    picks = _parse_pages(opts.get("pages"), len(pages))
    if not picks:
        return {"ok": False, "path": "", "message": "工程里没有可导出的页面。"}
    browser = _find_browser()
    if not browser:
        return {
            "ok": False,
            "path": "",
            "message": "未找到 Microsoft Edge 或 Chrome，无法截图导出 PNG。请安装 Edge 后重试（也可导出静态 HTML 后在浏览器里另存图片）。",
        }
    dpi, scale = _dpi_scale(opts.get("dpi"))
    transparent = bool(opts.get("transparent"))
    # 透明底要靠浏览器截图带 alpha 通道，个别版本会忽略这个开关，先探一次
    alpha = transparent and _alpha_supported(browser)

    work_dir = Path(tempfile.mkdtemp(prefix="noedit_core-png-"))
    warnings: list[str] = []
    targets: list[str] = []
    try:
        for index in picks:
            page_html, cw, ch = render_page_html(manifest, index, _file_prefix(root), transparent)
            image = _screenshot_page(browser, page_html, cw, ch, scale, work_dir, index, alpha)
            if image is None:
                warnings.append(f"第 {index + 1} 页截图失败，已跳过")
                continue
            width, height = int(round(cw * scale)), int(round(ch * scale))
            if image.size != (width, height):
                # 浏览器偶尔按最小窗口尺寸出图，裁到画布尺寸，保证像素精确
                image = image.crop((0, 0, min(width, image.width), min(height, image.height)))
            if not alpha:
                # 不是透明底就压到白底：PNG 的 alpha 通道留着反而容易在别的软件里显黑
                flat = Image.new("RGB", image.size, (255, 255, 255))
                flat.paste(image, (0, 0), image)
                image = flat
            suffix = "" if len(picks) == 1 else f"-{index + 1:02d}"
            target = _unique_path(target_dir / f"{_safe_name(manifest)}{suffix}.png")
            image.save(target, dpi=(dpi, dpi))
            image.close()
            targets.append(str(target))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not targets:
        return {"ok": False, "path": "", "message": "PNG 导出失败：所有页面都没截成功。", "warnings": warnings}
    message = f"已导出 {len(targets)} 张 PNG（{dpi} DPI）：{target_dir}"
    if transparent and alpha:
        message += "；背景透明"
    elif transparent:
        message += "；当前浏览器截图拿不到透明通道，已铺白底"
        warnings.append("透明背景未生效：浏览器截图不带透明通道，已铺白底")
    return {
        "ok": True,
        "path": targets[0],
        "paths": targets,
        "message": message,
        "format": "png",
        "warnings": warnings,
    }


# ------------------------------------------------------------------ SVG（矢量优先 + 内嵌截图）
_SVG_SEQ = [0]

_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".avif": "image/avif",
}


def _svg_uid(prefix: str) -> str:
    _SVG_SEQ[0] += 1
    return f"{prefix}{_SVG_SEQ[0]}"


def _xml(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _svg_num(value) -> str:
    number = _num(value)
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


def _svg_color(value) -> str:
    text = str(value or "").strip()
    if text.lower() in ("", "none", "transparent"):
        return ""
    # 渐变 / 图片底不能当颜色属性用（fill="linear-gradient(...)" 是非法值，会整块不渲染）
    return "" if _CSS_GRADIENT.search(text) else text


def _data_uri(path: Path) -> str:
    """文件 → data URI（SVG 要自包含，不能依赖相对路径）。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    mime = _IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _svg_dash(kind: str, sw: float) -> str:
    """线型 → stroke-dasharray（与 web/js/render-kit.js 的 shapeDash 一致）。"""
    width = sw if sw > 0 else 1
    return {
        "dash": f"{width * 4} {width * 3}",
        "longDash": f"{width * 8} {width * 4}",
        "dot": f"{width * 0.1} {width * 2}",
        "dashDot": f"{width * 4} {width * 2} {width * 0.1} {width * 2}",
        "roundDot": f"{width * 0.1} {width * 2}",
    }.get(kind, "")


def _svg_rotate(el: dict, x: float, y: float, w: float, h: float) -> str:
    rotate = _num(el.get("rotate"))
    if not rotate:
        return ""
    return f' transform="rotate({_svg_num(rotate)},{_svg_num(x + w / 2)},{_svg_num(y + h / 2)})"'


def _svg_flood(color: str) -> tuple:
    """CSS 颜色 → (flood-color, flood-opacity)：feDropShadow / feFlood 不认 rgba()。"""
    text = str(color or "").strip()
    match = re.fullmatch(r"rgba?\(([^)]*)\)", text, re.IGNORECASE)
    if match:
        parts = [p for p in re.split(r"[,\s/]+", match.group(1)) if p]
        if len(parts) >= 3:
            return f"rgb({parts[0]},{parts[1]},{parts[2]})", (parts[3] if len(parts) >= 4 else "1")
    return text or "#000000", "1"


def _svg_gradient(uid: str, from_color: str, to_color: str, angle, w: float, h: float) -> str:
    """线性渐变：角度按 CSS 习惯（0° 左→右，90° 上→下），端点落在元素局部框 0..w / 0..h 上。

    渐变坐标系用 userSpaceOnUse，所以坐标必须是元素局部空间的坐标；把端点按「元素框在
    方向轴上的投影长度」铺开，才能让整条渐变刚好覆盖这个元素（端点过远会看着是纯色）。
    """
    rad = math.radians(_num(angle, 90))
    dx, dy = math.cos(rad), math.sin(rad)
    half = (abs(dx) * w + abs(dy) * h) / 2
    cx, cy = w / 2, h / 2
    return (
        f'<defs><linearGradient id="{uid}" gradientUnits="userSpaceOnUse"'
        f' x1="{_svg_num(cx - dx * half)}" y1="{_svg_num(cy - dy * half)}"'
        f' x2="{_svg_num(cx + dx * half)}" y2="{_svg_num(cy + dy * half)}">'
        f'<stop offset="0" stop-color="{_xml(from_color)}"/>'
        f'<stop offset="1" stop-color="{_xml(to_color)}"/></linearGradient></defs>'
    )


def _svg_stroke_attrs(props: dict, style: dict) -> str:
    """描边属性（stroke / width / linecap / linejoin / dasharray）；无描边时 stroke="none"。

    形状的 detail 附加线只描边、与轮廓共用同一份描边属性，所以单独抽出来复用。
    """
    sw = _num(style.get("borderWidth"))
    stroke = _svg_color(style.get("borderColor"))
    if not (sw > 0 and stroke):
        return 'stroke="none"'
    cap = {"round": "round", "square": "square"}.get(str(props.get("strokeCap") or ""), "butt")
    join = {"round": "round", "bevel": "bevel"}.get(str(props.get("strokeJoin") or ""), "miter")
    dash_kind = str(props.get("strokeDash") or "")
    if not dash_kind and str(style.get("borderStyle") or "") == "dashed":
        dash_kind = "dash"
    dash = _svg_dash(dash_kind, sw)
    attrs = (f'stroke="{_xml(stroke)}" stroke-width="{_svg_num(sw)}"'
             f' stroke-linecap="{cap}" stroke-linejoin="{join}"')
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    return attrs


def _svg_paint(props: dict, style: dict, w: float, h: float, rule: str = "nonzero") -> tuple:
    """填充 / 描边属性（与 render-kit 的 vectorSvg 对齐）。返回 (defs, attrs)。"""
    parts: list = [_svg_stroke_attrs(props, style)]
    defs = ""

    fill_type = str(props.get("fillType") or "solid")
    base = _svg_color(style.get("background")) or _svg_color(style.get("fill"))
    if fill_type == "none":
        parts.append('fill="none"')
    elif fill_type == "gradient":
        uid = _svg_uid("acg")
        defs = _svg_gradient(uid, base or "#ffffff",
                             _svg_color(props.get("fillGradientTo")) or "#ffffff",
                             props.get("fillGradientAngle"), w, h)
        parts.append(f'fill="url(#{uid})"')
        parts.append(f'fill-rule="{rule}"')
    else:
        parts.append(f'fill="{_xml(base) or "none"}"')
        parts.append(f'fill-rule="{rule}"')
        opacity = _num(props.get("fillOpacity"), 1)
        if opacity < 1:
            parts.append(f'fill-opacity="{_svg_num(opacity)}"')
    return defs, " ".join(parts)


def _svg_box(el: dict, style: dict, x: float, y: float, w: float, h: float) -> str:
    """文字 / 链接带底色、描边、圆角或投影时垫一张矩形（对应 PPTX 里的卡片）。"""
    background = _svg_color(style.get("background"))
    border_w = _num(style.get("borderWidth"))
    border_col = _svg_color(style.get("borderColor"))
    shadow = _shadow_struct(style)
    if not background and not (border_w > 0 and border_col) and shadow is None:
        return ""
    defs = ""
    filter_attr = ""
    if shadow is not None:
        uid = _svg_uid("acs")
        flood, flood_opacity = _svg_flood(str(shadow.get("color") or "#000000"))
        std = max(0.0, _num(shadow.get("blur")) / 2)
        defs = (
            f'<defs><filter id="{uid}" x="-50%" y="-50%" width="200%" height="200%">'
            f'<feDropShadow dx="{_svg_num(_num(shadow.get("dx")))}" dy="{_svg_num(_num(shadow.get("dy")))}"'
            f' stdDeviation="{_svg_num(std)}" flood-color="{_xml(flood)}"'
            f' flood-opacity="{_xml(flood_opacity)}"/></filter></defs>'
        )
        filter_attr = f' filter="url(#{uid})"'
    attrs = [
        f'x="{_svg_num(x)}"', f'y="{_svg_num(y)}"',
        f'width="{_svg_num(w)}"', f'height="{_svg_num(h)}"',
        f'fill="{_xml(background) or "none"}"',
    ]
    radius = _num(style.get("borderRadius"))
    if radius > 0:
        attrs.append(f'rx="{_svg_num(radius)}"')
    if border_w > 0 and border_col:
        attrs.append(f'stroke="{_xml(border_col)}" stroke-width="{_svg_num(border_w)}"')
    return f'{defs}<rect {" ".join(attrs)}{filter_attr}/>'


def _svg_line(line: str, base: int, runs: list) -> str:
    """SVG 一行文本按 runs 拆成 <tspan>；没有行内样式时就是一段纯文本。

    高亮底色在 <tspan> 上无法表达（SVG 文本没有背景），带高亮的文本由「图元清单」那条路
    负责（探针会量出底衬矩形），这里只兜住加粗 / 斜体 / 下划线 / 变色。
    """
    segs = _line_segments(line, base, runs)
    if len(segs) == 1 and not segs[0][1]:
        return _xml(line)
    parts = []
    for seg_text, st in segs:
        attrs = []
        if st.get("b"):
            attrs.append('font-weight="700"')
        if st.get("i"):
            attrs.append('font-style="italic"')
        if st.get("u"):
            attrs.append('text-decoration="underline"')
        if st.get("c"):
            attrs.append(f'fill="{_xml(st["c"])}"')
        if attrs:
            parts.append(f'<tspan {" ".join(attrs)}>{_xml(seg_text)}</tspan>')
        else:
            parts.append(_xml(seg_text))
    return "".join(parts)


def _svg_text(el: dict, text: str, href: str = "") -> str:
    """文本 / 链接 → SVG <text>。断行沿用导出前量好的 props._wrapLines，与画布逐行一致。"""
    style = el.get("style") or {}
    props = el.get("props") or {}
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = max(1.0, _num(el.get("w"), 200))
    h = max(1.0, _num(el.get("h"), 60))
    pad = _num(style.get("padding"))
    size = _num(style.get("fontSize"), 24)
    pitch = size * _num(style.get("lineHeight"), 1.5)
    para = _num(style.get("paragraphSpacing"))
    wrapped = props.get("_wrapLines")
    if isinstance(wrapped, list) and wrapped and "".join(str(v) for v in wrapped) == str(text or "").replace("\n", ""):
        lines = [str(v) for v in wrapped]
    else:
        lines = str(text or "").split("\n") or [""]

    # CSS 的行盒是把字形垂直居中放在 line-height 里；基线 ≈ 行盒顶 + 半个行距差 + 约 0.8em 上伸部
    block = len(lines) * pitch + max(0, len(lines) - 1) * para
    v_align = str(style.get("verticalAlign") or "top")
    if v_align == "middle":
        top = y + (h - block) / 2 + pad
    elif v_align == "bottom":
        top = y + h - block - pad
    else:
        top = y + pad
    align = str(style.get("textAlign") or style.get("align") or "left")
    if align == "center":
        tx, anchor = x + w / 2, "middle"
    elif align == "right":
        tx, anchor = x + w - pad, "end"
    else:
        tx, anchor = x + pad, "start"

    font = []
    family = str(style.get("fontFamily") or "").strip()
    if family:
        if "," not in family and family not in ("serif", "sans-serif", "monospace"):
            family += ", sans-serif"
        font.append(f'font-family="{_xml(family)}"')
    font.append(f'font-size="{_svg_num(size)}"')
    if style.get("fontWeight"):
        font.append(f'font-weight="{_xml(style["fontWeight"])}"')
    if style.get("fontStyle"):
        font.append(f'font-style="{_xml(style["fontStyle"])}"')
    if style.get("letterSpacing"):
        font.append(f'letter-spacing="{_svg_num(style["letterSpacing"])}"')
    font.append(f'fill="{_xml(_svg_color(style.get("color")) or "#1f2328")}"')

    indent = _num(style.get("textIndent"))
    runs = _clean_runs(props.get("runs"), len(str(text or "")))
    offs = _line_offsets(str(text or ""), lines)
    rows = []
    for i, line in enumerate(lines):
        baseline = top + i * (pitch + para) + (pitch - size) / 2 + size * 0.8
        extra = f' dx="{_svg_num(indent)}"' if indent and not i else ""
        rows.append(
            f'<text x="{_svg_num(tx)}" y="{_svg_num(baseline)}" text-anchor="{anchor}"{extra}>'
            f'{_svg_line(line, offs[i], runs)}</text>'
        )
    body = "".join(rows)
    if href:
        body = f'<a xlink:href="{_xml(href)}">{body}</a>'
    opacity = _num(el.get("opacity"), 1)
    op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    return (f'<g{_svg_rotate(el, x, y, w, h)}{op}>{_svg_box(el, style, x, y, w, h)}'
            f'<g {" ".join(font)}>{body}</g></g>')


def _svg_image(el: dict, root: Path) -> str:
    """图片 → 内嵌 base64 的 <image>（自包含），cover / contain / 翻转 / 亮度对比度都跟上。"""
    props = el.get("props") or {}
    style = el.get("style") or {}
    src = str(props.get("src") or "")
    if not src:
        return ""
    path = (root / src).resolve()
    if not path.is_file():
        return ""
    href = _data_uri(path)
    if not href:
        return ""
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = max(1.0, _num(el.get("w"), 200))
    h = max(1.0, _num(el.get("h"), 200))
    cx, cy = x + w / 2, y + h / 2
    fit = str(props.get("fit") or "cover")
    preserve = {"contain": "xMidYMid meet", "scale-down": "xMidYMid meet",
                "fill": "none"}.get(fit, "xMidYMid slice")
    radius = _num(style.get("borderRadius"))
    clip = ""
    if fit in ("cover", "fill") or radius > 0:
        uid = _svg_uid("aci")
        round_attr = f' rx="{_svg_num(radius)}"' if radius > 0 else ""
        clip = (f'<defs><clipPath id="{uid}"><rect x="{_svg_num(x)}" y="{_svg_num(y)}"'
                f' width="{_svg_num(w)}" height="{_svg_num(h)}"{round_attr}/></clipPath></defs>')
        clip_path = f' clip-path="url(#{uid})"'
    else:
        clip_path = ""

    parts = [f"translate({_svg_num(cx)},{_svg_num(cy)})"]
    rotate = _num(el.get("rotate"))
    if rotate:
        parts.append(f"rotate({_svg_num(rotate)})")
    scale_x = -1 if props.get("flipH") else 1
    scale_y = -1 if props.get("flipV") else 1
    if scale_x < 0 or scale_y < 0:
        parts.append(f"scale({scale_x},{scale_y})")
    parts.append(f"translate({_svg_num(-cx)},{_svg_num(-cy)})")
    transform = f' transform="{" ".join(parts)}"' if len(parts) > 1 else ""

    filters = props.get("filter") or {}
    bright = _num(filters.get("brightness"), 1)
    contrast = _num(filters.get("contrast"), 1)
    fdefs = ""
    fattr = ""
    if abs(bright - 1) > 1e-6 or abs(contrast - 1) > 1e-6:
        uid = _svg_uid("acf")
        slope = bright * contrast
        intercept = 0.5 - 0.5 * contrast
        funcs = "".join(
            f'<feFunc{chan} type="linear" slope="{_svg_num(slope)}" intercept="{_svg_num(intercept)}"/>'
            for chan in ("R", "G", "B")
        )
        fdefs = (f'<defs><filter id="{uid}" color-interpolation-filters="sRGB">'
                 f'<feComponentTransfer>{funcs}</feComponentTransfer></filter></defs>')
        fattr = f' filter="url(#{uid})"'
    opacity = _num(el.get("opacity"), 1)
    op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    return (
        f'<g{clip_path}{op}>{clip}{fdefs}'
        f'<image x="{_svg_num(x)}" y="{_svg_num(y)}" width="{_svg_num(w)}" height="{_svg_num(h)}"'
        f' preserveAspectRatio="{preserve}"{transform}{fattr} xlink:href="{href}"/></g>'
    )


def _svg_path(el: dict) -> str:
    """可编辑路径 → 真矢量 <path>，几何直接用 props.d（编辑期算好的局部坐标）。"""
    props = el.get("props") or {}
    style = el.get("style") or {}
    d = str(props.get("d") or "")
    if not d:
        return ""
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    rule = "evenodd" if str(props.get("fillRule") or "") == "evenodd" else "nonzero"
    defs, paint = _svg_paint(props, style, w, h, rule)
    # 平移到元素局部原点后，渐变（userSpaceOnUse）就落在 0..w / 0..h 这套坐标里
    rotate = _num(el.get("rotate"))
    spin = f" rotate({_svg_num(rotate)},{_svg_num(w / 2)},{_svg_num(h / 2)})" if rotate else ""
    opacity = _num(el.get("opacity"), 1)
    op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    return (
        f'<g transform="translate({_svg_num(x)},{_svg_num(y)}){spin}"{op}>{defs}'
        f'<path d="{_xml(d)}" {paint}/></g>'
    )


def _svg_connector(el: dict) -> str:
    """连线 → 真矢量：主路径描边 + 两端的箭头（props.d / arrowStartPath / arrowEndPath）。

    箭头按 props.arrowStartPaint / arrowEndPaint 决定画法：fill 实心填充、hollow 空心（白底 + 描边）、
    stroke 开放（只描边，如依赖箭头）。
    """
    props = el.get("props") or {}
    style = el.get("style") or {}
    d = str(props.get("d") or "")
    if not d:
        return ""
    x, y = _num(el.get("x")), _num(el.get("y"))
    sw = max(0.0, _num(style.get("borderWidth"), 2))
    col = _svg_color(style.get("borderColor")) or "#2f6fed"
    cap = {"round": "round", "square": "square"}.get(str(props.get("strokeCap") or ""), "butt")
    join = {"round": "round", "bevel": "bevel"}.get(str(props.get("strokeJoin") or ""), "round")
    dash_kind = str(props.get("strokeDash") or "")
    if not dash_kind and str(style.get("borderStyle") or "") == "dashed":
        dash_kind = "dash"
    dash = _svg_dash(dash_kind, sw)
    attrs = (f'fill="none" stroke="{_xml(col)}" stroke-width="{_svg_num(sw)}"'
             f' stroke-linecap="{cap}" stroke-linejoin="{join}"')
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    heads = ""
    for dkey, pkey in (("arrowStartPath", "arrowStartPaint"), ("arrowEndPath", "arrowEndPaint")):
        head = str(props.get(dkey) or "")
        if not head:
            continue
        paint = str(props.get(pkey) or "fill")
        if paint == "hollow":
            heads += (f'<path d="{_xml(head)}" fill="#ffffff" stroke="{_xml(col)}"'
                      f' stroke-width="{_svg_num(sw)}" stroke-linejoin="miter"/>')
        elif paint == "stroke":
            heads += (f'<path d="{_xml(head)}" fill="none" stroke="{_xml(col)}"'
                      f' stroke-width="{_svg_num(sw)}" stroke-linecap="round" stroke-linejoin="round"/>')
        else:
            heads += f'<path d="{_xml(head)}" fill="{_xml(col)}"/>'
    opacity = _num(el.get("opacity"), 1)
    op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    return (
        f'<g transform="translate({_svg_num(x)},{_svg_num(y)})"{op}>'
        f'<path d="{_xml(d)}" {attrs}/>{heads}</g>'
    )


def _svg_shape(el: dict) -> str:
    """形状 → 真矢量 <path>：轮廓 + 装饰线 detail；几何由 shape_outline 现算（与画布同源）。

    填充规则取几何自带值（形状默认 evenodd，甜甜圈 / 边框 / 月亮的洞靠它挖出来；云形标注 / 旗帜为 nonzero）；
    detail 只描边、与轮廓共用描边属性。
    """
    props = el.get("props") or {}
    style = el.get("style") or {}
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    geom = shape_geometry(props, w, h, style)
    d, detail = geom["d"], geom["detail"]
    if not d and not detail:
        return ""
    defs, paint = _svg_paint(props, style, w, h, geom["rule"])
    rotate = _num(el.get("rotate"))
    spin = f" rotate({_svg_num(rotate)},{_svg_num(w / 2)},{_svg_num(h / 2)})" if rotate else ""
    # 翻转与画布一致：绕元素中心做 scale（对应前端 shapeSvg 的 scaleX/scaleY）
    flip = ""
    if props.get("flipH") or props.get("flipV"):
        flip = (f" translate({_svg_num(w / 2)},{_svg_num(h / 2)})"
                f" scale({-1 if props.get('flipH') else 1},{1 if not props.get('flipV') else -1})"
                f" translate({_svg_num(-w / 2)},{_svg_num(-h / 2)})")
    opacity = _num(el.get("opacity"), 1)
    op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    body = f'<path d="{_xml(d)}" {paint}/>' if d else ""
    if detail:
        body += f'<path d="{_xml(detail)}" fill="none" {_svg_stroke_attrs(props, style)}/>'
    return f'<g transform="translate({_svg_num(x)},{_svg_num(y)}){spin}{flip}"{op}>{defs}{body}</g>'


def _svg_embedded(el: dict, piece) -> str:
    """截图内嵌：从格子表截图里裁出该元素那一格，base64 贴回它在画布上的矩形。"""
    if piece is None:
        return ""
    bx, by, bw, bh = piece["canvas"]
    sx, sy, sw, sh = piece["spot"]
    scale = piece["scale"]
    if bw < 1 or bh < 1 or sw < 1 or sh < 1:
        return ""
    crop = piece["image"].crop((
        int(round(sx * scale)), int(round(sy * scale)),
        int(round((sx + sw) * scale)), int(round((sy + sh) * scale)),
    ))
    if crop.getchannel("A").getbbox() is None:
        return ""  # 全透明：没画出任何像素（比如空的分组容器）
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return (
        f'<image x="{_svg_num(bx)}" y="{_svg_num(by)}" width="{_svg_num(bw)}" height="{_svg_num(bh)}"'
        f' preserveAspectRatio="none" xlink:href="data:image/png;base64,{data}"/>'
    )


def _svg_display_list(el: dict, dp: list, href: str = "") -> str:
    """「图元清单」→ SVG <g>：矩形 + 文本，与 PPTX 侧 _add_display_list 同源。

    表格、代码块、含公式的文本都走这条路：浏览器怎么排的，SVG 里就怎么摆，文字仍是真文本。
    """
    x0, y0 = _num(el.get("x")), _num(el.get("y"))
    parts: list = []
    for prim in dp or []:
        if not isinstance(prim, dict):
            continue
        x = x0 + _num(prim.get("x"))
        y = y0 + _num(prim.get("y"))
        w = _num(prim.get("w"))
        h = _num(prim.get("h"))
        if w <= 0.4 or h <= 0.4:
            continue
        opacity = _num(prim.get("o"), 1)
        op = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
        if prim.get("k") == "s":
            # 外投影：高斯模糊的实心矩形（CSS blur 半径 ≈ 2 倍标准差）
            fid = _svg_uid("acsh")
            op = ""   # 透明度落在 fill-opacity 上，避免与组不透明度重复相乘
            parts.append(
                f'<defs><filter id="{fid}" x="-100%" y="-100%" width="300%" height="300%">'
                f'<feGaussianBlur stdDeviation="{_svg_num(_num(prim.get("b")) / 2)}"/>'
                f'</filter></defs>'
                f'<rect x="{_svg_num(x + _num(prim.get("dx")))}"'
                f' y="{_svg_num(y + _num(prim.get("dy")))}" width="{_svg_num(w)}"'
                f' height="{_svg_num(h)}" fill="{_xml(prim.get("f") or "#000000")}"'
                f' fill-opacity="{_svg_num(opacity)}" filter="url(#{fid})"/>')
        elif prim.get("k") == "r":
            radius = _num(prim.get("r"))
            rx = f' rx="{_svg_num(radius)}"' if radius > 0 else ""
            parts.append(f'<rect x="{_svg_num(x)}" y="{_svg_num(y)}" width="{_svg_num(w)}"'
                         f' height="{_svg_num(h)}"{rx} fill="{_xml(prim.get("f") or "#ffffff")}"{op}/>')
        elif prim.get("k") == "t":
            text = str(prim.get("t") or "")
            if not text.strip():
                continue
            size = _num(prim.get("s"), 14)
            # 文本图元的框是行盒；基线落在框底往上约 0.22em（与 PPTX 的居中锚点同一套近似）
            baseline = y + h - size * 0.22
            font = [f'font-size="{_svg_num(size)}"', f'fill="{_xml(prim.get("c") or "#1f2328")}"']
            family = str(prim.get("f") or "").strip()
            if family:
                font.insert(0, f'font-family="{_xml(family)}"')
            if prim.get("b"):
                font.append('font-weight="700"')
            if prim.get("i"):
                font.append('font-style="italic"')
            if prim.get("u"):
                font.append('text-decoration="underline"')
            if _num(prim.get("sp")):
                font.append(f'letter-spacing="{_svg_num(_num(prim.get("sp")))}"')
            parts.append(f'<text x="{_svg_num(x)}" y="{_svg_num(baseline)}" text-anchor="start"'
                         f' {" ".join(font)}{op}>{_xml(text)}</text>')
    if not parts:
        return ""
    body = "".join(parts)
    if href:
        body = f'<a xlink:href="{_xml(href)}">{body}</a>'
    opacity = _num(el.get("opacity"), 1)
    gop = f' opacity="{_svg_num(opacity)}"' if opacity < 1 else ""
    return f'<g{gop}>{body}</g>'


def _svg_chart(el: dict) -> str:
    """统计图 → 内联浏览器量出来的真矢量 SVG（投稿排版里仍可编辑，放大不糊）。"""
    m = _ac_measure(el)
    svg = str(m.get("svg") or "")
    if not svg.lstrip().startswith("<svg") or not m.get("vb"):
        return ""
    x, y = _num(el.get("x")), _num(el.get("y"))
    w = max(1.0, _num(el.get("w"), 480))
    h = max(1.0, _num(el.get("h"), 300))
    family = str((el.get("style") or {}).get("fontFamily") or "Microsoft YaHei")
    end = svg.index(">")
    # 探针带的 style="width:100%" 会盖掉 x/y/width/height，必须去掉后自己写定位属性
    open_tag = re.sub(r'\sstyle="[^"]*"', "", svg[:end]).rstrip()
    if open_tag.endswith("/"):
        open_tag = open_tag[:-1].rstrip()
    body = svg[end + 1:]
    inner = body[: body.rindex("</svg>")] if "</svg>" in body else body
    markup = (f'{open_tag} x="{_svg_num(x)}" y="{_svg_num(y)}" width="{_svg_num(w)}"'
              f' height="{_svg_num(h)}" font-family="{_xml(family)}">{inner}</svg>')
    opacity = _num(el.get("opacity"), 1)
    return f'<g opacity="{_svg_num(opacity)}">{markup}</g>' if opacity < 1 else markup


def _svg_dl_ok(el: dict) -> bool:
    """SVG 侧：表格 / 代码块 / 公式只要有浏览器量好的图元清单，就能一比一摆回来。"""
    if not _no_rotation(el) or _num(el.get("opacity"), 1) < 1:
        return False
    style = el.get("style") or {}
    if _CSS_GRADIENT.search(str(style.get("background") or style.get("fill") or "")):
        return False
    m = _ac_measure(el)
    return m.get("kind") in ("dl", "table") and bool(m.get("dp"))


def _svg_shape_ok(el: dict) -> bool:
    """形状能不能写真矢量：几何现算，效果层表达不了就回退截图。

    形状级投影 / 发光 / 倒影、图片填充、旧式 CSS 渐变底 —— 这几类 _svg_shape 里都没画，
    宁可贴图也别少一层效果。纯色 / 引擎渐变 / 虚线 / 旋转 / 翻转 / 透明都能矢量。
    """
    props = el.get("props") or {}
    style = el.get("style") or {}
    if props.get("shadowOn") or props.get("glowOn") or props.get("reflectOn"):
        return False
    if _has_shadow(style):
        return False
    if str(props.get("fillType") or "solid") == "image":
        return False
    if _CSS_GRADIENT.search(str(style.get("background") or style.get("fill") or "")):
        return False
    w = max(1.0, _num(el.get("w"), 100))
    h = max(1.0, _num(el.get("h"), 100))
    geom = shape_geometry(props, w, h, style)
    return bool(geom["d"] or geom["detail"])


def _svg_vector_ok(el: dict) -> bool:
    """SVG 里能不能写真矢量。

    判定比 PPTX 宽：渐变、虚线、弧线、半透明、投影 SVG 都原生支持，没必要为了这些去贴图。
    只有「SVG 也表达不了」的（模糊 / 灰度 / 饱和度滤镜、发光 / 倒影、分组容器）才回退内嵌截图。
    表格 / 代码块 / 图表反过来：SVG 比 PPTX 还像，走浏览器实测的真矢量。
    含公式的文本例外：KaTeX 的根号是内联 SVG（图元清单收不到）且字形取自自带字体，
    矢量重建必失真，故与 PPTX 一样回退内嵌截图。
    形状同样走真矢量：轮廓由 shape_outline 现算（与画布 shapeSvg 同源），不需要浏览器截图。
    """
    etype = str(el.get("type") or "")
    props = el.get("props") or {}
    style = el.get("style") or {}
    if etype in ("text", "link"):
        if has_math(props.get("text")):
            # 同 PPTX：公式的根号（内联 SVG）与自带字体都还原不了，内嵌截图才保真。
            return False
        return _plain_bg(style, props)
    if etype in ("table", "code"):
        return _svg_dl_ok(el)              # 表格 / 代码块：rect + text 一比一重建
    if etype == "chart":
        return _chart_vector_ok(el) and bool(_ac_measure(el).get("svg"))
    if etype == "image":
        return _vector_ok(el)  # 亮度 / 对比度能换出来，模糊 / 灰度 / 饱和度不行
    if etype in ("path", "connector"):
        if not str(props.get("d") or ""):
            return False
        # 形状级投影 / 发光 / 倒影 _svg_path 里没画，宁可贴图也别少一层效果
        if props.get("shadowOn") or props.get("glowOn") or props.get("reflectOn"):
            return False
        return not _has_shadow(style)
    if etype == "shape":
        return _svg_shape_ok(el)
    return False


def _svg_page(manifest: dict, page_index: int, root: Path, scale: float, transparent: bool,
              browser: str, work_dir: Path) -> tuple:
    """一页 → SVG 文本。矢量保得了的写真矢量（含表格 / 代码块 / 公式 / 图表 / 形状），其余内嵌截图。"""
    canvas = manifest.get("canvas", {})
    cw = int(_num(canvas.get("width"), 1280))
    ch = int(_num(canvas.get("height"), 720))
    pages = manifest.get("pages", [])
    page = pages[page_index] if 0 <= page_index < len(pages) else {}
    # 与 PPTX 同源：先量一次浏览器实测几何（表格列宽、代码块 / 公式排版、图表原生 SVG）
    _attach_measure(browser, root, manifest, page, page_index, work_dir)

    body: list = []
    warnings: list = list(_ir_diff_check(page))
    if not transparent:
        bg = page.get("background") or {}
        kind = str(bg.get("type") or "solid")
        if kind == "image" and bg.get("image"):
            href = _data_uri((root / str(bg["image"])).resolve())
            if href:
                body.append(f'<image x="0" y="0" width="{cw}" height="{ch}"'
                            f' preserveAspectRatio="xMidYMid slice" xlink:href="{href}"/>')
        elif kind != "none":
            body.append(f'<rect x="0" y="0" width="{cw}" height="{ch}"'
                        f' fill="{_xml(bg.get("color") or "#ffffff")}"/>')

    for el in sorted(page.get("elements", []), key=lambda e: e.get("z", 0)):
        if not el.get("visible", True):
            continue
        props = el.get("props") or {}
        etype = str(el.get("type") or "")
        markup = ""
        if _raster_mode(el) != "raster" and _svg_vector_ok(el):
            href = str(props.get("href") or "") if etype == "link" else ""
            dp = _ac_measure(el).get("dp") or []
            if etype in ("text", "link"):
                rich = bool(props.get("runs"))
                markup = (_svg_display_list(el, dp, href) if dp and (has_math(props.get("text")) or rich)
                          else _svg_text(el, str(props.get("text") or ""), href))
            elif etype in ("table", "code"):
                markup = _svg_display_list(el, dp)
            elif etype == "chart":
                markup = _svg_chart(el)
            elif etype == "image":
                markup = _svg_image(el, root)
            elif etype == "path":
                markup = _svg_path(el)
            elif etype == "connector":
                markup = _svg_connector(el)
            elif etype == "shape":
                markup = _svg_shape(el)
        if markup:
            body.append(markup)
            continue
        # 剩下的（分组 / 微场景 / 缺实测几何的图表表格代码块 / 带特效的形状）一律内嵌截图
        piece, image = _screenshot_element(browser, el, root, work_dir, page_index, scale)
        try:
            markup = _svg_embedded(el, piece)
        finally:
            if image is not None:
                image.close()
        if markup:
            body.append(markup)
        else:
            warnings.append(
                f"{el.get('name') or el.get('id')}：截图里没有像素（画布上本来就是空白，或截图失败），SVG 里已跳过"
            )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
        f' width="{cw}" height="{ch}" viewBox="0 0 {cw} {ch}" preserveAspectRatio="none">\n'
        + "\n".join(body)
        + "\n</svg>\n"
    ), warnings


def export_svg(project_path: str, manifest: dict, out_dir: str = "", options: dict | None = None) -> dict:
    """导出 SVG：文字 / 表格 / 代码块 / 图表 / 形状 / 路径 / 连线都是真矢量，其余内嵌截图。

    投稿排版（LaTeX / Illustrator / Inkscape）里矢量图比 PPTX 好用得多，所以默认按「矢量优先」
    为每个元素挑表达方式；表格 / 代码块按浏览器实测的图元清单重建，图表直接内联它的原生
    SVG，形状轮廓按 shape_outline 现算（与画布同源）；曲线、渐变、投影这类矢量保不了的效果，
    以及含公式的文本（KaTeX 内联 SVG 根号 + 自带字体），就按 dpi 内嵌一张透明 PNG。
    """
    opts = options or {}
    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    target_dir = _resolve_out_dir(root, out_dir)
    pages = manifest.get("pages", [])
    picks = _parse_pages(opts.get("pages"), len(pages))
    if not picks:
        return {"ok": False, "path": "", "message": "工程里没有可导出的页面。"}
    browser = _find_browser()
    if not browser:
        return {
            "ok": False,
            "path": "",
            "message": "SVG 导出需要本机 Edge 或 Chrome（表格 / 代码块 / 公式要浏览器实测几何，"
                       "分组 / 微场景 / 带特效的元素要按画布截图内嵌）。请安装 Edge 后重试。",
        }
    dpi, scale = _dpi_scale(opts.get("dpi"))
    transparent = bool(opts.get("transparent"))
    warnings: list[str] = []
    if not _alpha_supported(browser):
        warnings.append("浏览器截图拿不到透明通道，内嵌的元素（分组 / 微场景 / 带特效的形状等）可能带一圈白底")

    work_dir = Path(tempfile.mkdtemp(prefix="noedit_core-svg-"))
    targets: list[str] = []
    try:
        for index in picks:
            svg, page_warnings = _svg_page(manifest, index, root, scale, transparent, browser, work_dir)
            warnings.extend(page_warnings)
            suffix = "" if len(picks) == 1 else f"-{index + 1:02d}"
            target = _unique_path(target_dir / f"{_safe_name(manifest)}{suffix}.svg")
            target.write_text(svg, encoding="utf-8")
            targets.append(str(target))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    message = f"已导出 {len(targets)} 个 SVG（内嵌图 {dpi} DPI）：{target_dir}"
    message += "；背景透明" if transparent else ""
    if warnings:
        message += f"；{len(warnings)} 处降级处理"
    return {
        "ok": True,
        "path": targets[0],
        "paths": targets,
        "message": message,
        "format": "svg",
        "warnings": warnings,
    }
