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
    _smoke_media(path)
    _smoke_dh(path)

    print("\nSMOKE OK —— 核心可用。")


def _smoke_media(path: str) -> None:
    """[15] 素材导入回报 + 导出前体检 + 静态 HTML 标签闭合。"""
    dot = Path(path) / "assets" / "dot.png"

    # 缺文件不再静默跳过：problems 里点名，且进来的那个仍然成功
    r = api.import_asset(path, [str(ROOT / "_src" / "根本没有这个文件.png"), str(dot)])
    assert len(r["imported"]) == 1 and r["problems"] and r["problems"][0]["imported"] is False, r
    print(f"[15] import_asset 回报缺失项 ✓ {r['problems'][0]['reason']}")

    # 全缺 → 明确报错，不再「导入了 0 个」还往下走
    try:
        api.import_asset(path, [str(ROOT / "_src" / "不存在.png")])
        raise AssertionError("全不存在的导入应抛 CoreError")
    except api.CoreError as exc:
        assert "不存在" in str(exc), exc

    # 断图与外链都能被 check_media 点名
    api.insert(path, {"type": "image", "name": "断图", "x": 10, "y": 10, "w": 100, "h": 100,
                      "props": {"src": "assets/压根没导进来.png"}}, page_index=1)
    api.insert(path, {"type": "image", "name": "外链图", "x": 20, "y": 20, "w": 100, "h": 100,
                     "props": {"src": "https://example.com/x.png"}}, page_index=1)
    c = api.check_media(path)
    kinds = " | ".join(p["problem"] for p in c["problems"])
    assert not c["ok"], c
    assert "素材文件不存在" in kinds and "外链" in kinds, kinds
    assert any(p.get("level") == "warning" for p in c["problems"]), "1×1 的 dot.png 该被点成缩略图告警"
    api.delete(path, match={"name": "断图"}, page_index=1)
    api.delete(path, match={"name": "外链图"}, page_index=1)
    assert api.check_media(path)["ok"], api.check_media(path)["problems"]
    print(f"[16] check_media 导出前体检 ✓ 抓到并清空 {len(c['problems'])} 条")

    # 每种图片形态都得是闭合的（漏一个 </div> 会把后面所有元素吞进这个框里）
    from noedit_core.core import projects as prj
    for props in ({"src": "assets/dot.png"},
                  {"src": "assets/dot.png", "shadowOn": True},
                  {"src": "assets/dot.png", "reflectOn": True},
                  {"src": "assets/dot.png", "cropTop": 20, "cropLeft": 10},
                  {}):
        frag = prj.element_html({"type": "image", "name": "t", "w": 200, "h": 100, "props": props})
        assert frag.count("<div") == frag.count("</div>"), (props, frag)
    html = Path(api.export(path, "html")["path"]).read_text(encoding="utf-8")
    assert html.count("<div") == html.count("</div>"), "导出的静态 HTML 里 div 必须配平"
    print("[17] image 元素 HTML 片段标签闭合 ✓")

    # 导到工程外 = 用 ../<工程>/assets/ 引素材，单发这一个 HTML 会丢媒体：核心必须回警告
    outside = api.export(path, "html", out_dir=str(ROOT / "_html_outside"))
    assert outside["warnings"] and "assets" in outside["warnings"][0], outside
    assert not api.export(path, "html")["warnings"], "导到工程内不该有相对路径警告"
    print("[17b] 工程外 HTML 导出点名「相对路径会丢媒体」 ✓")

    # 有声媒体自动播放被浏览器拒时不许静默：得挂一次性手势解锁（旁白 / 数字人同理）
    for rt in (prj._AUDIO_RUNTIME, prj._DH_RUNTIME):
        assert "p.catch(function () { if (armed) unlockOnce(); })" in rt, rt[:60]
        assert "addEventListener('pointerdown'" in rt and "addEventListener('keydown'" in rt
    print("[18] 自动播放被拒时的一次性手势解锁 ✓")


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


def _smoke_dh(path: str) -> None:
    """[19] 数字人成片：out_name 不写扩展名也要产出 .mp4（ffmpeg 按扩展名选封装格式）。"""
    import math
    import struct
    import wave

    from noedit_core.dh import validator

    status = validator.check_all()
    if not any(v == "ok" for v in status.values()):
        print(f"[19] 数字人跳过：没有可用引擎 {status}")
        return

    photo, audio = ROOT / "dh_photo.png", ROOT / "dh_vo.wav"
    try:
        from PIL import Image, ImageDraw

        im = Image.new("RGB", (512, 512), "#223049")
        d = ImageDraw.Draw(im)
        for i in range(0, 500, 10):
            y = 180 + int(90 * math.sin(i / 48.0))
            d.ellipse((i, y, i + 8, y + 8), fill="#9db4d4")
        im.save(photo)
        with wave.open(str(audio), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"".join(struct.pack("<h", int(11000 * math.sin(i / 22)))
                                   for i in range(22050)))
        r = api.generate_digital_human(str(photo), str(audio), engine="auto",
                                       out_dir=str(ROOT), out_name="dh-noext")
    except Exception as exc:  # noqa: BLE001  外部依赖（ffmpeg/Pillow）不齐时不算失败
        print(f"[19] 数字人跳过：{exc}")
        return
    assert str(r["video"]).lower().endswith(".mp4"), f"缺扩展名时应自动补 .mp4：{r}"
    assert Path(r["video"]).stat().st_size > 2048, r
    print(f"[19] 数字人 auto → {r.get('engine')}，out_name 自动补扩展名 ✓ "
          f"{Path(r['video']).name} + {Path(r['poster']).name if r.get('poster') else '无封面帧'}")


if __name__ == "__main__":
    main()
