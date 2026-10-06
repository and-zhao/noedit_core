<p align="center"><img src="img/logo.svg" alt="NoEdit Core" width="96"></p>

<h1 align="center">NoEdit Core</h1>

<p align="center">
  <a href="README.md">English</a> |
  <b>简体中文</b> |
  <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/export-pptx%20%7C%20pdf%20%7C%20png%20%7C%20svg%20%7C%20html-success?style=flat-square" alt="Export">
  <img src="https://img.shields.io/badge/icons-1800%2B-orange?style=flat-square" alt="Icons">
</p>

<p align="center">一个<b>最小 PPT 创作核心</b>：用一个普通 Python 包建多页画布（PPT），并导出 pptx / pdf / html / png / svg。</p>

**核心特点**

- 可导出 **pptx** 格式，超高保真度、不失真
- 最大程度保留**可编辑能力**
- **微场景**模块能够产生动态效果（全球首创）
- 全套**矢量工具** + **1800+ 矢量库**，让 PPT 摆脱「文字 + 卡片 + 配图」的格式
- 超强的**科研绘图**能力：统计图、流程图、架构图、拓扑图……通通拿下

**能力范围**：工程读写、页面与元素增删改、20 种统计图、矢量图形（shape / path / connector）、
**内置矢量图标库**（1800+ 个图标，搜索即插成可编辑的 `path` 元素）、表格 / 代码 / 公式、
工程内本地素材、5 种导出格式，以及**内置的浏览器编辑器**（本地起服务，浏览器打开即可
预览、选中元素改属性）；元素动画（`anim`）与微场景（`scene`）——
**HTML 一定动；PPTX 里微场景会动**（核心自动抓帧合成 GIF 内嵌），PDF / PNG / SVG 取静态帧。

**不含**：AI 自动生成内容（含场景代码 / 封面帧）、全局素材库、模板、截图复核、桌面客户端。
（微场景可用的内置 JS 库按需**联网下载到本地缓存**后使用，见 `install_scene_lib`。）

## 演示

<p align="center">
  <img src="img/NoEdit_core%E6%BC%94%E7%A4%BA%E5%9B%BE.png" alt="NoEdit Core 演示图" width="100%">
</p>

<p align="center">
  <img src="img/slide1.png" width="24%">
  <img src="img/slide2.png" width="24%">
  <img src="img/slide3.png" width="24%">
  <img src="img/slide4.png" width="24%">
</p>

## NoEdit · 完整版

> **NoEdit** 是 **NoEdit_core** 的完整版，上手即用。

软件架构上采用 **MCP** 结构，可对外部智能体提供生成 PPT 的服务；内部采用**主 agent + 子代理**模式，
极大压缩 PPT 生成时间，并最大化优化缓存命中策略、节省 token。

**完整桌面版**

- 并行子代理架构，超快的生成速度
- 更节省 token 的策略
- 内置专业 agent 助手，一对一优化
- 更强的手动编辑修改能力，丝滑交互
- 全套手动科研绘图工具和交互
- 科研绘图临摹工具（AI + 手动）
- 打开即用，超简单配置（相比 NoEdit_core）
- 可视化素材管理、模板
- 插件机制：可自主开发 / 安装插件，灵活配置
- 底层可调：工具、MCP、skill、workflow、team、权限管理、画布设置……无限可能
- ……还有更多强大功能，等你去探索

<p align="center">
  <img src="img/%E8%BD%AF%E4%BB%B6%E5%85%A8%E8%B2%8C.png" alt="NoEdit 软件全貌" width="100%">
</p>

<table>
  <tr>
    <td width="48%" valign="top">
      <img src="img/%E7%9F%A2%E9%87%8F%E5%BA%93.png" alt="矢量库" width="100%">
      <img src="img/%E5%B1%9E%E6%80%A7%E9%9D%A2%E6%9D%BF.png" alt="属性面板" width="100%">
      <img src="img/%E4%B8%B4%E6%91%B9%E6%A8%A1%E5%BC%8F.png" alt="临摹模式" width="100%">
    </td>
    <td width="52%" valign="top">
      <img src="img/%E6%8F%92%E4%BB%B6%E6%9C%BA%E5%88%B6.png" alt="插件机制" width="100%">
    </td>
  </tr>
</table>

<h2 align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">点击链接，查看本项目做出来的各种惊艳效果</a>
</h2>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">
    <img src="https://img.shields.io/badge/%E2%96%B6%20WATCH%20THE%20DEMO-BILIBILI-FB7299?style=for-the-badge&logo=bilibili&logoColor=white" alt="在 B 站观看演示" width="440">
  </a>
</p>

<p align="center">
  <video src="img/NoEdit%E4%B8%80%E5%8F%A5%E8%AF%9D%E7%94%9F%E6%88%90ppt.mp4" controls width="720"></video>
</p>

## 目录结构

```
noedit_core/
├─ main.py                 # CLI 入口（python main.py <子命令>）
├─ img/                    # README 配图（logo.svg 等）
├─ noedit_core/
│  ├─ api.py               # 公共 API（唯一需要 import 的模块）
│  ├─ cli.py               # 命令行实现
│  ├─ server.py            # 本地 HTTP 服务（浏览器 UI 的后端：静态资源 + /api/call + /canvas 预览）
│  ├─ ui/                  # 内置浏览器 UI（index.html + app.css + app.js + i18n.js）
│  └─ core/                # 核心实现：projects / export / actions / element_schema /
│                          #   assets / icon_catalog / shape_outline / connector_geom / store ...
│  └─ web/                 # 渲染期资源：element-schema.json、icon-catalog*.json、render-kit、katex
├─ skill/                  # Agent Skill：怎么用这套核心（SKILL.md + references/）
└─ tests/smoke.py          # 端到端冒烟测试
```

## 环境依赖

- **Python 3.10+**（用到 `X | Y` 类型语法与 `from __future__ import annotations`）
- 导出依赖：
  - `pptx` → **python-pptx**（必需）
  - `pdf` / `png` / `svg` → 本机装有 **Edge 或 Chrome**（无头渲染）

```bash
pip install python-pptx
```

## 快速开始

### 浏览器 UI（起服务，浏览器打开即可用）

```bash
python main.py serve --project D:\work\季度汇报     # 启动后打开 http://127.0.0.1:8760/
```

不传 `--project` 时先打开 `http://127.0.0.1:8760/`，在落地页里**新建**或**打开**一个工程目录。

UI 提供：页面 / 元素列表、画布预览（点画布里的元素即选中）、属性面板（改 x / y / w / h、文字、
颜色、字号、层级、透明度等）、增删元素与页面、导入素材、导出（HTML / PPTX / PDF / PNG / SVG）。
预览用的是**导出同款渲染器**，所见即所得；每次改动即时落盘并刷新预览。数据仍落在同一份
`project.manifest.json`，与 API / CLI 完全互通。

界面支持**简体中文 / English / 日本語**（默认简体中文，选择记忆在本地）。左侧「页面」与「元素」
两个面板默认对半，中间可上下拖动调节；三栏之间的宽度也可拖动调整（双击拖拽条恢复默认），
列宽与画布缩放都会随窗口大小自适应。在画布区域滚动滚轮可直接切换页面；已打开工程时，
「新建 / 打开工程」面板点遮罩、点右上角关闭或按 Esc 即可返回编辑界面。

#### 本地 UI HTTP 接口

服务只监听回环、**单进程单工程**。除上面的界面外，它还暴露一组小接口，方便 agent（或别的工具）
切换当前工程、做工程设置：

| 端点 | 请求体 | 返回 |
| --- | --- | --- |
| `GET /api/ping` | — | `{"ok":true,"app":"..."}`（存活探测） |
| `GET /api/ui/current` | — | `{"ok":true,"result":{"project":<工程目录>\|null,"name","type","port","url"}}` |
| `POST /api/ui/open` | `{"path":"<工程目录>"}`（也可用 `?path=`） | 把运行中的 UI 切到该工程，无需重启 |
| `POST /api/call` | `{"method":"<方法名>","args":[...]}` | `{"ok":true,"result":...}` 或 `{"ok":false,"message":"..."}` |
| `GET /canvas?page=<0 起>` | — | 当前工程某页，用导出同款渲染器渲染 |

`POST /api/call` 自己处理一组**工程设置 / 工程切换 / 目录浏览**方法（`ping`、`state`、`create_project`、
`open_project`、`close_project`、`get_settings`、`set_default_dir`、`browse_roots`、`browse_dir`、`upload_asset`）；
**其余方法直接转发到 `noedit_core.api`**，工程 `path` 作为第一个参数，例如
`{"method":"insert","args":["D:\\work\\季度汇报", {...}, 0]}`。

「默认目录」（新建工程的父目录 / 目录树起点 / 导出落点）落盘在 `data/settings.json`。运行中的服务还会写
`data/ui.json`（`{app, version, host, port, url, pid, project, startedAt}`）供发现——由于强杀后可能残留，
拿到端口后先用 `GET /api/ping` 探测。

完整签名与返回结构见 [skill/references/api.md](skill/references/api.md) 的「本地 UI 服务」一节。

### 命令行

```bash
python main.py create "季度汇报" --dir D:\work
python main.py insert D:\work\季度汇报 --json "{\"type\":\"text\",\"props\":{\"text\":\"标题\"}}"
python main.py export D:\work\季度汇报 --fmt pptx
```

所有子命令输出 JSON；出错打印错误并返回非 0 退出码。

| 子命令 | 说明 |
| --- | --- |
| `serve [--host] [--port] [--project] [--open]` | 启动本地 UI 服务（浏览器打开地址即可预览 / 编辑） |
| `create <name> --dir <父目录> [--preset] [--type]` | 新建工程 |
| `open <path>` | 概要 + 大纲 |
| `types` | 列元素类型与 modelNote |
| `pages <path>` / `add-page <path>` | 页面列表 / 加页 |
| `elements <path> [--page] [--full]` | 列元素 |
| `insert <path> --json <元素JSON> [--page]` | 插入 |
| `update <path> --props <点号路径JSON> [--id/--match]` | 修改 |
| `delete <path> [--id/--match]` | 删除 |
| `reorder <path> [--index/--front/--back] [--id/--match]` | 层级 |
| `asset-add <path> <文件...>` / `assets <path>` | 导入 / 列素材 |
| `icon-groups` / `icon-list <分组> [--limit]` | 矢量图标：列分组 / 列某组图标 |
| `icon-search [关键词] [--group] [--limit]` | 搜矢量图标（匹配英文名 / id / 中文分组名） |
| `icon-insert <path> <图标id> [--x/--y/--size/--color/--page]` | 插入图标（生成可编辑 `path` 元素） |
| `export <path> [--fmt] [--out] [--pages] [--dpi] [--transparent] [--no-scene-gif]` | 导出 |
| `scene-libs` / `scene-lib-add [id]` / `scene-lib-remove <id>` | 微场景库：列 / 下载 / 删 |
| `scene-gif <path> [--id/--match] [--fps] [--scale] [--opaque]` | 单场景抓帧导出 GIF |

### Python

```python
import sys
sys.path.insert(0, r"D:\NoEdit\noedit_core")
from noedit_core import api

p = api.create_project("季度汇报", r"D:\work")
path = p["path"]

# 第 1 页（新工程自带的空白页）写封面
api.insert(path, {"type": "text", "x": 80, "y": 60, "w": 900, "h": 80,
                  "props": {"text": "2025 季度回顾"},
                  "style": {"fontSize": 40, "fontWeight": "700"}}, page_index=0)

# 加第二页并放图
api.add_page(path, name="数据页")
rec = api.import_asset(path, [r"D:\pics\chart.png"])["imported"][0]
api.insert(path, {"type": "image", "x": 80, "y": 100, "w": 500, "h": 300,
                  "props": {"src": rec["relPath"], "fit": "cover"}}, page_index=1)

api.export(path, "pptx")
```

## API 一览

| 函数 | 作用 |
| --- | --- |
| `create_project(name, parent_dir, preset="ppt-16:9", ptype="ppt")` | 新建工程 |
| `open_project(path)` | 打开：概要 + 大纲 + 预览地址 |
| `canvas(path)` / `list_pages(path)` / `add_page(path, ...)` | 画布 / 页面 |
| `update_page(path, props, ..., all_pages=False)` / `delete_page(path, index)` | 改页面属性（背景 / 页名）/ 删页 |
| `list_elements(path, page_index=-1, full=False)` | 列元素 |
| `insert(path, element, page_index=0, ...)` | 插入元素 |
| `update(path, props, element_id="", match=None, ...)` | 修改（props 用点号路径） |
| `delete(path, element_id="", match=None, ...)` / `reorder(path, ...)` | 删除 / 层级 |
| `import_asset(path, source_paths)` / `list_assets(path)` | 工程内本地素材 |
| `icon_groups()` / `icon_list(group="", limit=200)` | 矢量图标：分组概览 / 列某组图标 |
| `icon_search(keyword="", group="", limit=40)` | 搜矢量图标 |
| `icon_insert(path, icon_id, x=None, y=None, size=150, color="#2f6fed", ...)` | 插入图标（单色→1 个 `path`；多色→`group` 容器 + 分层成员） |
| `export(path, fmt="pptx", out_dir="", scene_gifs=None, **options)` | 导出（pptx 自动内嵌微场景 GIF） |
| `scene_libs()` / `install_scene_lib(lib_id="")` / `remove_scene_lib(lib_id)` | 微场景库：列 / 下载 / 删 |
| `export_scene_gif(path, ...)` / `compose_scene_gif(path, frames, ...)` | 单场景抓帧导出 GIF / 现成帧合成 GIF |
| `element_types()` | 元素类型 + modelNote |

完整签名、返回结构、字段字典见 [`skill/references/`](skill/references/)：

- [api.md](skill/references/api.md) — API 完整签名与返回结构
- [element-schema.md](skill/references/element-schema.md) — 12 类元素的字段字典
- [export.md](skill/references/export.md) — 导出细节与依赖
- [design-recipes.md](skill/references/design-recipes.md) — 术语 / 排版 / 六套配色 / 版式 / 装饰 / 示意图构成
- [page-templates.md](skill/references/page-templates.md) — 底板 + 五类页型的逐元素坐标
- [sci-vector-drawing.md](skill/references/sci-vector-drawing.md) — 科研图与矢量绘图硬规范
- [vector-playbook.md](skill/references/vector-playbook.md) — 矢量能力用法手册
- [diagram-atlas.md](skill/references/diagram-atlas.md) — 跨领域原理图图谱

## 给 Agent 用：skill

[`skill/SKILL.md`](skill/SKILL.md) 是这套核心的**使用规则**。三条要点：

1. **落笔的就是 agent 自己**——核心不生成内容，元素 JSON 由 agent 写。
2. **「会动」的：HTML 一定动，PPTX 里微场景也动**——元素动画（`anim`）与微场景（`scene`）导 HTML 会跑；PPTX 里微场景由核心自动抓帧合成 GIF 内嵌，PDF / PNG / SVG 是静态帧（微场景取 `props.poster`）。
3. **素材只有工程内本地副本**——`import_asset` 后把 `relPath` 写进 `props.src`，随工程文件夹迁移。

## 自测

```bash
python tests/smoke.py
```

跑完整闭环：建工程 → 插 3 类元素 → 改 → 加页 → 导素材 → 层级 / 删除 → 导出 HTML / PPTX
（含微场景自动抓帧内嵌 GIF）→ 本地 UI 服务自检（`/api/ping`、`/api/call` 增改删、`/canvas` 预览）
→ 矢量图标库（分组 / 搜索 / 单色与多色插入），产物在 `_smoke_out/`（可删）。结尾打印 `SMOKE OK` 即通过。

## 作者

**赵佳乐** —— 中国科学院大学 计算机技术硕士

邮箱：andzhaojiale@163.com
