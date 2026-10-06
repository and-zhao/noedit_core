<p align="center"><img src="img/logo.svg" alt="NoEdit Core" width="96"></p>

<h1 align="center">NoEdit Core</h1>

<p align="center">
  <b>An Agent Skill for making PPT decks.</b><br>
  Install <code>noedit-core</code> into a skill-aware agent and just ask — the agent writes the element JSON, this skill renders and exports
  <b>pptx · pdf · html · png · svg</b>.
</p>

<p align="center">
  <b>English</b> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/export-pptx%20%7C%20pdf%20%7C%20png%20%7C%20svg%20%7C%20html-success?style=flat-square" alt="Export">
  <img src="https://img.shields.io/badge/icons-1800%2B-orange?style=flat-square" alt="Icons">
</p>

<p align="center">A <b>minimal PPT creation core</b>: build multi-page canvases (decks) with a plain Python package, and export to pptx / pdf / html / png / svg.</p>

<h2 align="center">NoEdit Core vs. NoEdit — which one do you need?</h2>

<table align="center">
  <tr>
    <th align="right"></th>
    <th align="center">NoEdit Core <sub>(this repo)</sub></th>
    <th align="center">NoEdit <sub>(full version)</sub></th>
  </tr>
  <tr>
    <td align="right"><b>What it is</b></td>
    <td>Open-source PPT <b>core</b> + <b>Agent Skill</b> — a plain Python package that you (or your agent) drive</td>
    <td>Ready-to-use <b>desktop app</b>, works out of the box</td>
  </tr>
  <tr>
    <td align="right"><b>AI writes the deck</b></td>
    <td>Not included — the agent writes the element JSON, this core renders and exports</td>
    <td>Built-in main agent + sub-agents generate the deck for you</td>
  </tr>
  <tr>
    <td align="right"><b>How to get it</b></td>
    <td><code>git clone</code>, then install <code>noedit-core</code> as a skill</td>
    <td><b>Download the installer</b> (link below)</td>
  </tr>
</table>

<p align="center">
  <a href="https://github.com/and-zhao/noedit_core/releases/download/v0.2.0/NoEdit-Setup-0.2.0.exe">
    <img src="https://img.shields.io/badge/%E2%AC%87%20DOWNLOAD%20NoEdit-FULL%20VERSION-2EA44F?style=for-the-badge&logoColor=white" alt="Download NoEdit full version" width="560">
  </a>
</p>

<p align="center">
  <sub>Windows installer · v0.2.0 · <a href="https://github.com/and-zhao/noedit_core/releases">all releases</a></sub>
</p>

**Highlights**

- Exports **pptx** with ultra-high fidelity — no distortion
- Preserves **editability** to the greatest extent
- **Micro-scenes** produce dynamic effects (a world first)
- A full set of **vector tools** plus a **1800+ vector library**, freeing PPTs from the "text + card + image" formula
- Powerful **scientific figure** capability: statistical charts, flowcharts, architecture diagrams, topology diagrams… all covered

**Scope**: project read/write, page & element CRUD, 20 chart types, vector graphics (shape / path / connector),
a **built-in vector icon library** (1800+ icons — search and insert as editable `path` elements), tables / code / math,
project-local assets, 5 export formats, and a **built-in browser editor** (start a local server, open it in the browser to
preview and edit element properties by clicking). Element animation (`anim`) and micro-scenes (`scene`):
**HTML always animates; micro-scenes animate inside PPTX too** (the core auto-captures frames and embeds a GIF), while
PDF / PNG / SVG take a static frame.

**Not included**: AI content generation (incl. scene code / cover frames), a global asset library, templates, screenshot
review, a desktop client. (The built-in JS libraries used by micro-scenes are **downloaded on demand into a local cache**;
see `install_scene_lib`.)

## Demo

<p align="center">
  <img src="img/NoEdit_core%E6%BC%94%E7%A4%BA%E5%9B%BE.png" alt="NoEdit Core demo" width="100%">
</p>

<p align="center">
  <img src="img/slide1.png" width="24%">
  <img src="img/slide2.png" width="24%">
  <img src="img/slide3.png" width="24%">
  <img src="img/slide4.png" width="24%">
</p>

## NoEdit · Full Version

> **NoEdit** is the full version of **NoEdit_core** — ready to use out of the box.

<p align="center">
  <a href="https://github.com/and-zhao/noedit_core/releases/download/v0.2.0/NoEdit-Setup-0.2.0.exe">
    <img src="https://img.shields.io/badge/%E2%AC%87%20DOWNLOAD%20NoEdit-FULL%20VERSION-2EA44F?style=for-the-badge&logoColor=white" alt="Download NoEdit full version" width="560">
  </a>
</p>

<p align="center">
  <sub>Windows installer · v0.2.0 · <a href="https://github.com/and-zhao/noedit_core/releases">all releases</a></sub>
</p>

Its architecture follows **MCP**, so it can serve PPT generation to external agents. Internally it uses a
**main agent + sub-agents** model, dramatically cutting PPT generation time and maximizing cache-hit efficiency
to save tokens.

**Full desktop version**

- Parallel sub-agent architecture for blazing-fast generation
- More token-efficient strategies
- Built-in professional agent assistant for one-on-one optimization
- Stronger manual editing and modification, with silky-smooth interaction
- A complete set of manual scientific-drawing tools and interactions
- Scientific figure tracing tool (AI + manual)
- Ready to use out of the box, with ultra-simple setup (compared with NoEdit_core)
- Visual asset management and templates
- Plugin system: develop and install your own plugins, configured flexibly
- Deeply customizable: tools, MCP, skills, workflows, teams, permissions, canvas settings… endless possibilities
- …and many more powerful features waiting for you to explore

<p align="center">
  <img src="img/%E8%BD%AF%E4%BB%B6%E5%85%A8%E8%B2%8C.png" alt="NoEdit desktop overview" width="100%">
</p>

<table>
  <tr>
    <td width="48%" valign="top">
      <img src="img/%E7%9F%A2%E9%87%8F%E5%BA%93.png" alt="Vector library" width="100%">
      <img src="img/%E5%B1%9E%E6%80%A7%E9%9D%A2%E6%9D%BF.png" alt="Properties panel" width="100%">
      <img src="img/%E4%B8%B4%E6%91%B9%E6%A8%A1%E5%BC%8F.png" alt="Tracing mode" width="100%">
    </td>
    <td width="52%" valign="top">
      <img src="img/%E6%8F%92%E4%BB%B6%E6%9C%BA%E5%88%B6.png" alt="Plugin system" width="100%">
    </td>
  </tr>
</table>

<h2 align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">Click to watch — the stunning results made with this project</a>
</h2>

<p align="center">
  <a href="https://www.bilibili.com/video/BV1hQHZ6uEiT">
    <img src="https://img.shields.io/badge/%E2%96%B6%20WATCH%20THE%20DEMO-BILIBILI-FB7299?style=for-the-badge&logo=bilibili&logoColor=white" alt="Watch the demo on Bilibili" width="440">
  </a>
</p>

<p align="center">
  <video src="img/NoEdit%E4%B8%80%E5%8F%A5%E8%AF%9D%E7%94%9F%E6%88%90ppt.mp4" controls width="720"></video>
</p>

## Project layout

```
noedit_core/
├─ main.py                 # CLI entry (python main.py <subcommand>)
├─ img/                    # README images (logo.svg, ...)
├─ noedit_core/
│  ├─ api.py               # Public API (the only module you need to import)
│  ├─ cli.py               # CLI implementation
│  ├─ server.py            # Local HTTP server (browser-UI backend: static assets + /api/call + /canvas preview)
│  ├─ ui/                  # Built-in browser UI (index.html + app.css + app.js + i18n.js)
│  └─ core/                # Core implementation: projects / export / actions / element_schema /
│                          #   assets / icon_catalog / shape_outline / connector_geom / store ...
│  └─ web/                 # Render-time assets: element-schema.json, icon-catalog*.json, render-kit, katex
├─ skill/                  # Agent Skill: how to use this core (SKILL.md + references/)
└─ tests/smoke.py          # End-to-end smoke test
```

## Requirements

- **Python 3.10+** (uses `X | Y` type syntax and `from __future__ import annotations`)
- Export dependencies:
  - `pptx` → **python-pptx** (required)
  - `pdf` / `png` / `svg` → a local **Edge or Chrome** (headless rendering)

```bash
pip install python-pptx
```

## Quick start

### Browser UI (start a server, then open it in the browser)

```bash
python main.py serve --project D:\work\report     # open http://127.0.0.1:8760/ after it starts
```

Without `--project`, open `http://127.0.0.1:8760/` first, then **create** or **open** a project folder on the landing page.

The UI provides: page / element lists, a canvas preview (click an element in the canvas to select it), a property panel
(edit x / y / w / h, text, color, font size, z-order, opacity, ...), add/remove elements and pages, import assets, and
export (HTML / PPTX / PDF / PNG / SVG). The preview uses the **same renderer as export**, so it is WYSIWYG; every change is
written to disk immediately and the preview refreshes. Data still lives in the same `project.manifest.json`, fully
interoperable with the API / CLI.

The interface is available in **Simplified Chinese / English / Japanese** (Chinese by default; the choice is remembered
locally). The "Pages" and "Elements" panels share the left column 50/50 by default and can be resized by dragging the
divider; the column widths can be dragged too (double-click a divider to restore the default), and both the columns and
the canvas zoom adapt to the window size. Scroll the wheel over the canvas to switch pages; with a project open, the
Create / Open panel can be dismissed by clicking the backdrop, clicking the close button, or pressing Esc.

#### Local UI HTTP endpoints

The server listens on loopback only and is **single-process, single-project**. Besides the pages above, it exposes a
small HTTP API so an agent (or another tool) can switch the current project and manage the project settings:

| Endpoint | Body | Returns |
| --- | --- | --- |
| `GET /api/ping` | — | `{"ok":true,"app":"..."}` (liveness probe) |
| `GET /api/ui/current` | — | `{"ok":true,"result":{"project":<dir>\|null,"name","type","port","url"}}` |
| `POST /api/ui/open` | `{"path":"<project dir>"}` (or `?path=`) | switches the running UI to that project — no restart |
| `POST /api/call` | `{"method":"<name>","args":[...]}` | `{"ok":true,"result":...}` or `{"ok":false,"message":"..."}` |
| `GET /canvas?page=<0-based>` | — | the current project's page rendered exactly like export |

`POST /api/call` handles a set of **project-settings / project-switch / directory-browsing** methods itself
(`ping`, `state`, `create_project`, `open_project`, `close_project`, `get_settings`, `set_default_dir`,
`browse_roots`, `browse_dir`, `upload_asset`); **every other method is forwarded to `noedit_core.api`** with the
project path as the first argument, e.g. `{"method":"insert","args":["D:\\work\\report", {...}, 0]}`.

The default directory (parent folder for new projects, directory-tree root, export destination) is persisted in
`data/settings.json`. A running server also publishes `data/ui.json` (`{app, version, host, port, url, pid, project,
startedAt}`) for discovery — probe it with `GET /api/ping`, since it may be stale after a forced kill.

Full signatures and return structures: [skill/references/api.md](skill/references/api.md) → "本地 UI 服务" section.

### CLI

```bash
python main.py create "Quarterly report" --dir D:\work
python main.py insert D:\work\report --json "{\"type\":\"text\",\"props\":{\"text\":\"Title\"}}"
python main.py export D:\work\report --fmt pptx
```

Every subcommand prints JSON; on error it prints the error and returns a non-zero exit code.

| Subcommand | Description |
| --- | --- |
| `serve [--host] [--port] [--project] [--open]` | Start the local UI server (open the URL in a browser to preview / edit) |
| `create <name> --dir <parent> [--preset] [--type]` | Create a project |
| `open <path>` | Overview + outline |
| `types` | List element types and modelNote |
| `pages <path>` / `add-page <path>` | List pages / add a page |
| `elements <path> [--page] [--full]` | List elements |
| `insert <path> --json <element JSON> [--page]` | Insert |
| `update <path> --props <dot-path JSON> [--id/--match]` | Update |
| `delete <path> [--id/--match]` | Delete |
| `reorder <path> [--index/--front/--back] [--id/--match]` | Z-order |
| `asset-add <path> <files...>` / `assets <path>` | Import / list assets |
| `icon-groups` / `icon-list <group> [--limit]` | Vector icons: list groups / list icons in a group |
| `icon-search [keyword] [--group] [--limit]` | Search vector icons (matches English name / id / Chinese group name) |
| `icon-insert <path> <icon-id> [--x/--y/--size/--color/--page]` | Insert an icon (creates an editable `path` element) |
| `export <path> [--fmt] [--out] [--pages] [--dpi] [--transparent] [--no-scene-gif]` | Export |
| `scene-libs` / `scene-lib-add [id]` / `scene-lib-remove <id>` | Micro-scene libraries: list / download / remove |
| `scene-gif <path> [--id/--match] [--fps] [--scale] [--opaque]` | Capture a single scene and export a GIF |

### Python

```python
import sys
sys.path.insert(0, r"D:\NoEdit\noedit_core")
from noedit_core import api

p = api.create_project("Quarterly report", r"D:\work")
path = p["path"]

# Page 1 (the blank page a new project ships with): write the cover
api.insert(path, {"type": "text", "x": 80, "y": 60, "w": 900, "h": 80,
                  "props": {"text": "2025 Q4 Review"},
                  "style": {"fontSize": 40, "fontWeight": "700"}}, page_index=0)

# Add page 2 and place an image
api.add_page(path, name="Data")
rec = api.import_asset(path, [r"D:\pics\chart.png"])["imported"][0]
api.insert(path, {"type": "image", "x": 80, "y": 100, "w": 500, "h": 300,
                  "props": {"src": rec["relPath"], "fit": "cover"}}, page_index=1)

api.export(path, "pptx")
```

## API overview

| Function | Purpose |
| --- | --- |
| `create_project(name, parent_dir, preset="ppt-16:9", ptype="ppt")` | Create a project |
| `open_project(path)` | Open: overview + outline + preview URL |
| `canvas(path)` / `list_pages(path)` / `add_page(path, ...)` | Canvas / pages |
| `update_page(path, props, ..., all_pages=False)` / `delete_page(path, index)` | Update page props (background / name) / delete a page |
| `list_elements(path, page_index=-1, full=False)` | List elements |
| `insert(path, element, page_index=0, ...)` | Insert an element |
| `update(path, props, element_id="", match=None, ...)` | Update (props use dot paths) |
| `delete(path, element_id="", match=None, ...)` / `reorder(path, ...)` | Delete / z-order |
| `import_asset(path, source_paths)` / `list_assets(path)` | Project-local assets |
| `icon_groups()` / `icon_list(group="", limit=200)` | Vector icons: group overview / list icons in a group |
| `icon_search(keyword="", group="", limit=40)` | Search vector icons |
| `icon_insert(path, icon_id, x=None, y=None, size=150, color="#2f6fed", ...)` | Insert an icon (monochrome → one `path`; multi-color → `group` container + layered members) |
| `export(path, fmt="pptx", out_dir="", scene_gifs=None, **options)` | Export (pptx auto-embeds micro-scene GIFs) |
| `scene_libs()` / `install_scene_lib(lib_id="")` / `remove_scene_lib(lib_id)` | Micro-scene libraries: list / download / remove |
| `export_scene_gif(path, ...)` / `compose_scene_gif(path, frames, ...)` | Capture a single scene to a GIF / compose a GIF from ready frames |
| `element_types()` | Element types + modelNote |

Full signatures, return shapes and field dictionaries: [`skill/references/`](skill/references/)

- [api.md](skill/references/api.md) — full API signatures and return shapes
- [element-schema.md](skill/references/element-schema.md) — field dictionary for the 12 element types
- [export.md](skill/references/export.md) — export details and dependencies
- [design-recipes.md](skill/references/design-recipes.md) — terminology / typography / six palettes / layouts / decoration / diagram composition
- [page-templates.md](skill/references/page-templates.md) — base board + per-element coordinates for five page types
- [sci-vector-drawing.md](skill/references/sci-vector-drawing.md) — hard rules for scientific figures and vector drawing
- [vector-playbook.md](skill/references/vector-playbook.md) — practical guide to the vector capabilities
- [diagram-atlas.md](skill/references/diagram-atlas.md) — cross-domain diagram atlas

## Use it as an Agent Skill

This repo is packaged as a self-contained **Agent Skill** named `noedit-core`. Install it into a
skill-aware agent and the agent builds the deck for you — it writes the element JSON and drives the
CLI / API itself.

**Install**

Option 1 — let your agent install it from the release package. Hand it this link and say "install this skill":

```
https://github.com/and-zhao/noedit_core/releases/download/v0.2.0/noedit-core-skill.zip
```

The agent downloads the archive, finds the single `noedit-core/` folder containing `SKILL.md`, and
installs it under its global skills root (e.g. `~/.trae-cn/skills/noedit-core/`).

Option 2 — build the package yourself:

```bash
python packaging/build_skill.py     # → dist/noedit-core/  +  dist/noedit-core-skill.zip
```

Either way, the whole `noedit-core/` folder goes under your skills root:

- global: `~/.trae-cn/skills/noedit-core/`
- project-level: `<project>/.trae/skills/noedit-core/`

Keep the folder name `noedit-core` — it must match the `name` in the `SKILL.md` frontmatter. Runtime
data (`settings.json` / `ui.json` / locks) goes to `~/.noedit_core/`; the default project folder sits
next to the skill folder. Override with `NOEDIT_CORE_ROOT` / `NOEDIT_CORE_PROJECTS`.

**Use it** — once installed, just tell the agent what you want (e.g. "make a 10-page deck about X and
export pptx"); it follows [`skill/SKILL.md`](skill/SKILL.md) by itself. Three rules worth knowing:

1. **You (the agent) write the content** — the core does not generate content; the element JSON is written by the agent.
2. **What "moves": HTML always animates, and micro-scenes animate inside PPTX too** — element animation (`anim`) and micro-scenes (`scene`) run in exported HTML; inside PPTX the core auto-captures frames and embeds a GIF; PDF / PNG / SVG are a static frame (micro-scenes use `props.poster`).
3. **Assets are project-local copies only** — after `import_asset`, write the `relPath` into `props.src`; it travels with the project folder.

## Self-test

```bash
python tests/smoke.py
```

Runs the full loop: create a project → insert 3 element types → update → add a page → import assets → z-order / delete →
export HTML / PPTX (incl. the auto-captured GIF for micro-scenes) → local UI server self-check (`/api/ping`, `/api/call`
add/update/delete, `/canvas` preview) → vector icon library (groups / search / monochrome & multi-color insert). Output goes
to `_smoke_out/` (safe to delete). It prints `SMOKE OK` on success.

## Author

**Zhao Jiale (赵佳乐)** — Master of Computer Technology, University of Chinese Academy of Sciences

Email: andzhaojiale@163.com
