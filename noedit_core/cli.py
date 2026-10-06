"""命令行入口：把 noedit_core.api 包一层，方便 shell / agent 直接调用。

用法示例（在 noedit_core 目录下）：
    python main.py serve --project D:\\demo          # 浏览器打开 http://127.0.0.1:8760/ 预览/编辑
    python main.py create "我的演示" --dir D:\\demo
    python main.py insert <工程目录> --json "{\"type\":\"text\",\"props\":{\"text\":\"标题\"}}"
    python main.py update <工程目录> --id el_ab12 --props "{\"style.fontSize\":40}"
    python main.py icon-search arrow                      # 搜矢量图标
    python main.py icon-insert <工程目录> mxgraph.arrows.arrow_down --x 120 --y 80
    python main.py export <工程目录> --fmt pptx

除 serve（常驻，启动本地 UI 服务）外，其余子命令都把结果以 JSON 打印到 stdout；
出错时打印错误并返回非 0 退出码。
"""

from __future__ import annotations

import argparse
import json
import sys

from . import api


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _load_json(raw: str, what: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{what} 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{what} 必须是 JSON 对象")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noedit_core", description="NoEdit Core 命令行")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="新建工程")
    c.add_argument("name")
    c.add_argument("--dir", required=True, help="父目录")
    c.add_argument("--preset", default="ppt-16:9")
    c.add_argument("--type", default="ppt")

    o = sub.add_parser("open", help="打开工程（概要 + 大纲）")
    o.add_argument("path")

    sub.add_parser("types", help="列出可插入的元素类型与专用写法")

    pg = sub.add_parser("pages", help="列出所有页")
    pg.add_argument("path")

    ap = sub.add_parser("add-page", help="新增一页")
    ap.add_argument("path")
    ap.add_argument("--index", type=int, default=-1)
    ap.add_argument("--name", default="")

    el = sub.add_parser("elements", help="列出元素")
    el.add_argument("path")
    el.add_argument("--page", type=int, default=-1)
    el.add_argument("--full", action="store_true")

    ins = sub.add_parser("insert", help="插入元素")
    ins.add_argument("path")
    ins.add_argument("--json", required=True, help="元素 JSON")
    ins.add_argument("--page", type=int, default=0)

    up = sub.add_parser("update", help="修改元素")
    up.add_argument("path")
    up.add_argument("--props", required=True, help="点号路径的 JSON，如 {\"props.text\":\"新\"}")
    up.add_argument("--id", default="")
    up.add_argument("--match", default="", help="按描述定位的 JSON")
    up.add_argument("--page", type=int, default=0)

    dl = sub.add_parser("delete", help="删除元素")
    dl.add_argument("path")
    dl.add_argument("--id", default="")
    dl.add_argument("--match", default="")
    dl.add_argument("--page", type=int, default=0)

    ro = sub.add_parser("reorder", help="调整层级")
    ro.add_argument("path")
    ro.add_argument("--id", default="")
    ro.add_argument("--match", default="")
    ro.add_argument("--index", type=int, default=-1)
    ro.add_argument("--front", action="store_true")
    ro.add_argument("--back", action="store_true")
    ro.add_argument("--page", type=int, default=0)

    aa = sub.add_parser("asset-add", help="导入工程内本地素材")
    aa.add_argument("path")
    aa.add_argument("files", nargs="+")

    al = sub.add_parser("assets", help="列出工程内素材")
    al.add_argument("path")

    ex = sub.add_parser("export", help="导出")
    ex.add_argument("path")
    ex.add_argument("--fmt", default="pptx", choices=["html", "pdf", "pptx", "png", "svg"])
    ex.add_argument("--out", default="")
    ex.add_argument("--pages", default="")
    ex.add_argument("--dpi", type=int, default=300)
    ex.add_argument("--transparent", action="store_true")
    ex.add_argument("--no-scene-gif", action="store_true",
                    help="导出 pptx 时不抓帧内嵌微场景 GIF（只留封面帧）")

    sl = sub.add_parser("scene-libs", help="列出微场景库及本地缓存状态")
    sl.add_argument("--json", action="store_true", help="保留此参数以便统一用法（结果本就是 JSON）")

    sa = sub.add_parser("scene-lib-add", help="下载并缓存微场景库（留空 = 全部）")
    sa.add_argument("id", nargs="?", default="")

    sr = sub.add_parser("scene-lib-remove", help="删除本地缓存的微场景库")
    sr.add_argument("id")

    sg = sub.add_parser("scene-gif", help="把一个微场景导出成 GIF（无头浏览器抓帧 + 合成）")
    sg.add_argument("path")
    sg.add_argument("--id", default="")
    sg.add_argument("--match", default="", help="按描述定位的 JSON，如 {\"name\":\"标题场景\"}")
    sg.add_argument("--page", type=int, default=0)
    sg.add_argument("--fps", type=int, default=12)
    sg.add_argument("--width", type=float, default=0)
    sg.add_argument("--scale", type=float, default=2.0)
    sg.add_argument("--name", default="")
    sg.add_argument("--out", default="")
    sg.add_argument("--opaque", action="store_true", help="不透明背景（默认透明）")

    ig = sub.add_parser("icon-groups", help="列出矢量图标分组")
    il = sub.add_parser("icon-list", help="列出某分组的矢量图标")
    il.add_argument("group", help="分组 id（先 icon-groups 看有哪些）")
    il.add_argument("--limit", type=int, default=200)

    isr = sub.add_parser("icon-search", help="按关键词搜矢量图标")
    isr.add_argument("keyword", nargs="?", default="")
    isr.add_argument("--group", default="")
    isr.add_argument("--limit", type=int, default=40)

    ii = sub.add_parser("icon-insert", help="插入矢量图标（生成可编辑的 path 元素）")
    ii.add_argument("path")
    ii.add_argument("icon_id", help="图标 id（先 icon-search 找）")
    ii.add_argument("--x", type=int, default=None)
    ii.add_argument("--y", type=int, default=None)
    ii.add_argument("--size", type=int, default=150, help="元素框长边像素")
    ii.add_argument("--color", default="#2f6fed")
    ii.add_argument("--name", default="")
    ii.add_argument("--page", type=int, default=0)

    sv = sub.add_parser("serve", help="启动本地 UI 服务（浏览器打开地址即可预览/编辑工程）")
    sv.add_argument("--host", default="127.0.0.1", help="监听地址（只给本机用就别改）")
    sv.add_argument("--port", type=int, default=8760)
    sv.add_argument("--project", default="", help="启动时直接打开的工程目录（可省，进页面再开）")
    sv.add_argument("--open", action="store_true", help="启动后自动用默认浏览器打开")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        from . import server  # 延迟导入：不起服务就不碰 http.server
        return server.run(host=args.host, port=args.port, project=args.project,
                          open_browser=args.open)
    try:
        if args.cmd == "create":
            _dump(api.create_project(args.name, args.dir, preset=args.preset, ptype=getattr(args, "type", "ppt")))
        elif args.cmd == "open":
            _dump(api.open_project(args.path))
        elif args.cmd == "types":
            _dump(api.element_types())
        elif args.cmd == "pages":
            _dump(api.list_pages(args.path))
        elif args.cmd == "add-page":
            _dump(api.add_page(args.path, index=args.index, name=args.name))
        elif args.cmd == "elements":
            _dump(api.list_elements(args.path, page_index=args.page, full=args.full))
        elif args.cmd == "insert":
            _dump(api.insert(args.path, _load_json(args.json, "element"), page_index=args.page))
        elif args.cmd == "update":
            _dump(api.update(args.path, _load_json(args.props, "props"),
                             element_id=args.id, match=_load_json(args.match, "match") if args.match else None,
                             page_index=args.page))
        elif args.cmd == "delete":
            _dump(api.delete(args.path,
                             element_id=args.id,
                             match=_load_json(args.match, "match") if args.match else None,
                             page_index=args.page))
        elif args.cmd == "reorder":
            _dump(api.reorder(args.path, element_id=args.id,
                              match=_load_json(args.match, "match") if args.match else None,
                              index=args.index, to_front=args.front, to_back=args.back,
                              page_index=args.page))
        elif args.cmd == "asset-add":
            _dump(api.import_asset(args.path, args.files))
        elif args.cmd == "assets":
            _dump(api.list_assets(args.path))
        elif args.cmd == "export":
            opts = {}
            if args.fmt in ("png", "svg"):
                opts = {"pages": args.pages, "dpi": args.dpi, "transparent": args.transparent}
            if args.fmt == "pptx" and args.no_scene_gif:
                opts["scene_gifs"] = False
            _dump(api.export(args.path, fmt=args.fmt, out_dir=args.out, **opts))
        elif args.cmd == "scene-libs":
            _dump(api.scene_libs())
        elif args.cmd == "scene-lib-add":
            _dump(api.install_scene_lib(args.id))
        elif args.cmd == "scene-lib-remove":
            _dump(api.remove_scene_lib(args.id))
        elif args.cmd == "scene-gif":
            _dump(api.export_scene_gif(
                args.path, element_id=args.id,
                match=_load_json(args.match, "match") if args.match else None,
                page_index=args.page, out_dir=args.out, fps=args.fps, width=args.width,
                scale=args.scale, name=args.name, transparent=not args.opaque,
            ))
        elif args.cmd == "icon-groups":
            _dump(api.icon_groups())
        elif args.cmd == "icon-list":
            _dump(api.icon_list(args.group, limit=args.limit))
        elif args.cmd == "icon-search":
            _dump(api.icon_search(args.keyword, group=args.group, limit=args.limit))
        elif args.cmd == "icon-insert":
            _dump(api.icon_insert(args.path, args.icon_id, x=args.x, y=args.y, size=args.size,
                                  color=args.color, name=args.name, page_index=args.page))
        else:  # pragma: no cover - argparse 已保证
            return 2
    except api.CoreError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
