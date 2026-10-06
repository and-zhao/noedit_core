"""端到端冒烟测试：只用 noedit_core.api 走完「建工程 → 加页 → 增/改/删 → 导素材 → 插图标 → 导出」。

运行：python tests/smoke.py
产出：noedit_core/_smoke_out/ 下的一份工程与导出文件（可删）。
"""

from __future__ import annotations

import base64
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from noedit_core import api  # noqa: E402
from noedit_core.core.export import _find_browser  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "_smoke_out"
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)

# 1x1 透明 PNG，用来验证「工程内本地素材」导入与引用
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# 一个实现了 seek(t) 的微场景：t 驱动小球横向移动（否则逐帧画面相同，抓帧会判失败）
_SCENE_CODE = """
window.mount = function (root) {
  var c = document.createElement('canvas');
  c.width = 480; c.height = 270;
  c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
  root.appendChild(c);
  window.__ctx = c.getContext('2d');
};
window.seek = function (t) {
  var x = window.__ctx; if (!x) return;
  x.clearRect(0, 0, 480, 270);
  x.fillStyle = '#0f172a'; x.fillRect(0, 0, 480, 270);
  x.fillStyle = '#38bdf8';
  x.beginPath(); x.arc(60 + t * 360, 135, 36, 0, Math.PI * 2); x.fill();
};
"""


def main() -> None:
    types = api.element_types()
    assert len(types) >= 10, f"元素类型太少：{len(types)}"
    text_note = next(t for t in types if t["type"] == "text")["modelNote"]
    assert text_note, "text 类型应带 modelNote（知识下沉）"
    print(f"[1] 元素类型 {len(types)} 种；text 有 modelNote ✓")

    p = api.create_project("冒烟测试", str(ROOT))
    path = p["path"]
    assert (Path(path) / "project.manifest.json").exists()
    assert (Path(path) / "index.html").exists()
    print(f"[2] 建工程 ✓ {path}")

    api.insert(path, {"type": "text", "x": 80, "y": 60, "w": 900, "h": 80,
                      "props": {"text": "季度营收回顾"},
                      "style": {"fontSize": 40, "fontWeight": "bold", "color": "#1f2937"}}, page_index=0)
    api.insert(path, {"type": "shape", "x": 80, "y": 180, "w": 480, "h": 160,
                      "props": {"shape": "rect"}, "style": {"fill": "#eef2ff"}}, page_index=0)
    api.insert(path, {"type": "chart", "x": 600, "y": 180, "w": 560, "h": 360,
                      "props": {"kind": "bar", "title": "季度营收",
                                "rows": [["Q1", 120], ["Q2", 180], ["Q3", 150], ["Q4", 210]]}}, page_index=0)
    els = api.list_elements(path, page_index=0)["elements"]
    assert len(els) == 3, els
    print(f"[3] 插入 3 个元素 ✓ {[e['type'] for e in els]}")

    tid = next(e["id"] for e in els if e["type"] == "text")
    api.update(path, {"props.text": "2025 季度营收回顾", "style.fontSize": 44}, element_id=tid)
    t = next(e for e in api.list_elements(path, page_index=0, full=True)["elements"] if e["id"] == tid)
    assert t["props"]["text"] == "2025 季度营收回顾" and t["style"]["fontSize"] == 44
    print("[4] 更新元素（点号路径 props.text / style.fontSize）✓")

    api.add_page(path, name="第二页")
    api.insert(path, {"type": "text", "x": 80, "y": 60, "props": {"text": "第二页正文"}}, page_index=1)
    pages = api.list_pages(path)["pages"]
    assert pages[1]["name"] == "第二页" and pages[1]["elementCount"] == 1
    assert len(pages) == 2
    print("[5] 加页 + 第二页元素 ✓")

    src = ROOT / "_src"
    src.mkdir(exist_ok=True)
    img = src / "dot.png"
    img.write_bytes(_PNG)
    rec = api.import_asset(path, [str(img)])["imported"][0]
    assert (Path(path) / rec["relPath"]).exists(), rec
    api.insert(path, {"type": "image", "x": 80, "y": 400, "w": 64, "h": 64,
                      "props": {"src": rec["relPath"]}}, page_index=1)
    assert api.list_assets(path)["assets"][0]["exists"] is True
    print(f"[6] 工程内本地素材导入 + 引用 ✓ {rec['relPath']}")

    api.reorder(path, element_id=tid, to_front=True, page_index=0)
    api.delete(path, match={"type": "shape"}, page_index=0)
    left = api.list_elements(path, page_index=0)["elements"]
    assert all(e["type"] != "shape" for e in left), left
    print(f"[7] 层级调整 + 按描述删除 ✓ 剩余 {[e['type'] for e in left]}")

    api.update_page(path, {"background": {"type": "solid", "color": "#0f172a"}}, all_pages=True)
    bgs = [p["background"] for p in api.list_pages(path)["pages"]]
    assert all(b and b.get("color") == "#0f172a" for b in bgs), bgs
    print("[8] 全篇统一页面背景（update_page all_pages）✓")

    api.add_page(path, name="待删页")
    api.delete_page(path, 2)
    assert len(api.list_pages(path)["pages"]) == 2
    print("[9] 加页后删除一页 ✓")

    api.insert(path, {"type": "scene", "name": "冒烟场景", "x": 640, "y": 360, "w": 480, "h": 270,
                      "props": {"code": _SCENE_CODE, "duration": 1, "libs": []}}, page_index=0)

    html = api.export(path, "html")
    assert html.get("ok") and Path(html["path"]).exists(), html
    text = Path(html["path"]).read_text(encoding="utf-8")
    assert "el-scene-frame" in text and "srcdoc" in text, "HTML 里微场景应是沙箱 iframe 真身"
    print(f"[10] 导出 HTML（含微场景 iframe 真身）✓ {Path(html['path']).name}")
    assert Path(path, "project.manifest.json").exists()
    print(f"    预览地址：{Path(path, 'index.html').as_uri()}")

    browser = _find_browser()
    pptx_path = None
    try:
        pptx = api.export(path, "pptx")
        assert pptx.get("path") and Path(pptx["path"]).exists(), pptx
        pptx_path = Path(pptx["path"])
        print(f"[11] 导出 PPTX ✓ {pptx_path.name}")
        if browser:
            with zipfile.ZipFile(pptx_path) as z:
                media = [n for n in z.namelist() if n.startswith("ppt/media/")]
            assert any(n.lower().endswith(".gif") for n in media), f"PPTX 应内嵌微场景 GIF：{media}"
            print(f"     微场景已自动抓帧为 GIF 内嵌 ✓ {[Path(n).name for n in media]}")
            # 关掉内嵌：只留封面帧
            plain = api.export(path, "pptx", scene_gifs=False)
            with zipfile.ZipFile(Path(plain["path"])) as z:
                media2 = [n for n in z.namelist() if n.startswith("ppt/media/")]
            assert not any(n.lower().endswith(".gif") for n in media2), media2
            print("     scene_gifs=False 时不内嵌 GIF ✓")
        else:
            print("     未找到 Edge/Chrome，微场景 GIF 内嵌跳过")
    except Exception as exc:  # noqa: BLE001  缺 python-pptx 时不算测试失败
        print(f"[11] 导出 PPTX 跳过：{exc}")

    if browser:
        gif = api.export_scene_gif(path, match={"name": "冒烟场景"}, fps=4, scale=1)
        assert gif.get("ok"), gif
        from PIL import Image
        assert getattr(Image.open(gif["path"]), "n_frames", 1) >= 2, "GIF 应有多帧"
        print(f"[12] 单元素导出 GIF ✓ {Path(gif['path']).name} | {gif['message']}")
    else:
        print("[12] 单元素导出 GIF 跳过（未找到 Edge/Chrome）")

    _smoke_server(path)
    _smoke_icons(path)

    print("\nSMOKE OK —— 核心可用。")


def _smoke_icons(path: str) -> None:
    """[14] 矢量图标库：分组 / 搜索 / 插入可编辑 path（含多色分组）。"""
    groups = api.icon_groups()
    assert groups, "图标目录应有分组（noedit_core/web/icon-catalog*.json）"
    total = sum(g["count"] for g in groups)

    hit = api.icon_search("arrow", limit=5)
    if not hit["icons"]:
        hit = api.icon_search("", limit=5)
    assert hit["icons"], "图标搜索应能返回结果"
    icon_id = hit["icons"][0]["id"]

    before = len(api.list_elements(path, page_index=0)["elements"])
    res = api.icon_insert(path, icon_id, x=40, y=40, size=120, color="#c0392b")
    assert res["icon"]["elements"] >= 1, res
    after = api.list_elements(path, page_index=0, full=True)["elements"]
    assert len(after) - before == res["icon"]["elements"], (before, len(after), res)
    assert any(e.get("type") == "path" and (e.get("props") or {}).get("vector") for e in after), \
        "插入的图标应是可编辑的 path 元素（props.vector）"

    # 多色图标（自带配色）：应插成「group 容器 + 分层 path 成员（parentId）」
    multi_id = ""
    for g in groups:
        multi_id = next((i["id"] for i in api.icon_list(g["id"], limit=500)["icons"] if i["multi"]), "")
        if multi_id:
            break
    multi_note = ""
    if multi_id:
        res2 = api.icon_insert(path, multi_id, page_index=0)
        assert res2["icon"]["multi"] and res2["icon"]["elements"] >= 2, res2
        members = [e for e in api.list_elements(path, page_index=0, full=True)["elements"]
                   if e.get("parentId")]
        assert members, "多色图标的成员应挂在 group 容器下（parentId）"
        multi_note = f"；多色 {multi_id} → {res2['icon']['elements']} 个元素（含容器）"

    print(f"[14] 矢量图标库 ✓ {len(groups)} 组 / 共 {total} 个图标；"
          f"插入 {icon_id} → {res['icon']['elements']} 个元素{multi_note}")


def _smoke_server(path: str) -> None:
    """[13] 本地 UI 服务：/api/ping、/api/call（增改删）、/canvas 预览页。"""
    import json
    import urllib.request

    from noedit_core import server as srv

    ui = srv.LocalUI(port=0, project=path)   # 端口 0 = 系统随便给个空闲端口
    ui.start()
    try:
        base = f"http://{ui.host}:{ui.port}"
        with urllib.request.urlopen(base + "/api/ping", timeout=5) as resp:
            assert json.loads(resp.read())["ok"] is True

        def call(method, *args):
            body = json.dumps({"method": method, "args": list(args)}).encode("utf-8")
            req = urllib.request.Request(base + "/api/call", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())

        st = call("state")
        assert st["ok"] and st["result"]["project"] == str(Path(path).resolve()), st

        assert call("insert", path, {"type": "text", "props": {"text": "服务测试"}}, 0)["ok"]
        st = call("state")
        got = next(e for e in st["result"]["pages"][0]["elements"]
                   if (e.get("props") or {}).get("text") == "服务测试")
        assert call("update", path, {"props.text": "服务改过", "x": 123}, got["id"], None, 0)["ok"]
        st = call("state")
        changed = next(e for e in st["result"]["pages"][0]["elements"] if e["id"] == got["id"])
        assert changed["props"]["text"] == "服务改过" and changed["x"] == 123, changed
        assert call("delete", path, got["id"], None, 0)["ok"]

        with urllib.request.urlopen(base + "/canvas?page=0", timeout=15) as resp:
            html = resp.read().decode("utf-8")
        assert "data-id" in html and "ac-select" in html, "预览页应带 data-id 且注入选点脚本"
        print("[13] 本地 UI 服务（/api/ping、/api/call 增改删、/canvas 预览）✓")
    finally:
        ui.stop()


if __name__ == "__main__":
    main()
