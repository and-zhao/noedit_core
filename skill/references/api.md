# API 完整签名与返回结构

模块：`noedit_core.api`。全部为同步函数，出错抛 `noedit_core.api.CoreError`（`str(exc)` 即用户可读的中文说明）。

```python
import sys; sys.path.insert(0, r"<NECORE>")
from noedit_core import api
```

---

## 工程

### `create_project(name, parent_dir, preset="ppt-16:9", ptype="ppt") -> dict`

新建工程。目录名取 `name`，落在 `parent_dir` 下；**重名自动追加 `-2` / `-3`**，不覆盖已有目录。
`parent_dir` 不存在会自动创建。

`preset` 取值（`projects.CANVAS_PRESETS`）：

| preset | 尺寸 | 用途 |
| --- | --- | --- |
| `ppt-16:9` | 1280×720 | PPT 默认 |
| `ppt-4:3` | 1024×768 | 4:3 演示 |
| `slide-widescreen` | 1600×900 | 宽屏演示 |
| `a4-portrait` | 794×1123 | A4 纵向（简历） |
| `a4-landscape` | 1123×794 | A4 横向 |
| `b5-portrait` | 692×980 | B5 纵向 |

返回：

```json
{"path": "D:\\work\\季度汇报",
 "summary": {"name": "季度汇报", "type": "ppt", "canvas": {...},
             "pageCount": 1, "assetCount": 0, "updatedAt": 1234567890},
 "url": "file:///D:/work/%E5%AD%A3%E5%BA%A6%E6%B1%87%E6%8A%A5/index.html"}
```

新工程**自带 1 页空白页**——你的「第 1 页」（封面）就写进这页，**不要**再新建第 1 页，否则最前面会多一张空页。

### `open_project(path) -> dict`

```json
{"path": "...", "summary": {...},
 "outline": [{"index": 0, "id": "page_xxx", "name": "第 1 页", "elementCount": 0}],
 "url": "file:///..."}
```

### `canvas(path) -> dict`

```json
{"canvas": {"preset": "ppt-16:9", "width": 1280, "height": 720, "background": {...}}}
```

---

## 页面

### `list_pages(path) -> dict`

```json
{"path": "...", "canvas": {...},
 "pages": [{"index": 0, "id": "page_xxx", "name": "第 1 页",
            "elementCount": 3, "background": {...}}]}
```

### `add_page(path, index=-1, name="", background=None) -> dict`

`index < 0` 或不传 = 追加到末尾；否则插到该位置（越界会被夹到合法范围）。`name` 为空则自动命名。
`background` 会与页面默认背景（白底）合并。

```json
{"path": "...", "index": 1, "id": "page_yyy", "name": "第二页", "pageCount": 2}
```

### `update_page(path, props, page_index=0, page_indexes=None, all_pages=False) -> dict`

改页面属性。`props` 的键同样是**点号路径**，常用两个：

- `background`：页面背景，会与页面默认背景（白底）合并。结构同画布背景：
  - 纯色：`{"type": "solid", "color": "#0f172a"}`
  - 图片：`{"type": "image", "image": "assets/bg.jpg", "fit": "cover"}`（`image` 填工程内素材的 `relPath`）
- `name`：页名。

```python
# 全篇统一背景（先把页数建满）
api.update_page(path, {"background": {"type": "image", "image": "assets/bg.jpg", "fit": "cover"}},
                all_pages=True)
# 只改某一页
api.update_page(path, {"background": {"type": "solid", "color": "#0f172a"}}, page_index=2)
```

不传页范围只改 `page_index` 这一页；`page_indexes=[...]` 改指定若干页；`all_pages=True` 改所有页。
> 全篇统一背景、底板色走这条（属页面结构，**不要**拿满幅 `image` 元素当背景——会盖住内容、每页各存一份）。

返回：`{"path": "...", "changed": n, "logs": [...]}`。

### `delete_page(path, index) -> dict`

删掉第 `index` 页（0 起）。**至少保留一页**，删到只剩一页会抛 `CoreError`。

```json
{"path": "...", "changed": 1, "logs": ["删除页面 第 2 页"]}
```

---

## 元素

### `list_elements(path, page_index=-1, full=False) -> dict`

`page_index < 0` = 列所有页；`full=True` 返回完整 `props` / `style`，否则只返回摘要字段。

摘要字段：`id` `type` `name` `x` `y` `w` `h` `z` `parentId`。

```json
{"path": "...", "pages": [
    {"index": 0, "id": "page_xxx", "name": "第 1 页",
     "elements": [{"id": "el_ab12", "type": "text", "name": "标题",
                   "x": 80, "y": 60, "w": 900, "h": 80, "z": 1, "parentId": null}]}]}
```

指定单页时返回 `{"path", "pageIndex", "pageId", "pageName", "elements"}`；`page_index` 越界抛 `CoreError`。

### `insert(path, element, page_index=0, page_indexes=None, all_pages=False) -> dict`

在指定页插入一个元素；`element` 至少给 `type`（其余用 schema 默认值）。
`all_pages=True` 铺到**调用时已存在的所有页**；`page_indexes=[...]` 铺到指定若干页；否则只插 `page_index` 这一页。

```json
{"path": "...", "changed": 1, "logs": ["插入 text ..."]}
```

> ⚠️ 要全篇铺底板，**先把页数建满，再 `all_pages=True`**（它不会覆盖以后新建的页）。

### `update(path, props, element_id="", match=None, page_index=0, page_indexes=None, all_pages=False) -> dict`

`props` 的键是**点号路径**：顶层写键名，内部用 `props.xxx` / `style.xxx`。

```python
api.update(path, {"x": 100, "props.text": "新标题", "style.fontSize": 32}, element_id="el_ab12")
```

### `delete(path, element_id="", match=None, page_index=0, page_indexes=None, all_pages=False) -> dict`

### `reorder(path, element_id="", match=None, index=-1, to_front=False, to_back=False, page_index=0) -> dict`

`index` 越大越靠上；或用 `to_front` / `to_back`。

### 定位规则（`element_id` vs `match`）

- 给 `element_id`（元素 `id`）精确定位。
- 给 `match` 按描述定位，支持 4 个键：`type`、`name`（精确相等）、`nameContains`（子串）、`srcContains`（匹配图片 `props.src` 或元素名）。
  - 多条件为 AND：`match={"type": "text", "nameContains": "标题"}`。
- **`match` 不给页范围会跨整页匹配**，务必同时传 `page_index` / `page_indexes` / `all_pages`。
- 两者都不给 → `CoreError`；找不到目标 → `CoreError`。
- **锁定（`locked:true`）的元素不会被自动跳过**——核心不强制拦截，改了就是改了。要避开锁定元素得自己先筛。

---

## 工程内素材

### `import_asset(path, source_paths) -> dict`

把外部文件**复制**进 `<工程>/assets/`，返回登记记录。文件名冲突自动改名（`logo.png` → `logo_1.png`）。

```json
{"path": "...", "imported": [
    {"id": "a1b2c3d4e5", "name": "logo.png", "relPath": "assets/logo.png",
     "kind": "image", "size": 1234, "addedAt": 1234567890, "origin": "D:\\pics\\logo.png"}]}
```

之后把 `relPath` 写进元素 `props.src` 即可引用。`kind` 取值：`image` / `video` / `audio` / `table` / `code` / `file`。
路径不存在或不是文件的条目会被静默跳过；全都无效则抛 `CoreError`。

### `list_assets(path) -> dict`

```json
{"path": "...", "assets": [
    {"name": "logo.png", "relPath": "assets/logo.png", "kind": "image",
     "size": 1234, "exists": true}]}
```

`exists=false` 表示记录还在、文件已丢——下次任何落盘会自动把它剔除。

---

## 矢量图标库

核心**随发行内置**一份矢量图标目录（`noedit_core/web/icon-catalog*.json`，1800+ 图标、36 组：draw.io 几何 / 流程 / 器件、Bioicons 分子 / 细胞 / 器材 / 动植物、Apollon UML / 流程图），运行期只读、无需联网。图标是矢量 `d`（局部坐标、只有 `M/L/C/Z` 绝对命令），插入后是**可继续编辑的 `path` 元素**，不是图片。

### `icon_groups() -> list[dict]`

列出所有分组（含二级分组的父大类与数量）。目录缺失时回空列表。

```json
[{"id": "mxgraph", "label": "draw.io 图形", "count": 900, "parent": ""},
 {"id": "bioicons", "label": "Bioicons 生物", "count": 900, "parent": ""}]
```

### `icon_list(group="", limit=200) -> dict`

`group` 留空 = 只回分组概览（`icons: []`）；给了分组 id 则列出该组图标。条目是**精简字段**（`id/label/group/box/line/multi`），不带 `path` 的 `d`。

```json
{"groups": [...], "group": "mxgraph", "total": 900,
 "icons": [{"id": "mxgraph.arrows.arrow_down", "label": "arrow down",
            "group": "mxgraph", "box": 100, "line": true, "multi": false}]}
```

### `icon_search(keyword="", group="", limit=40) -> dict`

按关键词搜（匹配英文名 / id / 中文分组名），可用 `group` 限定。

```json
{"keyword": "arrow", "group": "", "total": 34,
 "icons": [{"id": "mxgraph.arrows.arrow_down", "label": "...", "group": "...",
            "box": 100, "line": true, "multi": false}]}
```

### `icon_insert(path, icon_id, x=None, y=None, size=150, color="#2f6fed", name="", page_index=0, page_indexes=None, all_pages=False) -> dict`

按图标 id 造元素并插入。

- **单色图标**（`line=true` 或纯填充）：插**一个 `path`**，颜色取 `color`，之后可换色。
- **多色图标**（`multi=true`，自带配色）：插成 `group` 容器 + 若干按层着色的 `path` 成员（成员靠 `parentId` 挂容器），此时 `color` 不参与。
- `x` / `y` 省略时按画布**居中偏上**摆位；`size` 是元素框**长边像素**，`d` 按长边等比缩放。
- 页选择同其它接口：`page_index` / `page_indexes` / `all_pages`，越界页静默丢弃。

```json
{"path": "...", "changed": 1,
 "icon": {"id": "mxgraph.arrows.arrow_down", "label": "...", "w": 150, "h": 150,
          "multi": false, "elements": 1},
 "pageCount": 3}
```

`icon_id` 不存在抛 `CoreError`（提示先用 `icon_search` 找）。

典型用法：

```python
from noedit_core import api
hit = api.icon_search("神经元", limit=1)["icons"][0]
api.icon_insert(path, hit["id"], x=120, y=200, size=90, color="#c0392b")
```

---

## 导出

### `export(path, fmt="pptx", out_dir="", scene_gifs=None, **options) -> dict`

`fmt ∈ html | pdf | pptx | png | svg`；默认落到**工程内的 `export/` 目录**，`out_dir` 可改。
`png` / `svg` 额外支持 `pages`（`"1"` / `"1,3"` / `"2-5"`，空 = 全部）、`dpi`（96/150/300/600）、`transparent`。

`scene_gifs` 只对 `pptx` 生效，控制**微场景动图**：

- `None`（默认）：工程里存在带 `props.code` 的 `scene` 元素时，核心**自动抓帧 → 合成 GIF → 内嵌**（需本机 Edge/Chrome，见下）。
- `False`：不内嵌，微场景退回静态 `props.poster`。
- `dict`：`{元素id: GIF 文件路径}`，用你现成的动图，跳过抓帧。

返回统一含 `{"ok", "path", "message", "format"}`；`png` / `svg` 还带 `paths`（多页路径列表）与 `warnings`。
`ok=False` 时 `path` 为空、`message` 说明原因（缺依赖 / 缺浏览器 / 无页面等）。详见 [export.md](export.md)。

抓帧失败的单个场景**不会中断导出**——该场景退回 `poster`，其余照常，`message` 会说明「已内嵌 N 个 / M 个失败」。

---

## 微场景（scene）

微场景 = 沙箱 `iframe` 跑 `props.code`（用户/agent 写的 JS），靠 `mount(el, params)` / `seek(t)` / `unmount()` 生命周期驱动。
HTML 导出一定动；**PPTX 里也能动**——核心把场景逐帧抓下来合成 GIF 内嵌（见上）。PDF / PNG / SVG 取 `props.poster` 静态帧。

> `seek(t)` 是抓帧的前提：场景必须实现「按时间 t 定格」的 `seek(t)`，核心才能逐帧取图。
> 只自播、不实现 `seek(t)` 的场景，GIF 判定失败并退回 `poster`（`ok=False` 附「逐帧画面完全相同」提示）。

### `scene_libs() -> dict`

列内置可选库及其本地缓存状态。

```json
{"libs": [{"id": "gsap", "name": "GSAP", "version": "3.12.5",
           "cached": true, "path": "noedit_core/data/scene_libs/gsap.js"}]}
```

### `install_scene_lib(lib_id="") -> dict`

下载并缓存库到 `data/scene_libs/<id>.js`（**会联网**，来自 CDN）。`lib_id=""` = 全部；未知 id → `CoreError`。

```json
{"installed": [{"id": "gsap", "ok": true, "bytes": 71123}]}
```

> 场景 `props.libs` 里引用的库**必须先本地缓存**——否则抓帧时缺库、GIF 判定失败。
> 用法：先 `api.install_scene_lib("gsap")`，再写 `"libs": ["gsap"]` 的场景。

### `remove_scene_lib(lib_id) -> dict`

删除某个已缓存库。返回 `{"removed": ["gsap"]}`。

### `compose_scene_gif(path, frames, fps=12, loop=True, background="#ffffff", transparent=False, out_dir="", name="") -> dict`

把**现成帧**合成 GIF（不抓帧，纯 Pillow）。`frames` = dataURL 字符串数组（`data:image/png;base64,...` / `data:image/webp;base64,...`）。

```json
{"ok": true, "path": "...\\export\\scene.gif", "n_frames": 9, "fps": 12,
 "width": 640, "height": 360, "bytes": 177000, "transparent": true, "message": "已导出 GIF"}
```

约束：帧数 `2..400`；`fps` 夹到 `1..60`；帧尺寸以第一帧为准对齐；`transparent=True` 时 `alpha<24` 判透明。
`name` 为空自动命名。

### `export_scene_gif(path, element_id="", match=None, page_index=0, out_dir="", fps=12, width=0, scale=2.0, background="#ffffff", transparent=True, name="") -> dict`

**一站式**：定位单个微场景元素 → 无头浏览器抓帧 → 合成 GIF。`element_id` / `match` 定位规则同 [元素定位](#定位规则element_id-vs-match)。

- `width`：抓帧 CSS 宽度（`0` = 用元素宽度，上限 1920）；`scale`：像素倍率（默认 2）。
- `name`：**输出文件名**（不含扩展名），与上面 `match={"name": …}` 里的「元素名」**是两回事**；留空按元素名自动命名。
- `out_dir`：输出目录（相对工程）；`background` / `transparent`：GIF 底色与透明通道；`fps`：帧率。
- 返回含 `{"ok", "path", "message", ...}`；缺浏览器 / 缺库 / 无 `seek` 时 `ok=False` 并说明原因。
- **调用一律用关键字**：本函数 11 个参数里后 10 个带默认值，**位置错位不报错、会静默串字段**——最典型的是把 `code` 之类的东西落到末尾的 `name` 上，表现为「输出文件名异常」。除 `path` 外请全部写 `键=值`。
- **失败排查**：`ok=False` 时 **`path` 恒为空**，原因只在 `message` 里（分流表见 SKILL.md「GIF 抓帧失败」节）。

---

## 本地 UI 服务（HTTP 接口 · 工程设置）

上面各节都是 Python 函数（`noedit_core.api`）。而浏览器 UI（`main.py serve`）对外是一套**本地 HTTP 服务**：只监听回环、**单进程单工程**，默认 `http://127.0.0.1:8760/`。
agent 想让 UI「切到某个工程 / 做工程设置 / 看目录树」，走的就是这一节。

### 服务发现：`data/ui.json`

`serve` 启动时写入、正常退出时删除：

```json
{"app": "NoEdit", "version": "0.2.0", "host": "127.0.0.1", "port": 8760,
 "url": "http://127.0.0.1:8760/", "pid": 12345,
 "project": "D:\\work\\季度汇报", "startedAt": "2026-10-05 12:34:56"}
```

（未打开工程时 `project` 为空串 `""`；`startedAt` 是本地时间字符串。）

> ⚠️ 该文件可能是上次被强杀留下的（进程已不在、文件还在）——**拿到端口后必须先探测**（`GET /api/ping`）确认真在跑，别直接把它当活服务。

### GET 端点

| 端点 | 返回 | 说明 |
| --- | --- | --- |
| `GET /api/ping` | `{"ok":true,"app":"..."}` | 存活探测 |
| `GET /api/ui/current` | `{"ok":true,"result":{...}}` | 当前工程（轻量）；见下 |
| `GET /canvas?page=<0 起>` | 整页 HTML | 用导出同款渲染器渲染当前工程某页（所见即所得，点选元素会 postMessage 回父窗口） |

另有静态资源路由：`/`（UI 首页）、`/ui/*`、`/img/*`、`/web/*`、`/proj/<token>/*`（当前工程内文件，`token` 即 `state` 里的 `assetBase` 前缀）。

`GET /api/ui/current` 的 `result`：

```json
{"project": "D:\\work\\季度汇报", "name": "季度汇报", "type": "ppt",
 "port": 8760, "url": "http://127.0.0.1:8760/"}
```

`project` 为 `null` = UI 当前没打开任何工程。

### `POST /api/ui/open`（切换当前工程）

体 `{"path":"<工程目录>"}`（也接受 `?path=<工程目录>`）；路径不是合法工程会明确报错。**运行中直接切，无需重启服务**；浏览器页面每 2 秒自检一次，会**自动跟随切换**（用户无需手动刷新）。

### `POST /api/call`（通用调用口）

体 `{"method":"<方法名>","args":[...]}`（`args` 用数组；若传的不是数组，会被当作**单个参数**包装成 `[args]`），应答 `{"ok":true,"result":...}` 或 `{"ok":false,"message":"..."}`。请求体上限 64 MB。

下面这组方法由 UI 服务**自己**处理（**不是** `noedit_core.api` 的函数），专管「工程设置 / 工程切换 / 目录浏览」：

| method | args | 作用 |
| --- | --- | --- |
| `ping` | — | 同 `GET /api/ping` |
| `state` | — | 当前工程完整视图（见下）；未打开工程 → `{"project": null}` |
| `create_project` | `name, parent_dir[, preset, ptype]` | 新建工程并**切换**过去（返回同 `state`） |
| `open_project` | `path` | 打开并切换到该工程（返回同 `state`） |
| `close_project` | — | 关闭当前工程，UI 回落地页 → `{"project": null}` |
| `get_settings` | — | `{"defaultDir":"...","custom":true/false}` |
| `set_default_dir` | `path` | 设「默认目录」并落盘（见下） |
| `browse_roots` | — | 目录树根节点（见下） |
| `browse_dir` | `path`（空 = 默认目录） | 列一层子目录并标出哪些是工程（见下） |
| `upload_asset` | `name, data_url` | 浏览器上传素材（dataURL 字节）写进当前工程 `assets/` → `{"asset": {...}}` |

**其余 method 直接转发到 `noedit_core.api`**，把工程 `path` 作为第一个参数传进去：

```json
{"method": "insert", "args": ["D:\\work\\季度汇报", {"type":"text","props":{"text":"标题"}}, 0]}
```

即 `/api/call` 等价于「先取当前工程 path，再调 `api.<method>(path, *args)`」。所以上面各节的函数（`list_pages` / `add_page` / `insert` / `update` / `delete` / `reorder` / `export` / `icon_*` / `scene_*` …）都能从 HTTP 走。

> 注意：转发方法操作的是**当前已打开工程**，**不是**请求体里传的 path——想操作别的工程，先用 `open_project` 切过去，或直接用 Python 调 `noedit_core.api`。

### `state` 返回结构

```json
{"project": "D:\\work\\季度汇报", "name": "季度汇报", "type": "ppt",
 "canvas": {"preset": "ppt-16:9", "width": 1280, "height": 720,
            "background": {"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"}},
 "pages": [{"index": 0, "id": "pg_...", "name": "封面", "background": null,
            "elements": [ /* 全字段，按 z 升序 */ ]}],
 "assets": [ /* 同 list_assets */ ],
 "assetBase": "/proj/<token>/", "canvasUrl": "/canvas"}
```

`assetBase` 是当前工程的资源前缀，`canvasUrl` 是画布预览页。

### 「默认目录」（工程设置）

新建工程的**父目录**、目录树起点、导出落点都由这个「默认目录」决定。它存在 `data/settings.json`（键 `defaultDir`）：

- `get_settings` → `{"defaultDir":"D:\\work","custom":true}`；`custom=false` = 用户没设过，`defaultDir` 是**回退值**（工程根 `paths.projects_root()`）。
- `set_default_dir(path)`：目录必须存在，否则 `CoreError("目录不存在：...")`；空串 → `CoreError("默认目录不能为空")`；成功返回 `{"defaultDir":"..."}`。

### `browse_roots` / `browse_dir`（目录树）

`browse_roots`：

```json
{"roots": [{"name": "C:", "path": "C:"}, {"name": "D:", "path": "D:"}],
 "defaultDir": "D:\\work"}
```

`browse_dir`（`path` 空 = 从默认目录开始）：

```json
{"path": "D:\\work", "parent": "D:\\", "root": "D:\\work", "isProject": false, "projectName": "",
 "entries": [{"name": "季度汇报", "path": "D:\\work\\季度汇报", "isProject": true,
              "projectName": "季度汇报", "type": "ppt", "pages": 8},
             {"name": "素材", "path": "D:\\work\\素材", "isProject": false,
              "projectName": "", "type": "", "pages": 0}]}
```

- `entries` 只列**目录**（跳过文件与 `.` 开头的隐藏项），工程排前面（`isProject=true`）；`isProject` 的判据是该目录下有没有 `project.manifest.json`。
- `root` 返回的是「默认目录」（与 `browse_roots.defaultDir` 同值），目录树从它起步；`parent` 才是上一级。
- `browse_roots` 在 Windows 上列盘符（名称形如 `C:`，依赖 `os.listdrives`，**需 Python 3.12+**）；其他平台回退 `["/"]`，Windows 上取不到盘符则返回空数组。

---

## 类型知识

### `element_types() -> list[dict]`

```json
[{"type": "text", "label": "文本", "defaultSize": {"w": 420, "h": 90},
  "modelNote": "科研图里的轴标 / 图注 ..."}, ...]
```

按 `type` 排序。`modelNote` 是该类型的易错点 / 必填项提示，**写该类型前先读它**。
`scene`（微场景）是沙箱 `iframe` 跑 `props.code`：**HTML 一定动，PPTX 会动**（核心自动抓帧合成 GIF 内嵌）；PDF / PNG / SVG 取 `props.poster` 静态帧（没有就深色占位）。详见上文「微场景」。
