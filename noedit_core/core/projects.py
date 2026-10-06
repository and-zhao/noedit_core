"""工程文件夹模式：index.html（画布）+ project.manifest.json（清单）+ assets（素材）。

- 项目可整体迁移、离线打开，素材不丢失
- 原子元素状态、会话记录、历史记录全部序列化在 manifest 中随工程保存
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import assets as assets_mod
from . import element_schema
from . import scene_libs
from . import storage
from .paths import (
    APP_ROOT,
    ASSETS_DIR_NAME,
    CANVAS_HTML_NAME,
    LOCK_DIR,
    MANIFEST_NAME,
    SCHEMA_VERSION,
    WEB_DIR,
    atomic_write_text,
    ensure_dir,
)

CANVAS_PRESETS = {
    "ppt-16:9": {"width": 1280, "height": 720, "label": "PPT 16:9"},
    "ppt-4:3": {"width": 1024, "height": 768, "label": "PPT 4:3"},
    "slide-widescreen": {"width": 1600, "height": 900, "label": "宽屏演示 1600x900"},
    "a4-portrait": {"width": 794, "height": 1123, "label": "A4 纵向（简历）"},
    "a4-landscape": {"width": 1123, "height": 794, "label": "A4 横向（简历）"},
    "b5-portrait": {"width": 692, "height": 980, "label": "B5 纵向"},
}


def _now() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str = "el") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def default_page(name: str = "第 1 页") -> dict:
    return {
        "id": new_id("page"),
        "name": name,
        "background": {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"},
        "elements": [],
    }


# 参数元数据（web/element-schema.json）读不到时的兜底，与改造前的字面量一致
_FALLBACK_NAMES = {"text": "文本", "image": "图片", "video": "视频", "link": "链接",
                   "table": "表格", "code": "代码块", "shape": "形状", "path": "路径",
                   "connector": "连线", "group": "分组"}


def default_element(etype: str, **overrides) -> dict:
    """新元素：通用字段 + 该类型的初始参数（名称与尺寸取自 element-schema.json）。"""
    spec = element_schema.defaults(etype) or {}
    el = {
        "id": new_id("el"),
        "type": etype,
        "name": spec.get("name") or _FALLBACK_NAMES.get(etype, etype),
        "x": 80,
        "y": 80,
        "w": spec.get("w") or 400,
        "h": spec.get("h") or 200,
        "z": 1,
        "rotate": 0,
        "opacity": 1,
        "visible": True,
        "locked": False,
        "parentId": None,
        "props": spec.get("props") or {},
        "style": spec.get("style") or {},
    }
    el.update(overrides)
    return el


def default_manifest(name: str, ptype: str = "ppt", preset: str = "ppt-16:9") -> dict:
    p = CANVAS_PRESETS.get(preset, CANVAS_PRESETS["ppt-16:9"])
    return {
        "schema": SCHEMA_VERSION,
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "type": ptype,
        "createdAt": _now(),
        "updatedAt": _now(),
        "canvas": {
            "preset": preset,
            "width": p["width"],
            "height": p["height"],
            "background": {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"},
        },
        "pages": [default_page()],
        "assets": [],
        "sessions": [],
        "history": [],
    }


#: 投影的两种形态：
#:   - 结构化 style.shadow —— {dx,dy,blur,spread,color,alpha}，IR 的规范形态；
#:   - legacy style.boxShadow —— CSS 字符串，老工程里全是这一种。
#: 读盘 / 落盘都过 normalize_style：能解析的老字符串就地升级成结构体，解析不了（多层阴影、
#: inset 之类）的原样留着，渲染端按 legacy 路径照旧处理，效果一点都不丢。
_SHADOW_RE = re.compile(
    r"(?P<x>-?\d+(?:\.\d+)?)(?:px)?\s+"
    r"(?P<y>-?\d+(?:\.\d+)?)(?:px)?\s+"
    r"(?P<blur>\d+(?:\.\d+)?)px"
    r"(?:\s+(?P<spread>-?\d+(?:\.\d+)?)(?:px)?)?\s+"
    r"(?P<color>rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})"
)


def _fmt_num(value) -> str:
    """数字 → CSS 里好看的写法（最多两位小数，去掉尾零）。"""
    try:
        text = f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0"
    return text.rstrip("0").rstrip(".") or "0"


def shadow_color(text) -> tuple:
    """CSS 颜色 → (#RRGGBB, alpha)。只认 #rgb/#rrggbb/#rrggbbaa/rgb()/rgba()。"""
    raw = str(text or "").strip().lower()
    if raw.startswith(("rgb(", "rgba(")) and ")" in raw:
        parts = [p for p in re.split(r"[,\s/]+", raw[raw.index("(") + 1: raw.rindex(")")]) if p]
        if len(parts) >= 3:
            comps = []
            for item in parts[:3]:
                try:
                    value = float(item.rstrip("%"))
                except ValueError:
                    value = 0.0
                comps.append(value * 2.55 if item.endswith("%") else value)
            color = "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in comps)
            alpha = 1.0
            if len(parts) >= 4:
                last = parts[3]
                try:
                    alpha = float(last.rstrip("%")) / 100 if last.endswith("%") else float(last)
                except ValueError:
                    alpha = 1.0
            return color, max(0.0, min(1.0, alpha))
    body = raw.lstrip("#")
    if len(body) == 8:
        try:
            return "#" + body[:6].upper(), int(body[6:], 16) / 255
        except ValueError:
            return "#000000", 1.0
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    if re.fullmatch(r"[0-9a-f]{6}", body):
        return "#" + body.upper(), 1.0
    return "#000000", 1.0


def clean_shadow(shadow) -> dict:
    """结构化投影 → 规范形态（分量转数字、颜色转 #RRGGBB + alpha）。"""
    src = shadow if isinstance(shadow, dict) else {}
    def num(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)
    color, alpha = shadow_color(src.get("color"))
    if src.get("alpha") not in (None, ""):
        alpha = num(src.get("alpha"), alpha)
    return {
        "dx": num(src.get("dx")),
        "dy": num(src.get("dy")),
        "blur": max(0.0, num(src.get("blur"))),
        "spread": num(src.get("spread")),
        "color": color,
        "alpha": max(0.0, min(1.0, alpha)),
    }


def parse_shadow(text) -> dict | None:
    """CSS box-shadow 字符串 → 结构化投影；多层 / inset / 认不出的返回 None。"""
    raw = str(text or "").strip()
    if not raw or raw.lower() == "none":
        return None
    match = _SHADOW_RE.fullmatch(raw)     # fullmatch：整串必须是一层，多层的交给 legacy
    if not match:
        return None
    return clean_shadow({
        "dx": match.group("x"), "dy": match.group("y"),
        "blur": match.group("blur"), "spread": match.group("spread"),
        "color": match.group("color"),
    })


def shadow_to_css(shadow) -> str:
    """结构化投影 → CSS box-shadow 值。"""
    s = clean_shadow(shadow)
    body = str(s["color"]).lstrip("#")
    if s["alpha"] >= 1:
        color = f"#{body.upper()}"
    else:
        r, g, b = (int(body[i:i + 2], 16) for i in (0, 2, 4))
        color = f"rgba({r},{g},{b},{_fmt_num(s['alpha'])})"
    return (f"{_fmt_num(s['dx'])}px {_fmt_num(s['dy'])}px {_fmt_num(s['blur'])}px "
            f"{_fmt_num(s['spread'])}px {color}")


def _normalize_line_height(style: dict) -> None:
    """行高归一：面板写的是倍数（1.5），模型常写成像素（38）或百分比（150%）。

    像素按字号折回倍数（38 / 24 ≈ 1.58）、百分比 ÷100，最后夹进 0.85~4 —— 不折的话
    CSS 会把 38 当成 38 倍行距，整页崩版。规则与前端 store.js 的 normalizeLineHeight 一致。
    """
    raw = style.get("lineHeight")
    if raw is None or raw == "":
        return
    is_pct = isinstance(raw, str) and raw.strip().endswith("%")
    value = _num(str(raw).strip()[:-1], 0) if is_pct else _num(raw, 0)
    if value <= 0:
        style.pop("lineHeight", None)
        return
    if is_pct:
        value /= 100.0
    elif value > 3:                       # 只有认得出是「像素 ÷ 字号」才折算，否则当倍数
        fs = _num(style.get("fontSize"), 0)
        ratio = value / fs if fs > 0 else 0
        if 0.85 <= ratio <= 4:
            value = ratio
    style["lineHeight"] = round(min(4.0, max(0.85, value)), 2)


def _normalize_shadow(style: dict) -> None:
    """投影双读：结构体与 legacy 字符串互相补齐，最终只留结构体一种形态。

    结构体是规范形态；字符串只在「解析不了」时保留（渲染端按 legacy 处理），
    免得老工程里那些多层阴影因为升级而掉层。
    """
    shadow = style.get("shadow")
    if isinstance(shadow, str):           # shadow 被写成字符串：当 legacy 看待
        style.pop("shadow", None)
        style.setdefault("boxShadow", shadow)   # 交给下面 boxShadow 那条路径解析
        shadow = None
    if isinstance(shadow, dict):
        style["shadow"] = clean_shadow(shadow)
        style.pop("boxShadow", None)      # 两份都在时结构体为准
        return
    if "shadow" in style:
        style.pop("shadow", None)
    raw = str(style.get("boxShadow") or "").strip()
    if not raw or raw.lower() == "none":
        style.pop("boxShadow", None)
        return
    parsed = parse_shadow(raw)
    if parsed is not None:
        style["shadow"] = parsed
        style.pop("boxShadow", None)


#: 边框线型白名单 + CSS 简写解析用正则（见 _normalize_border）。
_BORDER_STYLES = ("solid", "dashed", "dotted", "double")
_BORDER_WIDTH_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*px")
_BORDER_COLOR_RE = re.compile(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))")


def _normalize_border(style: dict) -> None:
    """把 CSS 简写 style.border 拆成 borderWidth / borderStyle / borderColor。

    模型爱写 `border: "1px solid #E2E8F0"` 这类整串，引擎只认三个分量。目标键已存在时
    不动（显式分量优先）。`none` / 空串 → 视作无边框（borderWidth = 0）。
    """
    raw = style.pop("border", None)
    if raw is None:
        return
    text = str(raw).strip()
    if not text or text.lower() == "none":
        style.setdefault("borderWidth", 0)
        return
    width = _BORDER_WIDTH_RE.search(text)
    color = _BORDER_COLOR_RE.search(text)
    line = next((s for s in _BORDER_STYLES if s in text.lower()), None)
    if width:
        style.setdefault("borderWidth", float(width.group(1)))
    if line:
        style.setdefault("borderStyle", line)
    if color:
        style.setdefault("borderColor", color.group(1))


def _alias_value(value, values):
    """把别名值映射成目标字段要的写法（如 bold 的 true → 700）。"""
    if isinstance(values, dict):
        return values.get(value, value) if isinstance(value, bool) else values.get(str(value), value)
    return value


def _apply_alias(el: dict, src: str, target, declared: dict) -> None:
    """把元素里写成别名（src 点路径）的字段并回规范字段。

    只在「源键不是该类型已声明字段」时才生效：table 的 props.fontSize 是它自己的单元格
    字号，不能被别名抢走。target 可以是 "props.xxx" / "style.xxx" / 顶层键（如 name）。
    """
    head, _, key = src.partition(".")
    box = el.get(head)
    if not isinstance(box, dict) or key not in box:
        return
    if key in declared.get(head, ()):     # 是本类型合法字段，不动
        return
    to, values = (target, None) if isinstance(target, str) else (target.get("to"), target.get("values"))
    if not to:
        return
    value = _alias_value(box.pop(key), values)
    if value in (None, ""):               # 别用空值覆盖规范字段
        return
    t_head, _, t_key = to.partition(".")
    if t_key:                             # 目标在 props / style 里
        dest = el.setdefault(t_head, {})
        if isinstance(dest, dict):
            dest[t_key] = value
    else:                                 # 顶层键（name / opacity）
        el[to] = value


def _fit_table_height(el: dict) -> None:
    """表格掉高：按几何公式（与 render-kit.js 的 tableGeom 同一套）算出表格总高，把元素框撑到刚好装下。

    **只增不减** —— 用户在画布上手调小的框不动；显式设了裁切 / 滚动（overflow）的也不动。
    挂在 normalize_element 上，任何落盘通路都会走到，一并覆盖老工程与导出。
    """
    if not isinstance(el, dict) or el.get("type") != "table":
        return
    style = el.get("style") if isinstance(el.get("style"), dict) else {}
    if str(style.get("overflow") or "") in ("hidden", "auto", "scroll"):
        return
    props = el.get("props") if isinstance(el.get("props"), dict) else {}
    rows = props.get("rows") if isinstance(props.get("rows"), list) else []
    if not rows:
        return
    pad = _num(style.get("padding"), 0)
    bw = _num(style.get("borderWidth"), 0)
    width = _num(el.get("w"), 0) - 2 * pad - 2 * bw
    if width <= 0:                        # 没有可用宽度就无从判断折行，宁可不撑也别撑错
        return
    from .export import _table_geom       # 延迟导入：export 模块级反向依赖本模块，顶层引会成环
    geom = _table_geom(props, rows, width)
    need = math.ceil(sum(geom["row_h"]) + 2 * pad + 2 * bw)
    if need > _num(el.get("h"), 0):
        el["h"] = need


def normalize_element(el: dict, aliases: dict | None = None) -> dict:
    """把元素归一到引擎真正认识的字段。

    顺序：先按 schema 别名表并键（含放错容器的字段上浮），再依次规整边框 / 投影，最后表格掉高。
    """
    if not isinstance(el, dict):
        return {}
    table = aliases if aliases is not None else element_schema.aliases()
    if table:
        etype = str(el.get("type") or "")
        declared = element_schema.declared(etype)
        for src, target in table.items():
            _apply_alias(el, src, target, declared)
    style = el.get("style")
    normalize_style(style)
    if isinstance(style, dict):
        _normalize_border(style)
    _fit_table_height(el)
    return el


def normalize_style(style) -> dict:
    """把元素 style 归一到引擎真正认识的字段（见 _normalize_shadow / _normalize_line_height）。"""
    if not isinstance(style, dict):
        return {}
    _normalize_shadow(style)
    _normalize_line_height(style)
    return style


def normalize_manifest(data: dict) -> dict:
    """补齐缺失字段，保证前后端结构一致。"""
    if not isinstance(data, dict):
        raise ValueError("工程文件内容不是合法 JSON 对象")
    data.setdefault("schema", SCHEMA_VERSION)
    data.setdefault("id", uuid.uuid4().hex[:12])
    data.setdefault("name", "未命名项目")
    data.setdefault("type", "ppt")
    data.setdefault("createdAt", _now())
    data.setdefault("updatedAt", data.get("createdAt"))
    canvas = data.setdefault("canvas", {})
    preset = canvas.get("preset", "ppt-16:9")
    p = CANVAS_PRESETS.get(preset, CANVAS_PRESETS["ppt-16:9"])
    canvas.setdefault("preset", preset)
    canvas.setdefault("width", p["width"])
    canvas.setdefault("height", p["height"])
    canvas.setdefault("background", {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"})
    pages = data.setdefault("pages", [])
    if not pages:
        pages.append(default_page())
    aliases = element_schema.aliases()    # 循环外取一次，别每个元素都读一遍 schema
    for page in pages:
        page.setdefault("id", new_id("page"))
        page.setdefault("name", "未命名页")
        page.setdefault("background", {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"})
        page.setdefault("elements", [])
        for el in page["elements"]:
            if isinstance(el, dict):
                normalize_element(el, aliases)
    data.setdefault("assets", [])
    data.setdefault("sessions", [])
    data.setdefault("history", [])
    return data


# ---------------------------------------------------------------- 工程读写

def _occupied(path: Path) -> bool:
    """目录已存在且里面有东西（存在同名文件也算占用）。"""
    if not path.exists():
        return False
    if path.is_file():
        return True
    try:
        return any(path.iterdir())
    except OSError:
        return True


def unique_project_dir(parent: Path, name: str) -> Path:
    """同名工程已存在时自动追加 -2、-3……，避免「未命名项目」第二次新建就报错。"""
    target = Path(parent) / name
    if not _occupied(target):
        return target
    for i in range(2, 1000):
        candidate = Path(parent) / f"{name}-{i}"
        if not _occupied(candidate):
            return candidate
    raise ValueError(f"同名工程过多，请换个名称：{name}")


def create_project(
    target_dir: str,
    name: str,
    ptype: str = "ppt",
    preset: str = "ppt-16:9",
    template: dict | None = None,
) -> dict:
    root = Path(target_dir)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"目标文件夹非空：{root}")
    ensure_dir(root)
    assets_mod.assets_dir(root)

    if template:
        manifest = normalize_manifest(json.loads(json.dumps(template)))
        manifest["id"] = uuid.uuid4().hex[:12]
        manifest["name"] = name
        manifest["type"] = template.get("type", ptype)
        manifest["createdAt"] = _now()
        manifest["updatedAt"] = _now()
        manifest["assets"] = []
        manifest["sessions"] = []
        manifest["history"] = []
        tpl_dir = Path(template.get("_sourceDir", "")) if template.get("_sourceDir") else None
        if tpl_dir and (tpl_dir / ASSETS_DIR_NAME).exists():
            for f in (tpl_dir / ASSETS_DIR_NAME).iterdir():
                if f.is_file():
                    copied = assets_mod.assets_dir(root) / f.name
                    shutil.copy2(f, copied)
                    assets_mod.stretch_svg(copied)
                    manifest["assets"].append(
                        {
                            "id": new_id("asset"),
                            "name": f.name,
                            "relPath": f"{ASSETS_DIR_NAME}/{f.name}",
                            "kind": assets_mod.kind_of(f),
                            "size": f.stat().st_size,
                            "addedAt": _now(),
                            "origin": "",
                        }
                    )
    else:
        manifest = default_manifest(name, ptype, preset)

    saved = write_project(str(root), manifest, push=True, action="新建")
    return {"path": str(root), "manifest": saved["manifest"], "rev": saved["rev"]}


def load_project(project_path: str, action: str = "打开") -> dict:
    root = Path(project_path)
    # 出厂那份「首次启动默认工程」记的是相对路径：绝对路径指向打包机的磁盘，装到别人
    # 机器上就不存在，打开失败又被前端静默忽略，首页会一片空白（见 packaging/build.py
    # 的 _relativize_last_project）。相对路径统一按软件安装目录解析；
    # 用户自己打开/保存过的工程仍是绝对路径，逻辑不变。
    if not root.is_absolute():
        root = APP_ROOT / root
    if root.is_file():
        root = root.parent
    manifest_file = root / MANIFEST_NAME
    if not manifest_file.exists():
        raise ValueError(f"不是有效的工程文件夹（缺少 {MANIFEST_NAME}）：{root}")
    data = json.loads(read_text(manifest_file))
    manifest = normalize_manifest(data)
    storage.push_recent(str(root), manifest["name"], manifest["type"], action)
    settings = storage.get_settings()
    settings["lastProject"] = str(root)
    storage.save_settings(settings)
    # rev 是这一份内容的指纹，界面拿它当下一次保存的基线（见 write_project）。
    return {"path": str(root), "manifest": manifest, "rev": content_rev(manifest)}


# ---------------------------------------------------------------- 落盘与跨进程互斥
# 工程可能被多个进程同时写（并发的脚本 / agent 会话等）。
# 各方必须用同一份实现、同一个锁文件，否则等于没锁。

def read_text(target: Path) -> str:
    """读工程文件（atomic_write_text 的对应面）。

    替换的一瞬间，读者可能被系统短暂拒绝（访问被拒或文件正被替换），等一下重试即可。
    内容始终是完整的旧版或新版：替换本身是原子的，不会读到半截文件。
    """
    for attempt in range(5):
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.04)


def lock_file(root: Path) -> Path:
    """工程的锁文件：data/locks/<sha1(工程路径)>.lock。

    锁文件不放进工程目录，免得污染工程内容；命名用路径哈希，一个工程一把。
    """
    token = hashlib.sha1(str(Path(root).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return LOCK_DIR / f"{token}.lock"


_thread_locks: dict[str, threading.RLock] = {}
_thread_locks_guard = threading.Lock()
_holding = threading.local()


def _thread_lock(key: str) -> threading.RLock:
    with _thread_locks_guard:
        if key not in _thread_locks:
            _thread_locks[key] = threading.RLock()
        return _thread_locks[key]


def _held_keys() -> set[str]:
    keys = getattr(_holding, "keys", None)
    if keys is None:
        keys = _holding.keys = set()
    return keys


def _os_try_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _os_unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def project_lock(root: str | Path, timeout: float = 30.0):
    """工程级互斥：进程内按路径用 RLock 排队，跨进程用系统文件锁。

    系统锁按句柄计，同进程再开一个句柄会被自己挡住，所以记录了「本线程已持有」，
    同一线程嵌套进同一工程时只走 RLock，不重复抢系统锁。超时抛 TimeoutError。
    """
    key = str(Path(root).resolve()).lower()
    inner = _thread_lock(key)
    if not inner.acquire(timeout=timeout):
        raise TimeoutError(f"工程忙（等待超过 {int(timeout)} 秒）：{root}")
    held = _held_keys()
    handle = None
    try:
        if key not in held:
            ensure_dir(LOCK_DIR)
            handle = open(lock_file(root), "a+b")
            deadline = time.time() + timeout
            while True:
                try:
                    _os_try_lock(handle)
                    break
                except OSError:
                    if time.time() >= deadline:
                        raise TimeoutError(
                            f"工程被其他进程占用（等待超过 {int(timeout)} 秒）：{root}"
                        )
                    time.sleep(0.05)
            held.add(key)
        yield
    finally:
        if handle is not None:
            held.discard(key)
            _os_unlock(handle)
            handle.close()
        inner.release()


# ---------------------------------------------------------------- 基线校验与增量合并
# 工程可能被多个进程改（并发的脚本 / agent 会话等）。
# 整份覆盖会静默吞掉别人的改动，所以每次保存都带上「我这份是从哪个版本长出来的」——
# 锁内重算盘上那份的指纹，一致就直接写，不一致就按页合并（见 write_project）。

# 每次写盘都会变的字段，算指纹时摘掉：否则「内容没动、只是时间戳变了」也会被判成冲突。
_VOLATILE_KEYS = ("updatedAt",)

# 合并时允许被 delta 覆盖的工程级字段（其余字段如 id / createdAt / schema 一律以盘上那份为准）。
_META_KEYS = ("name", "type", "canvas")


def content_rev(manifest: dict) -> str:
    """工程内容指纹（16 位 hex）。

    算的是**内容**不是**文件字节**：缩进、键序不同但内容等价的两份 manifest 指纹相同。
    若按字节算，外部程序重排一次键就会误报「有人插队」，合并路径会被无谓触发。
    """
    clone = {k: v for k, v in (manifest or {}).items() if k not in _VOLATILE_KEYS}
    blob = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _manifest_on_disk(root: Path) -> dict | None:
    """读盘上那份 manifest；不存在 / 读不动 / JSON 坏了都当「还没有」处理。"""
    file = root / MANIFEST_NAME
    if not file.exists():
        return None
    try:
        return normalize_manifest(json.loads(read_text(file)))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def project_type(project_path: str | Path) -> str:
    """读工程清单里的资源类型（ppt / resume / …）；读不到返回空串。"""
    if not project_path:
        return ""
    data = _manifest_on_disk(Path(project_path))
    return str((data or {}).get("type") or "")


def merge_delta(base: dict, delta: dict) -> dict:
    """把一份增量合进 base（形状见 web/js/store.js 的 buildDelta）。

    delta = {
        pageOrder: [页 id ...],        # 界面当前看到的页序（含删页之后的顺序）
        pages: [整页 ...],             # 界面改过 / 新建的页
        removedPageIds: [...],         # 界面删掉的页
        meta: {name/type/canvas},      # 只带改过的工程级字段
        assets / sessions / history,   # 同上，只在变了的时候带
    }

    没被 delta 提到的页一律保留 base 的版本——外部程序刚加 / 刚改的页靠这一条活下来，
    这就是「我改过的页以我为准，我没碰过的页不动」。外部的页序改动会被界面的页序覆盖
    （两者不可能都赢），外部新加、界面还不知道的页排在末尾，不丢。
    """
    out = dict(base or {})
    by_id: dict[str, dict] = {}
    for page in out.get("pages") or []:
        if isinstance(page, dict) and page.get("id"):
            by_id[page["id"]] = page
    for page in delta.get("pages") or []:
        if isinstance(page, dict) and page.get("id"):
            by_id[page["id"]] = page
    for pid in delta.get("removedPageIds") or []:
        by_id.pop(pid, None)
    order = [pid for pid in (delta.get("pageOrder") or []) if pid in by_id]
    known = set(order)
    out["pages"] = [by_id[pid] for pid in order] + [p for pid, p in by_id.items() if pid not in known]
    meta = delta.get("meta")
    if isinstance(meta, dict):
        for key, value in meta.items():
            if key in _META_KEYS:
                out[key] = value
    for key in ("assets", "sessions", "history"):
        if isinstance(delta.get(key), list):
            out[key] = delta[key]
    return out


def write_project(
    project_path: str,
    manifest: dict | None = None,
    *,
    delta: dict | None = None,
    base_rev: str = "",
    push: bool = False,
    action: str = "保存",
) -> dict:
    """落盘。两条入口，最终都收敛成「把这次要写的内容合进盘上那份，再整体写出」。

    - manifest：整份写（新建 / 另存 / 没有基线可言的场合）
    - delta + base_rev：增量写（界面每次保存都走这条）。锁内先读盘上那份重算指纹：
      与 base_rev 一致 = 没人插队，直接合；不一致 = 外部程序刚写过，仍按页合，
      而不是把别人的改动整份盖掉（merged 为真，界面据此整屏同步一次）。
    """
    root = Path(project_path)
    # 全程持锁 + 两次原子写：并发的另一个写者要么在锁外等，要么看到完整文件，不会写出半截工程。
    with project_lock(root):
        ensure_dir(root)
        assets_mod.assets_dir(root)
        merged = False
        if delta is not None:
            disk = _manifest_on_disk(root)
            if disk is None:
                raise ValueError(f"工程清单已不在盘上（可能被外部删除或移动），无法增量保存：{root / MANIFEST_NAME}")
            # 盘上不是界面这份的基线 ⇒ 中间有别人写过。基线为空（没记过）时不报冲突：
            # 那是老客户端或首次落盘，合并结果仍然是「界面改过的页 + 盘上其余页」，不会丢东西。
            merged = bool(base_rev) and content_rev(disk) != base_rev
            manifest = merge_delta(disk, delta)
        elif manifest is None:
            raise ValueError("保存内容为空")
        manifest = normalize_manifest(manifest)
        manifest["updatedAt"] = _now()
        valid = []
        for a in manifest.get("assets", []):
            rel = a.get("relPath", "")
            if rel and (root / rel).exists():
                a["size"] = (root / rel).stat().st_size
                valid.append(a)
        manifest["assets"] = valid
        atomic_write_text(
            root / MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        atomic_write_text(root / CANVAS_HTML_NAME, render_static_html(manifest))
        if push:
            storage.push_recent(str(root), manifest["name"], manifest["type"], action)
        # 指纹按「写出去的那份」算（素材 size 在这里被重算过），读回来重算才一致。
        return {"path": str(root), "manifest": manifest, "rev": content_rev(manifest), "merged": merged}


def save_as_project(project_path: str, new_dir: str, manifest: dict) -> dict:
    src = Path(project_path) if project_path else None
    dst = Path(new_dir)
    if dst.exists() and any(dst.iterdir()):
        raise ValueError(f"目标文件夹非空：{dst}")
    ensure_dir(dst)
    if src and (src / ASSETS_DIR_NAME).exists():
        shutil.copytree(src / ASSETS_DIR_NAME, dst / ASSETS_DIR_NAME, dirs_exist_ok=True)
    manifest["name"] = dst.name
    return write_project(str(dst), manifest, push=True, action="另存")


# ---------------------------------------------------------------- 静态画布

_ESC = lambda v: html.escape(str(v if v is not None else ""), quote=True)


def _bg_css(bg: dict | None, root_prefix: str = "") -> str:
    bg = bg or {}
    kind = bg.get("type", "solid")
    if kind == "image" and bg.get("image"):
        src = root_prefix + bg["image"] if not bg["image"].startswith("http") else bg["image"]
        fit = bg.get("fit", "cover")
        if fit == "repeat":
            return f"background-image:url('{_ESC(src)}');background-repeat:repeat;"
        if fit == "contain":
            return f"background-image:url('{_ESC(src)}');background-size:contain;background-repeat:no-repeat;background-position:center;"
        if fit == "fill":
            return f"background-image:url('{_ESC(src)}');background-size:100% 100%;"
        return f"background-image:url('{_ESC(src)}');background-size:cover;background-position:center;"
    if kind == "none":
        return "background:transparent;"
    return f"background:{_ESC(bg.get('color', '#ffffff'))};"


def _style_css(style: dict | None) -> str:
    s = style or {}
    out = []
    if s.get("fontFamily"):
        out.append(f"font-family:{_ESC(s['fontFamily'])};")
    if s.get("fontSize"):
        out.append(f"font-size:{_ESC(s['fontSize'])}px;")
    if s.get("fontWeight"):
        out.append(f"font-weight:{_ESC(s['fontWeight'])};")
    if s.get("fontStyle"):
        out.append(f"font-style:{_ESC(s['fontStyle'])};")
    if s.get("color"):
        out.append(f"color:{_ESC(s['color'])};")
    if s.get("lineHeight"):
        out.append(f"line-height:{_ESC(s['lineHeight'])};")
    if s.get("letterSpacing"):
        out.append(f"letter-spacing:{_ESC(s['letterSpacing'])}px;")
    if s.get("textAlign"):
        out.append(f"text-align:{_ESC(s['textAlign'])};")
    elif s.get("align"):
        out.append(f"text-align:{_ESC(s['align'])};")
    if s.get("paragraphSpacing"):
        out.append(f"margin-block:{_ESC(s['paragraphSpacing'])}px;")
    if s.get("verticalAlign"):
        align = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}.get(
            s["verticalAlign"], "flex-start"
        )
        out.append(f"display:flex;flex-direction:column;justify-content:{align};")
    if s.get("padding") is not None:
        out.append(f"padding:{_ESC(s['padding'])}px;")
    if s.get("background"):
        out.append(f"background:{_ESC(s['background'])};")
    if s.get("borderRadius") is not None:
        out.append(f"border-radius:{_ESC(s['borderRadius'])}px;")
    if s.get("borderWidth"):
        out.append(
            f"border:{_ESC(s['borderWidth'])}px {_ESC(s.get('borderStyle', 'solid'))} {_ESC(s.get('borderColor', '#333333'))};"
        )
    if isinstance(s.get("shadow"), dict):
        out.append(f"box-shadow:{_ESC(shadow_to_css(s['shadow']))};")
    elif s.get("boxShadow"):
        # legacy：解析不了的多层 / inset 阴影原样输出
        out.append(f"box-shadow:{_ESC(s['boxShadow'])};")
    if s.get("overflow"):
        out.append(f"overflow:{_ESC(s['overflow'])};")
    return "".join(out)


CHART_PALETTE = ["#2f6fed", "#f2a33c", "#34b98a", "#e46a76", "#8a7cf0", "#3fb6d3", "#b57ce0", "#f0755f"]


def _num(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{float(value):g}"



def _image_extra_css(props: dict) -> str:
    """图片滤镜与翻转（与前端 canvas.js 的 imageInner 保持一致）。"""
    f = props.get("filter") or {}
    filters = []
    for key, unit in (("brightness", ""), ("contrast", ""), ("saturate", "")):
        val = _num(f.get(key), 1)
        if val != 1:
            filters.append(f"{key}({_fmt_num(val)}{unit})")
    gray = _num(f.get("grayscale"), 0)
    if gray:
        filters.append(f"grayscale({_fmt_num(gray)})")
    blur = _num(f.get("blur"), 0)
    if blur:
        filters.append(f"blur({_fmt_num(blur)}px)")
    flips = []
    if props.get("flipH"):
        flips.append("scaleX(-1)")
    if props.get("flipV"):
        flips.append("scaleY(-1)")
    extra = f"filter:{' '.join(filters)};" if filters else ""
    extra += f"transform:{' '.join(flips)};" if flips else ""
    return extra


# ---------------------------------------------------------------- 共享渲染器接入
# 表格 / 代码块 / 统计图 / 含公式的文本这类「效果多、靠 CSS+SVG 画」的元素，不在 Python 里
# 重写一遍渲染逻辑（那样必然和编辑器漂移），而是把 props 交给 web/js/render-kit.js：
# 导出页加载时就地渲染，编辑器、静态 HTML、PDF、PPTX 图层四路共用同一份实现。
# PPTX / SVG 里这些元素要重摆成原生图表、原生表格、逐行文本图元，靠的就是浏览器实测几何：
# 见下方 _PROBE_JS 与 export.py 的 _attach_measure。
_MATH_RE = re.compile(r"\$[^$\n]+\$|\\\(|\\\[|\\begin\{")
_WEB_JS_CACHE: dict = {}


def _web_js(name: str) -> str:
    """读 web/js/ 下的脚本源码（带缓存；取不到返回空串）。"""
    if name not in _WEB_JS_CACHE:
        try:
            _WEB_JS_CACHE[name] = (WEB_DIR / "js" / name).read_text(encoding="utf-8")
        except OSError:
            _WEB_JS_CACHE[name] = ""
    return _WEB_JS_CACHE[name]


def has_math(text) -> bool:
    """文本里是否含 LaTeX 公式（$…$ / \\(…\\) / \\[…\\] / \\begin{…}）。"""
    return bool(_MATH_RE.search(str(text or "")))


#: window.AC_TOKENS 后面是严格 JSON 字面量（见 web/js/tokens.js 顶部约束），
#: 这里用同一个正则把它抠出来 json.loads，于是「样式 / 几何常数」只有一份。
_TOKENS_RE = re.compile(r"window\.AC_TOKENS\s*=\s*(\{.*\})\s*;", re.S)
_TOKENS_CACHE: dict | None = None


def tokens() -> dict:
    """读 web/js/tokens.js 里的 token 表（唯一事实来源）；取不到返回空字典。"""
    global _TOKENS_CACHE
    if _TOKENS_CACHE is None:
        match = _TOKENS_RE.search(_web_js("tokens.js"))
        try:
            _TOKENS_CACHE = json.loads(match.group(1)) if match else {}
        except ValueError:
            _TOKENS_CACHE = {}
    return _TOKENS_CACHE


#: KaTeX 里 20 个 @font-face 的三格式 src（woff2/woff/ttf）：内联时只留 woff2 的 data URI。
_KATEX_FONT_RE = re.compile(
    r'url\(fonts/([\w-]+)\.woff2\) format\("woff2"\),'
    r'url\(fonts/\1\.woff\) format\("woff"\),'
    r'url\(fonts/\1\.ttf\) format\("truetype"\)'
)
_KATEX_CACHE: tuple | None = None


def _inline_katex_fonts(css: str, fonts_dir: Path) -> str:
    """把 CSS 里的字体引用换成对应 woff2 的 base64 data URI（Chromium 只吃 woff2，其余格式丢掉）。"""
    def repl(m: re.Match) -> str:
        try:
            data = base64.b64encode((fonts_dir / f"{m.group(1)}.woff2").read_bytes()).decode("ascii")
        except OSError:
            return m.group(0)
        return f'url(data:font/woff2;base64,{data}) format("woff2")'

    return _KATEX_FONT_RE.sub(repl, css)


def _katex_assets() -> tuple:
    """KaTeX 的 CSS / JS 源码（字体以 base64 内联进 CSS），供导出页离线自包含。

    导出页写到工程目录（静态 HTML / PDF / PPTX），够不到程序安装目录里的 web/vendor/katex，
    所以这里整份读出来内联。取不到就返回空串，公式自动退回 render-kit 的手写实现。
    """
    global _KATEX_CACHE
    if _KATEX_CACHE is None:
        kdir = WEB_DIR / "vendor" / "katex"
        try:
            css = (kdir / "katex.min.css").read_text(encoding="utf-8")
            js = (kdir / "katex.min.js").read_text(encoding="utf-8")
        except OSError:
            css = js = ""
        if css:
            css = _inline_katex_fonts(css, kdir / "fonts")
        _KATEX_CACHE = (css, js)
    return _KATEX_CACHE


def _render_kit_script() -> str:
    """共享渲染器源码内联片段（空串表示取不到源文件，页面就只剩服务端兜底内容）。

    tokens.js 是样式 token 的唯一来源，渲染器读 window.AC_TOKENS，所以必须排在它前面。
    KaTeX（CSS + JS）要排在 render-kit.js 之前：render-kit 的 tex() 检测到 window.katex 就用它。
    """
    src = _web_js("render-kit.js")
    if not src:
        return ""
    toks = _web_js("tokens.js")
    kcss, kjs = _katex_assets()
    katex = f"<style>{kcss}</style><script>{kjs}{_SCRIPT_CLOSE}" if kjs else ""
    head = f"<script>{toks}{_SCRIPT_CLOSE}" if toks else ""
    return f"{katex}{head}<script>{src}{_SCRIPT_CLOSE}"


_RENDER_KIT_SIG: str | None = None


def render_kit_signature() -> str:
    """渲染器指纹：tokens.js + render-kit.js 源码的哈希。

    measured 缓存（见 app/export.py）拿它当版本号 —— 渲染逻辑或 token 一改，指纹就变，
    旧测量结果自动失效，不会拿过期几何去排版。
    """
    global _RENDER_KIT_SIG
    if _RENDER_KIT_SIG is None:
        blob = _web_js("tokens.js") + "\n" + _web_js("render-kit.js") + "\n" + _katex_assets()[1]
        _RENDER_KIT_SIG = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    return _RENDER_KIT_SIG


def _ac_host(etype: str, props: dict, style: str) -> str:
    """元素外壳 + props 载荷：值放在属性里由渲染器读取，避免脚本标签被内容提前闭合。"""
    payload = html.escape(json.dumps(props, ensure_ascii=False), quote=True)
    return f'<div class="el el-{etype}" style="{style}" data-ac-props="{payload}"></div>'


_RUN_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _clean_runs(runs, length: int) -> list:
    """把 props.runs 规范成 [{s, e, st}]（与前端 render-kit 的 cleanRuns 同一套规则）。

    s / e 是 props.text 的字符下标；越界、空样式、非法颜色一律丢掉。解析不出一律返回 []。
    这是行内富文本的唯一兜底入口 —— 静态导出、PDF、SVG、PPTX 与 COM 都从这里取样式。
    """
    if isinstance(runs, str):
        try:
            runs = json.loads(runs)
        except ValueError:
            runs = None
    if not isinstance(runs, list):
        return []
    out = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        try:
            a = max(0, min(length, int(r.get("s", 0))))
            b = max(0, min(length, int(r.get("e", 0))))
        except (TypeError, ValueError):
            continue
        if b <= a:
            continue
        st = {}
        if r.get("b"):
            st["b"] = 1
        if r.get("i"):
            st["i"] = 1
        if r.get("u"):
            st["u"] = 1
        c = str(r.get("c") or "")
        if _RUN_COLOR_RE.match(c):
            st["c"] = c
        g = str(r.get("bg") or "")
        if _RUN_COLOR_RE.match(g):
            st["bg"] = g
        if st:
            out.append({"s": a, "e": b, "st": st})
    return out


def _run_style_at(lst: list, i: int) -> dict | None:
    """第 i 个字符上叠出来的行内样式；多个区间重叠时后面的覆盖前面的颜色。"""
    st = None
    for r in lst:
        if r["s"] <= i < r["e"]:
            if st is None:
                st = {}
            s = r["st"]
            if s.get("b"):
                st["b"] = 1
            if s.get("i"):
                st["i"] = 1
            if s.get("u"):
                st["u"] = 1
            if s.get("c"):
                st["c"] = s["c"]
            if s.get("bg"):
                st["bg"] = s["bg"]
    return st


def _run_key(st) -> str:
    """样式的指纹：相邻字符指纹相同就并进同一个 <span>。"""
    if not st:
        return ""
    return (("b" if st.get("b") else "") + ("i" if st.get("i") else "")
            + ("u" if st.get("u") else "")
            + (f"c{st['c']}" if st.get("c") else "")
            + (f"g{st['bg']}" if st.get("bg") else ""))


def _run_css(st) -> str:
    css = ""
    if st.get("b"):
        css += "font-weight:700;"
    if st.get("i"):
        css += "font-style:italic;"
    if st.get("u"):
        css += "text-decoration:underline;"
    if st.get("c"):
        css += f"color:{st['c']};"
    if st.get("bg"):
        css += f"background-color:{st['bg']};"
    return css


def _line_offsets(text: str, lines: list) -> list:
    """每行首字符在原文（含 \\n）里的下标：断行结果是去掉 \\n 的，这里把偏移补回去。"""
    offs = []
    pos = 0
    for ln in lines:
        while pos < len(text) and text[pos] == "\n":
            pos += 1
        offs.append(pos)
        pos += len(ln)
    return offs


def _line_segments(line: str, base: int, runs: list) -> list:
    """一行文本按 runs 切成 [(片段, 样式字典)]；没有 runs 时就是整行一段、空样式。"""
    n = len(line)
    if not runs or not n:
        return [(line, {})]
    segs = []
    i = 0
    while i < n:
        st = _run_style_at(runs, base + i)
        j = i + 1
        while j < n and _run_style_at(runs, base + j) == st:
            j += 1
        segs.append((line[i:j], st or {}))
        i = j
    return segs


def _runs_html(text, runs, br: bool = True) -> str:
    """行内富文本 → HTML：逐段套 <span style=...>，样式相同的字并成一段。

    与前端 render-kit.js 的 runsHtml 同一套规则，画布 / 静态导出 / PDF 观感一致。
    br 为真时把 \\n 换成 <br/>，为假时原样保留（量断行用，字符下标才与原文对齐）。
    """
    s = str(text if text is not None else "")
    lst = _clean_runs(runs, len(s))
    if not lst:
        esc = _ESC(s)
        return esc.replace("\n", "<br/>") if br else esc
    out = []
    i, n = 0, len(s)
    while i < n:
        st = _run_style_at(lst, i)
        key = _run_key(st)
        j = i + 1
        while j < n and _run_key(_run_style_at(lst, j)) == key:
            j += 1
        chunk = _ESC(s[i:j])
        if br:
            chunk = chunk.replace("\n", "<br/>")
        out.append(f'<span style="{_run_css(st)}">{chunk}</span>' if st else chunk)
        i = j
    return "".join(out)


def _el_text(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """文本元素：普通文本直接服务端转义输出；含 LaTeX 公式时交给共享渲染器就地渲染。"""
    text = props.get("text", "")
    if props.get("math", True) is not False and has_math(text):
        return _ac_host("text", props, style)
    inner = _runs_html(text, props.get("runs"), True)
    return f'<div class="el el-text" style="{style}">{inner}</div>'


def _img_rgba(color, alpha) -> str:
    """颜色 + 透明度 → rgba()（认不出颜色退回纯黑），与前端 canvas.js 的 hexRgba 对齐。"""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(color or "").strip())
    if not m:
        return f"rgba(0,0,0,{alpha})"
    n = int(m.group(1), 16)
    return f"rgba({(n >> 16) & 255},{(n >> 8) & 255},{n & 255},{alpha})"


def _clamp01(v) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, n))


def _crop_frac(v) -> float:
    """裁剪百分比（0–90）→ 0–0.9 的比例。"""
    try:
        n = float(v) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return min(0.9, max(0.0, n))


def _el_image(el: dict, props: dict, style: str, root_prefix: str) -> str:
    src = props.get("src", "")
    if not src:
        return (
            f'<div class="el" style="{style}"><div style="width:100%;height:100%;background:#eef1f5;'
            'display:flex;align-items:center;justify-content:center;color:#9aa3ad;font-size:12px;">未设置图片</div></div>'
        )
    fit = props.get("fit", "cover")
    img_extra = _image_extra_css(props)          # 颜色滤镜 + 翻转，作用在 img 上
    radius = _num((el.get("style") or {}).get("borderRadius"), 0)
    radius_css = f"border-radius:{_fmt_num(radius)}px;" if radius else ""
    img_src = _ESC(root_prefix + src)
    img_style = f"width:100%;height:100%;object-fit:{_ESC(fit)};display:block;{radius_css}{img_extra}"
    block = f'<img src="{img_src}" style="{img_style}"/>'

    # 裁剪：外框裁掉溢出，img 放大并偏移，只露出要保留的那块（四边按百分比）
    ct, cb = _crop_frac(props.get("cropTop")), _crop_frac(props.get("cropBottom"))
    cl, cr = _crop_frac(props.get("cropLeft")), _crop_frac(props.get("cropRight"))
    if ct or cb or cl or cr:
        vw, vh = max(0.1, 1 - cl - cr), max(0.1, 1 - ct - cb)

        def _pct(v: float) -> str:
            return f"{round(v * 100, 2)}%"

        block = (
            f'<div style="position:relative;width:100%;height:100%;overflow:hidden;{radius_css}">'
            f'<img src="{img_src}" style="position:absolute;width:{_pct(1 / vw)};height:{_pct(1 / vh)};'
            f'left:{_pct(-cl / vw)};top:{_pct(-ct / vh)};object-fit:{_ESC(fit)};display:block;{img_extra}"/></div>'
        )

    # 阴影（drop-shadow）挂在整块图上，图片边界即阴影轮廓
    wrap_filter = ""
    if props.get("shadowOn"):
        wrap_filter = (
            f"filter:drop-shadow({_fmt_num(_num(props.get('shadowX'), 0))}px "
            f"{_fmt_num(_num(props.get('shadowY'), 0))}px "
            f"{_fmt_num(max(0.0, _num(props.get('shadowBlur'), 0)))}px "
            f"{_img_rgba(props.get('shadowColor', '#000000'), _clamp01(props.get('shadowOpacity', 0.35)))});"
        )
    out = f'<div style="position:relative;width:100%;height:100%;overflow:visible;{wrap_filter}">{block}'

    # 倒影：镜像一份贴在下方，用渐变遮罩淡出
    if props.get("reflectOn"):
        h = _num(el.get("h"), 0)
        if h:
            rs = max(0.0, min(1.0, _num(props.get("reflectSize"), 50) / 100.0))
            ref_h = max(1.0, h * rs)
            gap = _num(props.get("reflectGap"), 0)
            ref_o = _clamp01(props.get("reflectOpacity", 0.35))
            mask = "linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,0) 100%)"
            out += (
                f'<div style="position:absolute;left:0;top:100%;width:100%;height:{_fmt_num(ref_h)}px;'
                f'margin-top:{_fmt_num(gap)}px;overflow:hidden;pointer-events:none;opacity:{ref_o};'
                f'-webkit-mask-image:{mask};mask-image:{mask}">'
                f'<div style="width:100%;height:{_fmt_num(h)}px;transform:scaleY(-1)">{block}</div></div>'
            )
    return f'<div class="el" style="{style}">{out}</div>'


def _media_play_attrs(props: dict) -> str:
    """播放参数（音量 / 剪辑起止 / 播完返回开头 / 未播放时隐藏）落到 data-ac-* 上。

    画布与放映用 canvas.js 的 applyVideoPlayback 读同一套属性，静态导出由下面的
    _VIDEO_RUNTIME 脚本读，语义一份，三处行为不会各说各话。
    """
    volume = min(1.0, max(0.0, _num(props.get("volume"), 1)))
    start = max(0.0, _num(props.get("startTime")))
    end = max(0.0, _num(props.get("endTime")))
    rewind = "0" if props.get("rewind") is False else "1"
    attrs = (f' data-ac-video="1" data-ac-volume="{_fmt_num(volume)}"'
             f' data-ac-start="{_fmt_num(start)}" data-ac-end="{_fmt_num(end)}"'
             f' data-ac-rewind="{rewind}"')
    if props.get("hideWhenNotPlaying"):
        attrs += ' data-ac-hide-idle="1"'
    return attrs


def _el_video(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """视频：静态 HTML / PDF 里就是一段原生 <video>。

    poster 必须留下：PDF 是打印出来的那一帧，没有封面帧这一屏就是空白。
    封面帧可以是工程内图片路径，也可以是前端抓帧后存进去的 dataURL。
    """
    src = str(props.get("src") or "")
    poster = str(props.get("poster") or "")
    poster_attr = ""
    if poster:
        poster_url = poster if poster.startswith("data:") else root_prefix + poster
        poster_attr = f' poster="{_ESC(poster_url)}"'
    return (
        f'<div class="el" style="{style}">'
        f'<video src="{_ESC(root_prefix + src)}"{poster_attr}'
        f'{" controls" if props.get("controls", True) is not False else ""}'
        f'{" autoplay" if props.get("autoplay") else ""}'
        f'{" loop" if props.get("loop") else ""}'
        f'{" muted" if props.get("muted", True) is not False else ""} playsinline'
        f'{_media_play_attrs(props)} '
        f'style="width:100%;height:100%;object-fit:{_ESC(props.get("fit") or "fill")};background:#000;"></video></div>'
    )


def _el_link(el: dict, props: dict, style: str, root_prefix: str) -> str:
    inner = _runs_html(props.get("text", ""), props.get("runs"), True)
    return (
        f'<div class="el el-text" style="{style}">'
        f'<a href="{_ESC(props.get("href", "#"))}" target="_blank">{inner}</a></div>'
    )


def _el_table(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """表格：列宽 / 逐列对齐 / 合并单元格 / 单元格高亮等新属性只在共享渲染器里实现。"""
    return _ac_host("table", props, style)


def _el_code(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """代码块：语法高亮 + 标题栏 + 行号 + 高亮行，统一由共享渲染器画。"""
    return _ac_host("code", props, style)


def _el_chart(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """统计图：横向柱 / 堆叠 / 分组 / 雷达 / 散点 / 漏斗 / 仪表盘等都由共享渲染器画。"""
    return _ac_host("chart", props, style)


def _el_shape(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """形状：几何 / 填充 / 描边 / 阴影 / 倒影全部交给共享渲染器（SVG 矢量）绘制。

    引擎自带方框背景 / 边框 / 圆角会盖住 SVG，这里显式清掉再交给渲染器。
    """
    payload = dict(props)
    payload["$style"] = el.get("style") or {}
    payload["$w"] = el.get("w")
    payload["$h"] = el.get("h")
    payload["$assetBase"] = root_prefix
    return _ac_host("shape", payload, f"{style}background:transparent;border:0;border-radius:0;")


def _el_path(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """可编辑路径（任意矢量轮廓）：几何来自 props.d，填充 / 描边 / 阴影 / 倒影交给共享渲染器。

    与形状一样，引擎自带的方框背景 / 边框 / 圆角会盖住 SVG，这里显式清掉。
    """
    payload = dict(props)
    payload["$style"] = el.get("style") or {}
    payload["$w"] = el.get("w")
    payload["$h"] = el.get("h")
    payload["$assetBase"] = root_prefix
    return _ac_host("path", payload, f"{style}background:transparent;border:0;border-radius:0;")


def _el_connector(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """元素间连线：几何（主路径 + 两个箭头三角）在编辑期就由前端算好写进 props，
    这里照常交给共享渲染器画，静态导出因此不需要知道端点绑在哪两个元素上。"""
    payload = dict(props)
    payload["$style"] = el.get("style") or {}
    payload["$w"] = el.get("w")
    payload["$h"] = el.get("h")
    return _ac_host("connector", payload, f"{style}background:transparent;border:0;border-radius:0;")


_SCRIPT_CLOSE = "<" + "/script>"


# 静态 HTML 里的视频：把 data-ac-* 上的播放参数落地（音量 / 剪辑起止 / 播完返回开头 / 未播放时隐藏）。
# 与 web/js/canvas.js 的 applyVideoPlayback 保持同一套语义，导出的文件离线打开行为才一致。
_VIDEO_RUNTIME = """
(function () {
  function num(el, key, d) { var v = parseFloat(el.getAttribute(key)); return isNaN(v) ? d : v; }
  var list = document.querySelectorAll('video[data-ac-video]');
  for (var i = 0; i < list.length; i++) (function (v) {
    try { v.volume = Math.max(0, Math.min(1, num(v, 'data-ac-volume', 1))); } catch (e) { }
    var start = Math.max(0, num(v, 'data-ac-start', 0));
    var end = Math.max(0, num(v, 'data-ac-end', 0));
    var rewind = v.getAttribute('data-ac-rewind') !== '0';
    var hideIdle = v.getAttribute('data-ac-hide-idle') === '1';
    function seekStart() { try { v.currentTime = start; } catch (e) { } }
    if (start > 0) {
      if (v.readyState >= 1) seekStart(); else v.addEventListener('loadedmetadata', seekStart);
      v.addEventListener('play', function () { if (v.currentTime < start - 0.05) seekStart(); });
    }
    if (start > 0 || end > 0) {
      v.addEventListener('timeupdate', function () {
        if (!end || v.currentTime < end) return;
        if (v.loop) { seekStart(); return; }
        v.pause();
        if (rewind) seekStart();
      });
    }
    if (hideIdle) {
      v.style.visibility = 'hidden';
      v.addEventListener('play', function () { v.style.visibility = ''; });
      v.addEventListener('pause', function () { v.style.visibility = 'hidden'; });
    }
    v.addEventListener('ended', function () {
      if (rewind) seekStart();
      if (hideIdle) v.style.visibility = 'hidden';
    });
  })(list[i]);
})();
"""


def _scene_document(code: str, duration, loop: bool, params, libs=None, seek_at=None) -> str:
    """把场景代码包成一份独立文档（透明底、铺满），与前端 scene-runtime.js 的 sceneDocument 对应。

    脚本顺序与前端一致：引导 → 本地库 → 用户代码。
    libs 传 {库id: 源码}，导出时读的是磁盘上那份缓存（与编辑态内联的是同一份）。

    seek_at 不为 None 时进入「定格」模式：挂载后只把画面定在该时刻反复 seek 几帧，
    不起播放循环 —— 无头浏览器抓帧（core/scene_capture.py）靠它采出确定的时间点。
    """
    def esc(text: str) -> str:
        return re.sub(r"</script", r"<\\/script", str(text or ""), flags=re.I)

    safe = esc(code)
    if seek_at is None:
        boot = (
            "(function(){var W=window,D=document;"
            f"var DUR={_fmt_num(_num(duration, 3))},LOOP={'true' if loop else 'false'},"
            f"PARAMS={json.dumps(params if isinstance(params, dict) else {}, ensure_ascii=False)};"
            "function play(){var start=0;function step(ts){if(!start)start=ts;var t=(ts-start)/1000;"
            "if(t>DUR){if(!LOOP){try{W.seek(DUR)}catch(e){}return;}start=ts;t=0;}"
            "try{W.seek(t)}catch(e){}requestAnimationFrame(step);}requestAnimationFrame(step);}"
            "function boot(){W.__scene={duration:DUR,loop:LOOP};"
            "if(typeof W.mount==='function'){try{W.mount(D.getElementById('scn-root'),PARAMS)}catch(e){}}"
            "if(typeof W.seek==='function')play();}"
            "if(D.readyState==='complete')setTimeout(boot,0);"
            "else W.addEventListener('load',function(){setTimeout(boot,0)});})();"
        )
    else:
        boot = (
            "(function(){var W=window,D=document;"
            f"var DUR={_fmt_num(_num(duration, 3))},PARAMS={json.dumps(params if isinstance(params, dict) else {}, ensure_ascii=False)},"
            f"AT={_fmt_num(_num(seek_at, 0))};"
            "function boot(){W.__scene={duration:DUR,loop:false};"
            "if(typeof W.mount==='function'){try{W.mount(D.getElementById('scn-root'),PARAMS)}catch(e){}}"
            "var n=0;function tick(){try{W.seek(AT)}catch(e){}n++;"
            "if(n<8)requestAnimationFrame(tick);else W.__frameReady=true;}tick();}"
            "if(D.readyState==='complete')setTimeout(boot,0);"
            "else W.addEventListener('load',function(){setTimeout(boot,0)});})();"
        )
    lib_html = "".join(
        f'<script>/* 本地库：{lib_id} */\n{esc(source)}{_SCRIPT_CLOSE}'
        for lib_id, source in (libs or {}).items()
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"/>'
        '<style>html,body{margin:0;padding:0;width:100%;height:100%;background:transparent;'
        'overflow:hidden;}*{box-sizing:border-box;}#scn-root{width:100%;height:100%;}</style></head>'
        f'<body><div id="scn-root"></div><script>{boot}{_SCRIPT_CLOSE}'
        f'{lib_html}'
        f'<script>{safe}{_SCRIPT_CLOSE}</body></html>'
    )


def _el_scene(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """微场景：导出 HTML 里内联真身（iframe + 用户代码），封面帧只作为底色与打印回退。"""
    poster = str(props.get("poster") or "")
    poster_css = ""
    if poster:
        src = poster if poster.startswith("data:") else root_prefix + poster
        poster_css = (
            f"background-image:url('{_ESC(src)}');background-position:center;"
            "background-repeat:no-repeat;background-size:contain;"
        )
    code = str(props.get("code") or "")
    if not code.strip():
        hint = "微场景（未填写代码）" if not poster else ""
        inner = (
            f'<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;'
            f'color:#9aa3ad;font-size:12px;">{hint}</div>' if hint else ""
        )
        return f'<div class="el el-scene" style="{style}{poster_css}">{inner}</div>'
    # 库源码读的是本机那份缓存（data/scene_libs）：导出文件与编辑态用的是同一份，导出后无需联网
    raw_libs = props.get("libs")
    known = {item["id"] for item in scene_libs.list_libs()}
    lib_ids = [str(x) for x in raw_libs if x in known] if isinstance(raw_libs, list) else []
    sources = scene_libs.sources_for(lib_ids)
    doc = _scene_document(
        code, props.get("duration"), props.get("loop", True) is not False, props.get("params"), sources["sources"]
    )
    title = _ESC(el.get("name") or "微场景")
    # 有库没下载就摆在画面角上：导出文件打开时一眼能看到，而不是只看到一个跑不起来的空框
    note = ""
    if sources["missing"]:
        note = (
            '<div class="el-scene-note" style="position:absolute;left:6px;bottom:6px;padding:2px 8px;'
            'border-radius:10px;background:rgba(190,60,60,.88);color:#fff;font-size:11px;line-height:18px;">'
            f'缺少本地库：{_ESC("、".join(sources["missing"]))}（到「设置 → 场景库」下载后重新导出）</div>'
        )
    return (
        f'<div class="el el-scene" style="{style}{poster_css}">'
        f'<iframe class="el-scene-frame" sandbox="allow-scripts" scrolling="no" title="{title}" '
        f'srcdoc="{_ESC(doc)}" style="position:absolute;inset:0;width:100%;height:100%;border:0;'
        f'background:transparent;"></iframe>{note}</div>'
    )


def _el_fallback(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """未登记类型的兜底：按纯文本输出（没有专属内容的类型走这里）。"""
    return f'<div class="el" style="{style}">{_ESC(props.get("text", ""))}</div>'


def _el_group(el: dict, props: dict, style: str, root_prefix: str) -> str:
    """容器：本身不产出任何 DOM（它只是一条父子关系），成员按各自的类型平铺在画布上。"""
    return ""


# ------------------------------------------------------------------ 元素 → 静态 HTML 注册表
# 按 type 分发（取代原先的 if 链）。新增一种元素：写好上面的渲染函数，再在这里登记一条。
_ELEMENT_HTML = {
    "text": _el_text,
    "image": _el_image,
    "video": _el_video,
    "link": _el_link,
    "table": _el_table,
    "code": _el_code,
    "chart": _el_chart,
    "shape": _el_shape,
    "path": _el_path,
    "connector": _el_connector,
    "group": _el_group,
    "scene": _el_scene,
}


def register_element_html(etype: str, fn) -> None:
    """注册（或覆盖）一种元素的静态 HTML 渲染函数，供扩展新元素使用。"""
    if etype and fn:
        _ELEMENT_HTML[etype] = fn


def element_html(el: dict, root_prefix: str = "", offset: tuple = (0, 0)) -> str:
    """单元素 HTML 片段。

    offset=(dx, dy) 把元素从画布坐标平移到别处（截图画布逐行排布时用），
    其余定位/样式与画布上完全一致。
    """
    etype = el.get("type", "text")
    props = el.get("props") or {}
    dx, dy = offset or (0, 0)
    base = (
        f"position:absolute;left:{_num(el.get('x'), 0) + _num(dx, 0)}px;"
        f"top:{_num(el.get('y'), 0) + _num(dy, 0)}px;"
        f"width:{el.get('w', 0)}px;height:{el.get('h', 0)}px;"
        f"z-index:{el.get('z', 1)};opacity:{el.get('opacity', 1)};"
    )
    if el.get("rotate"):
        base += f"transform:rotate({el['rotate']}deg);"
    if not el.get("visible", True):
        base += "display:none;"
    style = base + _style_css(el.get("style"))
    if not style.rstrip().endswith(";"):
        style += ";"

    return _ELEMENT_HTML.get(etype, _el_fallback)(el, props, style, root_prefix)


def _with_el_id(html_str: str, el: dict) -> str:
    """给元素根节点补上 data-id / data-type，供导出 HTML 的放映脚本定位。

    带行内富文本（props.runs）的文本额外打一个 data-ac-rich，探针据此决定按「图元清单」
    逐段量回去（每一段加粗 / 变色 / 高亮各自独立），否则走整段文本的老路。
    """
    rich = bool((el.get("props") or {}).get("runs"))
    marker = ' data-ac-rich="1"' if rich else ""
    return html_str.replace(
        '<div class="el',
        f'<div data-id="{_ESC(el.get("id", ""))}" data-type="{_ESC(el.get("type", ""))}"'
        f'{marker} class="el',
        1,
    )


def _anim_data(manifest: dict) -> dict:
    """导出 HTML 的动画数据：elementId -> 时间轴（与前端 anim.js 的字段一一对应）。"""
    out = {}
    for page in manifest.get("pages", []):
        for el in page.get("elements", []):
            anim = el.get("anim")
            if not anim or anim.get("enabled") is False:
                continue
            kfs = anim.get("keyframes") or []
            if not kfs:
                continue
            opacity = el.get("opacity")
            out[str(el.get("id", ""))] = {
                "delay": _num(anim.get("delay"), 0),
                "duration": max(60.0, _num(anim.get("duration"), 700)),
                "easing": anim.get("easing") or "ease-out",
                "trigger": anim.get("trigger") or "page",
                "rotate": _num(el.get("rotate"), 0),
                "opacity": 1 if opacity is None else _num(opacity, 1),
                "kf": [
                    {
                        "t": min(1.0, max(0.0, _num(k.get("t"), 0))),
                        "o": None if k.get("opacity") in (None, "") else _num(k.get("opacity"), 1),
                        "dx": _num(k.get("dx"), 0),
                        "dy": _num(k.get("dy"), 0),
                        "s": 1 if k.get("scale") is None else _num(k.get("scale"), 1),
                        "r": _num(k.get("rotate"), 0),
                    }
                    for k in kfs
                ],
            }
    return out


# 导出 HTML 里的放映器：与编辑器 anim.js 同一套求值规则（延迟、点击触发、循环、缓动）。
# 用原生 JS 内联，保证导出的文件夹离线双击即可放映，不依赖任何外部文件。
_ANIM_RUNTIME = r"""
(function () {
  var ANIM = window.__ANIM__ || {};
  var CW = (window.__CANVAS__ || {}).w || 1280;
  var CH = (window.__CANVAS__ || {}).h || 720;
  var pages = [].slice.call(document.querySelectorAll('.page'));
  if (!pages.length || !Object.keys(ANIM).length) return;

  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }
  function ease(kind, k) {
    var x = clamp01(k);
    if (kind === 'ease-in') return x * x;
    if (kind === 'ease-out') return 1 - (1 - x) * (1 - x);
    if (kind === 'ease-in-out') return x < 0.5 ? 2 * x * x : 1 - 2 * (1 - x) * (1 - x);
    if (kind === 'ease') return x * x * (3 - 2 * x);
    return x;
  }
  function sample(a, ms) {
    var kfs = a.kf, span = a.duration, t = clamp01(ms / span);
    var i, lo = kfs[0], hi = kfs[kfs.length - 1];
    for (i = 0; i < kfs.length - 1; i++) {
      if (t >= kfs[i].t && t <= kfs[i + 1].t) { lo = kfs[i]; hi = kfs[i + 1]; break; }
    }
    var seg = hi.t - lo.t;
    var k = ease(a.easing, seg > 0 ? (t - lo.t) / seg : 0);
    function pick(key, fb) {
      var av = lo[key], bv = hi[key];
      if (av == null && bv == null) return fb;
      var from = av == null ? fb : av, to = bv == null ? fb : bv;
      return from + (to - from) * k;
    }
    return { o: pick('o', a.opacity), dx: pick('dx', 0), dy: pick('dy', 0), s: pick('s', 1), r: pick('r', 0) };
  }
  function apply(it, st) {
    var parts = [];
    if (st.dx || st.dy) parts.push('translate(' + st.dx + 'px,' + st.dy + 'px)');
    var rot = (it.a.rotate || 0) + st.r;
    if (rot) parts.push('rotate(' + rot + 'deg)');
    if (st.s !== 1) parts.push('scale(' + st.s + ')');
    it.node.style.transform = parts.join(' ');
    it.node.style.opacity = String(st.o);
  }
  function stateAt(it, elapsed) {
    var a = it.a;
    if (it.at === null) return sample(a, 0);
    var local = elapsed - it.at;
    if (local <= 0) return sample(a, 0);
    if (local < a.delay) return sample(a, 0);
    var after = local - a.delay;
    return sample(a, a.trigger === 'loop' ? after % a.duration : after);
  }
  function finished(it, elapsed) {
    if (it.a.trigger === 'loop' || it.at === null) return false;
    return elapsed - it.at >= it.a.delay + it.a.duration;
  }

  var overlay = document.createElement('div');
  overlay.className = 'anim-overlay';
  overlay.innerHTML =
    '<div class="anim-bar"><b class="anim-title"></b><span class="anim-counter"></span><span style="flex:1"></span>' +
    '<button data-a="replay">重播</button><button data-a="pause">暂停</button>' +
    '<button data-a="prev">上一页</button><button data-a="next">下一页</button><button data-a="exit">退出</button></div>' +
    '<div class="anim-stage-wrap"><div class="anim-stage"></div></div>' +
    '<div class="anim-progress"><i></i></div><div class="anim-hint"></div>';
  document.body.appendChild(overlay);

  var stage = overlay.querySelector('.anim-stage');
  var wrap = overlay.querySelector('.anim-stage-wrap');
  var titleEl = overlay.querySelector('.anim-title');
  var counterEl = overlay.querySelector('.anim-counter');
  var hintEl = overlay.querySelector('.anim-hint');
  var fillEl = overlay.querySelector('.anim-progress i');
  var pauseBtn = overlay.querySelector('[data-a="pause"]');

  var current = 0, elapsed = 0, last = 0, raf = 0, playing = true, items = [], clicks = [], total = 0;

  function fitScale() {
    return Math.min((window.innerWidth - 80) / CW, (window.innerHeight - 150) / CH);
  }
  function mount(index) {
    current = Math.max(0, Math.min(pages.length - 1, index));
    stage.innerHTML = '';
    var clone = pages[current].cloneNode(true);
    clone.style.margin = '0';
    clone.style.boxShadow = '0 18px 60px rgba(0,0,0,.6)';
    clone.style.transformOrigin = 'top left';
    var s = fitScale();
    clone.style.transform = 'scale(' + s + ')';
    stage.style.width = (CW * s) + 'px';
    stage.style.height = (CH * s) + 'px';
    stage.appendChild(clone);

    titleEl.textContent = pages[current].getAttribute('data-name') || ('第 ' + (current + 1) + ' 页');
    counterEl.textContent = (current + 1) + ' / ' + pages.length;
    items = []; clicks = []; total = 0;
    [].forEach.call(clone.querySelectorAll('.el[data-id]'), function (node) {
      var a = ANIM[node.getAttribute('data-id')] || null;
      node.style.transformOrigin = 'center center';
      var it = { node: node, a: a, at: a ? (a.trigger === 'click' ? null : 0) : 0 };
      items.push(it);
      if (a) {
        total = Math.max(total, a.delay + a.duration);
        if (a.trigger === 'click') clicks.push(it);
      }
    });
    clicks.sort(function (x, y) { return x.a.delay - y.a.delay; });
    elapsed = 0; last = 0;
    updateHint(); draw();
    if (playing) raf = requestAnimationFrame(tick);
  }
  function updateHint() {
    var left = clicks.filter(function (it) { return it.at === null; }).length;
    hintEl.textContent = left
      ? ('点击画面播放下一段动画（还剩 ' + left + ' 段）· ← → 翻页 · Esc 退出')
      : '← → 翻页 · R 重播 · 空格暂停 · Esc 退出';
  }
  function draw() {
    items.forEach(function (it) { if (it.a) apply(it, stateAt(it, elapsed)); });
    fillEl.style.width = (total ? Math.min(1, elapsed / total) : 1) * 100 + '%';
  }
  function tick(now) {
    if (!playing) return;
    var dt = last ? Math.min(120, now - last) : 0;
    last = now; elapsed += dt;
    draw();
    var done = items.every(function (it) { return !it.a || finished(it, elapsed); });
    raf = done ? 0 : requestAnimationFrame(tick);
  }
  function play() { if (!raf && playing) { last = 0; raf = requestAnimationFrame(tick); } }
  function togglePause() {
    playing = !playing;
    pauseBtn.textContent = playing ? '暂停' : '继续';
    if (playing) play(); else { cancelAnimationFrame(raf); raf = 0; }
  }
  function goto(index) {
    if (index < 0 || index >= pages.length) { hintEl.textContent = '已到边界 · Esc 退出'; return; }
    cancelAnimationFrame(raf); raf = 0;
    mount(index);
  }
  function exit() {
    cancelAnimationFrame(raf); raf = 0;
    overlay.remove();
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('resize', onResize);
  }
  function onResize() { cancelAnimationFrame(raf); raf = 0; mount(current); }
  function onKey(e) {
    if (e.key === 'Escape') { exit(); }
    else if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); goto(current + 1); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); goto(current - 1); }
    else if (e.key === 'r' || e.key === 'R') { goto(current); }
    else if (e.code === 'Space') { e.preventDefault(); togglePause(); }
  }

  overlay.addEventListener('click', function (e) {
    var a = e.target.getAttribute && e.target.getAttribute('data-a');
    if (a === 'exit') return exit();
    if (a === 'next') return goto(current + 1);
    if (a === 'prev') return goto(current - 1);
    if (a === 'replay') return goto(current);
    if (a === 'pause') return togglePause();
    if (a) return;
    var pending = clicks.filter(function (it) { return it.at === null; });
    if (pending.length) {
      pending[0].at = Math.max(elapsed, 16);
      updateHint();
      if (playing) play();
      return;
    }
    goto(current + 1);
  });
  window.addEventListener('keydown', onKey);
  window.addEventListener('resize', onResize);
  mount(0);
})();
"""

_ANIM_CSS = """
.anim-play-btn { position:fixed; right:18px; bottom:18px; z-index:50; padding:9px 16px; border:none;
  border-radius:20px; background:#2f6fed; color:#fff; font-size:13px; cursor:pointer;
  font-family:inherit; box-shadow:0 6px 20px rgba(47,111,237,.4); }
.anim-play-btn:hover { background:#1f5bd0; }
.anim-overlay { position:fixed; inset:0; z-index:999; background:#0b0f14; display:flex;
  flex-direction:column; align-items:center; }
.anim-bar { width:100%; display:flex; align-items:center; gap:8px; padding:10px 16px; color:#e6edf3;
  font-size:12px; }
.anim-bar button { background:rgba(255,255,255,.1); color:#e6edf3; border:1px solid rgba(255,255,255,.18);
  border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer; font-family:inherit; }
.anim-bar button:hover { background:rgba(255,255,255,.22); }
.anim-counter { color:#93a1b1; }
.anim-stage-wrap { flex:1; display:flex; align-items:center; justify-content:center; width:100%;
  overflow:hidden; cursor:pointer; padding:0 40px; }
.anim-stage { position:relative; }
.anim-progress { width:100%; height:3px; background:rgba(255,255,255,.14); }
.anim-progress i { display:block; height:100%; width:0; background:#2f6fed; transition:width .05s linear; }
.anim-hint { color:#7b8896; font-size:11px; padding:8px 0 12px; }
@media print { .anim-play-btn, .anim-overlay { display:none !important; } }
"""


# 元素级基础样式：静态 HTML 与「截图兜底」画布共用同一份，避免两处漂移。
ELEMENT_CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#8a8a8a; font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif; }
.page { position:relative; overflow:hidden; margin:0 auto 24px auto; background:#fff; page-break-after: always; }
.el-text { white-space:pre-wrap; word-break:break-word; }
.el-scene { overflow:hidden; }
a { color:#1a73e8; }
"""


def render_static_html(manifest: dict, root_prefix: str = "") -> str:
    """生成可离线打开的静态画布 HTML（工程内 index.html / 导出文件共用）。"""
    canvas = manifest.get("canvas", {})
    cw, ch = canvas.get("width", 1280), canvas.get("height", 720)
    pages_html = []
    for page in manifest.get("pages", []):
        els = sorted(page.get("elements", []), key=lambda e: e.get("z", 0))
        inner = "".join(_with_el_id(element_html(e, root_prefix), e) for e in els)
        pages_html.append(
            f'<section class="page" data-name="{_ESC(page.get("name", ""))}" '
            f'style="width:{cw}px;height:{ch}px;{_bg_css(page.get("background"), root_prefix)}">{inner}</section>'
        )
    anim = _anim_data(manifest)
    css = f"""{ELEMENT_CSS}
{_ANIM_CSS if anim else ""}
@media print {{ body {{ background:#fff; }} .page {{ margin:0; }} .el-scene-frame, .el-scene-note {{ display:none !important; }} }}
@page {{ size: {cw}px {ch}px; margin:0; }}
"""
    title = html.escape(manifest.get("name", "未命名项目"))
    play_btn = '<button class="anim-play-btn" id="anim-play">▶ 播放动画</button>' if anim else ""
    anim_script = (
        f'<script>window.__CANVAS__={{w:{cw},h:{ch}}};window.__ANIM__={json.dumps(anim, ensure_ascii=False)};'
        f'document.getElementById("anim-play").addEventListener("click",function(){{{_ANIM_RUNTIME}}});</script>'
        if anim else ""
    )
    body = "\n".join(pages_html)
    # 有视频才注入播放脚本（音量 / 剪辑起止 / 播完返回开头 / 未播放时隐藏要靠它落地）
    video_script = f"<script>{_VIDEO_RUNTIME}{_SCRIPT_CLOSE}" if "data-ac-video" in body else ""
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\"/>\n"
        f"<title>{title}</title>\n<style>{css}</style>\n{_render_kit_script()}\n</head>\n<body>\n"
        + body
        + f"\n{play_btn}\n{anim_script}\n{video_script}\n</body>\n</html>\n"
    )


def render_page_html(manifest: dict, page_index: int = 0, root_prefix: str = "",
                     transparent: bool = False) -> tuple:
    """单页 HTML（PNG 导出与逐页截图共用）：页面尺寸严格等于画布，无外边距、无多余留白。

    transparent=True 时不画页面背景，截出来就是带透明通道的图。
    """
    canvas = manifest.get("canvas", {})
    cw, ch = int(_num(canvas.get("width"), 1280)), int(_num(canvas.get("height"), 720))
    pages = manifest.get("pages", [])
    page = pages[page_index] if 0 <= page_index < len(pages) else {}
    els = sorted(page.get("elements", []), key=lambda e: e.get("z", 0))
    inner = "".join(_with_el_id(element_html(e, root_prefix), e) for e in els)
    bg = "background:transparent;" if transparent else _bg_css(page.get("background"), root_prefix)
    css = (
        ELEMENT_CSS
        + "\nhtml, body { margin:0; padding:0; background:transparent !important; overflow:hidden; }\n"
        + ".page { margin:0 !important; page-break-after:auto; }\n"
    )
    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\"/>\n"
        f"<style>{css}</style>\n{_render_kit_script()}\n</head>\n<body>\n"
        f'<section class="page" style="width:{cw}px;height:{ch}px;{bg}">{inner}</section>\n'
        "</body>\n</html>\n"
    )
    return html, cw, ch


# 导出用的 DOM 探针：在真实浏览器里渲染一页，把「只有浏览器算得出来」的几何写回 body 属性。
# 表格的实测列宽 / 行高、代码块与公式的逐行逐色排版、统计图的原生 SVG —— 在 Python 里重算
# 必然与画布漂移（列宽按内容自动分配、公式靠 CSS 排版），所以让浏览器量一次、导出器照着摆。
_PROBE_JS = r"""
(function () {
  var D = document;
  function r2(n) { return Math.round(n * 100) / 100; }
  function cs(n) { return window.getComputedStyle(n); }
  function px(v) { var n = parseFloat(v); return isFinite(n) ? n : 0; }
  function col(c) {
    var m = /rgba?\(([^)]+)\)/.exec(String(c || ''));
    if (!m) return null;
    var q = m[1].split(',');
    var r = parseInt(q[0], 10) || 0, g = parseInt(q[1], 10) || 0, b = parseInt(q[2], 10) || 0;
    var a = q.length > 3 ? parseFloat(q[3]) : 1;
    if (!(a > 0.02)) return null;
    var h = ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
    return { c: '#' + h, a: a };
  }

  // box-shadow 解析：计算样式归一化后是「颜色 偏移X 偏移Y 模糊 扩展 [inset]」，
  // 与手写 CSS 的「偏移 模糊 颜色」顺序不同，所以按「有没有 inset / 颜色 / px 数」拆开取。
  function shadowParts(v) {
    var t = String(v || '');
    if (!t || t === 'none') return null;
    var inset = /\binset\b/.test(t);
    t = t.replace(/\binset\b/g, ' ');
    var color = '';
    var cm = /rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}/.exec(t);
    if (cm) { color = cm[0]; t = t.replace(cm[0], ' '); }
    var nums = [], re = /(-?[\d.]+)px/g, m;
    while ((m = re.exec(t))) nums.push(parseFloat(m[1]));
    return { inset: inset, color: color, nums: nums };
  }

  // box-shadow 可能叠多层，按顶层逗号切开（rgba() 里的逗号不算分隔符）
  function shadowLayers(v) {
    var t = String(v || '');
    if (!t || t === 'none') return [];
    var raw = [], depth = 0, buf = '';
    for (var i = 0; i < t.length; i++) {
      var ch = t.charAt(i);
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { raw.push(buf); buf = ''; } else buf += ch;
    }
    if (buf.replace(/\s/g, '')) raw.push(buf);
    var res = [];
    for (var j = 0; j < raw.length; j++) {
      var p = shadowParts(raw[j]);
      if (p) res.push(p);
    }
    return res;
  }

  // 底色 / 边框 → 矩形图元（边框拆成四条细矩形，SVG 与 PPTX 都能直接画）
  function pushRect(node, s, R, out) {
    if (px(s.opacity) === 0) return;
    var b = node.getBoundingClientRect();
    if (b.width <= 0 || b.height <= 0) return;
    var bg = col(s.backgroundColor);
    var bt = px(s.borderTopWidth), br = px(s.borderRightWidth);
    var bb = px(s.borderBottomWidth), bl = px(s.borderLeftWidth);
    var x = b.left - R.left, y = b.top - R.top, w = b.width, h = b.height;
    var radius = px(s.borderTopLeftRadius);
    // 投影：外投影画在本矩形之下（代码块卡片那道投影），无模糊内阴影画成对应边的强调条
    var layers = shadowLayers(s.boxShadow);
    for (var li = 0; li < layers.length; li++) {
      var L = layers[li], ln = L.nums;
      if (!L.inset && ln.length >= 3 && ln[2] > 0) {
        var oc = col(L.color);
        if (!oc) continue;
        var sdx = ln[0], sdy = ln[1], sblur = ln[2], sspr = ln.length > 3 ? ln[3] : 0;
        out.push({ k: 's', x: r2(x - sspr), y: r2(y - sspr),
                   w: r2(w + sspr * 2), h: r2(h + sspr * 2),
                   dx: r2(sdx), dy: r2(sdy), b: r2(sblur), f: oc.c, o: r2(oc.a) });
      }
    }
    if (bg) {
      var p = { k: 'r', x: r2(x), y: r2(y), w: r2(w), h: r2(h), f: bg.c };
      if (radius > 0) p.r = r2(Math.min(radius, Math.min(w, h) / 2));
      if (bg.a < 1) p.o = r2(bg.a);
      out.push(p);
    }
    if (bt > 0 || br > 0 || bb > 0 || bl > 0) {
      var edges = [
        [x, y, w, bt, s.borderTopColor],
        [x, y + h - bb, w, bb, s.borderBottomColor],
        [x, y + bt, bl, h - bt - bb, s.borderLeftColor],
        [x + w - br, y + bt, br, h - bt - bb, s.borderRightColor]
      ];
      for (var i = 0; i < 4; i++) {
        var e = edges[i];
        if (e[2] <= 0 || e[3] <= 0) continue;
        var c = col(e[4]);
        if (!c) continue;
        out.push({ k: 'r', x: r2(e[0]), y: r2(e[1]), w: r2(e[2]), h: r2(e[3]), f: c.c, o: r2(c.a) });
      }
    }
    // 无模糊内阴影（代码块高亮行左侧那道强调条）→ 对应边上的一条实心细矩形
    for (var ii = 0; ii < layers.length; ii++) {
      var G = layers[ii], gn = G.nums;
      if (!G.inset || gn.length < 3 || gn[2] > 0) continue;   // 带模糊的内阴影画不准，略过
      var gc = col(G.color);
      if (!gc) continue;
      var gdx = gn[0] || 0, gdy = gn[1] || 0, bar = null;
      if (Math.abs(gdx) >= Math.abs(gdy)) {
        if (gdx > 0) bar = [x, y, gdx, h];
        else if (gdx < 0) bar = [x + w + gdx, y, -gdx, h];
        else bar = [x, y, w, gdy > 0 ? gdy : 0];
      } else {
        bar = gdy > 0 ? [x, y, w, gdy] : [x, y + h + gdy, w, -gdy];
      }
      if (bar && bar[2] > 0.4 && bar[3] > 0.4) {
        out.push({ k: 'r', x: r2(bar[0]), y: r2(bar[1]), w: r2(bar[2]), h: r2(bar[3]),
                   f: gc.c, o: r2(gc.a) });
      }
    }
  }

  // 字形盒顶 → 基线的距离：SVG 的 <text y> 要的是基线，而 Range 给的是盒顶，
  // 少了这段偏移，整块代码 / 公式文字就会整体上浮小半行。
  var _mctx = null;
  function ascentOf(size, family) {
    var f = px(size);
    if (!_mctx) {
      var cv = D.createElement('canvas');
      _mctx = cv.getContext ? cv.getContext('2d') : null;
    }
    if (!_mctx) return f * 0.8;
    _mctx.font = f + 'px ' + String(family || '');
    var a = _mctx.measureText('Hg').fontBoundingBoxAscent;
    return (typeof a === 'number' && a > 0) ? a : f * 0.8;
  }

  // 文本节点 → 逐行图元（一个字一个字量，才能把「同一节点里的多行」拆开、把基线量准）
  function pushText(node, R, out) {
    var text = node.nodeValue;
    if (!text || !/\S/.test(text)) return;
    var s = cs(node.parentNode);
    if (s.display === 'none' || s.visibility === 'hidden') return;
    var c = col(s.color);
    if (!c) return;
    var bold = s.fontWeight === 'bold' || parseInt(s.fontWeight, 10) >= 600;
    var italic = /italic|oblique/.test(s.fontStyle);
    var range = D.createRange();
    var groups = [];
    if (text.length < 2) {
      range.selectNodeContents(node);
      var one = range.getBoundingClientRect();
      groups.push({ t: text, l: one.left, tp: one.top, rt: one.right, bt: one.bottom });
    } else {
      var limit = Math.min(text.length, 800);
      var cur = null;
      for (var i = 0; i < limit; i++) {
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        var rb = range.getBoundingClientRect();
        if (rb.width === 0 && rb.height === 0) {
          if (cur) cur.t += text.charAt(i);
          continue;
        }
        if (cur && Math.abs(rb.top - cur.tp) < 1) {
          cur.t += text.charAt(i);
          cur.l = Math.min(cur.l, rb.left);
          cur.rt = Math.max(cur.rt, rb.right);
          cur.bt = Math.max(cur.bt, rb.bottom);
        } else {
          cur = { t: text.charAt(i), l: rb.left, tp: rb.top, rt: rb.right, bt: rb.bottom };
          groups.push(cur);
        }
      }
    }
    for (var j = 0; j < groups.length; j++) {
      var g = groups[j];
      var w = g.rt - g.l, h = g.bt - g.tp;
      if (w <= 0.5 || h <= 0.5 || !/\S/.test(g.t)) continue;
      var p = { k: 't', x: r2(g.l - R.left), y: r2(g.tp - R.top), w: r2(w), h: r2(h), t: g.t, c: c.c };
      p.s = r2(px(s.fontSize));
      p.f = String(s.fontFamily || '');
      p.a = r2(ascentOf(s.fontSize, s.fontFamily));
      if (c.a < 1) p.o = r2(c.a);
      if (bold) p.b = 1;
      if (italic) p.i = 1;
      // 行内富文本：下划线 / 高亮底色 / 字距也要跟着走，否则这一段就退回整段样式
      if (/underline/.test(String(s.textDecorationLine || s.textDecoration || ''))) p.u = 1;
      var bgc = col(s.backgroundColor);
      if (bgc) { p.hl = bgc.c; if (bgc.a < 1) p.hlo = r2(bgc.a); }
      var lsp = px(s.letterSpacing);
      if (lsp) p.sp = r2(lsp);
      out.push(p);
    }
  }

  function walk(node, R, out) {
    if (node.nodeType === 3) { pushText(node, R, out); return; }
    if (node.nodeType !== 1) return;
    var s = cs(node);
    if (s.display === 'none' || s.visibility === 'hidden') return;
    pushRect(node, s, R, out);
    var kids = node.childNodes;
    for (var i = 0; i < kids.length; i++) walk(kids[i], R, out);
  }

  function displayList(root, R) {
    var out = [];
    walk(root, R, out);
    return out;
  }

  function measureTable(root, R) {
    var table = root.querySelector('table');
    if (!table) return null;
    var tb = table.getBoundingClientRect();
    var cols = [];
    var colEls = table.querySelectorAll('colgroup > col');
    for (var i = 0; i < colEls.length; i++) cols.push(r2(colEls[i].getBoundingClientRect().width));
    if (!cols.length || Math.min.apply(null, cols) <= 0) {
      cols = [];
      var first = table.rows.length ? table.rows[0].cells : [];
      for (var j = 0; j < first.length; j++) cols.push(r2(first[j].getBoundingClientRect().width));
    }
    var rws = [];
    for (var k = 0; k < table.rows.length; k++) rws.push(r2(table.rows[k].getBoundingClientRect().height));
    return {
      kind: 'table', dp: displayList(root, R),
      tbl: { x: r2(tb.left - R.left), y: r2(tb.top - R.top), w: r2(tb.width), h: r2(tb.height) },
      cols: cols, rws: rws
    };
  }

  function measureChart(root) {
    var svg = root.querySelector('svg');
    if (!svg) return null;
    // 图表 SVG 里的颜色全是内联的，字体靠继承：导出时把 font-family 补到外层即可
    return { kind: 'chart', vb: svg.getAttribute('viewBox') || '', svg: svg.outerHTML };
  }

  function measureOne(root) {
    var type = root.getAttribute('data-type') || '';
    var R = root.getBoundingClientRect();
    if (R.width <= 0 || R.height <= 0) return null;
    try {
      if (type === 'chart') return measureChart(root);
      if (type === 'table') return measureTable(root, R);
      if (type === 'code') {
        var dp = displayList(root, R);
        return dp.length ? { kind: 'dl', dp: dp } : null;
      }
      if (root.querySelector('.ac-tex') || root.getAttribute('data-ac-rich') === '1') {
        // 含 LaTeX 公式、或带行内富文本的文本 → 逐段量成图元清单
        var dp2 = displayList(root, R);
        return dp2.length ? { kind: 'dl', dp: dp2 } : null;
      }
    } catch (e) { return null; }
    return null;
  }

  function run() {
    var items = {};
    var list = D.querySelectorAll('.el[data-type]');
    for (var i = 0; i < list.length; i++) {
      var id = list[i].getAttribute('data-id');
      if (!id) continue;
      var m = measureOne(list[i]);
      if (m) items[id] = m;
    }
    try { D.body.setAttribute('data-ac-probe', JSON.stringify({ items: items })); } catch (e) { }
  }

  // 渲染器在 DOMContentLoaded 里水合元素，探针必须排在它之后：先 run 一次，再等图片与字体
  if (D.readyState === 'loading') D.addEventListener('DOMContentLoaded', run);
  else run();
  D.addEventListener('load', run);
  setTimeout(run, 150);
})();
"""


def render_probe_html(manifest: dict, page_index: int = 0, root_prefix: str = "") -> str:
    """DOM 探针页：与 render_page_html 同一套渲染，只是末尾追加测量脚本。

    结果写在 document.body 的 data-ac-probe 属性里（HTML 转义后），由 export.py 用
    `--dump-dom` 取回并 html.unescape + json.loads 解析。
    """
    html_str, _, _ = render_page_html(manifest, page_index, root_prefix, transparent=True)
    if "</body>" not in html_str:
        return html_str
    return html_str.replace("</body>", f"<script>{_PROBE_JS}{_SCRIPT_CLOSE}</script>\n</body>", 1)


def render_raster_sheet_html(sheet_w, sheet_h, root_prefix: str, cells) -> str:
    """「格子表」页 HTML（透明底），供 PPTX 混合导出截图。

    为什么不再把所有元素叠在各自原始坐标：那样同一张图里兄弟元素的像素会互相「串门」——
    从一个元素的框里裁下去，可能连隔壁元素的像素一起裁走（重叠 / 重影），被裁对象自己反而
    被别人的不透明像素挡住或切掉一半。改成每个元素各占一个带 overflow 的格子、格与格之间
    留出间隔，每格截出来的像素就只属于它自己。

    cells: [{el, canvas:(x,y,w,h), sheet:(x,y,w,h)}]。canvas 是该元素在画布上的外接矩形
    （含旋转外扩与视觉余量），sheet 是它在这张表上的落地矩形（尺寸与 canvas 相同）。
    页面底色不在这里画：幻灯片底色由 export.py 的 _apply_page_background 负责。
    """
    parts = []
    for cell in cells:
        el = cell["el"]
        cx, cy = _num(cell["canvas"][0]), _num(cell["canvas"][1])
        sx, sy, sw, sh = cell["sheet"]
        # 注意：格子是 position:absolute，元素就以格子为定位原点，所以这里只平移「画布外接矩形
        # 左上角 → 0,0」，格子自身的 left/top（sx/sy）负责把格子摆到表上。若再叠加 sx/sy，
        # 元素就会被推出格子、被 overflow 裁掉。
        frag = _with_el_id(element_html(el, root_prefix, offset=(-cx, -cy)), el)
        style = (
            f"position:absolute;left:{_fmt_num(sx)}px;top:{_fmt_num(sy)}px;"
            f"width:{_fmt_num(sw)}px;height:{_fmt_num(sh)}px;overflow:hidden;"
        )
        parts.append(f'<div class="cell" style="{style}">{frag}</div>')
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\"/>\n<style>"
        + ELEMENT_CSS
        + "\nhtml, body { margin:0; padding:0; background:transparent !important; }"
        + f" .sheet {{ position:relative; margin:0; background:transparent; overflow:hidden;"
        + f" width:{_fmt_num(_num(sheet_w))}px; height:{_fmt_num(_num(sheet_h))}px; }}\n</style>\n"
        + _render_kit_script()
        + "\n</head>\n<body>\n"
        + f'<div class="sheet">{"".join(parts)}</div>\n'
        + "</body>\n</html>\n"
    )


def manifest_outline(manifest: dict) -> dict:
    """给前端的工程概要（不传全量元素，减少桥接数据量）。"""
    return {
        "id": manifest.get("id"),
        "name": manifest.get("name"),
        "type": manifest.get("type"),
        "updatedAt": manifest.get("updatedAt"),
        "pageCount": len(manifest.get("pages", [])),
        "assetCount": len(manifest.get("assets", [])),
        "sessionCount": len(manifest.get("sessions", [])),
        "historyCount": len(manifest.get("history", [])),
    }
