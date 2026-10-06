"""本地 HTTP 服务：把 noedit_core.api 暴露成「浏览器打开地址就能用」的后端。

用途（只监听回环地址，不对外、不访问网络）：
- 提供内置 UI（noedit_core/ui/）、仓库配图（img/，含 logo）与工程素材（/proj/<token>/…）
- 提供 /canvas 预览页：直接用「导出用的静态渲染器」逐页渲染当前工程，浏览即所见即所得
- 提供 /api/call：一行 JSON（{method, args}）打到 noedit_core.api 上，UI 的所有编辑都走它

预览为什么不用另写渲染器：core/projects.py 的 render_page_html() 就是 HTML / PDF / PPTX
三路导出共用的那一份渲染实现，元素上还自带 data-id。这里复用它，预览与导出零漂移；
点选只是往里注入一小段脚本，把点击的 data-id 用 postMessage 抛回父窗口。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import api
from .core import assets as assets_mod
from .core import projects as projects_mod
from .core.errors import CoreError
from .core.paths import (APP_NAME, APP_ROOT, DATA_DIR, MANIFEST_NAME, UI_FILE,
                         VERSION, WEB_DIR, atomic_write_text, ensure_dir,
                         projects_root)
from .core.store import mutate, project_root, read_manifest

UI_DIR: Path = Path(__file__).resolve().parent / "ui"
# 仓库根的 img/（README 配图、logo）。内置 UI 的顶栏 logo 也引用它，避免同一份图放两处。
IMG_DIR: Path = Path(__file__).resolve().parent.parent / "img"

# /api/call 的请求体上限。本机单用户，导入素材的 base64 可能偏大，给到 64MB。
MAX_BODY = 64 * 1024 * 1024

# 本机注册表里 .svg 常被登记成 "image/svg"，浏览器只认 "image/svg+xml"（否则 logo 全空）。
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
for _ext, _ctype in (
    (".mp4", "video/mp4"), (".m4v", "video/mp4"), (".webm", "video/webm"),
    (".ogv", "video/ogg"), (".mov", "video/quicktime"), (".m4a", "audio/mp4"),
    (".mp3", "audio/mpeg"), (".wav", "audio/wav"), (".ogg", "audio/ogg"),
):
    mimetypes.add_type(_ctype, _ext)


# 注入到 /canvas 预览页里的一小段脚本：点选元素 → postMessage 回父窗口；父窗口反向高亮。
_SELECT_JS = r"""
<script>
(function () {
  var BOX = '__ac_sel_box';
  function box() { return document.getElementById(BOX); }
  function clear() { var b = box(); if (b) b.remove(); }
  function draw(el) {
    clear();
    var r = el.getBoundingClientRect();
    var d = document.createElement('div');
    d.id = BOX;
    d.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483647;'
      + 'border:1.5px solid #2f6fed;box-shadow:0 0 0 1px rgba(255,255,255,.7) inset;'
      + 'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px;';
    document.body.appendChild(d);
  }
  function node(id) { return id ? document.querySelector('[data-id="' + id + '"]') : null; }
  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-id]') : null;
    var id = t && t.hasAttribute('data-id') ? t.getAttribute('data-id') : '';
    if (id) { draw(t); } else { clear(); }
    parent.postMessage({ type: 'ac-select', id: id }, '*');
  }, true);
  document.addEventListener('mousedown', function (e) {
    if (e.target && e.target.closest && e.target.closest('a')) e.preventDefault();
  }, true);
  window.addEventListener('message', function (e) {
    var m = e.data || {};
    if (m.type !== 'ac-highlight') return;
    if (!m.id) { clear(); return; }
    var el = node(m.id);
    if (el) draw(el); else clear();
  });
  parent.postMessage({ type: 'ac-ready' }, '*');
})();
</script>
"""


def _inject_select(html_text: str) -> str:
    """把选点脚本插到 </body> 前（找不到就追加在末尾）。"""
    return html_text.replace("</body>", _SELECT_JS + "</body>") if "</body>" in html_text \
        else html_text + _SELECT_JS


def _decode_data_url(data_url: str) -> bytes:
    """拆掉 dataURL 的 `data:*;base64,` 前缀并解出字节。"""
    text = str(data_url or "")
    if text.startswith("data:"):
        _head, _sep, text = text.partition(",")
    try:
        return base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise CoreError(f"素材数据不是合法的 base64：{exc}") from exc


class _Handler(BaseHTTPRequestHandler):
    server_version = "NoEditCore/0.2"
    protocol_version = "HTTP/1.1"
    timeout = 20

    def log_message(self, fmt, *args):  # 关掉 stdout 噪音
        return

    def handle_one_request(self):  # noqa: N802
        # 长连接下对面随时可能掐断（取消请求 / 丢弃空闲连接），那不是错误。
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    # ---------------------------------------------------------- 发送
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_text(self, text: str, ctype: str = "text/html; charset=utf-8", status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range", "")
        start, end, partial = 0, size - 1, False
        if range_header.startswith("bytes="):
            spec = range_header[len("bytes="):].split(",")[0].strip()
            try:
                s, _, e = spec.partition("-")
                if s:
                    start = int(s)
                if e:
                    end = int(e)
                if not s and e:
                    start, end = max(0, size - int(e)), size - 1
                if start <= end < size:
                    partial = True
                else:
                    start, end, partial = 0, size - 1, False
            except ValueError:
                start, end, partial = 0, size - 1, False
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    # ---------------------------------------------------------- 工具
    @staticmethod
    def _resolve_under(root: Path, rel: str) -> Path | None:
        try:
            target = (root / unquote(rel).lstrip("/")).resolve()
            target.relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        return target if target.is_file() else None

    # ---------------------------------------------------------- 路由
    def do_GET(self):  # noqa: N802
        self._route()

    def do_HEAD(self):  # noqa: N802
        self._route()

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/call":
            self._route_call()
            return
        if path == "/api/ui/open":
            self._route_ui_open()
            return
        self._send_json({"ok": False, "message": f"该路径不支持 POST：{path}"}, 405)

    def _route(self) -> None:
        ctx: "LocalUI" = self.server.ctx  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ping":
            self._send_json({"ok": True, "app": APP_NAME})
            return
        if path == "/api/ui/current":
            self._send_json({"ok": True, "result": ctx.ui_current()})
            return
        if path == "/canvas":
            self._route_canvas(ctx, parse_qs(parsed.query))
            return
        if path.startswith("/proj/"):
            rest = path[len("/proj/"):]
            token, _, rel = rest.partition("/")
            root = ctx.project_dir(token)
            if root is None:
                self._send_json({"ok": False, "message": "工程未注册"}, 404)
                return
            target = self._resolve_under(root, rel)
            if target is None:
                self._send_json({"ok": False, "message": "文件不存在"}, 404)
                return
            self._send_file(target)
            return
        if path.startswith("/ui/"):
            target = self._resolve_under(UI_DIR, path[len("/ui/"):])
            if target is None:
                self._send_json({"ok": False, "message": "资源不存在"}, 404)
                return
            self._send_file(target)
            return
        if path.startswith("/img/"):
            target = self._resolve_under(IMG_DIR, path[len("/img/"):])
            if target is None:
                self._send_json({"ok": False, "message": "资源不存在"}, 404)
                return
            self._send_file(target)
            return
        if path.startswith("/web/"):
            target = self._resolve_under(WEB_DIR, path[len("/web/"):])
            if target is None:
                self._send_json({"ok": False, "message": "资源不存在"}, 404)
                return
            self._send_file(target)
            return

        if path in ("", "/"):
            index = UI_DIR / "index.html"
            if not index.is_file():
                self._send_text("UI 文件缺失（noedit_core/ui/index.html）", status=500)
                return
            self._send_text(index.read_text(encoding="utf-8"))
            return
        self._send_json({"ok": False, "message": f"未知路径：{path}"}, 404)

    def _route_canvas(self, ctx: "LocalUI", query: dict) -> None:
        root = ctx.project_dir(ctx.current_token) if ctx.current_token else None
        if root is None:
            self._send_text("<!doctype html><meta charset='utf-8'>未打开工程", status=200)
            return
        try:
            page = int((query.get("page") or ["0"])[0])
        except ValueError:
            page = 0
        try:
            manifest = read_manifest(root)
            html_text, _cw, _ch = projects_mod.render_page_html(
                manifest, page_index=page, root_prefix=f"/proj/{ctx.current_token}/"
            )
        except CoreError as exc:
            self._send_text(f"<!doctype html><meta charset='utf-8'>渲染失败：{exc}", status=200)
            return
        self._send_text(_inject_select(html_text))

    def _route_call(self) -> None:
        ctx: "LocalUI" = self.server.ctx  # type: ignore[attr-defined]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json({"ok": False, "message": "Content-Length 不是数字"}, 400)
            return
        if length <= 0 or length > MAX_BODY:
            self._send_json({"ok": False, "message": f"请求体为空或过大（上限 {MAX_BODY // 1024 // 1024} MB）"}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json({"ok": False, "message": f"请求体不是合法 JSON：{exc}"}, 400)
            return
        method = str(payload.get("method") or "")
        args = payload.get("args") or []
        if not isinstance(args, list):
            args = [args]
        try:
            result = ctx.dispatch(method, args)
            self._send_json({"ok": True, "result": result})
        except CoreError as exc:
            self._send_json({"ok": False, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 —— 兜底：别把栈丢回浏览器，收成一句可读中文
            self._send_json({"ok": False, "message": f"后端内部错误：{exc}"})

    def _route_ui_open(self) -> None:
        """把 UI 正在展示的工程切成目标工程（运行中直接换，不重启服务）。

        给外部 agent 用。接受两种传参：JSON 体 {"path": "..."}，
        或查询串 /api/ui/open?path=...（方便命令行直接打）。
        """
        ctx: "LocalUI" = self.server.ctx  # type: ignore[attr-defined]
        target = (parse_qs(urlparse(self.path).query).get("path") or [""])[0]
        if not target:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= MAX_BODY:
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    target = str((payload or {}).get("path") or "")
                except (ValueError, UnicodeDecodeError):
                    self._send_json({"ok": False, "message": "请求体不是合法 JSON"}, 400)
                    return
        try:
            self._send_json({"ok": True, "result": ctx.ui_open(target)})
        except CoreError as exc:
            self._send_json({"ok": False, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "message": f"后端内部错误：{exc}"})


SETTINGS_FILE: Path = DATA_DIR / "settings.json"


def _load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_settings(data: dict) -> None:
    ensure_dir(SETTINGS_FILE.parent)
    atomic_write_text(SETTINGS_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def _default_dir() -> Path:
    """界面用的「默认目录」：用户在落地页设过的优先，没设过就退回 paths.projects_root()。

    新建工程的父目录、目录树起点、导出落点都以它为准。
    """
    raw = str(_load_settings().get("defaultDir") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = APP_ROOT / p
        p = p.resolve()
        if p.is_dir():
            return p
    root = projects_root()
    try:
        # 默认目录可能还没建过（首次使用、目录刚随 skill 换位置），先建好，
        # 否则目录树展开到它时会因「目录不存在」整棵树报错。
        ensure_dir(root)
    except OSError:
        pass
    return root


def _get_settings() -> dict:
    raw = str(_load_settings().get("defaultDir") or "").strip()
    # custom=True 表示用户显式设过；没设过时界面不改变导出等既有行为。
    return {"defaultDir": str(_default_dir()), "custom": bool(raw)}


def _set_default_dir(path: str) -> dict:
    raw = (path or "").strip()
    if not raw:
        raise CoreError("默认目录不能为空")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = APP_ROOT / p
    p = p.resolve()
    if not p.is_dir():
        raise CoreError(f"目录不存在：{p}")
    data = _load_settings()
    data["defaultDir"] = str(p)
    try:
        _save_settings(data)
    except OSError as exc:
        raise CoreError(f"保存设置失败：{exc}") from exc
    return {"defaultDir": str(p)}


def _browse_dir(path: str = "") -> dict:
    """列出一个目录下的子目录，并标出其中哪些是工程。

    界面「打开工程」靠它做目录浏览：默认落在「默认目录」（见 _default_dir），
    点工程直接打开、点普通目录进入下一层。只读操作，不碰任何工程内容。
    """
    raw = (path or "").strip()
    target = Path(raw).expanduser() if raw else _default_dir()
    if not target.is_absolute():
        target = APP_ROOT / target
    target = target.resolve()
    if not target.is_dir():
        raise CoreError(f"目录不存在：{target}")

    def read_project(folder: Path) -> dict | None:
        manifest_file = folder / MANIFEST_NAME
        if not manifest_file.is_file():
            return None
        name, ptype, pages = folder.name, "", 0
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                name = data.get("name") or name
                ptype = data.get("type") or ""
                pages = len(data.get("pages") or [])
        except (OSError, json.JSONDecodeError):
            pass
        return {"name": name, "type": ptype, "pages": pages}

    entries = []
    try:
        children = list(target.iterdir())
    except OSError as exc:
        raise CoreError(f"读不了这个目录：{exc}") from exc
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        proj = read_project(child)
        entries.append({
            "name": child.name,
            "path": str(child),
            "isProject": proj is not None,
            "projectName": (proj or {}).get("name", ""),
            "type": (proj or {}).get("type", ""),
            "pages": (proj or {}).get("pages", 0),
        })
    entries.sort(key=lambda e: (not e["isProject"], e["name"].casefold()))

    current = read_project(target)
    return {
        "path": str(target),
        "parent": str(target.parent),
        "root": str(_default_dir()),
        "isProject": current is not None,
        "projectName": (current or {}).get("name", ""),
        "entries": entries,
    }


def _browse_roots() -> dict:
    """列出目录树的根节点，供界面画「文件夹树」。

    Windows 上是各盘符（C:\\、D:\\ …），其它平台退化成 /。
    顺带把「默认目录」带回去，让界面一开始就能展开并定位到它。
    """
    names: list[str] = []
    lister = getattr(os, "listdrives", None)  # Python 3.12+，仅 Windows 有
    if lister is not None:
        try:
            names = [str(n) for n in lister()]
        except OSError:
            names = []
    if not names:
        names = ["/"] if os.name != "nt" else []
    return {
        "roots": [{"name": n, "path": n} for n in names],
        "defaultDir": str(_default_dir()),
    }


class _Server(ThreadingHTTPServer):
    """accept 队列放大：前端一上来会并发取多个静态资源。"""

    request_queue_size = 128
    daemon_threads = True


class LocalUI:
    """本地 UI 服务。单进程单工程（本机单用户）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8760, project: str = ""):
        self.current_token: str = ""
        self._tokens: dict[str, Path] = {}
        self.httpd = _Server((host, port), _Handler)
        self.httpd.ctx = self  # type: ignore[attr-defined]
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]
        self._started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        if project:
            root = project_root(project)
            self.current_token = self.register(root)

    # ---------------------------------------------------------- 生命周期
    def start(self) -> None:
        self._thread.start()
        self._publish()

    def stop(self) -> None:
        self._unpublish()
        try:
            self.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- 服务发现
    def _publish(self) -> None:
        """把「本机 UI 在哪个端口、开的哪个工程」写到 data/ui.json。

        外部进程（agent / 脚本）读它就能找到正在跑的服务，再调 /api/ui/*。
        写盘失败不算致命（服务照常跑），只是外部找不到，所以吞掉异常。
        """
        root = self.project_dir(self.current_token)
        payload = {
            "app": APP_NAME,
            "version": VERSION,
            "host": self.host,
            "port": self.port,
            "url": self.url,
            "pid": os.getpid(),
            "project": str(root) if root else "",
            "startedAt": self._started_at,
        }
        try:
            atomic_write_text(UI_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError:
            pass

    def _unpublish(self) -> None:
        """退出时撤掉注册文件。只删自己那份（pid 对得上），别误删别的实例。"""
        try:
            data = json.loads(UI_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("pid") == os.getpid():
                UI_FILE.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    # ---------------------------------------------------------- 工程注册
    def register(self, root: Path) -> str:
        root = Path(root).resolve()
        token = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:16]
        self._tokens[token] = root
        return token

    def project_dir(self, token: str) -> Path | None:
        return self._tokens.get(token or "")

    def set_project(self, path: str) -> None:
        self.current_token = self.register(project_root(path))
        self._publish()  # 切换后同步注册文件里的 project 字段

    # ---------------------------------------------------------- 业务分发
    def dispatch(self, method: str, args: list):
        if method == "ping":
            return {"app": APP_NAME}
        if method == "open_project":
            res = api.open_project(str(args[0]))
            self.set_project(res["path"])
            return self.state()
        if method == "create_project":
            res = api.create_project(*args)
            self.set_project(res["path"])
            return self.state()
        if method == "close_project":
            self.current_token = ""
            return {"project": None}
        if method == "state":
            return self.state()
        if method == "browse_dir":
            return _browse_dir(str(args[0]) if args else "")
        if method == "browse_roots":
            return _browse_roots()
        if method == "get_settings":
            return _get_settings()
        if method == "set_default_dir":
            return _set_default_dir(str(args[0]) if args else "")
        if method == "upload_asset":
            return self.upload_asset(str(args[0]), str(args[1]))
        fn = _DIRECT.get(method)
        if fn is None:
            raise CoreError(f"未知后端方法：{method}")
        return fn(*args)

    def upload_asset(self, name: str, data_url: str) -> dict:
        """浏览器上传一段素材（dataURL）→ 写进工程 assets/ 并登记。

        浏览器给不出本地文件路径，只能给字节，所以走 import_asset_bytes。
        """
        root = self.project_dir(self.current_token)
        if root is None:
            raise CoreError("未打开工程")
        data = _decode_data_url(data_url)

        def mut(manifest):
            record = assets_mod.import_asset_bytes(root, name, data)
            manifest.setdefault("assets", []).append(record)
            return {"asset": record}

        _root, _m, extra = mutate(str(root), mut, refresh_html=False)
        return extra

    def state(self) -> dict:
        """当前工程的完整视图：画布 + 每页元素（全字段）+ 素材 + 预览/素材地址前缀。"""
        root = self.project_dir(self.current_token)
        if root is None:
            return {"project": None}
        manifest = read_manifest(root)
        pages = []
        for i, page in enumerate(manifest.get("pages") or []):
            pages.append({
                "index": i,
                "id": page.get("id"),
                "name": page.get("name"),
                "background": page.get("background"),
                "elements": sorted(page.get("elements") or [], key=lambda e: e.get("z") or 0),
            })
        return {
            "project": str(root),
            "name": manifest.get("name"),
            "type": manifest.get("type"),
            "canvas": manifest.get("canvas"),
            "pages": pages,
            "assets": manifest.get("assets") or [],
            "assetBase": f"/proj/{self.current_token}/",
            "canvasUrl": "/canvas",
        }

    def ui_current(self) -> dict:
        """轻量视图：只说「UI 现在展示哪个工程」，不拉整份 pages（给外部 agent 用）。"""
        root = self.project_dir(self.current_token)
        if root is None:
            return {"project": None, "name": None, "type": None,
                    "port": self.port, "url": self.url}
        try:
            manifest = read_manifest(root)
            name, ptype = manifest.get("name"), manifest.get("type")
        except CoreError:
            name, ptype = root.name, ""
        return {"project": str(root), "name": name, "type": ptype,
                "port": self.port, "url": self.url}

    def ui_open(self, path: str) -> dict:
        """把 UI 切到目标工程（运行中直接换）。不是合法工程则由 open_project 明确报错。"""
        target = (path or "").strip()
        if not target:
            raise CoreError("缺少 path：请给出要打开的工程目录")
        res = api.open_project(target)
        self.set_project(res["path"])
        return self.ui_current()


# 直接转发到 noedit_core.api 的方法（path 由调用方作为第一个参数传入）。
_DIRECT = {
    "list_pages": api.list_pages,
    "add_page": api.add_page,
    "update_page": api.update_page,
    "delete_page": api.delete_page,
    "list_elements": api.list_elements,
    "insert": api.insert,
    "update": api.update,
    "delete": api.delete,
    "reorder": api.reorder,
    "import_asset": api.import_asset,
    "list_assets": api.list_assets,
    "export": api.export,
    "element_types": api.element_types,
    "scene_libs": api.scene_libs,
    "install_scene_lib": api.install_scene_lib,
    "remove_scene_lib": api.remove_scene_lib,
    "export_scene_gif": api.export_scene_gif,
    "compose_scene_gif": api.compose_scene_gif,
}


def run(host: str = "127.0.0.1", port: int = 8760, project: str = "", open_browser: bool = False) -> int:
    """启动服务并阻塞（Ctrl+C 退出）。返回进程退出码。"""
    try:
        ui = LocalUI(host=host, port=port, project=project)
    except OSError as exc:
        print(f"端口 {port} 起不来：{exc}（可换 --port）")
        return 1
    ui.start()
    print(f"{APP_NAME} Core UI 已启动：{ui.url}")
    if project:
        print(f"已打开工程：{ui.project_dir(ui.current_token)}")
    else:
        print("未指定工程——在页面里新建或打开一个即可（可用 --project 直接指定）。")
    print("按 Ctrl+C 停止。")
    if open_browser:
        webbrowser.open(ui.url)
    try:
        ui._thread.join()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        ui.stop()
    return 0
