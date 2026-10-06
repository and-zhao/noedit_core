"""微场景逐帧抓帧：无头浏览器逐帧截图 → 帧数组（供 core/scene_gif.py 合成 GIF）。

核心没有前端沙箱，抓帧必须在浏览器里做：容器怎么画、seek 到哪一帧，只有沙箱自己知道，
后端不执行前端代码。N 个时刻各出一份「定格文档」（projects._scene_document(seek_at=…)），
逐帧截屏即可。两条通路：

- playwright（可选依赖，装了就走）：开一个浏览器进程、逐帧换文档截图，快；
- 本机 Edge/Chrome 命令行：没有 playwright 时兜底，每次重启浏览器慢得多，
  所以退化成「精灵表」——把几帧并排塞进一张大页面只截一次，再按格子切帧。
  注意浏览器对塞满 iframe 的大页面只能光栅化到有限面积，格子面积要压住（SHEET_SAFE_PX），
  否则后面的格子会截成空帧。

前提与前端版一致：容器必须实现 seek(t)。自播场景的画面不随 seek 变化，
这里用「逐帧画面完全相同」把它识破并判失败，而不是导出一张废图。
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import projects as projects_mod
from . import scene_gif, scene_libs

# 单张精灵表的长边上限（CSS px）。再大浏览器截图会掉帧甚至崩，超了就拆成多张表。
SHEET_MAX_CSS = 6000
# 截图像素长边硬上限：CSS 尺寸 × 倍率不能超过它
SHEET_MAX_PX = 10000
# 单张精灵表的格子数上限
SHEET_MAX_CELLS = 6
# 单张精灵表里「所有格子加起来」的渲染面积上限（像素）。
# 无头浏览器对塞满 iframe 的大页面只能光栅化到有限一块区域，超出的格子会截成空画面
# （GIF 表现为闪空帧 / 白块）：实测 100 万像素稳定、400 万像素必掉，这里取中间偏保守。
SHEET_SAFE_PX = 1_600_000
# 格子间隔：避免相邻场景的像素互相渗进对方格子（与 export.RASTER_GUTTER 同理）
GUTTER = 8
# 抓帧的输出宽度上下限（像素）：与前端 scene-gif.js 的 MAX_CAPTURE_W 对齐
MAX_CAPTURE_W = 1920
MIN_CAPTURE_W = 120
# 一次抓帧所有场景文档的总字符预算：超了就降帧数，免得拼出几百 MB 的页面
DOC_BUDGET = 48 * 1024 * 1024
# 每张表等场景就绪的虚拟时间（ms）：库解析 + 首屏 + 若干帧重画
VIRTUAL_TIME_BUDGET = 6000
# 帧传输编码：WebP 有损（体积是 PNG 的几十分之一），Pillow 编不出来就退回 PNG
FRAME_QUALITY = 92


def _encode_frame(image) -> str:
    """PIL 图像 → dataURL（优先 WebP，退 PNG）。"""
    for fmt, mime in (("WEBP", "image/webp"), ("PNG", "image/png")):
        try:
            buf = io.BytesIO()
            if fmt == "WEBP":
                image.save(buf, fmt, quality=FRAME_QUALITY)
            else:
                image.save(buf, fmt)
            return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"
        except Exception:  # noqa: BLE001 —— 换下一种编码继续
            continue
    return ""


def _sheet_plan(count: int, cell_w: float, cell_h: float, max_css: float,
                max_cells: int = SHEET_MAX_CELLS) -> list[dict]:
    """把 count 个格子铺成若干张精灵表；返回 [{cols, rows, items:[帧号...]}]。"""
    cw = max(1.0, cell_w + GUTTER)
    ch = max(1.0, cell_h + GUTTER)
    max_cols = max(1, int(max_css // cw))
    max_rows = max(1, int(max_css // ch))
    per = max(1, min(max(1, int(max_cells)), max_cols * max_rows))
    plan: list[dict] = []
    start = 0
    while start < count:
        chunk = list(range(start, min(count, start + per)))
        cols = min(max_cols, len(chunk))
        rows = math.ceil(len(chunk) / cols)
        plan.append({"cols": cols, "rows": rows, "items": chunk})
        start += len(chunk)
    return plan


def _sheet_html(items: list, cols: int, rows: int, cell_w: float, cell_h: float, docs: list) -> tuple[str, float, float]:
    """拼一张精灵表页面：每格一个沙箱 iframe（srcdoc 是该时刻的场景文档）。"""
    parts = []
    for order, frame_index in enumerate(items):
        r, c = divmod(order, cols)
        left = c * (cell_w + GUTTER)
        top = r * (cell_h + GUTTER)
        parts.append(
            f'<div class="cell" style="left:{int(left)}px;top:{int(top)}px;'
            f'width:{int(cell_w)}px;height:{int(cell_h)}px">'
            f'<iframe sandbox="allow-scripts" scrolling="no" '
            f'srcdoc="{html.escape(docs[frame_index], quote=True)}"></iframe></div>'
        )
    width = cols * (cell_w + GUTTER) - GUTTER
    height = rows * (cell_h + GUTTER) - GUTTER
    doc = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"/>'
        '<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden;}'
        '.cell{position:absolute;overflow:hidden;background:transparent;}'
        '.cell iframe{display:block;width:100%;height:100%;border:0;background:transparent;}'
        '</style></head><body>'
        f'<div class="sheet">{"".join(parts)}</div></body></html>'
    )
    return doc, width, height


def _shot_sheet(browser: str, work_dir: Path, part: int, doc: str, w: float, h: float,
                scale: float, budget: int) -> "object":
    """截一张精灵表，返回 PIL 图像；失败返回 None。"""
    from PIL import Image

    page = work_dir / f"sheet-{part}.html"
    page.write_text(doc, encoding="utf-8")
    shot = (work_dir / f"sheet-{part}.png").resolve()
    profile = Path(tempfile.mkdtemp(prefix="noedit_core-scene-"))
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "--default-background-color=00000000",   # 透明底：场景没画到的地方不能被刷白
        f"--force-device-scale-factor={scale}",
        f"--window-size={int(w)},{int(h)}",
        f"--virtual-time-budget={budget}",
        f"--user-data-dir={profile}",
        f"--screenshot={shot}",
        page.resolve().as_uri(),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not shot.exists():
        return None
    try:
        return Image.open(shot).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def _playwright_ready() -> bool:
    """playwright 是可选依赖（与 extensions/mcp-server 一致）：装了就走快通路。"""
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _capture_frames_playwright(docs: list, layout_w: float, layout_h: float,
                               out_scale: float) -> list:
    """Playwright 通路：开一个浏览器进程，逐帧换文档、逐帧截图。

    无头浏览器「启动一次」就要好几秒，精灵表法正是为了摊薄这个成本，但把几十个 iframe
    塞进一页后浏览器只能光栅化其中一部分（其余截成空帧）。这里改成一次启动、逐帧截图：
    每帧都是独立页面，不受光栅化面积限制；进程复用又把启动成本摊成了零。
    没装 playwright 或三个 channel 都起不来时返回 []，交给命令行通路兜底。
    """
    if not _playwright_ready():
        return []

    from PIL import Image
    from playwright.sync_api import sync_playwright

    for channel in ("msedge", "chrome", None):
        images: list = []
        try:
            with sync_playwright() as pw:
                launch_args = {"args": ["--hide-scrollbars", "--no-first-run", "--disable-extensions"]}
                if channel:
                    launch_args["channel"] = channel
                browser = pw.chromium.launch(**launch_args)
                try:
                    context = browser.new_context(
                        viewport={"width": int(round(layout_w)), "height": int(round(layout_h))},
                        device_scale_factor=float(out_scale),
                    )
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    for doc in docs:
                        page.set_content(doc, wait_until="load")
                        try:
                            page.wait_for_function("window.__frameReady === true", timeout=15000)
                        except Exception:  # noqa: BLE001 —— 等不到就拍当前画面，别把整批拖垮
                            page.wait_for_timeout(200)
                        raw = page.screenshot(omit_background=True)
                        image = Image.open(io.BytesIO(raw))
                        image.load()
                        images.append(image.convert("RGBA"))
                finally:
                    browser.close()
            return images
        except Exception:  # noqa: BLE001 —— 换下一个 channel 再试
            continue
    return []


def _capture_frames_cli(browser: str, docs: list, layout_w: float, layout_h: float,
                        out_scale: float, work_dir: Path) -> list:
    """命令行兜底通路：本机 Edge/Chrome 逐张精灵表截图（每次都要重启浏览器，慢）。

    合表时把「所有格子加起来的渲染面积」压在 SHEET_SAFE_PX 以内：超了浏览器只会光栅化
    前几格，剩下的截出来是空的。宁可多开几张表，也不要空帧。
    """
    if not browser:
        return []

    cell_px = max(1.0, layout_w * out_scale) * max(1.0, layout_h * out_scale)
    per = max(1, min(SHEET_MAX_CELLS, int(SHEET_SAFE_PX // cell_px)))
    max_css = max(256.0, min(SHEET_MAX_CSS, SHEET_MAX_PX / out_scale))
    cw = layout_w + GUTTER
    ch = layout_h + GUTTER
    frames: list = []
    for part, sheet in enumerate(_sheet_plan(len(docs), layout_w, layout_h, max_css, per)):
        doc, w, h = _sheet_html(sheet["items"], sheet["cols"], sheet["rows"], layout_w, layout_h, docs)
        image = _shot_sheet(browser, work_dir, part, doc, w, h, out_scale, VIRTUAL_TIME_BUDGET)
        if image is None:
            continue
        for order, frame_index in enumerate(sheet["items"]):
            r, c = divmod(order, sheet["cols"])
            box = (
                int(round(c * cw * out_scale)), int(round(r * ch * out_scale)),
                int(round((c * cw + layout_w) * out_scale)), int(round((r * ch + layout_h) * out_scale)),
            )
            frames.append((frame_index, image.crop(box)))

    frames.sort(key=lambda pair: pair[0])
    return [img for _i, img in frames]


def capture_frames(browser: str, element: dict, work_dir: Path, *, duration, frames: int,
                   width: float, scale: float = 1.0) -> dict:
    """抓一个微场景的逐帧画面。返回 {ok, frames:[dataURL...], width, height, message, ...}。

    duration 秒内均匀采 frames 帧；width 是期望输出宽度（像素），scale 是像素倍率。
    容器必须实现 seek(t)，否则画面不随时间变，会判失败。
    """
    props = element.get("props") or {}
    code = str(props.get("code") or "")
    if not code.strip():
        return {"ok": False, "frames": [], "message": "微场景还没填代码"}

    el_w = float(element.get("w") or 0)
    el_h = float(element.get("h") or 0)
    ratio = (el_h / el_w) if (el_w > 0 and el_h > 0) else 9 / 16
    layout_w = max(MIN_CAPTURE_W, min(MAX_CAPTURE_W, int(round(float(width) or el_w or 480))))
    layout_h = max(2, int(round(layout_w * ratio)))
    out_scale = max(1.0, min(float(scale or 1), MAX_CAPTURE_W / layout_w))
    pixel_w = max(1, int(round(layout_w * out_scale)))
    pixel_h = max(2, int(round(layout_h * out_scale)))

    known = {item["id"] for item in scene_libs.list_libs()}
    raw_libs = props.get("libs")
    lib_ids = [str(x) for x in raw_libs if x in known] if isinstance(raw_libs, list) else []
    sources = scene_libs.sources_for(lib_ids)
    missing = sources["missing"]

    duration = max(0.2, min(60.0, float(duration or 3)))
    frames = max(2, min(scene_gif.MAX_FRAMES, int(frames or 12)))

    # 文档体积预算：库 + 代码会被塞进每一格，超预算就按比例降帧数，免得拼出超大页面
    per_doc = sum(len(s) for s in sources["sources"].values()) + len(code) + 2048
    while frames > 2 and per_doc * frames > DOC_BUDGET:
        frames -= 1

    step = duration / frames
    docs = [
        projects_mod._scene_document(
            code, duration, False, props.get("params"), sources["sources"], seek_at=i * step
        )
        for i in range(frames)
    ]

    images = _capture_frames_playwright(docs, layout_w, layout_h, out_scale)
    if not images:
        images = _capture_frames_cli(browser, docs, layout_w, layout_h, out_scale, work_dir)

    if len(images) < 2:
        return {"ok": False, "frames": [], "message": "抓帧失败：无头浏览器没有截出可用画面（检查是否装了 Edge / Chrome）"}

    frames_pil = images

    # 缺库 = 场景跑不起来，抓出来的也是残图，直接判失败让调用方先 install_scene_lib
    if missing:
        return {
            "ok": False, "frames": [], "width": pixel_w, "height": pixel_h,
            "missing": missing, "identical": False, "count": 0,
            "message": f"缺少本地库：{'、'.join(missing)}（先 install_scene_lib 下载后重试）",
        }

    # 「逐帧画面完全相同」= 容器没随 seek(t) 重画（自播场景或 seek 没生效）→ 导出的动图只会是一张静图
    sigs = {hashlib.md5(img.tobytes()).hexdigest() for img in frames_pil}
    if len(sigs) == 1:
        return {
            "ok": False, "frames": [], "width": pixel_w, "height": pixel_h,
            "identical": True, "count": 0,
            "message": "逐帧抓到的画面完全相同：容器没有随 seek(t) 重画（多半是自播场景，或 seek 没生效），无法导出动图",
        }

    data_urls = []
    for img in frames_pil:
        url = _encode_frame(img)
        if url:
            data_urls.append(url)

    return {
        "ok": len(data_urls) >= 2,
        "frames": data_urls,
        "width": pixel_w,
        "height": pixel_h,
        "count": len(data_urls),
        "identical": False,
        "missing": [],
        "message": "" if len(data_urls) >= 2 else "帧编码失败（Pillow 既编不出 WebP 也编不出 PNG）",
    }


def capture_scene_gif(browser: str, project_root: Path, element: dict, *, out_dir: str = "",
                      fps: int = 12, width: float = 0, scale: float = 2.0,
                      background: str = "", transparent: bool = True, name: str = "") -> dict:
    """抓帧 + 合成：把一个微场景元素导成 GIF。失败返回 {ok: False, path: "", message}。"""
    if not browser and not _playwright_ready():
        return {"ok": False, "path": "", "message": "未找到 Microsoft Edge 或 Chrome（也没装 playwright），无法抓帧导出 GIF"}

    props = element.get("props") or {}
    duration = max(0.2, min(60.0, float(props.get("duration") or 3)))
    fps = max(1, min(30, int(fps or 12)))
    frames = max(2, int(round(duration * fps)))
    if frames > scene_gif.MAX_FRAMES:
        fps = max(1, int(scene_gif.MAX_FRAMES // duration))
        frames = max(2, int(round(duration * fps)))

    work_dir = Path(tempfile.mkdtemp(prefix="noedit_core-scene-grab-"))
    try:
        grabbed = capture_frames(browser, element, work_dir, duration=duration, frames=frames,
                                 width=width or (element.get("w") or 480), scale=scale)
        if not grabbed.get("ok"):
            return {"ok": False, "path": "", "message": grabbed.get("message") or "抓帧失败"}
        result = scene_gif.export_scene_gif(project_root, {
            "frames": grabbed["frames"],
            "fps": fps,
            "loop": props.get("loop", True) is not False,
            "background": background or "#ffffff",
            "transparent": bool(transparent),
            "outDir": out_dir or "",
            "name": name or f"scene-{element.get('name') or element.get('id') or 'scene'}",
        })
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if result.get("ok") and grabbed.get("message"):
        result["message"] = f"{result['message']}；{grabbed['message']}"
    elif not result.get("ok") and grabbed.get("message"):
        result["message"] = f"{result.get('message') or '合成失败'}（{grabbed['message']}）"
    result["width"] = grabbed.get("width")
    result["height"] = grabbed.get("height")
    return result


def _page_solid_bg(page: dict, fallback: str = "#ffffff") -> str:
    """取页面纯色背景色，作为 GIF 的打底色。

    微场景是透明底的，合成 GIF 时必须先铺一层底色（GIF 没有 alpha 混合）。
    铺错色（比如一律铺白）会在深色页面上留下一块白雾，所以跟着页面背景走。
    页面背景不是纯色（渐变 / 图片）时退回 fallback。
    """
    bg = page.get("background")
    if isinstance(bg, dict) and str(bg.get("type") or "solid") == "solid":
        color = str(bg.get("color") or "").strip()
        if color:
            return color
    return fallback


def capture_project_gifs(browser: str, project_root: Path, manifest: dict, *, out_dir: str = "",
                         fps: int = 12, scale: float = 2.0) -> dict:
    """导出 PPTX 前批量抓帧：把每个「有代码」的微场景抓成 GIF。单个失败只记账、不抛出。

    返回 {gifs: {元素id: GIF 路径}, failed: [{id, name, reason}], skipped: 无代码场景数}
    """
    gifs: dict[str, str] = {}
    failed: list[dict] = []
    skipped = 0
    if not browser and not _playwright_ready():
        return {"gifs": gifs, "failed": failed, "skipped": skipped, "noBrowser": True}

    for page in manifest.get("pages") or []:
        page_bg = _page_solid_bg(page)
        for el in page.get("elements") or []:
            if el.get("type") != "scene":
                continue
            if not str((el.get("props") or {}).get("code") or "").strip():
                skipped += 1
                continue
            try:
                res = capture_scene_gif(
                    browser, project_root, el, out_dir=out_dir, fps=fps,
                    width=float(el.get("w") or 480), scale=scale,
                    background=page_bg, transparent=True,
                    name=f"ppt-scene-{el.get('name') or 'scene'}-{el.get('id')}",
                )
            except Exception as exc:  # noqa: BLE001 —— 一个坏场景不能把整批导出带下水
                res = {"ok": False, "message": f"生成动图时出错：{exc}"}
            if res.get("ok") and res.get("path"):
                gifs[str(el.get("id"))] = str(res["path"])
            else:
                failed.append({"id": el.get("id"), "name": el.get("name"),
                               "reason": res.get("message") or "GIF 合成失败"})
    return {"gifs": gifs, "failed": failed, "skipped": skipped}
