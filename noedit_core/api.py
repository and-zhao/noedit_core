"""NoEdit Core 的最小公共 API。

覆盖这条闭环：**建工程 → 加页 → 增/改/删元素 → 导素材 → 导出**。

所有函数都是同步阻塞的普通 Python 调用；出错抛 CoreError（message 可直接展示）。
坐标单位是画布 px，原点左上；页面索引从 0 开始，`-1` 表示「所有页 / 不指定」。
"""

from __future__ import annotations

import copy
from pathlib import Path

from .core import actions as act
from .core import assets as assets_mod
from .core import element_schema
from .core import export as export_mod
from .core import icon_catalog
from .core import projects as projects_mod
from .core import scene_capture, scene_gif
from .core import scene_libs as scene_libs_mod
from .core.errors import CoreError
from .core.paths import MANIFEST_NAME
from .core.store import (
    edit_project,
    mutate,
    project_lock,
    project_root,
    read_manifest,
    write_manifest,
)

__all__ = [
    "CoreError",
    "create_project",
    "open_project",
    "canvas",
    "list_pages",
    "add_page",
    "update_page",
    "delete_page",
    "list_elements",
    "insert",
    "update",
    "delete",
    "reorder",
    "import_asset",
    "list_assets",
    "export",
    "element_types",
    "icon_groups",
    "icon_list",
    "icon_search",
    "icon_insert",
    "scene_libs",
    "install_scene_lib",
    "remove_scene_lib",
    "compose_scene_gif",
    "export_scene_gif",
]

# ---------------------------------------------------------------- 工程


def _summary(manifest: dict) -> dict:
    return {
        "name": manifest.get("name"),
        "type": manifest.get("type"),
        "canvas": manifest.get("canvas"),
        "pageCount": len(manifest.get("pages") or []),
        "assetCount": len(manifest.get("assets") or []),
        "updatedAt": manifest.get("updatedAt"),
    }


def create_project(
    name: str,
    parent_dir: str,
    preset: str = "ppt-16:9",
    ptype: str = "ppt",
) -> dict:
    """新建工程。目录名取 name（重名自动追加 -2/-3），落在 parent_dir 下。

    preset 见 core/projects.py 的 CANVAS_PRESETS（ppt-16:9 / ppt-4:3 / a4-* 等）。
    返回 {path, summary, url}；url 是该工程 index.html 的 file:// 地址。
    """
    parent = Path(parent_dir).expanduser().resolve()
    if not str(parent_dir).strip():
        raise CoreError("必须给出 parent_dir（新工程要放在哪个目录下）")
    parent.mkdir(parents=True, exist_ok=True)
    target = projects_mod.unique_project_dir(parent, name or "未命名项目")
    target.mkdir(parents=True, exist_ok=True)
    assets_mod.assets_dir(target)                      # 先建 assets/，与软件侧工程结构一致

    manifest = projects_mod.default_manifest(target.name, ptype, preset)
    with project_lock(target):
        write_manifest(target, manifest)
    return {
        "path": str(target),
        "summary": _summary(manifest),
        "url": (target / "index.html").as_uri(),
    }


def open_project(path: str) -> dict:
    """打开工程：返回概要 + 大纲（每页 id/名称/元素数）+ 预览地址。"""
    root = project_root(path)
    manifest = read_manifest(root)
    pages = manifest.get("pages") or []
    return {
        "path": str(root),
        "summary": _summary(manifest),
        "outline": [
            {"index": i, "id": p.get("id"), "name": p.get("name"),
             "elementCount": len(p.get("elements") or [])}
            for i, p in enumerate(pages)
        ],
        "url": (root / "index.html").as_uri(),
    }


def canvas(path: str) -> dict:
    """取画布信息（宽高/预设/背景）。"""
    manifest = read_manifest(project_root(path))
    return {"canvas": manifest.get("canvas")}


# ---------------------------------------------------------------- 页面


def list_pages(path: str) -> dict:
    manifest = read_manifest(project_root(path))
    return {
        "path": str(project_root(path)),
        "canvas": manifest.get("canvas"),
        "pages": [
            {"index": i, "id": p.get("id"), "name": p.get("name"),
             "elementCount": len(p.get("elements") or []), "background": p.get("background")}
            for i, p in enumerate(manifest.get("pages") or [])
        ],
    }


def add_page(path: str, index: int = -1, name: str = "", background: dict | None = None) -> dict:
    """新增一页。index<0 或不传 = 追加到末尾；background 会与页面默认背景合并。"""
    def mut(manifest):
        pages = manifest.setdefault("pages", [])
        page = act.new_page(manifest, name or None)
        if background:
            page["background"] = {**page["background"], **background}
        at = len(pages) if index is None or int(index) < 0 else max(0, min(len(pages), int(index)))
        pages.insert(at, page)
        return {"index": at, "id": page["id"], "name": page["name"], "pageCount": len(pages)}

    root, _m, extra = mutate(path, mut)
    return {"path": str(root), **extra}


def update_page(path: str, props: dict, page_index: int = 0,
                page_indexes: list | None = None, all_pages: bool = False) -> dict:
    """改页面属性。props 的键是点号路径，常用：

    - `background`：页面背景，如 {"type": "image", "image": "assets/bg.jpg", "fit": "cover"}
      或 {"type": "solid", "color": "#0f172a"}（会与页面默认背景合并）。
    - `name`：页名。

    不传页范围时只改 page_index 这一页；all_pages=True 改所有页（全篇统一背景走这条）。
    """
    spec: dict = {"op": "page.update", "props": props}
    if all_pages:
        spec["allPages"] = True
    elif page_indexes:
        spec["pageIndexes"] = list(page_indexes)
    else:
        spec["pageIndexes"] = [int(page_index)]
    return _run(path, spec, page_index=page_index)


def delete_page(path: str, index: int) -> dict:
    """删掉某一页（0 起）。至少保留一页，删到只剩一页会抛 CoreError。"""
    if index is None:
        raise CoreError("必须给出要删除的页号 index")
    return _run(path, {"op": "page.delete", "index": int(index)}, page_index=int(index))


# ---------------------------------------------------------------- 元素


def _brief(el: dict) -> dict:
    return {k: el.get(k) for k in ("id", "type", "name", "x", "y", "w", "h", "z", "parentId")}


def list_elements(path: str, page_index: int = -1, full: bool = False) -> dict:
    """列出元素。page_index<0 = 列所有页；full=True 返回完整 props/style。"""
    manifest = read_manifest(project_root(path))
    pages = manifest.get("pages") or []
    pick = (lambda p: p.get("elements") or [])
    ser = (lambda e: copy.deepcopy(e)) if full else _brief

    if page_index is None or int(page_index) < 0:
        return {
            "path": str(project_root(path)),
            "pages": [
                {"index": i, "id": p.get("id"), "name": p.get("name"),
                 "elements": [ser(e) for e in act.sorted_elements(p)]}
                for i, p in enumerate(pages)
            ],
        }
    idx = int(page_index)
    if not (0 <= idx < len(pages)):
        raise CoreError(f"页序越界：{idx}（共 {len(pages)} 页）")
    page = pages[idx]
    return {
        "path": str(project_root(path)),
        "pageIndex": idx, "pageId": page.get("id"), "pageName": page.get("name"),
        "elements": [ser(e) for e in act.sorted_elements(page)],
    }


def _run(path: str, spec: dict, page_index: int = 0) -> dict:
    """把一条 op 交给动作引擎执行并落盘。"""
    def mut(manifest):
        result = act.apply_actions(manifest, [spec], page_index=int(page_index))
        if result["errors"]:
            raise CoreError(result["errors"][0])
        return {"changed": result["changed"], "logs": result["logs"]}

    root, _m, extra = mutate(path, mut)
    return {"path": str(root), **extra}


def insert(path: str, element: dict, page_index: int = 0,
           page_indexes: list | None = None, all_pages: bool = False) -> dict:
    """在指定页插入一个元素。element 至少给 type，其余字段缺省值取自 element-schema.json。

    element 形如 {"type": "text", "x": 80, "y": 60, "props": {"text": "标题"},
                  "style": {"fontSize": 40}}。
    """
    if not isinstance(element, dict) or not element.get("type"):
        raise CoreError("element 必须是对象且带 type 字段")
    spec: dict = {"op": "insert", "element": element}
    if all_pages:
        spec["allPages"] = True
    elif page_indexes:
        spec["pageIndexes"] = list(page_indexes)
    else:
        spec["pageIndexes"] = [int(page_index)]
    return _run(path, spec, page_index=page_index)


def update(path: str, props: dict, element_id: str = "", match: dict | None = None,
           page_index: int = 0, page_indexes: list | None = None, all_pages: bool = False) -> dict:
    """改元素。props 的键是**点号路径**，例如 {"x": 100, "props.text": "新标题",
    "style.fontSize": 32}。用 element_id 精确定位，或用 match 按描述定位，如
    {"type": "text", "text": "标题"}。"""
    return _run(path, _target("update", element_id, match, page_indexes, all_pages, props=props),
                page_index=page_index)


def delete(path: str, element_id: str = "", match: dict | None = None,
           page_index: int = 0, page_indexes: list | None = None, all_pages: bool = False) -> dict:
    """删除元素。定位方式同 update。"""
    return _run(path, _target("delete", element_id, match, page_indexes, all_pages),
                page_index=page_index)


def reorder(path: str, element_id: str = "", match: dict | None = None, index: int = -1,
            to_front: bool = False, to_back: bool = False, page_index: int = 0) -> dict:
    """调层级。给 index（0 起，越大越靠上），或用 to_front / to_back。"""
    spec = _target("reorder", element_id, match, None, False)
    if to_front:
        spec["index"] = 0
    elif to_back:
        spec["index"] = 10 ** 6
    elif index is None or int(index) < 0:
        raise CoreError("请给出 index，或使用 to_front / to_back")
    else:
        spec["index"] = int(index)
    return _run(path, spec, page_index=page_index)


def _target(op: str, element_id: str, match: dict | None, page_indexes, all_pages, **extra) -> dict:
    spec: dict = {"op": op}
    if element_id:
        spec["id"] = element_id
    if match:
        spec["match"] = match
    if page_indexes:
        spec["pageIndexes"] = list(page_indexes)
    if all_pages:
        spec["allPages"] = True
    if not element_id and not match:
        raise CoreError("必须给出 element_id 或 match（按描述定位）")
    spec.update({k: v for k, v in extra.items() if v is not None})
    return spec


# ---------------------------------------------------------------- 工程内素材


def import_asset(path: str, source_paths: list) -> dict:
    """把外部文件复制进工程的 assets/ 目录并登记，返回工程内相对路径 relPath。

    之后元素要用它，就把 props.src 写成这个 relPath（如 "assets/logo.png"）。
    这是**工程内本地素材**：随工程文件夹一起迁移，不依赖任何全局素材库。
    """
    if not source_paths:
        raise CoreError("请给出要导入的文件路径 source_paths")
    root = project_root(path)

    def mut(manifest):
        records = assets_mod.import_assets(root, list(source_paths))
        if not records:
            raise CoreError("没有可导入的文件（路径不存在或不是文件）")
        manifest.setdefault("assets", []).extend(records)
        return {"imported": records}

    _root, _m, extra = mutate(path, mut, refresh_html=False)
    return {"path": str(root), **extra}


def list_assets(path: str) -> dict:
    """列出工程内素材，并标明文件是否还在磁盘上。"""
    root = project_root(path)
    manifest = read_manifest(root)
    return {
        "path": str(root),
        "assets": [
            {"name": a.get("name"), "relPath": a.get("relPath"), "kind": a.get("kind"),
             "size": a.get("size"), "exists": (root / str(a.get("relPath") or "")).exists()}
            for a in (manifest.get("assets") or [])
        ],
    }


# ---------------------------------------------------------------- 导出


def export(path: str, fmt: str = "pptx", out_dir: str = "", scene_gifs=None, **options) -> dict:
    """导出。fmt ∈ html | pdf | pptx | png | svg；默认落到工程内的 export/ 目录。

    - pptx 需 python-pptx；pdf / png / svg 需本机 Edge/Chrome（无头打印/渲染）。
    - png / svg 额外支持 options：pages（"1" / "1,3" / "2-5"，空=全部）、
      dpi（96/150/300/600）、transparent（bool）。

    微场景 vs 导出格式：
    - html：微场景是真身（沙箱 iframe 跑 props.code），会动；
    - pptx：PPTX 不是可执行环境，微场景默认由 playwright（没装则退回本机 Edge/Chrome）逐帧抓帧合成 GIF 内嵌（会动）。
      scene_gifs 可覆盖这一行为：给 {元素id: GIF 绝对路径} 就用现成的，给 False 就不内嵌动图（只留封面帧）；
    - pdf / png / svg：静态，微场景取 props.poster 封面帧。
    """
    root = project_root(path)
    with project_lock(root):
        manifest = read_manifest(root)
    fmt = (fmt or "pptx").lower()
    src = str(root)
    if fmt == "html":
        return export_mod.export_static_html(src, manifest, out_dir=out_dir)
    if fmt == "pdf":
        return export_mod.export_pdf(src, manifest, out_dir=out_dir)
    if fmt == "pptx":
        gifs = None
        scene_note = ""
        if isinstance(scene_gifs, dict):
            gifs = scene_gifs
        elif scene_gifs is not False:
            has_scene = any(
                el.get("type") == "scene" and str((el.get("props") or {}).get("code") or "").strip()
                for page in (manifest.get("pages") or [])
                for el in (page.get("elements") or [])
            )
            if has_scene:
                capped = scene_capture.capture_project_gifs(
                    export_mod._find_browser(), root, manifest, out_dir=out_dir
                )
                gifs = capped["gifs"] or None
                if capped.get("noBrowser"):
                    scene_note = "；未找到 Edge/Chrome 且未安装 playwright，微场景无法抓帧成动图，已退回封面帧静图"
                elif capped["failed"]:
                    scene_note = f"；{len(capped['failed'])} 个微场景没能生成动图（{capped['failed'][0]['reason']}）"
                elif gifs:
                    scene_note = f"；{len(gifs)} 个微场景已内嵌 GIF 动图"
        result = export_mod.export_pptx(src, manifest, out_dir=out_dir, scene_gifs=gifs)
        if scene_note and result.get("ok"):
            result["message"] = str(result.get("message") or "") + scene_note
        return result
    if fmt == "png":
        return export_mod.export_png(src, manifest, out_dir=out_dir, options=options or None)
    if fmt == "svg":
        return export_mod.export_svg(src, manifest, out_dir=out_dir, options=options or None)
    raise CoreError(f"不支持的导出格式：{fmt}（可选 html / pdf / pptx / png / svg）")


# ---------------------------------------------------------------- 微场景（scene）

def scene_libs() -> list[dict]:
    """列出微场景可用的前端库及本地缓存状态（cached=True 表示已下载、离线可用）。"""
    return scene_libs_mod.list_libs()


def install_scene_lib(lib_id: str = "") -> dict:
    """下载并缓存微场景库（唯一需要联网的动作）。lib_id 留空 = 下载全部。

    只有在场景 props.libs 里声明的库已缓存，导出的 HTML 才能在沙箱里跑起来。
    """
    if str(lib_id or "").strip():
        return scene_libs_mod.ensure_lib(str(lib_id).strip())
    results = []
    for item in scene_libs_mod.list_libs():
        try:
            results.append(scene_libs_mod.ensure_lib(item["id"]))
        except Exception as exc:  # noqa: BLE001 —— 某个库下载失败不影响其它
            results.append({"id": item["id"], "cached": False, "error": str(exc)})
    return {"libs": results}


def remove_scene_lib(lib_id: str) -> dict:
    """删除本地缓存的微场景库。"""
    return scene_libs_mod.remove_lib(str(lib_id or "").strip())


def compose_scene_gif(path: str, frames: list, fps: int = 12, loop: bool = True,
                      background: str = "#ffffff", transparent: bool = False,
                      out_dir: str = "", name: str = "") -> dict:
    """把外部抓好的帧（dataURL 数组）合成为 GIF，落到工程导出目录。

    给「帧已在别处抓好」的场景用（例如自带前端抓帧的调用方）；
    只要微场景元素在工程里，直接用 export_scene_gif 一步到位。
    """
    root = project_root(path)
    return scene_gif.export_scene_gif(root, {
        "frames": list(frames or []),
        "fps": fps,
        "loop": loop,
        "background": background,
        "transparent": transparent,
        "outDir": out_dir,
        "name": name,
    })


def _find_scene(manifest: dict, element_id: str, match: dict | None, page_index: int):
    """在工程里定位一个 scene 元素；返回 (page, element)。"""
    pages = manifest.get("pages") or []
    if page_index is not None and int(page_index) >= 0:
        scope = [int(page_index)]
    else:
        scope = list(range(len(pages)))
    for index in scope:
        if not (0 <= index < len(pages)):
            continue
        for el in pages[index].get("elements") or []:
            if el.get("type") != "scene":
                continue
            if element_id and el.get("id") == element_id:
                return pages[index], el
            if not element_id and match:
                ok = all(
                    (el.get("props") or {}).get(k) == v if k not in ("id", "type", "name") else el.get(k) == v
                    for k, v in match.items()
                )
                if ok:
                    return pages[index], el
    return None, None


def export_scene_gif(path: str, element_id: str = "", match: dict | None = None,
                     page_index: int = 0, out_dir: str = "", fps: int = 12, width: float = 0,
                     scale: float = 2.0, background: str = "#ffffff", transparent: bool = True,
                     name: str = "") -> dict:
    """把一个微场景元素逐帧抓帧并合成 GIF（需要 playwright，或本机 Edge/Chrome）。

    抓帧走无头浏览器（core/scene_capture.py）：把整段时长均匀采样成 N 帧。
    只有实现了 seek(t) 的容器能导出动图；自播场景会判失败并说明原因。
    element_id 或 match（如 {"name": "标题场景"}）任选其一。
    """
    root = project_root(path)
    manifest = read_manifest(root)
    _page, el = _find_scene(manifest, element_id, match, page_index)
    if el is None:
        raise CoreError("没找到微场景元素（检查 element_id / match / page_index）")
    return scene_capture.capture_scene_gif(
        export_mod._find_browser(), root, el, out_dir=out_dir, fps=fps, width=width,
        scale=scale, background=background, transparent=transparent, name=name,
    )


# ---------------------------------------------------------------- 矢量图标库

def _icons_ready() -> None:
    if not icon_catalog.load():
        raise CoreError("图标目录读取失败：noedit_core/web/icon-catalog.json 缺失或损坏")


def icon_groups() -> list[dict]:
    """列出矢量图标的分组（含二级分组的父大类与数量）。

    图标目录随核心分发（web/icon-catalog*.json），空列表 = 目录缺失。
    """
    return icon_catalog.groups()


def icon_list(group: str = "", limit: int = 200) -> dict:
    """列出某分组（或某个大类）里的图标；group 留空 = 只回分组概览、不列图标。

    返回条目是精简字段（id/label/group/box/line/multi），不带 path 的 d。
    """
    _icons_ready()
    groups = icon_catalog.groups()
    if not group:
        return {"groups": groups, "total": icon_catalog.count(), "icons": []}
    items = icon_catalog.icons(group)
    top = max(1, int(limit or 200))
    return {"groups": groups, "group": group, "total": len(items),
            "icons": [icon_catalog.brief(i) for i in items[:top]]}


def icon_search(keyword: str = "", group: str = "", limit: int = 40) -> dict:
    """按关键词搜图标（匹配英文名 / id / 中文分组名），可选限定 group。"""
    _icons_ready()
    try:
        top = max(1, int(limit or 40))
    except (TypeError, ValueError):
        top = 40
    items = icon_catalog.search(keyword, group=group, limit=10 ** 6)
    return {"keyword": keyword, "group": group, "total": len(items),
            "icons": [icon_catalog.brief(i) for i in items[:top]]}


def icon_insert(path: str, icon_id: str, x: int | None = None, y: int | None = None,
                size: int = 150, color: str = "#2f6fed", name: str = "",
                page_index: int = 0, page_indexes: list | None = None,
                all_pages: bool = False) -> dict:
    """按图标 id 造可编辑的 path 元素并插入指定页（与图标目录同源）。

    单色图标（可换色）插一个 path 元素，颜色取 color；多色图标（自带配色）插一组元素：
    一个 group 容器 + 若干按层着色的 path 成员，成员挂在容器下（parentId），此时 color
    不参与。x / y 省略时按画布居中偏上摆位；size 是元素框长边像素。
    """
    icon = icon_catalog.by_id(str(icon_id or ""))
    if not icon:
        raise CoreError(f"没有这个图标：{icon_id}（先用 icon_search 按关键词找）")

    def mut(manifest):
        canvas = manifest.get("canvas") or {}
        w, h = icon_catalog.fit_size(icon_id, size)
        px = int(x) if x is not None else round((int(canvas.get("width") or 1280) - w) / 2)
        py = int(y) if y is not None else round((int(canvas.get("height") or 720) - h) / 3)

        pages = manifest.get("pages") or []
        if all_pages:
            raw_indexes = range(len(pages))
        elif page_indexes:
            raw_indexes = [int(i) for i in page_indexes]
        else:
            raw_indexes = [int(page_index)]
        # 越界页直接丢掉，别让整批插入失败
        indexes = [i for i in raw_indexes if 0 <= i < len(pages)]
        if not indexes:
            raise CoreError("目标页面不存在")

        # 逐页各生成一份元素（重新取 id），避免多页共用同一批 id
        specs: list[dict] = []
        elements: list[dict] = []
        for index in indexes:
            elements = icon_catalog.build_elements(icon_id, px, py, size=size, color=color,
                                                   name=name, make_id=projects_mod.new_id)
            for element in elements:
                specs.append({"op": "insert", "element": element, "pageIndexes": [index]})
        result = act.apply_actions(manifest, specs, page_index=int(page_index))
        if result["errors"]:
            raise CoreError(result["errors"][0])
        return {
            "changed": result["changed"],
            "icon": {"id": icon_id, "label": icon.get("label"), "w": w, "h": h,
                     "multi": bool(icon.get("multi")), "elements": len(elements)},
            "pageCount": len(pages),
        }

    root, _m, extra = mutate(path, mut)
    return {"path": str(root), **extra}


# ---------------------------------------------------------------- 类型知识（给 agent 看）


def element_types() -> list[dict]:
    """列出所有可插入的元素类型及其默认值 / 专用写法（modelNote）。

    通用 agent 直接写 insert 的 element JSON 时，先读这里，避免猜字段名。
    """
    schema = element_schema.load_schema() or {}
    out = []
    for name, spec in (schema.get("types") or {}).items():
        out.append({
            "type": name,
            "label": spec.get("label") or name,
            "defaultSize": {"w": spec.get("w"), "h": spec.get("h")},
            "modelNote": str(spec.get("modelNote") or "").strip(),
        })
    return sorted(out, key=lambda x: x["type"])
